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
  event types. A payload on disk is served only when its recorded fingerprint is the current one.
- Payloads are built on demand by one worker thread, one build at a time, all stale payloads that
  were asked for sharing one `HubContext` (the flow ledger takes about 80 s on the pilot). A request
  never waits for a build: it gets `Building` (the server answers 503 with `Retry-After`). A payload
  that failed at a fingerprint is not tried again until the fingerprint changes or `FAILED_RETRY_SECONDS` pass.
- The disk file `<name>.json` is written first, then `<name>.fp`; a payload without a matching
  `.fp` is stale.
- No function here calls a model or the network.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.inbox.links import parse_link
from factory.model.screening import Channel
from factory.model.work_ids import WORK_ID_RE
from factory.services import hub_build, hub_mining, hub_ui
from factory.services import inbox as inbox_service
from factory.services.context import Project
from factory.services.hub_trace import trace_figure
from factory.services.search import get_work, list_works
from factory.services.site import site_dir, type_counts

LINGER: float = 5.0
# A build that failed at a fingerprint is served as 500 for this long; the next request after it
# builds again (a transient fault, such as a locked file, then heals without a new event).
FAILED_RETRY_SECONDS: Final = 60.0
_LOG: Final = logging.getLogger(__name__)
"""Seconds the worker waits for another request after the queue empties before it exits and lets
go of the shared context (the next page's payloads arrive within moments of the first)."""
RETRY_AFTER: Final = 2
CACHE_DIR: Final = "hub-ui"
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


def fingerprint(project: Project) -> str:
    """One version for every payload: the event log head and the hub code.

    Reads the projected index (`type_counts`), not the log files: every writer projects on write,
    so the index is current whenever an event has landed."""
    counts = type_counts(project)
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
class Building:
    progress: dict[str, Any]


@dataclass(frozen=True)
class Failed:
    """A build that failed recently; carries only the payload name (the detail is logged)."""

    name: str


@dataclass(frozen=True)
class Unknown:
    pass


Answer = Ready | Building | Failed | Unknown


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

    # -- reading

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
        fp = fingerprint(self._project)
        if self._unknown.get(name) == fp:
            return Unknown()
        body = self._read(name, fp)
        if body is not None:
            return Ready(body, f'"{fp}"')
        with self._cond:
            failed = self._failed.get(name)
            if failed is not None and failed[0] == fp:
                if self._clock() - failed[1] < FAILED_RETRY_SECONDS:
                    return Failed(name)
                del self._failed[name]  # the window has passed: build it again
            if name not in self._queue and name != self._current:
                self._queue.append(name)
            self._ensure_worker()
            self._cond.notify_all()
            return Building(self._progress())

    def _progress(self) -> dict[str, Any]:
        return {
            "current": self._current,
            "queued": list(self._queue),
            "done": self._done,
            "seconds": None if self._started is None else round(time.monotonic() - self._started),
        }

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

    def _build(self, name: str) -> None:
        fp = fingerprint(self._project)  # taken first: an event landing meanwhile reads as stale
        try:
            ctx = self._context(fp)
            if name in hub_build.BUILDERS:
                payload = hub_build.BUILDERS[name](ctx)
            else:
                grids = ctx.grids
                if name not in grids:
                    self._unknown[name] = fp
                    return
                payload = grids[name]
            text = hub_build.dumps(payload)
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._dir / f"{name}.json.tmp"
            tmp.write_text(text + "\n", encoding="utf-8")
            tmp.replace(self._dir / f"{name}.json")
            (self._dir / f"{name}.fp").write_text(fp + "\n", encoding="utf-8")
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
