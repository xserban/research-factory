"""The authentication seam (plan 2026-11-13-main-hub, part 2): one function decides, for each
request, who the actor is and whether it may do the act. One implementation today (loopback host,
same-origin, the per-scope token); a fake in these tests shows the seam is the only place that
decides: a refusing one stops every route, an allowing one needs no token anywhere else."""

from __future__ import annotations

import http.client
import inspect
import json
import threading
from collections.abc import Iterator

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import read_all
from factory.services import site_auth, site_server
from factory.services.context import Project, list_projects, open_project
from factory.services.feed import FeedRunAll
from factory.services.project import init_project
from factory.services.site_auth import AuthDecision, AuthRequest, LoopbackTokenAuth, Scope
from tests.helpers import SESSION


def _req(
    port: int, method: str, path: str, body: object | None = None, token: str | None = None
) -> int:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Factory-Token"] = token
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
    response = conn.getresponse()
    response.read()
    conn.close()
    return response.status


# --- the default implementation ---


def _auth() -> LoopbackTokenAuth:
    auth = LoopbackTokenAuth(b"s" * 32)
    auth.bind(lambda: 8000)
    return auth


def _write(auth: LoopbackTokenAuth, **over: object) -> AuthRequest:
    fields: dict[str, object] = {
        "method": "POST",
        "path": "/p/demo/api/feed/react",
        "host": "127.0.0.1:8000",
        "origin": None,
        "credential": auth.page_credential(Scope("demo")),
        "scope": Scope("demo"),
        "act": "/api/feed/react",
    }
    fields.update(over)
    return AuthRequest(**fields)  # type: ignore[arg-type]


def test_a_write_with_the_scopes_token_on_loopback_is_the_local_human() -> None:
    auth = _auth()
    decision = auth.check(_write(auth))
    assert decision.allowed and decision.actor == "human"


@pytest.mark.parametrize(
    "over",
    [
        {"credential": None},
        {"credential": "0" * 64},
        {"host": "evil.example"},
        {"origin": "http://evil.example"},
        {"scope": Scope("other")},
        {"scope": Scope(None)},
    ],
)
def test_a_write_is_refused_without_the_token_host_origin_or_scope(over: dict[str, object]) -> None:
    auth = _auth()
    decision = auth.check(_write(auth, **over))
    assert not decision.allowed and decision.actor is None and decision.reason


def test_a_loopback_origin_is_accepted_and_a_read_needs_only_the_host() -> None:
    auth = _auth()
    assert auth.check(_write(auth, origin="http://localhost:8000")).allowed
    read = _write(auth, method="GET", credential=None, act="read")
    assert auth.check(read).allowed
    assert not auth.check(_write(auth, method="GET", credential=None, act="read", host="x")).allowed


def test_tokens_are_per_scope() -> None:
    auth = _auth()
    assert auth.page_credential(Scope("a")) != auth.page_credential(Scope("b"))
    assert auth.page_credential(Scope("a")) != auth.page_credential(Scope(None))


# --- the server decides nothing itself ---


class Refuse:
    """A seam that refuses everything, whatever the token."""

    def __init__(self) -> None:
        self.seen: list[AuthRequest] = []

    def check(self, request: AuthRequest) -> AuthDecision:
        self.seen.append(request)
        return AuthDecision(False, None, "refused by the test")

    def page_credential(self, scope: Scope) -> str:
        return "real-looking-token"


class AllowAll:
    """A seam that allows everything, with no token."""

    def check(self, request: AuthRequest) -> AuthDecision:
        return AuthDecision(True, "human", "")

    def page_credential(self, scope: Scope) -> str:
        return "none"


@pytest.fixture
def two(settings: Settings, clock: FixedClock, project: Project) -> Project:
    return init_project(settings, "other", "pilot", session=SESSION, clock=clock)


def _idle(refetch: bool) -> FeedRunAll:
    return FeedRunAll(exit_code=0, outcomes=())


def _serve(
    settings: Settings, clock: FixedClock, auth: site_auth.Authenticator
) -> tuple[object, int]:
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
        feed=site_server.FeedRunner(_idle),
    )
    httpd = site_server.make_main_server(hub, 0, authenticator=auth)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


@pytest.fixture
def refused(settings: Settings, clock: FixedClock, two: Project) -> Iterator[tuple[int, Refuse]]:
    auth = Refuse()
    httpd, port = _serve(settings, clock, auth)
    yield port, auth
    httpd.shutdown()  # type: ignore[attr-defined]
    httpd.server_close()  # type: ignore[attr-defined]


def _events(*projects: Project) -> int:
    return sum(len(list(read_all(p.paths.events_dir, p.catalog))) for p in projects)


def test_a_refusing_seam_stops_every_write_route_even_with_a_valid_looking_token(
    refused: tuple[int, Refuse], project: Project, two: Project
) -> None:
    port, auth = refused
    before = _events(project, two)
    routes = [f"/p/demo{route}" for route in site_server._ROUTES]
    routes += ["/api/feed/run", "/api/feed/refetch"]
    body = {"entry_id": "x", "reaction": "like", "categories": ["cs.AI"], "stage": "all"}
    for path in routes:
        assert _req(port, "POST", path, body, "real-looking-token") == 403, path
    assert _events(project, two) == before
    assert len(auth.seen) >= len(routes)
    assert all(r.method == "POST" for r in auth.seen)


def test_a_refusing_seam_stops_reads_too(refused: tuple[int, Refuse]) -> None:
    port, _ = refused
    for path in ("/", "/feed/", "/api/projects", "/p/demo/", "/p/demo/settings/"):
        assert _req(port, "GET", path) == 403, path


def test_an_allowing_seam_needs_no_token_anywhere_else(
    settings: Settings, clock: FixedClock, two: Project, project: Project
) -> None:
    httpd, port = _serve(settings, clock, AllowAll())
    try:
        body = {"categories": ["cs.AI"]}
        assert _req(port, "POST", "/p/demo/api/feed/configure", body) == 200
        assert _req(port, "POST", "/api/feed/run", {}) == 202
    finally:
        httpd.shutdown()  # type: ignore[attr-defined]
        httpd.server_close()  # type: ignore[attr-defined]


def test_the_single_project_server_takes_a_seam_too(project: Project) -> None:
    auth = Refuse()
    httpd, _ = site_server.make_server(project, 0, background=False, authenticator=auth)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        assert _req(port, "GET", "/") == 403
        assert _req(port, "POST", "/api/feed/react", {"entry_id": "x"}, "t") == 403
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_server_module_holds_no_token_or_host_check_of_its_own() -> None:
    """The decision lives in `site_auth`; `site_server` only asks."""
    source = inspect.getsource(site_server)
    for needle in ("compare_digest", "_host_ok", "_origin_ok", "_LOOPBACK", "hmac."):
        assert needle not in source, needle
