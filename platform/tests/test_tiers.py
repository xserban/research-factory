"""Tier plans (contract C3): plan data, skipped steps computed, the brief templates valid through
the normal protocol service, and `factory brief`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.model.levels import RIGOR_OF_TIER, Tier
from factory.model.protocol import Criterion, PlannedQuery, ProtocolStatus, ScreeningStage
from factory.model.search import QueryKind
from factory.services.context import Project
from factory.services.protocol import record_protocol
from factory.services.site_catalog import STAGE_IDS
from factory.tiers import plan_for, report_label, skipped_steps
from tests.helpers import bind_ids, record_pilot_question

runner = CliRunner()
STAGES = tuple(s for s in STAGE_IDS if s != "cross")


@pytest.mark.parametrize("tier", list(Tier))
def test_every_plan_lists_the_catalog_stages_in_order(tier: Tier) -> None:
    plan = plan_for(tier)
    assert plan.tier is tier
    assert tuple(s.stage_id for s in plan.stages) == STAGES


@pytest.mark.parametrize("tier", [Tier.PILOT, Tier.SYSTEMATIC])
def test_pilot_and_systematic_have_no_caps_and_skip_nothing(tier: Tier) -> None:
    plan = plan_for(tier)
    assert all(not s.caps and not s.skipped for s in plan.stages)
    assert plan.limits is None
    assert skipped_steps(tier) == ()
    assert report_label(tier) == ""


def test_brief_caps_are_the_ruled_ones() -> None:
    plan = plan_for(Tier.BRIEF)
    assert (plan.limits.max_papers, plan.limits.max_minutes, plan.limits.max_runs) == (30, 60, 12)  # type: ignore[union-attr]
    assert plan.stage("gather").caps == {
        "sources": 2,
        "searches_per_source": 1,
        "snowball_rounds": 0,
    }
    assert plan.stage("screen").caps["max_screened"] == 40
    assert plan.stage("acquire").caps["max_included"] == 20
    assert plan.stage("extract").caps["max_fields"] == 6
    assert [s.stage_id for s in plan.stages if s.skipped] == ["understand", "develop", "maintain"]
    assert RIGOR_OF_TIER[Tier.BRIEF].value == "exploratory"


def test_deep_limits_and_additions() -> None:
    plan = plan_for(Tier.DEEP)
    lim = plan.limits
    assert lim is not None and (lim.max_papers, lim.max_minutes, lim.max_runs) == (150, 360, 60)
    assert plan.stage("gather").caps["sources"] == 3
    assert plan.stage("gather").caps["snowball_rounds"] == 1
    assert not plan.stage("develop").skipped
    assert plan.protocol_template is not None and plan.protocol_template.press_lite


def test_skipped_steps_are_computed_from_the_plan() -> None:
    steps = skipped_steps(Tier.BRIEF)
    for expected in (
        "understand: skipped",
        "develop: skipped",
        "maintain: skipped",
        "gather: no snowball rounds",
        "screen: max screened capped at 40",
        "frame: no press reviews",
    ):
        assert expected in steps
    assert "write: skipped" not in steps
    assert "understand: skipped" in skipped_steps(Tier.DEEP)
    assert "develop: skipped" not in skipped_steps(Tier.DEEP)
    assert report_label(Tier.BRIEF).startswith("quick review, skipped: ")


def _criteria() -> tuple[Criterion, ...]:
    return (
        Criterion(
            id="IN01",
            statement="studies of vision transformers",
            rule="include studies of vision transformers",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
        ),
        Criterion(
            id="EX01",
            statement="not a vision study",
            rule="exclude studies with no vision task",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
            priority=1,
        ),
    )


@pytest.mark.parametrize("tier", [Tier.BRIEF, Tier.DEEP])
def test_a_tier_template_builds_a_valid_protocol_through_the_service(
    tier: Tier, explore_project: Project, agent: Actor, human: Actor
) -> None:
    template = plan_for(tier).protocol_template
    assert template is not None
    question_id = record_pilot_question(explore_project, agent)
    queries = tuple(
        PlannedQuery(source=s, kind=QueryKind.KEYWORD, text="linear attention")
        for s in template.sources
    )
    spec = template.instantiate(
        question_id, criteria=_criteria(), queries=queries, reviewer=human.id
    )
    assert spec.extraction_schema is not None and len(spec.extraction_schema.fields) <= 6
    result = record_protocol(
        explore_project,
        agent,
        spec,
        ready=True,
        decision_ids=bind_ids(explore_project, agent, DecisionLevel.PROTOCOL),
    )
    assert result.status is ProtocolStatus.READY and result.created
    assert not result.gaps


def test_the_template_refuses_queries_that_break_its_cap() -> None:
    template = plan_for(Tier.BRIEF).protocol_template
    assert template is not None
    two = tuple(
        PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text=t) for t in ("a b", "c d")
    )
    with pytest.raises(ValueError, match="at most 1 query per source"):
        template.instantiate("q", criteria=_criteria(), queries=two, reviewer="obd")
    stray = (PlannedQuery(source="pubmed", kind=QueryKind.KEYWORD, text="a b"),)
    with pytest.raises(ValueError, match="does not name"):
        template.instantiate("q", criteria=_criteria(), queries=stray, reviewer="obd")


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def test_brief_new_plan_and_status(tmp_path: Path) -> None:
    env = _env(tmp_path)
    made = runner.invoke(
        app, ["brief", "new", "Does linear attention match softmax?", "--slug", "lin"], env=env
    )
    assert made.exit_code == 0, made.output
    assert "exploratory" in made.output
    plan = runner.invoke(app, ["brief", "plan", "lin"], env=env)
    assert plan.exit_code == 0, plan.output
    for line in ("tier brief", "limits: 30 papers, 60 minutes, 12 runs", "rf-brief", "understand"):
        assert line in plan.output
    assert "skipped:" in plan.output and "gather: no snowball rounds" in plan.output
    status = runner.invoke(app, ["brief", "status", "lin"], env=env)
    assert status.exit_code == 0, status.output
    assert "mode exploratory" in status.output and "limit 30 papers" in status.output


def test_brief_new_refuses_a_bad_slug_and_writes_nothing(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["brief", "new", "A question", "--slug", "Bad Slug"], env=_env(tmp_path)
    )
    assert result.exit_code == 1
    assert not (tmp_path / "projects").exists() or not any((tmp_path / "projects").iterdir())
