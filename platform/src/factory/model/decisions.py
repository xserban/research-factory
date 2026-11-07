"""Suggested decisions and the scientist's selection (slice 8, plan A1).

Invariants enforced here (validated at the boundary, before any event is written):
- A decision is a set of suggested items at one level (goal, questions, plan, seeds, probe,
  protocol), with the step explained and each item grounded in references (a probe id, a seed id,
  a document name, an earlier decision id). An empty `grounds` is legal to write; a later check
  rule flags it. Item ids are unique within a decision.
- `recommended` marks an item the agent advises. Only technical subjects (`TECHNICAL_SUBJECTS`)
  may carry it; a research subject is the scientist's to choose and carries no recommendation.
- A selection names suggested item ids (unique) and may add free-text items. At least one of
  `selected` and `added` is non-empty; an explicit "none of these" is an empty selection with a
  non-blank `note` that says why. `reconstructed` marks a selection back-filled for a decision made
  before this slice.
- Who may suggest (an agent) and who may select (a human, over an unforged channel) is a service
  and fold rule, not a payload rule. Superseding is a new suggestion with `supersedes` set.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.screening import Channel, NonBlank

DECISION_ID_RE = rf"^dec_{ULID_RE}$"
ITEM_ID_RE = r"^I\d{2,}$"
ADDED_ID_RE = r"^A\d{2,}$"
SUBJECT_RE = r"^[a-z0-9]+(-[a-z0-9]+)*$"
MAX_ITEMS = 30
MAX_TEXT = 1200
MAX_EXPLANATION = 2400
MAX_NOTE = 600

TECHNICAL_SUBJECTS = frozenset({"tooling", "ordering", "fix", "model-choice", "setting"})
"""Subjects about how the work is run, not what it asks: only these may carry `recommended`."""

DecisionId = Annotated[str, StringConstraints(pattern=DECISION_ID_RE)]
ItemId = Annotated[str, StringConstraints(pattern=ITEM_ID_RE)]
Text = Annotated[NonBlank, StringConstraints(max_length=MAX_TEXT)]


class DecisionLevel(StrEnum):
    GOAL = "goal"
    QUESTIONS = "questions"
    PLAN = "plan"
    SEEDS = "seeds"
    PROBE = "probe"
    PROTOCOL = "protocol"


class DecisionItem(StrictModel):
    """One suggested option. `grounds` may be empty here; the check flags it."""

    item_id: ItemId
    text: Text
    grounds: tuple[Annotated[str, StringConstraints(min_length=1, max_length=200)], ...] = ()
    recommended: bool = False


class DecisionSuggested(StrictModel):
    """An agent's suggestion at one level. Invariants: at least one item, unique item ids,
    `recommended` only on a technical subject, `supersedes` (if any) names an earlier decision."""

    decision_id: DecisionId
    level: DecisionLevel
    subject: str = Field(pattern=SUBJECT_RE, max_length=60)
    explanation: Annotated[NonBlank, StringConstraints(max_length=MAX_EXPLANATION)]
    items: tuple[DecisionItem, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    supersedes: DecisionId | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("item ids must be unique within a decision")
        if self.subject not in TECHNICAL_SUBJECTS and any(i.recommended for i in self.items):
            raise ValueError(
                f"subject {self.subject!r} is a research subject: no item may be recommended"
            )
        if self.supersedes == self.decision_id:
            raise ValueError("a decision cannot supersede itself")
        return self


class DecisionSelected(StrictModel):
    """The scientist's choice on one decision. Invariants: selected ids are unique; at least one of
    `selected` and `added` is non-empty, unless `note` is non-blank (an explicit "none"). `channel`
    is how the act came (`elicit` is a person answering over an authenticated connection)."""

    decision_id: DecisionId
    selected: tuple[ItemId, ...] = ()
    added: tuple[Text, ...] = ()
    note: Annotated[str, StringConstraints(max_length=MAX_NOTE)] = ""
    reconstructed: bool = False
    channel: Channel = Channel.MCP

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.selected)) != len(self.selected):
            raise ValueError("selected item ids must be unique")
        if not self.selected and not self.added and not self.note.strip():
            raise ValueError("an empty selection (none of these) needs a note that says why")
        if len(self.added) > MAX_ITEMS:
            raise ValueError("too many added items")
        return self
