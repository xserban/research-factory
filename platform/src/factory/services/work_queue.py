"""The work queue (plan 2026-11-11-feed-hub, step H4): where each paper added from the feed stands,
and the open units of work per kind. Computed from the projections; it stores nothing and writes
no event.

Invariants:
- Read-only. The index is synced before it is read; no event, blob or table is written.
- One `QueueItem` per `feed_sends` row, newest first. Its stage is read from the existing reads
  and never re-derived here: the inbox projection (`list_items`) for the item and its last lookup,
  `final_outcomes` at title/abstract, `fulltext_status` and `fulltext_queue` for the document and
  its conversion, `unit_states` for pass A extraction, `stop_unscreened` and `exclusion_criteria`
  for the stopping rule and the criterion.
- Stages, in path order: `added` (the link is open, not yet looked up), `lookup-failed` (the last
  lookup failed, or resolved to no single work), `in-corpus` (the work awaits title/abstract),
  `screened-out` (excluded at title/abstract), `screened-in` (promoted, no full text sought yet),
  `no-document` (promoted, every route tried, no full text), `full-text` (a document, not yet
  converted), `converted` (a conversion, no current extraction), `extracted` (pass A current).
- `stopped` is true when the path has ended without a decision: the link was withdrawn, the
  lookup failed, or the work is left unscreened by a stopping rule. It is never a judgement.
- `pending_work` counts the open units per task kind: the tasks `claim_next` would serve now
  (open, or claimed with a lapsed lease), excluding extraction tasks a newer task replaced.
  Keys are task kinds, so a runner can map each to its stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.index.inbox import OPEN, WITHDRAWN
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import Outcome, exclusion_criteria, final_outcomes
from factory.services.context import Project
from factory.services.extraction import abandoned_task_ids, all_scopes, unit_states
from factory.services.fulltext_screening import fulltext_queue
from factory.services.fulltext_status import WorkFulltext, fulltext_status
from factory.services.inbox import InboxItemView, list_items
from factory.services.screening import stop_unscreened
from factory.services.stages import kinds_for, task_kind
from factory.services.tasks import open_task_ids

Stage = Literal[
    "added",
    "lookup-failed",
    "in-corpus",
    "screened-out",
    "screened-in",
    "no-document",
    "full-text",
    "converted",
    "extracted",
]

STAGES: tuple[Stage, ...] = (
    "added",
    "lookup-failed",
    "in-corpus",
    "screened-out",
    "screened-in",
    "no-document",
    "full-text",
    "converted",
    "extracted",
)

_TA = ScreeningStage.TITLE_ABSTRACT
_FT = ScreeningStage.FULL_TEXT


class QueueItem(StrictModel):
    """One paper added from the feed: its entry, its inbox item, its work (None until a lookup
    resolves one), the stage it stands at, whether its path has stopped, and a short detail."""

    entry_id: str
    title: str
    inbox_item_id: str
    sent_at: str
    work_id: str | None
    stage: Stage
    stopped: bool
    detail: str


class WorkQueue(StrictModel):
    items: list[QueueItem]
    pending: dict[str, int]


@dataclass(frozen=True)
class _Facts:
    """The read-side facts the stages are taken from, read once per call."""

    outcomes: dict[str, Outcome]
    criteria: dict[str, str | None]
    fulltext: dict[str, WorkFulltext]
    converted: frozenset[str]
    extracted: frozenset[str]
    stopped: frozenset[str]


def _facts(project: Project) -> _Facts:
    outcomes = final_outcomes(project, stage=_TA)
    ft = fulltext_status(project)
    return _Facts(
        outcomes=outcomes,
        criteria=exclusion_criteria(project, stage=_TA),
        fulltext={work.work_id: work for work in ft.works},
        converted=frozenset(e.work_id for e in fulltext_queue(project).eligible),
        extracted=frozenset(
            s.work_id
            for s in unit_states(project)
            if s.pass_label is PassLabel.A and s.state == "current"
        ),
        stopped=frozenset(stop_unscreened(project)),
    )


def _work_stage(work_id: str, facts: _Facts) -> tuple[Stage, bool, str]:
    """The stage of a resolved work, with whether its path has stopped and its detail."""
    outcome = facts.outcomes.get(work_id)
    if outcome is None or outcome is Outcome.PENDING:
        if work_id in facts.stopped:
            return "in-corpus", True, "left unscreened by the stopping rule"
        return "in-corpus", False, "awaiting title/abstract screening"
    if outcome is Outcome.EXCLUDED:
        criterion = facts.criteria.get(work_id)
        return "screened-out", True, f"excluded: {criterion}" if criterion else "excluded"
    ft = facts.fulltext.get(work_id)
    if ft is None or ft.state == "unsought":
        return "screened-in", False, "awaiting full-text retrieval"
    if ft.state == "not-retrieved":
        reasons = sorted(set(ft.reasons.values()))
        detail = "no full text: " + "; ".join(reasons) if reasons else "no full text retrieved"
        return "no-document", True, detail
    if work_id not in facts.converted:
        return "full-text", False, "full text retrieved, not converted"
    if work_id not in facts.extracted:
        return "converted", False, "converted, awaiting extraction"
    return "extracted", False, "extracted"


def _item_stage(
    status: str, last_outcome: str | None, work_id: str | None, facts: _Facts
) -> tuple[Stage, bool, str]:
    if status == WITHDRAWN:
        return "added", True, "withdrawn"
    if status == OPEN:
        if last_outcome == "failed":
            return "lookup-failed", True, "lookup failed; the link stays open"
        return "added", False, "not yet looked up"
    if work_id is None:
        return "lookup-failed", True, f"lookup {last_outcome or 'failed'}"
    return _work_stage(work_id, facts)


def added_papers(project: Project) -> list[QueueItem]:
    """One item per feed send, newest first. Empty when nothing was sent. Read-only."""
    project.index.sync()
    with project.index.connect() as conn:
        sends = conn.execute(
            text(
                "SELECT s.entry_id, s.inbox_item_id, ev.ts, e.title FROM feed_sends s "
                "JOIN events ev ON ev.id = s.event_id "
                "LEFT JOIN feed_entries e ON e.entry_id = s.entry_id "
                "ORDER BY s.event_id DESC"
            )
        ).all()
    if not sends:
        return []
    items = _inbox_items(project)
    facts = _facts(project)
    out: list[QueueItem] = []
    for entry_id, item_id, sent_at, title in sends:
        item = items.get(str(item_id))
        if item is None:
            stage: Stage = "added"
            work_id, stopped, detail = None, False, "item not in the inbox"
        else:
            work_id = item.work_id
            stage, stopped, detail = _item_stage(item.status, item.last_outcome, work_id, facts)
        out.append(
            QueueItem(
                entry_id=str(entry_id),
                title="" if title is None else str(title),
                inbox_item_id=str(item_id),
                sent_at=str(sent_at),
                work_id=work_id,
                stage=stage,
                stopped=stopped,
                detail=detail,
            )
        )
    return out


def _inbox_items(project: Project) -> dict[str, InboxItemView]:
    """Every inbox item by id, from the listing's pages (its status, last lookup and work)."""
    found: dict[str, InboxItemView] = {}
    cursor: str | None = None
    while True:
        page = list_items(project, cursor=cursor)
        for view in page.items:
            found[view.item_id] = view
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return found


def pending_work(project: Project) -> dict[str, int]:
    """The open units per task kind: screening (title/abstract and full text, each pass),
    extraction (evidence and contribution) and mining (registered miners). Every kind is listed,
    with 0 when none is open. Read-only."""
    project.index.sync()
    kinds: set[str] = set()
    for label in (PassLabel.A, PassLabel.B):
        kinds.add(task_kind(_TA, label))
        kinds.add(task_kind(_FT, label))
    for scope in all_scopes(project):
        kinds.update(kinds_for(scope).values())
    abandoned = abandoned_task_ids(project)
    return {
        kind: sum(1 for task_id in open_task_ids(project, kind) if task_id not in abandoned)
        for kind in sorted(kinds)
    }


def queue(project: Project) -> WorkQueue:
    """The added papers and the pending work together. Read-only."""
    return WorkQueue(items=added_papers(project), pending=pending_work(project))
