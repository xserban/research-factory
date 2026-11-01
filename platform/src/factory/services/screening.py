"""Screening passes, their sessions, and the batches an agent screens (R-16, R-20, R-31, R-35).

Pass A tests every work against the inclusion criteria in protocol order. Pass B, under a two-pass
plan, tests a sample of works against the exclusion criteria in reverse order. Each pass is opened
once, with a seed that orders its batches and, for B, its sample.

A session joins one pass. It is refused from the other pass, and from any session that relayed a
human label over MCP, since such a session could read the answer key (ruling 1). A refusal raises
FactoryValidationError and writes nothing.

`screen_next` serves the next batch of a pass. While calibration is required and the pass has not
passed it, only calibration batches are served, and `blocked` says why ordinary batches wait. A
batch's content is its task's input blob: the text the agent saw, without the task id. A work is
queued once per phase: calibration works in calibration batches, the others in screening batches.
A work with a live, non-stale decision in the pass is not queued again.

`screen_record` writes the verdicts of a held batch. Invalid items are reported and not written; a
new decision supersedes the live one for the same work and pass, and the task completes once each
of its records has a live decision of its own.

Invariants:
- No batch carries a decision, a worked example's seed id, or a held-out work.
- Within a batch, records are shuffled with a generator seeded by the pass seed and the task's
  index, so the order is reproducible and independent of the sorted order.
"""

import json
import math
import random
import secrets
from collections.abc import Sequence
from typing import Literal

from pydantic import JsonValue, ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.protocol import ProtocolStatus, ScreeningStage
from factory.model.screening import (
    DecisionRecorded,
    Framing,
    PassJoined,
    PassLabel,
    PassOpened,
    ScreeningItem,
    ScreeningPhase,
)
from factory.model.seed import SeedKind
from factory.model.task import Task, TaskStatus
from factory.model.work import Work
from factory.services.calibration import (
    CalibrationStatus,
    calibration_drawn,
    calibration_items,
    calibration_status,
    sensitivity_threshold,
    worked_examples,
)
from factory.services.context import Project
from factory.services.protocol import (
    ProtocolVersion,
    current_protocol,
    list_amendments,
    protocol_lineage,
)
from factory.services.protocol_rules import DecisionRef, stale_decisions
from factory.services.results import BatchResult, ItemError
from factory.services.screening_stats import quote_in
from factory.services.search import list_works
from factory.services.tasks import (
    TaskSpec,
    claim_next,
    complete_task,
    create_tasks,
    require_holder,
    task_content,
)

TASK_KIND = {PassLabel.A: "screen_a", PassLabel.B: "screen_b"}
SCREEN_BATCH = 10

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


class ScreenBatch(ScreenBatchContent):
    """A batch as served to a session: its content and the task that holds it."""

    task_id: str


class ScreenNext(StrictModel):
    """`batch` is None when nothing is served; `blocked` says why ordinary work waits; `remaining`
    counts the works of this pass that still lack a live, non-stale decision."""

    batch: ScreenBatch | None
    blocked: list[str]
    remaining: int


def open_pass(project: Project, actor: Actor, label: PassLabel) -> None:
    """Open pass `label` once: its framing, criterion order, a fresh seed and, for B under a
    fractional dual sample, its sample. A second call writes nothing.

    Refused when no protocol is recorded, or for pass B under a one-pass plan."""
    with project.index.exclusive():
        project.index.sync()
        if _pass_row(project, label) is not None:
            return
        protocol = _require_protocol(project)
        plan = protocol.spec.screening
        if label is PassLabel.B and plan.passes == 1:
            raise FactoryValidationError(
                [ValidationIssue("pass", "the protocol plans one screening pass")]
            )
        seed = secrets.randbits(32)
        sample = _sample(project, label, plan.dual_sample, seed)
        payload = PassOpened(
            pass_label=label,
            framing=_FRAMING[label],
            criterion_order=_CRITERION_ORDER[label],
            random_seed=seed,
            sample=sample,
        )
        project.record(
            [
                project.events.make(
                    "screening.pass_opened",
                    payload,
                    actor,
                    input_blob=_input(project, actor, {"pass_label": label.value}),
                )
            ]
        )


def join_pass(project: Project, actor: Actor, label: PassLabel) -> None:
    """Bind the session to pass `label`, once. Refused, with nothing written, when the actor is
    not an agent, when the session relayed a human label, or when it already screens the other
    pass. Joining the same pass again writes nothing."""
    with project.index.exclusive():
        project.index.sync()
        if _check_join(project, actor, label):
            _record_join(project, actor, label)


def _check_join(project: Project, actor: Actor, label: PassLabel) -> bool:
    """Whether the session may join `label` and has not yet: True when a join must be written.

    Raises FactoryValidationError on a refusal; writes nothing."""
    if actor.kind != "agent" or actor.model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent screener joins a pass")]
        )
    if _is_label_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session relayed a human label and cannot screen")]
        )
    joined = _joined_pass(project, actor.session)
    if joined is None:
        return True
    if joined is label:
        return False
    raise FactoryValidationError(
        [ValidationIssue("pass", f"this session already screens pass {joined.value}")]
    )


def _record_join(project: Project, actor: Actor, label: PassLabel) -> None:
    model = actor.model
    if model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent screener joins a pass")]
        )
    payload = PassJoined(pass_label=label, session=actor.session, model=model)
    project.record(
        [
            project.events.make(
                "screening.pass_joined",
                payload,
                actor,
                input_blob=_input(project, actor, {"pass_label": label.value}),
            )
        ]
    )


def screen_next(project: Project, actor: Actor, label: PassLabel) -> ScreenNext:
    """Serve the next batch of pass `label` to the session, or say why none is served.

    Nothing is written while the protocol is not ready, while the calibration set is required and
    not yet drawn (the human draws and labels it; an agent does not), or while pass B has no
    second pass to run. Otherwise the session joins the pass, the pass opens, the pending works are
    queued, and the next claimable batch is claimed.
    """
    with project.index.exclusive():
        project.index.sync()
        protocol = current_protocol(project)
        if protocol is None or protocol.status is not ProtocolStatus.READY:
            return ScreenNext(
                batch=None,
                blocked=["the protocol is not ready; record it ready before screening (R-16)"],
                remaining=0,
            )
        if label is PassLabel.B and protocol.spec.screening.passes == 1:
            return ScreenNext(
                batch=None, blocked=["the protocol plans one screening pass"], remaining=0
            )
        status = calibration_status(project)
        if status.required and not calibration_drawn(project):
            return ScreenNext(
                batch=None,
                blocked=[
                    "the calibration set must be drawn and labelled by the human before "
                    "screening; an agent does not draw it"
                ],
                remaining=0,
            )
        needs_join = _check_join(project, actor, label)
        open_pass(project, actor, label)
        if needs_join:
            _record_join(project, actor, label)
        gate_closed = status.required and not status.passed[label.value]
        remaining = _enqueue(project, actor, label, protocol)
        task = claim_next(
            project,
            actor,
            TASK_KIND[label],
            accept=lambda content: _servable(content, gate_closed, protocol.protocol_id),
        )
        blocked = _gate_reasons(project, status, label) if gate_closed else []
        batch = None if task is None else _claimed_batch(project, task)
        return ScreenNext(batch=batch, blocked=blocked, remaining=remaining)


def obsolete_tasks(project: Project, label: PassLabel) -> list[str]:
    """Open or claimed tasks of the pass whose protocol version is no longer current, sorted.

    Such a task is never served, and its works are queued again under the current version. A
    task that is completed is never obsolete: it is history."""
    protocol = current_protocol(project)
    if protocol is None:
        return []
    return [
        task_id
        for task_id, status, content in _kind_tasks(project, TASK_KIND[label])
        if status != TaskStatus.COMPLETED.value and content.protocol_id != protocol.protocol_id
    ]


def live_decisions(project: Project, label: PassLabel | None = None) -> list[DecisionRecorded]:
    """The decisions no later decision supersedes, in recording order, of one pass or of both."""
    project.index.sync()
    sql = (
        "SELECT decision_id, work_id, pass_label, phase, stage, verdict, criterion, quote, "
        "rationale, protocol_id, task_id, supersedes FROM decisions WHERE superseded_by IS NULL"
    )
    params: dict[str, str] = {}
    if label is not None:
        sql += " AND pass_label = :label"
        params["label"] = label.value
    with project.index.connect() as conn:
        rows = conn.execute(text(sql + " ORDER BY event_id"), params).mappings().all()
    return [DecisionRecorded.model_validate(dict(row)) for row in rows]


def stale_screening_decisions(project: Project) -> set[str]:
    """The live decisions that a protocol amendment's stale rules make doubtful (R-30)."""
    refs = [
        DecisionRef(
            decision_id=decision.decision_id,
            verdict=decision.verdict.value,
            criterion=decision.criterion,
            protocol_id=decision.protocol_id,
            stage=decision.stage,
        )
        for decision in live_decisions(project)
    ]
    return set(stale_decisions(list_amendments(project), protocol_lineage(project), refs))


# --- Recording ---


def screen_record(
    project: Project, actor: Actor, task_id: str, items: Sequence[ScreeningItem]
) -> BatchResult[str]:
    """Record the verdicts of a held batch, and return the decision IDs written (R-16, R-30).

    Refused with nothing written when the actor is not an agent, the task is unknown or not held
    by this session, this session does not screen the task's pass, or the task's protocol version
    is no longer current. Otherwise each item is checked on its own: an invalid item is reported
    as an ItemError and not written, and the valid items are appended in one write.

    A decision supersedes the live decision for the same work in the same pass, if any. When every
    record of the task has a live decision of the task, the task completes with those decisions as
    its results. The decision events carry the validated input as their input blob.
    """
    with project.index.exclusive():
        project.index.sync()
        if actor.kind != "agent":
            raise FactoryValidationError(
                [ValidationIssue("actor", "only an agent screener records a decision")]
            )
        task = require_holder(project, actor, task_id)
        batch = _batch_of(project, task)
        if _joined_pass(project, actor.session) is not batch.pass_label:
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
        accepted: list[ScreeningItem] = []
        answered: set[str] = set()
        for index, item in enumerate(items):
            duplicate = item.work_id in answered
            answered.add(item.work_id)
            issues = _item_issues(index, item, records, criteria, duplicate)
            if issues:
                rejected.append(ItemError(index=index, issues=issues))
            else:
                accepted.append(item)
        if not accepted:
            return BatchResult[str](written=[], rejected=rejected)

        blob = project.blobs.put_json(
            {"task_id": task_id, "items": [item.model_dump(mode="json") for item in items]}
        )
        live = {
            decision.work_id: decision for decision in live_decisions(project, batch.pass_label)
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
                stage=ScreeningStage.TITLE_ABSTRACT,
                verdict=item.verdict,
                criterion=None
                if item.criterion is None
                else f"{batch.protocol_id}:{item.criterion}",
                quote=item.quote,
                rationale=item.rationale,
                protocol_id=batch.protocol_id,
                task_id=task_id,
                supersedes=None if prior is None else prior.decision_id,
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
            for decision in live_decisions(project, batch.pass_label)
            if decision.task_id == task_id
        }
        results = [decided.get(str(record["work_id"])) for record in batch.records]
        if all(result is not None for result in results):
            complete_task(project, actor, task_id, [str(result) for result in results])
        return BatchResult[str](written=decision_ids, rejected=rejected)


def _batch_of(project: Project, task: Task) -> ScreenBatchContent:
    """The screening batch a task holds. Raises FactoryValidationError for any other task."""
    refusal = FactoryValidationError([ValidationIssue("task_id", "is not a screening batch")])
    try:
        batch = ScreenBatchContent.model_validate(task_content(project, task))
    except ValidationError as exc:
        raise refusal from exc
    if task.kind != TASK_KIND[batch.pass_label]:
        raise refusal
    return batch


def _item_issues(
    index: int,
    item: ScreeningItem,
    records: dict[str, dict[str, str | None]],
    criteria: set[str],
    duplicate: bool,
) -> list[ValidationIssue]:
    """Why one item may not be written, located as `items.<index>.<field>`; empty when valid.

    The item's own rules (Task 1) are re-checked here, so an item built without validation is
    still refused. The record and criterion checks depend on the batch the task holds."""
    field = f"items.{index}"
    record = records.get(item.work_id)
    if record is None:
        return [ValidationIssue(f"{field}.work_id", "is not a record of this task")]
    if duplicate:
        return [ValidationIssue(f"{field}.work_id", "is answered twice in one call")]
    try:
        ScreeningItem.model_validate(item.model_dump(mode="python"))
    except ValidationError as exc:
        return [
            ValidationIssue(".".join([field, *map(str, err["loc"])]), str(err["msg"]))
            for err in exc.errors()
        ]
    if item.criterion is not None and item.criterion not in criteria:
        return [
            ValidationIssue(
                f"{field}.criterion",
                "is not a criterion of this batch: not in its protocol version, or not "
                "applicable at title and abstract",
            )
        ]
    if not quote_in(item.quote, str(record.get("title") or ""), record.get("abstract")):
        return [ValidationIssue(f"{field}.quote", "is not in the record's title or abstract")]
    return []


# --- Enqueueing ---


def _enqueue(project: Project, actor: Actor, label: PassLabel, protocol: ProtocolVersion) -> int:
    """Create batches for the pending works of the pass, calibration first. Returns how many works
    of the pass's queue still lack a live, non-stale decision for their phase."""
    row = _pass_row(project, label)
    if row is None:
        raise FactoryValidationError([ValidationIssue("pass", "not opened")])
    seed, sample = row
    corpus = {work.id: work for work in list_works(project)}
    calibration = calibration_items(project)
    base = sorted(corpus) if sample is None else list(sample)
    ordinary = sorted(set(base) - set(calibration))

    kind = TASK_KIND[label]
    tasks = _kind_tasks(project, kind)
    done = _done_keys(project, label)
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

    examples = _examples(project, corpus)
    criteria = _criteria(protocol, label)
    specs: list[TaskSpec] = []
    index = len(tasks)
    for phase, works in pending:
        for start in range(0, len(works), SCREEN_BATCH):
            records = [
                {"work_id": w, "title": corpus[w].title, "abstract": corpus[w].abstract}
                for w in works[start : start + SCREEN_BATCH]
            ]
            random.Random(f"{seed}:{index}").shuffle(records)
            content = ScreenBatchContent(
                pass_label=label,
                framing=_FRAMING[label],
                instructions=INSTRUCTIONS[_FRAMING[label]],
                protocol_id=protocol.protocol_id,
                criteria=criteria,
                worked_examples=examples,
                records=records,
                phase=phase,
            )
            specs.append(TaskSpec(kind=kind, content=content.model_dump(mode="json")))
            index += 1
    if specs:
        result = create_tasks(project, actor, specs)
        if result.rejected:
            raise FactoryValidationError(
                [issue for item in result.rejected for issue in item.issues]
            )
    return remaining


def _sample(
    project: Project, label: PassLabel, dual_sample: float | None, seed: int
) -> tuple[str, ...] | None:
    """Pass B's sample: `ceil(dual_sample * corpus)` works drawn from the corpus outside the
    calibration set, plus the calibration set itself. Pass A, and B when no fraction below one is
    planned, cover the whole corpus (None)."""
    if label is PassLabel.A or dual_sample is None or dual_sample >= 1:
        return None
    calibration = set(calibration_items(project))
    corpus = {work.id for work in list_works(project)}
    pool = sorted(corpus - calibration)
    size = math.ceil(round(dual_sample * len(corpus), 9))
    drawn = random.Random(seed).sample(pool, min(size, len(pool)))
    return tuple(sorted(set(drawn) | calibration))


def _examples(project: Project, corpus: dict[str, Work]) -> list[dict[str, str]]:
    """The worked examples with their expected verdicts. Seed ids are never included."""
    examples: list[dict[str, str]] = []
    for view in worked_examples(project):
        work = corpus.get(view.work_id or "")
        if work is None:
            continue
        expected = "include" if view.kind is SeedKind.POSITIVE else "exclude"
        examples.append(
            {"title": work.title, "abstract": work.abstract or "", "expected": expected}
        )
    return examples


def _criteria(protocol: ProtocolVersion, label: PassLabel) -> list[dict[str, str]]:
    """The title-and-abstract criteria in the pass's order: protocol order for A, reversed for B."""
    applicable = [
        c
        for c in protocol.spec.criteria
        if c.applies_at in (ScreeningStage.TITLE_ABSTRACT, ScreeningStage.EITHER)
    ]
    ordered = applicable if label is PassLabel.A else list(reversed(applicable))
    return [
        {"id": c.id, "statement": c.statement, "rule": c.rule, "kind": c.kind.value}
        for c in ordered
    ]


def _done_keys(project: Project, label: PassLabel) -> set[tuple[str, str]]:
    """(work, phase) pairs with a live, non-stale decision in the pass."""
    stale = stale_screening_decisions(project)
    return {
        (decision.work_id, decision.phase.value)
        for decision in live_decisions(project, label)
        if decision.decision_id not in stale
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
    """Why ordinary batches wait for this pass. Counts and rates only, never a label."""
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
            f"calibration: pass {label.value} sensitivity {rates.sensitivity:.2f} is below "
            f"the {threshold:.2f} threshold"
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


def _pass_row(project: Project, label: PassLabel) -> tuple[int, tuple[str, ...] | None] | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT random_seed, sample FROM passes WHERE pass_label = :label"),
            {"label": label.value},
        ).one_or_none()
    if row is None:
        return None
    seed, sample = row
    if sample is None:
        return int(seed), None
    return int(seed), tuple(str(work) for work in json.loads(str(sample)))


def _joined_pass(project: Project, session: str) -> PassLabel | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT pass_label FROM pass_sessions WHERE session = :session"),
            {"session": session},
        ).one_or_none()
    return None if row is None else PassLabel(str(row[0]))


def _is_label_session(project: Project, session: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM label_sessions WHERE session = :session"), {"session": session}
        ).one_or_none()
    return row is not None


def _input(project: Project, actor: Actor, value: dict[str, JsonValue]) -> str | None:
    """The input blob an agent event must carry; human and system events carry none."""
    return project.blobs.put_json(value) if actor.kind == "agent" else None
