"""Serve the project site on 127.0.0.1 and keep it current (plan site-hub, step 6).

The hub is a folder of static files (`<project>/site/`); this server shows it over HTTP, adds
`/api/status` (each product's build time and staleness, read from the manifest and the event log),
and runs one background thread that rebuilds stale products. A rebuild waits at least `min_gap`
seconds after the previous one: the snapshot of the dashboard takes about a minute, and a project
that is being mined makes it stale all the time.

Invariants:
- Read-only for the browser except three allow-listed acts (decision 118): `POST /api/feed/react`,
  `POST /api/feed/add` and `POST /api/queue/process` (starts the headless runner, which records its
  own system events). Any other POST path is 404; PUT, DELETE and PATCH are 405. Apart from those
  acts the server writes nothing but the site folder, through `site.build`. `GET /api/queue/runs`
  reads the runs and reconciles nothing.
- A POST needs, all at once: a loopback Host, the per-start token in `X-Factory-Token` (compared in
  constant time), `Content-Type: application/json`, a body of at most 16 KiB and, if an Origin is
  sent, this server's own origin. Otherwise 403 (413 or 415 for size or type) and nothing is
  written. The token is made at server start, is injected into `/feed/` and `/queue/` pages only
  and is never written to the files on disk.
- The actor is the local human principal and each act is authorised by its command row
  (`cli:feed react`, `cli:feed add`, `cli:queue process`), as the CLI does.
- Loopback only: a request whose Host is not 127.0.0.1, localhost or [::1] is refused.
- One build runs at a time; a product that fails is recorded by `site.build` and the others go on.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.model.feed import FeedNote, FeedReaction
from factory.services import feed as feed_service
from factory.services import runner as runner_service
from factory.services import site as site_service
from factory.services.access import authorize_command
from factory.services.context import Project
from factory.sources.registry import default_sources

HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8766
_LOOPBACK: Final = {"127.0.0.1", "localhost", "[::1]"}
MAX_BODY: Final = 16 * 1024
TOKEN_HEADER: Final = "X-Factory-Token"
_ACTION_PAGES: Final = ("feed", "queue")
_TOKEN_META: Final = "<meta name='factory-token' content='{}'>"


def _sources() -> Any:
    """The source factories `feed add` resolves with (as `factory feed add` builds them)."""
    return dict(default_sources())


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


def queue_process(project: Project, body: dict[str, Any]) -> tuple[int, dict[str, object]]:
    """Start the headless runner for one stage as the local human; returns (status, body)."""
    stage = body.get("stage")
    cap = body.get("unit_cap", runner_service.DEFAULT_UNIT_CAP)
    bad: list[ValidationIssue] = []
    if not isinstance(stage, str) or stage not in runner_service.STAGES:
        bad.append(ValidationIssue("stage", "must be one of " + ", ".join(runner_service.STAGES)))
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
        run_id = runner_service.start_run(project, stage, unit_cap=cap)
    except FactoryValidationError as exc:
        return 400, _issues(*exc.issues)
    except FactoryError as exc:
        return 400, _issues(ValidationIssue("run", str(exc)))
    return 200, {"ok": True, "run_id": run_id, "stage": stage, "unit_cap": cap}


_ROUTES: Final = {
    "/api/feed/react": feed_react,
    "/api/feed/add": feed_add,
    "/api/queue/process": queue_process,
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


def make_server(
    project: Project, port: int = DEFAULT_PORT, *, min_gap: float = 300.0, background: bool = True
) -> tuple[ThreadingHTTPServer, Rebuilder]:
    """A server for `<project>/site/` on 127.0.0.1:`port` (0 picks a free port) and its rebuilder
    (started when `background`). The hub page is written first, so the server never starts empty."""
    root = site_service.site_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    site_service.render_hub(project)
    rebuilder = Rebuilder(project, min_gap=min_gap)
    token = secrets.token_urlsafe(32)
    write_lock = threading.Lock()

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

        def _host_ok(self) -> bool:
            return (self.headers.get("Host") or "").rsplit(":", 1)[0] in _LOOPBACK

        def _json(self, code: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            port = httpd.server_address[1]
            return origin in {f"http://{name}:{port}" for name in _LOOPBACK}

        def _feed_page(self) -> Path | None:
            """The built HTML file this GET names under `/feed/` or `/queue/`, if it is one."""
            url = self.path.split("?", 1)[0].split("#", 1)[0]
            if not any(url == f"/{name}" or url.startswith(f"/{name}/") for name in _ACTION_PAGES):
                return None
            target = Path(self.translate_path(url))
            if target.is_dir():
                target = target / "index.html"
            if target.suffix != ".html" or not target.is_file():
                return None
            return target

        def do_GET(self) -> None:
            if not self._host_ok():
                self._deny(403, "forbidden")
                return
            page = self._feed_page()
            if page is not None:
                text = page.read_text(encoding="utf-8")
                meta = _TOKEN_META.format(token)
                text = (
                    text.replace("<head>", "<head>" + meta, 1) if "<head>" in text else meta + text
                )
                body = text.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.split("?", 1)[0] == "/api/status":
                body = json.dumps(
                    {
                        "building": rebuilder.building,
                        "error": rebuilder.last_error,
                        "products": [s.model_dump(mode="json") for s in rebuilder.statuses()],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.split("?", 1)[0] == "/api/queue/runs":
                runs = runner_service.run_status(project, reconcile=False)
                self._json(200, {"runs": [r.model_dump(mode="json") for r in runs]})
                return
            super().do_GET()

        def _refuse(self) -> None:
            self._deny(405, "read-only")

        def do_POST(self) -> None:
            route = _ROUTES.get(self.path.split("?", 1)[0])
            if not self._host_ok() or not self._origin_ok():
                self._deny(403, "forbidden")
                return
            if route is None:
                self._deny(404, "not found")
                return
            sent = self.headers.get(TOKEN_HEADER) or ""
            if not hmac.compare_digest(sent.encode(), token.encode()):
                self._deny(403, "forbidden")
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
            if length < 0 or length > MAX_BODY:
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
            with write_lock:
                code, payload = route(project, body)
            # the feed product turns stale by the event log; the background rebuild picks it up
            self._json(code, payload)

        do_PUT = do_DELETE = do_PATCH = _refuse

        def log_message(self, format: str, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer((HOST, port), partial(Handler, directory=str(root)))
    if background:
        rebuilder.start()
    return httpd, rebuilder
