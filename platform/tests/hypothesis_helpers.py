"""Shared builders for the lead, hypothesis, review and registration tests (slice 6, plan H-C).

Sessions are distinct on purpose: `DRAFTER` is the default test session, `CRITIC` and `LEAD_AUTHOR`
are others, and each has its own model so the independence rules can be told apart.
"""

# ruff: noqa: F401

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.model.hypotheses import LeadInput, Trigger, TriggerKind
from factory.model.screening import PassLabel
from factory.modules.contract import PolicyKind
from factory.services.cards import create_card
from factory.services.context import Project
from tests.finder_helpers import MatchWorld, mw
from tests.helpers import S2, S3, SESSION, record_pilot_question
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world

S4 = "01JZ9Q3K5M7N8P0R2S4T6V8W11"
LEAD_TEXT = "Kernelised attention may keep accuracy while removing the quadratic memory term."
RATIONALE = "I believe the kernel trick transfers because of an argument the critic must not see."
STATEMENT = "Linear attention matches softmax attention top-1 accuracy on ImageNet-1k at 224."


def agent_actor(session: str, model: str, name: str, skill: str = "rf-ideate@1a2b3c4d") -> Actor:
    return Actor(kind="agent", id=name, user="obd", session=session, model=model, skill=skill)


DRAFTER = agent_actor(SESSION, "model-drafter", "drafter")
CRITIC = agent_actor(S2, "model-critic", "critic", "rf-critic@1a2b3c4d")
LEAD_AUTHOR = agent_actor(S3, "model-lead", "lead-author")
OTHER = agent_actor(S4, "model-other", "other")


def lead_input(
    text: str = LEAD_TEXT, *triggers: Trigger, framework: str | None = None
) -> LeadInput:
    return LeadInput(text=text, triggers=triggers, framework=framework)


def card_trigger(card_id: str) -> Trigger:
    return Trigger(kind=TriggerKind.CARD, ref=card_id)


def exploratory_card(project: Project, human: Actor) -> str:
    """A problem card in an exploratory project (preset `agent` for the hypothesis gates): a
    cheap resolvable trigger that needs no corpus."""
    record_pilot_question(project, human)
    return create_card(project, DRAFTER, "problem", "Dense prediction under a memory bound", "obd")
