"""Appraisal passes: serving and recording the span items, and agreement by item (IDEA-21).

Two independent agent passes answer the `agent-span` items of the declared instrument for each
included work with a conversion; pass B takes the dual sample. A disagreement stands open until a
human resolves it (`services/appraisal_judgements.py`).

Invariants:
- Optional: with no `appraisal_instrument` nothing is served and nothing is written.
- An answer is stored only with a verified quote in one anchor of the pinned conversion
  (`unclear` needs none). A yes or no never rests on a paraphrase.
- Independence (decision 37): a session or a model that gave one pass cannot give the other, and a
  session in a screening or extraction pass cannot appraise.
- Answers under another instrument digest or another conversion are stale and count for nothing.
- Cells carry the passes' answers side by side; no count of items, total or grade is formed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.clock import format_ts
from factory.document.anchors import Manifest
from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.extraction.verify import (
    ANCHOR_REQUIRED,
    ANCHOR_UNKNOWN,
    QUOTE_NOT_IN_ANCHOR,
    QUOTE_REQUIRED,
)
from factory.model.appraisal import Answer, AppraisalItem, ItemKind
from factory.model.appraisal_events import AnswerInput, AppraisalRecorded
from factory.model.base import StrictModel
from factory.model.screening import PassLabel
from factory.model.task import Task
from factory.services.appraisal import (
    InstrumentInForce,
    instrument_in_force,
    item_applies,
)
from factory.services.budgets import budget_issue, spent_for, task_unit
from factory.services.context import Project
from factory.services.conversions import conversion_manifest, conversion_of
from factory.services.extraction import in_dual_sample
from factory.services.passes import is_pass_session
from factory.services.protocol import current_protocol
from factory.services.results import ItemError
from factory.services.tasks import (
    TaskSpec,
    build_task_events,
    claim_next,
    complete_task,
    get_task,
    require_holder,
    task_content,
)

APPRAISAL_KINDS: dict[PassLabel, str] = {PassLabel.A: "appraise_a", PassLabel.B: "appraise_b"}
"""The task kinds of the two passes (registered in `services/modules/task_kinds.py`)."""
APPRAISAL_INSTRUCTIONS = (
    "Answer each item yes, no or unclear from the pinned document only, read with document_read. "
    "For yes and no give the anchor and a verbatim quote from that one anchor; unclear needs "
    "neither. Answer what the paper states, not what you know of the work. Never infer an "
    "answer the text does not give; use unclear. Give no score and no overall view."
)


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


# --- The population and the units of a pass ---


def appraisal_population(project: Project) -> list[str]:
    """The works to appraise, sorted: those included at the last declared screening stage (full
    text when the protocol declares it, else title/abstract) that have a conversion. Read-only;
    the caller syncs the index."""
    from factory.services.dedup import absorbed_ids
    from factory.services.document_read import default_conversion, promoted_works
    from factory.services.extraction import extraction_population

    protocol = current_protocol(project)
    if protocol is None:
        return []
    if protocol.spec.full_text_screening is not None:
        absorbed = absorbed_ids(project)  # a duplicate merged later is appraised as its primary
        works = [w for w in extraction_population(project) if w not in absorbed]
    else:
        works = sorted(promoted_works(project))
    return [w for w in works if default_conversion(project, w) is not None]


@dataclass(frozen=True)
class Unit:
    """One work to appraise: its current conversion and the span items asked about it."""

    work_id: str
    document_id: str
    conversion_id: str
    items: tuple[AppraisalItem, ...]


def _seed(found: InstrumentInForce) -> int:
    return int(found.digest, 16)


def _units(project: Project, found: InstrumentInForce, label: PassLabel) -> list[Unit]:
    """The units of pass `label`: pass A takes every work with a span item to answer; pass B the
    dual sample (`dual_sample`, None = every work), drawn from the instrument's digest."""
    from factory.services.document_read import default_conversion

    units: list[Unit] = []
    for work_id in appraisal_population(project):
        if label is PassLabel.B and not in_dual_sample(
            _seed(found), work_id, found.instrument.dual_sample
        ):
            continue
        ref = default_conversion(project, work_id)
        items = tuple(
            i
            for i in found.instrument.of_kind(ItemKind.AGENT_SPAN)
            if item_applies(project, work_id, i)
        )
        if ref is not None and items:
            units.append(Unit(work_id, ref.document_id, ref.conversion_id, items))
    return units


class AppraisalBatch(StrictModel):
    """What a served task holds: the work, the pinned conversion and the items to answer. The
    `records` entry is the shape `document_read` gates a session by."""

    task_id: str
    pass_label: PassLabel
    instrument: str
    digest: str
    records: list[dict[str, str]]
    items: list[dict[str, str]]
    instructions: str


class AppraisalNext(StrictModel):
    """`batch` is None when nothing is served; `blocked` says why (no document text);
    `remaining` counts the units of this pass that are not finished."""

    batch: AppraisalBatch | None
    blocked: list[str]
    remaining: int


def _done(project: Project, unit: Unit, found: InstrumentInForce, label: PassLabel) -> bool:
    """Whether the pass finished this unit under this instrument digest and conversion."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM appraisal_closures WHERE work_id = :w AND pass_label = :l "
                "AND digest = :d AND conversion_id = :c LIMIT 1"
            ),
            {"w": unit.work_id, "l": label.value, "d": found.digest, "c": unit.conversion_id},
        ).first()
    return row is not None


def appraisal_progress(project: Project) -> dict[str, bool] | None:
    """For each work with a unit in pass A, whether the pass finished it under the instrument and
    conversion in force; None when the protocol declares no instrument. Read-only; syncs."""
    project.index.sync()
    found = instrument_in_force(project)
    if found is None:
        return None
    return {
        u.work_id: _done(project, u, found, PassLabel.A)
        for u in _units(project, found, PassLabel.A)
    }


def _check_pass_actor(project: Project, actor: Actor, label: PassLabel) -> None:
    """Refuse a non-agent, a session in a screening or extraction pass, a session that gave the
    other pass's answers and a model that did (independence, decision 37)."""
    if actor.kind != "agent" or actor.model is None:
        raise _refuse("actor", "only an agent appraiser serves a pass")
    if is_pass_session(project, actor.session):
        raise _refuse("session", "this session joined a screening or extraction pass")
    other = PassLabel.B if label is PassLabel.A else PassLabel.A
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT session, model FROM appraisal_answers WHERE pass_label = :l"),
            {"l": other.value},
        ).all()
    if any(str(r[0]) == actor.session for r in rows):
        raise _refuse("session", f"this session gave pass {other.value}; each pass needs its own")
    if any(str(r[1]) == actor.model for r in rows):
        raise _refuse("model", f"pass {other.value} already uses this model")


def appraisal_next(project: Project, actor: Actor, label: PassLabel) -> AppraisalNext:
    """Serve the next appraisal task of pass `label`, or say why none is served.

    Refused, with nothing written, for a non-agent, for a session that joined another pass or
    gave the other pass's answers, for a model that did, and when the protocol declares no
    instrument. Otherwise a task is queued for each unit of the pass that is not finished and has
    none current (same instrument digest and conversion), and the next claimable current task is
    claimed; a session holding a live claim is served that task again. Judgement and platform
    items never enter a task."""
    with project.writing():
        project.index.sync()
        found = instrument_in_force(project)
        if found is None:
            raise _refuse("protocol", "declare an appraisal_instrument first")
        _check_pass_actor(project, actor, label)
        kind = APPRAISAL_KINDS[label]
        units = _units(project, found, label)
        pending = [u for u in units if not _done(project, u, found, label)]
        blocked: list[str] = []
        if not units:
            blocked.append("no included work has a converted document and a span item to answer")
        queued = _queued(project, kind)
        specs = [
            TaskSpec(kind, _content(found, label, u), refs=(u.work_id,))
            for u in pending
            if (u.work_id, u.conversion_id, found.digest) not in queued
        ]
        if specs:
            events, _ = build_task_events(project, actor, specs)
            project.record(events)
        current = {(u.work_id, u.conversion_id) for u in pending}

        def accept(content: object) -> bool:
            return _is_current(content, found, current)

        task = _held(project, actor, kind, accept)
        # A claim already held pays for no new claim; a spent budget on the kind blocks a new one.
        spent = None if task is not None else spent_for(project, actor, task_unit(kind))
        if spent is not None:
            blocked.append(budget_issue(spent).reason)
        elif task is None:
            task = claim_next(project, actor, kind, accept=accept)
        batch = None if task is None else _batch(project, task, label)
        return AppraisalNext(batch=batch, blocked=blocked, remaining=len(pending))


def _content(found: InstrumentInForce, label: PassLabel, unit: Unit) -> dict[str, JsonValue]:
    return {
        "pass_label": label.value,
        "instrument": found.instrument.ref,
        "digest": found.digest,
        "records": [
            {
                "work_id": unit.work_id,
                "document_id": unit.document_id,
                "conversion_id": unit.conversion_id,
            }
        ],
        "items": [{"id": i.id, "statement": i.statement} for i in unit.items],
    }


def _queued(project: Project, kind: str) -> set[tuple[str, str, str]]:
    """(work, conversion, digest) of the open and claimed tasks of `kind`."""
    with project.index.connect() as conn:
        blobs = conn.execute(
            text(
                "SELECT content_blob FROM tasks WHERE kind = :k AND status IN ('open', 'claimed')"
            ),
            {"k": kind},
        ).all()
    found: set[tuple[str, str, str]] = set()
    for (blob,) in blobs:
        content = project.blobs.get_json(str(blob))
        record = _record_of(content)
        if record is not None and isinstance(content, dict):
            found.add((record[0], record[1], str(content.get("digest"))))
    return found


def _record_of(content: object) -> tuple[str, str] | None:
    """(work, conversion) of a task's single record."""
    records = content.get("records") if isinstance(content, dict) else None
    if isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict):
        work, conversion = records[0].get("work_id"), records[0].get("conversion_id")
        if isinstance(work, str) and isinstance(conversion, str):
            return work, conversion
    return None


def _is_current(content: object, found: InstrumentInForce, current: set[tuple[str, str]]) -> bool:
    record = _record_of(content)
    return (
        record is not None
        and record in current
        and isinstance(content, dict)
        and content.get("digest") == found.digest
    )


def _held(
    project: Project, actor: Actor, kind: str, accept: Callable[[object], bool]
) -> Task | None:
    """The first current task of `kind` this session holds under a live claim, else None."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id FROM tasks WHERE kind = :k AND claim_session = :s "
                "AND status = 'claimed' AND lease_until > :now ORDER BY task_id"
            ),
            {"k": kind, "s": actor.session, "now": format_ts(project.clock.now())},
        ).all()
    for (task_id,) in rows:
        task = get_task(project, str(task_id))
        if task is not None and accept(task_content(project, task)):
            return task
    return None


def _batch(project: Project, task: Task, label: PassLabel) -> AppraisalBatch:
    content = task_content(project, task)
    assert isinstance(content, dict)
    records, items = content["records"], content["items"]
    assert isinstance(records, list) and isinstance(items, list)
    return AppraisalBatch(
        task_id=task.task_id,
        pass_label=label,
        instrument=str(content["instrument"]),
        digest=str(content["digest"]),
        records=[{str(k): str(v) for k, v in r.items()} for r in records if isinstance(r, dict)],
        items=[{str(k): str(v) for k, v in i.items()} for i in items if isinstance(i, dict)],
        instructions=APPRAISAL_INSTRUCTIONS,
    )


# --- Recording ---


class AppraisalResult(StrictModel):
    written: int
    rejected: list[ItemError]
    completed: bool


def _answer_issues(manifest: Manifest, answer: AnswerInput) -> list[ValidationIssue]:
    """Why an answer cannot be stored, in the fixed vocabulary of the quote checks. `unclear`
    needs no quote or anchor; if either is given it is checked like any other."""
    needs = answer.answer is not Answer.UNCLEAR
    reasons: list[str] = []
    if answer.anchor is None:
        if needs or answer.quote is not None:
            reasons.append(ANCHOR_REQUIRED)
    else:
        element = manifest.get(answer.anchor)
        if element is None:
            reasons.append(ANCHOR_UNKNOWN)
        elif answer.quote is not None and not quote_in_element(element.text, answer.quote):
            reasons.append(QUOTE_NOT_IN_ANCHOR)
    if (answer.quote is None or not answer.quote.strip()) and needs:
        reasons.append(QUOTE_REQUIRED)
    return [ValidationIssue("answer", reason) for reason in reasons]


def _asked(content: object) -> set[str]:
    items = content.get("items") if isinstance(content, dict) else None
    return {str(i["id"]) for i in items if isinstance(i, dict) and "id" in i} if items else set()


def appraisal_record(
    project: Project,
    actor: Actor,
    task_id: str,
    answers: list[AnswerInput],
    *,
    finish: bool = False,
    reason: str | None = None,
) -> AppraisalResult:
    """Record answers of one held task. Invalid answers are reported by index and the valid ones
    written. `finish` closes the work once no answer of the call was rejected and every item of
    the task has a current answer from this pass; it completes the task.

    Refused, with nothing written, for a non-agent, a task not held by this session, a task of an
    instrument or conversion no longer current, and a finish with an item unanswered."""
    with project.writing():
        project.index.sync()
        if actor.kind != "agent" or actor.model is None:
            raise _refuse("actor", "only an agent appraiser records answers")
        found = instrument_in_force(project)
        task = require_holder(project, actor, task_id)
        label = next((lb for lb, k in APPRAISAL_KINDS.items() if k == task.kind), None)
        if label is None:
            raise _refuse("task_id", "not an appraisal task")
        content = task_content(project, task)
        record = _record_of(content)
        if (
            found is None
            or record is None
            or not isinstance(content, dict)
            or content.get("digest") != found.digest
        ):
            raise _refuse("task_id", "the instrument changed; release this task and ask again")
        work_id, conversion_id = record
        conversion = conversion_of(project, conversion_id)
        if conversion is None or not conversion.live:
            raise _refuse("task_id", "the conversion is no longer live; ask again")
        asked = _asked(content)
        manifest = conversion_manifest(project, conversion_id)
        seen: set[str] = set()
        rejected: list[ItemError] = []
        good: list[AnswerInput] = []
        for index, answer in enumerate(answers):
            issues: list[ValidationIssue] = []
            if answer.item not in asked:
                issues.append(ValidationIssue("item", "not an item of this task"))
            elif answer.item in seen:
                issues.append(ValidationIssue("item", "answered twice in this call"))
            else:
                issues.extend(_answer_issues(manifest, answer))
            if issues:
                rejected.append(ItemError(index=index, issues=issues))
            else:
                seen.add(answer.item)
                good.append(answer)
        closing = finish and not rejected
        if closing:
            missing = asked - seen - _answered(project, work_id, label, found, conversion_id)
            if missing:
                raise _refuse("finish", f"{len(missing)} item(s) have no answer yet")
        if good or closing:
            payload = AppraisalRecorded(
                task_id=task_id,
                work_id=work_id,
                conversion_id=conversion_id,
                instrument=found.instrument.ref,
                digest=found.digest,
                pass_label=label,
                session=actor.session,
                model=actor.model,
                answers=tuple(good),
                finished=closing,
                reason=reason,
            )
            blob = project.blobs.put_json(
                {"task_id": task_id, "answers": [a.model_dump(mode="json") for a in answers]}
            )
            project.record(
                [
                    project.events.make(
                        "appraisal.recorded",
                        payload,
                        actor,
                        refs=(task_id, work_id),
                        input_blob=blob,
                    )
                ]
            )
        if closing:
            complete_task(project, actor, task_id)
        return AppraisalResult(written=len(good), rejected=rejected, completed=closing)


def _answered(
    project: Project, work_id: str, label: PassLabel, found: InstrumentInForce, conversion_id: str
) -> set[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT item FROM appraisal_answers WHERE work_id = :w AND "
                "pass_label = :l AND digest = :d AND conversion_id = :c"
            ),
            {"w": work_id, "l": label.value, "d": found.digest, "c": conversion_id},
        ).all()
    return {str(r[0]) for r in rows}


# --- Agreement by item ---

CellState = Literal["pending", "single", "agreed", "disagreement", "resolved"]


class SpanCell(StrictModel):
    """The final standing of one span item of one work. `answer` is None while pending and while
    a disagreement is open; `a` and `b` are the passes' current answers."""

    work_id: str
    item: str
    state: CellState
    answer: Answer | None
    a: Answer | None
    b: Answer | None


def span_cells(project: Project, work_id: str | None = None) -> list[SpanCell]:
    """Every span item of every appraised work (or of `work_id`), sorted by work and item. A dual
    work whose passes agree is `agreed`; one that differs is a `disagreement` until a human
    resolves it; a work outside the dual sample stands on pass A (`single`). Only answers under
    the instrument digest and the conversion in force count; the others are stale. Syncs."""
    from factory.services.document_read import default_conversion

    project.index.sync()
    found = instrument_in_force(project)
    if found is None:
        return []
    works = [work_id] if work_id is not None else appraisal_population(project)
    cells: list[SpanCell] = []
    for work in works:
        ref = default_conversion(project, work)
        if ref is None:
            continue
        current = _current_answers(project, work, found.digest, ref.conversion_id)
        resolved = _resolutions(project, work, found.digest)
        dual = in_dual_sample(_seed(found), work, found.instrument.dual_sample)
        for item in found.instrument.of_kind(ItemKind.AGENT_SPAN):
            if not item_applies(project, work, item):
                continue
            a = current.get((PassLabel.A, item.id))
            b = current.get((PassLabel.B, item.id))
            cells.append(_cell(work, item.id, a, b, dual, resolved.get(item.id)))
    return sorted(cells, key=lambda c: (c.work_id, c.item))


def _cell(
    work: str, item: str, a: Answer | None, b: Answer | None, dual: bool, choice: str | None
) -> SpanCell:
    def make(state: CellState, answer: Answer | None) -> SpanCell:
        return SpanCell(work_id=work, item=item, state=state, answer=answer, a=a, b=b)

    if not dual:
        return make("single", a) if a is not None else make("pending", None)
    if a is None or b is None:
        return make("pending", None)
    if a == b:
        return make("agreed", a)
    if choice == "a":
        return make("resolved", a)
    if choice == "b":
        return make("resolved", b)
    if choice == "neither":
        return make("resolved", Answer.UNCLEAR)
    return make("disagreement", None)


def _current_answers(
    project: Project, work_id: str, digest: str, conversion_id: str
) -> dict[tuple[PassLabel, str], Answer]:
    """The latest answer per (pass, item) under this digest and conversion."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT pass_label, item, answer FROM appraisal_answers WHERE work_id = :w "
                "AND digest = :d AND conversion_id = :c ORDER BY event_id"
            ),
            {"w": work_id, "d": digest, "c": conversion_id},
        ).all()
    return {(PassLabel(str(r[0])), str(r[1])): Answer(str(r[2])) for r in rows}


def _resolutions(project: Project, work_id: str, digest: str) -> dict[str, str]:
    """The latest human choice per span item under this digest."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT item, answer FROM appraisal_judgements WHERE work_id = :w AND "
                "source = 'resolved' AND digest = :d ORDER BY event_id"
            ),
            {"w": work_id, "d": digest},
        ).all()
    return {str(r[0]): str(r[1]) for r in rows}


def stale_works(project: Project) -> list[str]:
    """Works that have appraisal answers, none of which is under the instrument digest and
    conversion in force: `appraisal_next` serves them again. Syncs."""
    from factory.services.document_read import default_conversion

    project.index.sync()
    found = instrument_in_force(project)
    if found is None:
        return []
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT work_id FROM appraisal_answers ORDER BY work_id")
        ).all()
    stale: list[str] = []
    for (work,) in rows:
        ref = default_conversion(project, str(work))
        if ref is None or not _current_answers(project, str(work), found.digest, ref.conversion_id):
            stale.append(str(work))
    return stale
