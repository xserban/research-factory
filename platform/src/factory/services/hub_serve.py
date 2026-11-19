"""Serving the hub v2 (plan hub-ui, step 13): pages, versioned assets, cached payloads, the
trace adapter and the one write act. The server (`site_server`) only parses a request, calls this
module and sends the answer.

Invariants:
- Read-only except `snowball_add`, which records one `inbox.link_added` as the local human through
  `inbox.add_links` (the researcher supplies a work). Everything else reads the project and writes
  only under `<project>/site/hub-ui/`.
- One fingerprint covers every payload: the event log (count and greatest id per event type, summed)
  and the hub code (`code_hash`: the `hub_*` services and the served assets). Finer per-payload keys
  were not cheap: a payload reads through shared inputs (flow ledger, graph, layers) that span most
  event types. The one exception is a payload listed in `hub_build.PAYLOAD_EVENTS` (the Landscape:
  a 26 to 60 s read): its key is the count and greatest id of the event types it names plus the
  hub code and the technique code, so a feed, runner or page event never rebuilds it. A payload on
  disk is served only when its recorded fingerprint is the current one.
- Prewarm (on unless `FACTORY_HUB_PREWARM=0`): every payload is queued once per fingerprint, in
  the order a researcher is likely to open them, grids last; a request for one jumps the queue.
  The fingerprint is checked at most every `WATCH_SECONDS`. A payload on disk for an older
  fingerprint is served as `Stale` (200 with `X-Hub-Stale`) while the fresh one is built.
- Payloads are built on demand by one worker thread, one build at a time, all stale payloads that
  were asked for sharing one `HubContext` (the flow ledger takes about 80 s on the pilot). A request
  never waits for a build: it gets `Building` (the server answers 503 with `Retry-After`). A payload
  that failed at a fingerprint is not tried again until the fingerprint changes or
  `FAILED_RETRY_SECONDS` pass.
- The disk file `<name>.json` is written first, then `<name>.fp`; a payload without a matching
  `.fp` is stale.
- No function here calls a model or the network.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.inbox.links import parse_link
from factory.model.screening import Channel
from factory.model.work_ids import WORK_ID_RE
from factory.services import hub_build, hub_costs, hub_landscape, hub_mining, hub_sources, hub_ui
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
    "mining",
    "graph",
    "screening",
    "journeys",
    "living",
    "landscape",
    "landscape_uses",
    "protocol",
    "pipeline",
    "sources",
    "method",
    "costs",
    "write",
    "platform",
)
GRIDS: Final = "grids"
"""Queue entry that builds every `grid-<miner>` payload (their names are known only once the
mining data is loaded); it comes last in a prewarm."""
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


def asset(name: str, version: str | None) -> Asset | None:
    """Registered asset `name` (None when unknown), immutable only for the current `version`."""
    found = hub_ui.ASSETS.get(name)
    if found is None:
        return None
    return Asset(hub_ui.asset_bytes(name), found[1], version == hub_ui.asset_version())


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
    """The version of payload `name`: for most payloads (and for `None`) the event log head and the
    hub code; for a payload in `hub_build.PAYLOAD_EVENTS`, the head of its own event types, the hub
    code and the technique code.

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
    total = sum(n for n, _ in counts.values())
    last = max((m for _, m in counts.values()), default="")
    raw = f"events:{total}:{last}|code:{code_hash()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- payloads


@dataclass(frozen=True)
class Ready:
    body: bytes
    etag: str


@dataclass(frozen=True)
class Stale:
    """The payload as built for an older fingerprint, served while the fresh one is built."""

    body: bytes


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


class PayloadService:
    """One project's payload cache and its on-demand builder (see the module docstring)."""

    def __init__(self, project: Project, clock: Callable[[], float] = time.monotonic) -> None:
        self._project = project
        self._clock = clock
        self._dir = site_dir(project) / CACHE_DIR / "data"
        self._cond = threading.Condition()
        self._queue: list[str] = []
        self._current: str | None = None
        self._done = 0
        self._started: float | None = None
        self._failed: dict[str, tuple[str, float]] = {}  # name -> (fingerprint, time of failure)
        self._unknown: dict[str, str] = {}
        self._ctx: tuple[str, hub_build.HubContext] | None = None
        self._worker: threading.Thread | None = None
        self._watcher: threading.Thread | None = None
        self._stop = threading.Event()
        self._prewarmed: str | None = None  # the fingerprint a prewarm was last queued for

    # -- reading

    def _read_stale(self, name: str) -> bytes | None:
        """The payload on disk whatever fingerprint it was built for (None when there is none)."""
        try:
            return (self._dir / f"{name}.json").read_bytes()
        except OSError:
            return None

    def is_fresh(self, name: str) -> bool:
        """Whether `name` is on disk at the current fingerprint."""
        return known_name(name) and self._read(name, fingerprint(self._project)) is not None

    def status(self) -> dict[str, dict[str, Any]]:
        """Per payload: `fresh` (on disk at its current fingerprint), `built_at` (UTC time of the
        file on disk, None when none) and `error` (the build failed at the current fingerprint).
        Reads the index head and file times only; builds and writes nothing."""
        counts = type_counts(self._project)
        heads: dict[str | None, str] = {}

        def head(name: str) -> str:
            key = name if name in hub_build.PAYLOAD_EVENTS else None
            if key not in heads:
                heads[key] = _fingerprint_of(counts, key)
            return heads[key]

        out: dict[str, dict[str, Any]] = {}
        names: list[str] = [n for n in PREWARM_ORDER if n in hub_build.BUILDERS]
        names += [n for n in hub_build.BUILDERS if n not in names]
        for name in names:
            fp = head(name)
            row: dict[str, Any] = {"fresh": self._read(name, fp) is not None, "built_at": None}
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

    def _read(self, name: str, fp: str) -> bytes | None:
        try:
            if (self._dir / f"{name}.fp").read_text(encoding="utf-8").strip() != fp:
                return None
            return (self._dir / f"{name}.json").read_bytes()
        except OSError:
            return None

    def get(self, name: str) -> Answer:
        """The payload `name` at the current fingerprint, or what is happening to it."""
        if not known_name(name):
            return Unknown()
        fp = fingerprint(self._project, name)
        if self._unknown.get(name) == fp:
            return Unknown()
        body = self._read(name, fp)
        if body is not None:
            return Ready(body, f'"{fp}"')
        old = self._read_stale(name)
        with self._cond:
            failed = self._failed.get(name)
            if failed is not None and failed[0] == fp:
                if self._clock() - failed[1] < FAILED_RETRY_SECONDS:
                    return Failed(name) if old is None else Stale(old)
                del self._failed[name]  # the window has passed: build it again
            if name != self._current:
                if name in self._queue:
                    self._queue.remove(name)
                self._queue.insert(0, name)  # a request jumps the queue
            self._ensure_worker()
            self._cond.notify_all()
            return Building(self._progress()) if old is None else Stale(old)

    def _progress(self) -> dict[str, Any]:
        return {
            "current": self._current,
            "queued": list(self._queue),
            "done": self._done,
            "seconds": None if self._started is None else round(time.monotonic() - self._started),
        }

    # -- prewarm

    def prewarm(self) -> None:
        """Queue every payload now and again whenever the fingerprint changes (a no-op when the
        env switch is off). The first pass runs here; later checks run on a daemon thread."""
        if os.environ.get(PREWARM_ENV, "1").strip().lower() in {"0", "false", "no", "off"}:
            return
        self.prewarm_check()
        if self._watcher is None or not self._watcher.is_alive():
            self._watcher = threading.Thread(target=self._watch, name="hub-ui-prewarm", daemon=True)
            self._watcher.start()

    def stop(self) -> None:
        """Stop the fingerprint watch (a build in progress finishes)."""
        self._stop.set()

    def _watch(self) -> None:
        while not self._stop.wait(WATCH_SECONDS):
            try:
                self.prewarm_check()
            except Exception as exc:  # the watch outlives a transient index fault
                _LOG.warning("hub prewarm check failed: %s", exc)

    def prewarm_check(self) -> bool:
        """Queue the payloads that are not current when the fingerprint is new since the last
        check; cheap otherwise (the fingerprint only). True when anything was queued."""
        fp = fingerprint(self._project)
        with self._cond:
            if self._prewarmed == fp:
                return False
            self._prewarmed = fp
        names: list[str] = [n for n in PREWARM_ORDER if n in hub_build.BUILDERS]
        names += [n for n in hub_build.BUILDERS if n not in names]
        names = [n for n in names if self._read(n, fp) is None]
        grids = sorted(self._dir.glob("grid-*.fp")) if self._dir.is_dir() else []
        if not grids or any(g.read_text(encoding="utf-8").strip() != fp for g in grids):
            names.append(GRIDS)
        with self._cond:
            for name in names:
                if name not in self._queue and name != self._current:
                    self._queue.append(name)
            if self._queue:
                self._ensure_worker()
                self._cond.notify_all()
        return bool(names)

    # -- building

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
                    self._ctx = None
                    self._worker = None
                    return
                name = self._queue[0]
                self._current = name
            try:
                self._build(name)
            finally:
                with self._cond:
                    self._queue.remove(name)
                    self._done += 1
                    self._current = None

    def _context(self, fp: str) -> hub_build.HubContext:
        if self._ctx is None or self._ctx[0] != fp:
            self._ctx = (fp, hub_build.HubContext(self._project))
        return self._ctx[1]

    def _write(self, name: str, payload: dict[str, Any], fp: str) -> None:
        text = hub_build.dumps(payload)
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / f"{name}.json.tmp"
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(self._dir / f"{name}.json")
        (self._dir / f"{name}.fp").write_text(fp + "\n", encoding="utf-8")

    def _build(self, name: str) -> None:
        fp = fingerprint(
            self._project, name
        )  # taken first: an event landing meanwhile reads as stale
        context_fp = fingerprint(self._project)  # one shared context per log head, whatever the key
        try:
            ctx = self._context(context_fp)
            if name == GRIDS:
                for grid, body in ctx.grids.items():
                    self._write(grid, body, fp)
                return
            if name in hub_build.BUILDERS:
                payload = hub_build.BUILDERS[name](ctx)
            else:
                grids = ctx.grids
                if name not in grids:
                    self._unknown[name] = fp
                    return
                payload = grids[name]
            self._write(name, payload, fp)
        except Exception as exc:  # one broken payload never stops the others
            _LOG.exception("hub payload %s failed to build: %s", name, exc)
            self._failed[name] = (fp, self._clock())


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


def ops_file(project: Project, rel: str) -> hub_costs.OpsFile | None:
    """A file of the project's `ops/` folder (see `hub_costs.read_ops_file`)."""
    return hub_costs.read_ops_file(project, rel)


_WIKI_LOCK = threading.Lock()


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
            made = shutil.make_archive(str(work / "wiki"), "zip", root_dir=vault)
            for old in cache.glob("wiki-*.zip"):
                old.unlink(missing_ok=True)
            Path(made).replace(target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return target
