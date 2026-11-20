"""Serving the hub v2 (plan hub-ui, step 13): pages, versioned assets, cached payloads, the
trace adapter and the one write act. The server (`site_server`) only parses a request, calls this
module and sends the answer.

Invariants:
- Read-only except `snowball_add`, which records one `inbox.link_added` as the local human through
  `inbox.add_links` (the researcher supplies a work). Everything else reads the project and writes
  only under `<project>/site/hub-ui/`.
- Every payload has its own fingerprint: the count and greatest id of the event types it reads
  (`hub_build.PAYLOAD_INPUTS`; a payload with no entry reads every event; the Landscape pair reads
  `hub_build.PAYLOAD_EVENTS` and adds the technique code) plus the hub code (`code_hash`: the
  `hub_*` services and the served assets). A payload on disk is current only when its recorded
  fingerprint
  is its own current one, so an event a payload does not read leaves it fresh.
- Builders never run in the server process. A build is a child process (`spawn_builder`: `factory
  hub build --payloads-only --only <batch>` at a lower CPU priority, same environment) that writes
  each payload and its `.json.gz` into a scratch directory under the cache; the service moves the
  files in (gzip, json, then `.fp`) and records the fingerprint taken before the child started.
- Prewarm (on unless `FACTORY_HUB_PREWARM=0`): every payload not current is queued once per
  fingerprint, in the order a researcher is likely to open them, grids last; a request for one
  jumps the queue. The fingerprints are checked at most every `WATCH_SECONDS`.
- One worker thread, one child at a time. It takes up to `BATCH_MAX` queued payloads after a short
  `BATCH_WINDOW` (the payloads of one page arrive together) so they share one context in the
  child (the flow ledger takes about 80 s on the pilot). A request never waits for a build: it gets
  `Building` (503 with `Retry-After`), or the older file as `Stale` (200 with `X-Hub-Stale`). Both
  carry the ETag of the fingerprint the file was built for, so a browser keeps and revalidates
  them. A payload whose child failed at a fingerprint is not tried again until the fingerprint
  changes or `FAILED_RETRY_SECONDS` pass; the exit code and the last stderr lines are logged.
- The `.json.gz` and `.json` of a payload are written before its `.fp`; a payload without a
  matching `.fp` is stale.
- No function here calls a model or the network.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache, lru_cache
from pathlib import Path
from typing import Any, Final

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.inbox.links import parse_link
from factory.model.screening import Channel
from factory.model.work_ids import WORK_ID_RE
from factory.services import (
    hub_build,
    hub_costs,
    hub_landscape,
    hub_mining,
    hub_sources,
    hub_ui,
)
from factory.services import inbox as inbox_service
from factory.services.context import Project
from factory.services.hub_trace import trace_figure
from factory.services.search import get_work, list_works
from factory.services.site import TypeCounts, site_dir, type_counts

LINGER: float = 5.0
# A build that failed at a fingerprint is served as 500 for this long; the next request after it
# builds again (a transient fault, such as a locked file, then heals without a new event).
FAILED_RETRY_SECONDS: Final = 60.0
_LOG: Final = logging.getLogger(__name__)
"""Seconds the worker waits for another request after the queue empties before it exits and lets
go of the shared context (the next page's payloads arrive within moments of the first)."""
RETRY_AFTER: Final = 2
CACHE_DIR: Final = "hub-ui"
PREWARM_ENV: Final = "FACTORY_HUB_PREWARM"
"""`0` (or `false`, `no`, `off`) switches the prewarm off; it is on by default."""
WATCH_SECONDS: Final = 30.0
"""The prewarm checks the fingerprint (one index query) at most this often."""
PREWARM_ORDER: Final = (
    "shell",
    "overview",
    "corpus",
    "flow",
    "explore",
    "lenses",
    "findings",
    "contradictions",
    "chat",
    "mining",
    "graph",
    "screening",
    "journeys",
    "living",
    "landscape",
    "landscape_uses",
    "protocol",
    "levels",
    "pipeline",
    "sources",
    "method",
    "costs",
    "write",
    "platform",
    "learn",
)
GRIDS: Final = "grids"
"""Queue entry that builds every `grid-<miner>` payload (their names are known only once the
mining data is loaded); it comes last in a prewarm."""
BATCH_WINDOW: float = 0.3
"""Seconds the worker waits, before it starts a child, for the other payloads of the same page."""
BATCH_MAX: Final = 4
"""Payloads one child builds (they share its context); a request waits for the child running."""
BUILD_NICE: Final = 10
"""CPU niceness of the child, so a build never starves the server or other work."""
CHILD_TIMEOUT: Final = 4 * 3600.0
POLL_SECONDS: Final = 1.0
PAYLOAD_NAME: Final = re.compile(r"^[a-z][a-z0-9_.-]{0,80}$")
SNOWBALL_NOTE: Final = "added to the snowball from the hub (Foundations)"
_LINK_ORDER: Final = ("doi", "arxiv", "openalex", "pmid", "pmcid")


# ---------------------------------------------------------------- pages and assets


def page_text(page: str, *, version: str | None = None) -> str | None:
    """The fetch-mode HTML of hub page `page` (None when it is not a page): no data scripts."""
    spec = hub_ui.PAGES.get(page)
    if spec is None:
        return None
    return hub_ui.page_html(
        spec.id,
        spec.title,
        [spec.script],
        spec.payloads,
        version or hub_ui.asset_version(),
        static_data=False,
    )


@dataclass(frozen=True)
class Asset:
    body: bytes
    content_type: str
    immutable: bool
    """True when the request named the current version: cacheable for a year."""
    gz: bytes = b""
    """The body gzipped, compressed once per process (empty for a type that does not compress)."""


@cache
def _gzipped_asset(name: str, version: str) -> bytes:
    return gzip.compress(hub_ui.asset_bytes(name), 9, mtime=0)


def asset(name: str, version: str | None) -> Asset | None:
    """Registered asset `name` (None when unknown), immutable only for the current `version`."""
    found = hub_ui.ASSETS.get(name)
    if found is None:
        return None
    current = hub_ui.asset_version()
    gz = (
        _gzipped_asset(name, current) if found[1].startswith(("text/", "application/json")) else b""
    )
    return Asset(hub_ui.asset_bytes(name), found[1], version == current, gz)


# ---------------------------------------------------------------- fingerprint


@lru_cache(maxsize=1)
def code_hash() -> str:
    """Hash of the hub services and the served assets; read once per process."""
    digest = hashlib.sha256(hub_ui.asset_version().encode())
    here = Path(__file__).parent
    for path in sorted(here.glob("hub_*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def fingerprint(project: Project, name: str | None = None) -> str:
    """The version of payload `name`: the head of the event types it reads (`hub_build.reads`) and
    the hub code; for a payload in `hub_build.PAYLOAD_EVENTS` the technique code too. `None` is
    every event.

    Reads the projected index (`type_counts`), not the log files: every writer projects on write,
    so the index is current whenever an event has landed."""
    return _fingerprint_of(type_counts(project), name)


def _fingerprint_of(counts: TypeCounts, name: str | None) -> str:
    """`fingerprint` from event type counts already read."""
    if name in hub_build.PAYLOAD_EVENTS:
        raw = (
            f"events:{hub_landscape.event_key(counts)}|code:{code_hash()}"
            f"|technique:{hub_landscape.code_stamp()}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    hits = [v for t, v in counts.items() if name is None or hub_build.reads(name, t)]
    total = sum(n for n, _ in hits)
    last = max((m for _, m in hits), default="")
    raw = f"events:{total}:{last}|code:{code_hash()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def key_of(name: str) -> str | None:
    """The fingerprint key of a queue entry: grids follow the mining payload."""
    return "mining" if name == GRIDS or name.startswith(hub_mining.GRID_PREFIX) else name


# ---------------------------------------------------------------- payloads


@dataclass(frozen=True)
class Ready:
    body: bytes
    etag: str
    gzip: bool = False
    """True when `body` is gzip-compressed (asked for with `get(..., gzip=True)`)."""


@dataclass(frozen=True)
class Stale:
    """The payload as built for an older fingerprint, served while the fresh one is built; `etag`
    names the fingerprint it was built for."""

    body: bytes
    etag: str
    gzip: bool = False


@dataclass(frozen=True)
class Building:
    progress: dict[str, Any]


@dataclass(frozen=True)
class Failed:
    """A build that failed recently; carries only the payload name (the detail is logged)."""

    name: str


@dataclass(frozen=True)
class Unknown:
    pass


Answer = Ready | Stale | Building | Failed | Unknown


def known_name(name: str) -> bool:
    """Whether `name` may name a payload (a registered one or a grid of a miner)."""
    return bool(PAYLOAD_NAME.match(name)) and (
        name in hub_build.BUILDERS or name.startswith(hub_mining.GRID_PREFIX)
    )


def child_command(project: Project, names: Sequence[str], out: Path) -> list[str]:
    """The child that builds `names` into `out`: `nice` as a command, not `preexec_fn` (code run
    between fork and exec in a threaded server can deadlock the child). The environment is the
    server's, so `FACTORY_ROOT` and the like reach it."""
    return [
        "nice",
        "-n",
        str(BUILD_NICE),
        sys.executable,
        "-c",
        "from factory.cli.main import app; app()",
        "--root",
        str(project.settings.root),
        "hub",
        "build",
        project.paths.slug,
        "--out",
        str(out),
        "--only",
        ",".join(names),
        "--payloads-only",
    ]


_LIVE: set[subprocess.Popen[bytes]] = set()
"""Children running now; `PayloadService.stop` ends them so none outlives the server."""


def stop_children() -> None:
    for proc in list(_LIVE):
        proc.terminate()


def _spawn_subprocess(
    project: Project, names: Sequence[str], out: Path, poll: Callable[[], None]
) -> tuple[int, str]:
    """Run the child to its end, calling `poll` about every `POLL_SECONDS` meanwhile; its exit code
    and the last lines of its stderr (-1 when it could not start or was stopped at the timeout)."""
    log = out / "child.log"
    started = time.monotonic()
    try:
        with log.open("wb") as sink:
            proc = subprocess.Popen(
                child_command(project, names, out),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=sink,
            )
            _LIVE.add(proc)
            code: int | None = None
            while code is None:
                try:
                    code = proc.wait(POLL_SECONDS)
                except subprocess.TimeoutExpired:
                    poll()
                    if time.monotonic() - started > CHILD_TIMEOUT:
                        proc.kill()
                        proc.wait()
                        _LIVE.discard(proc)
                        return -1, f"stopped after {CHILD_TIMEOUT:.0f} s"
            _LIVE.discard(proc)
    except OSError as exc:
        return -1, f"could not start: {exc}"
    lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return code, "\n".join(lines[-12:])


spawn_builder: Callable[[Project, Sequence[str], Path, Callable[[], None]], tuple[int, str]] = (
    _spawn_subprocess
)
"""Runs one build child; replaced in tests by an in-process build."""


def accepts_gzip(header: str | None) -> bool:
    """Whether an `Accept-Encoding` header allows gzip (a `q=0` refuses it)."""
    for part in (header or "").split(","):
        token, _, params = part.partition(";")
        if token.strip().lower() in {"gzip", "x-gzip", "*"}:
            return params.replace(" ", "").lower() not in {"q=0", "q=0.0", "q=0.00", "q=0.000"}
    return False


class PayloadService:
    """One project's payload cache and its on-demand builder (see the module docstring)."""

    def __init__(self, project: Project, clock: Callable[[], float] = time.monotonic) -> None:
        self._project = project
        self._clock = clock
        self._dir = site_dir(project) / CACHE_DIR / "data"
        self._cond = threading.Condition()
        self._queue: list[str] = []
        self._current: str | None = None
        self._building: set[str] = set()
        self._done = 0
        self._started: float | None = None
        self._failed: dict[str, tuple[str, float]] = {}  # name -> (fingerprint, time of failure)
        self._unknown: dict[str, str] = {}
        self._gz_memo: dict[str, tuple[str, bytes]] = {}
        self._worker: threading.Thread | None = None
        self._watcher: threading.Thread | None = None
        self._stop = threading.Event()
        self._prewarmed: tuple[tuple[str, str], ...] | None = None  # the keys last queued for

    # -- reading

    def _recorded(self, name: str) -> str | None:
        """The fingerprint the payload on disk was built for (None when there is no record)."""
        try:
            return (self._dir / f"{name}.fp").read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _on_disk(self, name: str, fp: str) -> bool:
        """Whether `name` is on disk at fingerprint `fp` (reads the small record, not the file)."""
        return self._recorded(name) == fp and (self._dir / f"{name}.json").is_file()

    def _load(self, name: str, etag: str, want_gz: bool) -> tuple[bytes, bool] | None:
        """The file of `name` (gzipped when asked: the one the build wrote, else compressed here
        once per ETag); None when there is none."""
        if want_gz:
            try:
                return (self._dir / f"{name}.json.gz").read_bytes(), True
            except OSError:
                pass
        try:
            raw = (self._dir / f"{name}.json").read_bytes()
        except OSError:
            return None
        if not want_gz:
            return raw, False
        memo = self._gz_memo.get(name)
        if memo is None or memo[0] != etag:
            memo = (etag, gzip.compress(raw, 6, mtime=0))
            self._gz_memo[name] = memo
        return memo[1], True

    def is_fresh(self, name: str) -> bool:
        """Whether `name` is on disk at its current fingerprint."""
        return known_name(name) and self._on_disk(name, fingerprint(self._project, key_of(name)))

    def status(self) -> dict[str, dict[str, Any]]:
        """Per payload: `fresh` (on disk at its current fingerprint), `built_at` (UTC time of the
        file on disk, None when none) and `error` (the build failed at the current fingerprint).
        Reads the index head, the small `.fp` records and file times only."""
        counts = type_counts(self._project)
        out: dict[str, dict[str, Any]] = {}
        for name in self._names():
            fp = _fingerprint_of(counts, name)
            row: dict[str, Any] = {"fresh": self._on_disk(name, fp), "built_at": None}
            try:
                stamp = (self._dir / f"{name}.json").stat().st_mtime
                row["built_at"] = datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            except OSError:
                pass
            with self._cond:
                failed = self._failed.get(name)
            if failed is not None and failed[0] == fp:
                row["error"] = "build failed"
            out[name] = row
        return out

    @staticmethod
    def _names() -> list[str]:
        names: list[str] = [n for n in PREWARM_ORDER if n in hub_build.BUILDERS]
        return names + [n for n in hub_build.BUILDERS if n not in names]

    def get(self, name: str, gzip: bool = False) -> Answer:
        """The payload `name` at its current fingerprint, or what is happening to it. With `gzip`
        the body is the compressed file and the answer says so."""
        if not known_name(name):
            return Unknown()
        fp = fingerprint(self._project, key_of(name))
        if self._unknown.get(name) == fp:
            return Unknown()
        if self._on_disk(name, fp):
            loaded = self._load(name, f'"{fp}"', gzip)
            if loaded is not None:
                return Ready(loaded[0], f'"{fp}"', loaded[1])
        stale = self._stale(name, gzip)
        with self._cond:
            failed = self._failed.get(name)
            if failed is not None and failed[0] == fp:
                if self._clock() - failed[1] < FAILED_RETRY_SECONDS:
                    return Failed(name) if stale is None else stale
                del self._failed[name]  # the window has passed: build it again
            if name not in self._building:
                if name in self._queue:
                    self._queue.remove(name)
                self._queue.insert(0, name)  # a request jumps the queue
            self._ensure_worker()
            self._cond.notify_all()
            return Building(self._progress()) if stale is None else stale

    def _stale(self, name: str, want_gz: bool) -> Stale | None:
        """The file on disk for an older fingerprint, tagged with the one it was built for."""
        try:
            stamp = (self._dir / f"{name}.json").stat().st_mtime_ns
        except OSError:
            return None
        recorded = self._recorded(name)
        tag = f'"{recorded}"' if recorded else f'"s-{stamp:x}"'
        loaded = self._load(name, tag, want_gz)
        return None if loaded is None else Stale(loaded[0], tag, loaded[1])

    def _progress(self) -> dict[str, Any]:
        return {
            "current": self._current,
            "queued": list(self._queue),
            "done": self._done,
            "seconds": None if self._started is None else round(time.monotonic() - self._started),
        }

    # -- prewarm

    def prewarm(self) -> None:
        """Queue every payload now and again whenever a fingerprint changes (a no-op when the
        env switch is off). The first pass runs here; later checks run on a daemon thread."""
        if os.environ.get(PREWARM_ENV, "1").strip().lower() in {"0", "false", "no", "off"}:
            return
        self.prewarm_check()
        if self._watcher is None or not self._watcher.is_alive():
            self._watcher = threading.Thread(target=self._watch, name="hub-ui-prewarm", daemon=True)
            self._watcher.start()

    def stop(self) -> None:
        """Stop the fingerprint watch and end the build child, if one is running."""
        self._stop.set()
        stop_children()

    def _watch(self) -> None:
        while not self._stop.wait(WATCH_SECONDS):
            try:
                self.prewarm_check()
            except Exception as exc:  # the watch outlives a transient index fault
                _LOG.warning("hub prewarm check failed: %s", exc)

    def prewarm_check(self) -> bool:
        """Queue the payloads that are not current when a fingerprint is new since the last
        check; cheap otherwise (one index read). True when anything was queued."""
        counts = type_counts(self._project)
        fps = {n: _fingerprint_of(counts, n) for n in self._names()}
        grid_fp = _fingerprint_of(counts, "mining")
        snapshot = (*sorted(fps.items()), (GRIDS, grid_fp))
        with self._cond:
            if self._prewarmed == snapshot:
                return False
            self._prewarmed = snapshot
        names = [n for n in self._names() if not self._on_disk(n, fps[n])]
        grids = sorted(self._dir.glob("grid-*.fp")) if self._dir.is_dir() else []
        if not grids or any(g.read_text(encoding="utf-8").strip() != grid_fp for g in grids):
            names.append(GRIDS)
        with self._cond:
            for name in names:
                if name not in self._queue and name not in self._building:
                    self._queue.append(name)
            if self._queue:
                self._ensure_worker()
                self._cond.notify_all()
        return bool(names)

    # -- building (the worker thread supervises children; no builder code runs here)

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="hub-ui-build", daemon=True)
            self._worker.start()

    def _run(self) -> None:
        with self._cond:
            self._started = time.monotonic()
            self._done = 0
        while True:
            with self._cond:
                if not self._queue and LINGER > 0:
                    self._cond.wait(LINGER)
                if not self._queue:
                    self._current = None
                    self._started = None
                    self._worker = None
                    return
                end = time.monotonic() + BATCH_WINDOW  # the page's other payloads arrive now
                while (left := end - time.monotonic()) > 0:
                    self._cond.wait(left)
                batch = self._queue[:BATCH_MAX]
                self._building = set(batch)
                self._current = batch[0]
            try:
                self._build_batch(batch)
            except Exception as exc:  # the worker outlives one broken batch
                _LOG.exception("hub payload batch %s failed: %s", batch, exc)
            finally:
                with self._cond:
                    for name in batch:
                        if name in self._queue:
                            self._queue.remove(name)
                    self._done += len(batch)
                    self._current = None
                    self._building = set()

    def _install(self, out: Path, name: str, fp: str) -> bool:
        """Move the files a child wrote for `name` into the cache (gzip, json, then the record);
        False when the child has not finished it."""
        if not (out / "data" / f"{name}.json").is_file():
            return False
        self._dir.mkdir(parents=True, exist_ok=True)
        for suffix in (".json.gz", ".json"):
            src = out / "data" / f"{name}{suffix}"
            if src.is_file():
                src.replace(self._dir / f"{name}{suffix}")
            elif suffix == ".json.gz":
                (self._dir / f"{name}{suffix}").unlink(missing_ok=True)
        (self._dir / f"{name}.fp").write_text(fp + "\n", encoding="utf-8")
        return True

    def _build_batch(self, batch: list[str]) -> None:
        # fingerprints are taken first: an event landing meanwhile reads as stale
        fps = {n: fingerprint(self._project, key_of(n)) for n in batch}
        self._dir.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix="build-", dir=self._dir.parent))
        done: set[str] = set()

        def install() -> None:
            for name in batch:
                if name in done:
                    continue
                if name == GRIDS:
                    for found in sorted((out / "data").glob("grid-*.json")):
                        if self._install(out, found.stem, fps[GRIDS]):
                            done.add(GRIDS)
                elif self._install(out, name, fps[name]):
                    done.add(name)

        try:
            (out / "data").mkdir()
            only = ["grid" if n == GRIDS else n for n in batch]
            code, tail = spawn_builder(self._project, only, out, install)
            install()
            missing = [n for n in batch if n not in done]
            if missing:
                _LOG.error(
                    "hub payload child exited %s; no payload for %s; last output:\n%s",
                    code,
                    ", ".join(missing),
                    tail,
                )
            with self._cond:
                for name in missing:
                    if code == 0 and name.startswith(hub_mining.GRID_PREFIX):
                        self._unknown[name] = fps[name]  # the child built the rest: no such grid
                    elif code != 0 or name != GRIDS:
                        self._failed[name] = (fps[name], self._clock())
        finally:
            shutil.rmtree(out, ignore_errors=True)


# ---------------------------------------------------------------- trace


def trace(project: Project, query: dict[str, str]) -> dict[str, Any]:
    """The chain behind one figure (`figure`, optional `offset` and `limit`, as text). Raises
    `FactoryValidationError` for a missing figure or a number that is not one."""
    issues: list[ValidationIssue] = []
    figure = query.get("figure", "")
    if not figure.strip():
        issues.append(ValidationIssue("figure", "required"))
    numbers: dict[str, int] = {}
    for key in ("offset", "limit"):
        if key in query:
            try:
                numbers[key] = int(query[key])
            except ValueError:
                issues.append(ValidationIssue(key, "must be a whole number"))
    if issues:
        raise FactoryValidationError(issues)
    return trace_figure(project, figure, **numbers).to_payload()


# ---------------------------------------------------------------- the snowball act


def corpus_ids(project: Project) -> frozenset[str]:
    return frozenset(w.id for w in list_works(project))


def _link_of(identifiers: Any) -> str | None:
    """The first identifier of a work that the inbox accepts, as a link."""
    for kind in _LINK_ORDER:
        value = getattr(identifiers, kind, None)
        if value and parse_link(str(value)) is not None:
            return str(value)
    return None


def snowball_add(project: Project, actor: Actor, work_id: object) -> dict[str, object]:
    """Put an outside work in the inbox, as the researcher supplying it (`inbox.link_added`).

    The work must be a stored work outside the corpus with an identifier the inbox accepts; an
    identifier already open in the inbox answers `duplicate` and writes nothing. Raises
    `FactoryValidationError` (nothing written) or `FactoryError`."""
    if not isinstance(work_id, str) or not re.match(WORK_ID_RE, work_id):
        raise FactoryValidationError([ValidationIssue("work_id", "must be a work id")])
    found = get_work(project, work_id)
    if found is None:
        raise FactoryValidationError([ValidationIssue("work_id", "unknown work")])
    if work_id in corpus_ids(project):
        raise FactoryValidationError([ValidationIssue("work_id", "already in the corpus")])
    link = _link_of(found.identifiers)
    if link is None:
        raise FactoryValidationError(
            [ValidationIssue("work_id", "the work has no identifier the inbox accepts")]
        )
    with project.index.exclusive():
        project.index.sync()
        same = inbox_service.find_open_duplicate(project, link)
        if same is not None:
            return {"duplicate": True, "item_id": same, "work_id": work_id}
        result = inbox_service.add_links(
            project, actor, [inbox_service.LinkInput(link, note=SNOWBALL_NOTE)], Channel.CLI
        )
    if result.rejected:
        raise FactoryValidationError(list(result.rejected[0].issues))
    return {"duplicate": False, "item_id": result.written[0], "work_id": work_id}


# ---------------------------------------------------------------- read-only routes


def source_document(project: Project, document_id: str) -> dict[str, Any] | None:
    """The `sources-doc-<id>` payload (None for an id that is no converted document)."""
    return hub_sources.document_detail(project, document_id)


def source_file(project: Project, document_id: str, kind: str) -> tuple[bytes, str] | None:
    """The `original` or `markdown` of a converted document, with its content type."""
    return hub_sources.document_file(project, document_id, kind)


def study_file(project: Project, registration_id: str) -> tuple[bytes, str, str] | None:
    """A registered study file (stored blob) by registration id: (body, content type, name)."""
    return hub_sources.study_file(project, registration_id)


def ops_file(project: Project, rel: str) -> hub_costs.OpsFile | None:
    """A file of the project's `ops/` folder (see `hub_costs.read_ops_file`)."""
    return hub_costs.read_ops_file(project, rel)


_WIKI_LOCK = threading.Lock()
SKIPPED_LINKS = "SKIPPED-LINKS.txt"


def _zip_vault(vault: Path, root: Path, dest: Path) -> str:
    """Zip `vault` into `dest`. A symlink whose target is a file inside the project folder
    `root` is stored as that file's content; one pointing outside the project, or to nothing, is
    left out and listed in `SKIPPED-LINKS.txt` (WK-8). Returns the zip path."""
    base = root.resolve()
    skipped: list[str] = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(vault.rglob("*")):
            rel = path.relative_to(vault).as_posix()
            if path.is_symlink():
                target = path.resolve()
                if target.is_file() and target.is_relative_to(base):
                    zf.write(target, rel)
                else:
                    skipped.append(rel)
            elif path.is_file():
                zf.write(path, rel)
        if skipped:
            zf.writestr(
                SKIPPED_LINKS,
                "Links left out of this archive because they point outside the project "
                "folder or to a missing file:\n" + "\n".join(skipped) + "\n",
            )
    return str(dest)


def wiki_zip(project: Project) -> Path:
    """The wiki vault (`site.build_wiki`, synthesis pages included) as a zip under
    `site/hub-ui/`, built once per fingerprint (older ones are removed). Writes only there."""
    from factory.services.site import _build_wiki

    cache = site_dir(project) / CACHE_DIR
    target = cache / f"wiki-{fingerprint(project)}.zip"
    with _WIKI_LOCK:
        if target.is_file():
            return target
        cache.mkdir(parents=True, exist_ok=True)
        # beside the project, not in /tmp (a small tmpfs that is often full)
        work = Path(tempfile.mkdtemp(prefix="wiki-", dir=cache))
        try:
            vault = work / "vault"
            vault.mkdir()
            _build_wiki(project, vault)
            made = _zip_vault(vault, project.paths.dir, work / "wiki.zip")
            for old in cache.glob("wiki-*.zip"):
                old.unlink(missing_ok=True)
            Path(made).replace(target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return target
