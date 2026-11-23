"""Serve the project site on 127.0.0.1 and keep it current (plan site-hub, step 6).

The hub is a folder of static files (`<project>/site/`); this server shows it over HTTP and adds
`/api/status` (each product's build time and staleness, read from the manifest and the event log;
it never waits for a build). A product is rebuilt when its page is opened and it is stale
(IDEA-96): one worker thread per project builds the opened products one at a time, and a small
page that reloads itself stands in meanwhile. With `eager`, a second thread also rebuilds every
stale product, at most once per `min_gap` seconds (the behaviour before IDEA-96).

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
  and writes nothing). A project page uses `POST /p/<slug>/api/inbox/add` (`value`, optional
  `note`; the project is the slot's, a `project` field is refused) and
  `POST /p/<slug>/api/feed/run|refetch` (the same hub-wide feed run) with its own token; the hub
  token is on no project page. A refusal is a structured error, nothing is
  written. `GET /api/layers` reads the latest scheme's layer ids and each work's layer. Any
  other POST path is 404; PUT, DELETE and PATCH are 405. Apart from those acts the server writes
  nothing but the site folder, through `site.build`.
- Hub v2 (plan hub-ui, `services/hub_serve.py`) is served at `<prefix>/ui/`: pages, versioned
  assets, cached payloads (`data/<name>.json`, ETag, 503 while building) and `trace`, all read-only,
  plus one act, `POST <prefix>/ui/act/snowball-add` (`work_id`: puts an outside work in the inbox as
  the local human, `cli:inbox add`). The pages' other acts are the routes above. Further read-only
  routes: `ui/data/sources-doc-<document_id>.json` (one converted document: texts, lost and added
  runs), `ui/file/original|markdown/<document_id>` (the stored files, by registered id only),
  `ui/study/<registration_id>` (a registered study file, from its stored blob, by id only),
  `ui/ops/<path>` (a file of the project's `ops/` folder: no `..`, absolute path, symlink or
  directory, size capped), `ui/download/wiki.zip` (the vault, built once per fingerprint),
  `ui/status.json` (per payload: fresh, built_at, error) and `GET /api/screening`
  (`dashboard.screening_live`). None of them writes an event.
- `POST /api/queue/resume` with `dry_run` plans in the request and writes nothing. A real resume
  runs `services.resume.resume` in a daemon thread, one at a time (`ResumeRunner`), because its
  deterministic steps look papers up and convert them and must not run in a request; the reply is
  202 and the outcome (ids, refusals) is kept as `last_resume` in `GET /api/queue/interrupted`.
  `GET /api/queue/interrupted` reads `interrupted()` and reconciles nothing.
- After a successful `POST /api/feed/add` the deterministic steps (`work_queue.advance`) start in
  a daemon thread, at most one per server; the reply is not delayed. A thread already running
  means the new call is skipped. Conversion runs only in that thread, never in a request.
  `GET /api/queue/runs` reads the runs and reconciles nothing.
- `GET /api/activity` (IDEA-98) answers `services.activity.activity_cached` as JSON: the held
  tasks, the open passes, the long operations and the `*.live` traces. Read-only; the answer is
  reused for a few seconds while the event log is unchanged, so the Activity page's poll costs
  one reading per project per window.
- A POST needs, all at once: a loopback Host, the per-start token in `X-Factory-Token` (compared in
  constant time), `Content-Type: application/json`, a body of at most 16 KiB and, if an Origin is
  sent, this server's own origin. Otherwise 403 (413 or 415 for size or type) and nothing is
  written. The token is made at server start, is injected into `/feed/`, `/queue/`, `/explorer/`,
  `/updates/` and `/activity/` pages only and is never written to the files on disk.
- The actor is the local human principal and each act is authorised by its command row
  (`cli:feed react`, `cli:feed add`, `cli:queue process`, `cli:queue resume`), as the CLI does.
- Loopback only: a request whose Host is not 127.0.0.1, localhost or [::1] is refused.
- One build runs at a time; a product that fails is recorded by `site.build` and the others go on.
"""

from __future__ import annotations

import contextlib
import html as html_lib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final, Literal, NamedTuple
from urllib.parse import parse_qsl, unquote

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.model.feed import FeedNote, FeedReaction
from factory.model.screening import Channel
from factory.services import activity as activity_service
from factory.services import dashboard as dashboard_service
from factory.services import export_works as export_works_service
from factory.services import feed as feed_service
from factory.services import (
    hub_chat,
    hub_intuition,
    hub_learn,
    hub_serve,
    site_auth,
    site_backlog,
    site_catalog_page,
    site_chrome,
    site_create,
    site_hub_feed,
    site_portal,
    site_progress,
    site_settings,
    work_layers,
    work_queue,
)
from factory.services import inbox as inbox_service
from factory.services import pipeline as pipeline_service
from factory.services import resume as resume_service
from factory.services import runner as runner_service
from factory.services import site as site_service
from factory.services import snapshots as snapshots_service
from factory.services import watch_config as watch_config_service
from factory.services.access import authorize_command, authorize_export_works
from factory.services.context import Project
from factory.services.hint_input import HintInput
from factory.sources.fulltext.registry import default_routes
from factory.sources.registry import default_sources

HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8766
MAX_BODY: Final = 16 * 1024
MAX_EXPORT_BODY: Final = 256 * 1024
"""The export route takes a list of work ids (up to the cap of 200 works, each id up to a few
hundred characters), which the usual 16 KiB body limit would cut."""
EXPORT_ROUTE: Final = "/api/export/works"
UI_SNOWBALL_ROUTE: Final = "/ui/act/snowball-add"
UI_CHAT_ROUTES: Final = {
    "/ui/act/chat-request": ("cli:chat request", hub_chat.order_chat),
    "/ui/act/chat-batch": ("cli:chat request", hub_chat.order_chat_batch),
    "/ui/act/chat-rate-argument": ("cli:sheets rate", hub_chat.rate_argument_act),
    "/ui/act/chat-rate-sentence": ("cli:answers rate", hub_chat.rate_sentence_act),
    "/ui/act/chat-balance": ("cli:sheets balance", hub_chat.balance_act),
}
"""The hub Chat page's researcher acts (night feature N5): route, the command it is authorised
as, and the service act. Each is the local human's; nothing else on `/ui/` writes."""
UI_INTUITION_ROUTES: Final = {
    "/ui/act/intuition-review": ("cli:interpretations review", hub_intuition.act_review),
}
"""The hub Intuition page's researcher act: an interpretation review, authorised as the CLI
command of its kind; the service keeps the reviewer-is-not-author rule."""
UI_DOC_PREFIX: Final = "data/sources-doc-"
"""The lazy payload family of one converted document (`hub_sources.document_detail`)."""
UI_PREFIX: Final = "/ui"
"""Hub v2 (plan hub-ui): `<prefix>/ui/` pages, `assets/`, `data/<payload>.json` and `trace`; the
only write is the snowball act."""
TOKEN_HEADER: Final = "X-Factory-Token"
_ACTION_PAGES: Final = ("feed", "queue", "explorer", "updates", "activity")
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


def _hint_input(value: object) -> tuple[HintInput | None, list[ValidationIssue]]:
    """The optional `hints` object of a feed add: strings `layer`, `category`, `taxonomy` and
    `miner_notes`, each optional; anything else is a 400 issue."""
    if value is None:
        return None, []
    if not isinstance(value, dict):
        return None, [ValidationIssue("hints", "must be an object")]
    known = {"layer", "category", "taxonomy", "miner_notes"}
    issues = [ValidationIssue(f"hints.{k}", "unknown field") for k in value if k not in known]
    issues += [
        ValidationIssue(f"hints.{k}", "must be a string")
        for k, v in value.items()
        if k in known and v is not None and not isinstance(v, str)
    ]
    if issues:
        return None, issues
    return (
        HintInput(
            value.get("layer"),
            value.get("category"),
            value.get("taxonomy"),
            value.get("miner_notes"),
        ),
        [],
    )


def feed_add(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Send the entry to the inbox and look it up, as the local human; returns (status, body)."""
    entry_id = body.get("entry_id")
    ranking_id, bad = _optional_str(body, "ranking_id")
    note_text, more = _optional_str(body, "note")
    bad += more
    hints, hint_bad = _hint_input(body.get("hints"))
    bad += hint_bad
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
            project,
            actor,
            entry_id,
            sources=_sources(),
            note=note,
            ranking_id=ranking_id,
            hints=hints,
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


def ui_snowball_add(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """The hub v2 "Add to snowball" act: an outside work goes to the inbox as the researcher's link
    (`hub_serve.snowball_add`; authorised as `cli:inbox add`). Nothing else on `/ui/` writes."""
    work_id = body.get("work_id")
    return _layer_act(
        project,
        "cli:inbox add",
        [],
        lambda actor: hub_serve.snowball_add(project, actor, work_id),
    )


def _chat_route(
    command: str, act: Callable[[Project, Any, dict[str, Any]], dict[str, object]]
) -> Callable[[Project, dict[str, Any]], tuple[int, dict[str, object]]]:
    def route(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
        # a request is authorised as the CLI command of its kind
        name = command
        if command == "cli:chat request":
            kind = body.get("kind")
            if kind not in ("ask", "spar"):  # no access row is chosen for an unknown kind
                return 400, _issues(ValidationIssue("kind", "must be spar or ask"))
            name = f"cli:chat request {kind}"
        return _layer_act(project, name, [], lambda actor: act(project, actor, body))

    return route


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


def inbox_add_in(found: Slot, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Capture one link or identifier in `found`'s inbox as the local human, like `factory inbox
    add`. The project is the slot's; a `project` field of the body is never read here. A link
    whose identifier is already in the inbox is a `duplicate` and writes nothing. Offline."""
    value, bad = _optional_str(body, "value")
    note, extra = _optional_str(body, "note")
    bad += extra
    if value is None or not value.strip():
        bad.append(ValidationIssue("value", "required"))
    if bad:
        return 400, _issues(*bad)
    assert value is not None
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


def project_inbox_add(slot: Slot, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """`POST /p/<slug>/api/inbox/add` {value, note}: the project is the slot's; a `project` field
    is refused, so a page of one project cannot write into another."""
    if "project" in body:
        return 400, _issues(ValidationIssue("project", "not accepted; the project is the page's"))
    return inbox_add_in(slot, body)


def feed_run_here(_project: Project, _body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Marker route `POST /p/<slug>/api/feed/run`: `do_POST` hands it to the hub's feed runner.
    The feed is hub-wide (one run covers every project), so a project page starting it is the
    same act as the hub's, under the project token."""
    raise NotImplementedError


def feed_refetch_here(_project: Project, _body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Marker route `POST /p/<slug>/api/feed/refetch`; see `feed_run_here`."""
    raise NotImplementedError


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
    UI_SNOWBALL_ROUTE: ui_snowball_add,
    **{path: _chat_route(command, act) for path, (command, act) in UI_CHAT_ROUTES.items()},
    **{path: _chat_route(command, act) for path, (command, act) in UI_INTUITION_ROUTES.items()},
    "/api/inbox/add": project_inbox_add,
    "/api/feed/run": feed_run_here,
    "/api/feed/refetch": feed_refetch_here,
}


_CHAT_ACTS: Final = tuple(_ROUTES[path] for path in (*UI_CHAT_ROUTES, *UI_INTUITION_ROUTES))

Freshness = Literal["fresh", "stale", "queued", "building", "failed"]
"""What `Rebuilder.ensure` answers for a product: `fresh` (serve it), `stale` (serve the previous
build; the next update waits for the settle window), `queued` (serve the previous build; an update
is queued), `building` (no previous build: the updating page stands in), `failed` (its build at
the current fingerprint failed)."""

Builder = Callable[[str], str | None]
"""Builds one product by id; returns the error text, or None when it built."""

UPDATING_REFRESH: Final = 2
"""Seconds between the reloads of the page that stands in while a product builds."""
BUILD_NICE: Final = 10
"""How much lower the CPU priority of a child build is than the server's (`nice -n`)."""
BUILD_TIMEOUT: Final = 1800.0
"""Seconds a child build may run before it is stopped and recorded as failed, so one wedged
build (a held lock, a hung converter) never blocks the queue behind it."""


def _duration(seconds: object) -> str:
    if not isinstance(seconds, (int, float)):
        return ""
    if seconds < 60:
        return f"{seconds:.0f} s"
    return f"{seconds / 60:.0f} min"


def progress_text(progress: dict[str, object] | None) -> str:
    """One line for a running build: percentage, steps and time left, as far as known
    (`site_progress.summary`)."""
    if not progress:
        return "building&hellip;"
    waiting = progress.get("waiting")
    if isinstance(waiting, int) and waiting > 0:
        return f"waiting for {waiting} other page{'s' if waiting > 1 else ''} to build"
    if not progress.get("started"):
        return "starting&hellip;"
    bits: list[str] = []
    percent = progress.get("percent")
    if isinstance(percent, int):
        bits.append(f"{percent}%")
    done, total, label = progress.get("done"), progress.get("total"), progress.get("label")
    if isinstance(done, int) and isinstance(total, int) and total:
        if done >= total:
            so_far = _duration(progress.get("elapsed"))
            return f"finishing (writing the page) &middot; {so_far} so far"
        bits.append(f"{done:,} of {total:,} {html_lib.escape(str(label or 'steps'))}")
    remaining = progress.get("remaining")
    if isinstance(remaining, (int, float)):
        bits.append(f"about {_duration(remaining)} left")
    else:
        bits.append(f"{_duration(progress.get('elapsed'))} so far")
    return " &middot; ".join(bits)


def _bar(progress: dict[str, object] | None) -> str:
    percent = progress.get("percent") if progress else None
    width = percent if isinstance(percent, int) else 0
    return (
        "<div style='border:1px solid var(--mut);height:10px;margin:14px 0 6px;max-width:520px'>"
        f"<div style='height:100%;width:{width}%;background:var(--ac)'></div></div>"
    )


def updating_page(
    title: str, *, failed: str | None = None, progress: dict[str, object] | None = None
) -> str:
    """The page that stands in for a product that was never built, while it builds (it reloads
    itself; a meta refresh replaces the history entry, so Back is not caught), with the build's
    progress; or that shows its failed build."""
    name = html_lib.escape(title)
    if failed is not None:
        return site_service.page(
            f"{title}: build failed",
            f"<h1>{name}</h1><p>The build of this page failed and there is no earlier version to "
            f"show.</p><pre class=panel>{html_lib.escape(failed)}</pre><p class=dim>It is tried "
            "again when its inputs change, or after a restart of the server.</p>",
        )
    return site_service.page(
        f"Building {title}",
        f"<h1>Building {name}</h1><p>This page has not been built yet. It is being built now and "
        f"opens here when it is ready.</p>{_bar(progress)}"
        f"<p class=mono>{progress_text(progress)}</p>"
        "<p class=dim>The percentage counts the build's steps where the page reports them, and "
        "otherwise compares the time so far with its last build.</p>",
        head=f"<meta http-equiv=refresh content={UPDATING_REFRESH}>",
    )


_BADGE_CSS: Final = (
    "position:fixed;right:12px;bottom:12px;z-index:9999;padding:4px 10px;max-width:70vw;"
    "font:11px ui-monospace,Menlo,monospace;background:rgba(8,9,16,.88);color:{c};"
    "border:1px solid {c};letter-spacing:.04em"
)


def version_text(status: site_service.ProductStatus, events_now: int | None) -> str:
    """The version line of a served page: when it was built, from how many events (and how many
    there are now, when more) and by which factory code."""
    bits = [f"built {html_lib.escape(status.built_at or 'earlier')}"]
    if status.built_events is not None:
        events = f"{status.built_events:,} events"
        if events_now is not None and events_now != status.built_events:
            events += f" (now {events_now:,})"
        bits.append(events)
    if status.built_code:
        bits.append(f"code {html_lib.escape(status.built_code)}")
    return " &middot; ".join(bits)


def page_badge(
    pid: str,
    state: Freshness,
    status: site_service.ProductStatus,
    *,
    events_now: int | None,
    settle: float,
    progress: dict[str, object] | None,
) -> str:
    """The small fixed badge on every product page the server serves (IDEA-96): its version
    (`version_text`) and, when it is not current, why: an update running (with its progress,
    watched through `api/status`, offering a reload when done), waiting for the settle window, or
    failed."""
    version = version_text(status, events_now)
    colour = "#6a6e95" if state == "fresh" else "#e8b45a"
    if state == "failed":
        text = f"{version} &middot; the last update failed"
    elif state == "stale":
        text = (
            f"{version} &middot; newer data; updates at most every {max(1, round(settle / 60))} min"
        )
    elif state == "queued":
        text = f"{version} &middot; updating: <span id=rf-prog>{progress_text(progress)}</span>"
    else:
        text = version
    script = (
        ""
        if state != "queued"
        else "<script>(function(){var b=document.getElementById('rf-stale'),id="
        + json.dumps(pid)
        + ";function poll(){fetch('../api/status',{cache:'no-store'})"
        ".then(function(r){return r.json();})"
        ".then(function(s){if((s.queued||[]).indexOf(id)<0){"
        'b.innerHTML=\'updated &middot; <a href="#" style="color:#82FB9C">reload</a>\';'
        "b.querySelector('a').onclick=function(e){e.preventDefault();location.reload();};return;}"
        "var t=(s.progress_text||{})[id],p=document.getElementById('rf-prog');"
        "if(t&&p)p.innerHTML=t;setTimeout(poll,3000);})"
        ".catch(function(){setTimeout(poll,8000);});}"
        "setTimeout(poll,3000);})();</script>"
    )
    style = _BADGE_CSS.replace("{c}", colour)
    return f"<div id=rf-stale style='{style}'>{text}</div>{script}"


def build_progress(
    project: Project, pid: str, last_seconds: float | None, queue: list[str]
) -> dict[str, object]:
    """The progress of product `pid`'s build (`site_progress.summary`), with `waiting`: how many
    queued builds are ahead of it (0 when it is the one running) and `started` (False until the
    build process has opened its progress file)."""
    root = site_service.site_dir(project)
    found = site_progress.read(root, pid)
    out = site_progress.summary(found, last_seconds)
    out["waiting"] = queue.index(pid) if pid in queue else 0
    out["started"] = found is not None
    return out


def with_badge(page_text: str, badge: str) -> str:
    """`page_text` with `badge` before its closing body tag (appended when there is none)."""
    at = page_text.rfind("</body>")
    return page_text + badge if at < 0 else page_text[:at] + badge + page_text[at:]


def child_builder(project: Project) -> Builder:
    """A `Builder` that runs `factory site build --only <id>` as a child process at a lower CPU
    priority (IDEA-96): the build neither shares the server's interpreter (one Python thread runs
    at a time) nor holds its locks, and it loads the code as it is on disk, so a changed page shows
    without a server restart. The error is the manifest's, or the tail of the child's output."""
    root = str(project.settings.root)
    slug = project.paths.slug

    def build(pid: str) -> str | None:
        # `nice` as a command, not `preexec_fn`: code run between fork and exec in a threaded
        # server can deadlock the child
        cmd = [
            "nice",
            "-n",
            str(BUILD_NICE),
            sys.executable,
            "-c",
            "from factory.cli.main import app; app()",
            "--root",
            root,
            "--project",
            slug,
            "site",
            "build",
            "--lazy",
            "--only",
            pid,
        ]
        try:
            done = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=BUILD_TIMEOUT
            )
        except subprocess.TimeoutExpired:  # run() has killed the child
            return f"the build of {pid} took over {BUILD_TIMEOUT:.0f} s and was stopped"
        except OSError as exc:
            return f"the build of {pid} could not start: {exc}"
        product = next(p for p in site_service.products() if p.id == pid)
        recorded = site_service.status(project, [product])[0].error
        if recorded is not None:
            return recorded
        if done.returncode != 0:
            return (done.stderr or done.stdout or f"exit {done.returncode}")[-500:]
        return None

    return build


def render_item(project: Project, product: site_service.Product, rel: str) -> Path | None:
    """The file of item `rel` of `product`, rendered on first request into
    `site/.items/<product>/<fingerprint>/` and kept there until the product is rebuilt (the
    fingerprint is the recorded one, so items match the list page that is served). None when
    `rel` names no item. Rendering goes to a scratch folder first, so a reader never sees half a
    file and two requests for one item do not collide."""
    if product.item is None:
        return None
    root = site_service.site_dir(project) / site_service.ITEMS_DIR / product.id
    fp = site_service.recorded_fingerprint(project, product.id) or "unbuilt"
    cached = root / fp / rel
    if cached.exists():
        return cached
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=".render-", dir=root))
    try:
        if not product.item(project, rel, scratch):
            return None
        for made in scratch.rglob("*"):
            if made.is_dir() and not made.is_symlink():
                continue
            target = root / fp / made.relative_to(scratch)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(made, target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return cached if cached.exists() else None


class Rebuilder:
    """Keeps one project's products current (IDEA-96).

    On demand (the default): `ensure(pid)` answers how a product may be served; a stale one is
    queued for the one worker thread, so builds run one at a time and only for the products that
    are opened. A product built in this session is not built again within `min_gap` seconds (the
    settle window; 0 in development mode): meanwhile its previous build is served with a badge. A
    build that failed at a fingerprint is not tried again until the fingerprint changes (or the
    server restarts). `builder` builds one product (default: in this process; the CLI passes
    `child_builder`). With `eager`, a second thread also queues every stale product, at most once
    per `min_gap` seconds. Before `start`, `ensure` answers `fresh` for everything: the files on
    disk are served as they are."""

    def __init__(
        self,
        project: Project,
        *,
        min_gap: float,
        poll: float = 15.0,
        eager: bool = False,
        builder: Builder | None = None,
    ) -> None:
        self._project = project
        self._min_gap = min_gap
        self._poll = poll
        self._eager = eager
        self._builder = builder
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="site-rebuilder", daemon=True)
        self._worker = threading.Thread(target=self._work, name="site-on-open", daemon=True)
        self._products = {p.id: p for p in site_service.products()}
        self._queue: list[str] = []
        self._wake = threading.Condition()
        self._failed: dict[str, tuple[str, str]] = {}
        """Per product: the fingerprint its last build failed at, and the error text."""
        self._built: dict[str, float] = {}
        self._started = False
        self.building = False
        self.last_build_at: float | None = None
        self.last_error: str | None = None

    @property
    def settle(self) -> float:
        return self._min_gap

    def start(self) -> None:
        self._started = True
        # read the code version (git) off the request path: `/api/status` never waits for it
        threading.Thread(target=site_service.code_version, name="code-version", daemon=True).start()
        self._worker.start()
        if self._eager:
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._wake:
            self._wake.notify_all()

    def queued(self) -> list[str]:
        """The products waiting for, or in, an on-demand build."""
        with self._wake:
            return list(self._queue)

    def product(self, pid: str) -> site_service.Product | None:
        """The registered product `pid`, or None."""
        return self._products.get(pid)

    def ensure(self, pid: str) -> tuple[Freshness, site_service.ProductStatus | None, int | None]:
        """How product `pid` may be served now, with its status and the project's event count
        (None, None for what is no product, or before `start`). Queues a build when one is due.
        Never waits for a build. One grouped count read serves both."""
        product = self._products.get(pid)
        if not self._started or product is None:
            return "fresh", None, None
        counts = site_service.type_counts(self._project)
        events = sum(n for n, _ in counts.values())
        found = self._ensure(pid, product, counts)
        return found[0], found[1], events

    def _ensure(
        self, pid: str, product: site_service.Product, counts: site_service.TypeCounts
    ) -> tuple[Freshness, site_service.ProductStatus]:
        state = site_service.status(self._project, [product], counts)[0]
        with self._wake:
            if pid in self._queue:
                return ("queued" if state.built else "building"), state
        if state.built and not state.stale and state.error is None:
            return "fresh", state
        if self._failed_at(pid) == state.fingerprint:
            return "failed", state
        last = self._built.get(pid)
        if state.built and last is not None and time.monotonic() - last < self._min_gap:
            return "stale", state
        self._enqueue(pid)
        return ("queued" if state.built else "building"), state

    def _failed_at(self, pid: str) -> str | None:
        found = self._failed.get(pid)
        return None if found is None else found[0]

    def failure(self, pid: str) -> str | None:
        """The error of product `pid`'s last failed build, or None."""
        found = self._failed.get(pid)
        return None if found is None else found[1]

    def _enqueue(self, pid: str) -> None:
        with self._wake:
            if pid not in self._queue:
                self._queue.append(pid)
                self._wake.notify_all()

    def _work(self) -> None:
        while not self._stop.is_set():
            with self._wake:
                while not self._queue and not self._stop.is_set():
                    self._wake.wait()
                if self._stop.is_set():
                    return
                pid = self._queue[0]
            try:
                self._build_one(pid)
            except Exception:  # a worker that dies would leave the product "updating" forever
                logging.getLogger(__name__).exception("on-demand build of %s failed", pid)
                with contextlib.suppress(Exception):
                    fp = site_service.fingerprint(self._project, self._products[pid])
                    self._failed[pid] = (fp, "the build raised; see the server log")
            finally:
                self._built[pid] = time.monotonic()
                with self._wake:
                    self._queue.remove(pid)

    def _build_one(self, pid: str) -> None:
        fp = site_service.fingerprint(self._project, self._products[pid])
        self.building = True
        try:
            if self._builder is not None:
                error = self._builder(pid)
            else:
                with self._lock:
                    results = site_service.build(self._project, only=[pid])
                error = next((r.error for r in results if r.error), None)
        finally:
            self.building = False
            self.last_build_at = time.monotonic()
        if error is None:
            self._failed.pop(pid, None)
        else:
            self._failed[pid] = (fp, error)
            self.last_error = error

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
        """The eager loop: every `poll` seconds, queue each stale product that was not built in
        the last `min_gap` seconds (its build runs on the worker, like an opened one)."""
        while not self._stop.is_set():
            now = time.monotonic()
            for state in site_service.status(self._project):
                last = self._built.get(state.id)
                due = last is None or now - last >= self._min_gap
                if state.stale and due and self._failed_at(state.id) != state.fingerprint:
                    self._enqueue(state.id)
            self._stop.wait(self._poll)


class Slot:
    """One project's live parts inside a server: its built `site/` folder, rebuilder, write lock,
    advance gate and resume runner. A write for one project never takes another's lock."""

    def __init__(
        self, project: Project, *, min_gap: float, eager: bool = False, child_builds: bool = False
    ) -> None:
        self.project = project
        self.slug = project.paths.slug
        self.root = site_service.site_dir(project)
        self.rebuilder = Rebuilder(
            project,
            min_gap=min_gap,
            eager=eager,
            builder=child_builder(project) if child_builds else None,
        )
        self.write_lock = threading.Lock()
        self.advance_gate = threading.Lock()
        self.resumer = ResumeRunner()
        self.ui = hub_serve.PayloadService(project)
        """The hub v2 payload cache and its on-demand builder (served at `/ui/`)."""

    def prepare(self) -> None:
        """Write the project's hub page, so a served project is never without its hub."""
        self.root.mkdir(parents=True, exist_ok=True)
        site_service.render_hub(self.project)
        self.ui.prewarm()  # queues every hub v2 payload; a no-op when FACTORY_HUB_PREWARM=0


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

        _cache: str | None = None

        def end_headers(self) -> None:
            self.send_header("Cache-Control", self._cache or "no-store")
            self._cache = None
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

        def _json(self, code: int, payload: Mapping[str, object]) -> None:
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

        def _send_file(self, path: Path, name: str) -> None:
            """Stream the cached file `path` as a download (it stays in the cache)."""
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile, 1024 * 1024)

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
            if url == UI_PREFIX or url.startswith(UI_PREFIX + "/"):
                self._ui(url, mount.rel.partition("?")[2], slot, mount.prefix)
                return
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
                queued = slot.rebuilder.queued()
                seconds = {s.id: s.built_seconds for s in tried or []}
                progress = {
                    pid: build_progress(slot.project, pid, seconds.get(pid), queued)
                    for pid in queued
                }
                self._json(
                    200,
                    {
                        "building": tried is None or slot.rebuilder.building,
                        "queued": queued,
                        "progress": progress,
                        "progress_text": {k: progress_text(v) for k, v in progress.items()},
                        "code": site_service.code_version_ready(),
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
            if url == "/api/activity":
                try:
                    found = activity_service.activity_cached(slot.project)
                except FactoryError as exc:
                    self._json(500, _issues(ValidationIssue("activity", str(exc))))
                    return
                self._json(200, found.model_dump(mode="json"))
                return
            if url == "/api/screening":
                try:
                    self._json(200, dashboard_service.screening_live(slot.project))
                except FactoryError as exc:
                    self._json(500, _issues(ValidationIssue("screening", str(exc))))
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
            if self._product_gate(url, slot):
                return
            if self._lazy_item(url, slot):
                return
            self.directory = str(slot.root)
            self.path = mount.rel
            super().do_GET()

        def _send(self, code: int, body: bytes, kind: str, headers: Mapping[str, str]) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _ui(self, url: str, query: str, slot: Slot, prefix: str) -> None:
            """Hub v2 (`hub_serve`): read-only; the page, an asset, a payload or a trace."""
            if url == UI_PREFIX:
                self.send_response(301)
                self.send_header(
                    "Location", f"{prefix}{UI_PREFIX}/" + (f"?{query}" if query else "")
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            rest = unquote(url[len(UI_PREFIX) + 1 :])
            if rest in ("", "index.html") or (rest.endswith(".html") and "/" not in rest):
                index = rest in ("", "index.html")
                text = hub_serve.page_text(
                    hub_learn.landing_page(slot.project) if index else rest[:-5]
                )
                if text is None:
                    self._deny(404, "not found")
                    return
                text = _with_meta(text, auth.page_credential(site_auth.Scope(slot.slug)), prefix)
                text = text.replace("<head>", "<head><meta name='factory-served' content='1'>", 1)
                self._cache = "no-cache"
                self._html(text)
            elif rest.startswith("assets/"):
                version = dict(parse_qsl(query)).get("v")
                found = hub_serve.asset(rest[len("assets/") :], version)
                if found is None:
                    self._deny(404, "not found")
                    return
                self._cache = (
                    "public, max-age=31536000, immutable" if found.immutable else "no-cache"
                )
                if found.gz and hub_serve.accepts_gzip(self.headers.get("Accept-Encoding")):
                    self._send(
                        200,
                        found.gz,
                        found.content_type,
                        {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
                    )
                else:
                    self._send(200, found.body, found.content_type, {"Vary": "Accept-Encoding"})
            elif rest.startswith(UI_DOC_PREFIX) and rest.endswith(".json"):
                self._ui_document(slot, rest[len(UI_DOC_PREFIX) : -len(".json")], None)
            elif rest.startswith("data/") and rest.endswith(".json"):
                self._payload(rest[len("data/") : -len(".json")], slot)
            elif rest.startswith("file/"):
                kind, _, doc_id = rest[len("file/") :].partition("/")
                self._ui_document(slot, doc_id, kind)
            elif rest.startswith("study/"):
                found_study = hub_serve.study_file(slot.project, rest[len("study/") :])
                if found_study is None:
                    self._deny(404, "not found")
                    return
                body, kind, name = found_study
                safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
                extra = {"X-Content-Type-Options": "nosniff"}
                if not kind.startswith("text/plain"):
                    extra["Content-Disposition"] = f'attachment; filename="{safe}"'
                self._cache = "no-store"
                self._send(200, body, kind, extra)
            elif rest.startswith("ops/"):
                found_ops = hub_serve.ops_file(slot.project, rest[len("ops/") :])
                if found_ops is None:
                    self._deny(404, "not found")
                    return
                self._cache = "no-store"
                self._send(
                    200,
                    found_ops.body,
                    found_ops.content_type,
                    {"X-Content-Type-Options": "nosniff"},
                )
            elif rest == "download/wiki.zip":
                try:
                    archive = hub_serve.wiki_zip(slot.project)
                except (FactoryError, OSError) as exc:
                    self._json(500, _issues(ValidationIssue("wiki", str(exc))))
                    return
                self._send_file(archive, f"{slot.slug}-wiki.zip")
            elif rest == "status.json":
                self._cache = "no-store"
                self._json(200, slot.ui.status())
            elif rest == "fresh":
                name = dict(parse_qsl(query)).get("name", "")
                self._cache = "no-store"
                self._json(200, {"fresh": slot.ui.is_fresh(name)})
            elif rest == "chat":
                try:
                    chat = hub_chat.live(slot.project, dict(parse_qsl(query)))
                except FactoryValidationError as exc:
                    self._json(400, _issues(*exc.issues))
                    return
                except FactoryError as exc:
                    self._json(500, _issues(ValidationIssue("chat", str(exc))))
                    return
                self._cache = "no-store"
                self._json(200, chat)
            elif rest == "trace":
                try:
                    payload = hub_serve.trace(slot.project, dict(parse_qsl(query)))
                except FactoryValidationError as exc:
                    self._json(400, _issues(*exc.issues))
                    return
                except FactoryError as exc:
                    self._json(500, _issues(ValidationIssue("trace", str(exc))))
                    return
                self._cache = "no-cache"
                self._json(200, payload)
            else:
                self._deny(404, "not found")

        def _ui_document(self, slot: Slot, document_id: str, kind: str | None) -> None:
            """One converted document: its payload (`kind` None) or its original or Markdown
            file. The id is looked up in the index (`hub_sources`); anything unknown is a 404."""
            try:
                if kind is None:
                    detail = hub_serve.source_document(slot.project, document_id)
                    if detail is None:
                        self._deny(404, "not found")
                        return
                    self._cache = "no-cache"
                    self._json(200, detail)
                    return
                found_file = hub_serve.source_file(slot.project, document_id, kind)
            except (FactoryError, OSError):  # the stored file is gone
                self._deny(404, "not found")
                return
            if found_file is None:
                self._deny(404, "not found")
                return
            self._cache = "no-cache"
            self._send(
                200,
                found_file[0],
                found_file[1],
                {"X-Content-Type-Options": "nosniff"},
            )

        def _payload(self, name: str, slot: Slot) -> None:
            """A cached payload with its ETag (304 when the browser has it, stale or fresh), gzipped
            when the client accepts it, or why not yet."""
            want_gz = hub_serve.accepts_gzip(self.headers.get("Accept-Encoding"))
            answer = slot.ui.get(name, gzip=want_gz)
            if isinstance(answer, hub_serve.Unknown):
                self._deny(404, "not found")
            elif isinstance(answer, hub_serve.Building):
                self._cache = "no-store"
                body = json.dumps({"building": True, "progress": answer.progress}).encode()
                self._send(
                    503,
                    body,
                    "application/json; charset=utf-8",
                    {"Retry-After": str(hub_serve.RETRY_AFTER)},
                )
            elif isinstance(answer, hub_serve.Failed):
                self._json(500, {"error": "build failed", "payload": answer.name})
            else:
                self._cache = "private, no-cache"  # keep it, revalidate each time
                headers = {"ETag": answer.etag, "Vary": "Accept-Encoding"}
                if isinstance(answer, hub_serve.Stale):
                    headers["X-Hub-Stale"] = "1"
                seen = {
                    t.strip().removeprefix("W/")
                    for t in (self.headers.get("If-None-Match") or "").split(",")
                }
                if answer.etag in seen or "*" in seen:
                    self.send_response(304)
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    return
                if answer.gzip:
                    headers["Content-Encoding"] = "gzip"
                self._send(200, answer.body, "application/json; charset=utf-8", headers)

        def _lazy_item(self, url: str, slot: Slot) -> bool:
            """Serve an item page of a lazily built product, rendering it on its first request
            (IDEA-96); True when this answered. A file the build wrote is served as it is."""
            pid, _, rest = url.lstrip("/").partition("/")
            product = slot.rebuilder.product(pid)
            if product is None or product.item is None or not rest:
                return False
            parts = rest.split("/")
            if parts[0] not in product.item_dirs or any(not p or p.startswith(".") for p in parts):
                return False
            if (slot.root / pid / rest).exists():
                return False
            try:
                found = render_item(slot.project, product, rest)
            except OSError:  # a rebuild cleared the item cache meanwhile; the browser may retry
                self.send_response(503)
                self.send_header("Retry-After", "2")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return True
            if found is None:
                self._deny(404, "not found")
                return True
            body = found.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(found)))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

        def _product_gate(self, url: str, slot: Slot) -> bool:
            """Serve a product's entry page by its freshness (IDEA-96); True when this answered.

            Only a product's entry page is held (`/<id>/`, `/<id>/<entry>`); the files inside a
            product folder are served as they are. A product with a previous build is never
            waited for: that build is served with a badge (when it was built, and whether an
            update is queued, waits for the settle window or failed). A product never built gets
            the building page, which reloads itself, or its error."""
            pid, _, rest = url.lstrip("/").partition("/")
            product = slot.rebuilder.product(pid)
            if product is None or not url.startswith(f"/{pid}/") or rest not in ("", product.entry):
                return False
            state, status, events_now = slot.rebuilder.ensure(pid)
            if status is None:
                return False
            entry = slot.root / pid / product.entry
            if state == "fresh" and not entry.is_file():
                return False  # the static handler answers (404)
            progress = (
                build_progress(slot.project, pid, status.built_seconds, slot.rebuilder.queued())
                if state in ("queued", "building")
                else None
            )
            if state == "building" or not entry.is_file():
                failed = slot.rebuilder.failure(pid) if state == "failed" else None
                self._html(updating_page(product.title, failed=failed, progress=progress))
                return True
            badge = page_badge(
                pid,
                state,
                status,
                events_now=events_now,
                settle=slot.rebuilder.settle,
                progress=progress,
            )
            self._html(with_badge(entry.read_text(encoding="utf-8"), badge))
            return True

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
            if route is project_inbox_add:
                code, payload = project_inbox_add(slot, body)
            elif route in (feed_run_here, feed_refetch_here):
                feed_act = (hub_acts or {}).get(
                    "/api/feed/run" if route is feed_run_here else "/api/feed/refetch"
                )
                if feed_act is None:
                    code, payload = 503, _issues(ValidationIssue("feed", "the feed runner is off"))
                else:
                    code, payload = feed_act({})
            elif route in (
                feed_react,
                feed_configure,
                mine_work,
                mine_layer,
                move_layer,
                ui_snowball_add,
                *_CHAT_ACTS,
            ):
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
    eager: bool = False,
    child_builds: bool = False,
    authenticator: site_auth.Authenticator | None = None,
) -> tuple[ThreadingHTTPServer, Rebuilder]:
    """A server for `<project>/site/` on 127.0.0.1:`port` (0 picks a free port) and its rebuilder
    (started when `background`; products are built when opened, and all stale ones every `min_gap`
    seconds too with `eager`). The hub page is written first, so the server never starts empty."""
    slot = Slot(project, min_gap=min_gap, eager=eager, child_builds=child_builds)
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
        eager: bool = False,
        child_builds: bool = False,
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
        self._eager = eager
        self._child_builds = child_builds
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
            fresh = Slot(
                self._open(slug),
                min_gap=self._min_gap,
                eager=self._eager,
                child_builds=self._child_builds,
            )
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
        project's inbox as the local human, like `factory inbox add`."""
        slug, bad = _optional_str(body, "project")
        if not slug:
            bad.append(ValidationIssue("project", "required"))
        if bad:
            return 400, _issues(*bad)
        assert slug is not None
        found = self.slot(slug)
        if found is None:
            return 400, _issues(ValidationIssue("project", "unknown project"))
        return inbox_add_in(found, body)

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
            found.ui.stop()


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
