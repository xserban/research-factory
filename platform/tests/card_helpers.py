"""Shared builders and world for the card tests (slice 6, plan H-A).

`cw` is the G2 lineage world (`lin`) with an approved four-property vocabulary and one confirmed
lineage idea. The source work's document has these paragraphs (see `contribution_helpers`):

    s1.p1  We build on linear attention [5] for vision.
    s1.p2  Unlike softmax attention [3], our module is linear.
    s1.p3  It reaches 82.4% top-1 on ImageNet.
    s1.p4  A limitation is that very long sequences degrade.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from factory.events.envelope import Actor
from factory.model.cards import PropertyDef, QuoteBasis
from factory.model.lineage import LineageDecision
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.ideas import decide_idea, propose_idea
from factory.services.properties import decide_property, propose_property
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world


def prop(key: str = "pr:sampling", **over: Any) -> PropertyDef:
    """An enum property by default; keyword overrides replace fields."""
    base: dict[str, Any] = {
        "key": key,
        "kind": "enum",
        "allowed": ["regular", "irregular"],
        "match": "equal",
        "applies_to": "both",
        "value_aliases": {"irregular": ["irregularly sampled"]},
    }
    base.update(over)
    return PropertyDef.model_validate(base)


def approve(project: Project, proposer: Actor, decider: Actor, definition: PropertyDef) -> None:
    """Propose `definition` as `proposer` and approve it as `decider` (another session)."""
    propose_property(project, proposer, definition)
    decide_property(project, decider, definition.key, "approve", "fits the question")


ATTENTION = prop(
    "pr:attention-kind",
    allowed=["linear", "softmax"],
    applies_to="method",
    value_aliases={"linear": ["linear attention"], "softmax": ["softmax attention"]},
)
TOP1 = prop(
    "pr:top1",
    kind="number",
    allowed=[],
    unit_family="score",
    match="at-least",
    applies_to="method",
    value_aliases={},
)
LONG_SEQ = prop(
    "pr:long-sequences",
    kind="bool",
    allowed=[],
    match="equal",
    applies_to="both",
    aliases=["long sequences"],
    value_aliases={},
)
DENSE = prop(
    "pr:dense-prediction",
    kind="bool",
    allowed=[],
    match="equal",
    applies_to="problem",
    aliases=["dense prediction"],
    value_aliases={},
)
VOCABULARY = (ATTENTION, TOP1, LONG_SEQ, DENSE)


@dataclass
class CardWorld:
    lin: Lineage
    source: str
    other: str
    conversion_id: str
    idea: str
    """A confirmed lineage idea whose origin is `source`."""


def quote_basis(w: CardWorld, anchor: str, quote: str, *, work: str | None = None) -> QuoteBasis:
    return QuoteBasis(
        work_id=work or w.source, conversion_id=w.conversion_id, anchor=anchor, quote=quote
    )


@pytest.fixture
def cw(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    lin: Lineage,
    world: list[str],
) -> CardWorld:
    for definition in VOCABULARY:
        approve(project, agent, other_session_human, definition)
    conversion = default_conversion(project, lin.source)
    assert conversion is not None
    idea = propose_idea(project, agent, "Linear attention", lin.source, lin.base, [lin.source])
    decide_idea(project, other_session_human, idea, LineageDecision.CONFIRM, "a named idea")
    other = next(w for w in world if w != lin.source)
    return CardWorld(
        lin=lin,
        source=lin.source,
        other=other,
        conversion_id=conversion.conversion_id,
        idea=idea,
    )
