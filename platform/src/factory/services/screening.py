"""Screening passes, their sessions, and the batches an agent screens (R-16, R-20, R-31, R-35).

Pass A tests every work against the inclusion criteria in protocol order. Pass B, under a two-pass
plan, tests a sample of works against the exclusion criteria in reverse order. Each pass is opened
once, with a seed that orders its batches and, for B, its sample.

A session joins one pass per stage. It is refused from the other pass of that stage, and from any
session that relayed a human label over MCP, since such a session could read the answer key
(ruling 1). A refusal raises FactoryValidationError and writes nothing.

A person joins as a human, holding `pass:join-human` (slice 5 ruling 15), once per stage: the pass
keeps that session, and every later act of theirs in the pass runs in it. `index.screening.
join_refusal` states who may join: a pass is all human or all agent, one person never screens both
passes in person, and on a hosted project the passes share no user (in person, a person and their
agent, or two agents of one person) and a stage's judges join neither. An unhosted project keeps
the slice-1 rule for agents, so one researcher can still run both agent passes.

Every function takes a keyword `stage` (default title/abstract); `either` is refused on field
`stage`. At full text the plan is `full_text_screening`, refused on field `full_text_screening`
until declared (R-13). Task kinds are `screen_a`/`screen_b` and `screen_ft_a`/`screen_ft_b`. The
full-text pass B draws its sample from the eligible works at open and extends it as more works
become eligible, as at title/abstract. A full-text batch pins, in each record, the conversion that
was the work's default when the task was created.

`screen_next` serves the next batch of a pass. While calibration is required and the pass has not
passed it, only calibration batches are served, and `blocked` says why ordinary batches wait. A
batch's content is its task's input blob: the text the agent saw, without the task id. A work is
queued once per phase: calibration works in calibration batches, the others in screening batches.
A work with a live, non-stale decision in the pass is not queued again.

`screen_record` writes the verdicts of a held batch. Invalid items are reported and not written; a
new decision supersedes the live one for the same work and pass, and the task completes once each
of its records has a live decision of its own.

A person screens through the same two functions, under the session of their join (`passes.
human_membership`), and is served the same framing, order and batches as an agent. `screen_next`
gives them back a batch they already hold. A human quote is verified when given, and required for
an exclusion in `systematic` only (R-110); at full text the anchor is required all the same.

Invariants:
- No batch carries a decision, a worked example's seed id, or a held-out work.
- Within a batch, records are shuffled with a generator seeded by the pass seed and the task's
  index, so the order is reproducible and independent of the sorted order.
"""

import json
import math
import random
import secrets
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Literal

from pydantic import JsonValue, SerializerFunctionWrapHandler, ValidationError, model_serializer
from sqlalchemy import text

from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.index.chase import considered_works, extended_works
from factory.index.screening import join_refusal
from factory.model.base import StrictModel
from factory.model.chase import SampleExtended
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolStatus, ScreeningPlan, ScreeningStage
from factory.model.screening import (
    Channel,
    DecisionRecorded,
    Framing,
    HumanScreeningItem,
    PassJoined,
    PassLabel,
    PassOpened,
    ScreeningItem,
    ScreeningPhase,
    Verdict,
)
from factory.model.seed import SeedKind
from factory.model.task import ReportedUsage, Task, TaskStatus
from factory.model.work import Work
from factory.model.work_ids import nfc_matches
from factory.services import passes
from factory.services.access import Permission, authorize
from factory.services.budgets import require_for, task_unit
from factory.services.calibration import (
    CalibrationStatus,
    calibrated_models,
    calibration_drawn,
    calibration_items,
    calibration_status,
    humans_calibrated,
    sensitivity_threshold,
    stage_population,
    worked_examples,
)
from factory.services.context import Principal, Project
from factory.services.conversions import resolve_anchor
from factory.services.dedup import dedup_current
from factory.services.members import _lab_of
from factory.services.passes import pass_users, require_outside_passes
from factory.services.protocol import (
    ProtocolVersion,
    amendments_with_events,
    current_protocol,
    last_criterion_change,
    protocol_lineage,
)
from factory.services.protocol_rules import DecisionRef, stale_decisions
from factory.services.ranked_queue import (
    StopStatus,
    rank_key,
    ranked_sequence,
    ranking_positions,
    score_status,
    stop_status,
    unreached,
)
from factory.services.results import BatchResult, ItemError
from factory.services.screening_stats import quote_in
from factory.services.search import list_works
from factory.services.seeds import _rigor_mode
from factory.services.stages import require_pass_stage, screening_plan, stage_of_kind, task_kind
from factory.services.tasks import (
    TaskSpec,
    build_task_events,
    claim_next,
    complete_task,
    require_holder,
    session_in_layer,
    task_content,
)

__all__ = ["pass_users", "require_outside_passes"]  # kept with the pass rules in `passes`

SCREEN_BATCH = 10
TA = ScreeningStage.TITLE_ABSTRACT
FT = ScreeningStage.FULL_TEXT

_FRAMING = {PassLabel.A: Framing.INCLUSION, PassLabel.B: Framing.EXCLUSION}
_CRITERION_ORDER: dict[PassLabel, Literal["protocol", "reversed"]] = {
    PassLabel.A: "protocol",
    PassLabel.B: "reversed",
}
_QUOTE_RULE = (
    " Quote the title or abstract span you rely on; do not use knowledge of the authors, "
    "venue or paper beyond this text."
)
INSTRUCTIONS: dict[Framing, str] = {
    Framing.INCLUSION: "For each record decide whether it meets every inclusion criterion. "
    "When in doubt, include." + _QUOTE_RULE,
    Framing.EXCLUSION: "For each record look for a reason to exclude it under the exclusion "
    "criteria. When in doubt, include." + _QUOTE_RULE,
}


_FT_QUOTE_RULE = (
    " Read each record's pinned conversion with document_read (its document_id and "
    "conversion_id), cite one anchor of that conversion, and quote verbatim from that anchor; "
    "do not use knowledge of the paper beyond that text."
)
FULLTEXT_INSTRUCTIONS: dict[Framing, str] = {
    Framing.INCLUSION: "For each record decide whether the full text meets every inclusion "
    "criterion. When in doubt, include." + _FT_QUOTE_RULE,
    Framing.EXCLUSION: "For each record look in the full text for a reason to exclude it under "
    "the exclusion criteria. When in doubt, include." + _FT_QUOTE_RULE,
}


class ScreenBatchContent(StrictModel):
    """What one batch asks of an agent. This is the task's content, and its input blob."""

    pass_label: PassLabel
    framing: Framing
    instructions: str
    protocol_id: str
    criteria: list[dict[str, str]]
    worked_examples: list[dict[str, str]]
    records: list[dict[str, str | None]]
    phase: ScreeningPhase
    stage: ScreeningStage = TA


class ScreenBatch(ScreenBatchContent):
    """A batch as served to a session: its content and the task that holds it."""

    task_id: str


class ScreenNext(StrictModel):
    """`batch` is None when nothing is served; `blocked` says why ordinary work waits; `remaining`
    counts the works of this pass that still lack a live, non-stale decision."""

    batch: ScreenBatch | None
    blocked: list[str]
    remaining: int
    stopped: StopStatus | None = None
    """Set exactly while the protocol's stopping rule has stopped serving new title/abstract
    records (slice 8): the rule, N, the run and the number of ranked works not to be screened.
    Left out of the dump while None. `remaining` then leaves those works out."""

    @model_serializer(mode="wrap")
    def _omit_unset_stop(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if data.get("stopped") is None:
            data.pop("stopped", None)
        return data


def open_pass(
    project: Project, actor: Actor, label: PassLabel, *, stage: ScreeningStage = TA
) -> None:
    """Open pass `label` of `stage` once: its framing, criterion order, a fresh seed and, for B
    under a fractional dual sample, its sample. A second call writes nothing.

    Refused when no protocol is recorded, for pass B under a one-pass plan, or at full text
    without a declared plan."""
    require_pass_stage(stage)
    with project.index.exclusive():
        project.index.sync()
        if _pass_row(project, label, stage) is not None:
            return
        events, _ = _opened_event(project, actor, label, _require_protocol(project), stage)
        project.record(events)


def _pass_input(
    project: Project, actor: Actor, label: PassLabel, stage: ScreeningStage
) -> str | None:
    """The input blob of a pass event: the label, and the stage when it is not title/abstract
    (so a slice-1 blob keeps its hash)."""
    value: dict[str, JsonValue] = {"pass_label": label.value}
    if stage is not TA:
        value["stage"] = stage.value
    return _input(project, actor, value)


def _opened_event(
    project: Project,
    actor: Actor,
    label: PassLabel,
    protocol: ProtocolVersion,
    stage: ScreeningStage = TA,
) -> tuple[list[Event], tuple[int, tuple[str, ...] | None]]:
    """The `screening.pass_opened` event for a pass not yet opened, not yet recorded, with the
    seed and sample it carries. For pass B under a partial sample, also the open-time draw record:
    the corpus outside the sample is written as considered with nothing added, so that later
    extension draws see only works that arrived after the open. Raises FactoryValidationError for
    pass B under a one-pass plan."""
    plan = screening_plan(protocol, stage)
    if label is PassLabel.B and plan.passes == 1:
        raise FactoryValidationError(
            [ValidationIssue("pass", "the protocol plans one screening pass")]
        )
    seed = secrets.randbits(32)
    sample = _sample(project, label, plan.dual_sample, seed, stage)
    payload = PassOpened(
        pass_label=label,
        framing=_FRAMING[label],
        criterion_order=_CRITERION_ORDER[label],
        random_seed=seed,
        sample=sample,
        stage=stage,
    )
    event = project.events.make(
        "screening.pass_opened",
        payload,
        actor,
        input_blob=_pass_input(project, actor, label, stage),
    )
    events = [event]
    if label is PassLabel.B and sample is not None:
        population = stage_population(project, stage)
        unsampled = tuple(
            sorted(population - set(sample) - set(calibration_items(project, stage=stage)))
        )
        extension = SampleExtended(
            pass_label=PassLabel.B, random_seed=seed, considered=unsampled, added=(), stage=stage
        )
        events.append(
            project.events.make(
                "screening.sample_extended",
                extension,
                actor,
                input_blob=_pass_input(project, actor, label, stage),
            )
        )
    return events, (seed, sample)


def join_pass(
    project: Project, actor: Actor, label: PassLabel, *, stage: ScreeningStage = TA
) -> None:
    """Bind the session to pass `label` of `stage`, once per stage. Refused, with nothing written,
    for a system actor, a human without `pass:join-human`, when the session relayed a human label
    (screening or extraction) or joined an extraction pass, when it already screens the other pass
    of the stage or its model already screens the other pass of the stage, or by `join_refusal`.
    Joining the same pass again writes nothing."""
    require_pass_stage(stage)
    with project.index.exclusive():
        project.index.sync()
        if _check_join(project, actor, label, stage):
            project.record([_join_event(project, actor, label, stage)])


def _check_join(
    project: Project, actor: Actor, label: PassLabel, stage: ScreeningStage = TA
) -> bool:
    """Whether the session may join `label` of `stage` and has not yet: True when a join must be
    written.

    Raises FactoryValidationError on a refusal; writes nothing."""
    if actor.kind == "human":
        return _check_human_join(project, actor, label, stage)
    if actor.kind != "agent" or actor.model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent screener joins a pass")]
        )
    _refuse_tainted_session(project, actor)
    joined = _joined_pass(project, actor.session, stage)
    if joined is None:
        _refuse_join(project, actor, label, stage)
        if actor.model in _pass_models(project, _other(label), stage):
            raise FactoryValidationError(
                [ValidationIssue("model", f"pass {_other(label).value} already uses this model")]
            )
        if (
            _drifted(project, actor.model, label, stage)
            and _rigor_mode(project) is RigorMode.SYSTEMATIC
        ):
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "model",
                        "not calibrated for this pass; recalibrate through a "
                        "criterion-touching protocol amendment",
                    )
                ]
            )
        return True
    if joined is label:
        return False
    raise FactoryValidationError(
        [ValidationIssue("pass", f"this session already screens pass {joined.value}")]
    )


def _check_human_join(
    project: Project, actor: Actor, label: PassLabel, stage: ScreeningStage
) -> bool:
    """`_check_join` for a person. One join per person and stage, whichever session asks."""
    require_human_screener(project, actor)
    membership = passes.human_membership(project, actor.user, stage)
    if membership is not None:
        if membership[0] is label:
            return False
        raise FactoryValidationError(
            [ValidationIssue("pass", f"this person already screens pass {membership[0].value}")]
        )
    _refuse_tainted_session(project, actor)
    if _joined_pass(project, actor.session, stage) is not None:
        raise FactoryValidationError(
            [ValidationIssue("session", "this session already screens a pass")]
        )
    _refuse_join(project, actor, label, stage)
    return True


def require_human_screener(project: Project, actor: Actor) -> None:
    """Refuse a person who does not hold `pass:join-human` now, on field `permission`."""
    principal = Principal(actor.user, actor.credential, Channel.CLI)
    authorize(project, principal, "human", Permission.PASS_JOIN_HUMAN, lab=_lab_of(project))


def _refuse_join(project: Project, actor: Actor, label: PassLabel, stage: ScreeningStage) -> None:
    kind = "human" if actor.kind == "human" else "agent"
    with project.index.connect() as conn:
        refusal = join_refusal(
            conn, label=label.value, stage=stage.value, kind=kind, user=actor.user
        )
    if refusal is not None:
        raise FactoryValidationError([ValidationIssue(*refusal)])


def _refuse_tainted_session(project: Project, actor: Actor) -> None:
    """Refuse a session that did something a screener may not have done."""
    if _is_label_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session relayed a human label and cannot screen")]
        )
    if _is_extraction_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session joined an extraction pass and cannot screen")]
        )
    if session_in_layer(project, actor.session):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "session", "this session worked for the intuition layer and cannot screen"
                )
            ]
        )
    if relayed_extraction_label(project, actor.session):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "session", "this session relayed an extraction label and cannot screen"
                )
            ]
        )
    if _is_inbox_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session supplied a link and cannot screen")]
        )


def _drifted(project: Project, model: str, label: PassLabel, stage: ScreeningStage) -> bool:
    """Whether `model` is new to a pass that has been calibrated on other models, after a watch
    cycle has run (ruling 22): the calibration measured another model."""
    models = calibrated_models(project, label, stage)
    if not models or model in models:
        return False
    with project.index.connect() as conn:
        cycles = conn.execute(text("SELECT count(*) FROM watch_cycles")).scalar_one()
    return bool(cycles)


def _join_event(
    project: Project, actor: Actor, label: PassLabel, stage: ScreeningStage = TA
) -> Event:
    """The `screening.pass_joined` event for a join `_check_join` allowed, not yet recorded."""
    if actor.kind == "human":
        payload = PassJoined(
            pass_label=label,
            session=actor.session,
            stage=stage,
            actor_kind="human",
            user=actor.user,
        )
    elif actor.model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent screener joins a pass")]
        )
    else:
        payload = PassJoined(
            pass_label=label, session=actor.session, model=actor.model, stage=stage
        )
    return project.events.make(
        "screening.pass_joined",
        payload,
        actor,
        input_blob=_pass_input(project, actor, label, stage),
    )


def screen_next(
    project: Project, actor: Actor, label: PassLabel, *, stage: ScreeningStage = TA
) -> ScreenNext:
    """Serve the next batch of pass `label` of `stage` to the session, or say why none is served.

    Nothing is written while the protocol is not ready, while a `dedup_run` would still change the
    merges (twins must not be drawn or queued apart), while the calibration set is required and
    not yet drawn (the human draws and labels it; an agent does not), or while pass B has no
    second pass to run, and a spent task budget refuses the call with nothing written. Otherwise
    the session joins the pass, the pass opens, the pending works are
    queued, and the next claimable batch is claimed.
    """
    require_pass_stage(stage)
    with project.index.exclusive():
        project.index.sync()
        protocol = current_protocol(project)
        if protocol is None or protocol.status is not ProtocolStatus.READY:
            return ScreenNext(
                batch=None,
                blocked=["the protocol is not ready; record it ready before screening (R-16)"],
                remaining=0,
            )
        plan = screening_plan(protocol, stage)
        if label is PassLabel.B and plan.passes == 1:
            return ScreenNext(
                batch=None, blocked=["the protocol plans one screening pass"], remaining=0
            )
        if not dedup_current(project):
            return ScreenNext(
                batch=None,
                blocked=["run dedup_run: the corpus has works it has not yet reconciled"],
                remaining=0,
            )
        status = calibration_status(project, stage=stage)
        if status.required and not calibration_drawn(project, stage=stage):
            return ScreenNext(
                batch=None,
                blocked=[
                    "the calibration set must be drawn and labelled by the human before "
                    "screening; an agent does not draw it"
                ],
                remaining=0,
            )
        needs_join = _check_join(project, actor, label, stage)
        human = actor.kind == "human"
        if human and not needs_join and _joined_pass(project, actor.session, stage) is not label:
            raise FactoryValidationError(
                [ValidationIssue("session", "a person screens in the session of their join")]
            )
        uncalibrated = human and not humans_calibrated(project, stage)
        require_for(project, actor, task_unit(task_kind(stage, label)))
        # The pass, the join and the queued batches are built first and written in one append,
        # so a failure while building them writes nothing.
        events: list[Event] = []
        row = _pass_row(project, label, stage)
        if row is None:
            opened, row = _opened_event(project, actor, label, protocol, stage)
            events.extend(opened)
        if needs_join:
            events.append(_join_event(project, actor, label, stage))
        if label is PassLabel.B:
            drawn = _extend_sample(project, actor, stage=stage)
            if drawn is not None:
                extension, added = drawn
                events.append(extension)
                row = (row[0], tuple(sorted(set(row[1] or ()) | set(added))))
        stop = _stop_context(project, stage, protocol.spec.screening)
        withheld = set() if stop is None or not stop.status.stopped else stop.withheld(label)
        queued, remaining = _enqueue(
            project,
            actor,
            label,
            protocol,
            row,
            stage,
            serve_calibration=not uncalibrated,
            withheld=withheld,
        )
        project.record([*events, *queued])
        gate_closed = status.required and not status.passed[label.value] and not uncalibrated
        blocked = _gate_reasons(project, status, label) if gate_closed else []
        stopped = None if stop is None or not stop.status.stopped else stop.status
        if stopped is not None:
            blocked.append(_stop_reason(stopped))
        held = held_batch(project, actor, stage) if human else None
        if held is not None:
            return ScreenNext(batch=held, blocked=blocked, remaining=remaining, stopped=stopped)
        if stop is None:
            task = claim_next(
                project,
                actor,
                task_kind(stage, label),
                accept=lambda content: _servable(content, gate_closed, protocol.protocol_id),
            )
        else:
            task = _claim_ranked(
                project, actor, label, stage, stop, gate_closed, protocol.protocol_id, withheld
            )
        batch = None if task is None else _claimed_batch(project, task)
        return ScreenNext(batch=batch, blocked=blocked, remaining=remaining, stopped=stopped)


def _stop_reason(stopped: StopStatus) -> str:
    if stopped.below_score is not None:
        return (
            f"{stopped.rule}: the last {stopped.run} ranked decisions all scored below "
            f"{stopped.below_score} (rule: {stopped.n}); {stopped.not_screened} ranked records "
            "are not screened"
        )
    return (
        f"{stopped.rule}: the last {stopped.run} ranked records were all excluded (rule: "
        f"{stopped.n}); {stopped.not_screened} ranked records are not screened"
    )


class _StopContext(StrictModel):
    """The ranking and the stopping rule as they stand: `status` is the rule evaluated, `positions`
    the latest ranking, `sequence` its works in the pass-A queue, `verdicts` the primary's screening
    verdicts and `served` the works of served (claimed) batches per pass."""

    statuses: list[StopStatus]
    positions: dict[str, int]
    sequence: list[str]
    verdicts: dict[str, Verdict]
    served: dict[str, set[str]]

    @property
    def status(self) -> StopStatus:
        """The rule that has stopped serving (the excludes rule first when both have), else the
        first rule declared."""
        return next((s for s in self.statuses if s.stopped), self.statuses[0])

    def withheld(self, label: PassLabel) -> set[str]:
        """The ranked works pass `label` may not be served now that the rule has stopped serving:
        those pass A has not decided that no batch of this pass has been served."""
        return unreached(self.sequence, self.verdicts, self.served[label.value])


def _served_works(project: Project, label: PassLabel, stage: ScreeningStage) -> set[str]:
    """The works of screening-phase batches of the pass that were claimed (a claim whose lease
    lapsed still counts: the batch was shown)."""
    return {
        str(record["work_id"])
        for _, status, content in _kind_tasks(project, task_kind(stage, label))
        if status == TaskStatus.CLAIMED.value and content.phase is ScreeningPhase.SCREENING
        for record in content.records
    }


def _primary_verdicts(project: Project, stage: ScreeningStage) -> dict[str, Verdict]:
    """The live, non-stale screening-phase verdict of pass A per work (calibration never counts)."""
    stale = stale_screening_decisions(project, stage=stage)
    return {
        d.work_id: d.verdict
        for d in live_decisions(project, PassLabel.A, stage=stage)
        if d.phase is ScreeningPhase.SCREENING and d.decision_id not in stale
    }


def _primary_scores(project: Project, stage: ScreeningStage) -> dict[str, int | None]:
    """The score of the live, non-stale screening decision of pass A per work (None: no score)."""
    stale = stale_screening_decisions(project, stage=stage)
    return {
        d.work_id: d.score
        for d in live_decisions(project, PassLabel.A, stage=stage)
        if d.phase is ScreeningPhase.SCREENING and d.decision_id not in stale
    }


def _stop_context(
    project: Project, stage: ScreeningStage, plan: ScreeningPlan
) -> _StopContext | None:
    """None unless `stage` is title/abstract, the plan declares a rule and a ranking exists."""
    n = plan.stop_after_consecutive_excludes
    below, run = plan.stop_below_score, plan.stop_score_run
    if stage is not TA or (n is None and below is None):
        return None
    positions = ranking_positions(project)
    if not positions:
        return None
    queue = stage_population(project, TA) - set(calibration_items(project, stage=TA))
    sequence = ranked_sequence(positions, queue)
    verdicts = _primary_verdicts(project, TA)
    served = {label.value: _served_works(project, label, TA) for label in PassLabel}
    statuses: list[StopStatus] = []
    if n is not None:
        statuses.append(stop_status(sequence, verdicts, served[PassLabel.A.value], n))
    if below is not None and run is not None:
        scores = _primary_scores(project, TA)
        statuses.append(score_status(sequence, scores, served[PassLabel.A.value], below, run))
    return _StopContext(
        statuses=statuses,
        positions=positions,
        sequence=sequence,
        verdicts=verdicts,
        served=served,
    )


def screening_stops(project: Project, stage: ScreeningStage = TA) -> list[StopStatus]:
    """Every stopping rule the plan declares, evaluated as the events stand; empty while the stage
    is not title/abstract, no protocol declares a rule or no ranking exists. Used by the PRISMA
    flow and the methods report; nothing is written."""
    protocol = current_protocol(project)
    if protocol is None:
        return []
    context = _stop_context(project, stage, protocol.spec.screening)
    return [] if context is None else context.statuses


def screening_stop(project: Project, stage: ScreeningStage = TA) -> StopStatus | None:
    """The stopping rule of pass A that has stopped serving (else the first declared), or None
    while the stage is not title/abstract, no protocol declares a rule or no ranking exists."""
    protocol = current_protocol(project)
    if protocol is None:
        return None
    context = _stop_context(project, stage, protocol.spec.screening)
    return None if context is None else context.status


def stop_unscreened(project: Project) -> set[str]:
    """The ranked works that the stopping rules have left unscreened (no pass-A decision, no batch
    served); empty while neither rule has stopped serving."""
    protocol = current_protocol(project)
    if protocol is None:
        return set()
    context = _stop_context(project, TA, protocol.spec.screening)
    if context is None or not any(s.stopped for s in context.statuses):
        return set()
    return context.withheld(PassLabel.A)


def _claim_ranked(
    project: Project,
    actor: Actor,
    label: PassLabel,
    stage: ScreeningStage,
    stop: _StopContext,
    gate_closed: bool,
    protocol_id: str,
    withheld: set[str],
) -> Task | None:
    """Claim the next batch in ranked order: calibration batches first, then batches holding
    tuning-batch records, then screening batches by their best-ranked record (a batch queued
    before the ranking carries records of any rank), task ID breaking ties. While the rule has
    stopped serving, a screening batch holding a withheld work is passed over. Each candidate is
    offered to `claim_next` alone, which still decides whether it is claimable."""
    from factory.services.screening_check import tuning_priority  # circular at import time

    key = rank_key(stop.positions)
    tuning = tuning_priority(project, stage)
    candidates: list[tuple[int, tuple[int, str], str]] = []
    for task_id, status, content in _kind_tasks(project, task_kind(stage, label)):
        if status == TaskStatus.COMPLETED.value:
            continue
        works = [str(record["work_id"]) for record in content.records]
        screening = content.phase is ScreeningPhase.SCREENING
        if screening and withheld.intersection(works):
            continue
        best = min((key(w) for w in works), default=key(""))
        tier = 0 if not screening else (1 if tuning.intersection(works) else 2)
        candidates.append((tier, best, task_id))
    for _, _, task_id in sorted(candidates):
        task = claim_next(
            project,
            actor,
            task_kind(stage, label),
            accept=lambda content: _servable(content, gate_closed, protocol_id),
            task_ids={task_id},
        )
        if task is not None:
            return task
    return None


def held_batch(project: Project, actor: Actor, stage: ScreeningStage = TA) -> ScreenBatch | None:
    """The first batch of the current protocol this session holds a live claim on at `stage`, or
    None. Nothing is written: a person may come back to a batch in a later process."""
    label = _joined_pass(project, actor.session, stage)
    protocol = current_protocol(project)
    if label is None or protocol is None:
        return None
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id FROM tasks WHERE kind = :kind AND status = :status "
                "AND claim_session = :session ORDER BY task_id"
            ),
            {
                "kind": task_kind(stage, label),
                "status": TaskStatus.CLAIMED.value,
                "session": actor.session,
            },
        ).all()
    for (task_id,) in rows:
        try:
            batch = _claimed_batch(project, require_holder(project, actor, str(task_id)))
        except FactoryValidationError:  # the lease ran out
            continue
        if batch.protocol_id == protocol.protocol_id:
            return batch
    return None


def obsolete_tasks(project: Project, label: PassLabel, *, stage: ScreeningStage = TA) -> list[str]:
    """Open or claimed tasks of the pass whose protocol version is no longer current, sorted.

    Such a task is never served, and its works are queued again under the current version. A
    task that is completed is never obsolete: it is history."""
    protocol = current_protocol(project)
    if protocol is None:
        return []
    return [
        task_id
        for task_id, status, content in _kind_tasks(project, task_kind(stage, label))
        if status != TaskStatus.COMPLETED.value and content.protocol_id != protocol.protocol_id
    ]


def live_decisions(
    project: Project, label: PassLabel | None = None, *, stage: ScreeningStage | None = TA
) -> list[DecisionRecorded]:
    """The decisions no later decision supersedes, in recording order, of one pass or of both, at
    `stage` (title/abstract by default; every stage when None)."""
    project.index.sync()
    sql = (
        "SELECT decision_id, work_id, pass_label, phase, stage, verdict, criterion, quote, "
        "rationale, protocol_id, task_id, supersedes, anchor, conversion_id, score "
        "FROM decisions WHERE superseded_by IS NULL"
    )
    params: dict[str, str] = {}
    if stage is not None:
        sql += " AND stage = :stage"
        params["stage"] = require_pass_stage(stage).value
    if label is not None:
        sql += " AND pass_label = :label"
        params["label"] = label.value
    with project.index.connect() as conn:
        rows = conn.execute(text(sql + " ORDER BY event_id"), params).mappings().all()
    return [DecisionRecorded.model_validate(dict(row)) for row in rows]


def decision_events(project: Project) -> dict[str, str]:
    """The event ID each live decision was recorded at."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT decision_id, event_id FROM decisions WHERE superseded_by IS NULL")
        ).all()
    return {str(decision): str(event) for decision, event in rows}


def stale_screening_decisions(project: Project, *, stage: ScreeningStage | None = None) -> set[str]:
    """The live decisions that a protocol amendment's stale rules make doubtful (R-30), of
    `stage`, or of every stage when None. Each rule matches a decision's own stage."""
    events = decision_events(project)
    refs = [
        DecisionRef(
            decision_id=decision.decision_id,
            verdict=decision.verdict.value,
            criterion=decision.criterion,
            protocol_id=decision.protocol_id,
            stage=decision.stage,
            at=events.get(decision.decision_id),
        )
        for decision in live_decisions(project, stage=stage)
    ]
    amended = amendments_with_events(project)
    return set(
        stale_decisions(
            [amendment for _, amendment in amended],
            protocol_lineage(project),
            refs,
            amended_at=[event for event, _ in amended],
        )
    )


# --- Recording ---


def screen_record(
    project: Project,
    actor: Actor,
    task_id: str,
    items: Sequence[ScreeningItem | HumanScreeningItem],
    *,
    reported_usage: ReportedUsage | None = None,
) -> BatchResult[str]:
    """Record the verdicts of a held batch, and return the decision IDs written (R-16, R-30).

    Refused with nothing written when the actor is neither an agent nor a person who joined a pass
    and still holds `pass:join-human`, the task is unknown or not held by this session, this session
    does not screen the task's pass, or the task's protocol version is no longer current. Otherwise
    each item is checked on its own: an invalid item is reported
    as an ItemError and not written, and the valid items are appended in one write.

    A decision supersedes the live decision for the same work in the same pass, if any. When every
    record of the task has a live decision of the task, the task completes with those decisions as
    its results, and with `reported_usage`, which is shown and never enforced. The decision events
    carry the validated input as their input blob.
    """
    with project.index.exclusive():
        project.index.sync()
        human = actor.kind == "human"
        if actor.kind != "agent" and not (human and _is_human_session(project, actor.session)):
            raise FactoryValidationError(
                [ValidationIssue("actor", "only an agent screener records a decision")]
            )
        if human:
            require_human_screener(project, actor)
        task = require_holder(project, actor, task_id)
        batch = _batch_of(project, task)
        stage = _stage_of_task(task)
        if _joined_pass(project, actor.session, stage) is not batch.pass_label:
            raise FactoryValidationError(
                [ValidationIssue("pass", f"this session does not screen pass {batch.pass_label}")]
            )
        protocol = _require_protocol(project)
        if batch.protocol_id != protocol.protocol_id:
            raise FactoryValidationError(
                [ValidationIssue("task_id", "the task's protocol version is no longer current")]
            )

        records = {str(record["work_id"]): record for record in batch.records}
        criteria = {str(criterion["id"]) for criterion in batch.criteria}
        rejected: list[ItemError] = []
        accepted: list[ScreeningItem | HumanScreeningItem] = []
        answered: set[str] = set()
        sent = items
        for index, original in enumerate(items):
            item = _as_stored(original, records)
            duplicate = item.work_id in answered
            issues = _item_issues(
                project, stage, index, item, records, criteria, duplicate, human=human
            )
            if issues:
                rejected.append(ItemError(index=index, issues=issues))
            else:
                answered.add(item.work_id)
                accepted.append(item)
        if not accepted:
            return BatchResult[str](written=[], rejected=rejected)

        blob = project.blobs.put_json(
            {"task_id": task_id, "items": [item.model_dump(mode="json") for item in sent]}
        )
        live = {
            decision.work_id: decision
            for decision in live_decisions(project, batch.pass_label, stage=stage)
        }
        decision_ids: list[str] = []
        events = []
        for item in accepted:
            decision_id = project.ids.new("dec")
            prior = live.get(item.work_id)
            payload = DecisionRecorded(
                decision_id=decision_id,
                work_id=item.work_id,
                pass_label=batch.pass_label,
                phase=batch.phase,
                stage=stage,
                verdict=item.verdict,
                criterion=None
                if item.criterion is None
                else f"{batch.protocol_id}:{item.criterion}",
                quote=item.quote,
                rationale=item.rationale,
                protocol_id=batch.protocol_id,
                task_id=task_id,
                supersedes=None if prior is None else prior.decision_id,
                anchor=item.anchor if stage is FT else None,
                conversion_id=_pinned_conversion(records[item.work_id]) if stage is FT else None,
                score=item.score,
            )
            events.append(
                project.events.make(
                    "screening.decision_recorded",
                    payload,
                    actor,
                    refs=(decision_id,),
                    input_blob=blob,
                )
            )
            decision_ids.append(decision_id)
        project.record(events)

        decided = {
            decision.work_id: decision.decision_id
            for decision in live_decisions(project, batch.pass_label, stage=stage)
            if decision.task_id == task_id
        }
        results = [decided.get(str(record["work_id"])) for record in batch.records]
        if all(result is not None for result in results):
            complete_task(
                project,
                actor,
                task_id,
                [str(result) for result in results],
                reported_usage=reported_usage,
            )
        return BatchResult[str](written=decision_ids, rejected=rejected)


def item_issues(
    project: Project, actor: Actor, task_id: str, item: HumanScreeningItem
) -> list[ValidationIssue]:
    """Why a person's verdict on a held batch would be refused, before it is recorded, so a bad
    quote is put right at once. Writes nothing."""
    task = require_holder(project, actor, task_id)
    batch = _batch_of(project, task)
    records = {str(record["work_id"]): record for record in batch.records}
    criteria = {str(criterion["id"]) for criterion in batch.criteria}
    return _item_issues(
        project,
        _stage_of_task(task),
        0,
        _as_stored(item, records),
        records,
        criteria,
        False,
        human=True,
    )


def _batch_of(project: Project, task: Task) -> ScreenBatchContent:
    """The screening batch a task holds. Raises FactoryValidationError for any other task."""
    refusal = FactoryValidationError([ValidationIssue("task_id", "is not a screening batch")])
    try:
        batch = ScreenBatchContent.model_validate(task_content(project, task))
    except ValidationError as exc:
        raise refusal from exc
    stage = stage_of_kind(task.kind)
    if stage is None or task.kind != task_kind(stage, batch.pass_label):
        raise refusal
    if batch.stage != stage:
        raise refusal
    return batch


def _stage_of_task(task: Task) -> ScreeningStage:
    """The stage a screening task belongs to, from its kind (`_batch_of` has checked it)."""
    stage = stage_of_kind(task.kind)
    if stage is None:
        raise FactoryValidationError([ValidationIssue("task_id", "is not a screening batch")])
    return stage


def _pinned_conversion(record: Mapping[str, str | None]) -> str | None:
    """The conversion a full-text record pins, or None."""
    return record.get("conversion_id")


def _as_stored(
    item: ScreeningItem | HumanScreeningItem, records: dict[str, dict[str, str | None]]
) -> ScreeningItem | HumanScreeningItem:
    """The item with its work id spelled as the batch stores it.

    A model writes a non-Latin name in composed form (NFC) where the stored id may be decomposed
    (NFD), so the two look identical and differ as strings. When the id is not a record of the
    batch but its NFC form equals the NFC form of exactly one stored id, the stored spelling is
    used. An id that matches nothing is returned unchanged and refused as before.
    """
    if item.work_id in records:
        return item
    matches = nfc_matches(item.work_id, records)
    return item if len(matches) != 1 else item.model_copy(update={"work_id": matches[0]})


def _item_issues(
    project: Project,
    stage: ScreeningStage,
    index: int,
    item: ScreeningItem | HumanScreeningItem,
    records: dict[str, dict[str, str | None]],
    criteria: set[str],
    duplicate: bool,
    *,
    human: bool = False,
) -> list[ValidationIssue]:
    """Why one item may not be written, located as `items.<index>.<field>`; empty when valid.

    The item's own rules (Task 1) are re-checked here, so an item built without validation is
    still refused. The record and criterion checks depend on the batch the task holds.

    At title/abstract an item carries no anchor and its quote is in the record's title or abstract.
    At full text it names an anchor of the conversion its record pins, and its quote is verbatim in
    that anchor's element (never across blocks or cells); nothing outside the pinned conversion is
    read. An agent always quotes; for a `human` item only an exclusion in `systematic` must."""
    field = f"items.{index}"
    record = records.get(item.work_id)
    if record is None:
        return [ValidationIssue(f"{field}.work_id", "is not a record of this task")]
    if duplicate:
        return [ValidationIssue(f"{field}.work_id", "is answered twice in one call")]
    try:
        (HumanScreeningItem if human else ScreeningItem).model_validate(
            item.model_dump(mode="python")
        )
    except ValidationError as exc:
        return [
            ValidationIssue(".".join([field, *map(str, err["loc"])]), str(err["msg"]))
            for err in exc.errors()
        ]
    if stage is not FT and item.anchor is not None:
        return [ValidationIssue(f"{field}.anchor", "is only for full-text screening")]
    if item.criterion is not None and item.criterion not in criteria:
        return [
            ValidationIssue(
                f"{field}.criterion",
                "is not a criterion of this batch: not in its protocol version, or not "
                f"applicable at {'full text' if stage is FT else 'title and abstract'}",
            )
        ]
    if (
        not item.quote
        and item.verdict is Verdict.EXCLUDE
        and _rigor_mode(project) is RigorMode.SYSTEMATIC
    ):
        return [ValidationIssue(f"{field}.quote", "an exclusion needs a quote in systematic")]
    if stage is FT:
        return _anchored_quote_issues(project, field, item, _pinned_conversion(record))
    if item.quote and not quote_in(
        item.quote, str(record.get("title") or ""), record.get("abstract")
    ):
        return [ValidationIssue(f"{field}.quote", "is not in the record's title or abstract")]
    return []


def _anchored_quote_issues(
    project: Project,
    field: str,
    item: ScreeningItem | HumanScreeningItem,
    conversion_id: str | None,
) -> list[ValidationIssue]:
    """The full-text checks of one item: the anchor exists in the record's pinned conversion and
    the quote, when there is one, is verbatim, after normalisation, in that anchor's element
    only."""
    if item.anchor is None:
        return [ValidationIssue(f"{field}.anchor", "is required at full-text screening")]
    if conversion_id is None:
        return [ValidationIssue(f"{field}.work_id", "has no pinned conversion in this task")]
    try:
        anchor = resolve_anchor(project, conversion_id, item.anchor)
    except FactoryValidationError as exc:
        # An unreadable pinned conversion costs this item only; resolve_anchor's reasons never
        # carry document text.
        return [
            ValidationIssue(
                f"{field}.anchor",
                issue.reason
                if issue.field == "anchor"
                else f"pinned conversion unreadable: {issue.reason}",
            )
            for issue in exc.issues
        ]
    if item.quote and not quote_in_element(anchor.text, item.quote):
        return [ValidationIssue(f"{field}.quote", "is not in the cited anchor")]
    return []


# --- Enqueueing ---


def _enqueue(
    project: Project,
    actor: Actor,
    label: PassLabel,
    protocol: ProtocolVersion,
    row: tuple[int, tuple[str, ...] | None],
    stage: ScreeningStage = TA,
    *,
    serve_calibration: bool = True,
    withheld: Collection[str] = frozenset(),
) -> tuple[list[Event], int]:
    """The `task.created` events of the batches for the pending works of the pass (calibration
    first), not yet recorded, and how many works of the pass's queue still lack a live,
    non-stale decision for their phase. `row` is the pass's seed and sample. Without
    `serve_calibration` (an uncalibrated human pass) the calibration works are left out of the
    queue, and stay out of the ordinary works: their outcome is the human's label. Ordinary works
    are queued in ranked order (the order of work id while there is no ranking); `withheld` works,
    which a stopping rule will not screen, are not queued and not counted."""
    seed, sample = row
    corpus = {work.id: work for work in list_works(project)}
    calibration = calibration_items(project, stage=stage)
    population = stage_population(project, stage)
    base = sorted(population) if sample is None else [w for w in sample if w in population]
    pinned: dict[str, tuple[str, str]] = {}
    if stage is not TA:
        from factory.services.fulltext_screening import fulltext_queue  # circular at import time

        pinned = {
            entry.work_id: (entry.document_id, entry.conversion_id)
            for entry in fulltext_queue(project).eligible
        }
        calibration = [w for w in calibration if w in pinned]
        base = [w for w in base if w in pinned]
    positions = ranking_positions(project) if stage is TA else {}
    ordinary = sorted(set(base) - set(calibration) - set(withheld), key=rank_key(positions))
    from factory.services.screening_check import tuning_priority  # circular at import time

    first = tuning_priority(project, stage)  # tuning batches are screened before the main queue
    ordinary = [w for w in ordinary if w in first] + [w for w in ordinary if w not in first]
    if not serve_calibration:
        calibration = []

    kind = task_kind(stage, label)
    tasks = _kind_tasks(project, kind)
    done = _done_keys(project, label, stage)
    open_keys = {
        (str(record["work_id"]), content.phase.value)
        for _, status, content in tasks
        if status != TaskStatus.COMPLETED.value and content.protocol_id == protocol.protocol_id
        for record in content.records
    }
    cal_phase = ScreeningPhase.CALIBRATION.value
    scr_phase = ScreeningPhase.SCREENING.value
    unavailable = done | open_keys
    remaining = sum(1 for w in calibration if (w, cal_phase) not in done) + sum(
        1 for w in ordinary if (w, scr_phase) not in done
    )
    pending = [
        (ScreeningPhase.CALIBRATION, [w for w in calibration if (w, cal_phase) not in unavailable]),
        (ScreeningPhase.SCREENING, [w for w in ordinary if (w, scr_phase) not in unavailable]),
    ]

    examples = _examples(project, corpus, stage)
    criteria = _criteria(protocol, label, stage)
    specs: list[TaskSpec] = []
    index = len(tasks)
    for phase, works in pending:
        for start in range(0, len(works), SCREEN_BATCH):
            records = [
                _record(corpus[w], pinned.get(w)) for w in works[start : start + SCREEN_BATCH]
            ]
            random.Random(f"{seed}:{index}").shuffle(records)
            content = ScreenBatchContent(
                pass_label=label,
                framing=_FRAMING[label],
                instructions=(INSTRUCTIONS if stage is TA else FULLTEXT_INSTRUCTIONS)[
                    _FRAMING[label]
                ],
                protocol_id=protocol.protocol_id,
                criteria=criteria,
                worked_examples=examples,
                records=records,
                phase=phase,
                stage=stage,
            )
            specs.append(TaskSpec(kind=kind, content=content.model_dump(mode="json")))
            index += 1
    events, result = build_task_events(project, actor, specs)
    if result.rejected:
        raise FactoryValidationError([issue for item in result.rejected for issue in item.issues])
    return events, remaining


def _record(work: Work, pinned: tuple[str, str] | None) -> dict[str, str | None]:
    """One batch record: title and abstract at title/abstract; at full text the title and the
    conversion pinned now (the screener reads the document through `document_read`)."""
    if pinned is None:
        return {"work_id": work.id, "title": work.title, "abstract": work.abstract}
    document_id, conversion_id = pinned
    return {
        "work_id": work.id,
        "title": work.title,
        "document_id": document_id,
        "conversion_id": conversion_id,
    }


def _extend_sample(
    project: Project,
    actor: Actor,
    *,
    random_seed: int | None = None,
    stage: ScreeningStage = TA,
) -> tuple[Event, tuple[str, ...]] | None:
    """Draw pass B's extension at `stage` over the works that arrived (or, at full text, became
    eligible) after pass B opened, and return the
    `screening.sample_extended` event (not yet recorded) and the works it added.

    None, with nothing to record, when pass B covers the whole corpus (no fractional sample) or
    when every corpus work outside the sample has been considered. Otherwise each candidate
    (corpus less sample, less considered works, less calibration items) is kept with probability
    dual_sample, and the event records the candidates and the draw even when none is added."""
    sample = pass_b_sample(project, stage=stage)
    dual_sample = screening_plan(_require_protocol(project), stage).dual_sample
    if sample is None or dual_sample is None:
        return None
    with project.index.connect() as conn:
        considered = considered_works(conn, stage)
    population = stage_population(project, stage)
    candidates = sorted(
        population - set(sample) - considered - set(calibration_items(project, stage=stage))
    )
    if not candidates:
        return None
    seed = secrets.randbits(32) if random_seed is None else random_seed
    rng = random.Random(seed)
    added = tuple(work for work in candidates if rng.random() < dual_sample)
    payload = SampleExtended(
        pass_label=PassLabel.B,
        random_seed=seed,
        considered=tuple(candidates),
        added=added,
        stage=stage,
    )
    event = project.events.make(
        "screening.sample_extended",
        payload,
        actor,
        input_blob=_pass_input(project, actor, PassLabel.B, stage),
    )
    return event, added


def extend_sample(
    project: Project,
    actor: Actor,
    *,
    stage: ScreeningStage = TA,
    random_seed: int | None = None,
) -> tuple[str, ...]:
    """Record pass B's sample extension at `stage` and return the works it added.

    Writes one `screening.sample_extended` event, even when it added no work, unless there is
    nothing to draw (pass B not opened, covering the whole population, or every outside work
    already considered) or a `dedup_run` would still change the merges, since twins would then be
    drawn apart; then it writes nothing and returns (). The draw is `_extend_sample`'s, so
    `random_seed` makes it reproducible and the event records it. `screen_next`, its other caller,
    has refused by then."""
    require_pass_stage(stage)
    with project.index.exclusive():
        project.index.sync()
        if not dedup_current(project):
            return ()
        drawn = _extend_sample(project, actor, random_seed=random_seed, stage=stage)
        if drawn is None:
            return ()
        event, added = drawn
        project.record([event])
        return added


def pass_b_sample(project: Project, *, stage: ScreeningStage = TA) -> tuple[str, ...] | None:
    """Pass B's effective sample at `stage`, sorted: the sample recorded at open, plus every work
    a sample extension at `stage` drew into it. None when pass B is not opened or
    covers the whole population.

    The single reader of pass B's sample: screen_next, pass progress and agreement all use it."""
    require_pass_stage(stage)
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT sample FROM passes WHERE pass_label = :label AND stage = :stage"),
            {"label": PassLabel.B.value, "stage": stage.value},
        ).one_or_none()
        if row is None or row[0] is None:
            return None
        base = set(json.loads(str(row[0])))
        extended = extended_works(conn, stage)
    return tuple(sorted(base | extended))


def _sample(
    project: Project,
    label: PassLabel,
    dual_sample: float | None,
    seed: int,
    stage: ScreeningStage = TA,
) -> tuple[str, ...] | None:
    """Pass B's sample: `ceil(dual_sample * population)` works drawn from the stage's population
    outside the calibration set, plus the calibration set itself. Pass A, and B when no fraction
    below one is planned, cover the whole population (None)."""
    if label is PassLabel.A or dual_sample is None or dual_sample >= 1:
        return None
    calibration = set(calibration_items(project, stage=stage))
    corpus = stage_population(project, stage)
    pool = sorted(corpus - calibration)
    size = math.ceil(round(dual_sample * len(corpus), 9))
    drawn = random.Random(seed).sample(pool, min(size, len(pool)))
    return tuple(sorted(set(drawn) | calibration))


def _examples(
    project: Project, corpus: dict[str, Work], stage: ScreeningStage = TA
) -> list[dict[str, str]]:
    """The worked examples with their expected verdicts. Seed ids are never included. Their
    verdicts rest on title and abstract, so at full text each is marked as style only."""
    examples: list[dict[str, str]] = []
    for view in worked_examples(project):
        work = corpus.get(view.work_id or "")
        if work is None:
            continue
        expected = "include" if view.kind is SeedKind.POSITIVE else "exclude"
        example = {"title": work.title, "abstract": work.abstract or "", "expected": expected}
        if stage is not TA:
            example["basis"] = "title_abstract"
            example["use"] = "style only; verdicts were decided on title and abstract"
        examples.append(example)
    return examples


def _criteria(
    protocol: ProtocolVersion, label: PassLabel, stage: ScreeningStage = TA
) -> list[dict[str, str]]:
    """The criteria that apply at `stage` (its own or `either`) in the pass's order: protocol
    order for A, reversed for B."""
    applicable = [
        c
        for c in protocol.spec.criteria
        if c.applies_at in (require_pass_stage(stage), ScreeningStage.EITHER)
    ]
    ordered = applicable if label is PassLabel.A else list(reversed(applicable))
    from factory.services.screening_check import example_texts  # circular at import time

    out: list[dict[str, str]] = []
    for c in ordered:
        item = {"id": c.id, "statement": c.statement, "rule": c.rule, "kind": c.kind.value}
        lines = example_texts(c)
        if lines:  # examples found by tuning batches: text only, never a work id
            item["examples"] = "\n".join(lines)
        out.append(item)
    return out


def _done_keys(
    project: Project, label: PassLabel, stage: ScreeningStage = TA
) -> set[tuple[str, str]]:
    """(work, phase) pairs with a live, non-stale decision in the pass at `stage`. A calibration
    decision recorded before the latest criterion-changing amendment is not done: the gate is
    passed again (R-26; a clarification counts, slice-1 behaviour)."""
    stale = stale_screening_decisions(project, stage=stage)
    cut = last_criterion_change(project, stage=stage)
    events = decision_events(project)
    return {
        (decision.work_id, decision.phase.value)
        for decision in live_decisions(project, label, stage=stage)
        if decision.decision_id not in stale
        and not (
            decision.phase is ScreeningPhase.CALIBRATION
            and cut is not None
            and events.get(decision.decision_id, "") < cut
        )
    }


def _kind_tasks(project: Project, kind: str) -> list[tuple[str, str, ScreenBatchContent]]:
    """Every task of `kind` as (task id, status, content), in task-ID order."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id, status, content_blob FROM tasks WHERE kind = :kind "
                "ORDER BY task_id"
            ),
            {"kind": kind},
        ).all()
    return [
        (
            str(task_id),
            str(status),
            ScreenBatchContent.model_validate(project.blobs.get_json(str(blob))),
        )
        for task_id, status, blob in rows
    ]


# --- Serving ---


def _servable(content: JsonValue, gate_closed: bool, protocol_id: str) -> bool:
    """Whether a task may be claimed: only tasks of the current protocol version, and, while the
    gate is closed, calibration batches only."""
    if not isinstance(content, dict) or content.get("protocol_id") != protocol_id:
        return False
    return not gate_closed or content.get("phase") == ScreeningPhase.CALIBRATION.value


def _claimed_batch(project: Project, task: Task) -> ScreenBatch:
    content = task_content(project, task)
    fields = dict(content) if isinstance(content, dict) else {}
    return ScreenBatch.model_validate({**fields, "task_id": task.task_id})


def _gate_reasons(project: Project, status: CalibrationStatus, label: PassLabel) -> list[str]:
    """Why ordinary batches wait for this pass. Counts only, never a label or a rate: the screener
    must not learn the answer key or how close it is to the threshold (R-20)."""
    reasons: list[str] = []
    unlabelled = status.drawn - status.labelled
    if unlabelled:
        reasons.append(
            f"calibration: {unlabelled} of {status.drawn} calibration items are not yet "
            "labelled by the human"
        )
    rates = status.per_pass[label.value]
    threshold = sensitivity_threshold(project)
    if rates.sensitivity is None:
        reasons.append(
            f"calibration: pass {label.value} sensitivity is not yet defined; no decided "
            "positive calibration item"
        )
    elif threshold is not None and rates.sensitivity < threshold:
        reasons.append(
            f"calibration: pass {label.value} sensitivity is below the required threshold; "
            "the researcher must amend the protocol"
        )
    if not reasons:
        reasons.append(
            f"calibration: pass {label.value} has not decided every calibration item under "
            "the current protocol"
        )
    return reasons


# --- Projection reads and small helpers ---


def _require_protocol(project: Project) -> ProtocolVersion:
    protocol = current_protocol(project)
    if protocol is None:
        raise FactoryValidationError([ValidationIssue("protocol", "record a protocol first")])
    return protocol


def _pass_row(
    project: Project, label: PassLabel, stage: ScreeningStage = TA
) -> tuple[int, tuple[str, ...] | None] | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT random_seed, sample FROM passes WHERE pass_label = :label "
                "AND stage = :stage"
            ),
            {"label": label.value, "stage": stage.value},
        ).one_or_none()
    if row is None:
        return None
    seed, sample = row
    if label is PassLabel.B:
        return int(seed), pass_b_sample(project, stage=stage)
    if sample is None:
        return int(seed), None
    return int(seed), tuple(str(work) for work in json.loads(str(sample)))


def _joined_pass(project: Project, session: str, stage: ScreeningStage = TA) -> PassLabel | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT pass_label FROM pass_sessions WHERE session = :session AND stage = :stage"
            ),
            {"session": session, "stage": stage.value},
        ).one_or_none()
    return None if row is None else PassLabel(str(row[0]))


def _is_human_session(project: Project, session: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pass_sessions WHERE session = :s AND actor_kind = 'human' LIMIT 1"),
            {"s": session},
        ).first()
    return row is not None


def _other(label: PassLabel) -> PassLabel:
    return PassLabel.B if label is PassLabel.A else PassLabel.A


def _pass_models(project: Project, label: PassLabel, stage: ScreeningStage = TA) -> set[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT model FROM pass_sessions WHERE pass_label = :label AND stage = :stage "
                "AND model IS NOT NULL"
            ),
            {"label": label.value, "stage": stage.value},
        ).all()
    return {str(row[0]) for row in rows}


def _is_label_session(project: Project, session: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM label_sessions WHERE session = :session"), {"session": session}
        ).one_or_none()
    return row is not None


def relayed_extraction_label(project: Project, session: str) -> bool:
    """Whether `session` relayed an extraction resolution, audit label or miner gold label over
    MCP, or drew an extraction audit sample (decision 51). Read from the log, as the projection
    keeps no session for these events."""
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.actor.session != session:
            continue
        if event.type == "extraction.audit_sampled":
            return True
        if event.type in (
            "extraction.resolved",
            "extraction.audit_labelled",
            "miner.calibration_labelled",
        ) and event.payload.get("channel") in (Channel.MCP.value, Channel.ELICIT.value):
            return True
    return False


def _is_inbox_session(project: Project, session: str) -> bool:
    """Whether the session captured an inbox link (slice 4a ruling 4: proposer is not screener)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM inbox_items WHERE session = :session LIMIT 1"),
            {"session": session},
        ).first()
    return row is not None


def _is_extraction_session(project: Project, session: str) -> bool:
    return passes.is_pass_session(project, session, module="extraction")


def _input(project: Project, actor: Actor, value: dict[str, JsonValue]) -> str | None:
    """The input blob an agent event must carry; human and system events carry none."""
    return project.blobs.put_json(value) if actor.kind == "agent" else None
