"""Readiness rules for a protocol: errors block a write, gaps block only `ready`.

`protocol_issues` is pure. It reads the spec, the current question, the seeds (for worked
examples and their hold-out role), the probe evidence and the known source names, and returns
two lists. Errors are structural and always block a write. Gaps are the conditions a protocol
must meet before it is declared ready; a draft with gaps may still be recorded.

Held-out seeds are never named in an issue: a worked example that is held out gets the same
message as an unknown seed (R-20).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from factory.errors import ValidationIssue
from factory.model.project import RigorMode
from factory.model.protocol import (
    CriterionKind,
    ProtocolSpec,
    ReviewerRole,
    SourcePlan,
)
from factory.services.question import QuestionVersion
from factory.services.seeds import SeedRecord, SeedRole

PARENT_MISSING = "every criterion names its parent question element or non-goal (R-11)"
UNKNOWN_SEED = "unknown seed"
KAPPA_FLOOR_MIN = 0.7
SLOT_PREFIX = "slot:"


@dataclass(frozen=True)
class ProtocolCheck:
    """`errors` always block a write; `gaps` block only a `ready` declaration."""

    errors: list[ValidationIssue]
    gaps: list[ValidationIssue]


def protocol_issues(
    spec: ProtocolSpec,
    *,
    question: QuestionVersion,
    current_question_id: str,
    mode: RigorMode,
    seeds: Sequence[SeedRecord],
    probes: Mapping[str, set[str]],
    known_sources: set[str],
) -> ProtocolCheck:
    """Check a protocol against the current question, its seeds, its probes and its mode."""
    errors = _errors(spec, question, current_question_id, mode, seeds, known_sources)
    gaps = _gaps(spec, question, mode, probes)
    return ProtocolCheck(errors=errors, gaps=gaps)


def _errors(
    spec: ProtocolSpec,
    question: QuestionVersion,
    current_question_id: str,
    mode: RigorMode,
    seeds: Sequence[SeedRecord],
    known_sources: set[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if spec.question_id != current_question_id:
        issues.append(ValidationIssue("question_id", "must be the current question version"))

    seen: set[str] = set()
    for i, criterion in enumerate(spec.criteria):
        if criterion.id in seen:
            issues.append(ValidationIssue(f"criteria[{i}].id", "duplicate criterion id"))
        seen.add(criterion.id)

    slot_names = {slot.name for slot in question.spec.slots}
    non_goal_ids = {non_goal.id for non_goal in question.spec.non_goals}
    for i, criterion in enumerate(spec.criteria):
        if criterion.parent is None:
            if mode is not RigorMode.EXPLORATORY:
                issues.append(ValidationIssue(f"criteria[{i}].parent", PARENT_MISSING))
        elif not _resolves(criterion.parent, slot_names, non_goal_ids):
            issues.append(
                ValidationIssue(
                    f"criteria[{i}].parent",
                    "does not name a slot or non-goal of the current question",
                )
            )

    roles = {seed.seed_id: seed.role for seed in seeds}
    for i, criterion in enumerate(spec.criteria):
        examples = (*criterion.examples.include, *criterion.examples.exclude)
        if any(roles.get(seed_id) in (None, SeedRole.HELD_OUT) for seed_id in examples):
            issues.append(ValidationIssue(f"criteria[{i}].examples", UNKNOWN_SEED))

    for i, source in enumerate(spec.sources):
        if source.name not in known_sources:
            issues.append(ValidationIssue(f"sources[{i}].name", "unknown source"))

    included = {source.name for source in spec.sources if source.included}
    for i, query in enumerate(spec.queries):
        if query.source not in included:
            issues.append(
                ValidationIssue(
                    f"queries[{i}].source", "a query must use a source the protocol includes"
                )
            )
    return issues


def _resolves(parent: str, slot_names: set[str], non_goal_ids: set[str]) -> bool:
    if parent.startswith(SLOT_PREFIX):
        return parent[len(SLOT_PREFIX) :] in slot_names
    return parent in non_goal_ids


def _gaps(
    spec: ProtocolSpec,
    question: QuestionVersion,
    mode: RigorMode,
    probes: Mapping[str, set[str]],
) -> list[ValidationIssue]:
    gaps: list[ValidationIssue] = []
    if mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        gaps.extend(_coverage_gaps(spec, question))
        gaps.extend(_priority_gaps(spec))
        gaps.extend(_probe_gaps(spec, probes))

    if not any(source.included for source in spec.sources):
        gaps.append(ValidationIssue("sources", "at least one source must be included"))
    if not spec.queries:
        gaps.append(ValidationIssue("queries", "at least one query is required"))

    if mode is RigorMode.PILOT:
        gaps.extend(_pilot_screening_gaps(spec))
    elif mode is RigorMode.SYSTEMATIC:
        gaps.extend(_systematic_screening_gaps(spec))

    gaps.extend(_reviewer_gaps(spec))
    return gaps


def _coverage_gaps(spec: ProtocolSpec, question: QuestionVersion) -> list[ValidationIssue]:
    gaps: list[ValidationIssue] = []
    exclusions = [c for c in spec.criteria if c.kind is CriterionKind.EXCLUSION]
    inclusions = [c for c in spec.criteria if c.kind is CriterionKind.INCLUSION]

    excluded_parents = {c.parent for c in exclusions}
    for non_goal in question.spec.non_goals:
        if non_goal.id not in excluded_parents:
            gaps.append(
                ValidationIssue(
                    f"non_goals.{non_goal.id}", "no exclusion names this non-goal as its parent"
                )
            )

    included_parents = {c.parent for c in inclusions}
    for slot in question.spec.slots:
        if slot.value is None:
            continue
        if f"{SLOT_PREFIX}{slot.name}" not in included_parents:
            gaps.append(
                ValidationIssue(
                    f"slots.{slot.name}", "no inclusion names this filled slot as its parent"
                )
            )
    return gaps


def _priority_gaps(spec: ProtocolSpec) -> list[ValidationIssue]:
    gaps: list[ValidationIssue] = []
    seen: set[int] = set()
    for i, criterion in enumerate(spec.criteria):
        if criterion.kind is not CriterionKind.EXCLUSION or criterion.priority is None:
            continue
        if criterion.priority in seen:
            gaps.append(
                ValidationIssue(f"criteria[{i}].priority", "exclusion priorities must be distinct")
            )
        seen.add(criterion.priority)
    return gaps


def _probe_gaps(spec: ProtocolSpec, probes: Mapping[str, set[str]]) -> list[ValidationIssue]:
    gaps: list[ValidationIssue] = []
    for i, source in enumerate(spec.sources):
        if source.included and not _probed(source, probes):
            gaps.append(
                ValidationIssue(
                    f"sources[{i}].probe_id", "an included source needs a probe that measured it"
                )
            )
    return gaps


def _probed(source: SourcePlan, probes: Mapping[str, set[str]]) -> bool:
    return source.probe_id is not None and source.name in probes.get(source.probe_id, set())


def _pilot_screening_gaps(spec: ProtocolSpec) -> list[ValidationIssue]:
    screening = spec.screening
    gaps: list[ValidationIssue] = []
    if screening.passes != 2:
        gaps.append(ValidationIssue("screening.passes", "pilot screening needs two passes"))
    if screening.dual_sample is None:
        gaps.append(
            ValidationIssue("screening.dual_sample", "pilot screening needs a dual-coded sample")
        )
    if screening.kappa_floor is None:
        gaps.append(ValidationIssue("screening.kappa_floor", "a kappa floor must be declared"))
    return gaps


def _systematic_screening_gaps(spec: ProtocolSpec) -> list[ValidationIssue]:
    screening = spec.screening
    gaps: list[ValidationIssue] = []
    if screening.passes != 2:
        gaps.append(ValidationIssue("screening.passes", "systematic screening needs two passes"))
    if screening.dual_sample not in (None, 1.0):
        gaps.append(
            ValidationIssue(
                "screening.dual_sample", "systematic screening codes every record or none"
            )
        )
    if screening.kappa_floor is None or screening.kappa_floor < KAPPA_FLOOR_MIN:
        gaps.append(
            ValidationIssue(
                "screening.kappa_floor",
                f"systematic screening needs a kappa floor of at least {KAPPA_FLOOR_MIN}",
            )
        )
    if not screening.kappa_enforced:
        gaps.append(
            ValidationIssue("screening.kappa_enforced", "systematic screening enforces the floor")
        )
    return gaps


def _reviewer_gaps(spec: ProtocolSpec) -> list[ValidationIssue]:
    records = [r for r in spec.screening.reviewers if r.role is ReviewerRole.REVIEWER_OF_RECORD]
    if len(records) != 1:
        return [
            ValidationIssue("screening.reviewers", "exactly one reviewer-of-record is required")
        ]
    if records[0].kind != "human":
        return [ValidationIssue("screening.reviewers", "the reviewer-of-record must be human")]
    return []
