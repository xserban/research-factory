"""Property vocabulary, method cards, problem descriptions and their assertions (slice 6, H-A).

Invariants enforced here (validated at the boundary, before any event is written):
- A `PropertyDef` is typed: `enum` and `set` list their allowed values, `number` names a unit
  family, and the match rule fits the kind (`covers` only for sets, `at-most` and `at-least` only
  for numbers). Prose (`description`) never takes part in `V@`.
- A card id carries the prefix of its kind (`mcd_` method, `pbd_` problem).
- An assertion carries exactly one basis, of the shape its `basis_kind` names. The status is
  computed by the platform (`CardAsserted.status`); no input model can set one, and
  `StrictModel` refuses unknown fields.
- Decisions carry a non-blank rationale. That only a human decides is a service and projector
  rule, not a payload rule.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.extraction import RequiredAnchor
from factory.model.identity import CONVERSION_ID_RE, ULID_RE
from factory.model.screening import NonBlank
from factory.model.work_ids import WORK_ID_RE
from factory.packs import UnitFamily

PROPERTY_KEY_RE = r"^pr:[a-z0-9][a-z0-9-]{1,47}$"
VALUE_RE = r"^[a-z0-9][a-z0-9.-]{0,47}$"
CARD_ID_RE = rf"^(mcd|pbd)_{ULID_RE}$"
ASSERTION_ID_RE = rf"^pas_{ULID_RE}$"
VOCAB_VERSION_RE = r"^V@[0-9a-f]{8}$"
ROW_KEY_RE = r"^rk_[0-9a-f]{12}$"
MAX_ALIAS = 80
MAX_SUBJECT = 120
MAX_NOTE = 500
MAX_RATIONALE = 2000

PropertyKey = Annotated[str, StringConstraints(pattern=PROPERTY_KEY_RE)]
ValueToken = Annotated[str, StringConstraints(pattern=VALUE_RE)]
Alias = Annotated[str, StringConstraints(min_length=1, max_length=MAX_ALIAS)]
CardId = Annotated[str, StringConstraints(pattern=CARD_ID_RE)]
AssertionId = Annotated[str, StringConstraints(pattern=ASSERTION_ID_RE)]
VocabVersion = Annotated[str, StringConstraints(pattern=VOCAB_VERSION_RE)]
Reason = Annotated[NonBlank, Field(max_length=MAX_RATIONALE)]


class PropertyKind(StrEnum):
    ENUM = "enum"
    SET = "set"
    BOOL = "bool"
    NUMBER = "number"


class MatchRule(StrEnum):
    EQUAL = "equal"
    COVERS = "covers"
    AT_MOST = "at-most"
    AT_LEAST = "at-least"


AppliesTo = Literal["method", "problem", "both"]
CardKind = Literal["method", "problem"]
AssertionStatus = Literal["stated", "inferred", "imported-unverified"]
PropertyDecision = Literal["approve", "reject"]
AssertionDecision = Literal["confirm", "reject"]


class BasisKind(StrEnum):
    QUOTE = "quote"
    ROW = "row"
    RESEARCHER = "researcher"
    INFERRED = "inferred"
    IMPORTED = "imported"


class PropertyDef(StrictModel):
    """A typed property of the project vocabulary."""

    key: PropertyKey
    kind: PropertyKind
    allowed: tuple[ValueToken, ...] = ()
    unit_family: UnitFamily | None = None
    match: MatchRule
    applies_to: AppliesTo
    aliases: tuple[Alias, ...] = ()
    value_aliases: dict[ValueToken, tuple[Alias, ...]] = Field(default_factory=dict)
    scope: str = "project"
    description: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _kind_rules(self) -> Self:
        listed = self.kind in (PropertyKind.ENUM, PropertyKind.SET)
        if listed and not self.allowed:
            raise ValueError("an enum or set property lists its allowed values")
        if not listed and self.allowed:
            raise ValueError("only an enum or set property has allowed values")
        if len(set(self.allowed)) != len(self.allowed):
            raise ValueError("allowed values must be unique")
        if (self.kind is PropertyKind.NUMBER) != (self.unit_family is not None):
            raise ValueError("a number property, and only it, names a unit family")
        if self.match is MatchRule.COVERS and self.kind is not PropertyKind.SET:
            raise ValueError("`covers` applies to a set property only")
        if self.match in (MatchRule.AT_MOST, MatchRule.AT_LEAST) and (
            self.kind is not PropertyKind.NUMBER
        ):
            raise ValueError("`at-most` and `at-least` apply to a number property only")
        if set(self.value_aliases) - set(self.allowed):
            raise ValueError("value aliases name allowed values only")
        return self


class QuoteBasis(StrictModel):
    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)]
    conversion_id: Annotated[str, StringConstraints(pattern=CONVERSION_ID_RE)]
    anchor: RequiredAnchor
    quote: NonBlank


class RowBasis(StrictModel):
    row_key: Annotated[str, StringConstraints(pattern=ROW_KEY_RE)]
    field: NonBlank


class InferredBasis(StrictModel):
    note: Annotated[NonBlank, Field(max_length=MAX_NOTE)]
    supports: tuple[QuoteBasis, ...] = ()


Basis = QuoteBasis | RowBasis | InferredBasis
_BASIS_TYPE: dict[BasisKind, type[StrictModel]] = {
    BasisKind.QUOTE: QuoteBasis,
    BasisKind.ROW: RowBasis,
    BasisKind.INFERRED: InferredBasis,
}
_STATUS_OF: dict[BasisKind, str] = {
    BasisKind.QUOTE: "stated",
    BasisKind.ROW: "stated",
    BasisKind.RESEARCHER: "stated",
    BasisKind.INFERRED: "inferred",
}


class PropertyProposed(StrictModel):
    definition: PropertyDef
    supersedes: PropertyKey | None = None

    @model_validator(mode="after")
    def _supersedes_names_own_key(self) -> Self:
        if self.supersedes is not None and self.supersedes != self.definition.key:
            raise ValueError("a superseding definition keeps its key")
        return self


class PropertyDecided(StrictModel):
    key: PropertyKey
    decision: PropertyDecision
    rationale: Reason


class PropertyMerged(StrictModel):
    from_key: PropertyKey
    into: PropertyKey
    reason: Reason

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if self.from_key == self.into:
            raise ValueError("a merge names two distinct properties")
        return self


class PropertyUnmerged(StrictModel):
    from_key: PropertyKey
    into: PropertyKey
    reason: Reason


class CardCreated(StrictModel):
    card_id: CardId
    kind: CardKind
    subject: Annotated[NonBlank, Field(max_length=MAX_SUBJECT)]
    owner: Annotated[NonBlank, Field(max_length=MAX_SUBJECT)]

    @model_validator(mode="after")
    def _prefix_matches_kind(self) -> Self:
        if self.card_id[:3] != ("mcd" if self.kind == "method" else "pbd"):
            raise ValueError("the card id prefix must match the card kind")
        return self


class CardAsserted(StrictModel):
    assertion_id: AssertionId
    card_id: CardId
    property: PropertyKey
    value: str | tuple[str, ...] | bool
    unit: str | None = None
    canonical: str | None = None
    basis_kind: BasisKind
    basis: Basis | None = None
    status: AssertionStatus
    vocabulary_version: VocabVersion
    supersedes: AssertionId | None = None
    imported_from: str | None = None

    @model_validator(mode="after")
    def _basis_follows_kind(self) -> Self:
        expected = _BASIS_TYPE.get(self.basis_kind)
        if expected is not None and not isinstance(self.basis, expected):
            raise ValueError(f"a {self.basis_kind.value} assertion carries a {expected.__name__}")
        if self.basis_kind is BasisKind.RESEARCHER and self.basis is not None:
            raise ValueError("a researcher assertion carries no basis")
        if self.basis_kind is BasisKind.IMPORTED:
            if self.imported_from is None:
                raise ValueError("an imported assertion names its source")
            if self.status == "inferred":
                raise ValueError("an imported assertion is stated or imported-unverified")
        elif self.imported_from is not None:
            raise ValueError("only an imported assertion names a source")
        want = _STATUS_OF.get(self.basis_kind)
        if want is not None and self.status != want:
            raise ValueError(f"a {self.basis_kind.value} assertion is {want}")
        return self


class AssertionDecided(StrictModel):
    assertion_id: AssertionId
    decision: AssertionDecision
    rationale: Reason


class CardImported(StrictModel):
    """Written by the Later cross-project import; defined now so the catalog is complete."""

    card_id: CardId
    source_project: NonBlank
    source_card_id: CardId
    source_event_ids: tuple[str, ...]
