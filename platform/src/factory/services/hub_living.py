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
from factory.services.feed_read import feed_list
from factory.services.horizon import horizon_view

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
        "corpus."
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
    "user": OTHER,
    "briefing": OTHER,
    "budget": OTHER,
    "card": OTHER,
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


# payload --------------------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    return asdict(value)


def living_payload(project: Project, *, top_k: int = TOP_K) -> dict[str, Any]:
    """JSON-safe payload for the Living page; every number is computed here."""
    today = project.clock.now().date()
    river = feed_river(load_feed_rows(project), top_k)
    horizon = horizon_summary(horizon_view(project), today)
    beat = heartbeat(load_event_counts(project))
    return {
        "methods": dict(METHODS),
        "families": list(FAMILIES),
        "feed_river": _plain(river),
        "horizon": _plain(horizon),
        "heartbeat": _plain(beat),
    }


def family_table() -> Mapping[str, str]:
    """The prefix-to-family table (for the ⓘ panel and the tests)."""
    return dict(FAMILY_OF_PREFIX)


__all__ = [
    "METHODS",
    "FeedRow",
    "family_of",
    "feed_river",
    "heartbeat",
    "horizon_summary",
    "living_payload",
]
