"""The calibration set: drawn once, labelled by a human, and the per-pass gate on it (R-20, R-35).

`draw_calibration` picks the set from the resolved development seeds that are not worked examples,
the resolved negative seeds that are not worked examples, and seeded random corpus works up to the
protocol's `calibration_size` (a floor: every such seed is included). Held-out seeds and their
works are never chosen, not even as random fill, and neither are worked examples (an agent has
seen them). The split must be drawn first.

`label_calibration` records a human's label on an item of the set. The criterion is given bare and
qualified against the current protocol. An MCP-relayed label is refused from a session that has
joined a pass, so a screener cannot read the answer key.

`calibration_status` reports, per pass, the sensitivity and specificity of its live calibration
decisions under the current protocol version, and whether the pass has passed: every item is
labelled, the pass decided every item, and sensitivity reaches the mode's threshold (if any). A
human pass stands outside the gate unless the plan sets `calibrate_humans`, since the labeller is
usually the reference standard: it counts as passed, and it is served no calibration batch.

Every function takes a keyword `stage` (default title/abstract). The calibration set is drawn once
per stage; the full-text set is drawn from the full-text population (`_calibration_population`)
under the full-text plan, which must be declared. `either` is refused on field `stage`.
"""

import random
import secrets
from collections.abc import Iterable
from string import ascii_uppercase

from pydantic import JsonValue, ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningPlan, ScreeningStage
from factory.model.screening import (
    CalibrationDrawn,
    CalibrationLabelled,
    Channel,
    PassLabel,
    ScreeningPhase,
    Verdict,
)
from factory.model.seed import SeedKind
from factory.modules.presets import Enforcement, enforcement
from factory.services import passes
from factory.services.context import Project
from factory.services.dedup import absorbed_ids
from factory.services.gates import gate_issues
from factory.services.human_channel import require_human_channel
from factory.services.protocol import (
    ProtocolVersion,
    current_protocol,
    last_criterion_change,
    lineage_through,
)
from factory.services.protocol_rules import library_only
from factory.services.screening_stats import CALIBRATION_SENSITIVITY, Rates, sensitivity_specificity
from factory.services.search import corpus_work_ids
from factory.services.seeds import (
    SeedRole,
    SeedView,
    _rigor_mode,
    agent_seeds,
    all_seeds,
    split_is_drawn,
)
from factory.services.stages import require_pass_stage, screening_plan
from factory.services.work_ref import resolve_work_id

WORKED_EXAMPLES = 2
"""Development positives and negatives, each, shown to the screeners as worked examples."""

_DEFAULT_CALIBRATION_SIZE = int(ScreeningPlan.model_fields["calibration_size"].default)


class CalibrationStatus(StrictModel):
    drawn: int
    labelled: int
    required: bool
    per_pass: dict[str, Rates]
    passed: dict[str, bool]


def worked_examples(project: Project) -> list[SeedView]:
    """The lowest-ID `WORKED_EXAMPLES` development positives, then the lowest-ID negatives, among
    the seeds that resolved to corpus works. Held-out seeds are never returned."""
    corpus = _corpus_ids(project)
    resolved = [s for s in agent_seeds(project) if s.work_id in corpus]
    positives = _by_number(s for s in resolved if s.kind is SeedKind.POSITIVE)
    negatives = _by_number(s for s in resolved if s.kind is SeedKind.NEGATIVE)
    return positives[:WORKED_EXAMPLES] + negatives[:WORKED_EXAMPLES]


def draw_calibration(
    project: Project,
    actor: Actor,
    *,
    random_seed: int | None = None,
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT,
) -> list[str]:
    """Draw the calibration set of `stage` once and return its work ids, sorted.

    A second call returns the existing set and writes nothing. The default seed is 32 random
    bits. Refused when the hold-out split has not been drawn, since the set must exclude
    held-out works, unless a library-only protocol has no seed to hold out. The protocol's
    `calibration_size` is a floor, not a cap: every development seed in the population (but for
    the worked examples) is always included, and seeded random
    works fill the set up to the size when the population allows. Refused, with nothing written,
    at full text while no work is eligible yet, so the draw can be redone after conversion.
    """
    require_pass_stage(stage)
    seed = secrets.randbits(32) if random_seed is None else random_seed
    with project.index.exclusive():
        project.index.sync()
        protocol = current_protocol(project)
        if protocol is not None:
            screening_plan(protocol, stage)  # refuses full text without a declared plan
        if _was_drawn(project, stage):
            return _drawn_items(project, stage)
        issues: list[ValidationIssue] = []
        if not 0 <= seed < 2**32:
            issues.append(ValidationIssue("random_seed", "must be an integer from 0 to 2**32 - 1"))
        if not split_is_drawn(project) and not _nothing_held_out(project, protocol):
            issues.append(ValidationIssue("split", "draw the seed split before the calibration"))
        if stage is ScreeningStage.FULL_TEXT and not _calibration_population(project, stage):
            issues.append(
                ValidationIssue(
                    "stage",
                    "no works are eligible at full text yet; fetch and convert documents first",
                )
            )
        if issues:
            raise FactoryValidationError(issues)

        items = _select(project, seed, stage)
        payload = CalibrationDrawn(
            protocol_id=None if protocol is None else protocol.protocol_id,
            work_ids=tuple(items),
            random_seed=seed,
            stage=stage,
        )
        input_blob = None
        if actor.kind == "agent":
            draw_input: dict[str, JsonValue] = {"random_seed": seed, "work_ids": list(items)}
            input_blob = project.blobs.put_json(draw_input)
        project.record(
            [project.events.make("calibration.drawn", payload, actor, input_blob=input_blob)]
        )
    return items


def label_calibration(
    project: Project,
    actor: Actor,
    work_id: str,
    verdict: str,
    criterion: str | None,
    channel: Channel,
    *,
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT,
) -> str:
    """Record a human's label on one item of the calibration set of `stage`; return the event id.

    Refused, with nothing written, when the actor is not human, the work is not in the set, the
    criterion is not in the current protocol, the verdict or criterion does not fit, the label is
    relayed over MCP from a session that has joined a pass, or, on a hosted project, the person is
    a member of either pass of the stage.
    """
    require_pass_stage(stage)
    with project.index.exclusive():
        project.index.sync()
        passes.require_outside_passes(project, actor.user, stage)
        require_human_channel(project, actor, channel, "audit-label")
        work_id = resolve_work_id(project, work_id)
        issues: list[ValidationIssue] = []
        issues.extend(
            gate_issues(
                project,
                actor,
                "screening.calibration_label",
                channel=channel,
                agent_text="calibration labels are human acts",
            )
        )
        if work_id not in _drawn_items(project, stage):
            issues.append(ValidationIssue("work_id", "not in the calibration set"))
        protocol = current_protocol(project)
        qualified: str | None = None
        if criterion is not None:
            if protocol is None:
                issues.append(ValidationIssue("criterion", "record a protocol first"))
            elif criterion not in {c.id for c in protocol.spec.criteria}:
                issues.append(ValidationIssue("criterion", "not a criterion of the protocol"))
            else:
                qualified = f"{protocol.protocol_id}:{criterion}"
        if issues:
            raise FactoryValidationError(issues)
        try:
            payload = CalibrationLabelled(
                work_id=work_id, verdict=verdict, criterion=qualified, channel=channel, stage=stage
            )
        except ValidationError as exc:
            raise FactoryValidationError(_issues(exc)) from exc
        event = project.events.make("calibration.labelled", payload, actor)
        project.record([event])
    return event.id


def calibration_items(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> list[str]:
    """The work ids of the drawn calibration set of `stage`, sorted; empty before the draw."""
    require_pass_stage(stage)
    project.index.sync()
    return _drawn_items(project, stage)


def calibration_labels(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> dict[str, str]:
    """The live human label per labelled calibration work of `stage` (`include` or `exclude`);
    empty when none is labelled."""
    require_pass_stage(stage)
    project.index.sync()
    return _labels(project, stage)


def calibration_drawn(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> bool:
    """Whether the calibration set of `stage` has been drawn, even if the draw was empty."""
    require_pass_stage(stage)
    project.index.sync()
    return _was_drawn(project, stage)


def sensitivity_threshold(project: Project) -> float | None:
    """The minimum sensitivity a pass must reach on the set; `None` when there is no gate."""
    mode = _rigor_mode(project)
    if enforcement(mode, "screening.calibration_sensitivity") is Enforcement.OFF:
        return None
    return CALIBRATION_SENSITIVITY[mode]


def calibration_status(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> CalibrationStatus:
    """The calibration set's progress and each pass's rates and gate at `stage`, under the current
    protocol. The gate's threshold is the mode's, at either stage."""
    require_pass_stage(stage)
    project.index.sync()
    threshold = sensitivity_threshold(project)
    items = _drawn_items(project, stage)
    labels = _labels(project, stage)
    protocol = current_protocol(project)
    decided = _live_decisions(project, None if protocol is None else protocol.protocol_id, stage)
    per_pass: dict[str, Rates] = {}
    passed: dict[str, bool] = {}
    for label in (PassLabel.A, PassLabel.B):
        key = label.value
        pass_decided = decided.get(key, {})
        pairs = [
            (labels[item] == "include", pass_decided[item])
            for item in items
            if item in labels and item in pass_decided
        ]
        rates = sensitivity_specificity(pairs)
        per_pass[key] = rates
        complete = all(item in labels and item in pass_decided for item in items)
        clears = threshold is None or (
            rates.sensitivity is not None and rates.sensitivity >= threshold
        )
        passed[key] = (complete and clears) or uncalibrated_human(project, label, stage)
    return CalibrationStatus(
        drawn=len(items),
        labelled=sum(1 for item in items if item in labels),
        required=threshold is not None,
        per_pass=per_pass,
        passed=passed,
    )


def uncalibrated_human(project: Project, label: PassLabel, stage: ScreeningStage) -> bool:
    """Whether pass `label` of `stage` is a human pass the plan does not calibrate."""
    return "human" in passes.pass_kinds(project, label, stage) and not humans_calibrated(
        project, stage
    )


def humans_calibrated(project: Project, stage: ScreeningStage) -> bool:
    """Whether the plan of `stage` sets `calibrate_humans`; False while there is no plan."""
    protocol = current_protocol(project)
    if protocol is None:
        return False
    try:
        return screening_plan(protocol, stage).calibrate_humans
    except FactoryValidationError:  # full text with no declared plan
        return False


def calibrated_models(
    project: Project, label: PassLabel, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> set[str]:
    """The models that recorded a calibration decision for pass `label` at `stage`, under the
    current protocol lineage and since the last criterion-changing amendment: the models the
    pass's gate was measured on. Empty before any calibration decision."""
    require_pass_stage(stage)
    project.index.sync()
    protocol = current_protocol(project)
    if protocol is None:
        return set()
    versions = lineage_through(project, protocol.protocol_id)
    cut = last_criterion_change(project, stage=stage)
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT d.protocol_id, d.event_id, e.model FROM decisions d"
                " JOIN events e ON e.id = d.event_id WHERE d.phase = :phase AND d.stage = :stage"
                " AND d.pass_label = :label AND e.model IS NOT NULL"
            ),
            {
                "phase": ScreeningPhase.CALIBRATION.value,
                "stage": stage.value,
                "label": label.value,
            },
        ).all()
    return {
        str(model)
        for version, event_id, model in rows
        if str(version) in versions and (cut is None or str(event_id) > cut)
    }


def recorded_population(project: Project, stage: ScreeningStage) -> set[str]:
    """`stage_population` with the absorbed records kept: the works whose recorded decisions still
    read as outcomes, so `merge-verdict-conflict` keeps reporting them."""
    return _stage_works(project, require_pass_stage(stage))


def _calibration_population(project: Project, stage: ScreeningStage) -> set[str]:
    """The works a calibration set of `stage` is drawn from: `_stage_works` less the records an
    active merge absorbed, which a reverted merge returns."""
    return _stage_works(project, stage) - absorbed_ids(project)


def _stage_works(project: Project, stage: ScreeningStage) -> set[str]:
    """The corpus at title/abstract; at full text, the works whose title/abstract final outcome is
    INCLUDED and that have a converted live document (the eligible works of `fulltext_queue`)."""
    corpus = _corpus_ids(project)
    if stage is ScreeningStage.TITLE_ABSTRACT:
        return corpus
    from factory.services.fulltext_screening import fulltext_queue  # circular at import time

    return {entry.work_id for entry in fulltext_queue(project).eligible} & corpus


def stage_population(project: Project, stage: ScreeningStage) -> set[str]:
    """The works that `stage` screens: the corpus at title/abstract, the promoted works at full
    text, less the absorbed records of active merges (screening one decides nothing: outcomes are
    read from the primary). Calibration and the passes' queues are drawn from it."""
    return _calibration_population(project, require_pass_stage(stage))


def _nothing_held_out(project: Project, protocol: ProtocolVersion | None) -> bool:
    """A library-only protocol with no seed: the split would hold nothing out (PD-3)."""
    return (
        protocol is not None
        and library_only(protocol.spec, _rigor_mode(project))
        and not all_seeds(project)
    )


def _select(project: Project, seed: int, stage: ScreeningStage) -> list[str]:
    """The calibration set for a seed: fixed seed works, then seeded random works of the stage's
    population."""
    corpus = _calibration_population(project, stage)
    held_out = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT and s.work_id}
    examples = {v.work_id for v in worked_examples(project) if v.work_id is not None}
    fixed = {
        s.work_id
        for s in agent_seeds(project)
        if s.work_id is not None and s.work_id in corpus and s.work_id not in examples
    }
    need = max(0, _calibration_size(project, stage) - len(fixed))
    pool = sorted(corpus - held_out - examples - fixed)
    rng = random.Random(seed)
    return sorted(fixed | set(rng.sample(pool, min(need, len(pool)))))


def _calibration_size(project: Project, stage: ScreeningStage) -> int:
    protocol = current_protocol(project)
    if protocol is None:
        return _DEFAULT_CALIBRATION_SIZE
    return screening_plan(protocol, stage).calibration_size


def _corpus_ids(project: Project) -> set[str]:
    return corpus_work_ids(project)  # ids only: no work record is parsed


def _by_number(seeds: Iterable[SeedView]) -> list[SeedView]:
    """Seeds in numeric id order (`SEED02` before `SEED10`)."""
    return sorted(seeds, key=lambda s: (_number(s.seed_id), s.seed_id))


def _number(seed_id: str) -> int:
    return int(seed_id.lstrip(ascii_uppercase))


def _was_drawn(project: Project, stage: ScreeningStage) -> bool:
    """Whether a `calibration.drawn` event of `stage` exists, even an empty draw. Read from the
    `calibration_draws` flag of the projection (a slice-1 event without `stage` is a
    title/abstract draw)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM calibration_draws WHERE stage = :stage"), {"stage": stage.value}
        ).one_or_none()
    return row is not None


def _drawn_items(project: Project, stage: ScreeningStage) -> list[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id FROM calibration_items WHERE stage = :stage ORDER BY work_id"),
            {"stage": stage.value},
        ).all()
    return [str(row[0]) for row in rows]


def _labels(project: Project, stage: ScreeningStage) -> dict[str, str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id, verdict FROM calibration_labels WHERE stage = :stage"),
            {"stage": stage.value},
        ).all()
    return {str(work_id): str(verdict) for work_id, verdict in rows}


def _live_decisions(
    project: Project, protocol_id: str | None, stage: ScreeningStage
) -> dict[str, dict[str, bool]]:
    """Promotion of the live calibration decision per pass and work of `stage`, made under
    `protocol_id` or an earlier version of its lineage (decision 50), and recorded after the
    latest criterion-changing amendment.

    Calibration measures the passes against the criteria (R-26), so any such amendment, a
    clarification included (slice-1 behaviour kept), requires the gate to be passed again. Every
    stale rule comes from a criterion change, so the cut subsumes them. A decision superseded by
    a later one is not live; the latest live decision per work wins.
    """
    if protocol_id is None:
        return {}
    versions = lineage_through(project, protocol_id)
    cut = last_criterion_change(project, stage=stage)
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT pass_label, work_id, verdict, protocol_id, event_id "
                "FROM decisions WHERE phase = :phase AND stage = :stage "
                "AND superseded_by IS NULL ORDER BY event_id"
            ),
            {"phase": ScreeningPhase.CALIBRATION.value, "stage": stage.value},
        ).all()
    decided: dict[str, dict[str, bool]] = {}
    for pass_label, work_id, verdict, version, event_id in rows:
        if str(version) in versions and (cut is None or str(event_id) > cut):
            decided.setdefault(str(pass_label), {})[str(work_id)] = Verdict(str(verdict)).promotes
    return decided


def is_pass_session(project: Project, session: str, *, stage: ScreeningStage | None = None) -> bool:
    """Whether the session has joined a screening pass at `stage`; at any stage when None."""
    return passes.is_pass_session(project, session, module="screening", stage=stage)


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(".".join(str(part) for part in err["loc"]) or "label", str(err["msg"]))
        for err in exc.errors()
    ]
