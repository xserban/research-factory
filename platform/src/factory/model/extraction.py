"""Extraction value types and event payloads: rows, fields, claims, closures, resolutions, audits.

Invariants enforced here (validated at the boundary, before any event is written):
- A record is a row of one work in one pass; every field carries its own provenance (value,
  unit, anchor, cell, quote, `reported_in`, `reproduced`). The platform adds `canonical` and
  `copy_marker` (`StoredField`); an agent never supplies them.
- A `cell` has the table-cell form `t<N>.r<N>.c<N>`; an anchor has the document or cell form.
- A claim's statement, anchor and quote are non-blank; the statement is at most
  `CLAIM_STATEMENT_MAX` characters; its vocabularies are closed enums.
- A human resolves a disagreement by choosing `a`, `b` or `neither`; no value is typed.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from factory.model.base import StrictModel
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import CONVERSION_ID_RE, ULID_RE
from factory.model.miners import MINER_NAME_RE as MINER_NAME_RE
from factory.model.protocol import PROTOCOL_ID_RE
from factory.model.references import REX_ID_RE
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
CLAIM_STATEMENT_MAX = 600
"""Upper bound on a claim's statement: it is the agent's paraphrase, not literature text."""


CONTRIBUTION_SCOPE_NAME = "contribution"
"""The pack name (and schema name) of the contribution scope."""


class Scope(StrEnum):
    """Which family of rows an extraction event belongs to. Absent `pack` means evidence."""

    EVIDENCE = "evidence"
    CONTRIBUTION = "contribution"


@dataclass(frozen=True)
class MinerScope:
    """The scope of a registered miner's rows: its name is the scope key the projection stores.

    A value type, not an enum member: compare with `==`, never `is`."""

    name: str

    @property
    def value(self) -> str:
        return self.name


ScopeKey = Scope | MinerScope
"""A scope of extraction rows: a built-in one or a registered miner's."""


def scope_of_pack(pack: str | None) -> ScopeKey:
    """Scope of an event's optional `pack`: events written before G2 have none (evidence); a name
    in the miner namespace is that miner's scope."""
    if pack == CONTRIBUTION_SCOPE_NAME:
        return Scope.CONTRIBUTION
    if pack is not None and re.fullmatch(MINER_NAME_RE, pack):
        return MinerScope(pack)
    return Scope.EVIDENCE


def scope_from_value(value: str) -> ScopeKey:
    """The scope whose projected `scope` column holds `value`."""
    if re.fullmatch(MINER_NAME_RE, value):
        return MinerScope(value)
    return Scope(value)


def pack_tag(scope: ScopeKey) -> str | None:
    """The `pack` an event of `scope` carries: null for evidence, which projects as before G2."""
    return None if scope == Scope.EVIDENCE else scope.value


CARD_SCOPE_NAME = "card"
"""The pack tag of an audit of card assertions (slice 6); no schema or pack has this name."""


class CardScope(StrEnum):
    """The audit scope of card assertions. Not a `Scope`: a card is no extraction row and has no
    passes, so the code that walks every `Scope` must not meet it."""

    CARD = "card"


AuditScope = ScopeKey | CardScope


def audit_scope_of_pack(pack: str | None) -> AuditScope:
    """Scope of an audit event's optional `pack` (`card` is the audit of card assertions)."""
    return CardScope.CARD if pack == CARD_SCOPE_NAME else scope_of_pack(pack)


def scope_of_schema_ref(ref: str) -> ScopeKey:
    """Scope of a `<name>@<version>` schema reference."""
    return scope_of_pack(ref.split("@", 1)[0])


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

Statement = Annotated[NonBlank, Field(max_length=CLAIM_STATEMENT_MAX)]
"""A claim's statement: the agent's bounded paraphrase."""

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
    statement: Statement
    claim_type: ClaimType
    evidence_type: EvidenceType
    strength: Strength
    anchor: RequiredAnchor
    quote: NonBlank


class ExtractionPassOpened(StrictModel):
    pass_label: PassLabel
    random_seed: int
    field_order: Literal["schema", "reversed"]
    pack: str | None = None


class ExtractionPassJoined(StrictModel):
    pass_label: PassLabel
    session: str = Field(min_length=1)
    model: str = Field(min_length=1)
    pack: str | None = None


MarkerCheck = Literal["matched", "mismatch", "absent"]
"""Whether a cited reference entry's marker was found where the contribution quote cites it."""


class CitedEntry(StrictModel):
    """The reference-list entry (plan G1) a contribution item names as its predecessor."""

    reference_extraction_id: str = Field(pattern=REX_ID_RE)
    ordinal: int = Field(ge=1)
    marker: MarkerCheck


class EntryBrief(StrictModel):
    """One entry of a unit's reference list as shown to the agent."""

    ordinal: int
    anchor: str
    label: str | None
    title: str | None
    first_author: str | None
    year: int | None
    doi: str | None
    arxiv: str | None


class UnitReferences(StrictModel):
    """The reference list attached to a contribution unit; `entries` is empty unless current."""

    status: Literal["current", "none", "other-conversion"]
    extraction_id: str | None
    entries: list[EntryBrief]


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
    cited: CitedEntry | None = None


class ClaimRecorded(StrictModel):
    claim_id: str = Field(pattern=CLAIM_ID_RE)
    work_id: str = Field(min_length=1)
    pass_label: PassLabel
    task_id: str = Field(pattern=TASK_ID_RE)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    statement: Statement
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
    pack: str | None = None


class ExtractionResolved(StrictModel):
    """A human's choice between the two passes; `field` None resolves the whole row."""

    work_id: str = Field(min_length=1)
    row_key: str = Field(pattern=ROW_KEY_RE)
    field: FieldName | None
    choice: Literal["a", "b", "neither"]
    reason: NonBlank
    channel: Channel
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    pack: str | None = None


class AuditItemRef(StrictModel):
    """One audited value by location. `extraction_id` is the extraction the value came from when
    it was sampled; None in a sample recorded before it was stored, or in a bare reference."""

    work_id: str = Field(min_length=1)
    row_key: str = Field(pattern=ROW_KEY_RE)
    field: FieldName
    extraction_id: str | None = None


class ExtractionAuditSampled(StrictModel):
    audit_id: str = Field(pattern=EXTRACT_AUDIT_ID_RE)
    items: tuple[AuditItemRef, ...]
    random_seed: int
    population: int = Field(ge=0)
    population_digest: str = Field(min_length=1)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    pack: str | None = None


class ExtractionAuditLabelled(StrictModel):
    audit_id: str = Field(pattern=EXTRACT_AUDIT_ID_RE)
    work_id: str = Field(min_length=1)
    row_key: str = Field(pattern=ROW_KEY_RE)
    field: FieldName
    correct: bool
    note: str = ""
    channel: Channel
    pack: str | None = None
