"""Serve the project site on 127.0.0.1 and keep it current (plan site-hub, step 6).

The hub is a folder of static files (`<project>/site/`); this server shows it over HTTP, adds
`/api/status` (each product's build time and staleness, read from the manifest and the event log),
and runs one background thread that rebuilds stale products. A rebuild waits at least `min_gap`
seconds after the previous one: the snapshot of the dashboard takes about a minute, and a project
that is being mined makes it stale all the time.

Invariants:
- Read-only for the browser except these allow-listed acts (decision 119). Project acts:
  `POST /api/feed/react`, `POST /api/feed/add`, `POST /api/feed/configure`,
  `POST /api/watch/configure` and `POST /api/living/snapshot` (the Updates page),
  `POST /api/queue/process` (starts the headless runner, which records its own system events),
  `POST /api/queue/resume` (plan restart-and-costs, R3) and the researcher's layer acts
  (IDEA-50): `POST /api/mine/work` (`work_id`, optional `reason`), `POST /api/mine/layer`
  (`layer`, optional `reason`) and `POST /api/layers/move` (`work_id`, `layer`, `reason`
  required), which call `work_layers.request_mining` and `work_layers.move_layer` as the local
  human, as the CLI does (`cli:mine request`, `cli:layers move`). `POST /api/export/works`
  (`work_ids`, optional `pdfs`; IDEA-87) answers a zip of the chosen works' converted Markdown and
  manifest as the local human (`cli:export works`), read-only, body limit
  `MAX_EXPORT_BODY`; nothing is withheld. Hub acts (main server, hub
  token): `POST /api/feed/run`, `POST /api/feed/refetch`, `POST /api/projects/create` and
  `POST /api/inbox/add` (`project`, `value`, optional `note`: captures one link as an inbox item
  as the local human, `cli:inbox add`; an identifier already in the inbox answers `duplicate`
  and writes nothing). A refusal is a structured error, nothing is
  written. `GET /api/layers` reads the latest scheme's layer ids and each work's layer. Any
  other POST path is 404; PUT, DELETE and PATCH are 405. Apart from those acts the server writes
  nothing but the site folder, through `site.build`.
- `POST /api/queue/resume` with `dry_run` plans in the request and writes nothing. A real resume
  runs `services.resume.resume` in a daemon thread, one at a time (`ResumeRunner`), because its
  deterministic steps look papers up and convert them and must not run in a request; the reply is
  202 and the outcome (ids, refusals) is kept as `last_resume` in `GET /api/queue/interrupted`.
  `GET /api/queue/interrupted` reads `interrupted()` and reconciles nothing.
- After a successful `POST /api/feed/add` the deterministic steps (`work_queue.advance`) start in
  a daemon thread, at most one per server; the reply is not delayed. A thread already running
  means the new call is skipped. Conversion runs only in that thread, never in a request.
  `GET /api/queue/runs` reads the runs and reconciles nothing.
- A POST needs, all at once: a loopback Host, the per-start token in `X-Factory-Token` (compared in
  constant time), `Content-Type: application/json`, a body of at most 16 KiB and, if an Origin is
  sent, this server's own origin. Otherwise 403 (413 or 415 for size or type) and nothing is
  written. The token is made at server start, is injected into `/feed/`, `/queue/` and `/explorer/`
  pages only and is never written to the files on disk.
- The actor is the local human principal and each act is authorised by its command row
  (`cli:feed react`, `cli:feed add`, `cli:queue process`, `cli:queue resume`), as the CLI does.
- Loopback only: a request whose Host is not 127.0.0.1, localhost or [::1] is refused.
- One build runs at a time; a product that fails is recorded by `site.build` and the others go on.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final, NamedTuple

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.model.feed import FeedNote, FeedReaction
from factory.model.screening import Channel
from factory.services import export_works as export_works_service
from factory.services import feed as feed_service
from factory.services import inbox as inbox_service
from factory.services import pipeline as pipeline_service
from factory.services import resume as resume_service
from factory.services import runner as runner_service
from factory.services import site as site_service
from factory.services import (
    site_auth,
    site_backlog,
    site_catalog_page,
    site_chrome,
    site_create,
    site_hub_feed,
    site_portal,
    site_settings,
    work_layers,
    work_queue,
)
from factory.services import snapshots as snapshots_service
from factory.services import watch_config as watch_config_service
from factory.services.access import authorize_command, authorize_export_works
from factory.services.context import Project
from factory.sources.fulltext.registry import default_routes
from factory.sources.registry import default_sources

HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8766
MAX_BODY: Final = 16 * 1024
MAX_EXPORT_BODY: Final = 256 * 1024
"""The export route takes a list of work ids (up to the cap of 200 works, each id up to a few
hundred characters), which the usual 16 KiB body limit would cut."""
EXPORT_ROUTE: Final = "/api/export/works"
TOKEN_HEADER: Final = "X-Factory-Token"
_ACTION_PAGES: Final = ("feed", "queue", "explorer", "updates")
_TOKEN_META: Final = "<meta name='factory-token' content='{}'>"
_API_META: Final = "<meta name='factory-api' content='{}'>"
PORTAL_LINK: Final = (
    "<a href='/' style='position:fixed;right:12px;bottom:10px;z-index:9;font:12px sans-serif;"
    "padding:4px 8px;border:1px solid #888;border-radius:4px;background:#111;color:#ddd;"
    "text-decoration:none'>All projects</a>"
)
_LOG: Final = logging.getLogger(__name__)


def _sources() -> Any:
    """The source factories `feed add` resolves with (as `factory feed add` builds them)."""
    return dict(default_sources())


def _start_advance(project: Project, gate: threading.Lock) -> bool:
    """Run `work_queue.advance` in a daemon thread unless `gate` is held; True when started.
    The thread releases `gate` when it ends, whatever happens; a failure is logged, not raised."""
    if not gate.acquire(blocking=False):
        return False

    def run() -> None:
        try:
            work_queue.advance(
                project, sources=_sources(), fetchers=default_routes(project.settings)
            )
        except Exception:  # the reply to the add has already gone; nothing else to tell
            _LOG.exception("the automatic steps after a feed add failed")
        finally:
            gate.release()

    try:
        threading.Thread(target=run, name="queue-advance", daemon=True).start()
    except RuntimeError:
        gate.release()
        return False
    return True


def _issues(*issues: ValidationIssue) -> dict[str, object]:
    return {"ok": False, "issues": [{"field": i.field, "reason": i.reason} for i in issues]}


def _optional_str(body: dict[str, Any], key: str) -> tuple[str | None, list[ValidationIssue]]:
    value = body.get(key)
    if value is None or isinstance(value, str):
        return value, []
    return None, [ValidationIssue(key, "must be a string")]


def feed_react(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Record a reaction as the local human; returns (status, JSON body)."""
    entry_id = body.get("entry_id")
    ranking_id, bad = _optional_str(body, "ranking_id")
    if not isinstance(entry_id, str) or not entry_id:
        bad.append(ValidationIssue("entry_id", "required"))
    try:
        reaction = FeedReaction(str(body.get("reaction")))
    except ValueError:
        bad.append(
            ValidationIssue(
                "reaction", "must be one of " + ", ".join(r.value for r in FeedReaction)
            )
        )
    if bad:
        return 400, _issues(*bad)
    assert isinstance(entry_id, str)
    try:
        actor = project.human_actor()
        authorize_command(project, project.principal, "cli:feed react")
        event_id = feed_service.react(project, actor, entry_id, reaction, ranking_id=ranking_id)
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    return 200, {"ok": True, "event_id": event_id, "reaction": reaction.value}


def feed_add(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Send the entry to the inbox and look it up, as the local human; returns (status, body)."""
    entry_id = body.get("entry_id")
    ranking_id, bad = _optional_str(body, "ranking_id")
    note_text, more = _optional_str(body, "note")
    bad += more
    if not isinstance(entry_id, str) or not entry_id:
        bad.append(ValidationIssue("entry_id", "required"))
    note: FeedNote | None = None
    if note_text is not None and not more:
        try:
            note = TypeAdapter(FeedNote).validate_python(note_text)
        except PydanticValidationError as exc:
            bad.append(ValidationIssue("note", str(exc.errors()[0]["msg"])))
    if bad:
        return 400, _issues(*bad)
    assert isinstance(entry_id, str)
    try:
        actor = project.human_actor()
        authorize_command(project, project.principal, "cli:feed add")
        result = feed_service.add(
            project, actor, entry_id, sources=_sources(), note=note, ranking_id=ranking_id
        )
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    return 200, {"ok": True, **result.model_dump(mode="json")}


def feed_configure(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Record the feed configuration with these categories as the local human (the Settings page's
    Accept). The other settings of the current configuration are kept. Refusals write nothing."""
    categories = body.get("categories")
    bad: list[ValidationIssue] = []
    if (
        not isinstance(categories, list)
        or not categories
        or not all(isinstance(c, str) for c in categories)
    ):
        bad.append(ValidationIssue("categories", "must be a non-empty list of strings"))
    if bad:
        return 400, _issues(*bad)
    assert isinstance(categories, list)
    try:
        actor = project.human_actor()
        authorize_command(project, project.principal, "cli:feed configure")
        current = feed_service.current_config(project)
        kept: dict[str, object] = (
            {} if current is None else current.model_dump(mode="json", exclude={"config_id"})
        )
        event_id = feed_service.configure(project, actor, {**kept, "categories": tuple(categories)})
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    return 200, {"ok": True, "event_id": event_id, "categories": categories}


def watch_configure(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Save the weekly watch settings as a protocol amendment by the local human (the Updates
    page). `sources` (non-empty list), `interval_days` (int >= 1), `until` (ISO date or null),
    optional `reason`. Refusals write nothing."""
    sources = body.get("sources")
    interval = body.get("interval_days")
    until_text = body.get("until")
    reason = body.get("reason", "Weekly watch settings saved from the Updates page")
    bad: list[ValidationIssue] = []
    if not isinstance(sources, list) or not sources or not all(isinstance(s, str) for s in sources):
        bad.append(ValidationIssue("sources", "must be a non-empty list of strings"))
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
        bad.append(ValidationIssue("interval_days", "must be an integer of at least 1"))
    until: date | None = None
    if until_text is not None:
        try:
            if not isinstance(until_text, str):
                raise ValueError("not a string")
            until = date.fromisoformat(until_text)
        except ValueError:
            bad.append(ValidationIssue("until", "must be an ISO date (YYYY-MM-DD) or null"))
    if not isinstance(reason, str) or not reason.strip():
        bad.append(ValidationIssue("reason", "must be a non-empty string"))
    if bad:
        return 400, _issues(*bad)
    assert isinstance(sources, list) and isinstance(interval, int) and isinstance(reason, str)
    try:
        actor = project.human_actor()
        authorize_command(project, project.principal, "cli:protocol amend")
        protocol_id = watch_config_service.configure_watch(
            project, actor, sources=sources, interval_days=interval, until=until, reason=reason
        )
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    return 200, {"ok": True, "protocol_id": protocol_id}


def living_snapshot(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Close the week now: a human snapshot, as the local human (the Updates page)."""
    del body
    try:
        actor = project.human_actor()
        authorize_command(project, project.principal, "cli:living snapshot")
        recorded = snapshots_service.snapshot(project, actor, trigger="human")
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    return 200, {"ok": True, "snapshot_id": recorded.snapshot_id}


class ResumeRunner:
    """Starts `services.resume.resume` in a daemon thread, one at a time, and keeps the outcome of
    the last one (or its error) for the page. The thread is the only writer of `last`."""

    def __init__(self) -> None:
        self._gate = threading.Lock()
        self.last: dict[str, object] | None = None

    def start(self, project: Project, unit_cap: int | None) -> bool:
        """True when a resume was started; False while another one is still running."""
        if not self._gate.acquire(blocking=False):
            return False

        def run() -> None:
            try:
                outcome = resume_service.resume(project, unit_cap=unit_cap)
                self.last = outcome.model_dump(mode="json")
            except Exception as exc:  # the reply has gone; the page shows the error
                _LOG.exception("the resume from the hub failed")
                self.last = {"error": str(exc)}
            finally:
                self._gate.release()

        try:
            threading.Thread(target=run, name="queue-resume", daemon=True).start()
        except RuntimeError:
            self._gate.release()
            return False
        return True


def queue_resume(
    project: Project, body: dict[str, Any], runner: ResumeRunner
) -> tuple[int, dict[str, object]]:
    """Plan (`dry_run`) or start the resume of the interrupted work, as the local human."""
    dry_run = body.get("dry_run", False)
    cap = body.get("unit_cap")
    bad: list[ValidationIssue] = []
    if not isinstance(dry_run, bool):
        bad.append(ValidationIssue("dry_run", "must be true or false"))
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
        bad.append(ValidationIssue("unit_cap", "must be an integer of at least 1"))
    if bad:
        return 400, _issues(*bad)
    try:
        authorize_command(project, project.principal, "cli:queue resume")
    except FactoryValidationError as exc:
        return 403, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    if dry_run is True:
        try:
            plan = resume_service.resume(project, dry_run=True)
        except FactoryError as exc:
            return 403, _issues(ValidationIssue("permission", str(exc)))
        return 200, {"ok": True, "dry_run": True, "plan": plan.model_dump(mode="json")}
    if not runner.start(project, cap):
        return 409, _issues(ValidationIssue("resume", "another resume is still running"))
    return 202, {"ok": True, "dry_run": False, "started": True}


def interrupted_payload(project: Project) -> dict[str, object]:
    """`interrupted(project)` as JSON, with `is_clean`; read-only (no reconcile)."""
    found = resume_service.interrupted(project)
    return {**found.model_dump(mode="json"), "is_clean": found.is_clean}


def queue_process(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Start the headless runner for one stage as the local human; returns (status, body)."""
    stage = body.get("stage")
    cap = body.get("unit_cap", runner_service.DEFAULT_UNIT_CAP)
    bad: list[ValidationIssue] = []
    if not isinstance(stage, str) or not (stage == "all" or runner_service.is_stage_key(stage)):
        bad.append(ValidationIssue("stage", "must be all or one of " + runner_service.stage_keys()))
    if isinstance(cap, bool) or not isinstance(cap, int):
        bad.append(ValidationIssue("unit_cap", "must be an integer"))
    if bad:
        return 400, _issues(*bad)
    assert isinstance(stage, str) and isinstance(cap, int)
    try:
        authorize_command(project, project.principal, "cli:queue process")
    except FactoryValidationError as exc:
        return 403, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    try:
        if stage == "all":
            pipeline_id = pipeline_service.start_pipeline(project, unit_cap=cap)
            return 200, {"ok": True, "pipeline_id": pipeline_id, "stage": stage, "unit_cap": cap}
        run_id = runner_service.start_run(project, stage, unit_cap=cap)
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    return 200, {"ok": True, "run_id": run_id, "stage": stage, "unit_cap": cap}


def _layer_act(
    project: Project,
    command: str,
    issues: list[ValidationIssue],
    act: Callable[[Any], dict[str, object]],
) -> tuple[int, dict[str, object]]:
    """Run one layer act as the local human after `issues` (the parse) is empty; returns (status,
    body). Refusals are structured errors and nothing is written."""
    if issues:
        return 400, _issues(*issues)
    try:
        actor = project.human_actor()
        authorize_command(project, project.principal, command)
        return 200, {"ok": True, **act(actor)}
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))


def _required_str(body: dict[str, Any], key: str) -> tuple[str, list[ValidationIssue]]:
    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value, []
    return "", [ValidationIssue(key, "required")]


def mine_work(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Request mining of one work (`work_layers.request_mining(works=(work_id,))`)."""
    work_id, bad = _required_str(body, "work_id")
    reason, more = _optional_str(body, "reason")
    bad += more

    def act(actor: Any) -> dict[str, object]:
        request_id = work_layers.request_mining(
            project, actor, works=(work_id,), reason=reason or None
        )
        return {"request_id": request_id, "work_id": work_id}

    return _layer_act(project, "cli:mine request", bad, act)


def mine_layer(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Request mining of every included work of one layer (resolved to work ids at recording)."""
    layer, bad = _required_str(body, "layer")
    reason, more = _optional_str(body, "reason")
    bad += more

    def act(actor: Any) -> dict[str, object]:
        request_id = work_layers.request_mining(project, actor, layer=layer, reason=reason or None)
        return {"request_id": request_id, "layer": layer}

    return _layer_act(project, "cli:mine request", bad, act)


def move_layer(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Move one work to a layer of the latest scheme; the reason is required."""
    work_id, bad = _required_str(body, "work_id")
    layer, more = _required_str(body, "layer")
    reason, again = _required_str(body, "reason")
    bad += more + again

    def act(actor: Any) -> dict[str, object]:
        event_id = work_layers.move_layer(project, actor, work_id, layer, reason)
        return {"event_id": event_id, "work_id": work_id, "layer": layer}

    return _layer_act(project, "cli:layers move", bad, act)


def layers_payload(project: Project) -> dict[str, object]:
    """The latest scheme's layer ids and each known work's layer (read-only; the page's selects)."""
    from factory.services.reference_layers import current_scheme

    scheme = current_scheme(project)
    return {
        "layers": [] if scheme is None else [d.id for d in scheme.layers],
        "works": {
            work: {"layer": found.layer, "source": found.source}
            for work, found in work_layers.layers_of(project).items()
        },
    }


def export_works_zip(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Build the export zip of the works the page selected (`work_ids`, optional `pdfs`) as the
    local human (`cli:export works`); `pdfs: true` also needs `confirm: true` and the human
    confirmation permission (licensed files). Read-only: no event. On success the body names the zip
    (`_zip`, in a fresh temporary directory the handler removes after sending it) and its
    download name (`_name`); a refusal is a structured error and nothing is left behind."""
    ids = body.get("work_ids")
    pdfs = body.get("pdfs", False)
    confirm = body.get("confirm", False)
    bad: list[ValidationIssue] = []
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        bad.append(ValidationIssue("work_ids", "must be a list of work ids"))
    if not isinstance(pdfs, bool):
        bad.append(ValidationIssue("pdfs", "must be true or false"))
    if not isinstance(confirm, bool):
        bad.append(ValidationIssue("confirm", "must be true or false"))
    if bad:
        return 400, _issues(*bad)
    assert isinstance(ids, list)
    try:
        authorize_export_works(project, project.principal, pdfs=bool(pdfs), confirm=bool(confirm))
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 403, _issues(ValidationIssue("permission", str(exc)))
    # beside the project, not in /tmp (a small tmpfs that is often full)
    scratch = project.paths.dir / "ops" / "export-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="rf-export-", dir=scratch))
    try:
        slug = project.paths.slug
        name = f"{slug}-works-{date.today().isoformat()}.zip"
        export_works_service.export_works(
            project,
            export_works_service.Selection(
                export_works_service.work_ids_of(ids), "selected in the explorer"
            ),
            tmp / name,
            pdfs=bool(pdfs),
            max_works=export_works_service.MAX_WORKS,
            max_bytes=export_works_service.MAX_BYTES,
        )
    except FactoryValidationError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        return 403, _issues(ValidationIssue("permission", str(exc)))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return 200, {"ok": True, "_zip": str(tmp / name), "_name": name}


_ROUTES: Final[dict[str, Callable[..., tuple[int, dict[str, object]]]]] = {
    "/api/feed/react": feed_react,
    "/api/feed/add": feed_add,
    "/api/feed/configure": feed_configure,
    "/api/watch/configure": watch_configure,
    "/api/living/snapshot": living_snapshot,
    "/api/queue/process": queue_process,
    "/api/queue/resume": queue_resume,
    "/api/mine/work": mine_work,
    "/api/mine/layer": mine_layer,
    "/api/layers/move": move_layer,
    EXPORT_ROUTE: export_works_zip,
}


class Rebuilder:
    """Rebuilds stale products in the background, at most once per `min_gap` seconds."""

    def __init__(self, project: Project, *, min_gap: float, poll: float = 15.0) -> None:
        self._project = project
        self._min_gap = min_gap
        self._poll = poll
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="site-rebuilder", daemon=True)
        self.building = False
        self.last_build_at: float | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def statuses(self) -> list[site_service.ProductStatus]:
        with self._lock:
            return site_service.status(self._project)

    def try_statuses(self) -> list[site_service.ProductStatus] | None:
        """The statuses, or None at once when a rebuild holds the lock (it can take minutes)."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return site_service.status(self._project)
        finally:
            self._lock.release()

    def rebuild_if_stale(self) -> list[str]:
        """Build the stale products now (ignoring `min_gap`); returns the ids built."""
        with self._lock:
            stale = [s.id for s in site_service.status(self._project) if s.stale]
            if not stale:
                return []
            self.building = True
            try:
                results = site_service.build(self._project, only=stale)
                self.last_error = next((r.error for r in results if r.error), None)
            finally:
                self.building = False
                self.last_build_at = time.monotonic()
            return [r.id for r in results if r.built]

    def _run(self) -> None:
        while not self._stop.is_set():
            due = (
                self.last_build_at is None or time.monotonic() - self.last_build_at >= self._min_gap
            )
            if due:
                self.rebuild_if_stale()
            self._stop.wait(self._poll)


class Slot:
    """One project's live parts inside a server: its built `site/` folder, rebuilder, write lock,
    advance gate and resume runner. A write for one project never takes another's lock."""

    def __init__(self, project: Project, *, min_gap: float) -> None:
        self.project = project
        self.slug = project.paths.slug
        self.root = site_service.site_dir(project)
        self.rebuilder = Rebuilder(project, min_gap=min_gap)
        self.write_lock = threading.Lock()
        self.advance_gate = threading.Lock()
        self.resumer = ResumeRunner()

    def prepare(self) -> None:
        """Write the project's hub page, so a served project is never without its hub."""
        self.root.mkdir(parents=True, exist_ok=True)
        site_service.render_hub(self.project)


class Mount(NamedTuple):
    """Where a request lands: the project's slot, the path inside its site folder (query kept)
    and the URL prefix the project is served under ("" alone, "/p/<slug>" in the main server)."""

    slot: Slot
    rel: str
    prefix: str


def _with_meta(text: str, token: str, prefix: str) -> str:
    """`text` with the token and API-prefix `<meta>` tags after `<head>` (an action page's)."""
    meta = _TOKEN_META.format(token) + _API_META.format(prefix)
    return text.replace("<head>", "<head>" + meta, 1) if "<head>" in text else meta + text


def _scope_of(path: str) -> site_auth.Scope:
    """The scope a URL path belongs to, read from the path alone (nothing is opened): a project
    under `/p/<slug>/`, else the hub."""
    if path.startswith(PROJECT_PREFIX):
        slug = path[len(PROJECT_PREFIX) :].partition("/")[0]
        if slug:
            return site_auth.Scope(slug)
    return site_auth.Scope(None)


def _handler_class(
    resolve: Callable[[str], Mount | None],
    auth: site_auth.Authenticator,
    portal: Callable[[str], tuple[int, str, bytes] | None] | None,
    hub_acts: Mapping[str, Callable[[dict[str, Any]], tuple[int, dict[str, object]]]] | None = None,
) -> type[SimpleHTTPRequestHandler]:
    """The request handler. `resolve` maps a URL path to a `Mount` (None: not a project path);
    `portal` answers the paths that belong to no project (status, content type, body) or None.
    Every request, read or write, is first put to `auth.check` (the seam, `site_auth`); the handler
    decides nothing about hosts, origins or tokens itself."""

    class Handler(SimpleHTTPRequestHandler):
        def _deny(self, code: int, message: str) -> None:
            body = message.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _allowed(self, scope: site_auth.Scope, act: str) -> bool:
            """Put the request to the seam; True when it may go on (the actor is the human)."""
            decision = auth.check(
                site_auth.AuthRequest(
                    method=self.command,
                    path=self.path,
                    host=self.headers.get("Host") or "",
                    origin=self.headers.get("Origin"),
                    credential=self.headers.get(TOKEN_HEADER),
                    scope=scope,
                    act=act,
                )
            )
            if decision.allowed and decision.actor == "human":
                return True
            self._deny(403, "forbidden")
            return False

        def _json(self, code: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_zip(self, path: Path, name: str) -> None:
            """Stream `path` as a download, then remove its temporary directory."""
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(path.stat().st_size))
                self.end_headers()
                with path.open("rb") as handle:
                    shutil.copyfileobj(handle, self.wfile, 1024 * 1024)
            finally:
                shutil.rmtree(path.parent, ignore_errors=True)

        def _html(self, text: str) -> None:
            body = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _feed_page(self, url: str, slot: Slot) -> Path | None:
            """The built HTML file `url` names under `/feed/`, `/queue/` or `/explorer/`, if any."""
            if not any(url == f"/{name}" or url.startswith(f"/{name}/") for name in _ACTION_PAGES):
                return None
            self.directory = str(slot.root)
            target = Path(self.translate_path(url))
            if target.is_dir():
                target = target / "index.html"
            if target.suffix != ".html" or not target.is_file():
                return None
            return target

        def do_GET(self) -> None:
            full = self.path.split("?", 1)[0].split("#", 1)[0]
            if not self._allowed(_scope_of(full), "read"):
                return
            mount = resolve(self.path)
            if mount is None:
                answer = None if portal is None else portal(full)
                if answer is None:
                    self._deny(404, "not found")
                    return
                code, kind, body = answer
                self.send_response(code)
                if code in (301, 302):
                    self.send_header("Location", kind)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            slot = mount.slot
            url = mount.rel.split("?", 1)[0].split("#", 1)[0]
            if url in ("/settings", "/settings/"):
                self._html(
                    _with_meta(
                        site_settings.render_settings(slot.project, slot.slug),
                        auth.page_credential(site_auth.Scope(slot.slug)),
                        mount.prefix,
                    )
                )
                return
            page = self._feed_page(url, slot)
            if page is not None:
                text = page.read_text(encoding="utf-8")
                self._html(
                    _with_meta(text, auth.page_credential(site_auth.Scope(slot.slug)), mount.prefix)
                )
                return
            if mount.prefix and url in ("/", "/index.html"):
                hub = slot.root / "index.html"
                if hub.is_file():
                    text = hub.read_text(encoding="utf-8")
                    self._html(text.replace("</body>", PORTAL_LINK + "</body>", 1))
                    return
            if url == "/api/status":
                # never wait for a rebuild (it holds the lock for minutes): a waiting poll keeps
                # one of the browser's six connections to the host, and enough of them stall
                # every navigation; while building, answer at once with no product rows
                tried = slot.rebuilder.try_statuses()
                self._json(
                    200,
                    {
                        "building": tried is None or slot.rebuilder.building,
                        "error": slot.rebuilder.last_error,
                        "products": [s.model_dump(mode="json") for s in tried or []],
                    },
                )
                return
            if url == "/api/queue/interrupted":
                try:
                    payload = interrupted_payload(slot.project)
                except FactoryError as exc:
                    self._json(500, _issues(ValidationIssue("interrupted", str(exc))))
                    return
                self._json(200, {**payload, "last_resume": slot.resumer.last})
                return
            if url == "/api/layers":
                try:
                    self._json(200, layers_payload(slot.project))
                except FactoryError as exc:
                    self._json(500, _issues(ValidationIssue("layers", str(exc))))
                return
            if url == "/api/queue/runs":
                runs = runner_service.run_status(slot.project, reconcile=False)
                pipelines = pipeline_service.pipeline_status(slot.project)
                self._json(
                    200,
                    {
                        "runs": [r.model_dump(mode="json") for r in runs],
                        "pipelines": [p.model_dump(mode="json") for p in pipelines],
                    },
                )
                return
            self.directory = str(slot.root)
            self.path = mount.rel
            super().do_GET()

        def _refuse(self) -> None:
            self._deny(405, "read-only")

        def do_POST(self) -> None:
            mount = resolve(self.path)
            hub_act = (
                hub_acts.get(self.path.split("?", 1)[0]) if hub_acts and mount is None else None
            )
            route = None if mount is None else _ROUTES.get(mount.rel.split("?", 1)[0])
            if hub_act is None and (mount is None or route is None):
                self._deny(404, "not found")
                return
            slot = None if mount is None else mount.slot
            act = self.path.split("?", 1)[0] if mount is None else mount.rel.split("?", 1)[0]
            if not self._allowed(site_auth.Scope(None if slot is None else slot.slug), act):
                return
            kind = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if kind != "application/json":
                self._deny(415, "json only")
                return
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self._deny(411, "length required")
                return
            if length < 0 or length > (MAX_EXPORT_BODY if act == EXPORT_ROUTE else MAX_BODY):
                self._deny(413, "body too large")
                return
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                self._json(400, _issues(ValidationIssue("body", "not valid JSON")))
                return
            if not isinstance(body, dict):
                self._json(400, _issues(ValidationIssue("body", "must be a JSON object")))
                return
            if hub_act is not None:
                code, payload = hub_act(body)
                self._json(code, payload)
                return
            assert slot is not None and route is not None
            project = slot.project
            if route in (feed_react, feed_configure, mine_work, mine_layer, move_layer):
                with slot.write_lock:
                    code, payload = route(project, body)
            elif route is queue_resume:
                code, payload = queue_resume(project, body, slot.resumer)
            elif route is export_works_zip:
                code, payload = export_works_zip(project, body)
                if code == 200:
                    self._send_zip(Path(str(payload["_zip"])), str(payload["_name"]))
                    return
            else:
                # no lock: `feed add` looks the paper up over the network, and each service
                # serialises its own index work (`send` and the lookup take the index lock)
                code, payload = route(project, body)
            if code == 200 and route is feed_add:
                _start_advance(project, slot.advance_gate)
            # the feed product turns stale by the event log; the background rebuild picks it up
            self._json(code, payload)

        do_PUT = do_DELETE = do_PATCH = _refuse

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def make_server(
    project: Project,
    port: int = DEFAULT_PORT,
    *,
    min_gap: float = 300.0,
    background: bool = True,
    authenticator: site_auth.Authenticator | None = None,
) -> tuple[ThreadingHTTPServer, Rebuilder]:
    """A server for `<project>/site/` on 127.0.0.1:`port` (0 picks a free port) and its rebuilder
    (started when `background`). The hub page is written first, so the server never starts empty."""
    slot = Slot(project, min_gap=min_gap)
    slot.prepare()
    holder: list[ThreadingHTTPServer] = []
    default = site_auth.LoopbackTokenAuth()
    default.bind(lambda: holder[0].server_address[1])
    handler = _handler_class(lambda path: Mount(slot, path, ""), authenticator or default, None)
    httpd = ThreadingHTTPServer((HOST, port), handler)
    holder.append(httpd)
    if background:
        slot.rebuilder.start()
    return httpd, slot.rebuilder


PORTAL_FEED_ITEMS: Final = 5
"""How many New papers entries the portal page lists; the feed page has them all."""
PROJECT_PREFIX: Final = "/p/"
FEED_CHECK_EVERY: Final = 1800.0
WARM_EVERY: Final = 5.0
"""Seconds between the background reads that keep the feed views of `site_hub_feed.collect` warm."""
"""Seconds between the timer's looks at whether the feed is due (a run is due once per
`interval_days`, so most looks do nothing)."""


class FeedRunner:
    """Runs the feed of every project in a daemon thread, one run at a time, and keeps the outcome
    of the last one for the page. `run(refetch)` does the work (`feed_run_all`; `refetch` skips the
    shared cache). The thread is the only writer of `last`."""

    def __init__(self, run: Callable[[bool], feed_service.FeedRunAll]) -> None:
        self._run = run
        self._gate = threading.Lock()
        self.last: dict[str, object] | None = None
        self.running = False

    def start(self, *, refetch: bool = False) -> bool:
        """True when a run was started; False while another one is still running."""
        if not self._gate.acquire(blocking=False):
            return False

        def work() -> None:
            self.running = True
            try:
                outcome = self._run(refetch)
                self.last = {"refetch": refetch, **outcome.model_dump(mode="json")}
            except Exception as exc:  # the caller has gone; the page shows the error
                _LOG.exception("the feed run failed")
                self.last = {"refetch": refetch, "error": f"{type(exc).__name__}: {exc}"}
            finally:
                self.running = False
                self._gate.release()

        try:
            threading.Thread(target=work, name="feed-run", daemon=True).start()
        except RuntimeError:
            self._gate.release()
            return False
        return True


class FeedTimer:
    """Starts a due feed run when the hub starts and then every `every` seconds while it runs. It
    only asks the runner; whether anything is fetched is the feed's own cadence (`due`)."""

    def __init__(self, runner: FeedRunner, *, every: float = FEED_CHECK_EVERY) -> None:
        self._runner = runner
        self._every = every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="feed-timer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._runner.start()
            self._stop.wait(self._every)


class MainHub:
    """The parts of the main server that know several projects: which exist (scanned under the
    factory root, each time), their slots (opened on first use, each with its hub written at once)
    and the portal page. `open_project` opens and authorises one project by slug."""

    def __init__(
        self,
        root: Path,
        slugs: Callable[[], list[str]],
        open_project: Callable[[str], Project],
        *,
        min_gap: float,
        background: bool,
        feed: FeedRunner | None = None,
        feed_every: float = FEED_CHECK_EVERY,
        create: Callable[[object, object, object], site_create.Created] | None = None,
    ) -> None:
        self.feed = feed
        self._create = create
        self.auth: site_auth.Authenticator = site_auth.LoopbackTokenAuth()
        """The seam; `make_main_server` may replace it before serving."""
        self._timer = FeedTimer(feed, every=feed_every) if feed is not None and background else None
        self._root = root
        self._slugs = slugs
        self._open = open_project
        self._min_gap = min_gap
        self._background = background
        self._slots: dict[str, Slot] = {}
        self._lock = threading.Lock()
        self._warm_stop = threading.Event()
        self._warm_every = WARM_EVERY

    def start_warmer(self) -> None:
        """Read every project's feed view now and again every `WARM_EVERY` seconds, so the first
        page view after a start or after new events is served from `collect`'s cache instead of
        paying the read of the whole log. A read that fails is skipped; nothing is written."""

        def loop() -> None:
            while True:
                with contextlib.suppress(Exception):  # a background read never takes the hub down
                    self.feed_views()
                if self._warm_stop.wait(self._warm_every):
                    return

        threading.Thread(target=loop, name="feed-warm", daemon=True).start()

    def slot(self, slug: str) -> Slot | None:
        """The slot of a scanned project (None for an unknown slug), opened and prepared once."""
        with self._lock:
            found = self._slots.get(slug)
            if found is not None:
                return found
            if slug not in self._slugs():
                return None
            fresh = Slot(self._open(slug), min_gap=self._min_gap)
            fresh.prepare()
            if self._background:
                fresh.rebuilder.start()
            self._slots[slug] = fresh
            return fresh

    def prepare_all(self) -> list[str]:
        """Open every scanned project and write its hub (done at start: a project is never
        served without its hub); returns the slugs."""
        slugs = self._slugs()
        for slug in slugs:
            self.slot(slug)
        return slugs

    def resolve(self, path: str) -> Mount | None:
        """`/p/<slug>/<rest>` to its mount; anything else (and `/p/<slug>` alone) is None."""
        if not path.startswith(PROJECT_PREFIX):
            return None
        url, _, query = path.partition("?")
        slug, sep, rest = url[len(PROJECT_PREFIX) :].partition("/")
        if not sep or not slug:
            return None
        found = self.slot(slug)
        if found is None:
            return None
        rel = "/" + rest + ("?" + query if query else "")
        return Mount(found, rel, PROJECT_PREFIX + slug)

    def rows(self) -> list[site_portal.PortalRow]:
        out: list[site_portal.PortalRow] = []
        registry = site_portal.load_registry(self._root)
        for slug, title in site_portal.listed(self._slugs(), registry):
            found = self.slot(slug)
            if found is None:
                continue
            with found.project.index.connect() as conn:
                events = int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())
            # never wait for a rebuild: it holds the rebuilder's lock for minutes
            tried = found.rebuilder.try_statuses()
            building = tried is None
            states = tried or []
            out.append(
                site_portal.PortalRow(
                    slug=slug,
                    title=title,
                    events=events,
                    stale=sum(s.stale or s.error is not None for s in states),
                    built=site_service.built_count(found.project)
                    if building
                    else sum(s.built for s in states),
                    hub_ready=(found.root / "index.html").is_file(),
                    building=building,
                )
            )
        return out

    def portal(self, path: str) -> tuple[int, str, bytes] | None:
        """The answer for a path that belongs to no project: (status, content type or, for a
        redirect, the location, body), or None."""
        if path in ("/", "/index.html"):
            views = self.feed_views()
            panel = site_hub_feed.render_feed_panel(
                site_hub_feed.top_entries(views, PORTAL_FEED_ITEMS),
                ranked_total=site_hub_feed.ranked_total(views),
            )
            page = site_portal.render_portal(
                self.rows(),
                create_token=self.hub_token() if self._create else None,
                feed_panel=panel,
            )
            return 200, "text/html; charset=utf-8", page.encode()
        if path in ("/feed", "/feed/"):
            if path == "/feed":
                return 301, "/feed/", b""
            return 200, "text/html; charset=utf-8", self.feed_page().encode()
        if path in ("/backlog", "/catalog"):
            return 301, path + "/", b""
        if path == "/backlog/":
            doc = site_chrome.with_bar(site_backlog.render_backlog(), "backlog")
            return 200, "text/html; charset=utf-8", doc.encode()
        if path == "/catalog/":
            return 200, "text/html; charset=utf-8", self.catalog_page().encode()
        if path == "/api/feed/runner":
            body = json.dumps(site_hub_feed.runner_payload(self.feed)).encode()
            return 200, "application/json; charset=utf-8", body
        if path == "/api/projects":
            body = json.dumps(
                {"projects": [r._asdict() for r in self.rows()]}, ensure_ascii=False
            ).encode()
            return 200, "application/json; charset=utf-8", body
        if path.startswith(PROJECT_PREFIX) and "/" not in path[len(PROJECT_PREFIX) :]:
            slug = path[len(PROJECT_PREFIX) :]
            if slug and self.slot(slug) is not None:
                return 301, f"{PROJECT_PREFIX}{slug}/", b""
        return None

    def hub_token(self) -> str:
        """The write token of the hub's own acts (`/api/feed/run`, `/api/feed/refetch`)."""
        return self.auth.page_credential(site_auth.Scope(None))

    def feed_views(self) -> list[site_hub_feed.ProjectFeed]:
        """Every listed project's feed state, read from its events at request time."""
        registry = site_portal.load_registry(self._root)
        views = []
        for slug, title in site_portal.listed(self._slugs(), registry):
            found = self.slot(slug)
            if found is None:
                continue
            views.append(
                site_hub_feed.collect(
                    found.project, slug, title, self.auth.page_credential(site_auth.Scope(slug))
                )
            )
        return views

    def feed_page(self) -> str:
        """The `/feed/` page, read from every listed project's events at request time."""
        return site_hub_feed.render_feed_page(
            self.feed_views(), site_hub_feed.runner_payload(self.feed), self.hub_token()
        )

    def catalog_page(self) -> str:
        """The capability catalog (skills and tools are the factory's, not a project's), derived at
        request time with the settings of any listed project."""
        for slug in self._slugs():
            found = self.slot(slug)
            if found is not None:
                doc = site_catalog_page.render_catalog(found.project.settings)
                return site_chrome.with_bar(doc, "catalog")
        return site_chrome.with_bar(
            site_service.page(
                "Capability catalog", "<p>No project found under the factory root.</p>"
            ),
            "catalog",
        )

    def start_feed_run(self, *, refetch: bool) -> tuple[int, dict[str, object]]:
        """Start one feed run for every project (the hub acts); one at a time."""
        if self.feed is None:
            return 503, _issues(ValidationIssue("feed", "the feed runner is off"))
        if not self.feed.start(refetch=refetch):
            return 409, _issues(ValidationIssue("feed", "a feed run is already in progress"))
        return 202, {"ok": True, "started": True, "refetch": refetch}

    def create_project(self, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
        """The create-project act (the portal's form): as the local human, through the injected
        creator (`site_create.create_project`); the new project's hub is written at once."""
        if self._create is None:
            return 503, _issues(ValidationIssue("create", "creating projects is off"))
        try:
            made = self._create(body.get("slug"), body.get("title"), body.get("profile"))
        except FactoryValidationError as exc:
            return 400, _issues(*exc.issues)
        except FactoryError as exc:
            return 403, _issues(ValidationIssue("permission", str(exc)))
        self.slot(made.slug)
        return 200, {
            "ok": True,
            **made.model_dump(mode="json"),
            "url": f"{PROJECT_PREFIX}{made.slug}/",
        }

    def inbox_add(self, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
        """The add-to-inbox act (the portal's form): capture one link or identifier in a listed
        project's inbox as the local human, like `factory inbox add`. A link whose identifier is
        already in the inbox is a `duplicate` and writes nothing. Offline; no lookup runs."""
        slug, bad = _optional_str(body, "project")
        value, more = _optional_str(body, "value")
        note, extra = _optional_str(body, "note")
        bad += more + extra
        if not slug:
            bad.append(ValidationIssue("project", "required"))
        if value is None or not value.strip():
            bad.append(ValidationIssue("value", "required"))
        if bad:
            return 400, _issues(*bad)
        assert slug is not None and value is not None
        found = self.slot(slug)
        if found is None:
            return 400, _issues(ValidationIssue("project", "unknown project"))
        project = found.project
        link = value.strip()
        try:
            actor = project.human_actor()
            authorize_command(project, project.principal, "cli:inbox add")
            with found.write_lock, project.index.exclusive():
                project.index.sync()
                same = inbox_service.find_open_duplicate(project, link)
                if same is not None:
                    return 200, {"ok": True, "duplicate": True, "item_id": same}
                result = inbox_service.add_links(
                    project, actor, [inbox_service.LinkInput(link, note=note)], Channel.CLI
                )
        except FactoryValidationError as exc:
            return 400, _issues(*exc.issues)
        except FactoryError as exc:
            return 403, _issues(ValidationIssue("permission", str(exc)))
        if result.rejected:
            return 400, _issues(*result.rejected[0].issues)
        return 200, {"ok": True, "duplicate": False, "item_id": result.written[0]}

    def acts(self) -> dict[str, Callable[[dict[str, Any]], tuple[int, dict[str, object]]]]:
        return {
            "/api/feed/run": lambda _body: self.start_feed_run(refetch=False),
            "/api/feed/refetch": lambda _body: self.start_feed_run(refetch=True),
            "/api/projects/create": self.create_project,
            "/api/inbox/add": self.inbox_add,
        }

    def start_feed(self) -> None:
        """Start the feed timer (a due run now, then every `feed_every` seconds), if any."""
        if self._timer is not None:
            self._timer.start()

    def stop(self) -> None:
        self._warm_stop.set()
        if self._timer is not None:
            self._timer.stop()
        for found in list(self._slots.values()):
            found.rebuilder.stop()


def make_main_server(
    hub: MainHub,
    port: int = DEFAULT_PORT,
    *,
    secret: bytes | None = None,
    authenticator: site_auth.Authenticator | None = None,
) -> ThreadingHTTPServer:
    """The main server on 127.0.0.1:`port`: the portal at `/` and each project at `/p/<slug>/`.
    Every scanned project's hub is written before the first request. Each project has its own
    write token, so a token from one project's pages writes to no other. `authenticator` replaces
    the seam (`site_auth`); the default is loopback and per-scope tokens from `secret`."""
    holder: list[ThreadingHTTPServer] = []
    if authenticator is None:
        default = site_auth.LoopbackTokenAuth(secret)
        default.bind(lambda: holder[0].server_address[1])
        authenticator = default
    hub.auth = authenticator
    hub.prepare_all()
    hub.start_feed()
    if hub._background:
        hub.start_warmer()
    handler = _handler_class(hub.resolve, authenticator, hub.portal, hub.acts())
    httpd = ThreadingHTTPServer((HOST, port), handler)
    holder.append(httpd)
    return httpd
