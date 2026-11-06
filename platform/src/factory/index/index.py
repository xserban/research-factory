import fcntl
import hashlib
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import JsonValue
from sqlalchemy import Engine, Table, create_engine, insert, select
from sqlalchemy import event as sa_event
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.catalog import EventCatalog
from factory.events.envelope import Event
from factory.events.reader import event_files, read_file, relative_name
from factory.index.projection import Projection

NON_STATE_TABLES: frozenset[str] = frozenset(
    {
        "meta",
        "sync_state",
        # Lookup tables derived from works and merges, which the hash already covers.
        "work_keys",
        "work_title_buckets",
        "merge_members",
        # One row per event ref, derived from the events table, which the hash covers.
        "event_refs",
        # The event that recorded each audit sample, derived from the events table.
        "audit_events",
    }
)
OMITTED_WHEN_EMPTY: frozenset[str] = frozenset(
    {
        "watch_cycles",
        "gate_audits",
        "gate_audit_items",
        "watch_cycle_sources",
        "watch_cycle_runs",
        "imports",
        "import_records",
        "import_decisions",
        "import_admission_queries",
        "import_attachments",
        "import_descriptions",
        "audit_top_ups",
        "snapshots",
        "notices",
        "version_observations",
        "version_links",
        "work_aliases",
        "notice_assessments",
        "document_preferences",
        "relations",
        "ideas",
        "idea_members",
        "idea_merges",
        "graph_nodes",
        "graph_edges",
        "conclusions",
        "digests",
        "properties",
        "property_merges",
        "cards",
        "card_assertions",
        "card_props",
        "interpretations",
        "interpretation_sources",
        "interpretation_reviews",
        "layer_nodes",
        "layer_edges",
        "concepts",
        "concept_aliases",
        "concept_definitions",
        "concept_reviews",
        "concept_quotes",
        "concept_source_decisions",
        "concept_uses",
        "concept_merges",
        "contradictions",
        "regions",
        "region_definitions",
        "region_snapshots",
        "region_members",
        "region_reviews",
        "region_member_decisions",
        "miners",
        "leads",
        "lead_triggers",
        "lead_keys",
        "hypotheses",
        "hypothesis_reviews",
        "hypothesis_registrations",
        "model_cutoffs",
        "region_member_proposals",
        "region_links",
        "labels",
        "label_merges",
        "terms",
        "term_aliases",
        "consolidation_passes",
        "consolidation_proposals",
        "consolidation_decisions",
        "miner_calibrations",
        "miner_calibration_units",
        "miner_calibration_labels",
        "miner_calibration_label_sessions",
        "manuscripts",
        "manuscript_sentences",
        "manuscript_citations",
        "manuscript_closures",
        "manuscript_verdicts",
        "manuscript_flags",
        "manuscript_audits",
        "manuscript_audit_items",
        "mine_imports",
        "mine_import_items",
        "experiments",
        "experiment_amendments",
        "experiment_deviations",
        "xruns",
        "baseline_evaluations",
        "hypothesis_evaluations",
        "directions",
        "direction_keys",
        "drafts",
        "draft_sections",
        "draft_sentences",
        "sentence_supports",
        "sentence_flags",
        "sentence_stats",
        "sentence_verdicts",
        "draft_audits",
        "draft_audit_items",
        "draft_releases",
        "project_hosts",
        "briefings_served",
    }
)
"""Tables added after slice 3: while empty they leave no trace in the hash, so a log without
their events keeps the state hash it had before they existed."""

_PROJECTION_VERSION = "projection_version"
_LAST_EVENT_ID = "last_event_id"


@dataclass(frozen=True)
class SyncResult:
    applied: int
    rebuilt: bool


class Index:
    """The SQLite projection. Written only here; services read it through `connect()`."""

    def __init__(
        self,
        db_path: Path,
        events_dir: Path,
        catalog: EventCatalog,
        projection: Projection,
        *,
        on_exclusive: Callable[[str | None], None] | None = None,
    ) -> None:
        self._db_path = db_path
        self._events_dir = events_dir
        self._catalog = catalog
        self._projection = projection
        self._engine = _make_engine(db_path)
        self._identity = _file_identity(db_path)
        self._holding = False
        self._on_exclusive = on_exclusive

    def sync(self) -> SyncResult:
        """Apply new events incrementally, or rebuild when the index can't be trusted."""
        with self._locked():
            return self._sync()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the write lock across several reads and writes, so none can interleave.

        Re-entrant: the sync and reads made inside the block do not wait on the lock they hold.
        With `on_exclusive`, the outermost hold syncs first and hands it the last applied event id
        (the ID floor of a hosted project, slice 5 ruling 3).
        """
        outermost = not self._holding
        with self._locked():
            if outermost and self._on_exclusive is not None:
                self._sync()
                self._on_exclusive(self.last_event_id())
            yield

    def rebuild(self) -> str:
        """Rebuild the projection from the event log and return its state hash."""
        with self._locked():
            self._build()
            return self._state_hash()

    @contextmanager
    def _locked(self, *, shared: bool = False) -> Iterator[None]:
        """Hold the cross-process lock, with an engine on the current DB file.

        Writers take it exclusively; readers share it so they wait for any rebuild in progress.
        Limit: the hold is per instance, ignores `shared` once held, and is not thread-safe.
        """
        if self._holding:
            yield
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with (self._db_path.parent / "lock").open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            self._holding = True
            try:
                self._refresh_engine()
                yield
            finally:
                self._holding = False
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _refresh_engine(self) -> None:
        """Replace the engine if another process swapped in a new DB file."""
        identity = _file_identity(self._db_path)
        if identity is not None and identity != self._identity:
            self._engine.dispose()
            self._engine = _make_engine(self._db_path)
            self._identity = identity

    def _sync(self) -> SyncResult:
        if not self._db_path.exists():
            return self._rebuilt()
        stored = self._read_stored()
        if stored is None:
            return self._rebuilt()
        meta, known = stored
        if meta.get(_PROJECTION_VERSION) != self._projection.version:
            return self._rebuilt()

        current = {
            _relative(path, self._events_dir): path for path in event_files(self._events_dir)
        }
        unchanged: set[str] = set()
        for name, offset in known.items():
            path = current.get(name)
            if path is None:
                return self._rebuilt()
            size = path.stat().st_size
            if size < offset:
                return self._rebuilt()
            if size == offset:
                unchanged.add(name)

        new: list[Event] = []
        offsets: dict[str, int] = {}
        for name, path in current.items():
            if name in unchanged:  # nothing appended since the last sync: skip opening it
                continue
            result = read_file(path, self._catalog, known.get(name, 0))
            new.extend(result.events)
            offsets[name] = result.end_offset
        if not new:
            return SyncResult(applied=0, rebuilt=False)

        new.sort(key=lambda event: event.id)
        if new[0].id <= meta.get(_LAST_EVENT_ID, ""):
            # An event sorts before one already applied: incremental folding would be wrong.
            return self._rebuilt()

        with self._engine.begin() as conn:
            self._write(conn, new, offsets)
            self._set_meta(conn, _LAST_EVENT_ID, new[-1].id)
        return SyncResult(applied=len(new), rebuilt=False)

    def last_event_id(self) -> str | None:
        """The greatest event id folded into the index, or None while it is empty."""
        meta = self._table("meta")
        with self.connect() as conn:
            value = conn.execute(
                select(meta.c.value).where(meta.c.key == _LAST_EVENT_ID)
            ).scalar_one_or_none()
        return None if value is None else str(value)

    def head(self) -> str | None:
        """The id of the last event the projector applied (the sync cursor), after syncing; None
        for an empty log. Reads one `meta` row, so it is cheap at any size."""
        self.sync()
        return self.last_event_id()

    def state_hash(self) -> str:
        with self._locked(shared=True):
            return self._state_hash()

    def _state_hash(self) -> str:
        """The projection's hash. Callers hold the lock (shared or exclusive) already."""
        digest = hashlib.sha256()
        tables = sorted(
            (
                table
                for table in self._projection.metadata.tables.values()
                if table.name not in NON_STATE_TABLES
            ),
            key=lambda table: table.name,
        )
        with self._engine.connect() as conn:
            for table in tables:
                query = select(table).order_by(*table.primary_key.columns)
                rows = conn.execute(query).all()
                if not rows and table.name in OMITTED_WHEN_EMPTY:
                    continue
                digest.update(f"{table.name}\n".encode())
                for row in rows:
                    row_data: dict[str, Any] = dict(row._mapping)
                    digest.update(canonical_json(row_data) + b"\n")
        return f"sha256:{digest.hexdigest()}"

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        """A connection for read access; services must not write through it.

        The shared lock is held until the context exits, so a rebuild cannot swap the file under it.
        """
        with self._locked(shared=True), self._engine.connect() as conn:
            yield conn

    def _rebuilt(self) -> SyncResult:
        return SyncResult(applied=self._build(), rebuilt=True)

    def _build(self) -> int:
        """Build a fresh DB beside the live one, then atomically swap it in."""
        events, offsets = self._read_everything()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._db_path.with_name(f"{self._db_path.name}.tmp-{os.getpid()}")
        _remove_files(*_with_sidecars(tmp))

        engine = _make_engine(tmp)
        try:
            self._projection.metadata.create_all(engine)
            with engine.begin() as conn:
                self._write(conn, events, offsets)
                self._set_meta(conn, _PROJECTION_VERSION, self._projection.version)
                if events:
                    self._set_meta(conn, _LAST_EVENT_ID, events[-1].id)
        except BaseException:
            engine.dispose()
            _remove_files(*_with_sidecars(tmp))
            raise
        engine.dispose()

        # Cached connections must not hold the old file open across the swap.
        self._engine.dispose()
        _remove_files(*_sidecars(self._db_path))
        os.replace(tmp, self._db_path)
        self._engine = _make_engine(self._db_path)
        self._identity = _file_identity(self._db_path)
        return len(events)

    def _read_everything(self) -> tuple[list[Event], dict[str, int]]:
        events: list[Event] = []
        offsets: dict[str, int] = {}
        for path in event_files(self._events_dir):
            result = read_file(path, self._catalog)
            events.extend(result.events)
            offsets[_relative(path, self._events_dir)] = result.end_offset
        events.sort(key=lambda event: event.id)
        return events, offsets

    def _read_stored(self) -> tuple[dict[str, str], dict[str, int]] | None:
        with self._engine.connect() as conn:
            # Cheaper than `inspect(conn).has_table("meta")`, which builds an inspector per sync.
            has_meta = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
            ).first()
            if has_meta is None:
                return None
            meta = {
                key: value
                for key, value in conn.execute(
                    select(self._table("meta").c.key, self._table("meta").c.value)
                )
            }
            known = {
                file: offset
                for file, offset in conn.execute(
                    select(self._table("sync_state").c.file, self._table("sync_state").c.offset)
                )
            }
        return meta, known

    def _write(self, conn: Connection, events: list[Event], offsets: dict[str, int]) -> None:
        events_table = self._table("events")
        refs_table = self._table("event_refs")
        for event in events:
            conn.execute(insert(events_table).values(**_event_row(event)))
            if event.refs:
                conn.execute(
                    insert(refs_table),
                    [
                        {"event_id": event.id, "position": i, "ref": ref, "type": event.type}
                        for i, ref in enumerate(event.refs)
                    ],
                )
            handler = self._projection.handlers.get(event.type)
            if handler is not None:
                handler(conn, event)

        state_table = self._table("sync_state")
        for file, offset in sorted(offsets.items()):
            stmt = sqlite_insert(state_table).values(file=file, offset=offset)
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["file"], set_={"offset": stmt.excluded.offset}
                )
            )

    def _set_meta(self, conn: Connection, key: str, value: str) -> None:
        meta_table = self._table("meta")
        stmt = sqlite_insert(meta_table).values(key=key, value=value)
        conn.execute(
            stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        )

    def _table(self, name: str) -> Table:
        return self._projection.metadata.tables[name]


def _make_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @sa_event.listens_for(engine, "connect")
    def _enable_wal(dbapi_connection: Any, _record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def _event_row(event: Event) -> dict[str, JsonValue]:
    refs: list[JsonValue] = [*event.refs]
    return {
        "id": event.id,
        "ts": format_ts(event.ts),
        "type": event.type,
        "actor_kind": event.actor.kind,
        "actor_id": event.actor.id,
        "user": event.actor.user,
        "session": event.actor.session,
        "model": event.actor.model,
        "skill": event.actor.skill,
        "input_blob": event.input_blob,
        "refs": canonical_json(refs).decode(),
    }


def _file_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino


def _relative(path: Path, events_dir: Path) -> str:
    return relative_name(path, events_dir)


def _sidecars(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    )


def _with_sidecars(path: Path) -> tuple[Path, Path, Path]:
    wal, shm = _sidecars(path)
    return path, wal, shm


def _remove_files(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
