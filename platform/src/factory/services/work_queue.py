"""The work queue (plan 2026-11-11-feed-hub, step H4): where each paper added from the feed stands,
and the open units of work per kind. Computed from the projections; it stores nothing and writes
no event.

Invariants:
- Read-only, except `advance`. The index is synced before it is read; no event, blob or table is
  written by `queue`, `added_papers` or `pending_work`.
- `advance` runs only the deterministic steps for feed-added papers, each through the existing
  service as the system (`project.system_actor()`; the resolve passes `automatic=True`), so
  everything it writes is recorded as that service records it: resolve the open items never
  looked up (never a `lookup-failed` one), fetch full text for `screened-in` papers,
  convert `full-text` papers with the default converter.
  Each paper is one call; one paper's error is recorded and the others go on. A process-wide lock
  serialises calls, so the hub and the runner watcher never overlap. Capped by `limit` per step.
  No model is called and no judgement is made.
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
  Keys are task kinds, so a runner can map each to its stage; the key `mining` is the exception:
  it counts the works with an open mining need (`mining_needs`), summed over miners.
- A mining need (IDEA-50): a miner listed in the protocol with `layers` or `on_demand` has a need
  for each work of its population (`miner_population`: the layer-filtered works and the
  researcher's requests) that has no `current` pass A unit. `mining_needs` is computed from the
  protocol, the requests and the unit states; it stores nothing. A feed paper at stage `extracted`
  whose work has a need is shown at stage `mining`. Limit: the queue has one item per feed send,
  so a work that did not come through the feed never appears as a queue item; its needs are still
  counted in `pending_work["mining"]` and listed by `mining_needs`. A use with `on_demand` and
  no `layers` reads its whole population automatically plus the requested works, so all of them
  can be needs.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import Field
from sqlalchemy import text

from factory.document.registry import default_converters
from factory.errors import FactoryValidationError, ValidationIssue
from factory.index.inbox import OPEN, WITHDRAWN
from factory.model.base import StrictModel
from factory.model.extraction import MinerScope
from factory.model.fulltext import Route
from factory.model.inbox import ResolveStatus
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import (
    Outcome,
    cannot_assess_open,
    exclusion_criteria,
    final_outcomes,
)
from factory.services.context import Project
from factory.services.document_convert import convert_documents
from factory.services.extraction import abandoned_task_ids, all_scopes, unit_states
from factory.services.fulltext import MAX_LIMIT, fetch_fulltext
from factory.services.fulltext_screening import fulltext_queue
from factory.services.fulltext_status import WorkFulltext, fulltext_status
from factory.services.inbox import InboxItemView, list_items, resolve_links
from factory.services.screening import stop_unscreened
from factory.services.stages import kinds_for, task_kind
from factory.services.tasks import open_task_ids
from factory.sources.fulltext.base import FullTextRoute
from factory.sources.registry import SourceFactory

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
    "mining",
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
    "mining",
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
    awaiting: frozenset[str]
    """Works with an unresolved full-text cannot-assess, for the researcher's `screen resolve`."""
    mining: dict[str, tuple[str, ...]]
    """Work id -> the listed miners with an open mining need for it."""


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
        awaiting=frozenset(cannot_assess_open(project, stage=ScreeningStage.FULL_TEXT)),
        mining=_needs_by_work(project),
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
    if work_id in facts.awaiting and work_id not in facts.extracted:
        return "converted", False, "awaiting classification (screen resolve)"
    if work_id not in facts.extracted:
        return "converted", False, "converted, awaiting extraction"
    needed = facts.mining.get(work_id)
    if needed:
        return "mining", False, "extracted, awaiting mining by " + ", ".join(needed)
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


def mining_needs(project: Project) -> dict[str, tuple[str, ...]]:
    """Miner name -> the works (sorted) that miner has an open need to mine: the works of
    `miner_population` of each protocol-listed miner that uses `layers` or `on_demand`, less those
    with a `current` pass A unit. Miners with no need are absent. Read-only; stores nothing; a
    miner whose population is refused (see `miner_population`) is skipped, not raised."""
    from factory.services.mining import miner_population  # mining imports the extraction stack
    from factory.services.protocol import current_protocol

    project.index.sync()
    protocol = current_protocol(project)
    if protocol is None:
        return {}
    found: dict[str, tuple[str, ...]] = {}
    for use in protocol.spec.miners or ():
        if not (use.layers or use.on_demand):
            continue
        try:
            population = miner_population(project, use.name)
        except FactoryValidationError:
            continue
        current = {
            s.work_id
            for s in unit_states(project, scope=MinerScope(use.name))
            if s.pass_label is PassLabel.A and s.state == "current"
        }
        open_works = tuple(sorted(set(population) - current))
        if open_works:
            found[use.name] = open_works
    return found


def _needs_by_work(project: Project) -> dict[str, tuple[str, ...]]:
    by_work: dict[str, list[str]] = {}
    for miner, works in mining_needs(project).items():
        for work in works:
            by_work.setdefault(work, []).append(miner)
    return {work: tuple(sorted(miners)) for work, miners in by_work.items()}


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
    counts = {
        kind: sum(1 for task_id in open_task_ids(project, kind) if task_id not in abandoned)
        for kind in sorted(kinds)
    }
    counts["mining"] = sum(len(works) for works in mining_needs(project).values())
    return dict(sorted(counts.items()))


def queue(project: Project) -> WorkQueue:
    """The added papers and the pending work together. Read-only."""
    return WorkQueue(items=added_papers(project), pending=pending_work(project))


# --- Automatic steps (H6) ---

AdvanceStep = Literal["resolve", "fetch", "convert"]

_ADVANCE_LOCK = threading.Lock()
"""Serialises `advance` across threads of this process: the hub's add and the runner's watcher."""


class AdvanceError(StrictModel):
    """One paper's failed step. `work_id` is None for a resolve, which has no work yet."""

    step: AdvanceStep
    item_id: str
    work_id: str | None
    reason: str


class AdvanceResult(StrictModel):
    """What one `advance` did: papers attempted and done per step, and the errors. `converted`
    counts documents with the `converted` status, `fetched` works whose full text was retrieved,
    `resolved` items whose lookup recorded a resolution (not a failure)."""

    resolve_attempted: int = 0
    resolved: int = 0
    fetch_attempted: int = 0
    fetched: int = 0
    convert_attempted: int = 0
    converted: int = 0
    convert_skipped: bool = False
    errors: list[AdvanceError] = Field(default_factory=list)


def advance(
    project: Project,
    *,
    sources: Mapping[str, SourceFactory],
    fetchers: Mapping[Route, FullTextRoute],
    convert: bool = True,
    limit: int = 20,
) -> AdvanceResult:
    """Run the due deterministic steps for the papers added from the feed, at most `limit` papers
    per step, as the system. Refuses, with nothing written, a `limit` outside 1..MAX_LIMIT.

    Resolve: each open item never looked up (stage `added`, not stopped) through `resolve_links`
    with `item_ids`; a `lookup-failed` item is not retried. Fetch: each `screened-in` paper through
    `fetch_fulltext` with its work id, under its own gating and budget. Convert (unless `convert`
    is False): each `full-text` paper through `convert_documents` with `default_converters()`.
    The stage is read again before the fetch and before the convert step, so a paper that moved
    on is seen. A paper's error is recorded and the next paper goes on.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise FactoryValidationError([ValidationIssue("limit", f"must be 1 to {MAX_LIMIT}")])
    with _ADVANCE_LOCK:
        return _advance(project, sources, fetchers, convert, limit)


def _advance(
    project: Project,
    sources: Mapping[str, SourceFactory],
    fetchers: Mapping[Route, FullTextRoute],
    convert: bool,
    limit: int,
) -> AdvanceResult:
    system = project.system_actor()
    errors: list[AdvanceError] = []
    counts = {"resolve": 0, "resolved": 0, "fetch": 0, "fetched": 0, "convert": 0, "converted": 0}

    for paper in [p for p in added_papers(project) if p.stage == "added" and not p.stopped][:limit]:
        counts["resolve"] += 1
        try:
            [outcome] = resolve_links(
                project, system, sources=sources, item_ids=[paper.inbox_item_id], automatic=True
            )
        except Exception as exc:  # one paper's error never stops the others
            errors.append(_error("resolve", paper, f"{type(exc).__name__}: {exc}"))
            continue
        if outcome.status is None:
            reason = "; ".join(f"{i.field}: {i.reason}" for i in outcome.issues)
            errors.append(_error("resolve", paper, reason or "refused"))
        elif outcome.status is ResolveStatus.FAILED:
            errors.append(_error("resolve", paper, "lookup failed; the link stays open"))
        else:
            counts["resolved"] += 1

    for paper in [p for p in added_papers(project) if p.stage == "screened-in"][:limit]:
        counts["fetch"] += 1
        if paper.work_id is None:
            continue
        try:
            summary = fetch_fulltext(
                project, routes=fetchers, work_ids=[paper.work_id], limit=limit
            )
        except Exception as exc:  # one paper's error never stops the others
            errors.append(_error("fetch", paper, f"{type(exc).__name__}: {exc}"))
            continue
        if any(work.status == "retrieved" for work in summary.works):
            counts["fetched"] += 1

    if convert:
        registry = default_converters()
        for paper in [p for p in added_papers(project) if p.stage == "full-text"][:limit]:
            counts["convert"] += 1
            if paper.work_id is None:
                continue
            try:
                done = convert_documents(project, registry, work_ids=[paper.work_id])
            except Exception as exc:  # one paper's error never stops the others
                errors.append(_error("convert", paper, f"{type(exc).__name__}: {exc}"))
                continue
            counts["converted"] += done.converted
            for doc in done.outcomes:
                if doc.status in ("failed", "raw-missing"):
                    reason = doc.reason or doc.status
                    errors.append(_error("convert", paper, f"{doc.document_id}: {reason}"))

    return AdvanceResult(
        resolve_attempted=counts["resolve"],
        resolved=counts["resolved"],
        fetch_attempted=counts["fetch"],
        fetched=counts["fetched"],
        convert_attempted=counts["convert"],
        converted=counts["converted"],
        convert_skipped=not convert,
        errors=errors,
    )


def _error(step: AdvanceStep, paper: QueueItem, reason: str) -> AdvanceError:
    return AdvanceError(
        step=step, item_id=paper.inbox_item_id, work_id=paper.work_id, reason=reason
    )
