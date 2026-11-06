"""The appraisal matrix and the check rules over appraisal (IDEA-21; plan EQ ruling 3).

`appraisal_report` is a work by item matrix. Reports show, never filter: it removes no row from the
evidence report and carries no total, weight, grade, rank or sort by quality (decision 42). Works
are listed by id and cells in the instrument's item order.

Invariants:
- A project with no `appraisal_instrument` gets an empty report and no check hit except, in
  `systematic` mode only, one warning that none is declared.
- Every cell is a value the log or a fixed rule gave: `yes|no|unclear`, `found|not-found` for a
  computed item, or the open states `pending`, `disagreement` and `open`.
"""

from __future__ import annotations

from factory.model.appraisal import ItemKind
from factory.model.base import StrictModel
from factory.modules.contract import CheckHit
from factory.services.appraisal import (
    instrument_in_force,
    item_applies,
    platform_answers,
)
from factory.services.appraisal_judgements import judgements_of, unjudged
from factory.services.appraisal_passes import (
    appraisal_population,
    span_cells,
    stale_works,
)
from factory.services.context import Project


class ReportItem(StrictModel):
    id: str
    kind: str
    statement: str


class ReportCell(StrictModel):
    item: str
    value: str
    """`yes`, `no`, `unclear`, `found`, `not-found`, `pending`, `disagreement`, `open` or
    `n/a` (the item does not apply to the work)."""
    state: str
    """`computed`, a span state (`agreed`, `single`, `resolved`, ...) or `judged`/`open`."""


class ReportRow(StrictModel):
    work_id: str
    cells: list[ReportCell]


class AppraisalReport(StrictModel):
    instrument: str | None
    items: list[ReportItem]
    rows: list[ReportRow]


def appraisal_report(project: Project) -> AppraisalReport:
    """The work by item matrix of the declared instrument. Empty when none is declared. Syncs."""
    project.index.sync()
    found = instrument_in_force(project)
    if found is None:
        return AppraisalReport(instrument=None, items=[], rows=[])
    items = [
        ReportItem(id=i.id, kind=i.kind.value, statement=i.statement)
        for i in found.instrument.items
    ]
    spans = {(c.work_id, c.item): c for c in span_cells(project)}
    rows: list[ReportRow] = []
    for work in appraisal_population(project):
        computed = {p.item: p for p in platform_answers(project, work)}
        judged = judgements_of(project, work, found.digest)
        cells: list[ReportCell] = []
        for item in found.instrument.items:
            if not item_applies(project, work, item):
                cells.append(ReportCell(item=item.id, value="n/a", state="not-applicable"))
            elif item.kind is ItemKind.PLATFORM:
                got = computed.get(item.id)
                cells.append(
                    ReportCell(
                        item=item.id,
                        value=got.status if got is not None else "pending",
                        state="computed",
                    )
                )
            elif item.kind is ItemKind.AGENT_SPAN:
                cell = spans.get((work, item.id))
                if cell is None or cell.answer is None:
                    state = "pending" if cell is None else cell.state
                    cells.append(ReportCell(item=item.id, value=state, state=state))
                else:
                    cells.append(
                        ReportCell(item=item.id, value=cell.answer.value, state=cell.state)
                    )
            elif item.id in judged:
                cells.append(
                    ReportCell(item=item.id, value=judged[item.id][0].value, state="judged")
                )
            else:
                cells.append(ReportCell(item=item.id, value="open", state="open"))
        rows.append(ReportRow(work_id=work, cells=cells))
    return AppraisalReport(instrument=found.instrument.ref, items=items, rows=rows)


def appraisal_hits(project: Project) -> list[CheckHit]:
    """The check conditions of appraisal. Nothing for a project that never declares an instrument,
    except one `systematic`-mode warning (R-41) that none is. Hits are warnings by level; a
    declared instrument never blocks."""
    from factory.services.protocol import current_protocol

    found = instrument_in_force(project)
    if found is None:
        protocol = current_protocol(project)
        if protocol is None:
            return []
        return [
            CheckHit(
                "appraisal-not-declared",
                (),
                "no appraisal instrument is declared (R-41)",
            )
        ]
    hits: list[CheckHit] = []
    open_cells = sorted(
        {c.work_id for c in span_cells(project) if c.state in ("pending", "disagreement")}
    )
    if open_cells:
        hits.append(
            CheckHit(
                "appraisal-open",
                tuple(open_cells),
                f"{len(open_cells)} work(s) have span items without a final answer",
            )
        )
    open_judgements = sorted({work for work, _ in unjudged(project)})
    if open_judgements:
        hits.append(
            CheckHit(
                "appraisal-unjudged",
                tuple(open_judgements),
                f"{len(open_judgements)} work(s) have judgement items no human has answered",
            )
        )
    stale = stale_works(project)
    if stale:
        hits.append(
            CheckHit(
                "appraisal-stale",
                tuple(stale),
                f"{len(stale)} work(s) are appraised under an instrument or conversion no "
                "longer in force",
            )
        )
    return hits


class AppraisalMethods(StrictModel):
    """What the methods statement says of appraisal; every figure is computed."""

    instrument: str
    items_by_kind: dict[str, int]
    dual_sample: float | None
    works: int
    second_pass_works: int
    """Works with a finished second pass (the dual rate is this over `works`)."""


def appraisal_methods(project: Project) -> AppraisalMethods | None:
    """None when the protocol declares no instrument, so the statement is unchanged."""
    from sqlalchemy import text

    found = instrument_in_force(project)
    if found is None:
        return None
    project.index.sync()
    kinds: dict[str, int] = {}
    for item in found.instrument.items:
        kinds[item.kind.value] = kinds.get(item.kind.value, 0) + 1
    with project.index.connect() as conn:
        second = conn.execute(
            text(
                "SELECT COUNT(DISTINCT work_id) FROM appraisal_closures "
                "WHERE pass_label = 'B' AND digest = :d"
            ),
            {"d": found.digest},
        ).scalar_one()
    return AppraisalMethods(
        instrument=found.instrument.ref,
        items_by_kind=dict(sorted(kinds.items())),
        dual_sample=found.instrument.dual_sample,
        works=len(appraisal_population(project)),
        second_pass_works=int(second),
    )


def appraisal_paragraph(m: AppraisalMethods) -> str:
    """Fixed sentences over the figures; no item is summed or graded."""
    kinds = ", ".join(f"{k} {n}" for k, n in m.items_by_kind.items())
    sample = "every work" if m.dual_sample is None else f"a sample of fraction {m.dual_sample}"
    return (
        f"Appraisal. Instrument {m.instrument}; items by kind: {kinds}. Computed items report "
        "presence only, span items were answered by two independent agent passes over "
        f"{sample}, and judgement items by a human. Works appraised: {m.works}, with a finished "
        f"second pass for {m.second_pass_works}. Items are reported singly and never summed."
    )
