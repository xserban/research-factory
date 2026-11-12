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

from pydantic import (
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

from factory.canonical import canonical_json
from factory.imports.model import ImportFormat, ImportRole
from factory.model.appraisal import AppraisalInstrument
from factory.model.base import StrictModel
from factory.model.gates import GatePolicies
from factory.model.grey import GreySource, grey_source_issues
from factory.model.hypothesis_plan import HypothesisPlan
from factory.model.identity import REVIEW_REQUEST_ID_RE, ULID_RE, DecisionId
from factory.model.miners import MinerUse
from factory.model.question import QUESTION_ID_RE
from factory.model.search import QueryKind, QuerySpec
from factory.model.watch import WatchPlan

CRITERION_ID_RE = r"^(IN|EX)\d{2}$"
PARENT_RE = r"^(slot:.+|NG\d{2}|SQ\d{1,2})$"
PROTOCOL_ID_RE = r"^P@[0-9a-f]{8}$"
REVIEW_ID_RE = rf"^prs_{ULID_RE}$"
DEVIATION_ID_RE = rf"^dev_{ULID_RE}$"
AMENDMENT_ID_RE = rf"^amd_{ULID_RE}$"

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
    "library_sources": ("name", "format", "role"),
    "miners": ("name", "version"),
    "taxonomies": ("name", "version"),
    "grey_sources": ("method", "target", "stopping_rule"),
}
_SEARCH_STRATEGY_KEYS = ("sources", "queries", "limits")
_OMITTED_WHEN_NONE = frozenset(
    {
        "full_text_screening",
        "extraction_schema",
        "snowball_plan",
        "contribution_schema",
        "supplied_links",
        "watch_plan",
        "library_sources",
        "gate_policies",
        "miners",
        "taxonomies",
        "hypothesis_plan",
        "grey_sources",
        "appraisal_instrument",
    }
)
"""Optional sections left out of every hash while unset, so protocols that predate them keep
their versions. Other `None` values stay in the hash."""


class TaxonomyUse(StrictModel):
    """A protocol's listing of one registered taxonomy version. Defined here, not in
    `model.taxonomies`, which imports modules that import this one; the name pattern is that
    module's `TAXONOMY_NAME_RE`."""

    name: str = Field(pattern=r"^t-[a-z0-9][a-z0-9-]*$")
    version: int = Field(ge=1)


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
    EITHER = "either"  # A criterion's `applies_at` only, never the stage of a run or an event.


class CriterionKind(StrEnum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class ExampleCase(StrictModel):
    """A corpus record that settled how a criterion reads, found by a tuning batch (H2).

    `text` is what the screener sees (the title and a one-line reason, no work id); `work_id`
    and `source` (the tuning draw) only make the example traceable, and exclude the record from
    every measurement of agreement."""

    work_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: str | None = None


class CriterionExamples(StrictModel):
    """Seed ids used as worked examples of the rule. Held-out seeds are never accepted here.

    `include_cases` and `exclude_cases` are examples taken from tuning batches; left out of every
    dump while empty."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    include_cases: tuple[ExampleCase, ...] = ()
    exclude_cases: tuple[ExampleCase, ...] = ()

    @model_serializer(mode="wrap")
    def _omit_empty_cases(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        for key in ("include_cases", "exclude_cases"):
            if not data.get(key):
                data.pop(key, None)
        return data


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
    calibrate_humans: bool = False
    """Whether a human pass passes the same calibration gate as an agent pass (slice 5, "Human
    screening passes"). Left out of every dump, so of every hash, while false."""
    stop_after_consecutive_excludes: int | None = Field(default=None, ge=1)
    """Title/abstract only, and only once a ranking exists (slice 8, IDEA-42): serving stops when
    the records of the ranking, taken in ranked order, end in this many consecutive exclusions by
    pass A. None screens everything. Left out of every dump, so of every hash, while None."""
    stop_below_score: int | None = Field(default=None, ge=1, le=10)
    """Title/abstract only, with a ranking: serving stops when the last `stop_score_run` scored
    pass-A decisions, in ranked order, are all below this score (an unscored decision breaks the
    run). Set together with `stop_score_run`; left out of every dump while None."""
    stop_score_run: int | None = Field(default=None, ge=1)
    """The run length of the score-based stop; see `stop_below_score`."""

    @model_serializer(mode="wrap")
    def _omit_unset_options(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        if not data.get("calibrate_humans"):
            data.pop("calibrate_humans", None)
        if data.get("stop_after_consecutive_excludes") is None:
            data.pop("stop_after_consecutive_excludes", None)
        for key in ("stop_below_score", "stop_score_run"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _score_stop_is_whole(self) -> Self:
        if (self.stop_below_score is None) != (self.stop_score_run is None):
            raise ValueError("stop_below_score and stop_score_run are set together or not at all")
        return self


class ExtractionSchema(StrictModel):
    """What is extracted: a versioned domain pack, the declared subset of its fields, the keys
    that make rows comparable (a subset of `fields`) and the dual-extraction and audit settings.

    `dual_extract_sample` is the fraction of works extracted twice (None = every work)."""

    pack: str = Field(min_length=1)
    pack_version: int = Field(ge=1)
    fields: tuple[str, ...] = Field(min_length=1)
    comparability_keys: tuple[str, ...] = ()
    dual_extract_sample: float | None = Field(default=None, gt=0, le=1)
    audit_fraction: float = Field(default=0.02, ge=0, le=1)
    audit_minimum: int = Field(default=50, ge=0)
    claims: bool = True

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("fields must be unique")
        if len(set(self.comparability_keys)) != len(self.comparability_keys):
            raise ValueError("comparability_keys must be unique")
        return self


class SnowballPlan(StrictModel):
    """The snowballing stopping rule (slice 3a, ruling 19): the most rounds per direction, and
    whether a direction stops once its previous round yielded no newly included work."""

    max_backward_rounds: int = Field(ge=0)
    max_forward_rounds: int = Field(ge=0)
    stop_when_no_new_included: bool = True
    forward_core_only: bool = False
    """A forward round starts only from the core works that are included or seeds (slice 8)."""
    forward_topic_filter: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=1, max_length=1000, pattern=r"^[^,\x00-\x1f]+$"
            ),
        ]
        | None
    ) = None
    """An OpenAlex `title_and_abstract.search` expression every forward query also carries
    (comma-AND). It holds no comma, which would open another filter clause."""
    forward_max_per_work: int | None = Field(default=None, ge=1)
    """At most this many citing works are taken per source work of a forward round, ordered by
    similarity to the development seeds (decision 116); the rest are counted, not dropped."""

    @model_serializer(mode="wrap")
    def _omit_forward_defaults(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """A plan that leaves the forward options at their defaults serialises, and so hashes,
        exactly as it did before they existed."""
        data: dict[str, Any] = handler(self)
        if not self.forward_core_only:
            data.pop("forward_core_only", None)
        if self.forward_topic_filter is None:
            data.pop("forward_topic_filter", None)
        if self.forward_max_per_work is None:
            data.pop("forward_max_per_work", None)
        return data


SubmitterKind = Literal["human", "agent"]


class SuppliedLinksPlan(StrictModel):
    """Who may supply links whose lookups run without a deviation (slice 4a, ruling 7).

    `accept_from` is non-empty, has no duplicates and is kept sorted, so the order in which the
    kinds are stated never changes the protocol's hash. A `supplied` lookup of an item captured by
    a listed kind is planned; any other needs a recorded deviation in `pilot` and `systematic`.
    """

    accept_from: tuple[SubmitterKind, ...] = Field(min_length=1)

    @field_validator("accept_from")
    @classmethod
    def _unique(cls, value: tuple[SubmitterKind, ...]) -> tuple[SubmitterKind, ...]:
        if len(set(value)) != len(value):
            raise ValueError("accept_from must not repeat a kind")
        return tuple(sorted(value))


class LibrarySource(StrictModel):
    """A library the protocol declares (slice 3d, ruling 20): the collection `name` (`default`
    when the export names none), the export `format` and its `role`. An import is admitted as
    corpus only when an entry with its collection and format has role `corpus`."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    format: ImportFormat
    role: ImportRole


class ProtocolSpec(StrictModel):
    """The protocol as an agent or a human states it. Keys are unique within each list."""

    question_id: str = Field(pattern=QUESTION_ID_RE)
    method_profile: MethodProfile
    criteria: tuple[Criterion, ...]
    sources: tuple[SourcePlan, ...]
    queries: tuple[PlannedQuery, ...]
    limits: tuple[Limit, ...] = ()
    screening: ScreeningPlan
    full_text_screening: ScreeningPlan | None = None
    """The full-text plan. Absent (None) until the protocol declares full-text screening."""
    extraction_schema: ExtractionSchema | None = None
    """What is extracted. Absent (None) until the protocol declares it; left out of the hash."""
    snowball_plan: SnowballPlan | None = None
    """The snowballing stopping rule. Absent (None) until declared; left out of the hash."""
    contribution_schema: ExtractionSchema | None = None
    """What is extracted for the lineage graph (slice 3b, ruling 5): pack `contribution`, no
    comparability keys, no claims. Absent (None) until declared; left out of the hash."""
    supplied_links: SuppliedLinksPlan | None = None
    """Who may supply links (slice 4a). Absent (None) until declared; left out of the hash."""
    watch_plan: WatchPlan | None = None
    """The living-corpus watch (slice 4b). Absent (None) until declared; left out of the hash
    while unset, and never part of `S@`."""
    library_sources: tuple[LibrarySource, ...] | None = None
    """The libraries imported as corpus or reference (slice 3d). Absent (None) until declared;
    left out of the hash while unset, so protocols that predate it keep their versions."""
    gate_policies: GatePolicies | None = None
    """Who may pass each decision gate (slice M). Absent (None) until declared, so the preset of
    the project's rigor mode applies; left out of the hash while unset."""
    miners: tuple[MinerUse, ...] | None = None
    """The registered miners this protocol runs (slice M, M-C). Absent (None) until declared;
    left out of the hash while unset, and sorted by name and version in it."""
    taxonomies: tuple[TaxonomyUse, ...] | None = None
    """The registered taxonomy versions this protocol uses (IDEA-50), listed like miners: every
    derived miner's taxonomy must appear. Absent (None) until declared; left out of the hash
    while unset, and sorted by name and version in it."""
    hypothesis_plan: HypothesisPlan | None = None
    """Hypothesis defaults (slice 6): minimum seeds, confidence, test-access limit, conflict
    tolerance. Absent (None) until declared; left out of the hash while unset."""
    grey_sources: tuple[GreySource, ...] | None = None
    """The declared grey literature sources (plan SG, PD-7). Absent (None) until declared; left
    out of the hash while unset, so protocols that predate it keep their versions."""
    appraisal_instrument: AppraisalInstrument | None = None
    """The per-paper appraisal instrument (IDEA-21, R-41). Absent (None) until declared; left out
    of the hash while unset, so protocols that predate it keep their versions."""
    rationale: str = ""

    @model_validator(mode="after")
    def _grey_sources_valid(self) -> Self:
        if self.grey_sources is not None:
            issues = grey_source_issues(self.grey_sources)
            if issues:
                raise ValueError("; ".join(reason for _, reason in issues))
        return self

    @model_validator(mode="after")
    def _library_sources_unique(self) -> Self:
        if self.library_sources is not None:
            keys = [(s.name, s.format) for s in self.library_sources]
            if len(set(keys)) != len(keys):
                raise ValueError("library_sources must not repeat a (name, format)")
        return self


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
        if key in _OMITTED_WHEN_NONE and items is None:
            continue
        if key == "gate_policies":
            entries = sorted(items["entries"], key=lambda item: str(item["gate"]))
            payload[key] = {"entries": [strip_prose(item) for item in entries]}
        elif key in _SORT_KEYS:
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


AMENDABLE_FIELDS = (
    "question_id",
    "method_profile",
    "sources",
    "queries",
    "limits",
    "screening",
    "full_text_screening",
    "extraction_schema",
    "snowball_plan",
    "contribution_schema",
    "supplied_links",
    "watch_plan",
    "library_sources",
    "gate_policies",
    "miners",
    "taxonomies",
    "hypothesis_plan",
    "grey_sources",
    "appraisal_instrument",
)
"""Top-level hashed fields other than criteria, which an amendment reports as `other_changes`."""


def section_digest(spec: ProtocolSpec, key: str) -> str:
    """The digest of one hashed top-level field, prose stripped and lists sorted."""
    return _digest(spec.model_dump(mode="json"), (key,))


def search_strategy_hash(spec: ProtocolSpec) -> str:
    """`S@` plus the digest over sources, queries and limits only. Criteria do not affect it."""
    return "S@" + _digest(spec.model_dump(mode="json"), _SEARCH_STRATEGY_KEYS)


def criterion_ref(protocol_id: str, cid: str) -> str:
    """The reference to one criterion under one protocol version, e.g. `P@1a2b3c4d:IN01`."""
    return f"{protocol_id}:{cid}"


# --- Event payloads (schema 1). Written by `factory.services.protocol`, folded by
# `factory.index.protocol`. `protocol_id` must be the version hash of `spec`.


class ReviewLinked(StrictModel):
    """A protocol change that may consume an approved review request. The id is left out of the
    payload when absent, so an event without a request reads and hashes as it always has."""

    review_request_id: str | None = Field(default=None, pattern=REVIEW_REQUEST_ID_RE)

    @model_serializer(mode="wrap")
    def _omit_absent_review(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        if self.review_request_id is None:
            del data["review_request_id"]
        return data


class ProtocolStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"


class ProtocolRecorded(ReviewLinked):
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    status: ProtocolStatus
    spec: ProtocolSpec
    decision_ids: tuple[DecisionId, ...] | None = None

    @model_validator(mode="after")
    def _id_matches_spec(self) -> Self:
        if self.protocol_id != protocol_version(self.spec):
            raise ValueError("protocol_id must be the version hash of spec")
        return self


class PressElement(StrEnum):
    """The six elements of the PRESS 2015 peer review of electronic search strategies."""

    TRANSLATION = "translation"
    BOOLEAN_PROXIMITY = "boolean-proximity"
    SUBJECT_HEADINGS = "subject-headings"
    TEXT_WORDS = "text-words"
    SPELLING_SYNTAX_LINE_NUMBERS = "spelling-syntax-line-numbers"
    LIMITS_FILTERS = "limits-filters"


class PressFinding(StrictModel):
    element: PressElement
    finding: str = Field(min_length=1)
    severity: Literal["minor", "major"]


class PressReviewed(StrictModel):
    review_id: str = Field(pattern=REVIEW_ID_RE)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    findings: tuple[PressFinding, ...]


class PressConfirmed(StrictModel):
    """A human's response to each finding of a review, in the order of the findings."""

    review_id: str = Field(pattern=REVIEW_ID_RE)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    responses: tuple[str, ...]


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class CriterionEffect(StrEnum):
    """What a changed criterion does to decisions made under it. `clarified` changes nothing."""

    LOOSENED = "loosened"
    TIGHTENED = "tightened"
    CLARIFIED = "clarified"


class CriterionChange(StrictModel):
    cid: str = Field(pattern=CRITERION_ID_RE)
    change: ChangeKind
    effect: CriterionEffect | None = None


class StaleRule(StrictModel):
    """Decisions a change makes doubtful: those citing `criterion` (`exclusions-citing`), all
    inclusions (`inclusions`) or all decisions not yet tested against it (`untested`)."""

    criterion: str = Field(pattern=CRITERION_ID_RE)
    stales: Literal["exclusions-citing", "inclusions", "untested"]
    stage: ScreeningStage


class DeviationRecorded(ReviewLinked):
    deviation_id: str = Field(pattern=DEVIATION_ID_RE)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    description: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    affects: tuple[str, ...] = ()


class ExtractionStale(StrictModel):
    """Extraction rows an amendment makes stale: all of them, or those carrying `fields`.

    The rule applies within one scope: `ProtocolAmended.extraction_stale` to evidence rows,
    `ProtocolAmended.contribution_stale` to contribution rows."""

    all_records: bool
    fields: tuple[str, ...] = ()
    values: dict[str, tuple[str, ...]] | None = None
    """Value-level staleness: field name -> values whose rows are stale. A row is stale when it
    carries one of these values; `all_records` is False when used. Omitted from serialisation
    when None, so events written before it existed replay identically."""

    @model_serializer(mode="wrap")
    def _no_values_says_nothing(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        if self.values is None:
            out.pop("values", None)
        return out


class MinerStale(StrictModel):
    """The rows of one registered miner an amendment makes stale (`ExtractionStale`)."""

    name: str
    rule: ExtractionStale


class ProtocolAmended(ReviewLinked):
    """A new version of the current protocol, or a prose-only change when the versions are equal.

    `spec` is the amended protocol; `to_version` must be its version hash. `changes` lists the
    criteria that were added, removed or changed; `other_changes` lists the other hashed fields
    (`AMENDABLE_FIELDS`) that differ. `semantic` is false only for a clarification or prose.
    `extraction_stale` and `contribution_stale` are computed from the old and new
    `extraction_schema` and `contribution_schema` respectively; neither touches the other's
    rows. Events written before `contribution_schema` existed lack `contribution_stale`."""

    amendment_id: str = Field(pattern=AMENDMENT_ID_RE)
    from_version: str = Field(pattern=PROTOCOL_ID_RE)
    to_version: str = Field(pattern=PROTOCOL_ID_RE)
    spec: ProtocolSpec
    reason: str = Field(min_length=1)
    semantic: bool
    changes: tuple[CriterionChange, ...] = ()
    stale_rules: tuple[StaleRule, ...] = ()
    other_changes: tuple[str, ...] = ()
    extraction_stale: ExtractionStale | None = None
    contribution_stale: ExtractionStale | None = None
    miner_stale: tuple[MinerStale, ...] = ()

    @model_validator(mode="after")
    def _to_version_matches_spec(self) -> Self:
        if self.to_version != protocol_version(self.spec):
            raise ValueError("to_version must be the version hash of spec")
        return self
