"""The `costs` hub payload (plan hub-ui, page "Costs & runs"): run costs, budgets and run files.

Invariants:
- `build` is pure over its `HubContext`: it reads the project and the `ops/` listing, writes
  nothing and calls no model or network.
- Every money and token figure comes from `run_costs` (`cost_report`, `runs_with_logs`,
  `token_growth`) or `budgets.budget_status`; this module only groups, sums by day and
  restructures them. Costs are the API-equivalent price the CLI reports, never a bill.
- Events per model come from the ledger and are labelled as events, not cost.
- Run files are listed from `site_runs.run_groups`; they are not events. At most `FILE_CAP`
  files per group are listed (the group's file count is exact).
- `methods` holds the text of each info panel.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from factory.services import budgets as budgets_service
from factory.services import ledger as ledger_service
from factory.services.context import Project
from factory.services.hub_tab_help import TAB_HELP
from factory.services.run_costs import (
    CostReport,
    RunCost,
    cost_report,
    runs_with_logs,
    token_growth,
)
from factory.services.site_runs import RunGroup, run_groups

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

FILE_CAP = 200

METHODS: dict[str, str] = {
    "tab_cost": TAB_HELP["cost"],
    "summary": (
        "Totals over every headless run recorded in the project's events. Cost is the figure "
        "the CLI printed on each run's result line, the API-equivalent price of its tokens; a "
        "run whose log has no result line has no cost and is left out of the total. Units are "
        "the records or tasks a run served, counted by the MCP unit counter when it wrote one, "
        "else from the queue counts before and after."
    ),
    "over_time": (
        "Reported cost per day (UTC date of the run's start), stacked by stage or by model. "
        "Only runs that reported a cost are drawn; the days are the days on which a run started."
    ),
    "groups": (
        "One row per stage and model (and miner, for a mining stage). Cost per unit is the "
        "reported cost of the runs that have both a cost and units, divided by those units; a "
        "priced run without units is in the total but not in this figure. Per-unit tokens are "
        "the tokens of each kind over the units of the runs that served any. Median turns and "
        "duration use the complete runs only (those with a result line)."
    ),
    "treemap": (
        "The same reported cost as the table, as areas: stage, then model, then miner. An "
        "area is proportional to the group's reported cost."
    ),
    "dots": (
        "For each group with units, its tokens of one kind per unit served. A dot is one "
        "stage, model and miner; the dots of a group of runs with no units are absent."
    ),
    "growth": (
        "Each turn of a run re-reads the transcript, so the input and cache-read tokens of a "
        "turn grow with its position in the run. Per stage, the mean of input plus cache-read "
        "tokens of every run that has that turn, read from the run logs."
    ),
    "budgets": (
        "Budgets in force with what has been consumed of each in its current period, computed "
        "from the events; the share is consumed over the limit. Reported usage is what agents "
        "said they used: it is shown, never enforced."
    ),
    "events": (
        "Events each model wrote, from the ledger of the event log. This counts events, which "
        "are not cost: a model can write many cheap events or few expensive ones."
    ),
    "runs": (
        "The files under the project's ops/ folder (prompts, scripts, logs, status files) "
        "grouped by sub-folder and batch prefix, the leading token of the file name. A group "
        "is linked when a file name holds a run id or a task id that some event names. The "
        "files are not events. The folder is not part of the published project."
    ),
}


def _day(started_at: str) -> str:
    return started_at[:10]


def _group_row(g: Any) -> dict[str, Any]:
    return {
        "stage": g.stage,
        "miner": g.miner,
        "model": g.model,
        "runs": g.runs,
        "complete_runs": g.complete_runs,
        "units": g.units,
        "cost": g.reported_cost_usd,
        "cost_per_unit": g.cost_per_unit_usd,
        "median_turns": g.median_turns,
        "median_duration_s": None if g.median_duration_ms is None else g.median_duration_ms / 1000,
        "per_unit": dict(g.tokens_per_unit),
    }


def over_time(runs: list[RunCost]) -> dict[str, Any]:
    """Reported cost per UTC day, by stage and by model; days ascending, series aligned to them."""
    priced = [r for r in runs if r.cost_usd is not None]
    days = sorted({_day(r.started_at) for r in priced})
    out: dict[str, Any] = {"days": days}
    for key, label in (("by_stage", "stage"), ("by_model", "model")):
        acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for r in priced:
            acc[getattr(r, label)][_day(r.started_at)] += r.cost_usd or 0.0
        out[key] = {name: [per.get(d, 0.0) for d in days] for name, per in sorted(acc.items())}
    return out


def _runs(rows: list[RunCost]) -> list[dict[str, Any]]:
    return [
        {
            "run_id": r.run_id,
            "stage": r.stage,
            "model": r.model,
            "miner": r.miner,
            "day": _day(r.started_at),
            "cost": r.cost_usd,
            "units": r.units,
            "outcome": r.outcome,
            "complete": r.complete,
            "turns": r.turns,
        }
        for r in rows
    ]


def _budgets(ctx: HubContext) -> dict[str, Any]:
    status = budgets_service.budget_status(ctx.project)
    lines = [
        {
            "unit": ln.budget.unit,
            "scope": ln.budget.scope_user or "everyone",
            "period": str(ln.budget.period),
            "limit": ln.budget.limit,
            "consumed": ln.consumed,
            "remaining": ln.remaining,
            "share": ln.consumed / ln.budget.limit if ln.budget.limit else None,
        }
        for ln in status.budgets
    ]
    return {
        "lines": lines,
        "reported_usage": dict(status.reported_usage),
        "notice": status.notice,
    }


def _events_per_model(ctx: HubContext) -> list[dict[str, Any]]:
    slots: dict[str, dict[str, Any]] = {}
    for agent in ledger_service.ledger_report(ctx.project).ledger.agents:
        slot = slots.setdefault(
            agent.model or "unknown",
            {"model": agent.model or "unknown", "events": 0, "first": None, "last": None},
        )
        first, last = agent.first.isoformat(), agent.last.isoformat()
        slot["events"] += agent.events
        slot["first"] = first if slot["first"] is None else min(slot["first"], first)
        slot["last"] = last if slot["last"] is None else max(slot["last"], last)
    return sorted(slots.values(), key=lambda s: (-s["events"], s["model"]))


def _day_of(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%d")


def _files(groups: list[RunGroup], run_ids: set[str]) -> dict[str, Any]:
    rows = []
    for g in groups:
        files = sorted(g.files, key=lambda f: f.path)
        rows.append(
            {
                "folder": g.folder,
                "prefix": g.prefix,
                "files": len(g.files),
                "first": _day_of(g.first),
                "last": _day_of(g.last),
                "size": g.size,
                "linked": g.linked,
                "ids": list(g.ids),
                "run_ids": [i for i in g.ids if i in run_ids],
                "listed": [
                    {"path": f.path, "size": f.size, "day": _day_of(f.mtime)}
                    for f in files[:FILE_CAP]
                ],
            }
        )
    return {
        "groups": rows,
        "files": sum(len(g.files) for g in groups),
        "unlinked": sum(1 for g in groups if not g.linked),
        "file_cap": FILE_CAP,
    }


def _report_head(report: CostReport) -> dict[str, Any]:
    return {
        "caveat": report.caveat,
        "cost_source": report.cost_source,
        "runs": report.runs,
        "units": report.total_units,
        "cost": report.total_reported_cost_usd,
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `costs` page: run costs, budgets, events per model and run files."""
    pairs = runs_with_logs(ctx.project)
    report = cost_report(ctx.project, runs=pairs)
    rows = [c for c, _ in pairs]
    stages = sorted({g.stage for g in report.groups})
    growth = {
        stage: [
            {"turn": p.turn, "runs": p.runs, "mean": p.mean_context_tokens}
            for p in token_growth(ctx.project, stage, runs=pairs)
        ]
        for stage in stages
    }
    return {
        "ready": True,
        "methods": dict(METHODS),
        "summary": _report_head(report),
        "groups": [_group_row(g) for g in report.groups],
        "runs": _runs(rows),
        "over_time": over_time(rows),
        "growth": {k: v for k, v in growth.items() if v},
        "budgets": _budgets(ctx),
        "events_per_model": _events_per_model(ctx),
        "ops": _files(run_groups(ctx.project), {r.run_id for r in rows}),
    }


# ---------------------------------------------------------------- one ops file (read-only route)

OPS_FILE_CAP = 2_000_000
"""Largest ops file the route serves, in bytes."""
_OPS_TYPES: dict[str, str] = {".json": "application/json", ".jsonl": "application/x-ndjson"}


@dataclass(frozen=True)
class OpsFile:
    body: bytes
    content_type: str


def read_ops_file(project: Project, rel: str) -> OpsFile | None:
    """The file `rel` of the project's `ops/` folder, or None.

    Refused (None): an empty, absolute or `..` path, a path through or to a symlink (the resolved
    path must equal the lexical one, so containment holds), a directory, a missing file, a file
    over `OPS_FILE_CAP`. Pages are never served as pages: everything not JSON is `text/plain`."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or "\\" in rel or "\0" in rel:
        return None
    if any(p in ("", ".", "..") for p in parts):
        return None
    ops = (project.paths.dir / "ops").resolve()
    target = ops.joinpath(*parts)
    try:
        if target.resolve() != target or not target.is_file():
            return None
        if target.stat().st_size > OPS_FILE_CAP:
            return None
        body = target.read_bytes()
    except OSError:
        return None
    kind = _OPS_TYPES.get(target.suffix.lower(), "text/plain")
    return OpsFile(body, kind + "; charset=utf-8")
