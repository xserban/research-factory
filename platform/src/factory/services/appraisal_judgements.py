"""Appraisal by humans: judgement items, resolution of pass disagreements, the sheet and the audit
(IDEA-21; plan EQ ruling 1).

Invariants:
- Only a human writes a judgement item or resolves a disagreement; an agent is refused here, an MCP
  relay from a session in a pass is refused, and the fold ignores such an event on rebuild too.
- A judgement is typed (`yes|no|unclear`) with a rationale; a later act on the same work and item
  supersedes it and the first stays in the log.
- The sheet puts the agent-span answers of the work beside the judgement items; it forms no total,
  weight, grade or order by quality (decision 42).
- Counts and rates are computed from the log, never typed.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.appraisal import (
    Answer,
    ItemKind,
)
from factory.model.appraisal_events import (
    AppraisalAuditLabelled,
    AppraisalAuditSampled,
    AppraisalJudged,
    AppraisalResolved,
)
from factory.model.base import StrictModel
from factory.model.screening import Channel
from factory.quality.stats import audit_size, draw_uniform
from factory.services.appraisal import (
    InstrumentInForce,
    PlatformAnswer,
    instrument_in_force,
    item_applies,
    platform_answers,
)
from factory.services.appraisal_passes import (
    SpanCell,
    appraisal_population,
    span_cells,
    stale_works,
)
from factory.services.audit_core import validate_seed
from factory.services.context import Project
from factory.services.human_channel import HumanAct, require_human_channel
from factory.services.passes import require_not_pass_session


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _human_gate(
    project: Project, actor: Actor, channel: Channel, what: str, act: HumanAct
) -> None:
    """Refuse a non-human, a pass session and a forged or barred channel. The caller holds the
    write lock."""
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        issues.append(ValidationIssue("actor", f"only a human {what}"))
    issues.extend(require_not_pass_session(project, actor, channel))
    if issues:
        raise FactoryValidationError(issues)
    require_human_channel(project, actor, channel, act)


def _require_instrument(project: Project) -> InstrumentInForce:
    found = instrument_in_force(project)
    if found is None:
        raise _refuse("protocol", "declare an appraisal_instrument first")
    return found


# --- Judgement items ---


def record_judgement(
    project: Project,
    actor: Actor,
    work_id: str,
    item: str,
    answer: Answer,
    *,
    rationale: str,
    channel: Channel = Channel.CLI,
) -> None:
    """Record a human's judgement of one item of one work. Refused, with nothing written, for a
    non-human actor, an MCP relay from a pass session, an item that is not a judgement item of the
    declared instrument or does not apply to the work, a work outside the appraised population
    and a blank rationale. A later call on the same (work, item) supersedes the earlier one."""
    with project.writing():
        project.index.sync()
        _human_gate(project, actor, channel, "judges an appraisal item", "label")
        found = _require_instrument(project)
        declared = found.instrument.item(item)
        issues: list[ValidationIssue] = []
        if declared is None or declared.kind is not ItemKind.JUDGEMENT:
            issues.append(ValidationIssue("item", "not a judgement item of the instrument"))
        elif not item_applies(project, work_id, declared):
            issues.append(ValidationIssue("item", "this item does not apply to the work"))
        if work_id not in appraisal_population(project):
            issues.append(ValidationIssue("work_id", "not an appraised work with a conversion"))
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "must not be blank"))
        if issues:
            raise FactoryValidationError(issues)
        payload = AppraisalJudged(
            work_id=work_id,
            item=item,
            answer=answer,
            rationale=rationale.strip(),
            digest=found.digest,
        )
        project.record([project.events.make("appraisal.judged", payload, actor, refs=(work_id,))])


def resolve_disagreement(
    project: Project,
    actor: Actor,
    work_id: str,
    item: str,
    choice: str,
    reason: str,
    *,
    channel: Channel = Channel.CLI,
) -> None:
    """A human's choice between the passes' answers on one open disagreement: `a`, `b` or
    `neither` (which records `unclear`). No value is typed. Refused for a non-human, a relay from a
    pass session, a cell that is not an open disagreement and a blank reason."""
    with project.writing():
        project.index.sync()
        _human_gate(project, actor, channel, "resolves an appraisal disagreement", "resolve")
        found = _require_instrument(project)
        issues: list[ValidationIssue] = []
        if choice not in ("a", "b", "neither"):
            issues.append(ValidationIssue("choice", "a, b or neither"))
        cell = next((c for c in span_cells(project, work_id) if c.item == item), None)
        if cell is None or cell.state != "disagreement":
            issues.append(ValidationIssue("item", "not an open disagreement of this work"))
        if not reason.strip():
            issues.append(ValidationIssue("reason", "must not be blank"))
        if issues:
            raise FactoryValidationError(issues)
        payload = AppraisalResolved(
            work_id=work_id,
            item=item,
            choice=choice,
            reason=reason.strip(),
            digest=found.digest,
        )
        project.record([project.events.make("appraisal.resolved", payload, actor, refs=(work_id,))])


class Disagreement(StrictModel):
    work_id: str
    item: str
    a: Answer
    b: Answer


def disagreements(project: Project) -> list[Disagreement]:
    """The open disagreements, sorted by work and item, with each pass's answer."""
    return [
        Disagreement(work_id=c.work_id, item=c.item, a=c.a, b=c.b)
        for c in span_cells(project)
        if c.state == "disagreement" and c.a is not None and c.b is not None
    ]


class AgreementBySpan(StrictModel):
    """Per item: the dual cells (both passes answered) and how many agree. Computed."""

    item: str
    compared: int
    agreed: int
    disagreed: int


def agreement(project: Project) -> list[AgreementBySpan]:
    """Agreement by item over the cells both passes have answered, sorted by item. No overall
    figure is formed across items."""
    counts: dict[str, list[int]] = {}
    for cell in span_cells(project):
        if cell.a is None or cell.b is None:
            continue
        entry = counts.setdefault(cell.item, [0, 0])
        entry[0] += 1
        entry[1] += cell.a == cell.b
    return [
        AgreementBySpan(item=item, compared=n, agreed=ok, disagreed=n - ok)
        for item, (n, ok) in sorted(counts.items())
    ]


# --- The sheet ---


class PassAnswer(StrictModel):
    answer: Answer
    anchor: str | None
    quote: str | None


class SheetSpan(StrictModel):
    item: str
    statement: str
    state: str
    answer: Answer | None
    a: PassAnswer | None
    b: PassAnswer | None


class SheetJudgement(StrictModel):
    item: str
    statement: str
    answer: Answer | None
    rationale: str | None


class AppraisalSheet(StrictModel):
    """One work's appraisal, item by item. No total, grade or rank (decision 42)."""

    work_id: str
    instrument: str
    platform: list[PlatformAnswer]
    spans: list[SheetSpan]
    judgements: list[SheetJudgement]


def _pass_rows(project: Project, work_id: str, digest: str) -> dict[tuple[str, str], PassAnswer]:
    """The latest answer with its anchor and quote per (pass, item) under this digest."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT pass_label, item, answer, anchor, quote FROM appraisal_answers "
                "WHERE work_id = :w AND digest = :d ORDER BY event_id"
            ),
            {"w": work_id, "d": digest},
        ).all()
    return {
        (str(r[0]), str(r[1])): PassAnswer(
            answer=Answer(str(r[2])),
            anchor=None if r[3] is None else str(r[3]),
            quote=None if r[4] is None else str(r[4]),
        )
        for r in rows
    }


def judgements_of(project: Project, work_id: str, digest: str) -> dict[str, tuple[Answer, str]]:
    """The latest judgement per item of a work under this digest: (answer, rationale)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT item, answer, rationale FROM appraisal_judgements WHERE work_id = :w "
                "AND source = 'judged' AND digest = :d ORDER BY event_id"
            ),
            {"w": work_id, "d": digest},
        ).all()
    return {str(r[0]): (Answer(str(r[1])), str(r[2])) for r in rows}


def appraisal_sheet(project: Project, work_id: str) -> AppraisalSheet:
    """The sheet of one appraised work: computed items, both passes' span answers with quotes and
    the judgement items with any recorded judgement. Refused for a work outside the population or
    when no instrument is declared. Syncs."""
    project.index.sync()
    found = _require_instrument(project)
    if work_id not in appraisal_population(project):
        raise _refuse("work_id", "not an appraised work with a conversion")
    passes = _pass_rows(project, work_id, found.digest)
    cells = {c.item: c for c in span_cells(project, work_id)}
    spans = [
        SheetSpan(
            item=i.id,
            statement=i.statement,
            state=cells[i.id].state if i.id in cells else "pending",
            answer=cells[i.id].answer if i.id in cells else None,
            a=passes.get(("A", i.id)),
            b=passes.get(("B", i.id)),
        )
        for i in found.instrument.of_kind(ItemKind.AGENT_SPAN)
        if item_applies(project, work_id, i)
    ]
    judged = judgements_of(project, work_id, found.digest)
    judgements = [
        SheetJudgement(
            item=i.id,
            statement=i.statement,
            answer=judged[i.id][0] if i.id in judged else None,
            rationale=judged[i.id][1] if i.id in judged else None,
        )
        for i in found.instrument.of_kind(ItemKind.JUDGEMENT)
        if item_applies(project, work_id, i)
    ]
    return AppraisalSheet(
        work_id=work_id,
        instrument=found.instrument.ref,
        platform=platform_answers(project, work_id),
        spans=spans,
        judgements=judgements,
    )


# --- Status ---


class AppraisalStatus(StrictModel):
    """Counts computed from the log. None of them is a quality figure."""

    declared: bool
    instrument: str | None
    works: int
    span_cells: dict[str, int]
    judgement_items_open: int
    judgement_items_recorded: int
    stale_works: int


def appraisal_status(project: Project) -> AppraisalStatus:
    """Span items by state, judgement items answered and open, and stale works. Syncs."""
    project.index.sync()
    found = instrument_in_force(project)
    if found is None:
        return AppraisalStatus(
            declared=False,
            instrument=None,
            works=0,
            span_cells={},
            judgement_items_open=0,
            judgement_items_recorded=0,
            stale_works=0,
        )
    works = appraisal_population(project)
    states: dict[str, int] = {}
    for cell in span_cells(project):
        states[cell.state] = states.get(cell.state, 0) + 1
    asked = recorded = 0
    for work in works:
        judged = judgements_of(project, work, found.digest)
        for item in found.instrument.of_kind(ItemKind.JUDGEMENT):
            if item_applies(project, work, item):
                asked += 1
                recorded += item.id in judged
    return AppraisalStatus(
        declared=True,
        instrument=found.instrument.ref,
        works=len(works),
        span_cells=dict(sorted(states.items())),
        judgement_items_open=asked - recorded,
        judgement_items_recorded=recorded,
        stale_works=len(stale_works(project)),
    )


def unjudged(project: Project) -> list[tuple[str, str]]:
    """(work, item) of every judgement item that applies and has no judgement under the digest in
    force, sorted. Syncs."""
    project.index.sync()
    found = instrument_in_force(project)
    if found is None:
        return []
    open_: list[tuple[str, str]] = []
    for work in appraisal_population(project):
        judged = judgements_of(project, work, found.digest)
        open_.extend(
            (work, i.id)
            for i in found.instrument.of_kind(ItemKind.JUDGEMENT)
            if item_applies(project, work, i) and i.id not in judged
        )
    return open_


# --- The audit of final span answers ---


def _final_span_items(project: Project) -> list[SpanCell]:
    return [c for c in span_cells(project) if c.answer is not None]


def appraisal_audit_sample(
    project: Project, actor: Actor, *, random_seed: int | None = None
) -> AppraisalAuditSampled:
    """Draw a sample of final span answers (agreed, single or resolved) for a human to check
    against the document, sized by the instrument's `audit_fraction` and `audit_minimum`. Refused
    for a non-human and for a seed out of range, and when there are no final answers."""
    seed, seed_issues = validate_seed(random_seed)
    with project.writing():
        project.index.sync()
        issues = list(seed_issues)
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "only a human draws an appraisal audit"))
        if issues:
            raise FactoryValidationError(issues)
        found = _require_instrument(project)
        population = [(c.work_id, c.item) for c in _final_span_items(project)]
        if not population:
            raise _refuse("passes", "there are no final span answers to audit")
        size = audit_size(
            len(population), found.instrument.audit_fraction, found.instrument.audit_minimum
        )
        drawn = draw_uniform(population, size, seed, key=lambda pair: pair)
        payload = AppraisalAuditSampled(
            audit_id=project.ids.new("aau"),
            random_seed=seed,
            digest=found.digest,
            items=tuple(drawn),
        )
        project.record([project.events.make("appraisal.audit_sampled", payload, actor)])
    return payload


def appraisal_audit_label(
    project: Project,
    actor: Actor,
    audit_id: str,
    work_id: str,
    item: str,
    correct: bool,
    note: str = "",
    channel: Channel = Channel.CLI,
) -> None:
    """A human's label on one sampled answer: whether the final answer is right against the
    document. Refused for a non-human, a relay from a pass session and an item outside the
    sample."""
    with project.writing():
        project.index.sync()
        _human_gate(project, actor, channel, "labels an appraisal audit item", "audit-label")
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM appraisal_audit_items WHERE audit_id = :a AND work_id = :w "
                    "AND item = :i"
                ),
                {"a": audit_id, "w": work_id, "i": item},
            ).first()
        if row is None:
            raise _refuse("item", "not in the sample of this audit")
        payload = AppraisalAuditLabelled(
            audit_id=audit_id, work_id=work_id, item=item, correct=correct, note=note
        )
        project.record(
            [project.events.make("appraisal.audit_labelled", payload, actor, refs=(audit_id,))]
        )


class AppraisalAuditReport(StrictModel):
    audit_id: str
    sampled: int
    labelled: int
    incorrect: int
    error_rate: float | None
    """Incorrect over labelled, computed; None until one is labelled."""


def appraisal_audit_report(project: Project) -> AppraisalAuditReport | None:
    """The latest audit's counts and error rate, computed from the labels; None if none drawn."""
    project.index.sync()
    with project.index.connect() as conn:
        audit = conn.execute(
            text("SELECT audit_id FROM appraisal_audits ORDER BY event_id DESC LIMIT 1")
        ).first()
        if audit is None:
            return None
        rows = conn.execute(
            text("SELECT correct FROM appraisal_audit_items WHERE audit_id = :a"),
            {"a": str(audit[0])},
        ).all()
    labelled = [r for r in rows if r[0] is not None]
    incorrect = sum(1 for r in labelled if not r[0])
    return AppraisalAuditReport(
        audit_id=str(audit[0]),
        sampled=len(rows),
        labelled=len(labelled),
        incorrect=incorrect,
        error_rate=incorrect / len(labelled) if labelled else None,
    )


__all__ = [
    "AgreementBySpan",
    "AppraisalAuditReport",
    "AppraisalSheet",
    "AppraisalStatus",
    "Disagreement",
    "agreement",
    "appraisal_audit_label",
    "appraisal_audit_report",
    "appraisal_audit_sample",
    "appraisal_sheet",
    "appraisal_status",
    "disagreements",
    "judgements_of",
    "record_judgement",
    "resolve_disagreement",
    "unjudged",
]
