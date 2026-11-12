"""Readiness rules for a protocol: errors block a write, gaps block only `ready`.

`protocol_issues` is pure. It reads the spec, the current question, the seeds (for worked
examples and their hold-out role), the probe evidence and the known source names, and returns
two lists. Errors are structural and always block a write. Gaps are the conditions a protocol
must meet before it is declared ready; a draft with gaps may still be recorded.

Held-out seeds are never named in an issue: a worked example that is held out gets the same
message as an unknown seed (R-20).

`snowball_plan_gaps` is separate from readiness: a missing `snowball_plan` blocks snowball rounds
in `pilot` and `systematic` and is a promotion gap (slice 3a, ruling 19); it never blocks `ready`.
Negative round maxima are refused by the `SnowballPlan` model at the boundary.

The two extraction sections share one machinery (slice 3b, ruling 5; plan G2-A ruling 6):
`extraction_schema` may name any pack except `contribution`; `contribution_schema` must name
pack `contribution`, declare no comparability keys and set `claims` false. Field checks and the
plan-D ruling-9 sampling and audit gaps apply to both, each reported under its own section; the
comparability-key gap (R-45) applies to the evidence schema only.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from factory.errors import ValidationIssue
from factory.imports.model import ImportFormat, ImportRole
from factory.model.appraisal import INSTRUMENT_SECTION, PLATFORM_RULE_NAMES, AppraisalInstrument
from factory.model.miners import MinerUse
from factory.model.project import RigorMode
from factory.model.protocol import (
    AMENDABLE_FIELDS,
    ChangeKind,
    Criterion,
    CriterionChange,
    CriterionEffect,
    CriterionKind,
    ExtractionSchema,
    ExtractionStale,
    MethodProfile,
    PlannedQuery,
    ProtocolSpec,
    ReviewerRole,
    ScreeningPlan,
    SourcePlan,
    StaleRule,
    section_digest,
    strip_prose,
)
from factory.model.search import QuerySpec
from factory.model.staleness import DecisionRef as DecisionRef
from factory.model.staleness import stale_decisions as stale_decisions
from factory.modules.presets import preset, rank, weaker
from factory.packs import NON_COMPARABLE_KEYS, get_pack
from factory.packs.contribution import CONTRIBUTION_PACK
from factory.services.question import QuestionVersion
from factory.services.seeds import SeedRecord, SeedRole

# --- Amendments: what changed, and which earlier decisions it makes doubtful. ---


def criterion_changes(old: ProtocolSpec, new: ProtocolSpec) -> list[tuple[str, ChangeKind]]:
    """Criteria compared by id. A criterion is changed when its prose-stripped dump differs.

    A renamed criterion (a new id with similar text) is a removal plus an addition: its id
    is the identity that decisions cite."""
    old_by_id = {c.id: c for c in old.criteria}
    new_by_id = {c.id: c for c in new.criteria}
    changes: list[tuple[str, ChangeKind]] = []
    for cid in sorted(old_by_id.keys() | new_by_id.keys()):
        if cid not in new_by_id:
            changes.append((cid, ChangeKind.REMOVED))
        elif cid not in old_by_id:
            changes.append((cid, ChangeKind.ADDED))
        elif _criterion_dump(old_by_id[cid]) != _criterion_dump(new_by_id[cid]):
            changes.append((cid, ChangeKind.CHANGED))
    return changes


def other_changes(old: ProtocolSpec, new: ProtocolSpec) -> list[str]:
    """The hashed top-level fields other than criteria that differ."""
    return [key for key in AMENDABLE_FIELDS if section_digest(old, key) != section_digest(new, key)]


def extraction_stale(
    old: ExtractionSchema | None, new: ExtractionSchema | None
) -> ExtractionStale | None:
    """The extraction rows an amendment stales (ruling 12), or None.

    Nothing was declared before -> None. Schema removed, pack or pack version changed, or a
    field added -> every row. Fields only removed -> rows carrying them. Keys, sampling, audit
    settings and `claims` stale nothing."""
    if old is None:
        return None
    if new is None or (old.pack, old.pack_version) != (new.pack, new.pack_version):
        return ExtractionStale(all_records=True)
    if set(new.fields) - set(old.fields):
        return ExtractionStale(all_records=True)
    removed = tuple(f for f in old.fields if f not in new.fields)
    return ExtractionStale(all_records=False, fields=removed) if removed else None


def stale_rules(
    changes: Sequence[CriterionChange], old: ProtocolSpec, new: ProtocolSpec
) -> list[StaleRule]:
    """The rules an amendment's changes create. Clarification creates none.

    added -> untested at the new criterion's stage; removed -> exclusions citing it, at the old
    stage; loosened -> exclusions citing it; tightened -> inclusions."""
    old_by_id = {c.id: c for c in old.criteria}
    new_by_id = {c.id: c for c in new.criteria}
    rules: list[StaleRule] = []
    for change in changes:
        if change.change is ChangeKind.ADDED:
            rules.append(
                StaleRule(
                    criterion=change.cid,
                    stales="untested",
                    stage=new_by_id[change.cid].applies_at,
                )
            )
        elif change.change is ChangeKind.REMOVED:
            rules.append(
                StaleRule(
                    criterion=change.cid,
                    stales="exclusions-citing",
                    stage=old_by_id[change.cid].applies_at,
                )
            )
        elif change.effect is CriterionEffect.LOOSENED:
            rules.append(
                StaleRule(
                    criterion=change.cid,
                    stales="exclusions-citing",
                    stage=new_by_id[change.cid].applies_at,
                )
            )
        elif change.effect is CriterionEffect.TIGHTENED:
            rules.append(
                StaleRule(
                    criterion=change.cid,
                    stales="inclusions",
                    stage=new_by_id[change.cid].applies_at,
                )
            )
    return rules


def _criterion_dump(criterion: Criterion) -> object:
    return strip_prose(criterion.model_dump(mode="json"))


PARENT_MISSING = "every criterion names its parent question element or non-goal (R-11)"
UNKNOWN_SEED = "unknown seed"
KAPPA_FLOOR_MIN = 0.7
AUDIT_FRACTION_MIN = 0.02
AUDIT_MINIMUM_MIN = 50
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
    window_sources: Collection[str] = (),
    registered_miners: Collection[tuple[str, int]] = (),
    calibrated_miners: Collection[tuple[str, int]] = (),
    layer_miners: Collection[tuple[str, int]] = (),
    registered_taxonomies: Collection[tuple[str, int]] = (),
    miner_taxonomies: Mapping[tuple[str, int], tuple[str, int]] | None = None,
) -> ProtocolCheck:
    """Check a protocol against the current question, its seeds, its probes and its mode.

    `window_sources` names the sources whose adapter declares a listing-date filter; a
    `watch_plan` may use `window` mode only for those. `registered_taxonomies` and
    `miner_taxonomies` (listed miner version to the taxonomy version its spec references) feed the
    `taxonomies` section check.
    """
    errors = _errors(spec, question, current_question_id, mode, seeds, known_sources)
    errors.extend(_watch_plan_errors(spec, window_sources))
    errors.extend(_miner_errors(spec.miners, registered_miners, calibrated_miners))
    errors.extend(_layer_errors(spec.miners, layer_miners))
    errors.extend(_taxonomy_errors(spec, registered_taxonomies, miner_taxonomies or {}))
    gate_errors, gate_gaps = _gate_policy_issues(spec, mode)
    errors.extend(gate_errors)
    errors.extend(_hypothesis_plan_errors(spec, mode))
    errors.extend(_stop_rule_errors(spec, mode))
    gaps = _gaps(spec, question, mode, probes)
    gaps.extend(gate_gaps)
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
    non_goal_ids |= {sub_question.id for sub_question in question.spec.sub_questions}
    for i, criterion in enumerate(spec.criteria):
        if criterion.parent is None:
            if mode is not RigorMode.EXPLORATORY:
                issues.append(ValidationIssue(f"criteria[{i}].parent", PARENT_MISSING))
        elif not _resolves(criterion.parent, slot_names, non_goal_ids):
            issues.append(
                ValidationIssue(
                    f"criteria[{i}].parent",
                    "does not name a slot, non-goal or sub-question of the current question",
                )
            )

    roles = {seed.seed_id: seed.role for seed in seeds}
    for i, criterion in enumerate(spec.criteria):
        examples = (*criterion.examples.include, *criterion.examples.exclude)
        if any(roles.get(seed_id) in (None, SeedRole.HELD_OUT) for seed_id in examples):
            issues.append(ValidationIssue(f"criteria[{i}].examples", UNKNOWN_SEED))

    source_names: set[str] = set()
    for i, source in enumerate(spec.sources):
        if source.name not in known_sources:
            issues.append(ValidationIssue(f"sources[{i}].name", "unknown source"))
        if source.name in source_names:
            issues.append(ValidationIssue(f"sources[{i}].name", "duplicate source"))
        source_names.add(source.name)

    included = {source.name for source in spec.sources if source.included}
    earlier: list[tuple[PlannedQuery, QuerySpec]] = []
    for i, query in enumerate(spec.queries):
        as_spec = QuerySpec(
            source=query.source, kind=query.kind, text=query.text, filters=query.filters
        )
        if any(
            query.matches(prior_spec) and prior.matches(as_spec) for prior, prior_spec in earlier
        ):
            issues.append(ValidationIssue(f"queries[{i}]", "duplicate planned query"))
        earlier.append((query, as_spec))
        if query.source not in included:
            issues.append(
                ValidationIssue(
                    f"queries[{i}].source", "a query must use a source the protocol includes"
                )
            )
    issues.extend(_extraction_errors(spec.extraction_schema))
    issues.extend(_contribution_errors(spec.contribution_schema))
    issues.extend(appraisal_errors(spec.appraisal_instrument))
    return issues


def appraisal_errors(instrument: AppraisalInstrument | None) -> list[ValidationIssue]:
    """The `appraisal_instrument` section: item ids are unique and a platform item names a rule of
    the fixed menu. Absence is no error: the section is optional, and `systematic` only gets a
    `check` finding (plan EQ, required when)."""
    if instrument is None:
        return []
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for i, item in enumerate(instrument.items):
        where = f"{INSTRUMENT_SECTION}.items.{i}"
        if item.id in seen:
            issues.append(ValidationIssue(f"{where}.id", "an item id is listed once"))
        seen.add(item.id)
        if item.rule is not None and item.rule not in PLATFORM_RULE_NAMES:
            issues.append(
                ValidationIssue(f"{where}.rule", f"unknown rule; one of {PLATFORM_RULE_NAMES}")
            )
    return issues


MINERS_SECTION = "miners"
EVIDENCE_NEEDS_CALIBRATION = (
    "calibrate the miner first: evidence admission needs a passed calibration of this version "
    "in this project"
)


def _miner_errors(
    uses: Sequence[MinerUse] | None,
    registered: Collection[tuple[str, int]],
    calibrated: Collection[tuple[str, int]] = (),
) -> list[ValidationIssue]:
    """The `miners` section: each use names a registered `(name, version)`, a name is listed once
    (one version at a time), and `evidence` is refused unless that version's calibration passed
    in this project (`calibrated`; an imported calibration does not count, ruling 20)."""
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for i, use in enumerate(uses or ()):
        where = f"{MINERS_SECTION}.{i}"
        if (use.name, use.version) not in registered:
            issues.append(
                ValidationIssue(
                    f"{where}.name", "not a registered miner version; register it first"
                )
            )
        if use.name in seen:
            issues.append(ValidationIssue(f"{where}.name", "a miner is listed once"))
        seen.add(use.name)
        if use.evidence and (use.name, use.version) not in calibrated:
            issues.append(ValidationIssue(f"{where}.evidence", EVIDENCE_NEEDS_CALIBRATION))
    return issues


TAXONOMIES_SECTION = "taxonomies"


def _taxonomy_errors(
    spec: ProtocolSpec,
    registered: Collection[tuple[str, int]],
    miner_taxonomies: Mapping[tuple[str, int], tuple[str, int]],
) -> list[ValidationIssue]:
    """The `taxonomies` section: each use names a registered `(name, version)`, a name is listed
    once, and every listed miner whose registered spec references a taxonomy version has that
    version listed (reported on `miners.<i>.name`)."""
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for i, use in enumerate(spec.taxonomies or ()):
        where = f"{TAXONOMIES_SECTION}.{i}.name"
        if (use.name, use.version) not in registered:
            issues.append(
                ValidationIssue(where, "not a registered taxonomy version; register it first")
            )
        if use.name in seen:
            issues.append(ValidationIssue(where, "a taxonomy is listed once"))
        seen.add(use.name)
    listed = {(u.name, u.version) for u in spec.taxonomies or ()}
    for i, miner in enumerate(spec.miners or ()):
        ref = miner_taxonomies.get((miner.name, miner.version))
        if ref is not None and ref not in listed:
            issues.append(
                ValidationIssue(
                    f"{MINERS_SECTION}.{i}.name",
                    f"the miner derives from taxonomy {ref[0]} version {ref[1]}, which the "
                    "protocol must list in `taxonomies`",
                )
            )
    return issues


def _layer_errors(
    uses: Sequence[MinerUse] | None, layer_miners: Collection[tuple[str, int]]
) -> list[ValidationIssue]:
    """`MinerUse.layers` (the layer filter). Invariants: a use with `layers` needs the protocol to
    list a layer miner (a derived miner whose taxonomy has a dimension-zero dimension, passed as
    `layer_miners`, computed by the service); the layer miner itself carries no `layers`, since
    its reading assigns the layers the others filter by. Whether each entry is a layer id of a
    recorded scheme is not checked here (the scheme is not reachable from this pure module)."""
    listed = list(uses or ())
    filtered = [(i, u) for i, u in enumerate(listed) if u.layers]
    if not filtered:
        return []
    issues: list[ValidationIssue] = []
    layer_uses = [u for u in listed if (u.name, u.version) in layer_miners]
    if not layer_uses:
        issues.append(
            ValidationIssue(
                f"{MINERS_SECTION}.{filtered[0][0]}.layers",
                "layers need a listed derived miner whose taxonomy has a dimension-zero "
                "(layer scheme) dimension",
            )
        )
    for i, use in filtered:
        if (use.name, use.version) in layer_miners:
            issues.append(
                ValidationIssue(
                    f"{MINERS_SECTION}.{i}.layers",
                    "the layer miner assigns the layers and may not itself be filtered by them",
                )
            )
    return issues


EXTRACTION_SECTION = "extraction_schema"
CONTRIBUTION_SECTION = "contribution_schema"


def _extraction_errors(schema: ExtractionSchema | None) -> list[ValidationIssue]:
    """The evidence schema: any known pack but `contribution`, plus the plan-D field checks."""
    if schema is None:
        return []
    if schema.pack == CONTRIBUTION_PACK:
        return [
            ValidationIssue(
                f"{EXTRACTION_SECTION}.pack", "pack contribution belongs in contribution_schema"
            )
        ]
    return _schema_field_errors(schema, EXTRACTION_SECTION)


def _contribution_errors(schema: ExtractionSchema | None) -> list[ValidationIssue]:
    """The contribution schema: pack `contribution`, no comparability keys, no claims."""
    if schema is None:
        return []
    section = CONTRIBUTION_SECTION
    if schema.pack != CONTRIBUTION_PACK:
        return [ValidationIssue(f"{section}.pack", f"must be pack {CONTRIBUTION_PACK}")]
    issues = _schema_field_errors(schema, section)
    if schema.claims:
        issues.append(ValidationIssue(f"{section}.claims", "contribution items carry no claims"))
    if schema.comparability_keys:
        issues.append(
            ValidationIssue(
                f"{section}.comparability_keys", "contribution items have no comparability keys"
            )
        )
    return issues


def _schema_field_errors(schema: ExtractionSchema, section: str) -> list[ValidationIssue]:
    """Plan-D checks: a known pack version, declared fields of the pack, the pack's required
    fields declared, comparability keys among the declared fields and comparable."""
    pack = get_pack(schema.pack, schema.pack_version)
    if pack is None:
        return [
            ValidationIssue(
                f"{section}.pack",
                f"unknown pack {schema.pack} version {schema.pack_version}",
            )
        ]
    issues: list[ValidationIssue] = []
    known = {f.name for f in pack.fields}
    for i, name in enumerate(schema.fields):
        if name not in known:
            issues.append(
                ValidationIssue(f"{section}.fields[{i}]", f"not a field of the pack: {name}")
            )
    missing = [name for name in pack.required if name not in schema.fields]
    if missing:
        issues.append(
            ValidationIssue(f"{section}.fields", f"required by the pack: {', '.join(missing)}")
        )
    for i, key in enumerate(schema.comparability_keys):
        if key not in schema.fields:
            issues.append(
                ValidationIssue(f"{section}.comparability_keys[{i}]", "must be a declared field")
            )
        if key in NON_COMPARABLE_KEYS:
            issues.append(
                ValidationIssue(
                    f"{section}.comparability_keys[{i}]",
                    "speed/memory are not comparability keys",
                )
            )
    return issues


SNOWBALL_PLAN_MISSING = "snowball-plan-missing"


def snowball_plan_gaps(spec: ProtocolSpec, mode: RigorMode) -> list[ValidationIssue]:
    """`snowball-plan-missing` when `pilot` or `systematic` has no declared stopping rule."""
    if spec.snowball_plan is None and mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        return [ValidationIssue("snowball_plan", SNOWBALL_PLAN_MISSING)]
    return []


WATCH_PLAN_REQUIRED = "required for living-review"


def watch_plan_gaps(spec: ProtocolSpec, mode: RigorMode) -> list[ValidationIssue]:
    """A `living-review` protocol without a `watch_plan`: a promotion gap in `exploratory`.

    In `pilot` and `systematic` the same condition blocks `ready` (see `_gaps`).
    """
    if spec.method_profile is MethodProfile.LIVING_REVIEW and spec.watch_plan is None:
        return [ValidationIssue("watch_plan", WATCH_PLAN_REQUIRED)]
    return []


def _watch_plan_errors(
    spec: ProtocolSpec, window_sources: Collection[str]
) -> list[ValidationIssue]:
    """Every watched source is included; a window source's adapter has a listing-date filter."""
    plan = spec.watch_plan
    if plan is None:
        return []
    included = {source.name for source in spec.sources if source.included}
    issues: list[ValidationIssue] = []
    for i, item in enumerate(plan.sources):
        if item.source not in included:
            issues.append(
                ValidationIssue(f"watch_plan.sources[{i}].source", "not an included source")
            )
        elif item.mode == "window" and item.source not in window_sources:
            issues.append(
                ValidationIssue(f"watch_plan.sources[{i}].mode", "source has no window filter")
            )
    return issues


GATE_POLICY_BELOW_PRESET = "weaker than the preset"


def gate_policy_gaps(spec: ProtocolSpec, mode: RigorMode) -> list[ValidationIssue]:
    """Entries of `gate_policies` weaker than `mode`'s preset: a promotion gap (ruling 8), as
    `snowball_plan_gaps` is. Unknown gates and entries below the floor are errors elsewhere and
    are not repeated here."""
    from factory.services.modules.default import default_modules  # the registry imports services

    if spec.gate_policies is None:
        return []
    known = {g.gate_id: g for g in default_modules().gates()}
    gaps: list[ValidationIssue] = []
    for i, entry in enumerate(spec.gate_policies.entries):
        gate = known.get(entry.gate)
        if gate is None or rank(entry.policy) < rank(gate.floor):
            continue
        if weaker(entry.as_policy(), preset(mode, entry.gate)):
            gaps.append(
                ValidationIssue(f"gate_policies.entries.{i}.policy", GATE_POLICY_BELOW_PRESET)
            )
    return gaps


STOP_RULE_PROFILE = (
    "a stopping rule is a rapid-review shortcut; a systematic project cannot declare it"
)
STOP_RULE_STAGE = "the stopping rule applies to title/abstract screening only"


def _stop_rule_errors(spec: ProtocolSpec, mode: RigorMode) -> list[ValidationIssue]:
    """`screening.stop_after_consecutive_excludes` (slice 8): in `systematic` only under the
    `rapid-review` method profile (the mode-keyed pattern of `_hypothesis_plan_errors`); never in
    the full-text plan, which has no ranked serving."""
    issues: list[ValidationIssue] = []
    field = "stop_after_consecutive_excludes"
    if (
        spec.screening.stop_after_consecutive_excludes is not None
        and mode is RigorMode.SYSTEMATIC
        and spec.method_profile is not MethodProfile.RAPID_REVIEW
    ):
        issues.append(ValidationIssue(f"screening.{field}", STOP_RULE_PROFILE))
    full_text = spec.full_text_screening
    if full_text is not None and full_text.stop_after_consecutive_excludes is not None:
        issues.append(ValidationIssue(f"full_text_screening.{field}", STOP_RULE_STAGE))
    if (
        spec.screening.stop_below_score is not None
        and mode is RigorMode.SYSTEMATIC
        and spec.method_profile is not MethodProfile.RAPID_REVIEW
    ):
        issues.append(ValidationIssue("screening.stop_below_score", STOP_RULE_PROFILE))
    if full_text is not None and full_text.stop_below_score is not None:
        issues.append(ValidationIssue("full_text_screening.stop_below_score", STOP_RULE_STAGE))
    return issues


def _hypothesis_plan_errors(spec: ProtocolSpec, mode: RigorMode) -> list[ValidationIssue]:
    """Errors of `hypothesis_plan`: fewer than two seeds cannot give a confidence interval, the
    confirmatory split is read at least once, and a stated plan cannot switch off an independence
    rule the mode requires (a lead outside exploratory mode, a distinct critic model in
    systematic mode): the proposer would amend its own review away (slice M ruling 8)."""
    plan = spec.hypothesis_plan
    if plan is None:
        return []
    issues: list[ValidationIssue] = []
    if plan.min_seeds is not None and plan.min_seeds < 2:
        issues.append(ValidationIssue("hypothesis_plan.min_seeds", "at least 2 seeds"))
    if plan.test_access_limit < 1:
        issues.append(ValidationIssue("hypothesis_plan.test_access_limit", "at least 1"))
    if plan.require_lead is False and mode is not RigorMode.EXPLORATORY:
        issues.append(
            ValidationIssue("hypothesis_plan.require_lead", f"required in {mode.value} mode")
        )
    if plan.critic_distinct_model is False and mode is RigorMode.SYSTEMATIC:
        issues.append(
            ValidationIssue("hypothesis_plan.critic_distinct_model", "required in systematic mode")
        )
    return issues


def _gate_policy_issues(
    spec: ProtocolSpec, mode: RigorMode
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Errors and gaps of `gate_policies` (slice M ruling 8).

    An unknown gate, or a policy below the gate's floor, is an error in every mode. A policy
    weaker than the mode's preset is an error in `systematic`, a gap in `pilot` and allowed in
    `exploratory`. Messages name the gate and the mode, never a rate."""
    from factory.services.modules.default import default_modules  # the registry imports services

    if spec.gate_policies is None:
        return [], []
    registry = default_modules()
    known = {g.gate_id: g for g in registry.gates()}
    errors: list[ValidationIssue] = []
    gaps: list[ValidationIssue] = []
    for i, entry in enumerate(spec.gate_policies.entries):
        gate = known.get(entry.gate)
        if gate is None or gate.kind.value != "decision":
            errors.append(ValidationIssue(f"gate_policies.entries.{i}.gate", "unknown gate"))
            continue
        if rank(entry.policy) < rank(gate.floor):
            errors.append(
                ValidationIssue(
                    f"gate_policies.entries.{i}.policy", f"below the floor of {entry.gate}"
                )
            )
        elif weaker(entry.as_policy(), preset(mode, entry.gate)):
            issue = ValidationIssue(
                f"gate_policies.entries.{i}.policy",
                f"weaker than the {mode.value} preset of {entry.gate}",
            )
            if mode is RigorMode.SYSTEMATIC:
                errors.append(issue)
            elif mode is RigorMode.PILOT:
                gaps.append(issue)
    return errors, gaps


def _resolves(parent: str, slot_names: set[str], non_goal_ids: set[str]) -> bool:
    if parent.startswith(SLOT_PREFIX):
        return parent[len(SLOT_PREFIX) :] in slot_names
    return parent in non_goal_ids


def library_only(spec: ProtocolSpec, mode: RigorMode) -> bool:
    """Whether the protocol may rest on a declared library with no search (PD-3): a `corpus` entry
    in `library_sources`, in exploratory or pilot. `systematic` always needs a search. The PRESS
    review stays required; with nothing to review its findings are empty."""
    return mode is not RigorMode.SYSTEMATIC and any(
        source.role is ImportRole.CORPUS for source in spec.library_sources or ()
    )


def _gaps(
    spec: ProtocolSpec,
    question: QuestionVersion,
    mode: RigorMode,
    probes: Mapping[str, set[str]],
) -> list[ValidationIssue]:
    gaps: list[ValidationIssue] = []
    if mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        gaps.extend(watch_plan_gaps(spec, mode))
        gaps.extend(_coverage_gaps(spec, question))
        gaps.extend(_priority_gaps(spec))
        gaps.extend(_probe_gaps(spec, probes))

    if not library_only(spec, mode):
        if not any(source.included for source in spec.sources):
            gaps.append(ValidationIssue("sources", "at least one source must be included"))
        if not spec.queries:
            gaps.append(ValidationIssue("queries", "at least one query is required"))

    if mode is RigorMode.PILOT:
        gaps.extend(_pilot_screening_gaps(spec))
    elif mode is RigorMode.SYSTEMATIC:
        gaps.extend(_systematic_screening_gaps(spec))

    gaps.extend(_reviewer_gaps(spec))
    if mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        gaps.extend(_extraction_gaps(spec.extraction_schema, mode))
        gaps.extend(_sampling_gaps(spec.contribution_schema, mode, CONTRIBUTION_SECTION))
        for i, use in enumerate(spec.miners or ()):
            gaps.extend(_sampling_gaps(use, mode, f"{MINERS_SECTION}.{i}"))
    return gaps


def _extraction_gaps(schema: ExtractionSchema | None, mode: RigorMode) -> list[ValidationIssue]:
    """The evidence schema needs comparability keys (R-45) and the ruling-9 sampling gaps."""
    if schema is None:
        return []
    gaps: list[ValidationIssue] = []
    if not schema.comparability_keys:
        gaps.append(
            ValidationIssue(
                f"{EXTRACTION_SECTION}.comparability_keys",
                "declare the comparability keys (R-45)",
            )
        )
    gaps.extend(_sampling_gaps(schema, mode, EXTRACTION_SECTION))
    return gaps


def _sampling_gaps(
    schema: ExtractionSchema | MinerUse | None, mode: RigorMode, section: str
) -> list[ValidationIssue]:
    """Plan-D ruling 9: pilot needs a dual-extraction fraction, systematic needs every work;
    both need the audit floors."""
    if schema is None:
        return []
    gaps: list[ValidationIssue] = []
    sample = schema.dual_extract_sample
    if mode is RigorMode.PILOT and sample is None:
        gaps.append(
            ValidationIssue(
                f"{section}.dual_extract_sample",
                "pilot extraction needs a dual-extracted fraction",
            )
        )
    if mode is RigorMode.SYSTEMATIC and sample not in (None, 1.0):
        gaps.append(
            ValidationIssue(
                f"{section}.dual_extract_sample",
                "systematic extraction needs dual_extract_sample unset or 1.0: "
                "every work is extracted twice",
            )
        )
    if schema.audit_fraction < AUDIT_FRACTION_MIN:
        gaps.append(
            ValidationIssue(
                f"{section}.audit_fraction",
                f"the audit samples at least {AUDIT_FRACTION_MIN:.0%} of agreed values",
            )
        )
    if schema.audit_minimum < AUDIT_MINIMUM_MIN:
        gaps.append(
            ValidationIssue(
                f"{section}.audit_minimum",
                f"the audit draws at least {AUDIT_MINIMUM_MIN} values",
            )
        )
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
    gaps.extend(_audit_gaps(screening))
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
    gaps.extend(_audit_gaps(screening))
    return gaps


def _audit_gaps(screening: ScreeningPlan) -> list[ValidationIssue]:
    gaps: list[ValidationIssue] = []
    if screening.audit_fraction < AUDIT_FRACTION_MIN:
        gaps.append(
            ValidationIssue(
                "screening.audit_fraction",
                f"the audit samples at least {AUDIT_FRACTION_MIN:.0%} of agreed decisions",
            )
        )
    if screening.audit_minimum < AUDIT_MINIMUM_MIN:
        gaps.append(
            ValidationIssue(
                "screening.audit_minimum", f"the audit draws at least {AUDIT_MINIMUM_MIN} works"
            )
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


DEFAULT_LIBRARY = "default"
LIBRARY_UNDECLARED = "library-undeclared"


def library_source_gaps(
    spec: ProtocolSpec, collection: str | None, format: ImportFormat
) -> list[ValidationIssue]:
    """`library-undeclared` unless `library_sources` has an entry with the import's collection
    (`default` when it names none) and format whose role is `corpus` (slice 3d, ruling 20).

    The caller decides what the gap means: a refusal in `pilot` and `systematic`, a reported
    promotion gap in `exploratory`.
    """
    name = collection or DEFAULT_LIBRARY
    declared = any(
        s.name == name and s.format is format and s.role is ImportRole.CORPUS
        for s in spec.library_sources or ()
    )
    if declared:
        return []
    return [
        ValidationIssue(
            "library_sources",
            f"{LIBRARY_UNDECLARED}: no corpus entry for collection {name!r} in {format.value}",
        )
    ]
