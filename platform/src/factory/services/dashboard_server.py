"""The dashboard's local HTTP server and static export (slice 8, I1).

Invariants:
- Bound to 127.0.0.1 only; a request whose Host header is not a loopback name is refused (a
  rebinding guard). Only `GET /` and `GET /api/state` answer; every other method is 405.
- Nothing writes an event: the state is computed per request from the index (the index itself is
  synced under a lock, one request at a time).
- No external resource: the page is one inline HTML string.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from factory.services.context import Project
from factory.services.dashboard import dashboard_state
from factory.services.dashboard_page import render_page

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}


def state_json(project: Project, lock: threading.Lock | None = None) -> str:
    """The state as JSON text; serialised by `lock` when given."""
    if lock is None:
        return json.dumps(dashboard_state(project), ensure_ascii=False)
    with lock:
        return json.dumps(dashboard_state(project), ensure_ascii=False)


def make_server(project: Project, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1:`port` (0 picks a free port); the caller runs or closes it."""
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in _LOOPBACK:
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, render_page().encode(), "text/html; charset=utf-8")
            elif path == "/api/state":
                body = state_json(project, lock).encode()
                self._send(200, body, "application/json; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def _refuse(self) -> None:
            self._send(405, b"read-only", "text/plain; charset=utf-8")

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((HOST, port), Handler)


def export_snapshot(project: Project, path: Path) -> Path:
    """Write the page with the state embedded to `path`; no event is written."""
    path.write_text(render_page(dashboard_state(project)), encoding="utf-8")
    return path
