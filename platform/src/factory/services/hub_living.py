"""Living-page analytics for the hub (plan hub-ui, step 8): feed river, horizon, heartbeat.

Pure functions over plain rows (`FeedRow`, `HorizonView`, `(day, type, count)` triples) plus thin
read-only loaders. Nothing here calls a model or writes. The feed loader reads the feed projection
(`feed_entries`, `feed_fetches`, `feed_rankings` through `feed_list`, `feed_reactions`,
`feed_sends`); the horizon reuses `horizon_view`; the heartbeat reads the index's `events` table
(one grouped query, no JSONL parsing). `METHODS` holds the plain-English definitions shown to the
researcher.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import text

from factory.model.views import HorizonView
from factory.services.context import Project
from factory.services.dashboard import _feed_activity
from factory.services.feed_categories import primary_category, propose_categories
from factory.services.feed_read import feed_list
from factory.services.horizon import horizon_view
from factory.services.protocol import current_protocol
from factory.services.site_hub_feed import collect as collect_feed
from factory.services.updates import updates_view

METHODS: dict[str, str] = {
    "feed_river": (
        "Each feed entry is placed on the day of the fetch that first brought it in (the end "
        "date of that fetch's window). Rank and score are those of the latest ranking, and are "
        "empty for entries it did not show. A reaction is the entry's latest reaction by the "
        "researcher. Entries whose work the corpus already holds are not listed (they are not "
        "new), as in the feed listing. "
        "Counts per day are entries, entries shown by the latest ranking, entries sent to the "
        "inbox, and reactions by kind. The top entries of a day are the best-ranked ones "
        "(smallest rank first; unranked entries follow by entry id)."
    ),
    "horizon": (
        "For each source, the date of its latest finished search or chase run, and the number "
        "of days between that date and today. The publication years are those of the works the "
        "activity series cover (included works per confirmed idea, new ideas, new lineage "
        "edges, records); works published after a source's latest search are not in the "
        "corpus. The series, and so the years, stay empty until the project holds a confirmed "
        "idea, a lineage edge or a record group; they are not read from the corpus itself."
    ),
    "heartbeat": (
        "Events per day by family, from the index's event table, which records the type and "
        "time of every event in the project's log. One grouped query counts them; no log file "
        "is parsed. A day is the UTC date of the event time. Each event type belongs to exactly "
        "one family (search, screening, acquisition, conversion, mining, references, feed, "
        "other); a type that is not in the table counts as other, and so do the synthesis pages "
        "the agent records (`page.recorded`)."
    ),
}

METHODS.update(
    {
        "feed_status": (
            "Read from the feed events of this project: the configuration last recorded, the "
            "window of the latest fetch (incomplete when the source did not return everything), "
            "the reference set the latest ranking was computed against and how many references "
            "it held, the entries held back (works of held-out seeds, never shown), and whether "
            "a fetch is due today. Due is computed from the date of the last complete window and "
            "the configured interval; nothing here starts a run."
        ),
        "feed_cards": (
            "The cards are the shown items of the latest ranking, in shown order, with the "
            "abstract, authors and submission date the fetch recorded. Rank and score are the "
            "ranker's own and nothing is re-ranked here. The nearest core work is the reference "
            "the entry scored highest against. Ranked entries beyond the shown ones come after, "
            "at most the listed cap; the rest are counted, not listed. A reaction or an add on "
            "such a card is recorded as beyond the shown list."
        ),
        "reactions": (
            "Reactions are the ones recorded on feed entries. Over time: reactions per day of the "
            "event that recorded them, by kind. Per category: each reacted entry counts once, by "
            "its latest reaction, under the first arXiv category of its record; accepted is "
            "like or save, rejected is dislike or dismiss, and the rate is the share of the "
            "category's reacted entries. Entries without a category are counted under none."
        ),
        "updates": (
            "What entered the corpus since the last snapshot, and how each snapshot counted: "
            "read from the snapshot events and the corpus, as the updates view computes it. "
            "Every addition carries the route that brought it in (inbox, feed, watch, chase, "
            "search, other) as recorded on its first provenance event."
        ),
        "watch": (
            "The weekly watch plan as the current protocol records it: per source the mode, the "
            "interval, the last finished cycle, when the next is due, and the weekly windows run "
            "since the last full replay. Sources run in window mode; a full re-run never happens "
            "automatically."
        ),
        "growth": (
            "Included works per snapshot, and the counts each snapshot froze (identified, "
            "screened, included, identified by route). They are the snapshot's own numbers; "
            "none is recomputed here."
        ),
    }
)

TOP_K = 5
OTHER = "other"
FAMILIES = (
    "search",
    "screening",
    "acquisition",
    "conversion",
    "mining",
    "references",
    "feed",
    OTHER,
)

FAMILY_OF_PREFIX: dict[str, str] = {
    # search: finding and importing records
    "search": "search",
    "query": "search",
    "probe": "search",
    "chase": "search",
    "grey": "search",
    "watch": "search",
    "seed": "search",
    "import": "search",
    "work": "search",
    "dedup": "search",
    # screening
    "screening": "screening",
    "calibration": "screening",
    "audit": "screening",
    "ranking": "screening",
    "gate": "screening",
    "review": "screening",
    # acquisition
    "fulltext": "acquisition",
    "file": "acquisition",
    "inbox": "acquisition",
    "library": "acquisition",
    # `page.recorded` is a synthesis page the agent wrote (kind "synthesis"), not a fetched page:
    # it is no acquisition and no search, so it is counted as other, stated here.
    "page": OTHER,
    # conversion
    "document": "conversion",
    # mining and extraction
    "extraction": "mining",
    "mine": "mining",
    "miner": "mining",
    "mining": "mining",
    "appraisal": "mining",
    "taxonomy": "mining",
    "label": "mining",
    "term": "mining",
    "vocabulary": "mining",
    "interpretation": "mining",
    "concept": "mining",
    # references
    "reference": "references",
    "snowball": "references",
    "citation": "references",
    # feed
    "feed": "feed",
    # explicit other: project set-up, decisions, writing, lab, lineage, regions
    "baseline": OTHER,
    "credential": OTHER,
    "sheet": OTHER,
    "spar": OTHER,
    "user": OTHER,
    "briefing": OTHER,
    "budget": OTHER,
    "card": OTHER,
    "chat": OTHER,
    "check": OTHER,
    "conclusion": OTHER,
    "consolidation": OTHER,
    "contradiction": OTHER,
    "curation": OTHER,
    "decision": OTHER,
    "digest": OTHER,
    "direction": OTHER,
    "draft": OTHER,
    "experiment": OTHER,
    "hypothesis": OTHER,
    "idea": OTHER,
    "lead": OTHER,
    "ledger": OTHER,
    "living": OTHER,
    "manuscript": OTHER,
    "member": OTHER,
    "model": OTHER,
    "notice": OTHER,
    "project": OTHER,
    "protocol": OTHER,
    "question": OTHER,
    "region": OTHER,
    "relation": OTHER,
    "runner": OTHER,
    "task": OTHER,
    "version": OTHER,
    "xrun": OTHER,
}


def family_of(event_type: str) -> str:
    """The family of an event type, by its prefix before the first dot; `other` when unknown."""
    return FAMILY_OF_PREFIX.get(event_type.split(".", 1)[0], OTHER)


# feed river -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedRow:
    """One feed entry, flattened. `rank` and `score` are None when the latest ranking did not
    show it; `reaction` is the latest reaction or None."""

    entry_id: str
    title: str
    day: str
    rank: int | None
    score: float | None
    reaction: str | None
    sent: bool


@dataclass(frozen=True)
class FeedDay:
    day: str
    count: int
    shown: int
    sent: int
    reactions: dict[str, int]
    top: tuple[FeedRow, ...]


@dataclass(frozen=True)
class FeedRiver:
    total: int
    days: tuple[FeedDay, ...]


def _top_key(row: FeedRow) -> tuple[int, int, str]:
    return (0, row.rank, row.entry_id) if row.rank is not None else (1, 0, row.entry_id)


def feed_river(rows: Iterable[FeedRow], top_k: int = TOP_K) -> FeedRiver:
    """Entries per day, oldest day first, with counts and the best-ranked `top_k` of each day."""
    by_day: dict[str, list[FeedRow]] = defaultdict(list)
    for row in rows:
        by_day[row.day].append(row)
    days: list[FeedDay] = []
    for day in sorted(by_day):
        entries = by_day[day]
        reactions = Counter(r.reaction for r in entries if r.reaction is not None)
        days.append(
            FeedDay(
                day=day,
                count=len(entries),
                shown=sum(1 for r in entries if r.rank is not None),
                sent=sum(1 for r in entries if r.sent),
                reactions=dict(sorted(reactions.items())),
                top=tuple(sorted(entries, key=_top_key)[: max(top_k, 0)]),
            )
        )
    return FeedRiver(total=sum(d.count for d in days), days=tuple(days))


def load_feed_rows(project: Project) -> list[FeedRow]:
    """The feed projection as rows: every non-held entry, its latest-ranking rank and score, its
    latest reaction and send state. Read-only."""
    ranked = {i.entry_id: i for i in feed_list(project).items}  # syncs the index
    with project.index.connect() as conn:
        entries = conn.execute(
            text(
                "SELECT e.entry_id, e.title, f.window_to FROM feed_entries e "
                "JOIN feed_fetches f ON f.fetch_id = e.first_fetch_id "
                "WHERE e.held_work_id IS NULL ORDER BY e.entry_id"
            )
        ).all()
        reactions = {
            str(e): str(r)
            for e, r in conn.execute(
                text("SELECT entry_id, reaction FROM feed_reactions ORDER BY event_id")
            ).all()
        }
        sent = {str(e) for (e,) in conn.execute(text("SELECT entry_id FROM feed_sends")).all()}
    out: list[FeedRow] = []
    for entry_id, title, day in entries:
        item = ranked.get(str(entry_id))
        out.append(
            FeedRow(
                entry_id=str(entry_id),
                title=str(title),
                day=str(day),
                rank=item.rank if item is not None else None,
                score=item.score if item is not None else None,
                reaction=reactions.get(str(entry_id)),
                sent=str(entry_id) in sent,
            )
        )
    return out


# horizon --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceHorizon:
    source: str
    latest_search: str
    days_ago: int | None


@dataclass(frozen=True)
class Horizon:
    sources: tuple[SourceHorizon, ...]
    years: tuple[int, ...]
    first_year: int | None
    latest_year: int | None
    ideas_per_year: dict[int, int]
    edges_per_year: dict[int, int]
    undated: dict[str, int]
    notices: tuple[str, ...]


def horizon_summary(view: HorizonView, today: date) -> Horizon:
    """A `HorizonView` as plain rows: the latest search date per source with its age in days at
    `today`, the publication years the series cover, and the per-year idea and edge counts."""
    sources = []
    for source, latest in sorted(view.horizon.items()):
        try:
            age: int | None = (today - date.fromisoformat(latest)).days
        except ValueError:
            age = None
        sources.append(SourceHorizon(source, latest, age))
    return Horizon(
        sources=tuple(sources),
        years=tuple(view.years),
        first_year=min(view.years) if view.years else None,
        latest_year=max(view.years) if view.years else None,
        ideas_per_year={y: len(ids) for y, ids in sorted(view.new_ideas.items())},
        edges_per_year=dict(sorted(view.new_edges.items())),
        undated=dict(view.undated),
        notices=tuple(n.text for n in view.meta.notices),
    )


# heartbeat ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HeartbeatDay:
    day: str
    total: int
    families: dict[str, int]
    types: dict[str, int]


@dataclass(frozen=True)
class Heartbeat:
    total: int
    first_day: str | None
    last_day: str | None
    days: tuple[HeartbeatDay, ...]
    family_totals: dict[str, int]


def heartbeat(counts: Iterable[tuple[str, str, int]]) -> Heartbeat:
    """Events per day from `(day, event type, count)` triples: per day the total, the counts by
    family and by type, and the totals by family."""
    per_day: dict[str, dict[str, int]] = defaultdict(dict)
    for day, event_type, n in counts:
        per_day[day][event_type] = per_day[day].get(event_type, 0) + n
    days: list[HeartbeatDay] = []
    totals: Counter[str] = Counter()
    for day in sorted(per_day):
        types = dict(sorted(per_day[day].items()))
        families: Counter[str] = Counter()
        for event_type, n in types.items():
            families[family_of(event_type)] += n
        totals.update(families)
        days.append(
            HeartbeatDay(
                day=day,
                total=sum(types.values()),
                families={f: families[f] for f in FAMILIES if families[f]},
                types=types,
            )
        )
    return Heartbeat(
        total=sum(d.total for d in days),
        first_day=days[0].day if days else None,
        last_day=days[-1].day if days else None,
        days=tuple(days),
        family_totals={f: totals[f] for f in FAMILIES if totals[f]},
    )


def load_event_counts(project: Project) -> list[tuple[str, str, int]]:
    """`(UTC day, type, count)` over the whole log, from the index's `events` table in one grouped
    query (cost: one scan of the table, no log parsing). Read-only."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT substr(ts, 1, 10), type, COUNT(*) FROM events GROUP BY 1, 2 ORDER BY 1, 2")
        ).all()
    return [(str(d), str(t), int(n)) for d, t, n in rows]


# feed view: status, cards, further, categories ---------------------------------------------


def _iso(value: Any) -> str | None:
    return None if value is None else str(value)


def _record_str(record: Mapping[str, Any] | None, key: str) -> str:
    value = None if record is None else record.get(key)
    return value.strip() if isinstance(value, str) else ""


def _record_authors(record: Mapping[str, Any] | None) -> list[str]:
    value = None if record is None else record.get("authors")
    if not isinstance(value, list):
        return []
    return [a for a in value if isinstance(a, str) and a.strip()]


def category_of_record(record: Mapping[str, Any] | None) -> str | None:
    """The first arXiv category of a fetched record, or None."""
    value = None if record is None else record.get("categories")
    if not isinstance(value, list):
        return None
    return primary_category(str(c) for c in value)


def reactions_by_category(
    latest: Mapping[str, str], category_of: Mapping[str, str | None]
) -> list[dict[str, Any]]:
    """Per category (`none` for an entry without one), the reacted entries by their latest
    reaction, with the accepted (like, save) and rejected (dislike, dismiss) shares of that
    category. Largest category first, then by name."""
    per: dict[str, Counter[str]] = defaultdict(Counter)
    for entry, reaction in latest.items():
        per[category_of.get(entry) or "none"][reaction] += 1
    rows: list[dict[str, Any]] = []
    for category, counts in per.items():
        n = sum(counts.values())
        accepted = counts["like"] + counts["save"]
        rejected = counts["dislike"] + counts["dismiss"]
        rows.append(
            {
                "category": category,
                "reacted": n,
                "like": counts["like"],
                "dislike": counts["dislike"],
                "save": counts["save"],
                "dismiss": counts["dismiss"],
                "accepted": accepted,
                "rejected": rejected,
                "accept_rate": accepted / n if n else 0.0,
                "reject_rate": rejected / n if n else 0.0,
            }
        )
    return sorted(rows, key=lambda r: (-r["reacted"], r["category"]))


def reactions_over_time(pairs: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    """`(UTC day, reaction)` pairs as one row per day, oldest first: the counts by kind, the day's
    total and the running total."""
    per: dict[str, Counter[str]] = defaultdict(Counter)
    for day, reaction in pairs:
        per[day][reaction] += 1
    out: list[dict[str, Any]] = []
    running = 0
    for day in sorted(per):
        total = sum(per[day].values())
        running += total
        out.append({"day": day, "total": total, "cumulative": running, "kinds": dict(per[day])})
    return out


def reaction_stats(
    project: Project, records: Mapping[str, Mapping[str, Any]] | None
) -> dict[str, Any]:
    """Reactions over time and per category, from the feed projection (read-only)."""
    project.index.sync()
    with project.index.connect() as conn:
        timed = [
            (str(d), str(r))
            for d, r in conn.execute(
                text(
                    "SELECT substr(e.ts, 1, 10), r.reaction FROM feed_reactions r "
                    "JOIN events e ON e.id = r.event_id ORDER BY r.event_id"
                )
            ).all()
        ]
        latest = {
            str(e): str(r)
            for e, r in conn.execute(
                text("SELECT entry_id, reaction FROM feed_reactions ORDER BY event_id")
            ).all()
        }
    cats = {e: category_of_record((records or {}).get(e)) for e in latest}
    return {
        "total": len(timed),
        "entries": len(latest),
        "over_time": reactions_over_time(timed),
        "by_category": reactions_by_category(latest, cats),
    }


def _card(
    item: Any,
    record: Mapping[str, Any] | None,
    *,
    beyond: bool,
    activity: tuple[Mapping[str, int], Mapping[str, int]] = ({}, {}),
) -> dict[str, Any]:
    """One feed card; `activity` is (reactions, adds) per entry over the last seven days."""
    return {
        "reactions_7d": activity[0].get(item.entry_id, 0),
        "adds_7d": activity[1].get(item.entry_id, 0),
        "entry_id": item.entry_id,
        "title": item.title or item.entry_id,
        "rank": item.rank,
        "score": item.score,
        "explore": bool(getattr(item, "explore", False)),
        "nearest": getattr(item, "nearest_reference_title", None)
        or getattr(item, "nearest_reference", None),
        "reaction": None if item.reaction is None else str(item.reaction),
        "sent": bool(item.sent),
        "abstract": _record_str(record, "abstract") or (getattr(item, "abstract", None) or ""),
        "authors": _record_authors(record) or list(getattr(item, "authors", ()) or ()),
        "submitted": (_record_str(record, "submitted") or (getattr(item, "submitted", None) or ""))[
            :10
        ],
        "category": category_of_record(record),
        "beyond": beyond,
    }


def feed_view(project: Project) -> dict[str, Any]:
    """The Feed tab as data: status line, cards of the latest ranking, ranked-beyond list, the
    configuration and the category proposal. A failure reading the feed becomes `error`."""
    view = collect_feed(project, "", "", "")
    out: dict[str, Any] = {
        "error": view.error,
        "configured": False,
        "config": None,
        "status": None,
        "last_fetch": None,
        "references": view.references,
        "reference_count": view.reference_count,
        "ranking_id": None,
        "total_ranked": 0,
        "total_shown": 0,
        "cap": 0,
        "cut": 0,
        "cards": [],
        "further": [],
        "proposal": None,
        "reactions": {"total": 0, "entries": 0, "over_time": [], "by_category": []},
    }
    try:
        proposal = propose_categories(project)
        out["proposal"] = {
            "categories": list(proposal.categories),
            "shares": [
                {
                    "category": s.category,
                    "works": s.works,
                    "share": s.share,
                    "proposed": s.category in proposal.categories,
                }
                for s in proposal.shares
            ],
            "core_works": proposal.core_works,
            "with_category": proposal.with_category,
            "covered": proposal.covered,
            "coverage": proposal.coverage,
        }
    except Exception as exc:  # the proposal is a convenience; the tab renders without it
        out["proposal_error"] = f"{type(exc).__name__}: {exc}"
    status = view.status
    if view.error is not None or status is None:
        return out
    out["configured"] = status.configured
    out["config"] = None if status.config is None else status.config.model_dump(mode="json")
    out["status"] = {
        "last_complete_window_to": _iso(status.last_complete_window_to),
        "next_window_from": _iso(status.next_window_from),
        "due": status.due,
        "entries": status.entries,
        "held_entries": status.held_entries,
        "fetches": status.fetches,
        "rankings": status.rankings,
        "reactions": status.reactions,
        "sends": status.sends,
        "last_ranking_id": status.last_ranking_id,
    }
    if view.last_fetch is not None:
        out["last_fetch"] = asdict(view.last_fetch)
    if not status.configured:
        return out
    records = view.records or {}
    out["reactions"] = reaction_stats(project, records)
    listing = view.listing
    activity = _feed_activity(project, project.clock.now())
    if listing is not None and listing.ranking_id is not None:
        out["ranking_id"] = listing.ranking_id
        out["total_shown"] = len(listing.items)
        out["cards"] = [
            _card(i, records.get(i.entry_id), beyond=False, activity=activity)
            for i in listing.items
        ]
    page = view.ranked
    if page is not None and page.ranking_id is not None:
        out["total_ranked"] = page.total_ranked
        out["cap"] = page.cap
        out["cut"] = page.cut
        out["further"] = [
            _card(i, records.get(i.entry_id), beyond=True, activity=activity) for i in page.further
        ]
    return out


# updates --------------------------------------------------------------------------------------


def updates_block(project: Project) -> dict[str, Any]:
    """The Updates tab as data: the updates view as JSON, the route counts of the additions and the
    sources the protocol includes (the watch form's choices)."""
    data: dict[str, Any] = updates_view(project).model_dump(mode="json")
    routes = Counter(a["route"] for a in data["additions"])
    current = current_protocol(project)
    data["routes"] = {r: routes[r] for r in ("inbox", "feed", "watch", "chase", "search", "other")}
    data["included_sources"] = (
        [] if current is None else [s.name for s in current.spec.sources if s.included]
    )
    return data


# payload --------------------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    return asdict(value)


def living_payload(project: Project, *, top_k: int = TOP_K) -> dict[str, Any]:
    """JSON-safe payload for the Living page; every number is computed here."""
    today = project.clock.now().date()
    river = feed_river(load_feed_rows(project), top_k)
    horizon = horizon_summary(horizon_view(project), today)
    beat = heartbeat(load_event_counts(project))
    feed = feed_view(project)
    return {
        "methods": dict(METHODS),
        "families": list(FAMILIES),
        "feed_river": _plain(river),
        "horizon": _plain(horizon),
        "heartbeat": _plain(beat),
        "feed": feed,
        "updates": updates_block(project),
    }


def family_table() -> Mapping[str, str]:
    """The prefix-to-family table (for the ⓘ panel and the tests)."""
    return dict(FAMILY_OF_PREFIX)


__all__ = [
    "METHODS",
    "FeedRow",
    "family_of",
    "feed_river",
    "feed_view",
    "heartbeat",
    "horizon_summary",
    "living_payload",
    "reaction_stats",
    "reactions_by_category",
    "reactions_over_time",
    "updates_block",
]
