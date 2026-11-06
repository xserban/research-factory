"""Curation: computed lessons, reviewed proposals and their decisions (IDEA-15, plan SV task 4,
PD-8; R-34, R-51, R-52).

Invariants:
- `lessons` is computed from the index (audit labels, disagreements, `cannot-assess` decisions,
  failed runs); nothing is typed in and no rate is returned, only counts (decision 43).
- A proposal names one to twenty lesson ids that exist when it is made.
- Only a human decides, never the proposer (same actor id or same user, R-51), once per proposal.
  A rejected proposal stays (R-52).
- Accepting changes no protocol: an amendment still goes through `protocol_amend` (R-34), and the
  decision only records the link to the `protocol.amended` event.
- Learning never enters as retrieved memory: nothing here is read back into a prompt.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.curation import (
    CUR_ID_RE,
    CurationDecided,
    CurationDecision,
    CurationKind,
    CurationProposed,
)
from factory.model.protocol import ScreeningStage
from factory.services.agreement import screen_agreement
from factory.services.context import Project
from factory.services.protocol import amendments_with_events
from factory.services.status_lookup import unrecovered_failures

CANNOT_ASSESS_SPIKE = 5
"""Least `cannot-assess` decisions of one pass at one stage that make a lesson."""


class Lesson(StrictModel):
    lesson_id: str
    kind: str
    subject: str
    count: int


class Proposal(StrictModel):
    cur_id: str
    kind: CurationKind
    text: str
    lessons: tuple[str, ...]
    target: str | None
    proposer: str
    event_id: str
    decision: CurationDecision | None
    rationale: str | None
    amendment_event: str | None
    decided_by: str | None


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def lessons(project: Project) -> list[Lesson]:
    """The lessons of the project, sorted by id. Counts only; empty on a fresh project."""
    project.index.sync()
    found: list[Lesson] = []
    with project.index.connect() as conn:
        errors = Counter(
            (str(stage), str(criteria) if criteria else "none")
            for stage, criteria in conn.execute(
                text(
                    "SELECT a.stage, i.agreed_criteria FROM audit_items i"
                    " JOIN audits a ON a.audit_id = i.audit_id"
                    " WHERE i.human_verdict = 'include' AND i.agreed_verdict = 'exclude'"
                )
            ).all()
        )
        spikes = conn.execute(
            text(
                "SELECT stage, pass_label, count(*) FROM decisions"
                " WHERE verdict = 'cannot-assess' AND superseded_by IS NULL"
                " GROUP BY stage, pass_label HAVING count(*) >= :n"
            ),
            {"n": CANNOT_ASSESS_SPIKE},
        ).all()
        stages = sorted(
            str(s) for s in conn.execute(text("SELECT DISTINCT stage FROM passes")).scalars()
        )
    for (stage, criterion), n in errors.items():
        found.append(
            Lesson(
                lesson_id=f"audit-error:{stage}:{criterion}",
                kind="audit-error",
                subject=f"{stage}, criterion {criterion}",
                count=n,
            )
        )
    for stage in stages:
        disagreed: Counter[str] = Counter()
        try:
            agreement = screen_agreement(
                project, project.human_actor(), stage=ScreeningStage(stage)
            )
        except (FactoryValidationError, ValueError):
            continue
        for d in agreement.disagreements:
            for side in (d.a, d.b):
                if side.criterion is not None:
                    disagreed[side.criterion] += 1
        for criterion, n in disagreed.items():
            found.append(
                Lesson(
                    lesson_id=f"disagreement:{stage}:{criterion}",
                    kind="disagreement",
                    subject=f"{stage}, criterion {criterion}",
                    count=n,
                )
            )
    for stage, label, n in spikes:
        found.append(
            Lesson(
                lesson_id=f"cannot-assess:{stage}:{label}",
                kind="cannot-assess",
                subject=f"{stage}, pass {label}",
                count=int(n),
            )
        )
    for run in unrecovered_failures(project):
        found.append(Lesson(lesson_id=f"failed-run:{run}", kind="failed-run", subject=run, count=1))
    return sorted(found, key=lambda lesson: lesson.lesson_id)


def propose(
    project: Project,
    actor: Actor,
    kind: CurationKind,
    text_: str,
    lesson_ids: Sequence[str],
    target: str | None = None,
) -> str:
    """Record a proposal (an agent or a human) and return its `cur_` id. Refused, with nothing
    written: another actor kind (`actor`); a blank or long text, no lesson or more than twenty,
    a blank target (the field of the model); a lesson that is not one now (`lessons.<i>`:
    `unknown-lesson`)."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human proposes")
    with project.writing():
        known = {lesson.lesson_id for lesson in lessons(project)}
        cur_id = project.ids.new("cur")
        try:
            payload = CurationProposed(
                cur_id=cur_id,
                kind=kind,
                text=text_.strip(),
                lessons=tuple(dict.fromkeys(lesson_ids)),
                target=target,
            )
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(str(p) for p in err["loc"]), str(err["msg"]))
                    for err in exc.errors()
                ]
            ) from exc
        issues = [
            ValidationIssue(f"lessons.{i}", "unknown-lesson")
            for i, lesson_id in enumerate(payload.lessons)
            if lesson_id not in known
        ]
        if issues:
            raise FactoryValidationError(issues)
        input_blob = (
            project.blobs.put_json(payload.model_dump(mode="json"))
            if actor.kind == "agent"
            else None
        )
        event = project.events.make(
            "curation.proposed", payload, actor, refs=[cur_id], input_blob=input_blob
        )
        project.record([event])
    return cur_id


def decide_proposal(
    project: Project,
    actor: Actor,
    cur_id: str,
    decision: CurationDecision,
    *,
    rationale: str,
    amendment_event: str | None = None,
) -> str:
    """Accept or reject a proposal (a human other than the proposer) and return the event id.
    Refused, with nothing written: a non-human actor (`actor`: `human-only`); an unknown
    proposal (`cur_id`: `unknown`); a decided one (`cur_id`: `already-decided`); the proposer
    (`actor`: `proposer-cannot-decide`); a blank rationale or a link on a rejection (the field of
    the model); a link that is not a recorded amendment, or on a proposal that is not an
    amendment (`amendment_event`: `not-an-amendment`)."""
    if actor.kind != "human":
        raise _refuse("actor", "human-only")
    with project.writing():
        row = _row(project, cur_id)
        if row is None:
            raise _refuse("cur_id", "unknown")
        if row.decision is not None:
            raise _refuse("cur_id", "already-decided")
        if _is_proposer(project, actor, cur_id):
            raise _refuse("actor", "proposer-cannot-decide")
        try:
            payload = CurationDecided(
                cur_id=cur_id,
                decision=decision,
                rationale=rationale.strip(),
                amendment_event=amendment_event,
            )
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(str(p) for p in err["loc"]), str(err["msg"]))
                    for err in exc.errors()
                ]
            ) from exc
        if amendment_event is not None and (
            row.kind is not CurationKind.AMENDMENT
            or amendment_event not in {event_id for event_id, _ in amendments_with_events(project)}
        ):
            raise _refuse("amendment_event", "not-an-amendment")
        event = project.events.make("curation.decided", payload, actor, refs=[cur_id])
        project.record([event])
    return event.id


def proposals(project: Project, *, open_only: bool = False) -> list[Proposal]:
    """Every proposal in id order, decided ones included unless `open_only`."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = (
            conn.execute(text("SELECT cur_id FROM curation_proposals ORDER BY cur_id"))
            .scalars()
            .all()
        )
    found = [_row(project, str(cur_id)) for cur_id in rows]
    return [p for p in found if p is not None and not (open_only and p.decision is not None)]


def _is_proposer(project: Project, actor: Actor, cur_id: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT proposer_id, proposer_user FROM curation_proposals WHERE cur_id = :c"),
            {"c": cur_id},
        ).first()
    return row is not None and (actor.id == str(row[0]) or actor.user == str(row[1]))


def _row(project: Project, cur_id: str) -> Proposal | None:
    import re

    if re.fullmatch(CUR_ID_RE, cur_id) is None:
        return None
    project.index.sync()
    with project.index.connect() as conn:
        r = conn.execute(
            text("SELECT * FROM curation_proposals WHERE cur_id = :c"), {"c": cur_id}
        ).first()
    if r is None:
        return None
    m = r._mapping
    return Proposal(
        cur_id=str(m["cur_id"]),
        kind=CurationKind(str(m["kind"])),
        text=str(m["text"]),
        lessons=tuple(json.loads(str(m["lessons_json"]))),
        target=None if m["target"] is None else str(m["target"]),
        proposer=str(m["proposer_id"]),
        event_id=str(m["event_id"]),
        decision=None if m["decision"] is None else CurationDecision(str(m["decision"])),
        rationale=None if m["rationale"] is None else str(m["rationale"]),
        amendment_event=None if m["amendment_event"] is None else str(m["amendment_event"]),
        decided_by=None if m["decided_by"] is None else str(m["decided_by"]),
    )
