"""The citations product: how often each work is cited by the other works of the project (IDEA-57).

Three tables: the works most cited inside the corpus, the same count per year since publication,
and the works the corpus cites that are not in it (snowball candidates). All numbers come from
`services/citations.py`. The in-corpus count is a lower bound and the page prints both
denominators; a work with no count shows "unknown", never 0. The external count is the one stored
in the work record (OpenAlex), shown beside the in-corpus count and never merged with it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from factory.services.citations import CitationReport, citation_report
from factory.services.context import Project
from factory.services.site_widgets import REPORT_CSS, note, section, table

TOP = 50


def _count(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def render_citations(report: CitationReport) -> str:
    """The page body for a report."""
    ranked = sorted(
        (w for w in report.works if w.cited_by),
        key=lambda w: (-(w.cited_by or 0), w.title, w.work_id),
    )
    rows = [
        [w.title, w.year or "", _count(w.cited_by), _count(w.self_cited_by), _count(w.external)]
        for w in ranked[:TOP]
    ]
    rated = sorted(
        (w for w in ranked if w.per_year is not None),
        key=lambda w: (-(w.per_year or 0), w.title, w.work_id),
    )
    rate_rows = [[w.title, w.year or "", f"{w.per_year:.2f}", w.cited_by] for w in rated[:TOP]]
    cand_rows = [
        [c.title, c.year or "", c.citing_count, c.dois[0] if c.dois else (c.arxivs or ("",))[0]]
        for c in report.candidates[:TOP]
    ]
    unknown = report.extractions == 0
    head = (
        f"<p class=dim>Counts come from {report.extractions} works whose reference list was "
        f"extracted ({report.entries} entries, of which {report.resolved_links} resolved to a "
        f"work of the project), out of {report.works_total} works. A count is a lower bound: a "
        "work cited only by works without an extracted list shows 0 here. A citing work counts "
        "once, and a work does not cite itself.</p>"
    )
    if unknown:
        head += note("No reference list has been extracted: every in-corpus count is unknown.")
    return (
        "<h1>Citations inside the corpus</h1>"
        + head
        + section(
            f"Most cited by corpus works (top {min(TOP, len(rows))})",
            table(["work", "year", "cited by", "of which self", "OpenAlex count"], rows)
            if rows
            else "<p class=dim>No work is cited by another work of the corpus yet.</p>",
        )
        + section(
            "Citations per year since publication",
            table(["work", "year", "per year", "cited by"], rate_rows)
            if rate_rows
            else "<p class=dim>Nothing to rank.</p>",
        )
        + section(
            f"Cited by the corpus, not in it (snowball candidates, top {min(TOP, len(cand_rows))})",
            table(["cited item", "year", "citing works", "identifier"], cand_rows)
            if cand_rows
            else "<p class=dim>None.</p>",
        )
        + note(
            "Self-citation: a citing work that shares an author name with the cited work. "
            f"The per-year figure counts the publication year as one, up to {report.as_of_year}."
        )
    )


def build_citations(project: Project, out: Path) -> None:
    from factory.services.site import page

    report = citation_report(project, as_of_year=datetime.now(UTC).year)
    (out / "index.html").write_text(
        page("Citations", render_citations(report), REPORT_CSS), encoding="utf-8"
    )
