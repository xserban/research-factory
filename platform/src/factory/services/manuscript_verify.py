"""Verification of a manuscript's units (slice 7b, plan W-C rulings 5 and 6; spec ruling 17).

Declares: `manuscript_verify_next`, `manuscript_verify_record`, `flag_uncited`. The only module that
writes `manuscript.verified`.

Invariants:
- A unit's content, which is the verdict's `input_blob`, holds ids only: the manuscript, the
  ordinal, the cited work and the conversion pinned when its task was made. The verifier reads the
  sentence through `manuscript_read` and the source through `document_read`.
- A verifier is an agent of the skill `rf-verify` that joined no pass (plan ruling 6). No second
  verifier is required; a unit has one verdict.
- A quote must be in the named anchor of the pinned conversion (`quote_in_element`, R-32). Only
  here can that be checked: the fold has no library.
- `sentence_span` is offsets inside the sentence, never its text, and a note that copies the
  manuscript is refused, so no verdict carries the manuscript's text.
- A flag on an uncited sentence is advisory: it is stored apart and enters no count of verdicts.
- A refusal carries fixed reasons and field names, never text of the sentence or of the source.
"""

from __future__ import annotations

from pydantic import JsonValue, ValidationError
from sqlalchemy import text

from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.drafts import VERIFY_SKILL
from factory.model.drafts import Verdict
from factory.model.manuscripts import ManuscriptVerified, MsUnit, SentenceRow
from factory.model.task import MANUSCRIPT_VERIFY_TASK_KIND, Task, TaskCompleted, TaskStatus
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.conversions import resolve_anchor
from factory.services.document_read import default_conversion, promoted_works
from factory.services.manuscripts import (
    refuse_echo,
    refuse_pass_session,
    require_manuscript,
    sentence_rows,
    units,
    verdict_rows,
)
from factory.services.tasks import (
    TaskSpec,
    claim_next,
    create_tasks,
    require_holder,
    task_content,
)


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _require_verifier(project: Project, actor: Actor) -> None:
    if actor.kind != "agent":
        raise _refuse("actor", "a verifier session is an agent's")
    if not str(actor.skill).startswith(VERIFY_SKILL):
        raise _refuse("skill", "a verdict is written under the skill rf-verify")
    refuse_pass_session(project, actor.session)


def _open_tasks(project: Project, manuscript_id: str) -> dict[tuple[int, str], str]:
    """The task of each unit of the manuscript that has one not completed."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT task_id, content_blob FROM tasks WHERE kind = :k AND status != :done"),
            {"k": MANUSCRIPT_VERIFY_TASK_KIND, "done": TaskStatus.COMPLETED.value},
        ).all()
    found: dict[tuple[int, str], str] = {}
    for task_id, blob in rows:
        content = project.blobs.get_json(str(blob))
        if isinstance(content, dict) and content.get("manuscript_id") == manuscript_id:
            found[(int(str(content["ordinal"])), str(content["work_id"]))] = str(task_id)
    return found


def _claim(project: Project, actor: Actor, task_id: str) -> Task | None:
    try:
        return require_holder(project, actor, task_id)  # already ours: serve it again
    except FactoryValidationError:
        return claim_next(project, actor, MANUSCRIPT_VERIFY_TASK_KIND, task_ids={task_id})


def _new_task(project: Project, manuscript_id: str, ordinal: int, work_id: str) -> str | None:
    """A task for the unit, pinned to the conversion `document_read` serves now; None when there
    is none any more (the next `resolve_citations` closes the unit)."""
    pinned = default_conversion(project, work_id)
    if pinned is None or work_id not in promoted_works(project):
        return None
    content: dict[str, JsonValue] = {
        "manuscript_id": manuscript_id,
        "ordinal": ordinal,
        "work_id": work_id,
        "conversion_id": pinned.conversion_id,
    }
    spec = TaskSpec(MANUSCRIPT_VERIFY_TASK_KIND, content, refs=(manuscript_id, work_id))
    return create_tasks(project, project.system_actor(), [spec]).written[0]


def manuscript_verify_next(project: Project, manuscript_id: str, *, actor: Actor) -> MsUnit | None:
    """Serve the next open unit of the manuscript as a task claimed by `actor`, ids only; None when
    nothing is left to serve to it."""
    with project.index.exclusive(), entering():
        project.index.sync()
        _require_verifier(project, actor)
        require_manuscript(project, manuscript_id)
        verdicts = verdict_rows(project, manuscript_id)
        tasks = _open_tasks(project, manuscript_id)
        for unit in units(project, manuscript_id):
            if unit.reason is not None or unit.work_id is None:
                continue
            slot = (unit.ordinal, unit.work_id)
            if slot in verdicts:
                continue
            task_id = tasks.get(slot) or _new_task(
                project, manuscript_id, unit.ordinal, unit.work_id
            )
            claimed = None if task_id is None else _claim(project, actor, task_id)
            if claimed is None:
                continue
            served = task_content(project, claimed)
            assert isinstance(served, dict)
            return MsUnit.model_validate({**served, "task_id": claimed.task_id})
        return None


def _sentence(project: Project, manuscript_id: str, ordinal: int) -> SentenceRow:
    sentences = sentence_rows(project, manuscript_id)
    if not 1 <= ordinal <= len(sentences):
        raise _refuse("ordinal", "no such sentence")
    return sentences[ordinal - 1]


def _issues(exc: ValidationError) -> FactoryValidationError:
    """A model's refusal as issues. Pydantic's `msg` states the rule, not the input."""
    return FactoryValidationError(
        [
            ValidationIssue(".".join(str(p) for p in e["loc"]) or "verdict", str(e["msg"]))
            for e in exc.errors()
        ]
    )


def manuscript_verify_record(
    project: Project,
    task_id: str,
    verdict: Verdict,
    *,
    sentence_span: tuple[int, int] | None,
    anchor: str | None,
    quote: str | None,
    note: str | None,
    actor: Actor,
) -> str:
    """Record the verdict of the unit `task_id`, which `actor` holds, complete the task and return
    the verdict id. Refused, with nothing written: a verdict without what it must name; a span
    beyond the sentence; a quote not in the anchor of the pinned conversion; a note copying the
    manuscript; a unit closed or already judged. The unit served is the `input_blob`."""
    with project.index.exclusive(), entering():
        project.index.sync()
        _require_verifier(project, actor)
        task = require_holder(project, actor, task_id)
        if task.kind != MANUSCRIPT_VERIFY_TASK_KIND:
            raise _refuse("task_id", "not a manuscript verification task")
        content = task_content(project, task)
        assert isinstance(content, dict)
        unit = MsUnit.model_validate({**content, "task_id": task_id})
        row = require_manuscript(project, unit.manuscript_id)
        live = {
            (u.ordinal, u.work_id) for u in units(project, unit.manuscript_id) if u.reason is None
        }
        slot = (unit.ordinal, unit.work_id)
        if slot not in live:
            raise _refuse("task_id", "the unit is no longer open")
        if slot in verdict_rows(project, unit.manuscript_id):
            raise _refuse("task_id", "the unit has a verdict")
        verdict_id = project.ids.new("mvd")
        try:
            payload = ManuscriptVerified(
                verdict_id=verdict_id,
                manuscript_id=unit.manuscript_id,
                ordinal=unit.ordinal,
                work_id=unit.work_id,
                verdict=verdict,
                sentence_span=sentence_span,
                anchor=anchor,
                quote=quote,
                conversion_id=unit.conversion_id,
                note=note or None,
            )
        except ValidationError as exc:
            raise _issues(exc) from None
        sentence = _sentence(project, unit.manuscript_id, unit.ordinal)
        if sentence_span is not None and sentence_span[1] > sentence.end - sentence.start:
            raise _refuse("sentence_span", "beyond the sentence")
        if anchor is not None and quote is not None:
            found = resolve_anchor(project, unit.conversion_id, anchor)
            if not quote_in_element(found.text, quote):
                raise _refuse("quote", "not in that anchor of the cited work's conversion")
        refuse_echo(project, row, note)
        project.record(
            [
                project.events.make(
                    "manuscript.verified",
                    payload,
                    actor,
                    refs=[verdict_id, unit.manuscript_id, unit.work_id, unit.conversion_id],
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


def flag_uncited(
    project: Project, manuscript_id: str, ordinal: int, note: str | None, *, actor: Actor
) -> str:
    """Flag an uncited sentence as `uncited-claim`, advisory, and return the flag's id. Refused,
    with nothing written, for a sentence that cites, one already flagged, or a note copying the
    manuscript."""
    with project.index.exclusive(), entering():
        project.index.sync()
        _require_verifier(project, actor)
        row = require_manuscript(project, manuscript_id)
        sentence = _sentence(project, manuscript_id, ordinal)
        if sentence.keys:
            raise _refuse("ordinal", "the sentence cites; it is not an uncited claim")
        with project.index.connect() as conn:
            flagged = conn.execute(
                text("SELECT 1 FROM manuscript_flags WHERE manuscript_id = :m AND ordinal = :o"),
                {"m": manuscript_id, "o": ordinal},
            ).first()
        if flagged is not None:
            raise _refuse("ordinal", "the sentence is flagged")
        verdict_id = project.ids.new("mvd")
        try:
            payload = ManuscriptVerified(
                verdict_id=verdict_id,
                manuscript_id=manuscript_id,
                ordinal=ordinal,
                note=note or None,
                uncited_flag=True,
            )
        except ValidationError as exc:
            raise _issues(exc) from None
        refuse_echo(project, row, note)
        blob = project.blobs.put_json({"manuscript_id": manuscript_id, "ordinal": ordinal})
        project.record(
            [
                project.events.make(
                    "manuscript.verified",
                    payload,
                    actor,
                    refs=[verdict_id, manuscript_id],
                    input_blob=blob,
                )
            ]
        )
        return verdict_id
