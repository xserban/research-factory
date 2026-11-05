"""Independent verification of sentences (slice 7b, plan W-B, rulings 1 to 3; spec ruling 12).

Declares: `VerifyUnit`, `VerdictInput`, `verify_next`, `verify_record`, `verify_release`. The only
module that writes `draft.verified`.

Invariants:
- A unit is one live `claim` or `synthesis` sentence with no verdict whose supports all still
  resolve; a stale sentence is for the writer to revise, its spans are no longer served.
- A unit shows the sentence, the preceding sentence of its section as context, what each support
  says and the flags the platform computed (ruling 11): no writer identity, outline or writer's
  input (R-51), as a flag is not the writer's reasoning. It is the verifier's `input_blob`, and the
  verdict's substrings are checked against it.
- Everyone who recorded a sentence of the draft is refused, at the serving and at the recording; a
  verifier cannot write in the draft (`drafts.write_sentences`). In `systematic` a verifier with
  the writer's model is refused; elsewhere the pair is recorded (the verdict row holds the model).
- A refusal carries fixed codes and positions, never text of the sentence or of a span.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import Field, JsonValue, ValidationError
from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.drafts import CLAIM_BEARING, VERIFY_SKILL, identities, writers_of
from factory.model.base import StrictModel
from factory.model.drafts import (
    SentenceClass,
    SentenceFlag,
    SentenceVerified,
    SupportSpan,
    Verdict,
    parse_support,
)
from factory.model.project import RigorMode
from factory.model.task import DRAFT_VERIFY_TASK_KIND, Task, TaskCompleted, TaskStatus
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.drafts import SentenceRow, live_sentences, require_draft, stale_reason
from factory.services.gates import rigor_mode
from factory.services.supports import (
    ResolvedSupport,
    SupportShown,
    resolve_supports,
    support_shown,
)
from factory.services.tasks import (
    TaskSpec,
    claim_next,
    create_tasks,
    release_task,
    require_holder,
    task_content,
)
from factory.writing.verdicts import verdict_issues


class VerifyUnit(StrictModel):
    task_id: str
    sentence_id: str
    text: str
    cls: SentenceClass
    context_previous: str | None
    supports: list[SupportShown]
    flags: list[SentenceFlag] = Field(default_factory=list)


class VerdictInput(StrictModel):
    """A verdict as the verifier gives it. `sentence_id` defaults to the task's sentence."""

    verdict: Verdict
    sentence_id: str | None = None
    sentence_span: str | None = None
    support_spans: list[SupportSpan] = Field(default_factory=list)
    note: str | None = None


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _require_verifier(actor: Actor) -> None:
    if actor.kind not in ("human", "agent"):
        raise _refuse("actor", "only a human or an agent verifies")


def _is_writer(project: Project, actor: Actor, draft_id: str) -> bool:
    with project.index.connect() as conn:
        return bool(identities(actor) & writers_of(conn, draft_id))


def _same_model(mode: RigorMode, actor: Actor, writer_model: str | None) -> bool:
    return mode is RigorMode.SYSTEMATIC and writer_model is not None and actor.model == writer_model


def _content(
    project: Project,
    row: SentenceRow,
    previous: str | None,
    resolved: Sequence[ResolvedSupport],
) -> dict[str, JsonValue]:
    return {
        "sentence_id": row.sentence_id,
        "text": row.text,
        "cls": row.cls.value,
        "context_previous": previous,
        "flags": [f.value for f in row.flags],
        "supports": [support_shown(project, r).model_dump(mode="json") for r in resolved],
    }


def _open_tasks(project: Project, draft_id: str) -> dict[str, str]:
    """The task of each sentence of the draft that has one not completed: sentence id to task id,
    read from the task's refs. A task whose content is not a unit of that sentence was written by
    hand and is passed over, so it blocks nothing."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id, content_blob, refs FROM tasks WHERE kind = :k AND status != :done"
            ),
            {"k": DRAFT_VERIFY_TASK_KIND, "done": TaskStatus.COMPLETED.value},
        ).all()
    found: dict[str, str] = {}
    for task_id, blob, refs in rows:
        named = json.loads(str(refs))
        if len(named) != 2 or named[0] != draft_id:
            continue
        try:
            content = project.blobs.get_json(str(blob))
            if not isinstance(content, dict):
                continue
            unit = VerifyUnit.model_validate({**content, "task_id": str(task_id)})
        except (FactoryError, OSError, ValueError):
            continue
        if unit.sentence_id == named[1]:
            found[unit.sentence_id] = str(task_id)
    return found


def _verified(project: Project, draft_id: str) -> set[str]:
    with project.index.connect() as conn:
        return {
            str(r[0])
            for r in conn.execute(
                text("SELECT sentence_id FROM sentence_verdicts WHERE draft_id = :d"),
                {"d": draft_id},
            )
        }


def _claim(project: Project, actor: Actor, task_id: str) -> Task | None:
    try:
        return require_holder(project, actor, task_id)  # already ours: serve it again
    except FactoryValidationError:
        return claim_next(project, actor, DRAFT_VERIFY_TASK_KIND, task_ids={task_id})


def verify_next(project: Project, draft_id: str, *, actor: Actor) -> VerifyUnit | None:
    """Serve the next sentence of the draft that needs a verdict, as a task claimed by `actor`;
    None when nothing is left to serve to it. Refused to anyone who recorded a sentence of the
    draft. In `systematic` a sentence of the verifier's own model is passed over, and the call is
    refused when nothing else was left."""
    _require_verifier(actor)
    with project.index.exclusive(), entering():
        project.index.sync()
        require_draft(project, draft_id)
        if _is_writer(project, actor, draft_id):
            raise _refuse("session", "a session that wrote in this draft cannot verify it")
        mode = rigor_mode(project)
        verified = _verified(project, draft_id)
        tasks = _open_tasks(project, draft_id)
        passed_over = False
        previous: tuple[str, str] | None = None
        for row in live_sentences(project, draft_id):
            before = previous[1] if previous and previous[0] == row.section_id else None
            previous = (row.section_id, row.text)
            if row.cls.value not in CLAIM_BEARING or row.sentence_id in verified:
                continue
            if _same_model(mode, actor, row.model):
                passed_over = True
                continue
            refs = [parse_support(s) for s in row.supports]
            resolved = resolve_supports(project, refs, cls=row.cls)
            if stale_reason(row, resolved) is not None:
                continue
            task_id = tasks.get(row.sentence_id)
            if task_id is None:
                content = _content(project, row, before, resolved)
                spec = TaskSpec(DRAFT_VERIFY_TASK_KIND, content, refs=(draft_id, row.sentence_id))
                task_id = create_tasks(project, project.system_actor(), [spec]).written[0]
            claimed = _claim(project, actor, task_id)
            if claimed is None:
                continue
            served = task_content(project, claimed)
            assert isinstance(served, dict)
            return VerifyUnit.model_validate({**served, "task_id": claimed.task_id})
        if passed_over:
            raise _refuse("model", "the writer's model cannot verify in systematic mode")
        return None


def verify_release(project: Project, task_id: str, *, actor: Actor) -> None:
    """Give back a unit `actor` holds, so that a refused verdict does not keep the sentence for the
    whole lease. A unit no longer held has nothing to give back."""
    with project.index.exclusive():
        project.index.sync()
        try:
            release_task(project, actor, task_id, "verdict-refused")
        except FactoryValidationError:
            return


def _sentence(project: Project, sentence_id: str) -> tuple[str, str | None]:
    """The draft and writer's model of a live sentence, else a refusal."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT draft_id, model FROM draft_sentences WHERE sentence_id = :s "
                "AND superseded_by IS NULL AND withdrawn = 0"
            ),
            {"s": sentence_id},
        ).first()
    if row is None:
        raise _refuse("sentence_id", "not a live sentence")
    return str(row[0]), None if row[1] is None else str(row[1])


def verify_record(project: Project, task_id: str, item: VerdictInput, *, actor: Actor) -> str:
    """Record the verdict of the unit `task_id`, which `actor` holds, complete the task and return
    the verdict id. Refused, with nothing written, by the rules of ruling 1 and 3; the unit served
    is the event's `input_blob`."""
    _require_verifier(actor)
    if actor.kind == "agent" and not str(actor.skill).startswith(VERIFY_SKILL):
        raise _refuse("skill", "a verdict is written under the skill rf-verify")
    with project.index.exclusive(), entering():
        project.index.sync()
        task = require_holder(project, actor, task_id)
        if task.kind != DRAFT_VERIFY_TASK_KIND:
            raise _refuse("task_id", "not a verification task")
        content = task_content(project, task)
        assert isinstance(content, dict)
        unit = VerifyUnit.model_validate({**content, "task_id": task_id})
        if item.sentence_id not in (None, unit.sentence_id):
            raise _refuse("sentence_id", "the task is for another sentence")
        draft_id, writer_model = _sentence(project, unit.sentence_id)
        if _is_writer(project, actor, draft_id):
            raise _refuse("session", "a session that wrote in this draft cannot verify it")
        if _same_model(rigor_mode(project), actor, writer_model):
            raise _refuse("model", "the writer's model cannot verify in systematic mode")
        if unit.sentence_id in _verified(project, draft_id):
            raise _refuse("sentence_id", "the sentence has a verdict")
        issues = verdict_issues(
            item.verdict,
            item.sentence_span,
            item.support_spans,
            sentence=unit.text,
            spans_by_ref={s.ref: s.spans for s in unit.supports},
        )
        if issues:
            raise FactoryValidationError(issues)
        verdict_id = project.ids.new("svd")
        try:
            payload = SentenceVerified(
                verdict_id=verdict_id,
                sentence_id=unit.sentence_id,
                verdict=item.verdict,
                sentence_span=item.sentence_span,
                support_spans=item.support_spans,
                note=item.note,
            )
        except ValidationError:
            raise _refuse("note", "at most 300 characters") from None
        project.record(
            [
                project.events.make(
                    "draft.verified",
                    payload,
                    actor,
                    refs=[verdict_id, unit.sentence_id, draft_id],
                    input_blob=task.content_blob,
                ),
                project.events.make(
                    "task.completed",
                    TaskCompleted(task_id=task_id, result_refs=(verdict_id,)),
                    actor,
                    refs=(task_id,),
                    input_blob=task.content_blob,
                ),
            ]
        )
        return verdict_id
