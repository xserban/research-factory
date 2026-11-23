"""The main hub's factory feed acts: `POST /api/feed/react` and `POST /api/feed/train`.

Same guards as the other hub acts (token, JSON, body size, origin); the acts are the local
human's. A fake embedder stands in for SPECTER2; no network, torch or weights."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from http.server import ThreadingHTTPServer

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.model.feed import FeedReacted
from factory.services import factory_feed as ff
from factory.services import site_server
from factory.services.context import Project, list_projects, open_project
from factory.services.factory_scope import open_factory_scope
from tests.helpers import SESSION
from tests.test_factory_feed import FakeEmbedder, world  # noqa: F401 - `world` is a fixture
from tests.test_factory_feed_actions import (
    IDS,
    six,  # noqa: F401 - a fixture
)
from tests.test_site_create import _hub_token, _req


def _serve(
    settings: Settings, clock: FixedClock, *, env: bool = True, **env_kw: object
) -> tuple[ThreadingHTTPServer, int]:
    feed_env = (
        site_server.FactoryFeedEnv(settings, SESSION, clock, **env_kw)  # type: ignore[arg-type]
        if env
        else None
    )
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
        factory_feed=feed_env,
    )
    httpd = site_server.make_main_server(hub, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


@pytest.fixture
def served(
    six: tuple[Settings, Project, Project],  # noqa: F811
    clock: FixedClock,
) -> Iterator[tuple[int, Settings]]:
    settings = six[0]
    ff.rank_pool(settings, FakeEmbedder(), session=SESSION, clock=clock)
    httpd, port = _serve(settings, clock, embedder_factory=FakeEmbedder)
    yield port, settings
    httpd.shutdown()
    httpd.server_close()


def _react(
    port: int, body: Mapping[str, object], token: str | None
) -> tuple[int, dict[str, object]]:
    status, text = _req(port, "POST", "/api/feed/react", body, token)
    return status, json.loads(text) if text.startswith("{") else {}


def test_react_records_the_local_humans_reaction_in_the_factory_scope(
    served: tuple[int, Settings], clock: FixedClock
) -> None:
    port, settings = served
    status, body = _react(
        port, {"entry_id": IDS[0], "reaction": "like"}, _hub_token(port, "/feed/")
    )
    assert status == 200 and body["ok"] is True and body["reaction"] == "like"
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    from factory.events.reader import read_all

    (event,) = [
        e for e in read_all(scope.paths.events_dir, scope.catalog) if e.type == "feed.reacted"
    ]
    assert event.actor.kind == "human" and event.id == body["event_id"]
    assert FeedReacted.model_validate(event.payload).entry_id == IDS[0]
    assert ff.liked(settings, clock=clock)[0].entry_id == IDS[0]


def test_the_guards_hold_and_refusals_are_structured(served: tuple[int, Settings]) -> None:
    port, _ = served
    token = _hub_token(port, "/feed/")
    good = {"entry_id": IDS[0], "reaction": "like"}
    assert _react(port, good, None)[0] == 403
    assert _react(port, good, "wrong")[0] == 403
    status, body = _react(port, {"entry_id": "2699.99999", "reaction": "like"}, token)
    assert status == 400 and "not-ranked" in json.dumps(body)
    assert _react(port, {"entry_id": IDS[0], "reaction": "love"}, token)[0] == 400
    assert _react(port, {"reaction": "like"}, token)[0] == 400
    assert _react(port, {**good, "rank_shown": 0}, token)[0] == 400
    assert _req(port, "POST", "/api/feed/react", good, token)[0] == 200  # a valid one still works


def test_train_below_the_thresholds_is_a_400_with_the_reason(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    token = _hub_token(port, "/feed/")
    status, text = _req(port, "POST", "/api/feed/train", {}, token)
    assert status == 400 and "0 reactions, 5 needed" in text
    assert _req(port, "POST", "/api/feed/train", {}, None)[0] == 403


def test_train_then_today_is_ranked(served: tuple[int, Settings], clock: FixedClock) -> None:
    port, settings = served
    token = _hub_token(port, "/feed/")
    for entry, reaction in zip(
        IDS[:5], ["like", "like", "like", "dislike", "dislike"], strict=True
    ):
        assert _react(port, {"entry_id": entry, "reaction": reaction}, token)[0] == 200
    status, text = _req(port, "POST", "/api/feed/train", {}, token)
    body = json.loads(text)
    assert status == 200 and body["ranker_version"] == 1
    assert (body["likes"], body["dislikes"]) == (3, 2)
    assert {c.ranker_version for c in ff.today(settings, clock=clock).cards} == {1}
    assert _req(port, "POST", "/api/feed/train", {"x": 1}, token)[0] == 400


def test_missing_encoder_weights_are_a_structured_error_not_a_500(
    six: tuple[Settings, Project, Project],  # noqa: F811
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = six[0]
    monkeypatch.delenv("FACTORY_RANKER_MODEL", raising=False)
    ff.rank_pool(settings, FakeEmbedder(), session=SESSION, clock=clock)
    httpd, port = _serve(settings, clock)  # the default encoder factory: SPECTER2
    try:
        token = _hub_token(port, "/feed/")
        for entry, reaction in zip(IDS[:5], ["like"] * 3 + ["dislike"] * 2, strict=True):
            assert _react(port, {"entry_id": entry, "reaction": reaction}, token)[0] == 200
        status, text = _req(port, "POST", "/api/feed/train", {}, token)
        assert status == 400 and "ranker" in text
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_acts_are_off_without_the_factory_feed(
    six: tuple[Settings, Project, Project],  # noqa: F811
    clock: FixedClock,
) -> None:
    httpd, port = _serve(six[0], clock, env=False)
    try:
        token = _hub_token(port, "/feed/")
        assert _react(port, {"entry_id": IDS[0], "reaction": "like"}, token)[0] == 503
        assert _req(port, "POST", "/api/feed/train", {}, token)[0] == 503
    finally:
        httpd.shutdown()
        httpd.server_close()
