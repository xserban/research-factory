"""Serve the project site on 127.0.0.1 and keep it current (plan site-hub, step 6).

The hub is a folder of static files (`<project>/site/`); this server shows it over HTTP, adds
`/api/status` (each product's build time and staleness, read from the manifest and the event log),
and runs one background thread that rebuilds stale products. A rebuild waits at least `min_gap`
seconds after the previous one: the snapshot of the dashboard takes about a minute, and a project
that is being mined makes it stale all the time.

Invariants:
- Read-only for the browser: only GET is served; a POST, PUT, DELETE or PATCH is refused (as the
  dashboard server does). The server writes nothing but the site folder, through `site.build`.
- Loopback only: a request whose Host is not 127.0.0.1, localhost or [::1] is refused.
- One build runs at a time; a product that fails is recorded by `site.build` and the others go on.
"""

from __future__ import annotations

import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Final

from factory.services import site as site_service
from factory.services.context import Project

HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8766
_LOOPBACK: Final = {"127.0.0.1", "localhost", "[::1]"}


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

        def do_GET(self) -> None:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in _LOOPBACK:
                self._deny(403, "forbidden")
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
            super().do_GET()

        def _refuse(self) -> None:
            self._deny(405, "read-only")

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

        def log_message(self, format: str, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer((HOST, port), partial(Handler, directory=str(root)))
    if background:
        rebuilder.start()
    return httpd, rebuilder
