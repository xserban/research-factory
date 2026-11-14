"""The portal's add-to-inbox form (hub act `POST /api/inbox/add`): the form is on the portal, a
link is captured as the local human, a repeat is a duplicate, bad input and a missing token write
nothing, and the service is never reached on a refusal. No new event type; no model."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryError
from factory.services import inbox as inbox_service
from factory.services import site_server
from factory.services.context import Project, list_projects, open_project
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


def _token(port: int) -> str:
    match = re.search(r"name='factory-token' content='([^']+)'", _req(port, "GET", "/")[1])
    assert match is not None
    return match.group(1)


@pytest.fixture
def served(settings: Settings, clock: FixedClock, project: Project) -> Iterator[int]:
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
        create=lambda slug, title, profile: (_ for _ in ()).throw(AssertionError("unused")),
    )
    httpd = site_server.make_main_server(hub, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _items(project: Project) -> list[Any]:
    return inbox_service.list_items(project).items


def test_the_portal_has_the_inbox_form(served: int) -> None:
    page = _req(served, "GET", "/")[1]
    assert "id=inbox-form" in page and "name=project" in page and "name=value" in page
    assert "<option value='demo'>" in page and "inbox-msg" in page


def test_a_link_is_captured_as_the_human(served: int, project: Project) -> None:
    body = {"project": "demo", "value": " arXiv:2401.01234 ", "note": "from the portal"}
    status, text = _req(served, "POST", "/api/inbox/add", body, _token(served))
    assert status == 200, text
    out = json.loads(text)
    assert out["ok"] is True and out["duplicate"] is False
    items = _items(project)
    assert [i.item_id for i in items] == [out["item_id"]]
    assert items[0].actor_kind == "human" and items[0].note == "from the portal"


def test_a_repeat_is_a_duplicate_and_writes_nothing(served: int, project: Project) -> None:
    token = _token(served)
    first = json.loads(
        _req(served, "POST", "/api/inbox/add", {"project": "demo", "value": "2401.01234"}, token)[1]
    )
    status, text = _req(
        served, "POST", "/api/inbox/add", {"project": "demo", "value": "arxiv:2401.01234"}, token
    )
    assert status == 200
    again = json.loads(text)
    assert again["duplicate"] is True and again["item_id"] == first["item_id"]
    assert len(_items(project)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"project": "demo", "value": "not a link at all"},
        {"project": "demo", "value": ""},
        {"project": "demo"},
        {"value": "2401.01234"},
        {"project": "nope", "value": "2401.01234"},
        {"project": "demo", "value": "2401.01234", "note": 5},
        {"project": "demo", "value": "2401.01234", "note": "x" * 301},
    ],
)
def test_bad_input_is_400_and_writes_nothing(served: int, project: Project, body: Any) -> None:
    status, text = _req(served, "POST", "/api/inbox/add", body, _token(served))
    assert status == 400, text
    assert json.loads(text)["issues"]
    assert _items(project) == []


def test_a_missing_or_wrong_token_is_refused(served: int, project: Project) -> None:
    body = {"project": "demo", "value": "2401.01234"}
    assert _req(served, "POST", "/api/inbox/add", body, None)[0] == 403
    assert _req(served, "POST", "/api/inbox/add", body, "0" * 64)[0] == 403
    assert _items(project) == []


def test_a_refused_command_is_403_and_the_service_does_not_run(
    served: int, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused: list[str] = []

    def refuse(project: Project, principal: Any, tool: str) -> None:
        refused.append(tool)
        raise FactoryError("not allowed")

    monkeypatch.setattr(site_server, "authorize_command", refuse)
    body = {"project": "demo", "value": "2401.01234"}
    assert _req(served, "POST", "/api/inbox/add", body, _token(served))[0] == 403
    assert refused == ["cli:inbox add"] and _items(project) == []
