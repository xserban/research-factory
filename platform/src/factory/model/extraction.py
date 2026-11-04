"""Extraction value types and event payloads: rows, fields, claims, closures, resolutions, audits.

Invariants enforced here (validated at the boundary, before any event is written):
- A record is a row of one work in one pass; every field carries its own provenance (value,
  unit, anchor, cell, quote, `reported_in`, `reproduced`). The platform adds `canonical` and
  `copy_marker` (`StoredField`); an agent never supplies them.
- A `cell` has the table-cell form `t<N>.r<N>.c<N>`; an anchor has the document or cell form.
- A claim's statement, anchor and quote are non-blank; its vocabularies are closed enums.
- A human resolves a disagreement by choosing `a`, `b` or `neither`; no value is typed.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from factory.model.base import StrictModel
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import CONVERSION_ID_RE, ULID_RE
from factory.model.protocol import PROTOCOL_ID_RE
from factory.model.screening import (
    CELL_ANCHOR_RE,
    Anchor,
    Channel,
    NonBlank,
    PassLabel,
    anchor_form,
)
from factory.model.task import TASK_ID_RE

EXTRACTION_ID_RE = rf"^ext_{ULID_RE}$"
CLAIM_ID_RE = rf"^clm_{ULID_RE}$"
EXTRACT_AUDIT_ID_RE = rf"^xau_{ULID_RE}$"
ROW_KEY_RE = r"^rk_[0-9a-f]{12}$"
WHOLE_ROW_MARKER = "*"
VERIFIER_VERSION = 1
"""Version of the verification rules (ruling 6) a row was checked under."""


class ReportedIn(StrEnum):
    OWN = "own"
    CITED = "cited"


class ClaimType(StrEnum):
    FINDING = "finding"
    MECHANISM = "mechanism"
    LIMITATION = "limitation"
    NEGATIVE_RESULT = "negative-result"


class EvidenceType(StrEnum):
    EXPERIMENT = "experiment"
    ABLATION = "ablation"
    THEORY = "theory"
    REPORTED_ELSEWHERE = "reported-elsewhere"
    AUTHOR_ASSERTION = "author-assertion"


class Strength(StrEnum):
    """The agent's own judgement of how strongly the paper supports the claim."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


def _required_anchor(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    anchor_form(value)
    return value


RequiredAnchor = Annotated[str, AfterValidator(_required_anchor)]
"""A non-blank anchor of the document or table-cell form."""


def _field_name(value: str) -> str:
    """A field name is non-blank and never the whole-row marker `*` (the index's WHOLE_ROW)."""
    if not value.strip():
        raise ValueError("a field name must not be blank")
    if value == WHOLE_ROW_MARKER:
        raise ValueError(f"{WHOLE_ROW_MARKER!r} is reserved for a whole-row resolution")
    return value


FieldName = Annotated[str, AfterValidator(_field_name)]
"""A field name of a row, resolution or audit item: non-blank and not `*`."""

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
"""A float that is finite; NaN and infinities are not values a field can hold."""


class FieldInput(StrictModel):
    """One field of a row as the agent returns it."""

    value: str | int | FiniteFloat | bool
    unit: str | None = None
    anchor: Anchor = None
    cell: str | None = Field(default=None, pattern=CELL_ANCHOR_RE)
    quote: str | None = None
    reported_in: ReportedIn = ReportedIn.OWN
    reproduced: bool = False
    cited_work: str | None = None


class StoredField(FieldInput):
    """A verified field as stored: the input plus what the platform computed."""

    canonical: str | None = None
    copy_marker: bool


class ExtractedRowInput(StrictModel):
    fields: dict[FieldName, FieldInput] = Field(min_length=1)


class ClaimInput(StrictModel):
    statement: NonBlank
    claim_type: ClaimType
    evidence_type: EvidenceType
    strength: Strength
    anchor: RequiredAnchor
    quote: NonBlank


class ExtractionPassOpened(StrictModel):
    pass_label: PassLabel
    random_seed: int
    field_order: Literal["schema", "reversed"]


class ExtractionPassJoined(StrictModel):
    pass_label: PassLabel
    session: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ExtractionRecorded(StrictModel):
    extraction_id: str = Field(pattern=EXTRACTION_ID_RE)
    work_id: str = Field(min_length=1)
    pass_label: PassLabel
    task_id: str = Field(pattern=TASK_ID_RE)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    schema_ref: str = Field(min_length=1)
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    row_key: str = Field(pattern=ROW_KEY_RE)
    fields: dict[FieldName, StoredField] = Field(min_length=1)
    supersedes: str | None
    verifier: int = Field(ge=1)


class ClaimRecorded(StrictModel):
    claim_id: str = Field(pattern=CLAIM_ID_RE)
    work_id: str = Field(min_length=1)
    pass_label: PassLabel
    task_id: str = Field(pattern=TASK_ID_RE)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    statement: NonBlank
    claim_type: ClaimType
    evidence_type: EvidenceType
    strength: Strength
    anchor: RequiredAnchor
    quote: NonBlank
    supersedes: str | None


class ExtractionClosed(StrictModel):
    work_id: str = Field(min_length=1)
    pass_label: PassLabel
    task_id: str = Field(pattern=TASK_ID_RE)
    rows: int = Field(ge=0)
    claims: int = Field(ge=0)
    reason: str | None


class ExtractionResolved(StrictModel):
    """A human's choice between the two passes; `field` None resolves the whole row."""

    work_id: str = Field(min_length=1)
    row_key: str = Field(pattern=ROW_KEY_RE)
    field: FieldName | None
    choice: Literal["a", "b", "neither"]
    reason: NonBlank
    channel: Channel
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)


class AuditItemRef(StrictModel):
    work_id: str = Field(min_length=1)
    row_key: str = Field(pattern=ROW_KEY_RE)
    field: FieldName


class ExtractionAuditSampled(StrictModel):
    audit_id: str = Field(pattern=EXTRACT_AUDIT_ID_RE)
    items: tuple[AuditItemRef, ...]
    random_seed: int
    population: int = Field(ge=0)
    population_digest: str = Field(min_length=1)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)


class ExtractionAuditLabelled(StrictModel):
    audit_id: str = Field(pattern=EXTRACT_AUDIT_ID_RE)
    work_id: str = Field(min_length=1)
    row_key: str = Field(pattern=ROW_KEY_RE)
    field: FieldName
    correct: bool
    note: str = ""
    channel: Channel
