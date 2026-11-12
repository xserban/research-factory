"""The feed in the reports (slice 4c, F7, rulings 10 and 12): the digest feed section, the
discovery channel `feed` and `feed_only_included`, and the `feed-scope-drift` check hit.

The services are exercised with their upstream reads replaced by stubs, so no event or
corpus fixture is needed. `project` is passed as None where the stubs ignore it.
"""

from __future__ import annotations

from typing import cast

import pytest

from factory.living import digest_render
from factory.model.digest import DigestFeed, FeedRow, Listing
from factory.model.feed import FeedConfigured
from factory.services import check as check_service
from factory.services import digest as digest_service
from factory.services import discovery as discovery_service
from factory.services import feed_read
from factory.services.agreement import Outcome
from factory.services.context import Project
from factory.services.discovery import Route, WorkDiscovery
from factory.services.feed_read import FeedListing, FeedListItem, ScopeDrift

NO_PROJECT = cast(Project, None)
SCREENED_EXCLUDED = {f"w{i:02d}": Outcome.EXCLUDED for i in range(10)}


def _config(threshold: float = 0.5, min_count: int = 10) -> FeedConfigured:
    return FeedConfigured.model_construct(
        config_id="fcf_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
        categories=("cs.AI",),
        drift_threshold=threshold,
        drift_min_count=min_count,
    )


def _sent(works: list[str]) -> frozenset[str]:
    return frozenset(works)


def _outcomes(excluded: int, included: int = 0, pending: int = 0) -> dict[str, Outcome]:
    out: dict[str, Outcome] = {}
    n = 0
    for outcome, count in (
        (Outcome.EXCLUDED, excluded),
        (Outcome.INCLUDED, included),
        (Outcome.PENDING, pending),
    ):
        for _ in range(count):
            out[f"w{n:02d}"] = outcome
            n += 1
    return out


def _listing(count: int) -> FeedListing:
    items = tuple(
        FeedListItem(
            entry_id=f"2611.{i:05d}",
            title=f"Paper {i}",
            rank=i + 1,
            score=0.9 - i / 100,
            explore=i == 1,
            nearest_reference=None,
            nearest_reference_title=None,
            reaction=None,
            sent=False,
            inbox_item_id=None,
        )
        for i in range(count)
    )
    return FeedListing(ranking_id="fdr_ranking", reference_hash="a" * 64, reason=None, items=items)


# --- scope drift (ruling 12) ---


def _stub_drift(
    monkeypatch: pytest.MonkeyPatch, config: FeedConfigured | None, sent: frozenset[str]
) -> None:
    monkeypatch.setattr(feed_read, "current_config", lambda _project: config)
    monkeypatch.setattr(feed_read, "feed_work_ids", lambda _project: sent)


def test_drift_fires_at_the_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = _outcomes(excluded=5, included=5)
    _stub_drift(monkeypatch, _config(threshold=0.5, min_count=10), _sent(list(outcomes)))
    drift = feed_read.scope_drift(NO_PROJECT, outcomes)
    assert drift is not None
    assert (drift.screened, drift.excluded, drift.holds) == (10, 5, True)


def test_drift_does_not_fire_below_the_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = _outcomes(excluded=4, included=6)
    _stub_drift(monkeypatch, _config(threshold=0.5, min_count=10), _sent(list(outcomes)))
    drift = feed_read.scope_drift(NO_PROJECT, outcomes)
    assert drift is not None
    assert (drift.screened, drift.excluded, drift.holds) == (10, 4, False)


def test_drift_does_not_fire_below_the_minimum_count(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = _outcomes(excluded=9)
    _stub_drift(monkeypatch, _config(threshold=0.5, min_count=10), _sent(list(outcomes)))
    drift = feed_read.scope_drift(NO_PROJECT, outcomes)
    assert drift is not None
    assert (drift.screened, drift.excluded, drift.holds) == (9, 9, False)


def test_pending_sent_works_are_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = _outcomes(excluded=9, pending=5)
    _stub_drift(monkeypatch, _config(threshold=0.5, min_count=10), _sent(list(outcomes)))
    drift = feed_read.scope_drift(NO_PROJECT, outcomes)
    assert drift is not None
    assert (drift.screened, drift.holds) == (9, False)


def test_unsent_works_are_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = _outcomes(excluded=10)
    _stub_drift(monkeypatch, _config(), frozenset({"w00"}))
    drift = feed_read.scope_drift(NO_PROJECT, outcomes)
    assert drift is not None
    assert (drift.screened, drift.excluded, drift.holds) == (1, 1, False)


def test_no_configuration_gives_no_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_drift(monkeypatch, None, _sent(list(SCREENED_EXCLUDED)))
    assert feed_read.scope_drift(NO_PROJECT, SCREENED_EXCLUDED) is None


def test_check_raises_the_warning_only_when_drift_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    holding = ScopeDrift(
        screened=10,
        excluded=8,
        excluded_works=tuple(SCREENED_EXCLUDED),
        threshold=0.5,
        min_count=10,
        holds=True,
    )
    monkeypatch.setattr(check_service, "scope_drift", lambda _p, _o: holding)
    hits = check_service._feed_drift(NO_PROJECT, SCREENED_EXCLUDED)
    assert [hit.code for hit in hits] == ["feed-scope-drift"]
    assert "consider a protocol amendment" in hits[0].message
    assert "8 of 10" in hits[0].message

    not_holding = holding.model_copy(update={"holds": False})
    monkeypatch.setattr(check_service, "scope_drift", lambda _p, _o: not_holding)
    assert check_service._feed_drift(NO_PROJECT, SCREENED_EXCLUDED) == []


# --- digest feed section ---


def _stub_digest(
    monkeypatch: pytest.MonkeyPatch,
    config: FeedConfigured | None,
    listing: FeedListing,
    drift: ScopeDrift | None,
) -> None:
    monkeypatch.setattr(digest_service, "current_config", lambda _project: config)
    monkeypatch.setattr(digest_service, "feed_list", lambda _project: listing)
    monkeypatch.setattr(digest_service, "pending_sends", lambda _project: 2)
    monkeypatch.setattr(digest_service, "scope_drift", lambda _p, _o: drift)


def test_digest_feed_section_is_absent_without_a_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_digest(monkeypatch, None, _listing(3), None)
    assert digest_service._feed(NO_PROJECT, {}, cap=50) is None


def test_digest_feed_section_caps_items_and_reports_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holding = ScopeDrift(
        screened=10, excluded=6, excluded_works=(), threshold=0.5, min_count=10, holds=True
    )
    _stub_digest(monkeypatch, _config(), _listing(5), holding)
    section = digest_service._feed(NO_PROJECT, {}, cap=3)
    assert section is not None
    assert section.ranking_id == "fdr_ranking"
    assert [row.title for row in section.items.items] == ["Paper 0", "Paper 1", "Paper 2"]
    assert section.items.more == 2
    assert section.pending_sends == 2
    assert section.drift is True


def test_digest_feed_section_renders_explore_and_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_digest(monkeypatch, _config(), _listing(2), None)
    section = digest_service._feed(NO_PROJECT, {}, cap=50)
    assert section is not None
    assert section.drift is False
    lines = digest_render._feed(section)
    assert lines[1] == "### Feed"
    assert any("[explore]" in line and "Paper 1" in line for line in lines)
    assert "- feed-scope-drift: not raised" in lines
    assert "- sends awaiting resolution: 2" in lines


def test_digest_feed_section_before_any_ranking_says_so() -> None:
    section = DigestFeed(
        ranking_id=None,
        items=Listing[FeedRow](items=(), more=0),
        pending_sends=0,
        drift=False,
    )
    assert "No ranking yet." in digest_render._feed(section)


# --- discovery channel (ruling 10) ---


def _record(work_id: str, routes: tuple[Route, ...]) -> WorkDiscovery:
    return WorkDiscovery(
        work_id=work_id,
        routes=routes,
        sources=("feed",),
        first_route=routes[0],
        first_event_id=f"ev-{work_id}",
        first_actor_kind="human",
    )


def _stub_discovery(
    monkeypatch: pytest.MonkeyPatch,
    records: list[WorkDiscovery],
    outcomes: dict[str, Outcome],
    feed: frozenset[str],
) -> None:
    monkeypatch.setattr(discovery_service, "discovery", lambda _project: records)
    monkeypatch.setattr(discovery_service, "current_protocol", lambda _project: None)
    monkeypatch.setattr(discovery_service, "final_outcomes", lambda _project, **_kw: outcomes)
    monkeypatch.setattr(discovery_service, "final_rows", lambda _project: [])
    monkeypatch.setattr(discovery_service, "_groups", lambda _project: {})
    monkeypatch.setattr(discovery_service, "feed_work_ids", lambda _project: feed)


def test_discovery_counts_feed_works_by_level(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        _record("w1", (Route.SUPPLIED_HUMAN,)),
        _record("w2", (Route.DATABASE,)),
    ]
    outcomes = {"w1": Outcome.INCLUDED, "w2": Outcome.EXCLUDED}
    _stub_discovery(monkeypatch, records, outcomes, frozenset({"w1"}))
    report = discovery_service.discovery_report(NO_PROJECT)
    channel = report.by_channel["feed"]
    assert channel == {"identified": 1, "ta-included": 1, "in-evidence": 0}
    assert discovery_service.agent_view(report)["by_channel"] == {"feed": channel}


def test_feed_only_included_needs_supplied_only_inclusion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        discovery_service,
        "_supplied_only",
        lambda _project: {"w1": "human", "w2": "agent"},
    )
    monkeypatch.setattr(discovery_service, "feed_work_ids", lambda _project: frozenset({"w1"}))
    assert discovery_service.feed_only_included(NO_PROJECT) == 1
    monkeypatch.setattr(discovery_service, "feed_work_ids", lambda _project: frozenset({"w3"}))
    assert discovery_service.feed_only_included(NO_PROJECT) == 0


def test_supplied_only_included_still_counts_by_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        discovery_service,
        "_supplied_only",
        lambda _project: {"w1": "human", "w2": "agent", "w3": "human"},
    )
    assert discovery_service.supplied_only_included(NO_PROJECT) == {"human": 2, "agent": 1}
