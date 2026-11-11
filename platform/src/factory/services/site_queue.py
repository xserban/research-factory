"""The Work queue product: the papers added from the feed, each with the stage it stands at, and
the open units of work per kind (plan 2026-11-11-feed-hub, step H4).

Invariants:
- Read-only. Every count and stage comes from `work_queue.queue`; nothing is re-derived here.
- The "Process now" buttons start disabled and do nothing yet. Step H5 wires them to the runner.
- Text from the entries and the inbox is escaped; the page has no external resources.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from factory.services.context import Project
from factory.services.work_queue import STAGES, QueueItem, WorkQueue, queue

QUEUE_CSS = (
    ".stage{display:inline-block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;"
    "padding:1px 7px;border:1px solid var(--mut);color:var(--light);white-space:nowrap}"
    ".stage.stopped{color:var(--amber);border-color:var(--amber)}"
    ".stage.extracted{color:var(--ac);border-color:var(--ac)}"
    ".qtable td,.qtable th{vertical-align:top}"
    ".proc{margin:6px 0 14px}.proc button{padding:4px 12px;margin-right:8px}"
    ".proc button:disabled{opacity:.45;cursor:not-allowed}"
    ".dim{color:var(--dim)}"
)

# Stages the runner (H5) will process, with the pending kinds each one serves.
PROCESS_STAGES: tuple[tuple[str, str, str], ...] = (
    ("screen", "Screening", "Screen the open units of title/abstract and full-text screening."),
    ("extract", "Extraction", "Extract the open units of extraction and mining."),
)


def build_queue(project: Project, out: Path) -> None:
    """Write `index.html` into `out` from the work queue. Writes no event."""
    from factory.services.site import page

    (out / "index.html").write_text(
        page("Work queue", _body(queue(project)), QUEUE_CSS), encoding="utf-8"
    )


def _body(work: WorkQueue) -> str:
    return (
        "<h1>Work queue</h1>"
        + _added_html(work.items)
        + "<h2>Pending work</h2>"
        + _pending_html(work.pending)
    )


def _added_html(items: list[QueueItem]) -> str:
    if not items:
        return "<p class=dim>No paper has been added from the feed yet.</p>"
    rows = "".join(
        "<tr>"
        f"<td>{escape(item.entry_id)}</td>"
        f"<td>{escape(item.title)}</td>"
        f"<td>{_stage_badge(item)}</td>"
        f"<td class=dim>{escape(item.detail)}</td>"
        f"<td class=dim>{escape(item.sent_at)}</td>"
        "</tr>"
        for item in items
    )
    return (
        "<table class=qtable><tr><th>Entry</th><th>Title</th><th>Stage</th><th>Detail</th>"
        f"<th>Added</th></tr>{rows}</table>"
    )


def _stage_badge(item: QueueItem) -> str:
    css = (
        "stage"
        + (" stopped" if item.stopped else "")
        + (" extracted" if item.stage == "extracted" else "")
    )
    return f"<span class='{css}'>{escape(item.stage)}</span>"


def _pending_html(pending: dict[str, int]) -> str:
    rows = "".join(
        f"<tr><td>{escape(kind)}</td><td>{count}</td></tr>"
        for kind, count in sorted(pending.items())
    )
    table = (
        f"<table class=qtable><tr><th>Task kind</th><th>Open units</th></tr>{rows}</table>"
        if rows
        else "<p class=dim>No unit of work is defined yet.</p>"
    )
    buttons = "".join(
        f"<div class=proc><strong>{escape(title)}</strong> <span class=dim>{escape(text)}</span>"
        f"<br><button type=button disabled data-stage='{stage}'>Process now</button></div>"
        for stage, title, text in PROCESS_STAGES
    )
    return table + buttons + _legend()


def _legend() -> str:
    names = ", ".join(STAGES)
    return f"<p class=dim>Stages, in path order: {escape(names)}.</p>"
