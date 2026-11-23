"""The factory feed (decision 169, proposed): one pool, one general order, a score per project.

The pool is the arXiv entries every project's feed has fetched, one entry per arXiv id. Each
project that has a feed configuration scores every entry by the feed's own measure, the maximum
SPECTER2 cosine to its reference (core) works, and names the closest work. Projects never learn
from reactions (ruling 3). The general order comes from the factory's trained ranker, newest first
before the first training (A3). The result is a `feed.ranked` event in the factory scope.

Invariants:
- The pool's source of truth is each project's `feed.fetched` events and the entries blob each
  names, not the shared fetch cache (pruned after a day, "not a source of truth"). The first fetch
  that saw an entry supplies its title, abstract, authors and date; categories are the union. An
  entry a project's fetch recorded as held (`held_work_id`) carries that project in `held_in`; it
  stays in the pool (ruling, section 4.2).
- `rank_pool` embeds each distinct text once, through the injected `Embedder`, outside any lock,
  and writes one `feed.ranked` as the system actor. An empty pool writes nothing.
- A project's score is `round(max cosine, 6)` to its reference works, as `max_cosine_scores`; the
  closest work is the first of the sorted references on a tie.
- The ranker is the newest `factory_ranker_trainings` row whose state blob parses and whose
  dimension matches the vectors; a damaged one is skipped for the previous. None: newest first
  (submission date descending, arXiv id ascending on a tie).
- Exploration is the project feed's: `select_shown` with a seed from `exploration_seed` over the
  reference hash and the full order. The seed is recorded; picks carry `explore`.
- The reads never write. They work from the newest ranking: an entry fetched since is not listed
  until the next `rank_pool`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import select

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.index import factory_scope as fx
from factory.index.ranking import corpus_hash
from factory.model.feed import (
    FEED_ENTRY_RE,
    FeedFetched,
    FeedRanked,
    FeedRankParameters,
    FeedReferences,
    FeedShown,
)
from factory.services import feed_ranker
from factory.services.context import Project, list_projects, open_project
from factory.services.factory_scope import FactoryScope, factory_scope_exists, open_factory_scope
from factory.services.feed import exploration_seed, reference_set, select_shown
from factory.services.feed_events import feed_events
from factory.services.ranking import SCORE_DECIMALS, _dot, _unit, entry_text
from factory.services.ranking_model import Embedder

_ENTRY = re.compile(FEED_ENTRY_RE)
_READ_SESSION = "0" * 26  # a read opens the scope but never mints an event
DEFAULT_SHOWN = 100
DEFAULT_EXPLORATION = 0.1
WINDOWS = (1, 7, 30, None)


@dataclass(frozen=True)
class PoolEntry:
    entry_id: str
    title: str
    abstract: str
    authors: tuple[str, ...]
    submitted: str | None
    categories: tuple[str, ...]
    held_in: tuple[str, ...]
    fetch_ids: tuple[str, ...]


def _records(project: Project) -> list[tuple[str, list[dict[str, Any]]]]:
    """`(fetch_id, entry records)` per readable `feed.fetched` of the project, by event id."""
    out: list[tuple[str, list[dict[str, Any]]]] = []
    for event in feed_events(project.paths.events_dir, project.catalog):
        if event.type != "feed.fetched" or event.actor.kind == "human":
            continue
        try:
            payload = FeedFetched.model_validate(event.payload)
            raw = project.blobs.get_json(payload.entries_blob)
        except (ValidationError, FactoryError, OSError, ValueError):
            continue
        if isinstance(raw, list):
            out.append((payload.fetch_id, [r for r in raw if isinstance(r, dict)]))
    return out


def load_pool(settings: Settings, *, clock: Clock | None = None) -> list[PoolEntry]:
    """The pool, sorted by arXiv id (see the module docstring for the source)."""
    clock = clock or SystemClock()
    meta: dict[str, dict[str, Any]] = {}
    cats: dict[str, set[str]] = {}
    held: dict[str, set[str]] = {}
    fetches: dict[str, set[str]] = {}
    for slug in list_projects(settings):
        project = open_project(settings, slug, session=_READ_SESSION, clock=clock)
        for fetch_id, records in _records(project):
            for rec in records:
                entry_id = str(rec.get("id", ""))
                if not _ENTRY.match(entry_id):
                    continue
                meta.setdefault(entry_id, rec)
                cats.setdefault(entry_id, set()).update(str(c) for c in rec.get("categories") or [])
                fetches.setdefault(entry_id, set()).add(fetch_id)
                if rec.get("held_work_id"):
                    held.setdefault(entry_id, set()).add(slug)
    pool = []
    for entry_id in sorted(meta):
        rec = meta[entry_id]
        submitted = rec.get("submitted")
        pool.append(
            PoolEntry(
                entry_id=entry_id,
                title=str(rec.get("title", "")),
                abstract=str(rec.get("abstract") or ""),
                authors=tuple(str(a) for a in rec.get("authors") or []),
                submitted=None if submitted is None else str(submitted),
                categories=tuple(sorted(cats[entry_id])),
                held_in=tuple(sorted(held.get(entry_id, ()))),
                fetch_ids=tuple(sorted(fetches[entry_id])),
            )
        )
    return pool


@dataclass(frozen=True)
class ProjectScore:
    score: float
    closest_core_work: str
    closest_title: str


@dataclass(frozen=True)
class RankResult:
    ranking_id: str | None
    """None when the pool was empty and nothing was written."""
    entries: int
    ranker_version: int | None
    projects: tuple[str, ...]
    shown: int
    explore: int


def _newest_first(pool: Sequence[PoolEntry]) -> list[str]:
    """Submission date descending, arXiv id ascending on a tie, undated entries last."""
    ordered = sorted(pool, key=lambda e: e.entry_id)
    ordered.sort(key=lambda e: e.submitted or "", reverse=True)  # stable: ties keep id order
    return [e.entry_id for e in ordered]


def _latest_state(
    scope: FactoryScope, vectors: Mapping[str, Sequence[float]]
) -> tuple[int, feed_ranker.RankerState] | None:
    trainings = scope.tables["trainings"]
    rows = scope.read(
        lambda conn: conn.execute(
            select(trainings.c.ranker_version, trainings.c.state_blob).order_by(
                trainings.c.ranker_version.desc()
            )
        ).all()
    )
    dims = {len(v) for v in vectors.values()}
    for version, blob in rows:
        try:
            state = feed_ranker.RankerState.from_json(scope.blobs.get(str(blob)).decode("utf-8"))
        except (FactoryError, OSError, UnicodeDecodeError):
            continue
        if dims <= {state.dims}:
            return int(version), state
    return None


def rank_pool(
    settings: Settings,
    embedder: Embedder,
    *,
    session: str,
    clock: Clock,
    shown_per_cycle: int = DEFAULT_SHOWN,
    exploration_share: float = DEFAULT_EXPLORATION,
) -> RankResult:
    """Score the pool, order it and record the factory `feed.ranked` (system actor)."""
    pool = load_pool(settings, clock=clock)
    if not pool:
        return RankResult(None, 0, None, (), 0, 0)
    references: dict[str, list[Any]] = {}
    for slug in list_projects(settings):
        project = open_project(settings, slug, session=session, clock=clock)
        works = reference_set(project)
        if works:
            references[slug] = works
    texts = [entry_text(e.title, e.abstract) for e in pool]
    for works in references.values():
        texts += [entry_text(w.title, w.abstract) for w in works]
    distinct = list(dict.fromkeys(texts))
    embedded = embedder.embed(distinct)
    if len(embedded) != len(distinct):
        raise FactoryValidationError(
            [ValidationIssue("embedder", f"{len(embedded)} vectors for {len(distinct)} texts")]
        )
    vec = dict(zip(distinct, embedded, strict=True))
    unit = {t: _unit(v) for t, v in vec.items()}

    by_entry: dict[str, dict[str, ProjectScore]] = {e.entry_id: {} for e in pool}
    ref_hashes: dict[str, str] = {}
    for slug, works in references.items():
        ref_hashes[slug] = corpus_hash([w.id for w in works])
        ref_units = [(w, unit[entry_text(w.title, w.abstract)]) for w in works]
        for e in pool:
            u = unit[entry_text(e.title, e.abstract)]
            best_work, best = ref_units[0][0], _dot(u, ref_units[0][1])
            for w, r in ref_units[1:]:
                c = _dot(u, r)
                if c > best:
                    best_work, best = w, c
            by_entry[e.entry_id][slug] = ProjectScore(
                round(best, SCORE_DECIMALS), best_work.id, best_work.title
            )

    scope = open_factory_scope(settings, session=session, clock=clock)
    pool_vectors = {e.entry_id: vec[entry_text(e.title, e.abstract)] for e in pool}
    found = _latest_state(scope, pool_vectors)
    version = None if found is None else found[0]
    general: dict[str, float] | None = None
    if found is None:
        ids = _newest_first(pool)
        order = [(i, 0.0) for i in ids]
    else:
        general = feed_ranker.score(found[1], pool_vectors)
        order = [(i, general[i]) for i in feed_ranker.order(general)]
    parts = [f"{s}:{h}" for s, h in sorted(ref_hashes.items())]
    if found is not None:
        parts.append(f"ranker:{found[1].training_set_hash}")
    reference_hash = corpus_hash(parts)
    seed = exploration_seed(reference_hash, order)
    picks = select_shown(order, shown_per_cycle, exploration_share, seed)
    explore = {entry for _, entry, _, flag in picks if flag}
    ranking_id = scope.ids.new("fdr")
    blob = scope.blobs.put_json(
        [
            {
                "entry_id": entry,
                "rank": rank,
                "score": None if general is None else score,
                "ranker_version": "none" if version is None else version,
                "explore": entry in explore,
                "projects": {
                    slug: {
                        "score": ps.score,
                        "closest_core_work": ps.closest_core_work,
                        "closest_title": ps.closest_title,
                    }
                    for slug, ps in sorted(by_entry[entry].items())
                },
            }
            for rank, (entry, score) in enumerate(order, start=1)
        ]
    )
    payload = FeedRanked(
        ranking_id=ranking_id,
        fetch_ids=tuple(sorted({f for e in pool for f in e.fetch_ids})),
        reference_hash=reference_hash,
        reference_count=sum(len(w) for w in references.values()),
        model=embedder.model_id,
        weights_hash=embedder.weights_hash,
        software=embedder.software,
        parameters=FeedRankParameters(
            shown_per_cycle=shown_per_cycle,
            exploration_share=exploration_share,
            references=FeedReferences.CORE,
        ),
        exploration_seed=seed,
        order_blob=blob,
        shown=tuple(FeedShown(entry_id=e, rank=r, score=s, explore=f) for r, e, s, f in picks),
        ranker_version=version,
        project_references=ref_hashes,
    )
    scope.record(
        [scope.events.make("feed.ranked", payload, scope.system_actor(), refs=(ranking_id,))]
    )
    return RankResult(
        ranking_id, len(pool), version, tuple(sorted(references)), len(picks), len(explore)
    )


# --- reads for the hub ---


@dataclass(frozen=True)
class ProjectBadge:
    slug: str
    score: float
    closest_core_work: str
    closest_title: str
    held: bool
    """The project already holds the work ("in <project>")."""


@dataclass(frozen=True)
class FeedCard:
    entry_id: str
    title: str
    abstract: str
    authors: tuple[str, ...]
    submitted: str | None
    categories: tuple[str, ...]
    rank: int | None
    """Position in the newest ranking's full order; None when the entry is not in it."""
    score: float | None
    """The general ranker's probability, None before the first training."""
    ranker_version: int | None
    explore: bool
    label: str | None
    """`like`, `dislike` or None."""
    saved: bool
    badges: tuple[ProjectBadge, ...]
    """Every scored project, best score first; the weak line is the UI's."""


@dataclass(frozen=True)
class TodayPage:
    ranking_id: str | None
    cards: tuple[FeedCard, ...]
    total: int
    page: int
    pages: int
    sort: str


@dataclass(frozen=True)
class _Snapshot:
    ranking_id: str | None
    rows: list[dict[str, Any]]
    shown: list[str]
    reactions: dict[str, dict[str, str | None]]
    pool: dict[str, PoolEntry]


def _snapshot(settings: Settings, clock: Clock | None) -> _Snapshot:
    pool = {e.entry_id: e for e in load_pool(settings, clock=clock)}
    if not factory_scope_exists(settings):
        return _Snapshot(None, [], [], {}, pool)
    scope = open_factory_scope(settings, session=_READ_SESSION, clock=clock or SystemClock())
    rankings = scope.tables["rankings"]

    def read(conn: Any) -> tuple[Any, dict[str, dict[str, str | None]]]:
        row = conn.execute(
            select(rankings.c.ranking_id, rankings.c.order_blob, rankings.c.shown)
            .order_by(rankings.c.event_id.desc())
            .limit(1)
        ).first()
        return row, fx.latest_reactions(conn, scope.tables)

    row, reactions = scope.read(read)
    if row is None:
        return _Snapshot(None, [], [], reactions, pool)
    try:
        raw = scope.blobs.get_json(str(row[1]))
        shown_raw = json.loads(str(row[2]))
    except (FactoryError, OSError, ValueError):
        return _Snapshot(None, [], [], reactions, pool)
    rows = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
    shown = [str(s["entry_id"]) for s in shown_raw if isinstance(s, dict) and "entry_id" in s]
    return _Snapshot(str(row[0]), rows, shown, reactions, pool)


def _card(entry: PoolEntry, row: dict[str, Any] | None, snap: _Snapshot) -> FeedCard:
    projects: dict[str, Any] = {} if row is None else dict(row.get("projects") or {})
    badges = [
        ProjectBadge(
            slug=slug,
            score=float(p["score"]),
            closest_core_work=str(p["closest_core_work"]),
            closest_title=str(p.get("closest_title", "")),
            held=slug in entry.held_in,
        )
        for slug, p in projects.items()
    ]
    badges += [ProjectBadge(s, 0.0, "", "", True) for s in entry.held_in if s not in projects]
    badges.sort(key=lambda b: (-b.score, b.slug))
    state = snap.reactions.get(entry.entry_id, {})
    version = None if row is None else row.get("ranker_version")
    return FeedCard(
        entry_id=entry.entry_id,
        title=entry.title,
        abstract=entry.abstract,
        authors=entry.authors,
        submitted=entry.submitted,
        categories=entry.categories,
        rank=None if row is None else int(row["rank"]),
        score=None if row is None or row.get("score") is None else float(row["score"]),
        ranker_version=version if isinstance(version, int) else None,
        explore=bool(row and row.get("explore")),
        label=state.get("label"),
        saved=state.get("saved") == "save",
        badges=tuple(badges),
    )


def _rows_by_entry(snap: _Snapshot) -> dict[str, dict[str, Any]]:
    return {str(r["entry_id"]): r for r in snap.rows if "entry_id" in r}


def today(
    settings: Settings,
    *,
    page: int = 1,
    page_size: int = DEFAULT_SHOWN,
    sort: Literal["ranked", "newest"] = "ranked",
    clock: Clock | None = None,
) -> TodayPage:
    """Today's list, 1-based `page`. `ranked`: the shown picks by rank (exploration picks among
    them, labelled), then the rest of the order; `newest`: submission date descending."""
    snap = _snapshot(settings, clock)
    rows = _rows_by_entry(snap)
    ids = [i for i in rows if i in snap.pool]
    if sort == "newest":
        ids.sort(key=lambda i: i)
        ids.sort(key=lambda i: snap.pool[i].submitted or "", reverse=True)
    else:
        shown = {i: n for n, i in enumerate(snap.shown)}
        ids.sort(key=lambda i: (0, shown[i]) if i in shown else (1, int(rows[i]["rank"])))
    size = max(1, page_size)
    pages = max(1, -(-len(ids) // size))
    page = min(max(1, page), pages)
    window = ids[(page - 1) * size : page * size]
    cards = tuple(_card(snap.pool[i], rows[i], snap) for i in window)
    return TodayPage(snap.ranking_id, cards, len(ids), page, pages, sort)


def project_view(
    settings: Settings,
    slug: str,
    *,
    window_days: int | None = 7,
    clock: Clock | None = None,
) -> list[FeedCard]:
    """The entries scored for `slug`, best score first (id ascending on a tie), limited to those
    submitted within `window_days` of today (1, 7, 30 or None for all). Entries without a date are
    kept only without a window. The weak line is the UI's."""
    if window_days not in WINDOWS:
        raise FactoryValidationError([ValidationIssue("window_days", "must be 1, 7, 30 or none")])
    snap = _snapshot(settings, clock)
    rows = _rows_by_entry(snap)
    since = (
        None
        if window_days is None
        else ((clock or SystemClock()).now().date() - timedelta(days=window_days)).isoformat()
    )
    keep = []
    for entry_id, row in rows.items():
        entry = snap.pool.get(entry_id)
        if entry is None or slug not in (row.get("projects") or {}):
            continue
        if since is not None and (entry.submitted is None or entry.submitted[:10] < since):
            continue
        keep.append((entry_id, float(row["projects"][slug]["score"])))
    keep.sort(key=lambda p: (-p[1], p[0]))
    return [_card(snap.pool[i], rows[i], snap) for i, _ in keep]


def _by_state(settings: Settings, clock: Clock | None, wanted: str) -> list[FeedCard]:
    snap = _snapshot(settings, clock)
    rows = _rows_by_entry(snap)
    ids = [
        i
        for i, st in snap.reactions.items()
        if i in snap.pool and (st.get("label") == wanted or (wanted == "save" and st.get("saved")))
    ]
    return [_card(snap.pool[i], rows.get(i), snap) for i in reversed(ids)]


def liked(settings: Settings, *, clock: Clock | None = None) -> list[FeedCard]:
    """Entries whose latest label is a like, most recently first reacted first."""
    return _by_state(settings, clock, "like")


def reading_list(settings: Settings, *, clock: Clock | None = None) -> list[FeedCard]:
    """Entries saved and not unsaved, most recently first reacted first."""
    return _by_state(settings, clock, "save")


__all__ = [
    "FeedCard",
    "PoolEntry",
    "ProjectBadge",
    "ProjectScore",
    "RankResult",
    "TodayPage",
    "liked",
    "load_pool",
    "project_view",
    "rank_pool",
    "reading_list",
    "today",
]
