"""The Flow explorer product: the PRISMA flow by source, every identified record with the step it
reached, a per-work trail, and the records that never became works.

Invariants: a projection, rebuilt from the events and written to `index.html` plus `trails.js`
(the trails load on demand, so the first paint does not wait for them). Every cell of the by-source
table is counted in the page from the same work rows that the list below shows, so a cell and the
list it links to always agree. The rows come from `flow_ledger`; the header states whether the
ledger reconciles with `prisma_flow`. Building writes no event.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from factory.services.context import Project
from factory.services.flow_ledger import (
    OTHER_GROUP,
    TOTAL,
    LedgerRow,
    flow_ledger,
    ledger_reconciles,
)
from factory.services.flow_skipped import run_gaps, skipped_records
from factory.services.flow_trails import flow_trails
from factory.services.prisma import UNSPECIFIED
from factory.services.site_flow_page import DATA_MARKER, PAGE
from factory.services.site_widgets import FUTURE_CSS

FIXED_GROUPS: Final = ("arxiv-only", "both", "openalex-only", OTHER_GROUP)
STEP_DUP: Final = "Duplicate removed"
STEP_TA: Final = "Title/abstract"
STEP_PROMOTED: Final = "Promoted to full text"
STEP_SOUGHT: Final = "Full text sought"
STEP_FT: Final = "Full text"


def tags(row: LedgerRow) -> list[str]:
    """The stage memberships of a row, the keys the by-source table counts.

    `id` every record; `dup` an absorbed duplicate not on the full-text queue; `scr` a record
    screened at title/abstract (`ta-inc`, `ta-exc`, `ta-pen` its outcome); `prom` promoted to
    full text with `ns` (not yet sought), `sought` and within it `nr` (not retrieved) or `ret`
    (retrieved); `ft-inc`, `ft-exc`, `ft-pen`, `ft-aw` the full-text outcome."""
    out = ["id"]
    if row.noncanonical_promoted:
        pass
    elif row.canonical_id is not None:
        out.append("dup")
    else:
        out.append("scr")
        out.append(
            {"included": "ta-inc", "excluded": "ta-exc"}.get(
                row.ta_outcome.value if row.ta_outcome else "", "ta-pen"
            )
        )
    if row.ft_state is not None:
        out.append("prom")
        out.append({"not-sought": "ns", "attempted-failed": "nr", "retrieved": "ret"}[row.ft_state])
        if row.ft_state != "not-sought":
            out.append("sought")
    if row.ft_outcome is not None:
        out.append(
            {"included": "ft-inc", "excluded": "ft-exc", "pending": "ft-pen", "awaiting": "ft-aw"}[
                row.ft_outcome
            ]
        )
    return out


def reached(row: LedgerRow) -> tuple[str, str, str]:
    """The (step reached, outcome, criterion or reason) of a row, the last stage it passed."""
    if row.ft_outcome is not None:
        crit = row.ft_criterion or ""
        return STEP_FT, row.ft_outcome, crit
    if row.ft_state == "retrieved":
        return STEP_FT, "retrieved, not assessed", ""
    if row.ft_state == "attempted-failed":
        return STEP_SOUGHT, "not retrieved", "; ".join(row.ft_reasons)
    if row.ft_state == "not-sought":
        return STEP_PROMOTED, "not yet sought", ""
    if row.canonical_id is not None:
        return STEP_DUP, "duplicate", row.merge_rule or ""
    outcome = row.ta_outcome.value if row.ta_outcome else "pending"
    if outcome == "included":
        return STEP_TA, "included", ""
    return STEP_TA, outcome, row.ta_criterion or ""


def _work(row: LedgerRow) -> dict[str, Any]:
    step, outcome, crit = reached(row)
    return {
        "i": row.work_id,
        "t": row.title,
        "y": row.year,
        "g": row.source_group,
        "s": row.sources,
        "st": step,
        "o": outcome,
        "c": crit,
        "p": row.canonical_id,
        "k": tags(row),
    }


def _by_count(rows: list[dict[str, Any]], tag: str, field: str = "c") -> list[str]:
    counts = Counter(w[field] or UNSPECIFIED for w in rows if tag in w["k"])
    return [key for key, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def table_spec(works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows of the by-source table: label, indent, the stage tag counted and an optional
    criterion or reason. Sub-rows list the criteria and reasons present, most frequent first."""
    spec: list[dict[str, Any]] = []

    def add(label: str, depth: int, tag: str, c: str | None = None) -> None:
        spec.append({"l": label, "d": depth, "k": tag, "c": c})

    def crits(tag: str, depth: int) -> None:
        for crit in _by_count(works, tag):
            add(crit, depth, tag, crit)

    add("Records identified", 0, "id")
    add("Duplicate records removed", 1, "dup")
    add("Records screened (title/abstract)", 0, "scr")
    add("Excluded", 1, "ta-exc")
    crits("ta-exc", 2)
    add("Included", 1, "ta-inc")
    add("Pending", 1, "ta-pen")
    add("Promoted to full text", 0, "prom")
    add("Promoted, not yet sought", 1, "ns")
    add("Sought", 1, "sought")
    add("Sought, not retrieved", 2, "nr")
    crits("nr", 3)
    add("Retrieved", 2, "ret")
    add("Excluded at full text", 3, "ft-exc")
    crits("ft-exc", 4)
    add("Included at full text", 3, "ft-inc")
    add("Pending at full text", 3, "ft-pen")
    add("Awaiting resolution", 3, "ft-aw")
    return spec


def _skipped(project: Project) -> dict[str, Any]:
    try:
        skipped = [
            [s.run_id, s.query_id, s.source, s.native_id, s.title, s.reason]
            for s in skipped_records(project)
        ]
        gaps = [
            {
                "q": g.query_id,
                "s": g.source,
                "rep": g.reported,
                "got": g.retrieved,
                "gap": g.gap,
                "runs": [
                    [r.run_id, r.status, r.reported_count, r.retrieved_count, r.skipped, r.note]
                    for r in g.runs
                ],
            }
            for g in run_gaps(project)
        ]
    except Exception as exc:  # an archived page missing or altered must not stop the product
        return {"error": f"{type(exc).__name__}: {exc}", "skipped": [], "gaps": []}
    return {"error": None, "skipped": skipped, "gaps": gaps}


def build_payload(project: Project) -> tuple[dict[str, Any], dict[str, Any]]:
    """The page payload and the trails (`work id -> steps`) for one project."""
    rows = flow_ledger(project)
    works = [_work(row) for row in rows]
    present = {w["g"] for w in works}
    groups = [*FIXED_GROUPS, *sorted(present - set(FIXED_GROUPS))]
    trails = {
        work_id: [{"at": s.at, "kind": s.kind, "d": s.d} for s in steps]
        for work_id, steps in flow_trails(project).items()
    }
    payload: dict[str, Any] = {
        "project": project.paths.slug,
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "groups": groups,
        "total": TOTAL,
        "spec": table_spec(works),
        "works": works,
        "mismatches": ledger_reconciles(project),
        **{f"skip_{k}": v for k, v in _skipped(project).items()},
    }
    return payload, trails


def _embed(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def build_flow(project: Project, out: Path) -> None:
    payload, trails = build_payload(project)
    (out / "trails.js").write_text("window.FLOW_TRAILS=" + _embed(trails) + ";", encoding="utf-8")
    (out / "index.html").write_text(
        PAGE.replace("FUTURE_OVERLAY", FUTURE_CSS).replace(DATA_MARKER, _embed(payload)),
        encoding="utf-8",
    )
