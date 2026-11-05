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
Level = Literal["0.90", "0.95", "0.99"]

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


# --- Hypothesis specification --------------------------------------------------------------

CardRef = Annotated[str, StringConstraints(pattern=CARD_ID_RE)]
IdeaRef = Annotated[str, StringConstraints(pattern=IDEA_ID_RE)]
RowKey = Annotated[str, StringConstraints(pattern=ROW_KEY_RE)]
Decimal0 = Annotated[str, StringConstraints(pattern=DECIMAL_RE)]
Name = Annotated[NonBlank, Field(max_length=MAX_METHOD_NAME)]


class MethodRef(StrictModel):
    """A method of the hypothesis: exactly one of a method card, a lineage idea or a plain name,
    with an optional evidence row that reports it."""

    card: CardRef | None = None
    idea: IdeaRef | None = None
    name: Name | None = None
    row_key: RowKey | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if sum(x is not None for x in (self.card, self.idea, self.name)) != 1:
            raise ValueError("name exactly one of card, idea or name")
        return self


class MetricSpec(StrictModel):
    name: Name
    direction: Literal["higher", "lower"]
    unit_family: UnitFamily
    unit: Annotated[NonBlank, Field(max_length=40)] | None = None


class Prediction(StrictModel):
    direction: Literal["treatment-better", "no-worse"]
    margin: Decimal0
    unit: Annotated[NonBlank, Field(max_length=40)] | None = None


class Superiority(StrictModel):
    rule: Literal["superiority"] = "superiority"


class NonInferiority(StrictModel):
    rule: Literal["non-inferiority"] = "non-inferiority"


class LiteratureDirection(StrictModel):
    rule: Literal["literature-direction"] = "literature-direction"
    n_min: int = Field(ge=1)
    q: Decimal0

    @model_validator(mode="after")
    def _q_in_range(self) -> Self:
        if not Decimal("0.5") < Decimal(self.q) <= Decimal(1):
            raise ValueError("q lies in (0.5, 1]")
        return self


DecisionRule = Annotated[
    Superiority | NonInferiority | LiteratureDirection, Field(discriminator="rule")
]


class ExperimentTest(StrictModel):
    """The hypothesis is tested by an experiment design that names it (the design points here,
    so linking a design never changes `H@`)."""

    kind: Literal["experiment"] = "experiment"


class LiteratureTest(StrictModel):
    kind: Literal["literature"] = "literature"
    window_start: date
    sources: tuple[Annotated[NonBlank, Field(max_length=120)], ...] = ()
    """The search runs or protocol versions that define "later literature"."""


Test = Annotated[ExperimentTest | LiteratureTest, Field(discriminator="kind")]


class HypothesisSpec(StrictModel):
    """A hypothesis as an agent or a human states it. `H@` hashes the decision-relevant fields
    (`HASHED_FIELDS`); `statement`, `rationale`, `alternatives` and `lead` are links and prose."""

    kind: Literal["experiment", "literature"]
    statement: Annotated[NonBlank, Field(max_length=MAX_STATEMENT)]
    lead: LeadId | None = None
    treatment: MethodRef
    baseline: MethodRef
    metric: MetricSpec
    conditions: dict[str, str] = Field(default_factory=dict)
    prediction: Prediction
    decision_rule: DecisionRule
    test: Test
    alternatives: tuple[HypothesisId, ...] = ()
    rationale: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.kind != self.test.kind:
            raise ValueError("kind and test.kind must agree")
        rule = self.decision_rule.rule
        if (self.kind == "literature") != (rule == "literature-direction"):
            raise ValueError("literature-direction is the rule of a literature hypothesis only")
        if (self.prediction.direction == "no-worse") != (rule == "non-inferiority"):
            raise ValueError("a `no-worse` prediction goes with non-inferiority, and only it")
        if any(not k.strip() or not v.strip() for k, v in self.conditions.items()):
            raise ValueError("conditions name a key and a value")
        return self


HASHED_FIELDS = (
    "kind",
    "treatment",
    "baseline",
    "metric",
    "conditions",
    "prediction",
    "decision_rule",
    "test",
)


def hypothesis_version(spec: HypothesisSpec) -> str:
    """`H@` and the first eight hex digits of the hash over the decision-relevant fields. The
    statement, rationale, alternatives and lead never enter; neither does key order."""
    dump = spec.model_dump(mode="json")
    body: dict[str, JsonValue] = {name: dump[name] for name in HASHED_FIELDS}
    test = dict(dump["test"])
    if "sources" in test:
        test["sources"] = sorted(test["sources"])
    body["test"] = test
    return "H@" + hashlib.sha256(canonical_json(body)).hexdigest()[:8]


def _percent(value: str) -> str:
    return f"{(Decimal(value) * 100).normalize():f}%"


def falsifier_text(spec: HypothesisSpec, *, confidence: str = "0.95") -> str:
    """The sentence that says what would refute the hypothesis, generated from the rule, the
    margin, the metric and the conditions; never typed by an agent."""
    unit = spec.prediction.unit or spec.metric.unit
    margin = f"{spec.prediction.margin} {unit}" if unit else spec.prediction.margin
    where = ", ".join(f"{k}={v}" for k, v in sorted(spec.conditions.items()))
    scope = f" ({where})" if where else ""
    metric = spec.metric.name
    difference = (
        "(treatment \N{MINUS SIGN} baseline)"
        if spec.metric.direction == "higher"
        else "(baseline \N{MINUS SIGN} treatment)"
    )
    rule = spec.decision_rule
    if isinstance(rule, Superiority):
        return (
            f"Refuted if the {_percent(confidence)} CI upper bound of {difference} on "
            f"{metric}{scope} is below {margin}."
        )
    if isinstance(rule, NonInferiority):
        return (
            f"Refuted if the {_percent(confidence)} CI upper bound of {difference} on "
            f"{metric}{scope} is below \N{MINUS SIGN}{margin}."
        )
    return (
        f"Refuted if at least {_percent(rule.q)} of at least {rule.n_min} later-literature "
        f"comparisons of treatment and baseline on {metric}{scope} favour the baseline."
    )


# --- Drafting, abandonment, conclusion -----------------------------------------------------


class HypothesisDrafted(StrictModel):
    hypothesis_id: HypothesisId
    spec: HypothesisSpec
    h_version: HVersion
    supersedes: HypothesisId | None = None

    @model_validator(mode="after")
    def _version_is_computed(self) -> Self:
        if self.h_version != hypothesis_version(self.spec):
            raise ValueError("h_version is the hash of the spec; it is computed, not stated")
        if self.supersedes == self.hypothesis_id:
            raise ValueError("a hypothesis cannot supersede itself")
        return self


class AbandonReason(StrEnum):
    NO_RUNNABLE_CODE = "no-runnable-code"
    BUDGET_EXHAUSTED = "budget-exhausted"
    INFEASIBLE = "infeasible"
    DATA_UNAVAILABLE = "data-unavailable"
    OTHER = "other"


class HypothesisAbandoned(StrictModel):
    hypothesis_id: HypothesisId
    reason: AbandonReason
    note: Annotated[NonBlank, Field(max_length=MAX_NOTE)]


class HypothesisConcluded(StrictModel):
    hypothesis_id: HypothesisId
    text: Annotated[NonBlank, Field(max_length=MAX_CONCLUSION)]


# --- Critic review -------------------------------------------------------------------------

ChecklistItem = Literal[
    "falsifiable",
    "measurable",
    "single-factor",
    "baselines-named",
    "rule-complete",
    "prior-addressed",
    "conditions-in-evidence",
]
CHECKLIST: tuple[ChecklistItem, ...] = (
    "falsifiable",
    "measurable",
    "single-factor",
    "baselines-named",
    "rule-complete",
    "prior-addressed",
    "conditions-in-evidence",
)
ItemResult = Literal["pass", "fail", "n/a"]
Recommendation = Literal["register", "revise", "reject"]
ReviewNote = Annotated[str, Field(max_length=MAX_NOTE)]


class ReviewTrigger(StrictModel):
    """A lead trigger as the critic sees it: the reference, the builder row stored with it and,
    for a claim or a contribution item, the verified quote the platform holds."""

    kind: TriggerKind
    ref: str
    row: dict[str, JsonValue] | None = None
    quote: str | None = None


class ReviewTask(StrictModel):
    """What a critic is served: the artefact and nothing of its proposer. The lead's text, its
    `input_blob` and the drafter's rationale are never part of it (R-51)."""

    hypothesis_id: HypothesisId
    h_version: HVersion
    spec_without_prose: dict[str, JsonValue]
    statement: str
    triggers: list[ReviewTrigger]
    prior: list[str]
    prior_total: int
    checklist: list[ChecklistItem]


class ReviewInput(StrictModel):
    """The critic's verdict: every checklist item, a note per item if wanted, a recommendation."""

    items: dict[ChecklistItem, ItemResult]
    notes: dict[ChecklistItem, ReviewNote] = Field(default_factory=dict)
    recommend: Recommendation

    @model_validator(mode="after")
    def _every_item_answered(self) -> Self:
        missing = [item for item in CHECKLIST if item not in self.items]
        if missing:
            raise ValueError(f"answer every checklist item; missing {', '.join(missing)}")
        stray = [item for item in self.notes if item not in self.items]
        if stray:
            raise ValueError("notes name checklist items only")
        return self


class HypothesisReviewed(StrictModel):
    hypothesis_id: HypothesisId
    h_version: HVersion
    items: dict[ChecklistItem, ItemResult]
    notes: dict[ChecklistItem, ReviewNote] = Field(default_factory=dict)
    recommend: Recommendation
    critic_session: str
    critic_model: str | None = None
    task_id: str


# --- Registration and model cut-offs -------------------------------------------------------


class HypothesisRegistered(StrictModel):
    """The act at the gate `hypotheses.register`. `policy` is the gate policy in force and
    `autonomy` the label of the act: `human`, or `agent` for any agent act. Both are checked by
    the projector against the log; an event that disagrees is not folded."""

    hypothesis_id: HypothesisId
    h_version: HVersion
    review_event_id: str | None = None
    policy: PolicyKind
    autonomy: Literal["human", "agent"]
    flags: tuple[str, ...] = ()
    level: Level | None = None
    min_seeds: int | None = Field(default=None, ge=1)
    """The confidence level and minimum seeds in force at registration: the decision rule is
    judged at these, whatever the protocol says later (R-121). None in a log written before
    these fields; the fold then pins the plan in force at this point of the log."""


class ModelCutoffDeclared(StrictModel):
    """A human's declaration of a model's training cut-off (R-53); the latest per model wins."""

    model: Annotated[NonBlank, Field(max_length=120)]
    cutoff: date
    source: Annotated[NonBlank, Field(max_length=300)]


# --- Evaluation (plan XP-B) ---------------------------------------------------------------

EVALUATOR_VERSION = "1"
EVALUATION_OUTCOMES = ("supported", "refuted", "inconclusive", "incomplete")
SIGNED_DECIMAL_RE = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"


class LiteratureComparison(StrictModel):
    """One work that compares the two methods: the evidence rows read and the side it favours.
    The projector checks them against the works and extraction tables."""

    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)]
    treatment_row: RowKey
    baseline_row: RowKey
    favour: Literal["treatment", "baseline", "tie"]


class HypothesisEvaluated(StrictModel):
    """The computed outcome of a registered hypothesis, written by the platform (a `system` actor)
    and by nothing else. There is no input model: no tool, command or service takes an outcome.
    The projector recomputes the whole payload from the log and folds the event only if it is
    equal to the recomputation (experiment hypotheses) or checks out against the works, rows,
    cut-offs and registration (literature hypotheses), so a hand-written event changes nothing."""

    hypothesis_id: HypothesisId
    h_version: HVersion
    experiment_id: Annotated[str, StringConstraints(pattern=rf"^exp_{ULID_RE}$")] | None = None
    e_version: Annotated[str, StringConstraints(pattern=r"^E@[0-9a-f]{8}$")] | None = None
    outcome: Literal["supported", "refuted", "inconclusive", "incomplete"]
    n: int = Field(ge=0)
    mean: Annotated[str, StringConstraints(pattern=SIGNED_DECIMAL_RE)] | None = None
    ci_low: Annotated[str, StringConstraints(pattern=SIGNED_DECIMAL_RE)] | None = None
    ci_high: Annotated[str, StringConstraints(pattern=SIGNED_DECIMAL_RE)] | None = None
    level: Level
    counts: dict[str, int] = Field(default_factory=dict)
    flags: tuple[str, ...] = ()
    runs: tuple[str, ...] = ()
    works: tuple[str, ...] = ()
    comparisons: tuple[LiteratureComparison, ...] = ()
    inputs_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    evaluator_version: str
