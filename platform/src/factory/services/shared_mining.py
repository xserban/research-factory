"""The shared mining store: a read-only projection across projects (slice M rulings 18-20).

Invariants:
- Events stay per project. The store is a projection of every project under the root, rebuildable
  at any time; nothing but `SharedStore` writes it, and no project's replay ever reads it.
- No document text enters it (I9, R-47): keys, hashes, pass identities and statuses only.
- Status is computed at sync through each source's own services (`settled_rows`,
  `stale_extractions`), after syncing the source's own index; the source's log is never written.
- A sync is incremental per event file: a project whose files have not grown is not opened. A
  project that grew is read from its offsets and its records are computed again, since any event
  (an amendment, a new document version, a screening decision) can change a record's status.
- A project with a `.no-share` file offers nothing. A source that cannot be read is skipped and
  reported, and keeps its old rows, which no lookup offers.
- Lock order: nothing here runs inside a project's `index.exclusive()`. `sync` takes the store's
  lock and then each source's, and a project's lock is never held while the store's is awaited.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import Engine, MetaData, create_engine, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from factory.canonical import canonical_json
from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.document.anchors import Manifest
from factory.errors import (
    FactoryError,
    FactoryValidationError,
    ProjectNotFoundError,
    ValidationIssue,
)
from factory.events.envelope import Actor, Event
from factory.events.reader import event_files, read_file, relative_name
from factory.index.shared import (
    NON_STATE_TABLES,
    SHARED_PROJECTION_VERSION,
    STATUS_OK,
    SharedFold,
    SharedTables,
    clear_project,
    mark_unreadable,
    opt_out_project,
    replace_project,
    set_meta,
    shared_tables,
)
from factory.mining.compile import compile_miner
from factory.mining.kinds import kind_checks
from factory.mining.spec import MinerSpec, spec_to_json
from factory.model.extraction import (
    ExtractionRecorded,
    FieldInput,
    MinerScope,
    StoredField,
)
from factory.model.mine_imports import (
    MAX_ITEMS,
    ImportedItem,
    ImportedPass,
    MineImported,
    SourceStatus,
)
from factory.model.miners import ImportedFrom, MinerRegistered
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project, ProjectPaths, list_projects, open_project
from factory.services.conversions import conversion_manifest, conversion_of
from factory.services.extraction import (
    ExtraCheck,
    ExtractionRow,
    ExtraVerdict,
    ImportItem,
    UnitPin,
    filled_imports,
    import_items,
    mined_works,
    scope_rows,
    stale_extractions,
)
from factory.services.extraction_agreement import SettledRow, settled_rows
from factory.services.extraction_verify import RowVerdict, verify_row_in
from factory.services.mining import (
    MinerRow,
    calibration_sample,
    register_miner,
    registered_miner,
    registered_miners,
    registered_row,
    require_listed,
    require_not_retired,
)
from factory.services.protocol import current_protocol
from factory.services.results import BatchResult, ItemError
from factory.services.search import list_works

__all__ = [
    "OPT_OUT_FILE",
    "SharedProject",
    "SharedStore",
    "SharedSyncResult",
    "SharedUnit",
    "SourceState",
    "available_units",
    "content_hash",
    "field_digest",
    "held_conversions",
    "mine_import",
    "register_from",
    "reopened_works",
    "shared_store",
    "source_state",
    "source_superseded",
    "unverified_imports",
]

OPT_OUT_FILE = ".no-share"
"""A file of this name in a project's directory keeps it out of the store (plan ruling 1)."""
_SYNC_SESSION = "shared-store"
_VERSION_KEY = "version"
_BATCH = 1000
_UNREADABLE = (FactoryError, SQLAlchemyError, OSError, ValueError, KeyError)
"""What reading a source may raise: a damaged or newer log, a locked or older index, a bad blob."""


@dataclass(frozen=True)
class SharedSyncResult:
    """`projects` folded or found unchanged, `applied` new events read, `skipped` each project left
    out with why (`<slug>: opted out` or `<slug>: unreadable`)."""

    projects: int
    applied: int
    skipped: list[str]


@dataclass(frozen=True)
class SharedProject:
    """One project as the store knows it, for `factory shared status`."""

    slug: str
    status: str
    records: int
    last_event_id: str | None


def content_hash(markdown_hash: str, manifest_hash: str) -> str:
    """The identity of a conversion across projects: a conversion id is minted per project, so two
    projects hold one conversion when its Markdown and its manifest hash alike."""
    return hashlib.sha256(f"{markdown_hash}\n{manifest_hash}".encode()).hexdigest()


def field_digest(stored: StoredField) -> str:
    """SHA-256 of the canonical stored field: compares fields without holding their text."""
    return hashlib.sha256(canonical_json(stored.model_dump(mode="json"))).hexdigest()


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _row_meta(project: Project, name: str) -> dict[str, tuple[str, str | None]]:
    """Per extraction of miner `name`: its schema reference and the model that recorded it."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.extraction_id, r.schema_ref, e.model FROM extraction_rows r "
                "JOIN events e ON e.id = r.event_id WHERE r.scope = :s"
            ),
            {"s": name},
        ).all()
    return {str(i): (str(ref), None if m is None else str(m)) for i, ref, m in rows}


def _status(
    key: tuple[str, str],
    rows: list[tuple[ExtractionRow, bool]],
    final: SettledRow | None,
    dropped: frozenset[tuple[str, str]],
    stale: set[str],
) -> str:
    """The status of one record: its final status, else why it no longer stands."""
    if final is not None:
        return final.final.status
    live = [row for row, is_live in rows if is_live]
    if not live or key in dropped:
        return "superseded"
    return "stale" if any(row.extraction_id in stale for row in live) else "pending"


def _digests(
    rows: list[tuple[ExtractionRow, bool]],
    final: SettledRow | None,
    by_id: Mapping[str, ExtractionRow],
) -> dict[str, str]:
    """The digest of each field of the record: of the row each final field came from, else of its
    newest row's."""
    if final is not None:
        return {
            name: field_digest(by_id[f.extraction_id].fields[name])
            for name, f in final.final.fields.items()
            if f.extraction_id in by_id and name in by_id[f.extraction_id].fields
        }
    return {name: field_digest(stored) for name, stored in rows[-1][0].fields.items()}


def _miner_records(
    project: Project, name: str, versions: Mapping[int, MinerRow], last_event: str
) -> list[dict[str, object]]:
    """The records of miner `name`: one per `(version, conversion, work, row key)`, superseded and
    stale ones included, so a source's correction reaches the importers."""
    scope = MinerScope(name)
    rows = scope_rows(project, scope)
    stale = stale_extractions(project, scope=scope)
    settled, dropped = settled_rows(project, scope=scope)
    meta = _row_meta(project, name)
    finals = {(s.final.work_id, s.final.row_key): s for s in settled}
    by_id = {row.extraction_id: row for row, _ in rows}
    groups: dict[tuple[int, str, str, str], list[tuple[ExtractionRow, bool]]] = {}
    for row, live in rows:
        ref = meta.get(row.extraction_id, ("", None))[0].rpartition("@")[2]
        if ref.isdigit() and int(ref) in versions:
            key = (int(ref), row.conversion_id, row.work_id, row.row_key)
            groups.setdefault(key, []).append((row, live))
    out: list[dict[str, object]] = []
    for (version, conversion, work, row_key), group in sorted(groups.items()):
        final = finals.get((work, row_key))
        if final is not None and final.final.conversion_id != conversion:
            final = None  # the same key under another conversion is that conversion's record
        kept = [row for row, live in group if live] or [row for row, _ in group]
        out.append(
            {
                "project": project.paths.slug,
                "miner": name,
                "version": version,
                "digest": versions[version].digest,
                "conversion_id": conversion,
                "work_id": work,
                "row_key": row_key,
                "status": _status((work, row_key), group, final, dropped, stale),
                "extraction_ids": _dumps(sorted(r.extraction_id for r in kept)),
                "pass_labels": _dumps(sorted({r.pass_label.value for r in kept})),
                "models": _dumps(
                    sorted({m for r in kept if (m := meta[r.extraction_id][1]) is not None})
                ),
                "field_digests": _dumps(_digests(group, final, by_id)),
                "source_last_event": last_event,
            }
        )
    return out


def _conversions(project: Project, ids: set[str]) -> list[dict[str, object]]:
    """The content hash of each conversion the project's records pin."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT conversion_id, markdown_hash, manifest_hash FROM document_conversions")
        ).all()
    return [
        {
            "project": project.paths.slug,
            "conversion_id": str(conversion),
            "content_hash": content_hash(str(markdown), str(manifest)),
        }
        for conversion, markdown, manifest in sorted(rows)
        if str(conversion) in ids
    ]


def _imports(project: Project) -> list[dict[str, object]]:
    """The project's own `mine.imported` events, as its projection folded them."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT i.import_id, i.source_project, i.miner, i.version, i.digest, "
                "(SELECT COUNT(*) FROM mine_import_items m WHERE m.import_id = i.import_id) "
                "FROM mine_imports i ORDER BY i.import_id"
            )
        ).all()
    return [
        {
            "project": project.paths.slug,
            "import_id": str(ident),
            "source_project": str(source),
            "miner": str(miner),
            "version": int(version),
            "digest": str(digest),
            "items": int(items),
        }
        for ident, source, miner, version, digest, items in rows
    ]


def _read_source(project: Project, offsets: Mapping[str, int]) -> SharedFold:
    """What `project` contributes, through its own services. Syncs its index; writes no event."""
    project.index.sync()
    last_event = project.index.last_event_id() or ""
    registered = registered_miners(project)
    by_name: dict[str, dict[int, MinerRow]] = {}
    for row in registered:
        by_name.setdefault(row.name, {})[row.version] = row
    records = [
        record
        for name, versions in sorted(by_name.items())
        for record in _miner_records(project, name, versions, last_event)
    ]
    return SharedFold(
        last_event_id=last_event or None,
        offsets=offsets,
        miners=[
            {
                "project": project.paths.slug,
                "name": row.name,
                "version": row.version,
                "digest": row.digest,
                "miner_id": row.miner_id,
            }
            for row in registered
        ],
        conversions=_conversions(project, {str(r["conversion_id"]) for r in records}),
        records=records,
        imports=_imports(project),
    )


class SharedStore:
    """The shared projection of every project under `settings.root`."""

    def __init__(self, settings: Settings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock
        self._path = settings.shared_store_path
        self._metadata = MetaData()
        self._tables: SharedTables = shared_tables(self._metadata)

    @property
    def tables(self) -> SharedTables:
        return self._tables

    def _engine(self) -> Engine:
        """A fresh engine: another process may have rebuilt the file since the last call."""
        return create_engine(f"sqlite:///{self._path}", poolclass=NullPool)

    @contextmanager
    def _locked(self, *, shared: bool = False) -> Iterator[None]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with (self._path.parent / "lock").open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _stored_version(self, engine: Engine) -> str | None:
        if not self._path.exists():
            return None
        with engine.connect() as conn:
            found = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shared_meta'"
            ).first()
            if found is None:
                return None
            meta = self._tables.meta
            value = conn.execute(
                select(meta.c.value).where(meta.c.key == _VERSION_KEY)
            ).scalar_one_or_none()
        return None if value is None else str(value)

    def available(self) -> bool:
        """Whether the store exists at this schema version; a read never creates it."""
        if not self._path.exists():
            return False
        engine = self._engine()
        try:
            with self._locked(shared=True):
                return self._stored_version(engine) == SHARED_PROJECTION_VERSION
        except SQLAlchemyError:
            return False
        finally:
            engine.dispose()

    def sync(self) -> SharedSyncResult:
        """Fold what changed since the last sync, or rebuild a store that cannot be trusted."""
        with self._locked():
            engine = self._engine()
            try:
                if self._stored_version(engine) != SHARED_PROJECTION_VERSION:
                    return self._build()
                return self._fold_all(engine)
            finally:
                engine.dispose()

    def rebuild(self) -> str:
        """Rebuild the store from every project's log and return its state hash."""
        with self._locked():
            self._build()
            return self._hash()

    def state_hash(self) -> str:
        with self._locked(shared=True):
            return self._hash()

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        """A connection for reading; services must not write through it."""
        engine = self._engine()
        try:
            with self._locked(shared=True), engine.connect() as conn:
                yield conn
        finally:
            engine.dispose()

    def projects(self) -> list[SharedProject]:
        """Every project the store knows of, by slug, with how many records it holds."""
        with self.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT p.slug, p.status, p.last_event_id, "
                    "(SELECT COUNT(*) FROM shared_records r WHERE r.project = p.slug) "
                    "FROM shared_projects p ORDER BY p.slug"
                )
            ).all()
        return [
            SharedProject(str(slug), str(status), int(count), None if last is None else str(last))
            for slug, status, last, count in rows
        ]

    def _build(self) -> SharedSyncResult:
        """A fresh store. The caller holds the lock; the version is written last, so a failed
        build is rebuilt by the next sync."""
        for path in self._with_sidecars():
            path.unlink(missing_ok=True)
        engine = self._engine()
        try:
            self._metadata.create_all(engine)
            result = self._fold_all(engine)
            with engine.begin() as conn:
                set_meta(conn, self._tables, _VERSION_KEY, SHARED_PROJECTION_VERSION)
            return result
        finally:
            engine.dispose()

    def _with_sidecars(self) -> tuple[Path, Path]:
        return self._path, self._path.with_name(self._path.name + "-journal")

    def _fold_all(self, engine: Engine) -> SharedSyncResult:
        slugs = list_projects(self._settings)
        t = self._tables
        with engine.begin() as conn:
            known = {str(s) for s in conn.execute(select(t.projects.c.slug)).scalars()}
            for gone in sorted(known - set(slugs)):
                clear_project(conn, t, gone)
        applied = 0
        skipped: list[str] = []
        for slug in slugs:
            paths = ProjectPaths(self._settings.root, slug)
            if (paths.dir / OPT_OUT_FILE).exists():
                with engine.begin() as conn:
                    opt_out_project(conn, t, slug)
                skipped.append(f"{slug}: opted out")
                continue
            try:
                applied += self._fold_project(engine, slug, paths)
            except _UNREADABLE:
                with engine.begin() as conn:
                    mark_unreadable(conn, t, slug)
                skipped.append(f"{slug}: unreadable")
        return SharedSyncResult(projects=len(slugs), applied=applied, skipped=skipped)

    def _fold_project(self, engine: Engine, slug: str, paths: ProjectPaths) -> int:
        """Fold one project when its files changed; the number of new events read."""
        t = self._tables
        with engine.connect() as conn:
            known: dict[str, int] = {
                str(f): int(o)
                for f, o in conn.execute(
                    select(t.sync_state.c.file, t.sync_state.c.offset).where(
                        t.sync_state.c.project == slug
                    )
                )
            }
            status = conn.execute(
                select(t.projects.c.status).where(t.projects.c.slug == slug)
            ).scalar_one_or_none()
        files = {relative_name(p, paths.events_dir): p for p in event_files(paths.events_dir)}
        sizes = {name: path.stat().st_size for name, path in files.items()}
        if status == STATUS_OK and sizes == known:
            return 0
        project = open_project(self._settings, slug, session=_SYNC_SESSION, clock=self._clock)
        rewritten = any(name not in sizes or sizes[name] < end for name, end in known.items())
        applied = 0
        offsets: dict[str, int] = {}
        for name, path in files.items():
            start = 0 if rewritten else known.get(name, 0)
            if start == sizes[name]:
                offsets[name] = start  # nothing appended: this file is not opened
                continue
            result = read_file(path, project.catalog, start)
            applied += len(result.events)
            offsets[name] = result.end_offset
        fold = _read_source(project, offsets)
        with engine.begin() as conn:
            replace_project(conn, t, slug, fold)
        return applied

    def _hash(self) -> str:
        digest = hashlib.sha256()
        tables = sorted(
            (t for t in self._metadata.tables.values() if t.name not in NON_STATE_TABLES),
            key=lambda t: t.name,
        )
        engine = self._engine()
        try:
            with engine.connect() as conn:
                for table in tables:
                    digest.update(f"{table.name}\n".encode())
                    result = conn.execute(select(table).order_by(*table.primary_key.columns))
                    while rows := result.fetchmany(_BATCH):
                        for row in rows:
                            digest.update(canonical_json(dict(row._mapping)) + b"\n")
        finally:
            engine.dispose()
        return f"sha256:{digest.hexdigest()}"


def shared_store(settings: Settings, clock: Clock | None = None) -> SharedStore:
    """The store of `settings`; nothing is created until it is synced."""
    return SharedStore(settings, SystemClock() if clock is None else clock)


# --- Lookup ---

MAX_PAGE_SIZE = 1000


@dataclass(frozen=True)
class SharedUnit:
    """An importable unit: the source's `(work_id, conversion_id)` of one miner version, and the
    importer's own copy of that conversion. `status` is its final rows' common status, `mixed` when
    they differ; `dual` says every row is agreed by two passes."""

    project: str
    miner: str
    version: int
    digest: str
    work_id: str
    conversion_id: str
    local_conversion_id: str
    status: Literal["agreed", "resolved", "single", "mixed"]
    rows: int
    dual: bool


def held_conversions(project: Project) -> dict[str, str]:
    """The conversions `project` holds, content hash to conversion id: those of a live document
    whose Markdown and manifest are in its own library. Of two with one hash, the newest."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.conversion_id, c.markdown_hash, c.manifest_hash "
                "FROM document_conversions c JOIN fulltext_documents d "
                "ON d.document_id = c.document_id WHERE d.superseded_by IS NULL "
                "ORDER BY c.event_id"
            )
        ).all()
    return {
        content_hash(str(markdown), str(manifest)): str(conversion)
        for conversion, markdown, manifest in rows
        if project.library.exists(str(markdown)) and project.library.exists(str(manifest))
    }


_UNITS_SQL = """
SELECT r.project, r.work_id, r.conversion_id, c.content_hash,
       SUM(r.status = 'agreed'), SUM(r.status = 'resolved'), SUM(r.status = 'single')
FROM shared_records r
JOIN shared_conversions c ON c.project = r.project AND c.conversion_id = r.conversion_id
JOIN shared_projects p ON p.slug = r.project
WHERE r.miner = :miner AND r.version = :version AND r.digest = :digest
  AND p.status = :ok AND r.project != :importer AND (:source IS NULL OR r.project = :source)
  AND c.content_hash IN (SELECT value FROM json_each(:hashes))
GROUP BY r.project, r.work_id, r.conversion_id, c.content_hash
HAVING SUM(r.status IN ('stale', 'pending')) = 0
   AND SUM(r.status IN ('agreed', 'resolved', 'single')) > 0
ORDER BY r.project, r.work_id, r.conversion_id
LIMIT :limit OFFSET :offset
"""


def _unit_status(
    agreed: int, resolved: int, single: int
) -> Literal["agreed", "resolved", "single", "mixed"]:
    if resolved == 0 and single == 0:
        return "agreed"
    if agreed == 0 and single == 0:
        return "resolved"
    return "single" if agreed == 0 and resolved == 0 else "mixed"


def available_units(
    store: SharedStore,
    importer: Project,
    miner: str,
    version: int,
    digest: str,
    *,
    source: str | None = None,
    page: int = 0,
    page_size: int = 200,
) -> list[SharedUnit]:
    """One page of the units of `(miner, version, digest)` that `importer` could import, by source,
    work and conversion: of another project, on a conversion the importer's library holds, every
    live record final. A superseded record is history and does not count; a stale or pending one
    keeps its unit out, since a unit is imported whole. Empty when the store is not built. Reads
    the store as it stands: the caller syncs it. Raises on `page` and `page_size` out of range."""
    if page < 0 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise FactoryValidationError(
            [ValidationIssue("page_size", f"page >= 0 and page_size in 1..{MAX_PAGE_SIZE}")]
        )
    held = held_conversions(importer)
    if not held or not store.available():
        return []
    with store.connect() as conn:
        rows = conn.execute(
            text(_UNITS_SQL),
            {
                "miner": miner,
                "version": version,
                "digest": digest,
                "ok": STATUS_OK,
                "importer": importer.paths.slug,
                "source": source,
                "hashes": json.dumps(sorted(held)),
                "limit": page_size,
                "offset": page * page_size,
            },
        ).all()
    return [
        SharedUnit(
            project=str(slug),
            miner=miner,
            version=version,
            digest=digest,
            work_id=str(work),
            conversion_id=str(conversion),
            local_conversion_id=held[str(hashed)],
            status=_unit_status(int(agreed), int(resolved), int(single)),
            rows=int(agreed) + int(resolved) + int(single),
            dual=int(resolved) == 0 and int(single) == 0,
        )
        for slug, work, conversion, hashed, agreed, resolved, single in rows
    ]


# --- Import ---

IMPORT_UNVERIFIED = "mine-import-unverified"
"""The reason of a row that did not re-verify; the check of that name finds the same in a log."""
_NOT_FINAL = "the source unit is not final"
_NOT_HELD = "this project does not hold this conversion"
_NOT_OFFERED = "the source has no such unit of this miner version"
_MINED_HERE = "this unit is mined in this project"
_CALIBRATION = "this unit is in the miner's calibration sample"
_TOO_LARGE = f"a unit of more than {MAX_ITEMS} rows cannot be imported"


@dataclass(frozen=True)
class _SourceRow:
    """A final row as the source's log holds it. `fields` is empty when the log lacks one."""

    row_key: str
    status: SourceStatus
    extraction_ids: tuple[str, ...]
    fields: Mapping[str, StoredField]
    passes: tuple[ImportedPass, ...]


@dataclass(frozen=True)
class _SourceUnit:
    work_id: str
    conversion_id: str
    hashed: str | None
    rows: tuple[_SourceRow, ...]
    final: bool
    """False when a live row of the unit is not final: a unit is imported whole (plan ruling 4)."""


def _recorded(source: Project, wanted: set[str]) -> dict[str, tuple[ExtractionRecorded, Event]]:
    """The `extraction.recorded` events of `wanted`, read from the source's log itself: the values
    an import carries are the log's, never the index's text form."""
    out: dict[str, tuple[ExtractionRecorded, Event]] = {}
    for path in event_files(source.paths.events_dir):
        for event in read_file(path, source.catalog).events:
            if event.type != "extraction.recorded":
                continue
            ident = event.payload.get("extraction_id")
            if ident in wanted:
                try:
                    out[str(ident)] = (ExtractionRecorded.model_validate(event.payload), event)
                except ValidationError:
                    continue  # left out: the row then fails re-verification
    return out


def _source_row(
    settled: SettledRow, recorded: Mapping[str, tuple[ExtractionRecorded, Event]]
) -> _SourceRow:
    final = settled.final
    fields: dict[str, StoredField] = {}
    for name, cell in final.fields.items():
        found = recorded.get(cell.extraction_id)
        stored = None if found is None else found[0].fields.get(name)
        if stored is None:
            fields = {}
            break
        fields[name] = stored
    try:
        passes = tuple(
            ImportedPass(
                pass_label=recorded[i][0].pass_label,
                session=recorded[i][1].actor.session,
                model=recorded[i][1].actor.model,
            )
            for i in settled.extraction_ids
            if i in recorded
        )
    except ValidationError:
        passes = ()  # the row then fails re-verification
    return _SourceRow(final.row_key, final.status, settled.extraction_ids, fields, passes)


def _source_units(source: Project, miner: str, version: int) -> dict[tuple[str, str], _SourceUnit]:
    """The units of `(miner, version)` in `source`, by `(work_id, conversion_id)`, read through its
    own services. Only rows mined there: an import is not re-exported."""
    scope = MinerScope(miner)
    source.index.sync()
    settled, dropped = settled_rows(source, scope=scope)
    meta = _row_meta(source, miner)
    ref = f"{miner}@{version}"
    kept = [s for s in settled if all(meta[i][0] == ref for i in s.extraction_ids if i in meta)]
    recorded = _recorded(source, {i for s in kept for i in s.extraction_ids})
    rows: dict[tuple[str, str], list[_SourceRow]] = {}
    for one in kept:
        key = (one.final.work_id, one.final.conversion_id)
        rows.setdefault(key, []).append(_source_row(one, recorded))
    settled_ids = {i for s in settled for i in s.extraction_ids}
    open_units = {
        (row.work_id, row.conversion_id)
        for row, live in scope_rows(source, scope)
        if live
        and row.extraction_id not in settled_ids
        and (row.work_id, row.row_key) not in dropped
        and meta.get(row.extraction_id, ("", None))[0] == ref
    }
    out: dict[tuple[str, str], _SourceUnit] = {}
    for key in sorted({*rows, *open_units}):
        conversion = conversion_of(source, key[1])
        hashed = (
            None
            if conversion is None
            else content_hash(conversion.markdown_hash, conversion.manifest_hash)
        )
        out[key] = _SourceUnit(
            key[0], key[1], hashed, tuple(rows.get(key, ())), key not in open_units
        )
    return out


def _open_source(project: Project, slug: str) -> Project:
    """The source project, opened in the importer's session. Refused on `source`."""
    refused = FactoryValidationError([ValidationIssue("source", f"no source project {slug!r}")])
    if slug == project.paths.slug:
        raise FactoryValidationError(
            [ValidationIssue("source", "a project does not import from itself")]
        )
    try:
        source = open_project(project.settings, slug, session=project.session, clock=project.clock)
    except ProjectNotFoundError:
        raise refused from None
    if (source.paths.dir / OPT_OUT_FILE).exists():
        raise refused
    return source


def register_from(
    project: Project, actor: Actor, source: str, name: str, version: int
) -> MinerRegistered:
    """Register in `project` the spec `source` registered as `(name, version)`, recording where it
    came from (`imported_from`). Refused on `source` for an unknown or opted-out project and on
    `miner` for a version the source does not hold, and as `register_miner`."""
    origin = _open_source(project, source)
    spec = registered_miner(origin, name, version)
    row = registered_row(origin, name, version)
    if spec is None or row is None:
        raise FactoryValidationError(
            [ValidationIssue("miner", f"{source} has no miner {name} version {version}")]
        )
    return register_miner(
        project,
        actor,
        spec_to_json(spec),
        imported_from=ImportedFrom(project=source, digest=row.digest),
    )


def _refused(index: int, field: str, reason: str) -> ItemError:
    return ItemError(index=index, issues=[ValidationIssue(field, reason)])


@dataclass(frozen=True)
class _Importer:
    """What every unit of one import is judged against, read once under the importer's lock."""

    project: Project
    spec: MinerSpec
    held: Mapping[str, str]
    corpus: frozenset[str]
    mined: frozenset[str]
    calibration: frozenset[str]


def _reverified(
    project: Project,
    spec: MinerSpec,
    pin: UnitPin,
    fields: Mapping[str, StoredField],
    manifest: Manifest,
    corpus: frozenset[str],
    extra: ExtraCheck,
) -> tuple[RowVerdict, ExtraVerdict | None]:
    """Stored fields judged as a mined row is, against this project's conversion and corpus: what
    the platform computed is dropped and computed again. The kind checks run only on a verified
    row, so their verdict is None otherwise."""
    given = {
        name: FieldInput(**stored.model_dump(exclude={"canonical", "copy_marker"}))
        for name, stored in fields.items()
    }
    declared = tuple(f.name for f in spec.fields)
    verdict = verify_row_in(
        compile_miner(spec), declared, given, pin.conversion_id, manifest, corpus
    )
    return verdict, None if verdict.fields is None else extra(project, pin, verdict.fields, ())


def _unit_items(
    importer: _Importer, unit: _SourceUnit, import_id: str
) -> tuple[list[ImportedItem], list[ValidationIssue]]:
    """The items of `unit`, each row re-verified against the importer's own conversion by the
    verifiers a mined row passes, or why the whole unit is refused. Reasons are fixed; no document
    text enters them."""
    project, spec = importer.project, importer.spec
    local = None if unit.hashed is None else importer.held.get(unit.hashed)
    conversion = None if local is None else conversion_of(project, local)
    if conversion is None:
        return [], [ValidationIssue("conversion_id", _NOT_HELD)]
    if not unit.final or not unit.rows:
        return [], [ValidationIssue("units", _NOT_FINAL)]
    if len(unit.rows) > MAX_ITEMS:
        return [], [ValidationIssue("units", _TOO_LARGE)]
    work = conversion.work_id
    if work in importer.mined:
        return [], [ValidationIssue("units", _MINED_HERE)]
    if work in importer.calibration:
        return [], [ValidationIssue("units", _CALIBRATION)]
    try:
        manifest = conversion_manifest(project, conversion.conversion_id)
    except FactoryValidationError as exc:
        return [], exc.issues
    extra = kind_checks(spec)
    pin = UnitPin(
        import_id,
        work,
        PassLabel.A,
        MinerScope(spec.name),
        conversion.document_id,
        conversion.conversion_id,
    )
    items: list[ImportedItem] = []
    issues: list[ValidationIssue] = []
    keys: set[str] = set()
    for row in unit.rows:
        where = f"rows.{row.row_key}"
        if not row.fields or not row.passes:
            issues.append(ValidationIssue(where, IMPORT_UNVERIFIED))
            continue
        verdict, checked = _reverified(
            project, spec, pin, row.fields, manifest, importer.corpus, extra
        )
        if verdict.fields is None or verdict.row_key is None or checked is None or checked.issues:
            found = verdict.issues if checked is None else checked.issues
            issues += [
                ValidationIssue(f"{where}.{i.field}", f"{IMPORT_UNVERIFIED}: {i.reason}")
                for i in found
            ]
            continue
        if verdict.row_key in keys:
            issues.append(ValidationIssue(where, f"{IMPORT_UNVERIFIED}: duplicate row"))
            continue
        keys.add(verdict.row_key)
        try:
            items.append(
                ImportedItem(
                    extraction_id=project.ids.new("ext"),
                    work_id=work,
                    document_id=conversion.document_id,
                    conversion_id=conversion.conversion_id,
                    row_key=verdict.row_key,
                    fields=verdict.fields,
                    cited=checked.cited,
                    source_extraction_ids=row.extraction_ids,
                    source_conversion_id=unit.conversion_id,
                    source_row_key=row.row_key,
                    source_status=row.status,
                    source_passes=row.passes,
                    source_field_digests={n: field_digest(f) for n, f in row.fields.items()},
                )
            )
        except ValidationError:
            issues.append(ValidationIssue(where, IMPORT_UNVERIFIED))
    return ([], issues) if issues else (items, [])


def _chosen(
    offered: Mapping[tuple[str, str], _SourceUnit],
    units: Sequence[tuple[str, str]] | None,
    held: Mapping[str, str],
) -> list[tuple[tuple[str, str], _SourceUnit | None]]:
    """The units of this import in order. Without `units`, every offered unit whose conversion the
    importer holds; a named unit the source does not offer stays, as None, to be refused."""
    if units is None:
        return [(k, u) for k, u in offered.items() if u.hashed in held]
    return [(key, offered.get(key)) for key in units]


def mine_import(
    project: Project,
    actor: Actor,
    source: str,
    miner: str,
    version: int,
    units: Sequence[tuple[str, str]] | None = None,
    *,
    channel: Channel = Channel.CLI,
) -> BatchResult[str]:
    """Import whole units of `(miner, version)` from `source` (ruling 19); `units` names them by the
    source's `(work_id, conversion_id)`, None takes every unit on a conversion this project holds.
    `written` holds `<work_id>@<conversion_id>` of each imported unit, in this project's ids.

    Refused, with nothing written: for an agent (`actor`: a human act, relayed over MCP by a human
    actor); on `source` for this project, an unknown one or one that opted out; on `protocol` and
    `miners` as `require_listed`, which holds a built-in miner too, since no `MinerUse` can allow
    its import; on `miners` when the use is `deny`; on `miner` for a retired version; on `digest`
    unless the source registers the same digest.

    Each unit is judged alone: an `ItemError` at its position refuses it when this project does not
    hold its conversion, the unit is not final in the source, it is mined here or drawn into a
    calibration, or any row fails re-verification (`mine-import-unverified`). The others are
    written, as one or more `mine.imported` events in one append.

    The source is read before this project's lock is taken and never under it, so two imports in
    opposite directions cannot wait on each other."""
    if actor.kind == "agent":
        raise FactoryValidationError(
            [ValidationIssue("actor", "an import is a human act; an agent relays it")]
        )
    origin = _open_source(project, source)
    _, use, _ = require_listed(project, miner, version)
    if use.imports == "deny":
        raise FactoryValidationError(
            [ValidationIssue("miners", f"the protocol declines imports of {miner}")]
        )
    require_not_retired(project, miner, version)
    theirs = registered_row(origin, miner, version)
    ours = registered_row(project, miner, version)
    if theirs is None or ours is None or theirs.digest != ours.digest:
        raise FactoryValidationError(
            [ValidationIssue("digest", f"{source} does not register this digest of {miner}")]
        )
    offered = _source_units(origin, miner, version)
    with project.index.exclusive():
        project.index.sync()
        protocol, use, spec = require_listed(project, miner, version)
        if use.imports == "deny":
            raise FactoryValidationError(
                [ValidationIssue("miners", f"the protocol declines imports of {miner}")]
            )
        require_not_retired(project, miner, version)
        importer = _Importer(
            project=project,
            spec=spec,
            held=held_conversions(project),
            corpus=frozenset(w.id for w in list_works(project)),
            mined=frozenset(mined_works(project, MinerScope(miner))),
            calibration=frozenset(calibration_sample(project, miner)),
        )
        written: list[str] = []
        rejected: list[ItemError] = []
        batches: list[list[ImportedItem]] = [[]]
        import_ids = [project.ids.new("mim")]
        for index, (_, unit) in enumerate(_chosen(offered, units, importer.held)):
            if unit is None:
                rejected.append(_refused(index, "units", _NOT_OFFERED))
                continue
            items, issues = _unit_items(importer, unit, import_ids[-1])
            if issues:
                rejected.append(ItemError(index=index, issues=issues))
                continue
            if len(batches[-1]) + len(items) > MAX_ITEMS:
                batches.append([])
                import_ids.append(project.ids.new("mim"))
            batches[-1].extend(items)
            written.append(f"{items[0].work_id}@{items[0].conversion_id}")
        events = [
            project.events.make(
                "mine.imported",
                MineImported(
                    import_id=import_id,
                    source_project=source,
                    miner=miner,
                    version=version,
                    digest=ours.digest,
                    protocol_id=protocol.protocol_id,
                    channel=channel,
                    items=tuple(batch),
                ),
                actor,
                refs=(import_id, ours.miner_id),
            )
            for import_id, batch in zip(import_ids, batches, strict=True)
            if batch
        ]
        if events:
            project.record(events)
    return BatchResult[str](written=written, rejected=rejected)


# --- Corrections in the source, and imports that do not verify ---


@dataclass(frozen=True)
class SourceState:
    """What the store says of the imported rows in use, by extraction id. `superseded`: the source
    record is superseded, stale, dropped or gone. `unavailable`: its source project disappeared,
    opted out or cannot be read. `store_missing`: there is no store to ask, so nothing is known."""

    superseded: tuple[str, ...]
    unavailable: tuple[str, ...]
    store_missing: bool


def _rows_in_use(project: Project) -> list[ExtractionRow]:
    """The imported rows in use, of every miner the protocol lists, by extraction id."""
    protocol = current_protocol(project)
    uses = () if protocol is None else protocol.spec.miners or ()
    rows = [
        row
        for use in uses
        for unit in filled_imports(project, MinerScope(use.name)).values()
        for row in unit
    ]
    return sorted(rows, key=lambda r: r.extraction_id)


def _corrected(item: ImportItem, found: tuple[str, str, str], entry: ImportedItem | None) -> bool:
    """Whether the store's record is no longer what was imported: superseded or stale, or its rows
    changed (a correction that kept the row key), or a field's digest differs. A pending record
    counts as changed when its rows differ."""
    status, ids_json, digests_json = found
    if status in ("superseded", "stale"):
        return True
    if not set(item.source_extraction_ids) <= set(json.loads(ids_json)):
        return True
    if entry is None or status == "pending":
        return False
    now = json.loads(digests_json)
    return any(now.get(name) != digest for name, digest in entry.source_field_digests.items())


def source_state(project: Project, store: SharedStore | None = None) -> SourceState:
    """The state of each imported row's source, read from the store as it stands: nothing is
    synced and nothing written, in this project or the store. A row of a source the store reads
    fine and no longer lists counts as superseded. Nothing here changes what the importer holds
    (ruling 20): only a re-import or re-mining does."""
    rows = _rows_in_use(project)
    if not rows:
        return SourceState((), (), False)
    shared = shared_store(project.settings, project.clock) if store is None else store
    if not shared.available():
        return SourceState((), (), True)
    items = import_items(project)
    logged = _logged_items(project, set(items))
    superseded: list[str] = []
    unavailable: list[str] = []
    with shared.connect() as conn:
        statuses = {
            str(slug): str(status)
            for slug, status in conn.execute(text("SELECT slug, status FROM shared_projects"))
        }
        for row in rows:
            item = items.get(row.extraction_id)
            if item is None:
                continue
            events = ProjectPaths(project.settings.root, item.source_project).events_dir
            if statuses.get(item.source_project) != STATUS_OK or not events.is_dir():
                unavailable.append(row.extraction_id)
                continue
            found = conn.execute(
                text(
                    "SELECT status, extraction_ids, field_digests FROM shared_records "
                    "WHERE miner = :m AND version = :v "
                    "AND digest = :d AND conversion_id = :c AND project = :p AND row_key = :k"
                ),
                {
                    "m": item.miner,
                    "v": item.version,
                    "d": item.digest,
                    "c": item.source_conversion_id,
                    "p": item.source_project,
                    "k": item.source_row_key,
                },
            ).one_or_none()
            if found is None or _corrected(
                item, (str(found[0]), str(found[1]), str(found[2])), logged.get(row.extraction_id)
            ):
                superseded.append(row.extraction_id)
    return SourceState(tuple(superseded), tuple(unavailable), False)


def source_superseded(project: Project, store: SharedStore | None = None) -> list[str]:
    """The imported extraction ids whose source record is now superseded, stale or corrected.
    A source that disappeared is not one: its rows are self-contained and stay, and `check`
    reports it as unavailable (`source_state`). Read-only; empty without a store."""
    return sorted(source_state(project, store).superseded)


def reopened_works(project: Project, name: str) -> frozenset[str]:
    """The works of miner `name` an import fills whose source was corrected: `mine_next` queues
    them, which is how a project re-mines instead of re-importing."""
    filled = filled_imports(project, MinerScope(name))
    if not filled:
        return frozenset()
    flagged = set(source_superseded(project))
    return frozenset(
        work for work, rows in filled.items() if any(r.extraction_id in flagged for r in rows)
    )


def _logged_items(project: Project, wanted: set[str]) -> dict[str, ImportedItem]:
    """The items of `wanted` as this project's log holds them: a value's original type, which the
    projection's text form loses."""
    out: dict[str, ImportedItem] = {}
    for path in event_files(project.paths.events_dir):
        for event in read_file(path, project.catalog).events:
            if event.type != "mine.imported":
                continue
            try:
                payload = MineImported.model_validate(event.payload)
            except ValidationError:
                continue  # never folded
            out.update({i.extraction_id: i for i in payload.items if i.extraction_id in wanted})
    return out


def unverified_imports(project: Project) -> list[str]:
    """The imported rows in use that do not re-verify against this project's own conversion: the
    tools never write one, so this guards a replayed, hand-edited log, which the projection cannot
    judge as it reads no library. A conversion that cannot be read counts as not verified."""
    rows = _rows_in_use(project)
    if not rows:
        return []
    items = import_items(project)
    logged = _logged_items(project, {row.extraction_id for row in rows})
    corpus = frozenset(w.id for w in list_works(project))
    out: list[str] = []
    for row in rows:
        item, entry = items.get(row.extraction_id), logged.get(row.extraction_id)
        spec = None if item is None else registered_miner(project, item.miner, item.version)
        if entry is None or spec is None:
            out.append(row.extraction_id)
            continue
        pin = UnitPin(
            row.task_id,
            row.work_id,
            PassLabel.A,
            MinerScope(spec.name),
            row.document_id,
            row.conversion_id,
        )
        try:
            manifest = conversion_manifest(project, row.conversion_id)
            verdict, checked = _reverified(
                project, spec, pin, entry.fields, manifest, corpus, kind_checks(spec)
            )
        except FactoryError:
            out.append(row.extraction_id)
            continue
        if verdict.row_key != row.row_key or checked is None or checked.issues:
            out.append(row.extraction_id)
    return out
