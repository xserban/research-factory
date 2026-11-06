"""Per-paper appraisal: the instrument (a protocol section) and the event payloads (IDEA-21).

An instrument is a list of typed items, each answered about one work and never summed. Three kinds
(plan EQ ruling 1):
- `platform`: computed on read by a named deterministic rule over the conversion; never stored.
- `agent-span`: `yes|no|unclear` from an agent, with a verified quote in one anchor (`unclear`
  needs no quote); two independent passes, disagreement goes to a human.
- `judgement`: `yes|no|unclear` from a human with a rationale; an agent never writes one.

Invariants:
- No total, weight, grade or sort by quality exists (decision 42): nothing here computes one.
- Absent (`None`) on the protocol the section leaves every protocol hash as it was.
- Pure: whether an instrument is acceptable beyond its shape is the protocol rules' concern.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

APPRAISAL_ITEM_RE = r"^[a-z][a-z0-9-]{0,39}$"
APPRAISAL_AUDIT_ID_RE = rf"^aau_{ULID_RE}$"
INSTRUMENT_SECTION = "appraisal_instrument"
PLATFORM_RULE_NAMES = (
    "code-url-present",
    "dataset-named",
    "seeds-reported",
    "hardware-reported",
)
"""The fixed menu of computed rules (plan EQ ruling 1)."""
APPRAISAL_QUOTE_MAX = 600
DIGEST_RE = r"^[0-9a-f]{8}$"


class ItemKind(StrEnum):
    PLATFORM = "platform"
    AGENT_SPAN = "agent-span"
    JUDGEMENT = "judgement"


class Answer(StrEnum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


AppliesTo = Literal["all", "peer-reviewed", "grey"]


class AppraisalItem(StrictModel):
    """One question about a work. `rule` is set exactly for `platform` items."""

    id: str = Field(pattern=APPRAISAL_ITEM_RE)
    statement: str = Field(min_length=1)
    kind: ItemKind
    rule: str | None = None
    applies_to: AppliesTo = "all"

    @model_validator(mode="after")
    def _rule_follows_kind(self) -> Self:
        if (self.kind is ItemKind.PLATFORM) != (self.rule is not None):
            raise ValueError("a rule is named exactly by a platform item")
        return self


class AppraisalInstrument(StrictModel):
    """The declared instrument. `dual_sample` is the fraction of works appraised twice (None =
    every work); the audit fields follow `ExtractionSchema`."""

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    version: int = Field(ge=1)
    items: tuple[AppraisalItem, ...] = Field(min_length=1)
    dual_sample: float | None = Field(default=None, gt=0, le=1)
    audit_fraction: float = Field(default=0.02, ge=0, le=1)
    audit_minimum: int = Field(default=50, ge=0)

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def item(self, item_id: str) -> AppraisalItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def of_kind(self, kind: ItemKind) -> tuple[AppraisalItem, ...]:
        return tuple(i for i in self.items if i.kind is kind)
