"""The read side of the discovery feed (slice 4c, F6, decision 118): the latest ranking, or a named
one, as a listing for a person or an agent.

Invariants:
- Read-only: no event is written. The projection is synchronised as the other read services do.
- The listing shows only what the ranking showed: its items come from the ranking's `shown` list,
  in that order, and `top` takes a prefix of it. Nothing is re-ranked or added.
- An entry whose work the corpus holds (`held_work_id` set) is never listed, even if a ranking
  named it; held-out seeds' works are included in that rule (R-F4).
- A reaction is the entry's latest human reaction on any ranking (by event order), or None.
  `sent` is true when the entry has a `feed_sends` row; `inbox_item_id` then names its item.
- Titles are looked up in the corpus for the nearest reference only; a reference that is no
  longer in the corpus has a None title. Refusal of a session that has joined a pass is made by
  the MCP layer, not here.
- With no ranking the listing is empty and says why. A named `ranking_id` that does not exist is
  refused (`ranking_id: unknown`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.feed import FeedReaction, FeedShown
from factory.services.agreement import Outcome
from factory.services.context import Project
from factory.services.feed import current_config
from factory.services.search import get_work


class FeedListItem(StrictModel):
    """One shown entry of a ranking, with its reaction and send state."""

    entry_id: str
    title: str | None
    rank: int
    score: float
    explore: bool
    nearest_reference: str | None
    nearest_reference_title: str | None
    reaction: FeedReaction | None
    sent: bool
    inbox_item_id: str | None


class FeedListing(StrictModel):
    """A ranking's shown items in shown order. `ranking_id` is None, and `reason` says why, when
    no ranking exists."""

    ranking_id: str | None
    reference_hash: str | None
    reason: str | None
    items: tuple[FeedListItem, ...]


def _ranking_row(project: Project, ranking_id: str | None) -> tuple[str, str, str] | None:
    """`(ranking_id, reference_hash, shown_json)` of the named ranking, or of the latest one."""
    with project.index.connect() as conn:
        if ranking_id is None:
            row = conn.execute(
                text(
                    "SELECT ranking_id, reference_hash, shown FROM feed_rankings "
                    "ORDER BY event_id DESC LIMIT 1"
                )
            ).first()
        else:
            row = conn.execute(
                text(
                    "SELECT ranking_id, reference_hash, shown FROM feed_rankings "
                    "WHERE ranking_id = :r"
                ),
                {"r": ranking_id},
            ).first()
    if row is None:
        return None
    return str(row[0]), str(row[1]), str(row[2])


def feed_list(
    project: Project, *, ranking_id: str | None = None, top: int | None = None
) -> FeedListing:
    """The latest ranking (or `ranking_id`) as a listing of at most `top` items (all when None).

    Refused with `ranking_id: unknown` when a named ranking does not exist. Empty, with a reason,
    before any ranking. See the module invariants."""
    project.index.sync()
    found = _ranking_row(project, ranking_id)
    if found is None:
        if ranking_id is not None:
            raise FactoryValidationError([ValidationIssue("ranking_id", "unknown")])
        return FeedListing(ranking_id=None, reference_hash=None, reason="no ranking yet", items=())
    ranking, reference_hash, shown_json = found
    shown = [FeedShown.model_validate(item) for item in json.loads(shown_json)]
    if top is not None:
        shown = shown[: max(top, 0)]

    with project.index.connect() as conn:
        titles: dict[str, str] = {}
        held: set[str] = set()
        for e, t, h in conn.execute(
            text("SELECT entry_id, title, held_work_id FROM feed_entries")
        ).all():
            titles[str(e)] = str(t)
            if h is not None:
                held.add(str(e))
        reactions: dict[str, FeedReaction] = {}
        for entry_id, reaction in conn.execute(
            text("SELECT entry_id, reaction FROM feed_reactions ORDER BY event_id")
        ).all():
            reactions[str(entry_id)] = FeedReaction(str(reaction))
        sends = {
            str(e): str(i)
            for e, i in conn.execute(text("SELECT entry_id, inbox_item_id FROM feed_sends")).all()
        }

    works: dict[str, str | None] = {}

    def work_title(work_id: str | None) -> str | None:
        if work_id is None:
            return None
        if work_id not in works:
            work = get_work(project, work_id)
            works[work_id] = work.title if work is not None else None
        return works[work_id]

    items: list[FeedListItem] = []
    for s in shown:
        if s.entry_id in held:
            continue
        item_id = sends.get(s.entry_id)
        items.append(
            FeedListItem(
                entry_id=s.entry_id,
                title=titles.get(s.entry_id),
                rank=s.rank,
                score=s.score,
                explore=s.explore,
                nearest_reference=s.nearest_reference,
                nearest_reference_title=work_title(s.nearest_reference),
                reaction=reactions.get(s.entry_id),
                sent=item_id is not None,
                inbox_item_id=item_id,
            )
        )
    return FeedListing(
        ranking_id=ranking,
        reference_hash=reference_hash,
        reason=None,
        items=tuple(items),
    )


class ScopeDrift(StrictModel):
    """The scope-drift count (ruling 12): sent works screened at title/abstract, those excluded,
    the declared threshold and minimum count, and whether the finding holds."""

    screened: int
    excluded: int
    excluded_works: tuple[str, ...]
    threshold: float
    min_count: int
    holds: bool


def feed_work_ids(project: Project) -> frozenset[str]:
    """The works that came through a feed send: the work each resolved send's inbox item resolved
    to. A send whose item is not resolved yet has no work."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT r.work_id FROM feed_sends s JOIN inbox_resolutions r"
                " ON r.item_id = s.inbox_item_id"
                " WHERE r.status = 'resolved' AND r.work_id IS NOT NULL"
            )
        ).all()
    return frozenset(str(row[0]) for row in rows)


def pending_sends(project: Project) -> int:
    """Sends whose inbox item is still open (awaiting resolution)."""
    project.index.sync()
    with project.index.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM feed_sends s JOIN inbox_items i"
                " ON i.item_id = s.inbox_item_id WHERE i.status = 'open'"
            )
        ).scalar_one()
    return int(count)


def scope_drift(project: Project, outcomes: Mapping[str, Outcome]) -> ScopeDrift | None:
    """The drift count of the project's feed, or None without a feed configuration.

    Among the works sent through the feed, those screened at title/abstract (an outcome other
    than pending) are counted, and those excluded. The finding holds when the screened count is at
    least `drift_min_count` and the excluded share is at least `drift_threshold`. A count, not a
    judgement: the feed never changes the criteria. `outcomes` is the title/abstract outcome of
    every corpus work; a work without one counts as pending."""
    config = current_config(project)
    if config is None:
        return None
    screened = [w for w in sorted(feed_work_ids(project)) if _screened(outcomes.get(w))]
    excluded = tuple(w for w in screened if outcomes[w] is Outcome.EXCLUDED)
    # min_count >= 1 makes screened non-empty before the division.
    holds = len(screened) >= config.drift_min_count and (
        len(excluded) / len(screened) >= config.drift_threshold
    )
    return ScopeDrift(
        screened=len(screened),
        excluded=len(excluded),
        excluded_works=excluded,
        threshold=config.drift_threshold,
        min_count=config.drift_min_count,
        holds=holds,
    )


def _screened(outcome: Outcome | None) -> bool:
    return outcome is not None and outcome is not Outcome.PENDING
