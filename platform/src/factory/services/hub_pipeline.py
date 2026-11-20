# ruff: noqa: E501 (the information panels are long strings)
"""The `pipeline` hub payload: Control room, Work queue and Activity (parity sections 2, 22, 26).

Invariants:
- `build` is pure over its `HubContext` and reads no network. It only reads: nothing is written, and
  no model is called. The project clock supplies "now", so a build is deterministic for a given log.
- Every number is computed by an existing service and only re-shaped here: PRISMA counts
  (`prisma_flow` through the context's flow data), `pipeline.stages` and `paper_progress`,
  `work_queue.queue`, `resume.interrupted`, `runner.run_status`, `pipeline.pipeline_status`,
  `activity.activity` and `dashboard.screening_live`. The only arithmetic is a share of two computed
  counts (`pct`) and a tally of the progress cells per stage (`stage_counts`).
- Each section is guarded: a section that cannot be read is `{"error": "..."}` and the others
  stay. The page treats an error section as an empty state.
- The acts (Process all, per-stage run, Preview, Resume) are not here: the page posts to the
  existing
  `/api/queue/process` and `/api/queue/resume` routes. This payload only carries what the page needs
  to word them (the stages that apply, their pending units, the unit-cap bounds).
- `methods` holds the text of every information panel of the page.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from factory.services import activity as activity_service
from factory.services import pipeline as pipeline_service
from factory.services import resume as resume_service
from factory.services import runner as runner_service
from factory.services import work_queue as work_queue_service
from factory.services.runner import MINE_PREFIX

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.context import Project
    from factory.services.hub_build import HubContext

CELL_STATES: Final = ("done", "pending", "n/a", "stopped")
"""The four readings of one paper at one stage (`pipeline.paper_progress`)."""
HEARTBEAT_DAYS: Final = 21
RUNS_SHOWN: Final = 8

METHODS: Final[dict[str, str]] = {
    "stations": (
        "<b>The production line</b>"
        "<p><span class=k>How to read it.</span> Work moves left to right: records found, screened, "
        "read in full, converted to text, mined, synthesised, written up. A station shows how many "
        "items it holds; the share under it is the part of the previous station that arrived here.</p>"
        "<p><span class=k>How it's computed.</span> Found, screened, read in full and converted are "
        "the PRISMA flow, computed from the event log (identified records; records screened at "
        "title and abstract; full texts assessed out of those sought; full texts eligible). Mined is "
        "the current pass-A rows of the registered miners; synthesised is the pages recorded; "
        "written up is the drafts released. Nothing is typed.</p>"
    ),
    "status": (
        "<b>Where the data stands</b>"
        "<p><span class=k>How it's computed.</span> Events and the newest event id come from the "
        "event log, the code version from the factory checkout that built this hub, and the build "
        "time from this payload. The newest event id is the data version: when it changes, the "
        "pages are out of date.</p>"
    ),
    "heartbeat": (
        "<b>Events per day</b>"
        "<p><span class=k>How to read it.</span> Each bar is one day on which events were "
        "recorded (screening verdicts, rows, labels, decisions).</p>"
        "<p><span class=k>How it's computed.</span> A count of the event log by calendar day, the "
        "last days that have events.</p>"
    ),
    "queue": (
        "<b>Papers added from the feed</b>"
        "<p><span class=k>How it's computed.</span> One row per paper sent from the feed, with the "
        "stage it has reached on its path (added, looked up, screened, fetched, converted, "
        "extracted) and whether that path has stopped. Read from the work queue, never re-derived.</p>"
    ),
    "grid": (
        "<b>Paper by stage</b>"
        "<p><span class=k>How to read it.</span> One row per added paper, one column per stage that "
        "applies to this project (one per registered miner). Done: the stage has run for the paper. "
        "Pending: it is waiting. Not applicable: the stage has no unit of work for that paper. "
        "Stopped: the paper's path has ended.</p>"
        "<p><span class=k>How it's computed.</span> Read per paper by the pipeline service. The "
        "bars above the grid count the cells of each stage.</p>"
    ),
    "pending": (
        "<b>Pending work</b>"
        "<p><span class=k>How it's computed.</span> Open units of work per task kind and per stage, "
        "counted by the work queue and the pipeline. A stage that does not apply to this project "
        "has none and says why.</p>"
    ),
    "process": (
        "<b>Process now</b>"
        "<p><span class=k>What it does.</span> Starts the headless runner for one stage, or for the "
        "whole pipeline with Process all: each stage that has pending work, in order, with the "
        "automatic steps between them. It stops at the first failed run. The unit cap bounds the "
        "units one run takes; the server refuses a cap outside its limits.</p>"
        "<p>A run calls a model through the agent runner; the platform itself never does. Starting "
        "one records system events. It is available only when the hub is served and no run is open.</p>"
    ),
    "interrupted": (
        "<b>Interrupted work</b>"
        "<p><span class=k>How it's computed.</span> Read without changing anything: runs and "
        "pipelines that ended unfinished (with the usage-limit reset time, marked estimated when it "
        "is the run end plus five hours), expired task leases, stale passes, and added papers whose "
        "automatic step is undone.</p>"
        "<p><span class=k>Preview and Resume.</span> Preview plans a resume and writes nothing. "
        "Resume really starts it; the outcome is kept and shown here when it ends.</p>"
    ),
    "runs": (
        "<b>Runs</b>"
        "<p><span class=k>How it's computed.</span> The most recent runner runs and pipelines, newest "
        "first, read without reconciling (an open run whose process is gone shows as lost). While a "
        "run is open the page asks again every few seconds.</p>"
    ),
    "held": (
        "<b>Tasks held now</b>"
        "<p><span class=k>How it's computed.</span> A task is held while a session has claimed it "
        "and its lease has not ended. A holder that wrote no event for "
        f"{activity_service.STALE_MINUTES} minutes is shown as stale; its lease is still live "
        "until it ends.</p>"
    ),
    "passes": (
        "<b>Open passes</b>"
        "<p><span class=k>How to read it.</span> The bar is done over total tasks of the pass. Rate "
        "and time left are estimates.</p>"
        "<p><span class=k>How it's computed.</span> Done and total count the tasks of the pass in "
        "the index. The rate is the completions of the last "
        f"{activity_service.RATE_WINDOW_MINUTES} minutes scaled to an hour; the time left is the "
        "remaining tasks over that rate, unknown while the rate is zero. A pass with no held task "
        f"and no completion for {activity_service.DORMANT_HOURS} hours is dormant.</p>"
    ),
    "operations": (
        "<b>Long operations</b>"
        "<p><span class=k>How it's computed.</span> One row per operation that reports its progress "
        "to the project folder, with elapsed time and, when it has a rate, the time left. These "
        "files are not part of the record.</p>"
    ),
    "traces": (
        "<b>Worker traces</b>"
        "<p><span class=k>How it's computed.</span> The headless workers' trace files changed in the "
        f"last {activity_service.TRACE_WINDOW_MINUTES // 60} hours, with the last line of each.</p>"
    ),
    "screening": (
        "<b>Screening live</b>"
        "<p><span class=k>How to read it.</span> Verdicts of the title and abstract screening under "
        "the current protocol: totals per pass, the sessions active in the last hour, how far each "
        "stopping rule has run, and the latest decisions.</p>"
        "<p><span class=k>How it's computed.</span> From the screening decisions in the index as of "
        "the time this page was built; it is not refreshed while the page is open.</p>"
    ),
}

BLURBS: Final[dict[str, str]] = {
    "protocol": "The question, criteria, decisions, press reviews and deviations.",
    "overview": "The state of the review at a glance.",
    "pipeline": "Where the work stands and what runs next.",
    "corpus": "Browse the papers and open any one with its quotes.",
    "flow": "Where the records went, step by step.",
    "lenses": "Slice the corpus by what the papers do.",
    "explore": "Search and filter the coded papers.",
    "graph": "Who cites whom, and where the foundations lie.",
    "landscape": "How the techniques cluster.",
    "sources": "Search, deduplication, full-text acquisition, conversion and documents.",
    "method": "Lifecycle, steps and taxonomy.",
    "miners": "How each reading was made and how stable it is.",
    "data": "The extracted values, row by row.",
    "findings": "What the miners found.",
    "write": "Synthesis pages, bibliography and exports.",
    "living": "New papers, how current the review is, and its heartbeat.",
    "costs": "Run costs and the runs behind them.",
    "platform": "Capabilities and the backlog.",
    "chat": "Spar with an agent over the corpus; you rate each argument and write the balance.",
    "contradictions": "Pairs of papers that may disagree, and your decisions on them.",
}


def _guard(fn: Callable[[], Any]) -> Any:
    """`fn()`, or `{"error": ...}`: a section that cannot be read never takes the page down."""
    try:
        return fn()
    except Exception as exc:  # a panel must never take the page down
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _pct(n: int | None, of: int | None) -> int | None:
    """The share of `n` in `of` as a whole percent; None when it is not defined."""
    if n is None or not of:
        return None
    return round(100 * n / of)


def _count(project: Project, sql: str) -> int:
    with project.index.connect() as conn:
        return int(conn.execute(text(sql)).scalar() or 0)


def stations(ctx: HubContext, pending: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """The seven stations of the production line with their counts and the share kept from the
    previous one. PRISMA stations come from the flow data, the rest from the index. `pending` is
    `pipeline.pending_by_stage`: the open units of the stages that apply, shown under the station
    that runs them (screening; the extraction and miner stages for mining)."""
    pending = pending or {}
    mining = [v for k, v in pending.items() if k == "extract" or k.startswith(MINE_PREFIX)]
    project = ctx.project
    prisma = ctx.flow_data.prisma
    ft = prisma.full_text
    identified = sum(prisma.identified_databases.values()) + sum(prisma.identified_other.values())
    rows = _count(
        project,
        "SELECT COUNT(*) FROM extraction_rows WHERE superseded_by IS NULL "
        "AND pass_label = 'A' AND schema_ref LIKE 'm-%'",
    )
    pages = _count(project, "SELECT COUNT(*) FROM events WHERE type = 'page.recorded'")
    drafts = _count(project, "SELECT COUNT(*) FROM events WHERE type = 'draft.released'")
    sought = ft.sought if ft.stage_run else None
    assessed = ft.assessed if ft.stage_run else None
    eligible = ft.eligible if ft.stage_run else None
    raw: list[dict[str, Any]] = [
        {"key": "search", "label": "Search", "n": identified, "of": None, "page": "sources"},
        {
            "key": "screen",
            "label": "Screen",
            "n": prisma.screened,
            "of": identified,
            "page": "flow",
        },
        {"key": "fulltext", "label": "Full text", "n": assessed, "of": sought, "page": "sources"},
        {"key": "convert", "label": "Convert", "n": eligible, "of": sought, "page": "sources"},
        {"key": "mine", "label": "Mine", "n": rows, "of": None, "page": "miners"},
        {"key": "synthesize", "label": "Synthesise", "n": pages, "of": None, "page": "write"},
        {"key": "report", "label": "Write up", "n": drafts, "of": None, "page": "write"},
    ]
    waiting = {"screen": pending.get("screen"), "mine": sum(mining) if mining else None}
    return [
        {**s, "pct": _pct(s["n"], s["of"]), "sub": SUBS[s["key"]], "pending": waiting.get(s["key"])}
        for s in raw
    ]


SUBS: Final[dict[str, str]] = {
    "search": "records found",
    "screen": "records screened",
    "fulltext": "full texts assessed",
    "convert": "texts converted",
    "mine": "rows read",
    "synthesize": "pages recorded",
    "report": "drafts released",
}


def status(ctx: HubContext) -> dict[str, Any]:
    """Events total, newest event id and time, the factory code version and the build time."""
    from factory.services.site import code_version

    project = ctx.project
    project.index.sync()
    with project.index.connect() as conn:
        total, last_at = conn.execute(text("SELECT COUNT(*), MAX(ts) FROM events")).one()
    try:
        version: str | None = code_version()
    except Exception:  # not a checkout, or git is absent
        version = None
    return {
        "events_total": int(total or 0),
        "last_event_id": project.index.last_event_id(),
        "last_event_at": None if last_at is None else str(last_at),
        "code_version": version,
        "built_at": project.clock.now().isoformat(timespec="seconds"),
    }


def heartbeat(project: Project, days: int = HEARTBEAT_DAYS) -> list[list[Any]]:
    """Events per calendar day, the last `days` days that have events, oldest first."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT substr(ts, 1, 10) AS d, COUNT(*) FROM events GROUP BY d "
                "ORDER BY d DESC LIMIT :n"
            ),
            {"n": days},
        ).all()
    return [[str(d), int(n)] for d, n in reversed(rows)]


def page_cards() -> list[dict[str, str]]:
    """One card per hub page: id, title and what it holds (from `hub_ui.PAGES`)."""
    from factory.services import hub_ui

    return [
        {"id": p.id, "title": p.title, "blurb": BLURBS.get(p.id, "")}
        for p in hub_ui.PAGES.values()
        if p.id != "kit"
    ]


def queue_section(project: Project, plan: list[pipeline_service.PipelineStage]) -> dict[str, Any]:
    """The added papers, the pending kinds, the progress cells and their tally per stage."""
    work = work_queue_service.queue(project)
    columns = [s for s in plan if s.applies and s.key != "intuition"]
    progress = (
        pipeline_service.paper_progress(project, work.items, plan) if work.items and columns else {}
    )
    counts: dict[str, dict[str, int]] = {}
    for stage in columns:
        tally = Counter(progress.get(i.entry_id, {}).get(stage.key, "n/a") for i in work.items)
        counts[stage.key] = {state: tally.get(state, 0) for state in CELL_STATES}
    return {
        "items": [i.model_dump(mode="json") for i in work.items],
        "pending": work.pending,
        "columns": [{"key": s.key, "label": s.label} for s in columns],
        "progress": progress,
        "stage_counts": counts,
        "by_stage": dict(Counter(i.stage for i in work.items)),
        "stopped": sum(1 for i in work.items if i.stopped),
        "stage_order": list(work_queue_service.STAGES),
    }


def runs_section(project: Project) -> dict[str, Any]:
    """The latest runs and pipelines (read without reconciling) and whether one is open."""
    runs = runner_service.run_status(project, reconcile=False, limit=RUNS_SHOWN)
    pipes = pipeline_service.pipeline_status(project, limit=RUNS_SHOWN)
    return {
        "runs": [r.model_dump(mode="json") for r in runs],
        "pipelines": [p.model_dump(mode="json") for p in pipes],
        "run_open": runner_service.has_open_run(project),
        "pipeline_open": any(p.status == "running" for p in pipes),
    }


def interrupted_section(project: Project) -> dict[str, Any]:
    """`resume.interrupted` as JSON with `is_clean` and the panel's text lines."""
    from factory.services.site_queue import summary_lines

    found = resume_service.interrupted(project)
    return {
        **found.model_dump(mode="json"),
        "is_clean": found.is_clean,
        "lines": summary_lines(found),
    }


def activity_section(project: Project) -> dict[str, Any]:
    """The four activity panels as of the project clock, with the constants the text states."""
    found = activity_service.activity(project, project.clock.now())
    return {
        **found.model_dump(mode="json"),
        "stale_minutes": activity_service.STALE_MINUTES,
        "rate_window_minutes": activity_service.RATE_WINDOW_MINUTES,
        "dormant_hours": activity_service.DORMANT_HOURS,
        "trace_window_minutes": activity_service.TRACE_WINDOW_MINUTES,
    }


def screening_section(project: Project) -> Any:
    from factory.services.dashboard import screening_live

    return screening_live(project)


def next_actions(project: Project) -> list[dict[str, Any]]:
    from factory.services.human_queue import human_queue

    return [i.model_dump(mode="json") for i in human_queue(project).items]


def build(ctx: HubContext) -> dict[str, Any]:
    """The `pipeline` payload. See the module docstring for its shape."""
    project = ctx.project
    plan = _guard(lambda: pipeline_service.stages(project))
    stage_rows = [] if isinstance(plan, dict) else [s.model_dump(mode="json") for s in plan]
    return {
        "slug": project.paths.slug,
        "generated": project.clock.now().isoformat(timespec="seconds"),
        "status": _guard(lambda: status(ctx)),
        "stations": _guard(
            lambda: (
                stations(ctx, {s.key: s.pending for s in plan if s.applies})
                if not isinstance(plan, dict)
                else stations(ctx)
            )
        ),
        "pages": page_cards(),
        "next_actions": _guard(lambda: next_actions(project)),
        "heartbeat": _guard(lambda: heartbeat(project)),
        "stages": stage_rows,
        "unit_cap": {
            "default": runner_service.DEFAULT_UNIT_CAP,
            "max": runner_service.MAX_UNIT_CAP,
        },
        "queue": _guard(lambda: queue_section(project, [] if isinstance(plan, dict) else plan)),
        "runs": _guard(lambda: runs_section(project)),
        "interrupted": _guard(lambda: interrupted_section(project)),
        "activity": _guard(lambda: activity_section(project)),
        "screening_live": _guard(lambda: screening_section(project)),
        "methods": dict(METHODS),
        "ready": True,
    }
