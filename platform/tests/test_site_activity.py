"""The Activity product and `GET /api/activity` (IDEA-98): the page as a file and as served by
the hub, the escaping of task text, the endpoint's JSON and that nothing is written."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from factory.events.envelope import Actor
from factory.services import site_activity, site_server
from factory.services.context import Project
from factory.services.site import products, site_dir
from factory.services.tasks import TaskSpec, claim_next, create_tasks


def _hold(project: Project, agent: Actor, title: str) -> None:
    create_tasks(
        project,
        project.system_actor(),
        [TaskSpec("demo", {"records": [{"work_id": "wrk_1", "title": title}]})],
    )
    claim_next(project, agent, "demo")


def _get(port: int, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read().decode()
    conn.close()
    return response.status, body


@pytest.fixture
def hub(project: Project, agent: Actor) -> Iterator[int]:
    _hold(project, agent, "A <b>bold</b> title")
    out = site_dir(project) / "activity"
    out.mkdir(parents=True, exist_ok=True)
    site_activity.build_activity(project, out)
    httpd, _ = site_server.make_server(project, 0, background=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def test_the_product_is_registered_in_the_mining_group() -> None:
    found = {p.id: p for p in products()}
    assert found["activity"].group == "Mining" and found["activity"].inputs == ("%",)


def test_the_page_as_a_file_is_a_snapshot_with_an_inert_script(
    project: Project, agent: Actor, tmp_path: Path
) -> None:
    _hold(project, agent, "A <b>bold</b> title")
    out = tmp_path / "activity"
    out.mkdir()
    site_activity.build_activity(project, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "A &lt;b&gt;bold&lt;/b&gt; title" in html and "<b>bold</b>" not in html
    for panel in ("id=active", "id=passes", "id=operations", "id=traces"):
        assert panel in html
    assert "Snapshot as of" in html
    assert "meta[name=factory-token]" in html  # the guard reads the meta ...
    assert "<meta name='factory-token'" not in html  # ... which a file never carries
    assert "location.protocol==='file:'" in html
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html
    assert "estimate" in html


def test_the_served_page_carries_the_token_and_polls_the_endpoint(hub: int) -> None:
    status, body = _get(hub, "/activity/")
    assert status == 200
    assert re.search(r"name='factory-token' content='[^']+'", body)
    assert "/api/activity" in body


def test_the_endpoint_answers_the_four_panels(hub: int) -> None:
    status, body = _get(hub, "/api/activity")
    assert status == 200, body
    data = json.loads(body)
    assert set(data) == {"now", "active", "passes", "operations", "traces"}
    assert data["active"][0]["title"] == "A <b>bold</b> title"
    assert data["active"][0]["kind"] == "demo"


def test_serving_and_polling_write_no_event(hub: int, project: Project) -> None:
    events = project.paths.events_dir
    before = {p: p.read_bytes() for p in events.rglob("*") if p.is_file()}
    _get(hub, "/api/activity")
    _get(hub, "/api/activity")
    assert before == {p: p.read_bytes() for p in events.rglob("*") if p.is_file()}
