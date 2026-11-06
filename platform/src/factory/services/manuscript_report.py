"""Status and report of a manuscript (slice 7b, plan W-C; spec ruling 17 and Manuscript
verification).

Declares: `manuscript_status`, `manuscript_report`, `report_text`, `refuse_project_path`.

Invariants:
- `manuscript_status` and `manuscript_report` read the projection only and hold no sentence: counts
  are derived, never stored. `report_text` is the one place the report meets the text, read from
  the library at render time, for the researcher's command.
- No MCP tool reads this module: the audit's rate in the report is the researcher's.
- A verdict whose unit no longer stands (its citation changed since) is shown as `detached` and
  enters no count.
- An `uncited-claim` flag is listed apart and never counted as a verdict.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.manuscripts import (
    CitationState,
    ManuscriptReport,
    ManuscriptStatus,
    ReportSentence,
    ReportUnit,
    UnitRow,
    VerdictRow,
)
from factory.services.context import Project
from factory.services.manuscript_audit import audit_report
from factory.services.manuscripts import (
    citation_rows,
    format_of,
    manuscript_text,
    require_manuscript,
    sentence_rows,
    units,
    verdict_rows,
)
from factory.writing.manuscript_render import render_report
from factory.writing.segment import mask


def refuse_project_path(project: Project, path: Path) -> None:
    """A report joins the manuscript's text, which stays out of the project's tracked tree: it goes
    to stdout or a path the researcher names, never under the project (spec ruling 8)."""
    if path.resolve().is_relative_to(project.paths.dir.resolve()):
        raise FactoryValidationError(
            [ValidationIssue("out", "a report is not written under the project")]
        )


def _flagged(project: Project, manuscript_id: str) -> set[int]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT ordinal FROM manuscript_flags WHERE manuscript_id = :m"),
            {"m": manuscript_id},
        ).all()
    return {int(r[0]) for r in rows}


def _report_unit(unit: UnitRow, verdict: VerdictRow | None) -> ReportUnit:
    state = "closed" if unit.reason is not None else "open" if verdict is None else "judged"
    return ReportUnit(
        work_id=unit.work_id,
        keys=unit.keys,
        state=state,
        reason=unit.reason,
        verdict=verdict,
    )


def _detached(verdict: VerdictRow) -> ReportUnit:
    return ReportUnit(
        work_id=verdict.work_id, keys=[], state="detached", reason=None, verdict=verdict
    )


def manuscript_report(project: Project, manuscript_id: str) -> ManuscriptReport:
    """Per cited or flagged sentence its keys, units, verdicts and closures, with the counts and
    the audit. No text of the manuscript. Refused for an unknown manuscript."""
    row = require_manuscript(project, manuscript_id)
    sentences = sentence_rows(project, manuscript_id)
    citations = citation_rows(project, manuscript_id)
    verdicts = verdict_rows(project, manuscript_id)
    flagged = _flagged(project, manuscript_id)
    by_ordinal: dict[int, list[ReportUnit]] = {}
    attached: set[tuple[int, str]] = set()
    for unit in units(project, manuscript_id):
        slot = None if unit.work_id is None else (unit.ordinal, unit.work_id)
        verdict = None if slot is None else verdicts.get(slot)
        if slot is not None and verdict is not None:
            attached.add(slot)
        by_ordinal.setdefault(unit.ordinal, []).append(_report_unit(unit, verdict))
    for slot, verdict in verdicts.items():
        if slot not in attached:
            by_ordinal.setdefault(slot[0], []).append(_detached(verdict))
    rows: list[ReportSentence] = []
    for s in sentences:
        if s.keys or s.ordinal in flagged:
            waiting = [
                k
                for k in s.keys
                if k not in citations or citations[k].state is CitationState.PROPOSED
            ]
            rows.append(
                ReportSentence(
                    ordinal=s.ordinal,
                    keys=s.keys,
                    waiting=waiting,
                    units=by_ordinal.get(s.ordinal, []),
                    uncited_flag=s.ordinal in flagged,
                )
            )
    all_units = [u for r in rows for u in r.units]
    return ManuscriptReport(
        manuscript_id=manuscript_id,
        label=row.label,
        sentences=len(sentences),
        cited=sum(1 for s in sentences if s.keys),
        verdicts=dict(
            Counter(u.verdict.verdict.value for u in all_units if u.state == "judged" and u.verdict)
        ),
        closed=dict(Counter(u.reason.value for u in all_units if u.reason is not None)),
        open_units=sum(1 for u in all_units if u.state == "open"),
        waiting=sum(1 for c in citations.values() if c.state is CitationState.PROPOSED),
        flags=len(flagged),
        audit=audit_report(project, manuscript_id),
        rows=rows,
    )


def manuscript_status(project: Project, manuscript_id: str) -> ManuscriptStatus:
    """The counts of a manuscript. Refused for an unknown manuscript."""
    report = manuscript_report(project, manuscript_id)
    states = Counter(c.state.value for c in citation_rows(project, manuscript_id).values())
    return ManuscriptStatus(
        manuscript_id=manuscript_id,
        label=report.label,
        sentences=report.sentences,
        cited=report.cited,
        citations=dict(states),
        verdicts=report.verdicts,
        closed=report.closed,
        open_units=report.open_units,
        flags=report.flags,
    )


def report_text(project: Project, manuscript_id: str) -> str:
    """The report as Markdown, with each listed sentence's text read from the library now."""
    report = manuscript_report(project, manuscript_id)
    row = require_manuscript(project, manuscript_id)
    masked = mask(manuscript_text(project, row), format_of(row.format), row.segmenter)
    wanted = {r.ordinal for r in report.rows}
    texts = {
        s.ordinal: masked[s.start : s.end]
        for s in sentence_rows(project, manuscript_id)
        if s.ordinal in wanted
    }
    return render_report(report, texts)
