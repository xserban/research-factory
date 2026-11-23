"""The main hub server (plan 2026-11-13-main-hub, part 1): a portal at `/`, each project's hub at
`/p/<slug>/`, one write token per project, every scanned project's hub written before serving."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.services import site_portal, site_server
from factory.services.context import Project, list_projects, open_project
from factory.services.project import init_project
from factory.services.site import site_dir
from tests.helpers import SESSION


def _get(
    port: int, path: str, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("GET", path, headers=headers or {})
    response = conn.getresponse()
    body = response.read().decode(errors="replace")
    head = {k.lower(): v for k, v in response.getheaders()}
    conn.close()
    return response.status, head, body


def _post(port: int, path: str, body: dict[str, Any], token: str | None) -> int:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Factory-Token"] = token
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("POST", path, body=json.dumps(body), headers=headers)
    response = conn.getresponse()
    response.read()
    conn.close()
    return response.status


def _token(page: str) -> str:
    match = re.search(r"name='factory-token' content='([^']+)'", page)
    assert match is not None
    return match.group(1)


@pytest.fixture
def two(settings: Settings, clock: FixedClock, project: Project) -> Project:
    """A second project under the same root (`project` is `demo`)."""
    return init_project(settings, "other", "pilot", session=SESSION, clock=clock)


def _hub(settings: Settings, clock: FixedClock) -> site_server.MainHub:
    return site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
    )


@pytest.fixture
def served(
    settings: Settings, clock: FixedClock, two: Project
) -> Iterator[tuple[int, site_server.MainHub]]:
    hub = _hub(settings, clock)
    httpd: ThreadingHTTPServer = site_server.make_main_server(hub, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1], hub
    httpd.shutdown()
    httpd.server_close()


def _action_page(project: Project) -> None:
    folder = site_dir(project) / "feed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text("<html><head></head><body>feed</body></html>")


def test_every_scanned_project_has_its_hub_before_the_first_request(
    served: tuple[int, site_server.MainHub], project: Project, two: Project
) -> None:
    assert (site_dir(project) / "index.html").is_file()
    assert (site_dir(two) / "index.html").is_file()


def test_the_portal_lists_each_project_with_a_link_to_its_hub(
    served: tuple[int, site_server.MainHub],
) -> None:
    port, _ = served
    status, head, body = _get(port, "/")
    assert status == 200 and head["content-type"].startswith("text/html")
    assert "href='/p/demo/ui/'" in body and "href='/p/other/ui/'" in body
    assert "href='/p/demo/'" in body  # the classic hub, a second link
    listing = json.loads(_get(port, "/api/projects")[2])
    assert [p["slug"] for p in listing["projects"]] == ["demo", "other"]
    assert all(p["hub_ready"] for p in listing["projects"])


def test_each_project_is_served_under_its_own_prefix_with_a_way_back(
    served: tuple[int, site_server.MainHub],
) -> None:
    port, _ = served
    for slug in ("demo", "other"):
        status, _, body = _get(port, f"/p/{slug}/")
        assert status == 200 and f"<title>{slug}</title>" in body
        assert "href='/'" in body and "All projects" in body


def test_a_static_file_of_a_project_is_served_under_its_prefix(
    served: tuple[int, site_server.MainHub], project: Project
) -> None:
    port, _ = served
    (site_dir(project) / "note.txt").write_text("only demo")
    assert _get(port, "/p/demo/note.txt")[2] == "only demo"
    assert _get(port, "/p/other/note.txt")[0] == 404


def test_a_project_url_without_a_slash_redirects_and_unknown_paths_are_404(
    served: tuple[int, site_server.MainHub],
) -> None:
    port, _ = served
    status, head, _ = _get(port, "/p/demo")
    assert status == 301 and head["location"] == "/p/demo/"
    for path in ("/p/nope/", "/p/nope", "/p/../etc/passwd", "/elsewhere", "/p/"):
        assert _get(port, path)[0] == 404, path


def test_action_pages_get_their_token_and_their_api_prefix(
    served: tuple[int, site_server.MainHub], project: Project, two: Project
) -> None:
    port, _ = served
    _action_page(project)
    _action_page(two)
    demo = _get(port, "/p/demo/feed/")[2]
    other = _get(port, "/p/other/feed/")[2]
    assert "name='factory-api' content='/p/demo'" in demo
    assert "name='factory-api' content='/p/other'" in other
    assert _token(demo) != _token(other)


def test_a_token_from_one_project_writes_nothing_to_another(
    served: tuple[int, site_server.MainHub], project: Project, two: Project
) -> None:
    port, _ = served
    _action_page(project)
    _action_page(two)
    demo_token = _token(_get(port, "/p/demo/feed/")[2])
    other_token = _token(_get(port, "/p/other/feed/")[2])
    act = {"reaction": "like"}
    assert _post(port, "/p/other/api/feed/react", act, demo_token) == 403
    assert _post(port, "/p/other/api/feed/react", act, None) == 403
    # the right token reaches the act, which refuses the missing entry (400): routed, not forbidden
    assert _post(port, "/p/other/api/feed/react", act, other_token) == 400
    assert _post(port, "/p/nope/api/feed/react", act, other_token) == 404
    # the hub's own route (the factory feed's reaction) takes the hub token, not a project's
    assert _post(port, "/api/feed/react", act, other_token) == 403


def test_projects_do_not_share_a_write_lock(
    served: tuple[int, site_server.MainHub],
) -> None:
    _, hub = served
    a, b = hub.slot("demo"), hub.slot("other")
    assert a is not None and b is not None
    assert a.write_lock is not b.write_lock and a.advance_gate is not b.advance_gate


def test_a_project_created_after_the_start_is_found_and_gets_its_hub(
    served: tuple[int, site_server.MainHub], settings: Settings, clock: FixedClock
) -> None:
    port, _ = served
    late = init_project(settings, "late", "pilot", session=SESSION, clock=clock)
    assert _get(port, "/p/late/")[0] == 200
    assert (site_dir(late) / "index.html").is_file()
    assert "href='/p/late/'" in _get(port, "/")[2]


def test_the_single_project_server_has_an_empty_api_prefix_and_no_portal_link(
    project: Project,
) -> None:
    _action_page(project)
    httpd, _ = site_server.make_server(project, 0, background=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        assert "name='factory-api' content=''" in _get(port, "/feed/")[2]
        assert "All projects" not in _get(port, "/")[2]
        assert _get(port, "/api/projects")[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_registry_gives_titles_and_hides_projects_without_unserving_them(
    settings: Settings, clock: FixedClock, project: Project, two: Project
) -> None:
    (settings.root / "registry.json").write_text(
        json.dumps(
            {"projects": {"demo": {"title": "<b>Demo</b> review"}, "other": {"hidden": True}}}
        )
    )
    hub = _hub(settings, clock)
    httpd = site_server.make_main_server(hub, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        page = _get(port, "/")[2]
        assert "&lt;b&gt;Demo&lt;/b&gt; review" in page and "<b>Demo</b>" not in page
        assert "href='/p/other/'" not in page
        assert _get(port, "/p/other/")[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize(
    "text", ["", "not json", "[]", '{"projects": []}', '{"projects": {"a": 1}}']
)
def test_a_bad_registry_is_an_empty_one(tmp_path: Path, text: str) -> None:
    (tmp_path / "registry.json").write_text(text)
    assert site_portal.load_registry(tmp_path) == {}


def test_a_missing_registry_is_an_empty_one(tmp_path: Path) -> None:
    assert site_portal.load_registry(tmp_path) == {}


def test_a_remote_host_is_refused_on_the_portal_too(
    served: tuple[int, site_server.MainHub],
) -> None:
    port, _ = served
    assert _get(port, "/", {"Host": "evil.example"})[0] == 403


def test_the_portal_answers_while_a_project_is_rebuilding(
    served: tuple[int, site_server.MainHub],
) -> None:
    """A rebuild holds the rebuilder's lock for minutes; the portal must not wait for it."""
    port, hub = served
    slot = hub.slot("demo")
    assert slot is not None
    with slot.rebuilder._lock:  # what `rebuild_if_stale` holds while it builds
        status, _, body = _get(port, "/")
        listing = json.loads(_get(port, "/api/projects")[2])
    assert status == 200 and "Rebuilding" in body
    demo = next(p for p in listing["projects"] if p["slug"] == "demo")
    assert demo["building"] is True
    other = next(p for p in listing["projects"] if p["slug"] == "other")
    assert other["building"] is False
