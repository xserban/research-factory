"""The site server's write path (plan 2026-11-11-feed-hub, H2, decision 118): two allow-listed
POSTs behind a per-start token, a loopback Host and a same-origin check; nothing else writes.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from factory.events.reader import read_all
from factory.services import feed as feed_service
from factory.services import feed_read, site_server
from factory.services.context import Project
from factory.services.site import site_dir
from factory.services.site_feed import build_feed
from tests.test_feed_index import CONFIG, _record
from tests.test_feed_read import FIRST, RANKING, _fetch, _ranked


@pytest.fixture
def served(project: Project, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, str]]:
    monkeypatch.setattr(feed_read, "get_work", lambda p, w: SimpleNamespace(title="t"))
    _record(project, "feed.configured", {"config_id": CONFIG, "categories": ["cs.AI"]})
    _fetch(project)
    _ranked(project)
    feed_dir = site_dir(project) / "feed"
    feed_dir.mkdir(parents=True, exist_ok=True)
    build_feed(project, feed_dir)
    httpd, _ = site_server.make_server(project, 0, background=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    status, body = _request(port, "GET", "/feed/")
    assert status == 200
    match = re.search(r"name='factory-token' content='([^']+)'", body)
    assert match is not None
    yield port, match.group(1)
    httpd.shutdown()
    httpd.server_close()


def _request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Content-Type": "application/json", **(headers or {})}
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
    response = conn.getresponse()
    text = response.read().decode()
    conn.close()
    return response.status, text


def _reactions(project: Project) -> list[Any]:
    return [
        e for e in read_all(project.paths.events_dir, project.catalog) if e.type == "feed.reacted"
    ]


REACT = {"entry_id": FIRST, "reaction": "like", "ranking_id": RANKING}


def test_missing_or_wrong_token_writes_nothing(project: Project, served: tuple[int, str]) -> None:
    port, _ = served
    assert _request(port, "POST", "/api/feed/react", REACT)[0] == 403
    bad = {"X-Factory-Token": "nope"}
    assert _request(port, "POST", "/api/feed/react", REACT, bad)[0] == 403
    assert _reactions(project) == []


def test_foreign_origin_and_non_loopback_host_are_refused(
    project: Project, served: tuple[int, str]
) -> None:
    port, token = served
    auth = {"X-Factory-Token": token}
    foreign = {**auth, "Origin": "http://evil.example"}
    assert _request(port, "POST", "/api/feed/react", REACT, foreign)[0] == 403
    host = {**auth, "Host": "evil.example"}
    assert _request(port, "POST", "/api/feed/react", REACT, host)[0] == 403
    assert _reactions(project) == []


def test_unknown_post_path_is_404_and_put_is_405(served: tuple[int, str]) -> None:
    port, token = served
    auth = {"X-Factory-Token": token}
    assert _request(port, "POST", "/api/feed/other", {}, auth)[0] == 404
    assert _request(port, "PUT", "/api/feed/react", REACT, auth)[0] == 405
    assert _request(port, "DELETE", "/api/feed/react", None, auth)[0] == 405


def test_valid_react_writes_one_human_event(project: Project, served: tuple[int, str]) -> None:
    port, token = served
    own = {"X-Factory-Token": token, "Origin": f"http://127.0.0.1:{port}"}
    status, text = _request(port, "POST", "/api/feed/react", REACT, own)
    assert status == 200, text
    assert json.loads(text)["ok"] is True
    events = _reactions(project)
    assert len(events) == 1
    assert events[0].actor.kind == "human"


def test_invalid_reaction_is_400_and_writes_nothing(
    project: Project, served: tuple[int, str]
) -> None:
    port, token = served
    status, text = _request(
        port, "POST", "/api/feed/react", {**REACT, "reaction": "adore"}, {"X-Factory-Token": token}
    )
    assert status == 400
    assert json.loads(text)["ok"] is False
    assert _reactions(project) == []


def test_valid_add_calls_the_service_with_the_sources(
    served: tuple[int, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, token = served
    calls: list[dict[str, Any]] = []

    def fake_add(project: Project, actor: Any, entry_id: str, **kwargs: Any) -> Any:
        calls.append({"entry_id": entry_id, "kind": actor.kind, **kwargs})
        return feed_service.FeedAddResult(
            inbox_item_id="inb_x", outcome="lookup-failed", reason="r"
        )

    monkeypatch.setattr(feed_service, "add", fake_add)
    monkeypatch.setattr(site_server, "_sources", lambda: {"fake": object()})
    status, text = _request(
        port, "POST", "/api/feed/add", {"entry_id": FIRST, "note": "n"}, {"X-Factory-Token": token}
    )
    assert status == 200, text
    assert json.loads(text)["outcome"] == "lookup-failed"
    assert calls[0]["entry_id"] == FIRST
    assert calls[0]["kind"] == "human"
    assert calls[0]["note"] == "n"
    assert set(calls[0]["sources"]) == {"fake"}


def test_built_files_hold_no_token(project: Project, served: tuple[int, str]) -> None:
    _, token = served
    for path in site_dir(project).rglob("*"):
        if path.is_file():
            assert token not in path.read_text(encoding="utf-8", errors="ignore")
