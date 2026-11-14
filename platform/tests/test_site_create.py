"""The portal's create-project form (plan 2026-11-13-main-hub, setup part; first form only): a hub
act `POST /api/projects/create` and the form on the portal. It creates a project as the human
actor with the hub token, refuses a bad or existing slug with nothing written, and the new
project is listed with its hub. No model, no other setup form."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import read_all
from factory.services import site_auth, site_portal, site_server
from factory.services.context import Project, list_projects, open_project
from factory.services.site_create import create_project
from tests.helpers import SESSION


def _req(
    port: int, method: str, path: str, body: object | None = None, token: str | None = None
) -> tuple[int, str]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Factory-Token"] = token
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
    response = conn.getresponse()
    text = response.read().decode(errors="replace")
    conn.close()
    return response.status, text


def _hub_token(port: int, page: str = "/") -> str:
    match = re.search(r"name='factory-token' content='([^']+)'", _req(port, "GET", page)[1])
    assert match is not None
    return match.group(1)


def _serve(
    settings: Settings, clock: FixedClock, auth: site_auth.Authenticator | None = None
) -> tuple[site_server.ThreadingHTTPServer, int]:
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
        create=lambda slug, title, profile: create_project(
            settings, slug, title, profile, session=SESSION, clock=clock
        ),
    )
    httpd = site_server.make_main_server(hub, 0, authenticator=auth)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


@pytest.fixture
def served(settings: Settings, clock: FixedClock, project: Project) -> Iterator[int]:
    httpd, port = _serve(settings, clock)
    yield port
    httpd.shutdown()
    httpd.server_close()


def _entries(settings: Settings) -> list[str]:
    return sorted(p.name for p in (settings.root / "projects").iterdir())


def test_the_portal_has_the_form_and_the_hub_token(served: int) -> None:
    page = _req(served, "GET", "/")[1]
    assert "id=create-form" in page and "name=slug" in page and "name=title" in page
    assert "<option value='pilot'>" in page and "<option value='exploratory'>" in page
    assert "factory-token" in page


def test_a_created_project_is_listed_with_its_title_and_has_its_hub(
    served: int, settings: Settings
) -> None:
    body = {"slug": "second", "title": "A <b>second</b> review", "profile": "pilot"}
    status, text = _req(served, "POST", "/api/projects/create", body, _hub_token(served))
    assert status == 200, text
    assert json.loads(text)["url"] == "/p/second/"
    assert _req(served, "GET", "/p/second/")[0] == 200
    portal = _req(served, "GET", "/")[1]
    assert "href='/p/second/'" in portal
    assert "&lt;b&gt;second&lt;/b&gt;" in portal and "<b>second</b>" not in portal
    assert site_portal.load_registry(settings.root)["second"].title == "A <b>second</b> review"
    listing = json.loads(_req(served, "GET", "/api/projects")[1])
    assert "second" in [p["slug"] for p in listing["projects"]]


def test_the_project_created_event_is_the_human_s_and_never_the_system(
    served: int, settings: Settings, clock: FixedClock
) -> None:
    body = {"slug": "second", "title": "T", "profile": "exploratory"}
    assert _req(served, "POST", "/api/projects/create", body, _hub_token(served))[0] == 200
    project = open_project(settings, "second", session=SESSION, clock=clock)
    events = list(read_all(project.paths.events_dir, project.catalog))
    created = [ev for ev in events if ev.type == "project.created"]
    assert len(created) == 1
    assert created[0].actor.kind == "human"
    assert created[0].payload["rigor_mode"] == "exploratory"
    assert all(ev.actor.kind == "human" for ev in events)


@pytest.mark.parametrize(
    "body",
    [
        {"slug": "Bad Slug", "title": "T", "profile": "pilot"},
        {"slug": "", "title": "T", "profile": "pilot"},
        {"slug": "../etc", "title": "T", "profile": "pilot"},
        {"slug": "lab", "title": "T", "profile": "pilot"},
        {"slug": "demo", "title": "T", "profile": "pilot"},  # exists
        {"slug": "fine", "title": "T", "profile": "nonsense"},
        {"slug": "fine", "title": "x" * 500, "profile": "pilot"},
        {"slug": "fine", "title": 5, "profile": "pilot"},
        {"slug": 5, "title": "T", "profile": "pilot"},
        {"slug": "fine", "title": "T"},
    ],
)
def test_a_refusal_writes_nothing(served: int, settings: Settings, body: dict[str, object]) -> None:
    before = _entries(settings)
    status, text = _req(served, "POST", "/api/projects/create", body, _hub_token(served))
    assert status == 400 and json.loads(text)["ok"] is False
    assert _entries(settings) == before
    assert not (settings.root / "registry.json").exists()


def test_a_project_token_or_no_token_creates_nothing(served: int, settings: Settings) -> None:
    before = _entries(settings)
    body = {"slug": "second", "title": "T", "profile": "pilot"}
    assert _req(served, "POST", "/api/projects/create", body, None)[0] == 403
    assert _req(served, "POST", "/api/projects/create", body, "0" * 64)[0] == 403
    assert _entries(settings) == before


def test_a_refusing_seam_creates_nothing(settings: Settings, clock: FixedClock) -> None:
    class Refuse:
        def check(self, request: site_auth.AuthRequest) -> site_auth.AuthDecision:
            return site_auth.AuthDecision(False, None, "no")

        def page_credential(self, scope: site_auth.Scope) -> str:
            return "t"

    httpd, port = _serve(settings, clock, Refuse())
    try:
        before = _entries(settings) if (settings.root / "projects").exists() else []
        body = {"slug": "second", "title": "T", "profile": "pilot"}
        assert _req(port, "POST", "/api/projects/create", body, "t")[0] == 403
        after = _entries(settings) if (settings.root / "projects").exists() else []
        assert after == before
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_act_is_off_without_a_creator(settings: Settings, clock: FixedClock) -> None:
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
    )
    httpd = site_server.make_main_server(hub, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        assert "id=create-form" not in _req(port, "GET", "/")[1]
        body = {"slug": "second", "title": "T", "profile": "pilot"}
        assert (
            _req(port, "POST", "/api/projects/create", body, _hub_token(port, "/feed/"))[0] == 503
        )
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_second_create_of_the_same_slug_is_refused(served: int, settings: Settings) -> None:
    body = {"slug": "second", "title": "T", "profile": "pilot"}
    token = _hub_token(served)
    assert _req(served, "POST", "/api/projects/create", body, token)[0] == 200
    status, text = _req(served, "POST", "/api/projects/create", body, token)
    assert status == 400 and "already exists" in text


def test_a_hand_edited_registry_that_does_not_parse_is_not_overwritten(
    settings: Settings, clock: FixedClock, project: Project
) -> None:
    (settings.root / "registry.json").write_text("{not json")
    result = create_project(settings, "second", "A title", "pilot", session=SESSION, clock=clock)
    assert result.slug == "second" and result.title_saved is False
    assert (settings.root / "registry.json").read_text() == "{not json"
    assert (settings.root / "projects" / "second" / "events").is_dir()


def test_the_registry_keeps_other_entries_and_hidden_flags(
    settings: Settings, clock: FixedClock, project: Project, tmp_path: Path
) -> None:
    (settings.root / "registry.json").write_text(
        json.dumps({"projects": {"demo": {"title": "Demo", "hidden": True}}, "extra": 1})
    )
    create_project(settings, "second", "Second", "pilot", session=SESSION, clock=clock)
    data = json.loads((settings.root / "registry.json").read_text())
    assert data["projects"]["demo"] == {"title": "Demo", "hidden": True}
    assert data["projects"]["second"]["title"] == "Second" and data["extra"] == 1
