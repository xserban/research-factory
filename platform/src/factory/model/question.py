"""The question: its slots, non-goals and goal, with a version hash over the semantic fields.

A question version `Q@<sha256[:8]>` hashes the scheme, the primary question, the slots and the
non-goals. Prose (rationales, objectives, scheme reasons) is never hashed, so a prose-only change
keeps the version. Written by `factory.services.question`, folded by `factory.index.question`.
"""

from __future__ import annotations

import hashlib
from typing import Self

from pydantic import Field, JsonValue, model_validator

from factory.canonical import canonical_json
from factory.model.base import StrictModel

NON_GOAL_ID_RE = r"^NG\d{2}$"
QUESTION_ID_RE = r"^Q@[0-9a-f]{8}$"


class Slot(StrictModel):
    """One element of the scheme: fixed to `value`, or `open` until `resolve_in` settles it."""

    name: str = Field(min_length=1)
    value: str | None = None
    open: str | None = None
    resolve_in: str | None = None

    @model_validator(mode="after")
    def _one_of_value_or_open(self) -> Self:
        if (self.value is None) == (self.open is None):
            raise ValueError("exactly one of value or open must be set")
        if self.value is not None:
            if not self.value.strip():
                raise ValueError("value must not be empty")
            if self.value.strip().upper() == "TBD":
                raise ValueError("TBD is not a value; mark the slot open instead")
        if self.open is not None and not self.resolve_in:
            raise ValueError("an open slot must name where it is resolved (resolve_in)")
        return self


class NonGoal(StrictModel):
    id: str = Field(pattern=NON_GOAL_ID_RE)
    text: str = Field(min_length=1)


class QuestionSpec(StrictModel):
    """The question as an agent or a human states it. Slots and non-goals are unique by key."""

    scheme: str = Field(min_length=1)
    primary_question: str = Field(min_length=1)
    slots: tuple[Slot, ...] = Field(min_length=1)
    non_goals: tuple[NonGoal, ...] = ()
    scheme_rationale: str = ""
    rationale: str = ""
    objectives: str = ""

    @model_validator(mode="after")
    def _keys_are_unique(self) -> Self:
        names = [slot.name for slot in self.slots]
        if len(set(names)) != len(names):
            raise ValueError("slot names must be unique")
        ids = [non_goal.id for non_goal in self.non_goals]
        if len(set(ids)) != len(ids):
            raise ValueError("non-goal ids must be unique")
        return self


def question_version(spec: QuestionSpec) -> str:
    """`Q@` plus the first 8 hex digits of the hash over the semantic fields, sorted by key."""
    payload: JsonValue = {
        "scheme": spec.scheme,
        "primary_question": spec.primary_question,
        "slots": [
            [slot.name, slot.value, slot.open, slot.resolve_in]
            for slot in sorted(spec.slots, key=lambda s: s.name)
        ],
        "non_goals": [
            [non_goal.id, non_goal.text] for non_goal in sorted(spec.non_goals, key=lambda g: g.id)
        ],
    }
    return "Q@" + hashlib.sha256(canonical_json(payload)).hexdigest()[:8]


class GoalStated(StrictModel):
    """The raw goal, verbatim. Whitespace is kept; the text must hold a non-whitespace character."""

    text: str

    @model_validator(mode="after")
    def _has_content(self) -> Self:
        if not self.text.strip():
            raise ValueError("goal must contain a non-whitespace character")
        return self


class QuestionRecorded(StrictModel):
    """One recorded version of the question. `question_id` must be the hash of `spec`."""

    question_id: str = Field(pattern=QUESTION_ID_RE)
    supersedes: str | None = Field(default=None, pattern=QUESTION_ID_RE)
    reason: str | None = None
    spec: QuestionSpec

    @model_validator(mode="after")
    def _id_matches_spec(self) -> Self:
        if self.question_id != question_version(self.spec):
            raise ValueError("question_id must be the version hash of spec")
        return self
