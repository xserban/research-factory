"""Shared worlds for the matching and finder tests (slice 6, plan H-B).

`mw` builds on the card world (`cw`): an approved vocabulary of problem-and-method properties,
one problem description and seven method cards whose subjects are works. The problem asks for

    pr:memory-scaling = linear, pr:tasks covers {detection, segmentation},
    pr:params at-most 100 M, pr:dense = true.

Cards, by the order the matcher must give (conflicting, then satisfied, then unknown, then id):

    ok        all four satisfied (included work)
    transfer  all four satisfied, subject not included in the project
    unknown   three satisfied, `pr:dense` not asserted
    conflict  `pr:memory-scaling` is quadratic, the others satisfied
    inferred  all four, but inferred (human has not confirmed)
    noprop    asserts only a method-only property: never a candidate
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from dataclasses import dataclass

import pytest

from factory.events.envelope import Actor
from factory.model.cards import InferredBasis, PropertyDef
from factory.services.cards import AssertionInput, assert_properties, create_card
from factory.services.context import Project
from tests.card_helpers import CardWorld, approve, cw, prop
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world

MEM = prop(
    "pr:memory-scaling", allowed=["linear", "quadratic"], applies_to="both", value_aliases={}
)
TASKS = prop(
    "pr:tasks",
    kind="set",
    allowed=["classification", "detection", "segmentation"],
    match="covers",
    applies_to="both",
    value_aliases={},
)
PARAMS = prop(
    "pr:params",
    kind="number",
    allowed=[],
    unit_family="count",
    match="at-most",
    applies_to="both",
    value_aliases={},
)
DENSE_BOTH = prop(
    "pr:dense", kind="bool", allowed=[], match="equal", applies_to="both", value_aliases={}
)
METHOD_ONLY = prop("pr:method-only", allowed=["yes", "no"], applies_to="method", value_aliases={})
MATCH_VOCABULARY = (MEM, TASKS, PARAMS, DENSE_BOTH, METHOD_ONLY)

TRANSFER_WORK = "rf:zhou2020-negative-1-73bc34f9"
"""A known work of the card world that screening did not include."""


def item(
    key: str, value: object, unit: str | None = None, *, inferred: bool = False
) -> AssertionInput:
    if inferred:
        return AssertionInput(
            property=key,
            value=value,  # type: ignore[arg-type]
            unit=unit,
            basis_kind="inferred",
            basis=InferredBasis(note="reading of the abstract"),
        )
    return AssertionInput(
        property=key,
        value=value,  # type: ignore[arg-type]
        unit=unit,
        basis_kind="researcher",
    )


def full_items(
    *, memory: str = "linear", dense: bool | None = True, inferred: bool = False
) -> list[AssertionInput]:
    items = [
        item("pr:memory-scaling", memory, inferred=inferred),
        item("pr:tasks", ("classification", "detection", "segmentation"), inferred=inferred),
        item("pr:params", "50", "M", inferred=inferred),
    ]
    if dense is not None:
        items.append(item("pr:dense", dense, inferred=inferred))
    return items


@dataclass
class MatchWorld:
    cw: CardWorld
    problem: str
    ok: str
    transfer: str
    unknown: str
    conflict: str
    inferred: str
    noprop: str
    assertions: dict[str, dict[str, str]]
    """card id -> property -> assertion id."""


def _assert(
    project: Project, actor: Actor, card: str, items: list[AssertionInput]
) -> dict[str, str]:
    result = assert_properties(project, actor, card, items)
    assert result.rejected == [], result.rejected
    return {items[i].property: aid for i, aid, _ in result.accepted}


@pytest.fixture
def mw(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    cw: CardWorld,
    world: list[str],
) -> MatchWorld:
    for definition in MATCH_VOCABULARY:
        approve(project, agent, other_session_human, definition)
    problem = create_card(project, agent, "problem", "Dense prediction under a memory bound", "obd")
    ids: dict[str, dict[str, str]] = {}
    ids[problem] = _assert(
        project,
        human,
        problem,
        [
            item("pr:memory-scaling", "linear"),
            item("pr:tasks", ("detection", "segmentation")),
            item("pr:params", "100", "M"),
            item("pr:dense", True),
        ],
    )

    def method(subject: str, items: list[AssertionInput]) -> str:
        card = create_card(project, agent, "method", subject, "obd")
        ids[card] = _assert(project, human, card, items)
        return card

    ok = method(world[1], full_items())
    transfer = method(TRANSFER_WORK, full_items())
    unknown = method(world[2], full_items(dense=None))
    conflict = method(world[3], full_items(memory="quadratic"))
    inferred = method(world[4], full_items(inferred=True))
    noprop = method(world[5], [item("pr:method-only", "yes")])
    return MatchWorld(cw, problem, ok, transfer, unknown, conflict, inferred, noprop, ids)
