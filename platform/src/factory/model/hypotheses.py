"""Leads, hypotheses, critic reviews, registrations and model cut-offs (slice 6, plan H-C).

Invariants enforced here (validated at the boundary, before any event is written):
- A lead has one to twenty triggers and a note of at most 600 characters. A trigger names one
  artefact: an id kind carries a reference of the kind's shape and no row; a builder kind
  (`match`, `conflict`, `gap`) carries the builder's key and the output row it was shown.
- A hypothesis spec states kind, treatment, baseline, one metric, conditions, a prediction with a
  margin, a decision rule from a fixed menu and a test; the combination is consistent
  (`experiment` with `superiority` or `non-inferiority`, `literature` with `literature-direction`;
  `no-worse` if and only if `non-inferiority`). `H@` hashes the decision-relevant fields only
  (`hypothesis_version`); prose never takes part.
- No input model carries a state, a flag, an id or an autonomy label; the platform computes them.
  That only a human registers (under the `human` policy), decides, concludes or abandons is a
  service and projector rule, not a payload rule.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StringConstraints, model_validator

from factory.canonical import canonical_json
from factory.model.base import StrictModel
from factory.model.cards import CARD_ID_RE, ROW_KEY_RE
from factory.model.extraction import CLAIM_ID_RE, EXTRACTION_ID_RE
from factory.model.findings import CONTRADICTION_ID_RE
from factory.model.hypothesis_plan import DECIMAL_RE
from factory.model.identity import ULID_RE
from factory.model.lineage import IDEA_ID_RE
from factory.model.screening import NonBlank
from factory.model.work_ids import WORK_ID_RE
from factory.modules.contract import PolicyKind
from factory.packs import UnitFamily

LEAD_ID_RE = rf"^led_{ULID_RE}$"
HYP_ID_RE = rf"^hyp_{ULID_RE}$"
DIRECTION_ID_RE = rf"^dir_{ULID_RE}$"
INTERPRETATION_REF_RE = rf"^int_{ULID_RE}$"
CONCEPT_REF_RE = rf"^cpt_{ULID_RE}$"
"""Shapes of intuition-layer ids, spelled here: evidence-side modules never import the layer's own
modules (the separation scan); a lead may still cite an interpretation or a concept."""
H_VERSION_RE = r"^H@[0-9a-f]{8}$"
MAX_LEAD_TEXT = 600
MAX_TRIGGERS = 20
MAX_FRAMEWORK = 80
MAX_STATEMENT = 600
MAX_CONCLUSION = 1200
MAX_NOTE = 300
MAX_METHOD_NAME = 120
PRIOR_CAP = 50

LeadId = Annotated[str, StringConstraints(pattern=LEAD_ID_RE)]
HypothesisId = Annotated[str, StringConstraints(pattern=HYP_ID_RE)]
HVersion = Annotated[str, StringConstraints(pattern=H_VERSION_RE)]


# --- Leads -------------------------------------------------------------------------------


class TriggerKind(StrEnum):
    WORK = "work"
    ROW = "row"
    CLAIM = "claim"
    ITEM = "item"
    IDEA = "idea"
    INTERPRETATION = "interpretation"
    CONCEPT = "concept"
    CARD = "card"
    MATCH = "match"
    CONFLICT = "conflict"
    GAP = "gap"
    CONTRADICTION = "contradiction"
    LEAD = "lead"
    HYPOTHESIS = "hypothesis"
    DIRECTION = "direction"


BUILDER_KINDS = frozenset({TriggerKind.MATCH, TriggerKind.CONFLICT, TriggerKind.GAP})
"""Triggers that cite a builder output: they store the builder's key and the row shown."""

_REF_PATTERNS: dict[TriggerKind, str] = {
    TriggerKind.WORK: WORK_ID_RE,
    TriggerKind.ROW: ROW_KEY_RE,
    TriggerKind.CLAIM: CLAIM_ID_RE,
    TriggerKind.ITEM: EXTRACTION_ID_RE,
    TriggerKind.IDEA: IDEA_ID_RE,
    TriggerKind.INTERPRETATION: INTERPRETATION_REF_RE,
    TriggerKind.CONCEPT: CONCEPT_REF_RE,
    TriggerKind.CARD: CARD_ID_RE,
    TriggerKind.MATCH: r"^[0-9a-f]{16}$",
    TriggerKind.CONFLICT: r"^grp_[0-9a-f]{12}$",
    TriggerKind.GAP: r"^[0-9a-f]{16}$",
    TriggerKind.CONTRADICTION: CONTRADICTION_ID_RE,
    TriggerKind.LEAD: LEAD_ID_RE,
    TriggerKind.HYPOTHESIS: HYP_ID_RE,
    TriggerKind.DIRECTION: DIRECTION_ID_RE,
}


class DiscardReason(StrEnum):
    DUPLICATE = "duplicate"
    PRIOR_FAILURE = "prior-failure"
    OUT_OF_SCOPE = "out-of-scope"
    INFEASIBLE = "infeasible"
    NOT_FALSIFIABLE = "not-falsifiable"
    OTHER = "other"


class Trigger(StrictModel):
    kind: TriggerKind
    ref: str = Field(min_length=1, max_length=200)
    row: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if re.fullmatch(_REF_PATTERNS[self.kind], self.ref) is None:
            raise ValueError(f"not a {self.kind.value} reference")
        builder = self.kind in BUILDER_KINDS
        if builder and self.row is None:
            raise ValueError(f"a {self.kind.value} trigger carries the row it was shown")
        if not builder and self.row is not None:
            raise ValueError(f"a {self.kind.value} trigger carries no row")
        return self


class LeadInput(StrictModel):
    """What an agent or a human states: the note, its triggers and the framework used."""

    text: Annotated[NonBlank, Field(max_length=MAX_LEAD_TEXT)]
    triggers: tuple[Trigger, ...] = Field(min_length=1, max_length=MAX_TRIGGERS)
    framework: Annotated[NonBlank, Field(max_length=MAX_FRAMEWORK)] | None = None


class LeadRecorded(StrictModel):
    lead_id: LeadId
    text: str
    triggers: tuple[Trigger, ...]
    framework: str | None = None
    prior: tuple[str, ...] = ()
    prior_total: int = Field(default=0, ge=0)
    keys: tuple[str, ...] = ()


LeadDecision = Literal["promote", "park", "discard"]


class LeadDecided(StrictModel):
    lead_id: LeadId
    decision: LeadDecision
    reason: DiscardReason | None = None
    note: Annotated[NonBlank, Field(max_length=MAX_NOTE)] | None = None
    policy: PolicyKind

    @model_validator(mode="after")
    def _discard_has_reason(self) -> Self:
        if (self.decision == "discard") != (self.reason is not None):
            raise ValueError("a discard, and only a discard, has a reason")
        if self.reason is DiscardReason.OTHER and self.note is None:
            raise ValueError("a reason `other` needs a note")
        return self

