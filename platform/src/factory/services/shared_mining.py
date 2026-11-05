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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import Engine, MetaData, create_engine, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from factory.canonical import canonical_json
from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
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
from factory.model.extraction import MinerScope, StoredField
from factory.services.context import Project, ProjectPaths, list_projects, open_project
from factory.services.extraction import ExtractionRow, scope_rows, stale_extractions
from factory.services.extraction_agreement import SettledRow, settled_rows
from factory.services.mining import MinerRow, registered_miners

__all__ = [
    "OPT_OUT_FILE",
    "SharedProject",
    "SharedStore",
    "SharedSyncResult",
    "SharedUnit",
    "available_units",
    "content_hash",
    "field_digest",
    "held_conversions",
    "shared_store",
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
