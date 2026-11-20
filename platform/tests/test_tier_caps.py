"""The platform enforces the tier caps (lane L14): the title/abstract queue and the full-text
fetch stop at the caps of a `brief` or `deep` plan; legacy, pilot and systematic projects are never
capped. The caps are read from `tiers/plans.py`; the world tests lower them to a small number."""

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.fulltext import Route
from factory.model.levels import Tier
from factory.model.screening import PassLabel
from factory.services import fulltext as fulltext_module
from factory.services import screening as screening_module
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.level_statement import level_statement
from factory.services.project import init_project
from factory.services.screening import screen_next
from factory.services.tier_caps import ACQUIRE_CAP, SCREEN_CAP, tier_cap
from factory.tiers.plans import PLANS
from tests.fulltext_helpers import _promoted_corpus
from tests.helpers import SESSION, SourcesFor
from tests.route_helpers import always, retrieved, routes_for
from tests.screening_helpers import _batch

SMALL = 1


def _promoted(project: Project) -> list[str]:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _tier_project(settings: Settings, clock: FixedClock, tier: str | None, slug: str) -> Project:
    return init_project(
        settings, slug, None if tier else "pilot", session=SESSION, clock=clock, tier=tier
    )


def test_caps_come_from_the_plan_for_brief_and_deep_only(
    settings: Settings, clock: FixedClock
) -> None:
    for tier in ("brief", "deep"):
        project = _tier_project(settings, clock, tier, tier)
        plan = PLANS[Tier(tier)]
        assert tier_cap(project, SCREEN_CAP) == plan.stage("screen").caps["max_screened"]
        assert tier_cap(project, ACQUIRE_CAP) == plan.stage("acquire").caps["max_included"]
    for tier in ("pilot", "systematic", None):
        project = _tier_project(settings, clock, tier, f"u-{tier or 'legacy'}")
        assert tier_cap(project, SCREEN_CAP) is None
        assert tier_cap(project, ACQUIRE_CAP) is None


def test_the_level_statement_lists_the_caps(settings: Settings, clock: FixedClock) -> None:
    project = _tier_project(settings, clock, "brief", "stated")
    text = "\n".join(level_statement(project).lines)
    assert "screen: max screened capped at" in text
    assert "acquire: max included capped at" in text


def test_screening_refuses_past_the_cap(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    assert len(batch.records) >= SMALL
    before = len(list(project.paths.events_dir.rglob("*.jsonl")))
    monkeypatch.setattr(screening_module, "tier_cap", lambda _p, _which: SMALL)
    with pytest.raises(FactoryValidationError) as refused:
        screen_next(project, agent, PassLabel.A)
    [issue] = refused.value.issues
    assert issue.field == "tier"
    assert issue.reason.startswith("tier-cap-reached")
    assert "1" in issue.reason and "max_screened" in issue.reason
    assert len(list(project.paths.events_dir.rglob("*.jsonl"))) == before


def test_screening_without_a_cap_is_unchanged(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _batch(project, agent, human, mock_sources)
    assert screen_next(project, agent, PassLabel.A) is not None


def test_fetch_stops_at_the_cap(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _promoted_corpus(project, agent, human, mock_sources)
    stubs = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"x")))
    promoted = _promoted(project)
    assert len(promoted) >= 2
    cap = len(promoted) - 1
    monkeypatch.setattr(fulltext_module, "tier_cap", lambda _p, _which: cap)
    first = fetch_fulltext(project, routes=stubs, limit=20)
    assert len(first.works) == cap
    with pytest.raises(FactoryValidationError) as refused:
        fetch_fulltext(project, routes=stubs, limit=20)
    [issue] = refused.value.issues
    assert issue.field == "tier"
    assert issue.reason.startswith("tier-cap-reached")
    assert "max_included" in issue.reason


def test_fetch_without_a_cap_takes_every_promoted_work(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _promoted_corpus(project, agent, human, mock_sources)
    stubs = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"x")))
    summary = fetch_fulltext(project, routes=stubs, limit=20)
    assert len(summary.works) == len(_promoted(project))
