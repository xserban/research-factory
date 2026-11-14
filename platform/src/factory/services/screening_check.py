"""Checks of the screener by a person: band checks, the tuning loop, measurement (H2).

*Band check.* `draw_band_check` draws, from the live screening decisions of one pass, a stratified
sample by relevance score: the band limits, the number per band and the seed are recorded in the
`check.drawn` event, so the sample is reproducible. Decisions without a score form their own band
(`unscored`); a score that falls in no band is not drawn. A person labels each record include or
exclude (`check_label`), blind to the agent's verdict; `check_report` then gives, per band, the
agreement and the records the person would add (agent excluded, person included, and the reverse).

*Tuning loop.* `draw_tuning_batch` draws records the agent has not screened; ranked and unranked
serving put them first (`tuning_priority`). After the person has labelled them, `add_tuning_example`
turns one disagreement into an example of a criterion: a protocol amendment that adds an
`ExampleCase` (a one-line text for the screener, and the work id only for tracing).
`draw_measurement_batch` draws a fresh batch that excludes every tuning record, every example
record, every worked-example seed, the calibration set, every record any pass has decided, every
earlier batch and every held-out seed work; it records the latest example change, and agreement is
reported only on a measurement batch that is still current (no example changed since the draw).

Invariants:
- Draws and labels are human acts. Refusals raise FactoryValidationError and write nothing.
- Held-out seed works are never drawn into a tuning or measurement batch (R-20, as calibration).
- A measurement batch never shares a record with a tuning batch or an example (checked again after
  the draw); a measurement draw is refused while a tuning batch has unlabelled records.
- Counts and rates are computed here, never supplied.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Literal, TypeVar

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.protocol import Criterion, CriterionExamples, ExampleCase, ScreeningStage
from factory.model.screening import Channel, DecisionRecorded, PassLabel, ScreeningPhase, Verdict
from factory.model.screening_check import (
    DEFAULT_BANDS,
    DEFAULT_MEASUREMENT_SIZE,
    DEFAULT_PER_BAND,
    DEFAULT_TUNING_SIZE,
    UNSCORED,
    CheckDrawn,
    CheckItem,
    CheckKind,
    CheckLabelled,
    ScoreBand,
)
from factory.services import audit_core, passes
from factory.services.calibration import calibration_items, stage_population, worked_examples
from factory.services.context import Project
from factory.services.human_channel import require_human_channel
from factory.services.protocol import (
    AmendResult,
    amend_protocol,
    amendments_with_events,
    current_protocol,
)
from factory.services.screening import live_decisions
from factory.services.search import list_works
from factory.services.seeds import SeedRole, all_seeds
from factory.services.stages import require_pass_stage
from factory.services.work_ref import resolve_work_id

TA = ScreeningStage.TITLE_ABSTRACT
_T = TypeVar("_T")
MAX_EXAMPLE_TEXT = 400


class BandRow(StrictModel):
    """One stratum of a draw. `agreement` is None where it is not reported or nothing is
    comparable; `would_add_includes` counts records the agent excluded and the person included,
    `would_add_excludes` the reverse; `undecided` counts labelled records the agent has not
    decided or was unsure about."""

    band: str
    drawn: int
    labelled: int
    compared: int
    agreed: int
    agreement: float | None
    would_add_includes: int
    would_add_excludes: int
    undecided: int


class CheckDisagreement(StrictModel):
    work_id: str
    title: str
    band: str
    agent_verdict: Literal["include", "exclude"]
    human_verdict: Literal["include", "exclude"]
    score: int | None
    rationale: str


class ScreenCheckReport(StrictModel):
    draw_id: str
    kind: CheckKind
    stage: ScreeningStage
    pass_label: PassLabel
    name: str | None
    random_seed: int
    bands: list[ScoreBand]
    per_band: int | None
    drawn: int
    labelled: int
    rows: list[BandRow]
    agreement: float | None
    agreement_note: str | None
    current: bool
    disagreements: list[CheckDisagreement]


class CheckSummary(StrictModel):
    draw_id: str
    kind: CheckKind
    name: str | None
    drawn: int
    labelled: int
    current: bool


# --- Draws ---


def parse_bands(value: str) -> tuple[ScoreBand, ...]:
    """Bands from `1-3,4-7,8-10`; a lone number is a band of one score."""
    bands: list[ScoreBand] = []
    for part in value.split(","):
        low, _, high = part.strip().partition("-")
        try:
            bands.append(ScoreBand(low=int(low), high=int(high or low)))
        except (ValueError, TypeError):
            raise FactoryValidationError(
                [ValidationIssue("bands", "write bands as 1-3,4-7,8-10 (scores 1..10)")]
            ) from None
    return tuple(bands)


def draw_band_check(
    project: Project,
    actor: Actor,
    *,
    stage: ScreeningStage = TA,
    pass_label: PassLabel = PassLabel.A,
    bands: Sequence[ScoreBand] = DEFAULT_BANDS,
    per_band: int = DEFAULT_PER_BAND,
    random_seed: int | None = None,
) -> CheckDrawn:
    """Draw and record a band check of the live screening decisions of `pass_label` at `stage`.

    Each band (and `unscored`) contributes `per_band` records, or all it has; records drawn in an
    earlier band check of the same pass are left out. Refused, with nothing written, for a non-human
    actor, a member of a pass on a hosted project, a seed out of range, bands that are malformed or
    overlap, or a pass with no decision to draw from."""
    require_pass_stage(stage)
    seed, seed_issues = audit_core.validate_seed(random_seed)
    with project.writing():
        project.index.sync()
        passes.require_outside_passes(project, actor.user, stage)
        issues = audit_core.human_gate(project, actor, Channel.CLI, noun="sample")
        issues.extend(seed_issues)
        if per_band < 1:
            issues.append(ValidationIssue("per_band", "must be at least 1"))
        if issues:
            raise FactoryValidationError(issues)
        scored = {
            d.work_id: d.score
            for d in live_decisions(project, pass_label, stage=stage)
            if d.phase is ScreeningPhase.SCREENING
        }
        if not scored:
            raise _refuse("pass", f"pass {pass_label.value} has no screening decision to draw from")
        earlier = _drawn_works(project, CheckKind.BAND, stage, pass_label)
        strata: list[tuple[str, list[str]]] = [
            (
                band.label,
                sorted(w for w, s in scored.items() if s is not None and band.holds(s)),
            )
            for band in bands
        ]
        strata.append((UNSCORED, sorted(w for w, s in scored.items() if s is None)))
        rng = random.Random(seed)
        items: dict[str, str] = {}
        for label, pool in strata:
            fresh = [w for w in pool if w not in earlier and w not in items]
            for work in rng.sample(fresh, min(per_band, len(fresh))):
                items[work] = label
        payload = _make(
            lambda: CheckDrawn(
                draw_id=project.ids.new("chk"),
                kind=CheckKind.BAND,
                stage=stage,
                pass_label=pass_label,
                random_seed=seed,
                items=tuple(CheckItem(work_id=w, band=items[w]) for w in sorted(items)),
                bands=tuple(bands),
                per_band=per_band,
            )
        )
        project.record([project.events.make("check.drawn", payload, actor)])
    return payload


def draw_tuning_batch(
    project: Project,
    actor: Actor,
    *,
    stage: ScreeningStage = TA,
    size: int = DEFAULT_TUNING_SIZE,
    name: str | None = None,
    random_seed: int | None = None,
) -> CheckDrawn:
    """Draw a named tuning batch of `size` fresh records for the agent to screen before main
    screening. See `_fresh_pool` for what is left out. Refused for a non-human actor, a bad seed or
    size, or when no fresh record remains."""
    return _draw_fresh(CheckKind.TUNING, project, actor, stage, size, name, random_seed)


def draw_measurement_batch(
    project: Project,
    actor: Actor,
    *,
    stage: ScreeningStage = TA,
    size: int = DEFAULT_MEASUREMENT_SIZE,
    name: str | None = None,
    random_seed: int | None = None,
) -> CheckDrawn:
    """Draw a measurement batch: fresh records that overlap no tuning batch and no example, drawn
    after the last example change (which the event records). Refused while a tuning batch has
    unlabelled records, and for the reasons of `draw_tuning_batch`."""
    return _draw_fresh(CheckKind.MEASUREMENT, project, actor, stage, size, name, random_seed)


def _draw_fresh(
    kind: CheckKind,
    project: Project,
    actor: Actor,
    stage: ScreeningStage,
    size: int,
    name: str | None,
    random_seed: int | None,
) -> CheckDrawn:
    require_pass_stage(stage)
    seed, seed_issues = audit_core.validate_seed(random_seed)
    with project.writing():
        project.index.sync()
        passes.require_outside_passes(project, actor.user, stage)
        issues = audit_core.human_gate(project, actor, Channel.CLI, noun="sample")
        issues.extend(seed_issues)
        if size < 1:
            issues.append(ValidationIssue("size", "must be at least 1"))
        if kind is CheckKind.MEASUREMENT:
            unlabelled = _unlabelled_tuning(project, stage)
            if unlabelled:
                issues.append(
                    ValidationIssue(
                        "tuning",
                        f"a tuning batch has {unlabelled} unlabelled record(s); check it first",
                    )
                )
        if issues:
            raise FactoryValidationError(issues)
        pool = sorted(_fresh_pool(project, stage))
        if not pool:
            raise _refuse("pool", "no fresh record remains to draw")
        drawn = sorted(random.Random(seed).sample(pool, min(size, len(pool))))
        if kind is CheckKind.MEASUREMENT:
            overlap = set(drawn) & (
                _drawn_works(project, CheckKind.TUNING, stage) | _example_works(project)
            )
            if overlap:  # unreachable: the pool excludes them
                raise _refuse("pool", "a measurement batch must not overlap a tuning batch")
        payload = _make(
            lambda: CheckDrawn(
                draw_id=project.ids.new("chk"),
                kind=kind,
                stage=stage,
                pass_label=PassLabel.A,
                random_seed=seed,
                items=tuple(CheckItem(work_id=w) for w in drawn),
                name=name,
                last_example_change=last_example_change(project),
            )
        )
        project.record([project.events.make("check.drawn", payload, actor)])
    return payload


def _fresh_pool(project: Project, stage: ScreeningStage) -> set[str]:
    """Records an agent has not seen and a measurement may use: the stage population less
    held-out seed works (as calibration), the calibration set, worked-example seeds, example
    records, every record either pass has decided, and every record of an earlier tuning or
    measurement batch."""
    held_out = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT and s.work_id}
    seen = {v.work_id for v in worked_examples(project) if v.work_id is not None}
    decided = {d.work_id for d in live_decisions(project, None, stage=stage)}
    return (
        stage_population(project, stage)
        - held_out
        - seen
        - set(calibration_items(project, stage=stage))
        - decided
        - _example_works(project)
        - _drawn_works(project, CheckKind.TUNING, stage)
        - _drawn_works(project, CheckKind.MEASUREMENT, stage)
    )


def tuning_priority(project: Project, stage: ScreeningStage) -> set[str]:
    """The records of tuning and measurement batches, which serving puts first (they are screened
    before the main queue, so a measurement is not left behind a stop rule; pilot 2026-11-07).
    Reads the index only."""
    return _drawn_works(project, CheckKind.TUNING, stage) | _drawn_works(
        project, CheckKind.MEASUREMENT, stage
    )


# --- Labels ---


def check_label(
    project: Project,
    actor: Actor,
    draw_id: str,
    work_id: str,
    verdict: str,
    channel: Channel,
) -> str:
    """Record a person's include/exclude label on a drawn record; return the event id.

    Refused, with nothing written, for a non-human actor, an unknown draw, a record outside the
    draw, a verdict other than include or exclude, an MCP relay from a session that has joined a
    pass, or a member of a pass of the draw's stage on a hosted project."""
    with project.writing():
        project.index.sync()
        require_human_channel(project, actor, channel, "audit-label")
        work_id = resolve_work_id(project, work_id)
        issues = audit_core.human_gate(
            project, actor, channel, noun="screening-label", gate_id="screening.audit_label"
        )
        row = _draw_row(project, draw_id)
        stage = TA
        if row is None:
            issues.append(ValidationIssue("draw_id", "unknown draw"))
        else:
            stage = ScreeningStage(row["stage"])
            passes.require_outside_passes(project, actor.user, stage)
            if work_id not in _items(project, draw_id):
                issues.append(ValidationIssue("work_id", "not in this draw"))
        if issues:
            raise FactoryValidationError(issues)
        payload = _make(
            lambda: CheckLabelled(
                draw_id=draw_id,
                work_id=work_id,
                verdict=verdict,
                channel=channel,
                stage=stage,
            )
        )
        event = project.events.make("check.labelled", payload, actor)
        project.record([event])
    return event.id


def unlabelled_works(project: Project, draw_id: str) -> list[str]:
    """The records of a draw without a label, sorted."""
    project.index.sync()
    labelled = _labels(project, draw_id)
    return [w for w in _items(project, draw_id) if w not in labelled]


# --- Examples ---


def add_tuning_example(
    project: Project,
    actor: Actor,
    draw_id: str,
    work_id: str,
    criterion: str,
    example_text: str,
    channel: Channel,
) -> AmendResult:
    """Turn one disagreement of a tuning batch into an example of `criterion`, by a protocol
    amendment that adds an `ExampleCase` (its kind is the person's label).

    `example_text` is what the screener sees: a title and a one-line reason, with no work id. The
    work id and the draw are kept beside it for tracing, and the record leaves every later
    measurement. Refused, with nothing written, for a non-human actor, a draw that is not a tuning
    batch, a record the person has not labelled or the agent has not decided, a record on which
    they agree, a held-out seed work, a record already an example, an unknown criterion, or a text
    that is empty, multi-line, too long or names the work id."""
    with project.writing():
        project.index.sync()
        require_human_channel(project, actor, channel, "audit-label")
        work_id = resolve_work_id(project, work_id)
        issues = audit_core.human_gate(
            project, actor, channel, noun="screening-label", gate_id="screening.audit_label"
        )
        protocol = current_protocol(project)
        row = _draw_row(project, draw_id)
        line = example_text.strip()
        if protocol is None:
            issues.append(ValidationIssue("protocol", "record a protocol first"))
        if row is None or row["kind"] != CheckKind.TUNING.value:
            issues.append(ValidationIssue("draw_id", "not a tuning batch"))
        elif work_id not in _items(project, draw_id):
            issues.append(ValidationIssue("work_id", "not in this tuning batch"))
        if not line or "\n" in line or len(line) > MAX_EXAMPLE_TEXT:
            issues.append(
                ValidationIssue(
                    "text", f"one non-empty line of at most {MAX_EXAMPLE_TEXT} characters"
                )
            )
        if work_id in line:
            issues.append(ValidationIssue("text", "must not contain the work id"))
        if issues or protocol is None or row is None:
            raise FactoryValidationError(issues)
        stage = ScreeningStage(row["stage"])
        label = _labels(project, draw_id).get(work_id)
        agent = _agent_side(_decisions(project, PassLabel(row["pass_label"]), stage).get(work_id))
        if label is None:
            issues.append(ValidationIssue("work_id", "the person has not labelled this record"))
        elif agent is None:
            issues.append(ValidationIssue("work_id", "the agent has not decided this record"))
        elif agent == label:
            issues.append(ValidationIssue("work_id", "the agent and the person agree"))
        if work_id in {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT}:
            issues.append(ValidationIssue("work_id", "a held-out seed work is never an example"))
        if work_id in _example_works(project):
            issues.append(ValidationIssue("work_id", "already an example"))
        target = next((c for c in protocol.spec.criteria if c.id == criterion), None)
        if target is None:
            issues.append(ValidationIssue("criterion", "not a criterion of the protocol"))
        if issues or target is None or label is None:
            raise FactoryValidationError(issues)
        case = ExampleCase(work_id=work_id, text=line, source=draw_id)
        examples = target.examples
        if label == "include":
            grown = examples.model_copy(update={"include_cases": (*examples.include_cases, case)})
        else:
            grown = examples.model_copy(update={"exclude_cases": (*examples.exclude_cases, case)})
        spec = protocol.spec.model_copy(
            update={
                "criteria": tuple(
                    _with_examples(c, grown) if c.id == criterion else c
                    for c in protocol.spec.criteria
                )
            }
        )
        return amend_protocol(
            project,
            actor,
            spec,
            reason=f"{label} example for {criterion} from tuning batch {draw_id}",
            semantic=False,
            effects={},
        )


def _with_examples(criterion: Criterion, examples: CriterionExamples) -> Criterion:
    return criterion.model_copy(update={"examples": examples})


def example_works(project: Project) -> set[str]:
    """Every work that is, or ever was, an example case of a criterion."""
    project.index.sync()
    return _example_works(project)


def _example_works(project: Project) -> set[str]:
    specs = [amendment.spec for _, amendment in amendments_with_events(project)]
    protocol = current_protocol(project)
    if protocol is not None:
        specs.append(protocol.spec)
    return {
        case.work_id
        for spec in specs
        for criterion in spec.criteria
        for case in (*criterion.examples.include_cases, *criterion.examples.exclude_cases)
    }


def last_example_change(project: Project) -> str | None:
    """The event of the latest amendment that changed the set of example cases; None while no
    example case has been added. Read from the amendments, so an amendment made by any route
    (`protocol_amend` included) counts."""
    project.index.sync()
    previous: frozenset[tuple[str, str, str]] = frozenset()
    last: str | None = None
    for event_id, amendment in amendments_with_events(project):
        now = frozenset(
            (criterion.id, kind, case.work_id)
            for criterion in amendment.spec.criteria
            for kind, cases in (
                ("include", criterion.examples.include_cases),
                ("exclude", criterion.examples.exclude_cases),
            )
            for case in cases
        )
        if now != previous:
            last = event_id
        previous = now
    return last


def example_texts(criterion: Criterion) -> list[str]:
    """The example lines a screener sees for `criterion`: no work ids."""
    return [f"include: {c.text}" for c in criterion.examples.include_cases] + [
        f"exclude: {c.text}" for c in criterion.examples.exclude_cases
    ]


# --- Reports ---


def check_list(project: Project, *, stage: ScreeningStage = TA) -> list[CheckSummary]:
    """Every draw of `stage`, oldest first."""
    require_pass_stage(stage)
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT draw_id FROM check_draws WHERE stage = :s ORDER BY event_id"),
            {"s": stage.value},
        ).all()
    out: list[CheckSummary] = []
    for (draw_id,) in rows:
        draw = _draw(project, str(draw_id))
        if draw is not None:
            out.append(
                CheckSummary(
                    draw_id=draw.draw_id,
                    kind=draw.kind,
                    name=draw.name,
                    drawn=len(draw.items),
                    labelled=len(_labels(project, draw.draw_id)),
                    current=_current(project, draw),
                )
            )
    return out


def check_report(
    project: Project,
    draw_id: str | None = None,
    *,
    kind: CheckKind = CheckKind.BAND,
    stage: ScreeningStage = TA,
) -> ScreenCheckReport | None:
    """The report of a draw (the latest of `kind` at `stage` when `draw_id` is None); None when
    there is none. Agreement is reported for a band check and for a current measurement batch
    only: a tuning batch reports its disagreements, and a measurement batch drawn before the last
    example change says so instead of an agreement."""
    require_pass_stage(stage)
    project.index.sync()
    if draw_id is None:
        with project.index.connect() as conn:
            found = conn.execute(
                text(
                    "SELECT draw_id FROM check_draws WHERE kind = :k AND stage = :s "
                    "ORDER BY event_id DESC LIMIT 1"
                ),
                {"k": kind.value, "s": stage.value},
            ).one_or_none()
        if found is None:
            return None
        draw_id = str(found[0])
    draw = _draw(project, draw_id)
    if draw is None:
        return None
    labels = _labels(project, draw_id)
    decisions = _decisions(project, draw.pass_label, draw.stage)
    titles = {w.id: w.title for w in list_works(project)}
    current = _current(project, draw)
    reported = draw.kind is CheckKind.BAND or (draw.kind is CheckKind.MEASUREMENT and current)
    note: str | None = None
    if draw.kind is CheckKind.TUNING:
        note = "agreement is measured on a measurement batch only"
    elif not reported:
        note = "examples changed after this draw; draw a new measurement batch"
    strata = list(dict.fromkeys(item.band for item in draw.items))
    rows: list[BandRow] = []
    disagreements: list[CheckDisagreement] = []
    for stratum in strata:
        works = [item.work_id for item in draw.items if item.band == stratum]
        row_labels = {w: labels[w] for w in works if w in labels}
        compared = agreed = adds_in = adds_ex = undecided = 0
        for work, human in row_labels.items():
            decision = decisions.get(work)
            agent = _agent_side(decision)
            if agent is None or decision is None:
                undecided += 1
                continue
            compared += 1
            if agent == human:
                agreed += 1
                continue
            if human == "include":
                adds_in += 1
            else:
                adds_ex += 1
            disagreements.append(
                CheckDisagreement(
                    work_id=work,
                    title=titles.get(work, ""),
                    band=stratum,
                    agent_verdict=agent,
                    human_verdict=human,
                    score=decision.score,
                    rationale=decision.rationale,
                )
            )
        rows.append(
            BandRow(
                band=stratum,
                drawn=len(works),
                labelled=len(row_labels),
                compared=compared,
                agreed=agreed,
                agreement=agreed / compared if reported and compared else None,
                would_add_includes=adds_in,
                would_add_excludes=adds_ex,
                undecided=undecided,
            )
        )
    total_compared = sum(r.compared for r in rows)
    total_agreed = sum(r.agreed for r in rows)
    return ScreenCheckReport(
        draw_id=draw.draw_id,
        kind=draw.kind,
        stage=draw.stage,
        pass_label=draw.pass_label,
        name=draw.name,
        random_seed=draw.random_seed,
        bands=list(draw.bands),
        per_band=draw.per_band,
        drawn=len(draw.items),
        labelled=len(labels),
        rows=rows,
        agreement=total_agreed / total_compared if reported and total_compared else None,
        agreement_note=note,
        current=current,
        disagreements=disagreements,
    )


# --- Reading the index ---


def _agent_side(decision: DecisionRecorded | None) -> Literal["include", "exclude"] | None:
    """The side of an agent decision: include (include, cannot-assess) or exclude; None when
    there is none or it is unsure."""
    if decision is None or decision.verdict is Verdict.UNSURE:
        return None
    return "include" if decision.verdict.promotes else "exclude"


def _decisions(
    project: Project, label: PassLabel, stage: ScreeningStage
) -> dict[str, DecisionRecorded]:
    return {
        d.work_id: d
        for d in live_decisions(project, label, stage=stage)
        if d.phase is ScreeningPhase.SCREENING
    }


def _current(project: Project, draw: CheckDrawn) -> bool:
    """A measurement is current while no example changed since it was drawn; other kinds always."""
    if draw.kind is not CheckKind.MEASUREMENT:
        return True
    return draw.last_example_change == last_example_change(project)


def _draw_row(project: Project, draw_id: str) -> dict[str, str] | None:
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text("SELECT kind, stage, pass_label FROM check_draws WHERE draw_id = :d"),
                {"d": draw_id},
            )
            .mappings()
            .one_or_none()
        )
    return None if row is None else {k: str(v) for k, v in row.items()}


def _draw(project: Project, draw_id: str) -> CheckDrawn | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT payload FROM check_draws WHERE draw_id = :d"), {"d": draw_id}
        ).one_or_none()
    return None if row is None else CheckDrawn.model_validate_json(str(row[0]))


def _items(project: Project, draw_id: str) -> list[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id FROM check_items WHERE draw_id = :d ORDER BY work_id"),
            {"d": draw_id},
        ).all()
    return [str(r[0]) for r in rows]


def _labels(project: Project, draw_id: str) -> dict[str, Literal["include", "exclude"]]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id, verdict FROM check_labels WHERE draw_id = :d"), {"d": draw_id}
        ).all()
    return {str(w): ("include" if str(v) == "include" else "exclude") for w, v in rows}


def _drawn_works(
    project: Project,
    kind: CheckKind,
    stage: ScreeningStage,
    pass_label: PassLabel | None = None,
) -> set[str]:
    sql = (
        "SELECT i.work_id FROM check_items i JOIN check_draws d ON d.draw_id = i.draw_id "
        "WHERE d.kind = :k AND d.stage = :s"
    )
    params = {"k": kind.value, "s": stage.value}
    if pass_label is not None:
        sql += " AND d.pass_label = :p"
        params["p"] = pass_label.value
    with project.index.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    return {str(r[0]) for r in rows}


def _unlabelled_tuning(project: Project, stage: ScreeningStage) -> int:
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM check_items i "
                    "JOIN check_draws d ON d.draw_id = i.draw_id "
                    "LEFT JOIN check_labels l ON l.draw_id = i.draw_id AND l.work_id = i.work_id "
                    "WHERE d.kind = 'tuning' AND d.stage = :s AND l.verdict IS NULL"
                ),
                {"s": stage.value},
            ).scalar_one()
        )


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _make(build: Callable[[], _T]) -> _T:
    """Build a payload, turning a model refusal into issues on the offending fields."""
    try:
        return build()
    except ValidationError as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(".".join(str(p) for p in err["loc"]) or "draw", str(err["msg"]))
                for err in exc.errors()
            ]
        ) from exc
