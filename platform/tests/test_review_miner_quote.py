"""B1 (hypothesis engine): the critic sees the verbatim quote and anchor of a miner row cited as an
`item` trigger, for technique and `m-claims` rows alike; the lead text stays hidden (R-51)."""

# ruff: noqa: F811
from __future__ import annotations

from factory.events.envelope import Actor
from factory.model.extraction import MinerScope
from factory.model.hypotheses import LeadInput, Trigger, TriggerKind
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import live_rows
from factory.services.finders import ref_quote, ref_source
from factory.services.hypotheses import draft_hypothesis
from factory.services.hypothesis_review import review_next
from factory.services.leads import decide_lead, record_lead
from tests.claims_helpers import QUOTES
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.hypothesis_helpers import CRITIC, DRAFTER, LEAD_AUTHOR, LEAD_TEXT, make_spec
from tests.lead_engine_helpers import QUOTE, engine_world


def _ext(project: Project, miner: str) -> str:
    rows = live_rows(project, PassLabel.A, scope=MinerScope(miner))
    return sorted(r.extraction_id for r in rows)[0]


def test_ref_quote_falls_back_to_a_miner_row_of_any_scope(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    tech = _ext(project, "m-tech-ideation")
    claim = _ext(project, "m-claims")
    assert ref_quote(project, tech) == QUOTE
    assert ref_source(project, tech) == (QUOTE, "s3.p1")
    assert ref_quote(project, claim) in QUOTES
    assert ref_quote(project, "ext_01JZ9Q3K5M7N8P0R2S4T6V8WZZ") is None
    assert ref_quote(project, "rf:not-a-row-00000000") is None


def test_the_critic_view_carries_the_miner_quote_and_not_the_lead_text(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    tech, claim = _ext(project, "m-tech-ideation"), _ext(project, "m-claims")
    triggers = tuple(Trigger(kind=TriggerKind.ITEM, ref=r) for r in (tech, claim))
    lead = record_lead(project, LEAD_AUTHOR, LeadInput(text=LEAD_TEXT, triggers=triggers))
    decide_lead(project, human, lead, "promote")
    draft_hypothesis(project, DRAFTER, make_spec(lead=lead))
    served = review_next(project, CRITIC)
    assert served is not None
    by_ref = {t.ref: t for t in served.task.triggers}
    assert by_ref[tech].quote == QUOTE and by_ref[tech].anchor == "s3.p1"
    assert by_ref[claim].quote in QUOTES and by_ref[claim].anchor == "s3.p1"
    assert LEAD_TEXT not in served.model_dump_json()
