"""The protocol: criteria, sources, search strategy, limits and screening plan, with version hashes.

A protocol version `P@<sha256[:8]>` hashes the canonical JSON of the spec with prose removed
(`PROSE_KEYS`), and with each list sorted by its identity key. A prose-only change keeps the
version; a change to a rule, a source, a query, a limit or the screening plan does not. The
search-strategy hash `S@<sha256[:8]>` covers sources, queries and limits only.

This module is pure: it holds the value types and the hashing. Readiness rules live in
`factory.services.protocol_rules`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, JsonValue, StringConstraints, model_validator

from factory.canonical import canonical_json
from factory.model.base import StrictModel
from factory.model.question import QUESTION_ID_RE
from factory.model.search import QueryKind, QuerySpec

CRITERION_ID_RE = r"^(IN|EX)\d{2}$"
PARENT_RE = r"^(slot:.+|NG\d{2})$"
PROTOCOL_ID_RE = r"^P@[0-9a-f]{8}$"

PROSE_KEYS = frozenset(
    {
        "note",
        "rationale",
        "why",
        "reason",
        "comment",
        "examples",
        "duties",
        "scheme_rationale",
        "objectives",
    }
)
"""Fields that explain a protocol without changing what it decides. Never hashed."""

_SORT_KEYS: dict[str, tuple[str, ...]] = {
    "criteria": ("id",),
    "sources": ("name",),
    "queries": ("source", "kind", "text"),
    "limits": ("field", "value"),
}
_SEARCH_STRATEGY_KEYS = ("sources", "queries", "limits")


class MethodProfile(StrEnum):
    SYSTEMATIC_REVIEW = "systematic-review"
    SCOPING_REVIEW = "scoping-review"
    SE_SYSTEMATIC_REVIEW = "se-systematic-review"
    MAPPING_STUDY = "mapping-study"
    RAPID_REVIEW = "rapid-review"
    LIVING_REVIEW = "living-review"


class ScreeningStage(StrEnum):
    TITLE_ABSTRACT = "title-abstract"
    FULL_TEXT = "full-text"
    EITHER = "either"


class CriterionKind(StrEnum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class CriterionExamples(StrictModel):
    """Seed ids used as worked examples of the rule. Held-out seeds are never accepted here."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


class Criterion(StrictModel):
    """One inclusion or exclusion rule. The kind is the prefix of the id: `IN` or `EX`."""

    id: str = Field(pattern=CRITERION_ID_RE)
    parent: str | None = Field(default=None, pattern=PARENT_RE)
    statement: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    applies_at: ScreeningStage
    priority: int | None = Field(default=None, ge=0)
    examples: CriterionExamples = CriterionExamples()
    note: str = ""

    @property
    def kind(self) -> CriterionKind:
        return CriterionKind.INCLUSION if self.id.startswith("IN") else CriterionKind.EXCLUSION

    @model_validator(mode="after")
    def _priority_matches_kind(self) -> Self:
        if self.kind is CriterionKind.EXCLUSION and self.priority is None:
            raise ValueError("an exclusion needs a priority")
        if self.kind is CriterionKind.INCLUSION and self.priority is not None:
            raise ValueError("an inclusion has no priority")
        return self


class SourcePlan(StrictModel):
    """A source the protocol names, whether it is searched, and the probe that measured it."""

    name: str = Field(min_length=1)
    included: bool
    probe_id: str | None = None
    why: str = ""


class PlannedQuery(StrictModel):
    """A query the protocol plans on one source. Matching ignores surrounding whitespace."""

    source: str = Field(min_length=1)
    kind: QueryKind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    filters: dict[str, str] = Field(default_factory=dict)

    def matches(self, spec: QuerySpec) -> bool:
        """True when a query request is this planned query: same source, kind, text and filters."""
        return (
            self.source == spec.source
            and self.kind is spec.kind
            and self.text == spec.text.strip()
            and self.filters == spec.filters
        )


class Limit(StrictModel):
    """A bound on the search, such as a date range or a language, with the reason it is set."""

    field: str = Field(min_length=1)
    value: str = Field(min_length=1)
    why: str = ""


class ReviewerRole(StrEnum):
    REVIEWER_OF_RECORD = "reviewer-of-record"
    ASSISTING = "assisting"


class Reviewer(StrictModel):
    role: ReviewerRole
    actor: str = Field(min_length=1)
    kind: Literal["human", "agent"]
    duties: str = ""


class ScreeningPlan(StrictModel):
    """How screening is run: passes, dual-coding sample, agreement floor and reviewers."""

    passes: Literal[1, 2]
    dual_sample: float | None = Field(default=None, gt=0, le=1)
    kappa_floor: float | None = Field(default=None, ge=0, le=1)
    kappa_enforced: bool = False
    calibration_size: int = Field(default=30, ge=0)
    audit_fraction: float = Field(default=0.02, ge=0, le=1)
    audit_minimum: int = Field(default=50, ge=0)
    reviewers: tuple[Reviewer, ...]


class ProtocolSpec(StrictModel):
    """The protocol as an agent or a human states it. Keys are unique within each list."""

    question_id: str = Field(pattern=QUESTION_ID_RE)
    method_profile: MethodProfile
    criteria: tuple[Criterion, ...]
    sources: tuple[SourcePlan, ...]
    queries: tuple[PlannedQuery, ...]
    limits: tuple[Limit, ...] = ()
    screening: ScreeningPlan
    rationale: str = ""


def strip_prose(value: JsonValue) -> JsonValue:
    """Drop prose fields (`PROSE_KEYS`) recursively, so the hash tracks meaning, not wording."""
    if isinstance(value, dict):
        return {key: strip_prose(item) for key, item in value.items() if key not in PROSE_KEYS}
    if isinstance(value, list):
        return [strip_prose(item) for item in value]
    return value


def _digest(dump: dict[str, Any], keys: Iterable[str]) -> str:
    """First 8 hex digits of the hash over the given sections, prose stripped, lists sorted."""
    payload: dict[str, JsonValue] = {}
    for key in keys:
        if key in PROSE_KEYS:
            continue
        items: Any = dump[key]
        if key in _SORT_KEYS:
            sort_keys = _SORT_KEYS[key]
            items = sorted(items, key=lambda item: tuple(str(item[k]) for k in sort_keys))
            payload[key] = [strip_prose(item) for item in items]
        else:
            payload[key] = strip_prose(items)
    return hashlib.sha256(canonical_json(payload)).hexdigest()[:8]


def protocol_version(spec: ProtocolSpec) -> str:
    """`P@` plus the digest over every section of the spec (prose excluded)."""
    dump = spec.model_dump(mode="json")
    return "P@" + _digest(dump, dump.keys())


def search_strategy_hash(spec: ProtocolSpec) -> str:
    """`S@` plus the digest over sources, queries and limits only. Criteria do not affect it."""
    return "S@" + _digest(spec.model_dump(mode="json"), _SEARCH_STRATEGY_KEYS)


def criterion_ref(protocol_id: str, cid: str) -> str:
    """The reference to one criterion under one protocol version, e.g. `P@1a2b3c4d:IN01`."""
    return f"{protocol_id}:{cid}"
