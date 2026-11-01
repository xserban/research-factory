"""The calibration set: drawn once, labelled by a human, and the per-pass gate on it (R-20, R-35).

`draw_calibration` picks the set from the resolved development seeds that are not worked examples,
the resolved negative seeds that are not worked examples, and seeded random corpus works up to the
protocol's `calibration_size`. Held-out seeds and their works are never chosen, not even as random
fill, and neither are worked examples (an agent has seen them). The split must be drawn first.

`label_calibration` records a human's label on an item of the set. The criterion is given bare and
qualified against the current protocol. An MCP-relayed label is refused from a session that has
joined a pass, so a screener cannot read the answer key.

`calibration_status` reports, per pass, the sensitivity and specificity of its live calibration
decisions under the current protocol version, and whether the pass has passed: every item is
labelled, the pass decided every item, and sensitivity reaches the mode's threshold (if any).
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
from factory.model.protocol import ScreeningPlan
from factory.model.screening import (
    CalibrationDrawn,
    CalibrationLabelled,
    Channel,
    PassLabel,
    ScreeningPhase,
    Verdict,
)
from factory.model.seed import SeedKind
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.screening_stats import CALIBRATION_SENSITIVITY, Rates, sensitivity_specificity
from factory.services.search import list_works
from factory.services.seeds import (
    SeedRole,
    SeedView,
    _rigor_mode,
    agent_seeds,
    all_seeds,
    split_is_drawn,
)

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
    project: Project, actor: Actor, *, random_seed: int | None = None
) -> list[str]:
    """Draw the calibration set once and return its work ids, sorted.

    A second call returns the existing set and writes nothing. The default seed is 32 random
    bits. Refused when the hold-out split has not been drawn, since the set must exclude
    held-out works. The protocol's `calibration_size` sets the size when the corpus allows.
    """
    seed = secrets.randbits(32) if random_seed is None else random_seed
    with project.index.exclusive():
        project.index.sync()
        if _was_drawn(project):
            return _drawn_items(project)
        issues: list[ValidationIssue] = []
        if not 0 <= seed < 2**32:
            issues.append(ValidationIssue("random_seed", "must be an integer from 0 to 2**32 - 1"))
        if not split_is_drawn(project):
            issues.append(ValidationIssue("split", "draw the seed split before the calibration"))
        if issues:
            raise FactoryValidationError(issues)

        items = _select(project, seed)
        protocol = current_protocol(project)
        payload = CalibrationDrawn(
            protocol_id=None if protocol is None else protocol.protocol_id,
            work_ids=tuple(items),
            random_seed=seed,
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
) -> str:
    """Record a human's label on one item of the calibration set and return the event id.

    Refused, with nothing written, when the actor is not human, the work is not in the set, the
    criterion is not in the current protocol, the verdict or criterion does not fit, or the
    label is relayed over MCP from a session that has joined a pass.
    """
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "calibration labels are human acts"))
        if work_id not in _drawn_items(project):
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
        if channel is Channel.MCP and is_pass_session(project, actor.session):
            issues.append(ValidationIssue("channel", "this session has joined a pass"))
        if issues:
            raise FactoryValidationError(issues)
        try:
            payload = CalibrationLabelled(
                work_id=work_id, verdict=verdict, criterion=qualified, channel=channel
            )
        except ValidationError as exc:
            raise FactoryValidationError(_issues(exc)) from exc
        event = project.events.make("calibration.labelled", payload, actor)
        project.record([event])
    return event.id


def calibration_items(project: Project) -> list[str]:
    """The work ids of the drawn calibration set, sorted; empty before the draw."""
    project.index.sync()
    return _drawn_items(project)


def calibration_labels(project: Project) -> dict[str, str]:
    """The live human label per labelled calibration work (`include` or `exclude`); empty when none
    is labelled."""
    project.index.sync()
    return _labels(project)


def calibration_drawn(project: Project) -> bool:
    """Whether the calibration set has been drawn, even when the draw yielded no items."""
    project.index.sync()
    return _was_drawn(project)


def sensitivity_threshold(project: Project) -> float | None:
    """The minimum sensitivity a pass must reach on the set; `None` when there is no gate."""
    return CALIBRATION_SENSITIVITY[_rigor_mode(project)]


def calibration_status(project: Project) -> CalibrationStatus:
    """The calibration set's progress and each pass's rates and gate under the current protocol."""
    project.index.sync()
    threshold = sensitivity_threshold(project)
    items = _drawn_items(project)
    labels = _labels(project)
    protocol = current_protocol(project)
    decided = _live_decisions(project, None if protocol is None else protocol.protocol_id)
    per_pass: dict[str, Rates] = {}
    passed: dict[str, bool] = {}
    for label in (PassLabel.A, PassLabel.B):
        key = label.value
        passes = decided.get(key, {})
        pairs = [
            (labels[item] == "include", passes[item])
            for item in items
            if item in labels and item in passes
        ]
        rates = sensitivity_specificity(pairs)
        per_pass[key] = rates
        complete = all(item in labels and item in passes for item in items)
        clears = threshold is None or (
            rates.sensitivity is not None and rates.sensitivity >= threshold
        )
        passed[key] = complete and clears
    return CalibrationStatus(
        drawn=len(items),
        labelled=sum(1 for item in items if item in labels),
        required=threshold is not None,
        per_pass=per_pass,
        passed=passed,
    )


def _select(project: Project, seed: int) -> list[str]:
    """The calibration set for a seed: fixed seed works, then seeded random corpus works."""
    corpus = _corpus_ids(project)
    held_out = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT and s.work_id}
    examples = {v.work_id for v in worked_examples(project) if v.work_id is not None}
    fixed = {
        s.work_id
        for s in agent_seeds(project)
        if s.work_id is not None and s.work_id in corpus and s.work_id not in examples
    }
    need = max(0, _calibration_size(project) - len(fixed))
    pool = sorted(corpus - held_out - examples - fixed)
    rng = random.Random(seed)
    return sorted(fixed | set(rng.sample(pool, min(need, len(pool)))))


def _calibration_size(project: Project) -> int:
    protocol = current_protocol(project)
    if protocol is None:
        return _DEFAULT_CALIBRATION_SIZE
    return protocol.spec.screening.calibration_size


def _corpus_ids(project: Project) -> set[str]:
    return {work.id for work in list_works(project)}


def _by_number(seeds: Iterable[SeedView]) -> list[SeedView]:
    """Seeds in numeric id order (`SEED02` before `SEED10`)."""
    return sorted(seeds, key=lambda s: (_number(s.seed_id), s.seed_id))


def _number(seed_id: str) -> int:
    return int(seed_id.lstrip(ascii_uppercase))


def _was_drawn(project: Project) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM events WHERE type = 'calibration.drawn' LIMIT 1")
        ).one_or_none()
    return row is not None


def _drawn_items(project: Project) -> list[str]:
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT work_id FROM calibration_items ORDER BY work_id")).all()
    return [str(row[0]) for row in rows]


def _labels(project: Project) -> dict[str, str]:
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT work_id, verdict FROM calibration_labels")).all()
    return {str(work_id): str(verdict) for work_id, verdict in rows}


def _live_decisions(project: Project, protocol_id: str | None) -> dict[str, dict[str, bool]]:
    """Promotion of the live calibration decision per pass and work, under one protocol version.

    A decision superseded by a later one is not live; the latest live decision per work wins.
    """
    if protocol_id is None:
        return {}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT pass_label, work_id, verdict FROM decisions "
                "WHERE phase = :phase AND protocol_id = :protocol "
                "AND superseded_by IS NULL ORDER BY event_id"
            ),
            {"phase": ScreeningPhase.CALIBRATION.value, "protocol": protocol_id},
        ).all()
    decided: dict[str, dict[str, bool]] = {}
    for pass_label, work_id, verdict in rows:
        decided.setdefault(str(pass_label), {})[str(work_id)] = Verdict(str(verdict)).promotes
    return decided


def is_pass_session(project: Project, session: str) -> bool:
    """Whether the session has joined a screening pass."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pass_sessions WHERE session = :session"), {"session": session}
        ).one_or_none()
    return row is not None


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(".".join(str(part) for part in err["loc"]) or "label", str(err["msg"]))
        for err in exc.errors()
    ]
