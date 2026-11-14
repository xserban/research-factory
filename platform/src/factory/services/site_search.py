"""The Search and deduplication product: every registered query with its runs and the gap between
what a source reported and what was retrieved, the records that never became works, every merge
(active or reverted) with the works it joined, and the merges whose absorbed work was screened
differently from its primary.

Invariants: a projection of the events, written to `index.html`; it writes no event. Counts come
from `search_report`, `run_gaps`, `list_merges` and `merged_after_screening`, never from the page.
A merge row names its works with their titles; a reverted merge keeps its recorded reason.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory.errors import FactoryError
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.dedup import list_merges, merged_after_screening
from factory.services.flow_skipped import _archived_pages, run_gaps, skipped_records
from factory.services.prisma import search_report
from factory.services.search import list_works
from factory.services.site_flow import _embed
from factory.services.site_search_page import DATA_MARKER, PAGE
from factory.services.site_widgets import FUTURE_CSS

MERGED_AFTER_NOTE = (
    "The canonical work's outcome stands in every count (researcher ruling 2026-11-14); "
    "these pairs are listed for review."
)


def _queries(project: Project) -> list[dict[str, Any]]:
    """One row per registered query: its text, filters, runs, gap and skipped records."""
    report = search_report(project)
    pages = _archived_pages(project)
    gaps = {g.query_id: g for g in run_gaps(project)}
    skipped: dict[str, list[list[Any]]] = {}
    for s in skipped_records(project):
        skipped.setdefault(s.query_id, []).append([s.run_id, s.native_id, s.title, s.reason])
    rows: list[dict[str, Any]] = []
    for r in report.rows:
        gap = gaps.get(r.query_id)
        rows.append(
            {
                "id": r.query_id,
                "source": r.source,
                "interface": r.interface,
                "kind": str(r.kind.value),
                "text": r.text,
                "filters": dict(r.filters),
                "purpose": str(r.purpose.value),
                "at": r.registered_at.strftime("%Y-%m-%d"),
                "reported": r.reported,
                "retrieved": r.retrieved,
                "gap": None if gap is None else gap.gap,
                "shortfall": r.shortfall_reason,
                "round": r.round_id,
                "runs": [
                    {
                        "id": run.run_id,
                        "status": str(run.status.value),
                        "rep": run.reported_count,
                        "got": run.retrieved_count,
                        "skip": run.skipped,
                        "new": run.new_works,
                        "note": run.note,
                        "pages": len(pages.get(run.run_id, [])),
                    }
                    for run in r.runs
                ],
                "skipped": skipped.get(r.query_id, []),
            }
        )
    return rows


def _merges(project: Project) -> list[dict[str, Any]]:
    """Every merge, active and reverted, with the titles of its primary and absorbed works."""
    titles = {w.id: w.title for w in list_works(project)}
    rows: list[dict[str, Any]] = []
    for m in list_merges(project):
        rows.append(
            {
                "id": m.merge_id,
                "status": str(m.status.value),
                "rule": m.rule,
                "records": m.records,
                "primary": m.primary,
                "pt": titles.get(m.primary or "", ""),
                "absorbed": [[w, titles.get(w, "")] for w in (m.absorbed or ())],
                "reason": m.reason,
                "manual": m.manual,
            }
        )
    return rows


def _counts(merges: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Merges per rule, split by status: `{rule: {active, reverted}}`."""
    out: dict[str, Counter[str]] = {}
    for m in merges:
        out.setdefault(m["rule"], Counter())[m["status"]] += 1
    return {rule: dict(c) for rule, c in sorted(out.items())}


def build_payload(project: Project) -> dict[str, Any]:
    """The page payload for one project. A missing or altered archived page is reported in
    `error` and leaves the query rows empty; the merges are still built."""
    with entering():
        return _build_payload(project)


def _build_payload(project: Project) -> dict[str, Any]:
    error: str | None = None
    queries: list[dict[str, Any]] = []
    try:
        queries = _queries(project)
    except (FactoryError, ValueError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    merges = _merges(project)
    after = [
        [
            a.merge_id,
            a.rule,
            a.primary,
            a.primary_title,
            a.primary_outcome,
            a.absorbed,
            a.absorbed_title,
            a.absorbed_outcome,
        ]
        for a in merged_after_screening(project)
    ]
    return {
        "project": project.paths.slug,
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "error": error,
        "queries": queries,
        "merges": merges,
        "rule_counts": _counts(merges),
        "after": after,
        "after_note": MERGED_AFTER_NOTE,
    }


def build_search(project: Project, out: Path) -> None:
    payload = build_payload(project)
    (out / "index.html").write_text(
        PAGE.replace("FUTURE_OVERLAY", FUTURE_CSS).replace(DATA_MARKER, _embed(payload)),
        encoding="utf-8",
    )
