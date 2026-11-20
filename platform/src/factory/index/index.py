import fcntl
import hashlib
import os
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import JsonValue
from sqlalchemy import Engine, Table, create_engine, insert, select
from sqlalchemy import event as sa_event
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from factory.canonical import canonical_json
from factory.clock import format_ts, parse_ts
from factory.errors import FactoryError
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
        # Lookups for budget consumption, derived from events and tasks, which the hash covers.
        "task_claims",
        "source_requests",
        "request_starts",
    }
)
OMITTED_WHEN_EMPTY: frozenset[str] = frozenset(
    {
        # Taxonomy, mining request and work layer tables (IDEA-50 T1): an old log has none.
        "taxonomies",
        "taxonomy_proposals",
        "mining_requests",
        "mining_request_works",
        "work_layer_moves",
        "ledger_confirmations",
        "dedup_pair_decisions",
        "budgets",
        "task_usage",
        "appraisal_answers",
        "appraisal_judgements",
        "appraisal_closures",
        "appraisal_audits",
        "appraisal_audit_items",
        "watch_cycles",
        "grey_searches",
        "grey_contacts",
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
        "stage_judges",
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
        "check_draws",
        "check_items",
        "check_labels",
        "idea_merges",
        "graph_nodes",
        "graph_edges",
        "conclusions",
        "digests",
        "curation_proposals",
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
        "registered_files",
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
        "rankings",
        "ranking_positions",
        "core_works",
        "feed_configs",
        "feed_fetches",
        "feed_entries",
        "feed_rankings",
        "feed_reactions",
        "feed_sends",
        "runner_runs",
        "runner_pipelines",
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
        "region_adoptions",
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
        "mine_reopenings",
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
        "project_visibility",
        "members",
        "member_events",
        "reviews",
        "fulltext_adoptions",
        "library_source_confirmations",
        "decision_sets",
        "decision_items",
        "document_renders",
        "reference_layer_schemes",
        "reference_layers",
        "reference_layer_labels",
        # Spar sheets, answers, chat requests and argument checks (added 2026-11-18 to 11-20): an
        # old log has none, so they leave the hash while empty (old log replay).
        "sheets",
        "sheet_arguments",
        "sheet_balances",
        "sheet_candidates",
        "sheet_ratings",
        "answers",
        "answer_ratings",
        "answer_sentences",
        "argument_checks",
        "chat_requests",
        "spar_coverage",
        "spar_readings",
        "spar_roles",
    }
)
"""Tables added after slice 3: while empty they leave no trace in the hash, so a log without
their events keeps the state hash it had before they existed."""

_PROJECTION_VERSION = "projection_version"
_LAST_EVENT_ID = "last_event_id"
# The holder marker (IDEA-62): which process of `projection_version` last built or synced the
# index, and when. `meta` is outside the state hash, so the marker never changes it.
_HOLDER_PID = "holder_pid"
_HOLDER_HOST = "holder_host"
_HOLDER_CODE = "holder_code"
_HELD_AT = "held_at"

DEFAULT_HOLD_WINDOW = timedelta(minutes=10)
"""How long a version's hold on the index lasts after its last build or sync (IDEA-62)."""
_MAX_REFRESH = timedelta(seconds=60)


class IndexHeldError(FactoryError):
    """This process's projection version may not rebuild the index now: another code line holds
    it (IDEA-62). Nothing was written; the events are untouched."""


@dataclass(frozen=True)
class Holder:
    """The marker an index carries: the version that last built or synced it, by whom, and when."""

    version: str
    pid: int | None
    host: str | None
    code: str | None
    held_at: datetime | None


def code_path() -> str:
    """Where this process's code lives: the worktree for a `platform/src` checkout, else the
    directory of the installed `factory` package."""
    package = Path(__file__).resolve().parent.parent
    src = package.parent
    if src.name == "src" and src.parent.name == "platform":
        return str(src.parent.parent)
    return str(package)


def _version_key(version: str) -> int | None:
    return int(version) if version.isascii() and version.isdigit() else None


def holder_blocks(
    holder: Holder,
    version: str,
    *,
    now: datetime,
    window: timedelta,
    pid: int,
    host: str,
    alive: Callable[[int], bool],
) -> bool:
    """Whether `holder` forbids a process running projection `version` to rebuild the index.

    The open question of IDEA-62, decided here: inside the window an older version never
    rebuilds over a newer one, and a newer version always may (the newer code is where the line
    is heading; the older process is the stray one). Versions that are not both integers have no
    order, so each refuses the other inside the window.

    Never blocks: the same version; an unmarked index (built before the marker existed); a hold
    older than `window` (a holder that crashed on another host ages out); this very process; a
    holder on this host whose process is gone (a crash frees the index at once); a zero window; a
    `held_at` more than a window ahead of `now` (clock skew or a damaged value must not hold the
    index for ever).
    """
    if holder.version == version or holder.held_at is None or window <= timedelta(0):
        return False
    age = now - holder.held_at
    if age >= window or -age > window:
        return False
    if (
        holder.host == host
        and holder.pid is not None
        and (holder.pid == pid or not alive(holder.pid))
    ):
        return False
    mine, theirs = _version_key(version), _version_key(holder.version)
    return not (mine is not None and theirs is not None and mine > theirs)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, owned by another user
    return True


def _holder(meta: dict[str, str]) -> Holder | None:
    version = meta.get(_PROJECTION_VERSION)
    if version is None:
        return None
    pid = meta.get(_HOLDER_PID)
    held_at = meta.get(_HELD_AT)
    try:
        when = parse_ts(held_at) if held_at is not None else None
    except (ValueError, TypeError, OverflowError):
        when = None
    if when is not None and when.utcoffset() is None:
        when = None  # a naive time cannot be compared; an unmarked index holds nothing
    return Holder(
        version=version,
        pid=int(pid) if pid is not None and pid.isascii() and pid.isdigit() else None,
        host=meta.get(_HOLDER_HOST),
        code=meta.get(_HOLDER_CODE),
        held_at=when,
    )


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
        on_write_lock: Callable[[], None] | None = None,
        hold_window: timedelta = DEFAULT_HOLD_WINDOW,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """`hold_window` is how long another version's last build or sync keeps this one from
        rebuilding (IDEA-62, `holder_blocks`); `now` is the clock the marker is read and written
        with."""
        self._hold_window = hold_window
        self._now = now
        self._pid = os.getpid()
        self._host = socket.gethostname()
        self._code = code_path()
        self._db_path = db_path
        self._events_dir = events_dir
        self._catalog = catalog
        self._projection = projection
        self._engine = _make_engine(db_path)
        self._identity = _file_identity(db_path)
        self._threads = threading.Lock()  # one thread of this process holds the file lock
        self._owner: int | None = None  # that thread's ident while it holds it
        self._snapshot = False  # set and read only by the owner
        self._clean = False  # owner only: the index holds the whole log, for this hold
        self._frozen: ContextVar[bool] = ContextVar("index_frozen", default=False)
        self._on_exclusive = on_exclusive
        self._on_write_lock = on_write_lock

    def sync(self) -> SyncResult:
        """Apply new events incrementally, or rebuild when the index can't be trusted.

        Inside `snapshot()` it applies nothing: the snapshot synced on entry and holds only the
        shared lock, under which this process must not write.
        """
        if self._in_snapshot() or self._frozen.get():
            return SyncResult(applied=0, rebuilt=False)
        with self._locked():
            if self._clean:
                return SyncResult(applied=0, rebuilt=False)
            result = self._sync()
            self._clean = True
            return result

    def appended(self) -> None:
        """Tell the index its own process just appended to the log, so the next `sync()` reads it.
        While a hold lasts, a `sync()` after one that found the log fully applied reads nothing
        (no other writer can append under the write lock); every append inside a hold calls this."""
        self._clean = False

    @contextmanager
    def frozen_sync(self) -> Iterator[None]:
        """Sync once, then make `sync()` a no-op until the block exits, without holding any lock.

        For a long read-only build (the hub) whose services each call `sync()`: every call scans
        the event files, which costs about 30 ms on the pilot and was repeated hundreds of times.
        Invariant: the build reads the log as of the one sync; events appended meanwhile are seen
        by the next build. Nested blocks reuse the outer one. Only this thread's context is frozen.
        """
        if self._frozen.get():
            yield
            return
        self.sync()
        token = self._frozen.set(True)
        try:
            yield
        finally:
            self._frozen.reset(token)

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Sync once, then hold the shared lock across many reads (a read-only view such as the
        dashboard), so each `connect()` inside does not queue again behind writers.

        Invariant: nothing is written inside; nested `sync()` is a no-op and `exclusive()` is
        refused. Writers wait until the block exits, so keep it short.
        """
        if self._holding:
            yield
            return
        self.sync()
        with self._locked(shared=True):
            self._snapshot = True
            try:
                yield
            finally:
                self._snapshot = False

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the write lock across several reads and writes, so none can interleave.

        Re-entrant: the sync and reads made inside the block do not wait on the lock they hold.
        With `on_exclusive`, the outermost hold syncs first and hands it the last applied event id
        (the ID floor of a hosted project, slice 5 ruling 3). `on_write_lock` then runs, once per
        outermost hold, after the lock is won (`build_project` wires it to `call_memo.invalidate`).
        """
        if self._in_snapshot():
            raise RuntimeError("exclusive() inside a read-only snapshot")
        outermost = not self._holding
        with self._locked():
            if outermost:
                if self._on_exclusive is not None:
                    self._sync()
                    self._on_exclusive(self.last_event_id())
                if self._on_write_lock is not None:
                    # After a possible wait: values derived before the lock may be stale.
                    self._on_write_lock()
            yield

    def rebuild(self) -> str:
        """Rebuild the projection from the event log and return its state hash."""
        with self._locked():
            self._build()
            self._clean = False
            return self._state_hash()

    @property
    def _holding(self) -> bool:
        """Whether the calling thread holds the lock (re-entry is per thread, not per instance)."""
        return self._owner == threading.get_ident()

    def _in_snapshot(self) -> bool:
        return self._holding and self._snapshot

    @contextmanager
    def _locked(self, *, shared: bool = False) -> Iterator[None]:
        """Hold the cross-process lock, with an engine on the current DB file.

        Writers take it exclusively; readers share it so they wait for any rebuild in progress.
        Threads of one process take turns on an in-process lock first: `flock` is per open file
        description, so it cannot order threads, and re-entry is granted only to the owning
        thread (a threaded server shares one instance). Limits: two instances on one file in one
        process deadlock; `shared` is ignored once held; threads of one process never share a hold
        (a snapshot also makes other threads wait). Never wait on another thread that needs this
        index while holding it (inside `snapshot`, `exclusive` or `on_exclusive`): it deadlocks.
        """
        if self._holding:
            yield
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._threads, (self._db_path.parent / "lock").open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            self._owner = threading.get_ident()
            self._clean = False
            try:
                self._refresh_engine()
                yield
            finally:
                self._owner = None
                self._clean = False
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def reopen(self) -> None:
        """Point this instance at the DB file now on disk, after it was replaced by copy.

        Invariant: one project has one `Index` per process. The lock hold lives on the instance, so
        a second `Index` on the same file does not see a hold taken through the first and would
        wait on it forever. Whoever swaps the file refreshes the engine here; it never builds a
        second instance (the writer's host guard and the ID floor are wired to this one).
        """
        with self._locked():
            self._engine.dispose()
            self._engine = _make_engine(self._db_path)
            self._identity = _file_identity(self._db_path)

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
            self._refresh_hold(meta)
            return SyncResult(applied=0, rebuilt=False)

        new.sort(key=lambda event: event.id)
        if new[0].id <= meta.get(_LAST_EVENT_ID, ""):
            # An event sorts before one already applied: incremental folding would be wrong.
            return self._rebuilt()

        with self._engine.begin() as conn:
            self._write(conn, new, offsets)
            self._set_meta(conn, _LAST_EVENT_ID, new[-1].id)
            self._mark_holder(conn, _holder(meta))
        return SyncResult(applied=len(new), rebuilt=False)

    def holder(self) -> Holder | None:
        """The marker of the index on disk, or None when there is no index or no version yet."""
        with self._locked(shared=True):
            return self._stored_holder()

    def _stored_holder(self) -> Holder | None:
        if not self._db_path.exists():
            return None
        try:
            stored = self._read_stored()
        except DBAPIError:
            return None  # an unreadable index is rebuilt; it holds nothing
        return None if stored is None else _holder(stored[0])

    def _guard(self) -> Holder | None:
        """Refuse to rebuild while another code line holds the index (IDEA-62, `holder_blocks`);
        otherwise return the stored marker. Callers hold the write lock."""
        holder = self._stored_holder()
        if holder is None or not holder_blocks(
            holder,
            self._projection.version,
            now=self._now(),
            window=self._hold_window,
            pid=self._pid,
            host=self._host,
            alive=_pid_alive,
        ):
            return holder
        assert holder.held_at is not None  # holder_blocks is False without it
        until = format_ts(holder.held_at + self._hold_window)
        raise IndexHeldError(
            f"index {self._db_path} is held by projection version {holder.version} "
            f"(process {holder.pid} on {holder.host}, code {holder.code}, last at "
            f"{format_ts(holder.held_at)}); this process runs version "
            f"{self._projection.version} from {self._code} and will not rebuild over it before "
            f"{until}. Point this session at the shared runtime (docs/runbook-living.md)."
        )

    def _refresh_hold(self, meta: dict[str, str]) -> None:
        """Renew this version's hold when it is older than a minute (or half the window), so an
        index in use stays held while a sync writes nothing else. Best effort: an index that cannot
        be written (a read-only file system) is read as before, unrenewed."""
        held = _holder(meta)
        step = min(_MAX_REFRESH, self._hold_window / 2)
        if held is not None and held.held_at is not None:
            age = self._now() - held.held_at
            if timedelta(0) <= age < step:
                return
        try:
            with self._engine.begin() as conn:
                self._mark_holder(conn, held)
        except DBAPIError:
            return

    def _mark_holder(self, conn: Connection, stored: Holder | None) -> None:
        """Write this version's hold. The process named stays the one already named when it runs
        the same version and is still alive (on this host) or still fresh (on another host), so
        that a short-lived command of the same version, once exited, does not look like a crash
        of the long-lived holder and free the index to an older version."""
        now = self._now()
        keep = (
            stored is not None
            and stored.version == self._projection.version
            and stored.pid is not None
            and stored.pid != self._pid
            and (
                _pid_alive(stored.pid)
                if stored.host == self._host
                else stored.held_at is not None
                and timedelta(0) <= now - stored.held_at < self._hold_window
            )
        )
        if not keep:
            self._set_meta(conn, _HOLDER_PID, str(self._pid))
            self._set_meta(conn, _HOLDER_HOST, self._host)
            self._set_meta(conn, _HOLDER_CODE, self._code)
        else:
            assert stored is not None
            self._set_meta(conn, _HOLDER_PID, str(stored.pid))
            self._set_meta(conn, _HOLDER_HOST, stored.host or "")
            self._set_meta(conn, _HOLDER_CODE, stored.code or "")
        self._set_meta(conn, _HELD_AT, format_ts(now))

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
        """Build a fresh DB beside the live one, then atomically swap it in.

        Refused (`IndexHeldError`) while another code line holds the index (IDEA-62)."""
        stored = self._guard()
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
                self._mark_holder(conn, stored)
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
