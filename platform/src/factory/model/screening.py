"""Screening value types and event payloads: verdicts, passes, decisions, calibration and audit.

Invariants enforced here (validated at the boundary, before any event is written):
- `include` and `cannot-assess` promote; `exclude` and `unsure` do not.
- Every exclusion names an EX criterion, human labels included (R-30); an inclusion never
  cites an EX criterion. `exclude` needs a rationale; `cannot-assess` needs a criterion;
  `unsure` needs a rationale. Text fields must not be blank after stripping.
- A decision's criterion is version-qualified (`P@<hash>:EX03`), so a decision stays
  interpretable after a protocol amendment.
- A pass join is an agent's (with its model) or a human's (with the user, without a model); a
  line written before human passes reads as an agent's, and an agent's join is written as it was.
- A quote is never blank. Only a human decision may have none (`""`, slice 5 ruling 15, R-110).

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from factory.document.anchors import ANCHOR_RE
from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE, CONVERSION_ID_RE, ULID_RE
from factory.model.protocol import CRITERION_ID_RE, PROTOCOL_ID_RE, ScreeningStage

DECISION_ID_RE = rf"^dec_{ULID_RE}$"
AUDIT_ID_RE = rf"^aud_{ULID_RE}$"
QUALIFIED_CRITERION_RE = r"^P@[0-9a-f]{8}:(IN|EX)\d{2}$"
"""A criterion qualified by the protocol version that defines it, e.g. `P@1a2b3c4d:EX03`."""
CELL_ANCHOR_RE = r"^t\d+\.r\d+\.c\d+$"
"""A table cell anchor, e.g. `t2.r5.c3`: a cell of a converted table, not a unit of its own."""


class Verdict(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    CANNOT_ASSESS = "cannot-assess"
    UNSURE = "unsure"

    @property
    def promotes(self) -> bool:
        """Whether a work with this verdict proceeds to the next stage."""
        return self in (Verdict.INCLUDE, Verdict.CANNOT_ASSESS)


class PassLabel(StrEnum):
    A = "A"
    B = "B"


class Framing(StrEnum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class ScreeningPhase(StrEnum):
    CALIBRATION = "calibration"
    SCREENING = "screening"


class Channel(StrEnum):
    CLI = "cli"
    MCP = "mcp"
    ELICIT = "elicit"

    @property
    def remote(self) -> bool:
        """Whether the act came through an MCP session, as a relay or by elicitation. Decision 37's
        session rules read this: they apply to `elicit` exactly as to `mcp` (ruling 11)."""
        return self is not Channel.CLI


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlank = Annotated[str, AfterValidator(_non_blank)]


def _quote_or_none(value: str) -> str:
    """Empty, for a human decision with no quote, or a real quote; never only whitespace."""
    return value if value == "" else _non_blank(value)


OptionalQuote = Annotated[str, AfterValidator(_quote_or_none)]

PassActorKind = Literal["agent", "human"]
"""Who screens a pass. A pass is all one or all the other (plan teams-C ruling 5)."""

RunStage = Literal[ScreeningStage.TITLE_ABSTRACT, ScreeningStage.FULL_TEXT]
"""The stage of a screening run, decision or event. `either` names a criterion's reach only."""


def anchor_form(value: str | None) -> str | None:
    """Accept a document anchor (`ANCHOR_RE`) or a table cell anchor; the form only."""
    if value is None:
        return None
    if ANCHOR_RE.fullmatch(value) or re.fullmatch(CELL_ANCHOR_RE, value):
        return value
    raise ValueError(f"{value!r} is not a document anchor")


Anchor = Annotated[str | None, AfterValidator(anchor_form)]


def _check_criterion(verdict: str, criterion: str | None) -> None:
    """Every exclusion names an EX criterion (R-30); an inclusion never cites one.

    Accepts bare (`EX03`) and version-qualified (`P@1a2b3c4d:EX03`) criteria alike.
    """
    bare = None if criterion is None else criterion.rsplit(":", 1)[-1]
    if verdict == "exclude" and (bare is None or not bare.startswith("EX")):
        raise ValueError("an exclusion names its EX criterion")
    if verdict == "include" and bare is not None and bare.startswith("EX"):
        raise ValueError("an inclusion cannot cite an exclusion criterion")


def _check_verdict_fields(verdict: Verdict, criterion: str | None, rationale: str) -> None:
    """Raise ValueError when a verdict lacks the fields it requires or cites a wrong criterion."""
    _check_criterion(verdict, criterion)
    if verdict is Verdict.EXCLUDE and not rationale.strip():
        raise ValueError("an exclusion needs a rationale")
    if verdict is Verdict.CANNOT_ASSESS and criterion is None:
        raise ValueError("cannot-assess needs the criterion that could not be assessed")
    if verdict is Verdict.UNSURE and not rationale.strip():
        raise ValueError("unsure needs a rationale")


class _ItemFields(StrictModel):
    work_id: str = Field(min_length=1)
    verdict: Verdict
    criterion: str | None = Field(default=None, pattern=CRITERION_ID_RE)
    rationale: str = ""
    anchor: Anchor = None

    @model_validator(mode="after")
    def _verdict_has_its_fields(self) -> Self:
        _check_verdict_fields(self.verdict, self.criterion, self.rationale)
        return self


class ScreeningItem(_ItemFields):
    """One verdict as an agent returns it, before it becomes a decision event."""

    quote: NonBlank


class HumanScreeningItem(_ItemFields):
    """One verdict as a human returns it. The quote may be left out, except that the service
    requires it for an exclusion in `systematic` (R-110); one that is given is verified."""

    quote: OptionalQuote = ""


class HumanRecordFile(StrictModel):
    """The file `factory screen record` reads: the verdicts of one held batch."""

    task_id: str = Field(min_length=1)
    items: tuple[HumanScreeningItem, ...]


class PassOpened(StrictModel):
    pass_label: PassLabel
    framing: Framing
    criterion_order: Literal["protocol", "reversed"]
    random_seed: int
    sample: tuple[str, ...] | None
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT


class PassJoined(StrictModel):
    """A session joins a pass. `user` names the human of a human join; an agent's user is the
    event's `actor.user`, so an agent's line is byte for byte what it was before human passes."""

    pass_label: PassLabel
    session: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT
    actor_kind: PassActorKind = "agent"
    user: str | None = Field(default=None, pattern=ACTOR_ID_RE)

    @model_serializer(mode="wrap")
    def _omit_agent_defaults(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        if data.get("actor_kind") == "agent":
            del data["actor_kind"]
        for key in ("model", "user"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _fields_follow_kind(self) -> Self:
        if self.actor_kind == "agent" and self.model is None:
            raise ValueError("an agent join names its model")
        if self.actor_kind == "human" and (self.user is None or self.model is not None):
            raise ValueError("a human join names its user and no model")
        return self


class DecisionRecorded(StrictModel):
    decision_id: str = Field(pattern=DECISION_ID_RE)
    work_id: str = Field(min_length=1)
    pass_label: PassLabel
    phase: ScreeningPhase
    stage: RunStage
    verdict: Verdict
    criterion: str | None = Field(pattern=QUALIFIED_CRITERION_RE)
    quote: OptionalQuote
    rationale: str
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    task_id: str = Field(min_length=1)
    supersedes: str | None
    anchor: Anchor = None
    conversion_id: str | None = Field(default=None, pattern=CONVERSION_ID_RE)

    @model_validator(mode="after")
    def _anchor_matches_stage(self) -> Self:
        """A full-text decision cites its anchor in one conversion; a title/abstract one cannot."""
        _check_verdict_fields(self.verdict, self.criterion, self.rationale)
        has_both = self.anchor is not None and self.conversion_id is not None
        has_any = self.anchor is not None or self.conversion_id is not None
        if self.stage is ScreeningStage.FULL_TEXT and not has_both:
            raise ValueError("a full-text decision needs an anchor and a conversion_id")
        if self.stage is not ScreeningStage.FULL_TEXT and has_any:
            raise ValueError("a title-abstract decision has no anchor or conversion_id")
        return self


class CalibrationDrawn(StrictModel):
    protocol_id: str | None = Field(default=None, pattern=PROTOCOL_ID_RE)
    work_ids: tuple[str, ...]
    random_seed: int
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT


class CalibrationLabelled(StrictModel):
    work_id: str = Field(min_length=1)
    verdict: Literal["include", "exclude"]
    criterion: str | None = Field(default=None, pattern=QUALIFIED_CRITERION_RE)
    channel: Channel
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT

    @model_validator(mode="after")
    def _criterion_fits_verdict(self) -> Self:
        _check_criterion(self.verdict, self.criterion)
        return self


class DisagreementResolved(StrictModel):
    work_id: str = Field(min_length=1)
    verdict: Literal["include", "exclude"]
    criterion: str | None = Field(default=None, pattern=QUALIFIED_CRITERION_RE)
    reason: NonBlank
    channel: Channel
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT

    @model_validator(mode="after")
    def _criterion_fits_verdict(self) -> Self:
        _check_criterion(self.verdict, self.criterion)
        return self


class AuditSampled(StrictModel):
    audit_id: str = Field(pattern=AUDIT_ID_RE)
    work_ids: tuple[str, ...]
    random_seed: int
    population: int = Field(ge=0)
    exclusions: int = Field(ge=0)
    inclusions: int = Field(ge=0)
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT
    top_up_of: str | None = Field(default=None, pattern=AUDIT_ID_RE)
    """The audit this sample tops up (living review); absent on every other audit."""


class AuditLabelled(StrictModel):
    audit_id: str = Field(pattern=AUDIT_ID_RE)
    work_id: str = Field(min_length=1)
    verdict: Literal["include", "exclude"]
    criterion: str | None = Field(default=None, pattern=QUALIFIED_CRITERION_RE)
    channel: Channel
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT

    @model_validator(mode="after")
    def _criterion_fits_verdict(self) -> Self:
        _check_criterion(self.verdict, self.criterion)
        return self
