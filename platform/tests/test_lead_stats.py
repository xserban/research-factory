"""Lead statistics (hypothesis engine, task 5): counts computed from the tables."""

# ruff: noqa: F811
from __future__ import annotations

from factory.events.envelope import Actor
from factory.model.hypotheses import DiscardReason, LeadInput, Trigger, TriggerKind
from factory.model.lead_engine import Candidate
from factory.services.context import Project
from factory.services.hypotheses import draft_hypothesis
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_stats import lead_stats, scope_source
from factory.services.leads import decide_lead, record_lead
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.hypothesis_helpers import DRAFTER, LEAD_AUTHOR, LEAD_TEXT, make_spec
from tests.lead_engine_helpers import engine_world


def _record(project: Project, *candidates: Candidate) -> str:
    triggers = tuple(
        Trigger(kind=TriggerKind(t.kind), ref=t.ref) for c in candidates for t in c.triggers
    )
    return record_lead(project, LEAD_AUTHOR, LeadInput(text=LEAD_TEXT, triggers=triggers))


def test_a_project_without_leads_gives_zeros(project: Project) -> None:
    stats = lead_stats(project)
    assert stats.recorded == 0 and stats.decided == 0
    assert stats.by_state == {"open": 0, "promoted": 0, "parked": 0, "discarded": 0}
    assert stats.promotion_rate is None and stats.decided_promotion_rate is None
    assert stats.hypotheses_drafted == 0 and stats.reviews == 0 and stats.outcomes == {}
    assert stats.by_source == {} and stats.oldest_undecided == ()


def test_counts_equal_what_the_stream_recorded(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    found = lead_candidates(project, layer="all", technique_min_works=1)
    by_source: dict[str, Candidate] = {}
    for c in found.candidates:
        by_source.setdefault(c.source, c)
    tech, claim = by_source["technique-challenge"], by_source["claims-limitation"]
    combo, gap = by_source["technique-combination"], by_source["technique-gap"]
    promoted = _record(project, claim)
    discarded = _record(project, combo)
    parked = _record(project, gap)
    undecided = _record(project, tech, claim)
    decide_lead(project, human, promoted, "promote")
    decide_lead(project, human, discarded, "discard", DiscardReason.DUPLICATE)
    decide_lead(project, human, parked, "park")
    draft_hypothesis(project, DRAFTER, make_spec(lead=promoted))
    stats = lead_stats(project)
    assert stats.recorded == 4 and stats.decided == 3
    assert stats.by_state == {"open": 1, "promoted": 1, "parked": 1, "discarded": 1}
    assert stats.promotion_rate == 0.25 and stats.decided_promotion_rate == 1 / 3
    assert stats.discard_reasons == {"duplicate": 1}
    assert stats.by_trigger_kind == {"item": 4, "work": 4}
    assert stats.by_source["claims"]["promoted"] == 1
    assert stats.by_source["technique"] == {
        "recorded": 2,
        "open": 0,
        "promoted": 0,
        "parked": 1,
        "discarded": 1,
    }
    assert stats.by_source["mixed"]["open"] == 1
    assert stats.hypotheses_drafted == 1 and stats.hypotheses_by_state["draft"] == 1
    assert stats.hypotheses_registered == 0 and stats.hypotheses_closed == {
        "abandoned": 0,
        "concluded": 0,
    }
    [old] = stats.oldest_undecided
    assert (old.lead_id, old.source, old.triggers) == (
        undecided,
        "mixed",
        5,
    )  # the shared work is one trigger
    assert lead_stats(project).model_dump_json() == stats.model_dump_json()
    assert "text" not in stats.model_dump_json().split('"oldest_undecided"')[1]


def test_scope_source_labels() -> None:
    assert scope_source([]) == "none"
    assert scope_source(["m-tech-ideation", "m-tech-experiment"]) == "technique"
    assert scope_source(["m-claims"]) == "claims"
    assert scope_source(["evidence"]) == "rows"
    assert scope_source(["m-other"]) == "other-miner"
    assert scope_source(["m-claims", "evidence"]) == "mixed"


def test_the_stats_are_labelled_and_the_oldest_undecided_follow_the_event_not_the_id(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    from sqlalchemy import text

    engine_world(project, agent, human, world)
    found = lead_candidates(project, layer="all", technique_min_works=1)
    first, second = found.candidates[0], found.candidates[1]
    a, b = _record(project, first), _record(project, second)
    stats = lead_stats(project)
    assert stats.exploratory is True and stats.klass == "interpretation"
    assert "exploratory" in stats.notice
    assert '"class"' in stats.model_dump_json(by_alias=True)
    assert [o.lead_id for o in stats.oldest_undecided] == sorted([a, b], key=lambda i: i)
    with project.index._engine.begin() as conn:  # a test world: the projection is rebuildable
        ids = {
            str(r[0]): str(r[1]) for r in conn.execute(text("SELECT lead_id, event_id FROM leads"))
        }
        conn.execute(
            text("UPDATE leads SET event_id = :e WHERE lead_id = :l"), {"e": "0", "l": max(a, b)}
        )
    order = [o.lead_id for o in lead_stats(project).oldest_undecided]
    assert order == [max(a, b), min(a, b)] and ids  # the lead with the older event comes first


def test_the_stats_table_is_compact_and_json_stays_complete() -> None:
    from datetime import UTC, datetime

    from factory.cli import render
    from factory.model.lead_engine import LeadStats, OldestLead

    long = "a very long framework name " * 12
    stats = LeadStats(
        recorded=300,
        by_state={"open": 200, "promoted": 40, "parked": 30, "discarded": 30},
        decided=100,
        promotion_rate=0.1333,
        decided_promotion_rate=0.4,
        discard_reasons={f"reason number {i} " * 8: i + 1 for i in range(8)},
        by_trigger_kind={"item": 300, "work": 300},
        by_source={"claims": {"recorded": 300, "open": 200, "promoted": 40, "parked": 30}},
        hypotheses_drafted=12,
        hypotheses_by_state={"draft": 12},
        hypotheses_registered=0,
        hypotheses_closed={"abandoned": 0, "concluded": 0},
        reviews=3,
        reviews_by_recommendation={"revise": 3},
        outcomes={},
        oldest_undecided=tuple(
            OldestLead(
                lead_id=f"lead_{'x' * 40}{i}",
                framework=long,
                triggers=20,
                source="claims",
                event_id=str(i),
                recorded_at="2026-11-01T10:00:00Z",
            )
            for i in range(10)
        ),
    )
    lines = render.lead_stats_lines(stats, now=datetime(2026, 11, 20, tzinfo=UTC))
    assert lines[0].startswith("EXPLORATORY") and max(len(x) for x in lines) <= 110
    assert any("18d" in x for x in lines) and sum("oldest" in x for x in lines) == 1
    assert sum(x.startswith("  lead_") for x in lines) == 5
    at = lines.index("discard reasons (top 5):")
    assert "reason number 7" in lines[at + 1] and "reason number 3" in lines[at + 5]
    assert "reason number 2" not in " ".join(lines)
    assert len(stats.model_dump_json()) > 3000 and "reason number 0" in stats.model_dump_json()
