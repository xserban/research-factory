"""Consistency of copied results with their source (IDEA-23; plan EQ task 7).

A copied row is a final evidence row whose value the citing paper takes from another paper
(`independent` false, the value's `cited_work` set). When the cited paper is in the corpus and has
its own final row with identical comparability keys and method, the two values are compared
within the relative tolerance of `finders` (`hypothesis_plan.conflict_tolerance`).

Invariants:
- Read-only. The copied row stays the citing paper's statement: it never becomes independent and
  nothing is corrected. A mismatch is a flag in `check` and in the evidence report's limits.
- Statuses: `match`; `differs` (beyond the tolerance); `version-differs` (the values differ and
  the cited paper's pinned document is a later revision than its first, which the citing paper may
  not have read; revision dates are not in the projection, so the revision number stands in for
  the date); `no-source-row` (the cited paper has no comparable own row).
- Only rows of the report's groups are considered, so rows the report excludes (a retracted
  work) are not compared.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from sqlalchemy import text

from factory.extraction.numbers import normalise_text
from factory.model.base import StrictModel
from factory.modules.contract import CheckHit
from factory.services.context import Project
from factory.services.evidence_report import (
    EvidenceReport,
    EvidenceRow,
    assemble_report,
    report_inputs,
)
from factory.services.finders import _number, conflict_tolerance

CopiedStatus = Literal["match", "differs", "version-differs", "no-source-row"]
_REVISION_RE = re.compile(r"v(\d+)$")


class CopiedMismatch(StrictModel):
    """One copied row set against its source. `source_row` is None for `no-source-row`."""

    row: str
    cited_work: str
    source_row: str | None
    status: CopiedStatus


def copied_mismatches(
    project: Project, report: EvidenceReport | None = None
) -> list[CopiedMismatch]:
    """Every copied row of the report with a cited work in the corpus, against that work's own
    row of the same group and method, sorted by row key. Pass `report` to reuse one already
    built. Syncs."""
    project.index.sync()
    if report is None:
        inputs = report_inputs(project)
        if inputs is None:
            return []
        report = assemble_report(inputs)
    built = report
    tolerance = conflict_tolerance(project)
    revisions = _revisions(project)
    corpus = {r.work_id for g in built.groups for r in g.rows}
    found: list[CopiedMismatch] = []
    for group in built.groups:
        own = {
            (r.work_id, _method_key(r)): r
            for r in group.rows
            if r.independent and r.value.cited_work is None
        }
        for row in group.rows:
            cited = row.value.cited_work
            if row.independent or cited is None or cited not in corpus or cited == row.work_id:
                continue
            source = own.get((cited, _method_key(row)))
            if source is None:
                found.append(
                    CopiedMismatch(
                        row=row.row_key, cited_work=cited, source_row=None, status="no-source-row"
                    )
                )
                continue
            found.append(_compare(row, source, cited, tolerance, revisions))
    return sorted(found, key=lambda m: m.row)


def _method_key(row: EvidenceRow) -> tuple[str, str]:
    return normalise_text(row.method_name or ""), normalise_text(row.variant or "")


def _compare(
    row: EvidenceRow,
    source: EvidenceRow,
    cited: str,
    tolerance: Decimal,
    revisions: dict[str, int],
) -> CopiedMismatch:
    def make(status: CopiedStatus) -> CopiedMismatch:
        return CopiedMismatch(
            row=row.row_key, cited_work=cited, source_row=source.row_key, status=status
        )

    a, b = _number(row), _number(source)
    same_unit = normalise_text(row.value.unit or "") == normalise_text(source.value.unit or "")
    if a is None or b is None or not same_unit:
        return make("differs")
    larger = max(abs(a), abs(b))
    if larger == 0 or abs(a - b) / larger <= tolerance:
        return make("match")
    return make("version-differs" if revisions.get(cited, 1) >= 2 else "differs")


def _revisions(project: Project) -> dict[str, int]:
    """The revision number of each work's live document (`v<N>` source version), where there is
    one; 1 is the first version."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, source_version FROM fulltext_documents "
                "WHERE superseded_by IS NULL ORDER BY event_id"
            )
        ).all()
    out: dict[str, int] = {}
    for work, version in rows:
        match = _REVISION_RE.search(str(version))
        if match is not None:
            out[str(work)] = int(match.group(1))
    return out


def copied_hits(project: Project) -> list[CheckHit]:
    """`copied-value-differs` (a warning in every mode): the copied rows whose value differs from
    their source's, whether or not the difference may be a revision. Nothing without an extraction
    schema or a mismatch."""
    mismatches = [
        m for m in copied_mismatches(project) if m.status in ("differs", "version-differs")
    ]
    if not mismatches:
        return []
    return [
        CheckHit(
            "copied-value-differs",
            tuple(m.row for m in mismatches),
            f"{len(mismatches)} copied result(s) differ from the cited paper's own value; the "
            "copy stays the citing paper's statement",
        )
    ]
