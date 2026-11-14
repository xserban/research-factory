"""The ranked page of the discovery feed: a project's latest ranking beyond the shown items.

A `feed.ranked` event keeps the full ranked order in `order_blob`; `shown` lists only the shown
items. This read-only service returns the totals and the entries that follow the shown ones, in
ranked order, so the hub page can offer them as further cards.

Invariants:
- Read-only: no event is written; nothing is re-ranked (rank and score are the blob's own).
- Held entries (`held_work_id` set at fetch, held-out seeds included) are never listed and never
  counted, as in `feed_list`.
- An entry is "further" when it is in the order blob and not in the shown set (an exploration pick
  with a low rank is shown, not further). At most `cap` further entries are returned; `cut` counts
  those left out.
- The order blob is read as written; an unreadable or empty one leaves the shown items as the
  whole ranking (`total_ranked == total_shown`, no further entries).
- The reaction and add services accept a further entry and record it as beyond the shown list;
  each further item carries its latest reaction and send state, read with the totals in one pass
  over the reaction and send rows (no event-log scan).
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.model.feed import FeedReaction
from factory.services.context import Project
from factory.services.feed import ranking_order as _order
from factory.services.feed_read import feed_list
from factory.services.site_feed import _authors_list, _entry_records, _text

DEFAULT_CAP = 300


class FeedFurtherItem(StrictModel):
    """One ranked entry that is not in the shown set."""

    entry_id: str
    rank: int
    score: float
    title: str | None
    authors: tuple[str, ...]
    abstract: str | None
    reaction: FeedReaction | None = None
    sent: bool = False
    inbox_item_id: str | None = None


class FeedRankedPage(StrictModel):
    """Totals of a ranking and its entries beyond the shown ones. `ranking_id` is None before any
    ranking."""

    ranking_id: str | None
    total_ranked: int
    total_shown: int
    further: tuple[FeedFurtherItem, ...]
    cut: int
    cap: int


def feed_ranked_page(
    project: Project,
    *,
    cap: int = DEFAULT_CAP,
    records: Mapping[str, Mapping[str, object]] | None = None,
) -> FeedRankedPage:
    """The latest ranking's totals and its entries after the shown ones (see the module
    invariants). `records` are the fetch-blob records (read when omitted)."""
    cap = max(cap, 0)
    listing = feed_list(project)
    if listing.ranking_id is None:
        return FeedRankedPage(
            ranking_id=None, total_ranked=0, total_shown=0, further=(), cut=0, cap=cap
        )
    with project.index.connect() as conn:
        titles: dict[str, str] = {}
        held: set[str] = set()
        for e, t, h in conn.execute(
            text("SELECT entry_id, title, held_work_id FROM feed_entries")
        ).all():
            titles[str(e)] = str(t)
            if h is not None:
                held.add(str(e))
        reactions = {
            str(e): FeedReaction(str(r))
            for e, r in conn.execute(
                text("SELECT entry_id, reaction FROM feed_reactions ORDER BY event_id")
            ).all()
        }
        sends = {
            str(e): str(i)
            for e, i in conn.execute(text("SELECT entry_id, inbox_item_id FROM feed_sends")).all()
        }
    shown = {i.entry_id for i in listing.items}
    order = [o for o in _order(project, listing.ranking_id) if o[0] not in held]
    ranked_ids = {o[0] for o in order} | shown
    further_all = [o for o in order if o[0] not in shown]
    recs = _entry_records(project) if records is None else records
    items = tuple(
        FeedFurtherItem(
            entry_id=entry,
            rank=rank,
            score=score,
            title=titles.get(entry),
            authors=_authors_list(recs.get(entry)),
            abstract=_text(recs.get(entry), "abstract") or None,
            reaction=reactions.get(entry),
            sent=entry in sends,
            inbox_item_id=sends.get(entry),
        )
        for entry, rank, score in further_all[:cap]
    )
    return FeedRankedPage(
        ranking_id=listing.ranking_id,
        total_ranked=len(ranked_ids),
        total_shown=len(shown),
        further=items,
        cut=len(further_all) - len(items),
        cap=cap,
    )
