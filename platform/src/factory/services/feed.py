"""The discovery feed cycle (slice 4c, decision 117): configure, fetch, rank.

A feed ranks the new arXiv listings of the declared categories against the project's core works.
It suggests; it never includes, excludes or screens, and no model is called here: the embedder is
the local scorer of decision 116 (injected, so fixtures run offline).

Invariants:
- `configure` is a human act: another actor is refused (`actor`: `human-only`) and nothing is
  written. A configuration is validated at the boundary; an invalid one writes nothing.
- `feed_run` is serialised per project by a file lock (`feed.lock`), as `watch_run`. It refuses,
  writing nothing, with no configuration and with no reference work. A run that is not due, and a
  dry run, write no event.
- The window starts at the last complete fetch's `window_to` minus `overlap_days` (the first
  fetch: `interval_days` before today) and ends today. The query is `cat:A OR cat:B` with the
  `listed_since` filter, through the injected source, outside any search run.
- The shared cache (`<cache_root>/arxiv/<sha256 of sorted categories>/<from>_<to>/`) holds
  complete results only and is not a source of truth: on a hit the pages are replayed from disk,
  and every page is put into the project's blobs and its hash recorded either way.
- An entry already in `feed_entries` is not ranked again. An entry whose work the corpus holds
  (`held_matches`: identifiers, aliases, title) is recorded with `held_work_id` and never ranked
  or shown, held-out seeds' works included (R-F4).
- With `core+included` references, a held-out seed's work is left out of the included works
  unless the researcher marked it core, as `forward_core_sources` does (R-20, R-F4).
- The score is the maximum cosine to any reference (`max_cosine_scores`), ties broken by arXiv id.
  The shown list is the top `round(shown * (1 - exploration_share))` plus a seeded random draw
  from the rest. The seed is derived from the reference hash and the order, so equal inputs give
  equal payloads; it is recorded. Each shown item records its nearest reference work.
- `react` and `send` are human acts (`actor`: `human-only`, nothing written). The entry must be
  known (`entry_id`: `unknown`) and shown in the ranking given, by default the latest ranking that
  showed it (`not-shown`). A reaction records the rank and score shown; several are allowed and
  the latest counts. `send` refuses a held entry (`held`) and a second send (`already-sent`); it
  writes the inbox `inbox.link_added` (channel CLI) and `feed.sent` in one batch under one lock.
- Embedding happens outside `project.writing()`. Inside it the inputs (configuration, known
  entries, held matches, references) are read again; if any changed nothing is written and the
  caller is told to run again. `feed.fetched` and `feed.ranked` are written in one batch, as the
  system or, when an agent triggers the run over MCP, as that agent with its provenance (model,
  skill, `input_blob` of the call's arguments); a human actor is refused (`actor`). A fetch never
  exists without the ranking of its new entries.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import random
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import JsonValue, ValidationError
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.ranking import corpus_hash
from factory.model.base import StrictModel
from factory.model.feed import (
    FEED_ENTRY_RE,
    FeedConfigured,
    FeedFetched,
    FeedNote,
    FeedRanked,
    FeedRankParameters,
    FeedReacted,
    FeedReaction,
    FeedReferences,
    FeedSent,
    FeedShown,
)
from factory.model.screening import Channel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv
from factory.services.context import Project, list_projects, open_project
from factory.services.core_works import core_marks, forward_core_sources, seed_core_works
from factory.services.dedup_incremental import held_matches
from factory.services.inbox import LinkInput, _refuse_actor, link_event
from factory.services.ranking import _dot, _unit, max_cosine_scores, order_by_score, ranking_text
from factory.services.ranking_model import Embedder
from factory.services.references import included_works
from factory.services.search import get_work
from factory.sources.base import PageSink, RawPage, SearchResult

SOURCE = "arxiv"
CACHE_DIR = ".feed-cache"
"""The shared fetch cache, under the projects root."""

_ENTRY = re.compile(FEED_ENTRY_RE)
_VERSION = re.compile(r"v(\d+)$", re.IGNORECASE)
_SEED_BITS = 53

RunStatusName = Literal[
    "not-due", "dry-run", "complete", "partial", "failed", "nothing-new", "not-configured"
]


class FeedSource(Protocol):
    """What the feed needs of a source: `ArxivSource.run`."""

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult: ...


class FeedStatus(StrictModel):
    configured: bool
    config: FeedConfigured | None
    last_complete_window_to: date | None
    next_window_from: date | None
    due: bool
    last_ranking_id: str | None
    entries: int
    held_entries: int
    fetches: int
    rankings: int
    reactions: int
    sends: int


class FeedRunResult(StrictModel):
    """What one `feed_run` did. `fetch_id` and `ranking_id` are None when nothing was written."""

    status: RunStatusName
    window_from: date | None = None
    window_to: date | None = None
    fetch_id: str | None = None
    ranking_id: str | None = None
    fetched: int = 0
    already_known: int = 0
    held: int = 0
    ranked: int = 0
    shown: int = 0
    explore: int = 0
    note: str | None = None


class FeedProjectOutcome(StrictModel):
    slug: str
    code: int
    result: FeedRunResult | None = None
    error: str | None = None


class FeedRunAll(StrictModel):
    exit_code: int
    outcomes: tuple[FeedProjectOutcome, ...]


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


# --- configuration and status ---


def configure(project: Project, actor: Actor, config: Mapping[str, object]) -> str:
    """Record the project's feed configuration (`feed.configured`) and return its event id.

    `config` holds the fields of `FeedConfigured` except `config_id`, which is minted here. The
    configuration replaces the previous one. Refused for a non-human actor, and for invalid
    fields, with nothing written."""
    if actor.kind != "human":
        raise _refuse("actor", "human-only")
    fields = {k: v for k, v in config.items() if k != "config_id"}
    with project.writing():
        try:
            payload = FeedConfigured.model_validate({**fields, "config_id": project.ids.new("fdc")})
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(str(p) for p in err["loc"]), str(err["msg"]))
                    for err in exc.errors()
                ]
            ) from exc
        event = project.events.make("feed.configured", payload, actor, refs=(payload.config_id,))
        project.record([event])
    return event.id


def current_config(project: Project) -> FeedConfigured | None:
    """The latest configuration, or None before any (or when the stored row does not validate)."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT config FROM feed_configs LIMIT 1")).first()
    if row is None:
        return None
    try:
        return FeedConfigured.model_validate_json(str(row[0]))
    except ValidationError:
        return None


def _last_complete_to(project: Project) -> date | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(window_to) FROM feed_fetches WHERE complete = 1")
        ).first()
    return None if row is None or row[0] is None else date.fromisoformat(str(row[0]))


def _window(config: FeedConfigured, last_to: date | None, today: date) -> tuple[date, date]:
    start = (
        today - timedelta(days=config.interval_days)
        if last_to is None
        else last_to - timedelta(days=config.overlap_days)
    )
    return min(start, today), today


def _is_due(config: FeedConfigured, last_to: date | None, today: date) -> bool:
    return last_to is None or (today - last_to).days >= config.interval_days


def feed_status(project: Project, *, today: date | None = None) -> FeedStatus:
    """Configuration, the last complete fetch window, whether a run is due, and counts."""
    config = current_config(project)
    day = today or project.clock.now().date()
    with project.index.connect() as conn:

        def count(sql: str) -> int:
            return int(conn.execute(text(sql)).scalar_one())

        fetches = count("SELECT COUNT(*) FROM feed_fetches")
        entries = count("SELECT COUNT(*) FROM feed_entries")
        held = count("SELECT COUNT(*) FROM feed_entries WHERE held_work_id IS NOT NULL")
        rankings = count("SELECT COUNT(*) FROM feed_rankings")
        reactions = count("SELECT COUNT(*) FROM feed_reactions")
        sends = count("SELECT COUNT(*) FROM feed_sends")
        last_rank = conn.execute(
            text("SELECT ranking_id FROM feed_rankings ORDER BY event_id DESC LIMIT 1")
        ).first()
    last_to = _last_complete_to(project)
    return FeedStatus(
        configured=config is not None,
        config=config,
        last_complete_window_to=last_to,
        next_window_from=None if config is None else _window(config, last_to, day)[0],
        due=config is not None and _is_due(config, last_to, day),
        last_ranking_id=None if last_rank is None else str(last_rank[0]),
        entries=entries,
        held_entries=held,
        fetches=fetches,
        rankings=rankings,
        reactions=reactions,
        sends=sends,
    )


# --- the cycle ---


@contextmanager
def _feed_lock(project: Project) -> Iterator[None]:
    """The project's feed lock (a cross-process file lock), held for the whole of a run."""
    lock_path = project.paths.index_path.parent / "feed.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def feed_query(config: FeedConfigured, since: date) -> QuerySpec:
    """The category listing query: `cat:A OR cat:B`, listed on or after `since`."""
    return QuerySpec(
        source=SOURCE,
        kind=QueryKind.KEYWORD,
        text=" OR ".join(f"cat:{c}" for c in config.categories),
        purpose=QueryPurpose.SEARCH,
        filters={"listed_since": since.isoformat()},
    )


def _cache_dir(root: Path, categories: Sequence[str], start: date, end: date) -> Path:
    key = hashlib.sha256(",".join(sorted(categories)).encode()).hexdigest()
    return root / SOURCE / key / f"{start.isoformat()}_{end.isoformat()}"


@dataclass
class _Fetched:
    works: list[Work]
    pages: list[RawPage]
    blobs: list[str]
    status: RunStatus
    note: str | None
    cached: bool


def _read_cache(directory: Path, sink: PageSink) -> _Fetched | None:
    """The pages and works of a cached complete fetch, the pages put through `sink`; None on a
    miss or an unreadable cache (a cache is never trusted over a fetch)."""
    meta = directory / "meta.json"
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
        pages = [
            RawPage(
                ordinal=int(p["ordinal"]),
                body=str(p["body"]),
                url=str(p["url"]),
                fetched_at=datetime.fromisoformat(str(p["fetched_at"])),
            )
            for p in json.loads((directory / "pages.json").read_text(encoding="utf-8"))
        ]
        works = [
            Work.model_validate(w)
            for w in json.loads((directory / "works.json").read_text(encoding="utf-8"))
        ]
    except (OSError, ValueError, KeyError, TypeError, ValidationError):
        return None
    if info.get("status") != RunStatus.COMPLETE.value:
        return None
    blobs = [sink(page) for page in pages]
    return _Fetched(works, pages, blobs, RunStatus.COMPLETE, None, True)


def _write_cache(directory: Path, fetched: _Fetched) -> None:
    """Best effort, and only for a complete fetch; `meta.json` goes last so a hit is whole."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "pages.json").write_text(
            json.dumps(
                [
                    {
                        "ordinal": p.ordinal,
                        "body": p.body,
                        "url": p.url,
                        "fetched_at": p.fetched_at.isoformat(),
                    }
                    for p in fetched.pages
                ]
            ),
            encoding="utf-8",
        )
        (directory / "works.json").write_text(
            json.dumps([w.model_dump(mode="json") for w in fetched.works]), encoding="utf-8"
        )
        (directory / "meta.json").write_text(
            json.dumps({"status": RunStatus.COMPLETE.value}), encoding="utf-8"
        )
    except OSError:
        return


def _fetch(
    project: Project,
    source: FeedSource,
    config: FeedConfigured,
    start: date,
    end: date,
    cache_root: Path | None,
) -> _Fetched:
    pages: list[RawPage] = []
    blobs: list[str] = []

    def sink(page: RawPage) -> str:
        ref = project.blobs.put(page.body.encode("utf-8"))
        pages.append(page)
        blobs.append(ref)
        return ref

    directory = (
        None if cache_root is None else _cache_dir(cache_root, config.categories, start, end)
    )
    if directory is not None:
        hit = _read_cache(directory, sink)
        if hit is not None:
            return hit
        pages.clear()
        blobs.clear()
    result = source.run(
        feed_query(config, start),
        run_id=project.ids.new("run"),
        query_id=project.ids.new("qry"),
        archive=sink,
    )
    fetched = _Fetched(list(result.works), pages, blobs, result.status, result.note, False)
    if directory is not None and result.status is RunStatus.COMPLETE:
        _write_cache(directory, fetched)
    return fetched


@dataclass(frozen=True)
class _Entry:
    entry_id: str
    version: str | None
    work: Work


def _entries(works: Sequence[Work]) -> tuple[list[_Entry], int]:
    """The distinct valid entries of the fetched works, sorted by arXiv id, and how many works
    were skipped (no valid arXiv id)."""
    found: dict[str, _Entry] = {}
    skipped = 0
    for work in works:
        raw = work.identifiers.arxiv
        entry_id = None if not raw else normalize_arxiv(raw)
        if entry_id is None or not _ENTRY.match(entry_id) or not work.title.strip():
            skipped += 1
            continue
        match = _VERSION.search(raw.strip()) if raw else None
        found.setdefault(
            entry_id, _Entry(entry_id, None if match is None else f"v{match.group(1)}", work)
        )
    return [found[k] for k in sorted(found)], skipped


def _entry_record(entry: _Entry, held: str | None) -> dict[str, JsonValue]:
    work = entry.work
    published = work.dates.published
    return {
        "id": entry.entry_id,
        "version": entry.version,
        "title": work.title,
        "abstract": work.abstract,
        "authors": [a.name for a in work.authors],
        "categories": list(work.subjects),
        "submitted": None if published is None else published.isoformat(),
        "held_work_id": held,
    }


def _known_entries(project: Project) -> set[str]:
    with project.index.connect() as conn:
        return {str(r[0]) for r in conn.execute(text("SELECT entry_id FROM feed_entries"))}


def _reference_ids(project: Project, config: FeedConfigured) -> list[str]:
    included = included_works(project)
    ids = set(forward_core_sources(project, included))
    if config.references is FeedReferences.CORE_INCLUDED:
        marked = {m.work_id for m in core_marks(project)}
        held_out = set(seed_core_works(project)) - set(
            seed_core_works(project, development_only=True)
        )
        ids.update(set(included) - (held_out - marked))
    return sorted(ids)


def _reference_works(project: Project, ids: Sequence[str]) -> list[Work]:
    found = (get_work(project, work_id) for work_id in ids)
    return [w for w in found if w is not None and w.title.strip()]


class _Recording:
    """An embedder that remembers each text's vector, so the nearest reference of a shown item
    is read from the vectors that scored it, without a second embedding."""

    def __init__(self, inner: Embedder) -> None:
        self._inner = inner
        self.vectors: dict[str, list[float]] = {}

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @property
    def weights_hash(self) -> str:
        return self._inner.weights_hash

    @property
    def software(self) -> str:
        return self._inner.software

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = self._inner.embed(texts)
        for t, v in zip(texts, out, strict=False):
            self.vectors[t] = v
        return out


def _nearest(recorded: _Recording, work: Work, references: Sequence[Work]) -> str | None:
    vector = recorded.vectors.get(ranking_text(work))
    if vector is None or not references:
        return None
    unit = _unit(vector)
    best: tuple[float, str] | None = None
    for ref in references:
        ref_vector = recorded.vectors.get(ranking_text(ref))
        if ref_vector is None:
            continue
        cosine = _dot(unit, _unit(ref_vector))
        if best is None or cosine > best[0]:
            best = (cosine, ref.id)
    return None if best is None else best[1]


def exploration_seed(reference_hash: str, order: Sequence[tuple[str, float]]) -> int:
    """The draw's seed, from the reference-set hash and the full order alone: equal inputs give
    equal seeds (spec ruling 6, R-F2)."""
    digest = hashlib.sha256(
        reference_hash.encode() + b"\n" + canonical_json([[e, s] for e, s in order])
    ).digest()
    return int.from_bytes(digest[:8], "big") % (1 << _SEED_BITS)


def select_shown(
    order: Sequence[tuple[str, float]], shown_per_cycle: int, share: float, seed: int
) -> list[tuple[int, str, float, bool]]:
    """`(rank, entry_id, score, explore)` of the shown items, by rank: the top
    `round(shown * (1 - share))` of `order`, then `shown - top` picks drawn by `Random(seed)` from
    the rest. With fewer items than slots, all are shown and none is an exploration pick."""
    top_n = min(len(order), round(shown_per_cycle * (1 - share)))
    rest = list(range(top_n, len(order)))
    picks = min(len(rest), shown_per_cycle - top_n)
    chosen = random.Random(seed).sample(rest, picks) if picks > 0 else []
    top = [(i, False) for i in range(top_n)]
    explore = [(i, True) for i in chosen]
    return [(i + 1, order[i][0], order[i][1], flag) for i, flag in sorted([*top, *explore])]


def _describe(config: FeedConfigured, start: date, end: date, refs: int) -> str:
    return (
        f"would fetch {feed_query(config, start).text} listed since {start} (window {start} to "
        f"{end}), rank the new entries against {refs} reference work(s) and show "
        f"{config.shown_per_cycle} (exploration share {config.exploration_share})"
    )


def feed_run(
    project: Project,
    embedder: Embedder,
    source: FeedSource,
    *,
    due: bool = True,
    dry_run: bool = False,
    cache_root: Path | None = None,
    today: date | None = None,
    actor: Actor | None = None,
) -> FeedRunResult:
    """Fetch the window's listings and rank the new entries; write `feed.fetched` and
    `feed.ranked` as `actor` (default the system; an agent actor also records the call's
    arguments as its `input_blob`). A human actor is refused (`actor`: `no-human`).

    `due=True` runs only when the cadence says so (otherwise status `not-due`, nothing written);
    `due=False` runs now. `dry_run` fetches and writes nothing and says what it would do. Refused,
    with nothing written, with no configuration or no reference work, and when the inputs changed
    while embedding. A missing ranker surfaces as the embedder's own `ranker_unavailable` refusal.
    """
    who = actor or project.system_actor()
    if who.kind == "human":
        raise _refuse("actor", "the feed is fetched by the system or an agent, not a human")
    with _feed_lock(project):
        project.index.sync()
        config = current_config(project)
        if config is None:
            raise _refuse("config", "no feed configuration; run `factory feed configure` first")
        day = today or project.clock.now().date()
        last_to = _last_complete_to(project)
        if due and not _is_due(config, last_to, day):
            return FeedRunResult(status="not-due", note=f"last complete window ended {last_to}")
        start, end = _window(config, last_to, day)
        reference_ids = _reference_ids(project, config)
        references = _reference_works(project, reference_ids)
        if not references:
            raise _refuse(
                "references",
                "no reference work: mark a work core or add a development positive seed first",
            )
        if dry_run:
            return FeedRunResult(
                status="dry-run",
                window_from=start,
                window_to=end,
                note=_describe(config, start, end, len(references)),
            )
        fetched = _fetch(project, source, config, start, end, cache_root)
        if fetched.status is not RunStatus.COMPLETE and not fetched.works:
            return FeedRunResult(
                status="failed", window_from=start, window_to=end, note=fetched.note or "no records"
            )
        known = _known_entries(project)
        entries, skipped = _entries(fetched.works)
        new = [e for e in entries if e.entry_id not in known]
        held = held_matches(project, [e.work for e in new])
        candidates = [e for e in new if e.work.id not in held]
        by_entry = {e.entry_id: e for e in candidates}

        recorded = _Recording(embedder)
        scores: dict[str, float] = {}
        if candidates:
            by_work = max_cosine_scores(recorded, references, [e.work for e in candidates])
            scores = {e.entry_id: by_work[e.work.id] for e in candidates}
        order = order_by_score(scores)

        with project.writing():
            project.index.sync()
            again = _reference_ids(project, config)
            if (
                current_config(project) != config
                or _known_entries(project) != known
                or again != reference_ids
                or held_matches(project, [e.work for e in new]) != held
            ):
                raise _refuse("feed", "the configuration, corpus or references changed; run again")
            fetch_id = project.ids.new("fdf")
            records: list[JsonValue] = [_entry_record(e, held.get(e.work.id)) for e in new]
            ok = fetched.status is RunStatus.COMPLETE
            fetched_payload = FeedFetched(
                fetch_id=fetch_id,
                categories=config.categories,
                window_from=start,
                window_to=end,
                raw_blobs=tuple(dict.fromkeys(fetched.blobs)),
                entries_blob=project.blobs.put_json(records),
                count=len(new),
                held_count=len(held),
                complete=ok,
            )
            input_blob = (
                project.blobs.put_json({"due": due, "dry_run": dry_run})
                if who.kind == "agent"
                else None
            )
            events = [
                project.events.make(
                    "feed.fetched",
                    fetched_payload,
                    who,
                    refs=(fetch_id,),
                    input_blob=input_blob,
                )
            ]
            ranking_id: str | None = None
            shown_count = explore_count = 0
            if order:
                reference_hash = corpus_hash(reference_ids)
                seed = exploration_seed(reference_hash, order)
                picks = select_shown(order, config.shown_per_cycle, config.exploration_share, seed)
                ranking_id = project.ids.new("fdr")
                ranked_payload = FeedRanked(
                    ranking_id=ranking_id,
                    fetch_ids=(fetch_id,),
                    reference_hash=reference_hash,
                    reference_count=len(reference_ids),
                    model=recorded.model_id,
                    weights_hash=recorded.weights_hash,
                    software=recorded.software,
                    parameters=FeedRankParameters(
                        shown_per_cycle=config.shown_per_cycle,
                        exploration_share=config.exploration_share,
                        references=config.references,
                    ),
                    exploration_seed=seed,
                    order_blob=project.blobs.put_json(
                        [
                            {"entry_id": entry, "rank": i, "score": score}
                            for i, (entry, score) in enumerate(order, start=1)
                        ]
                    ),
                    shown=tuple(
                        FeedShown(
                            entry_id=entry,
                            rank=rank,
                            score=score,
                            explore=flag,
                            nearest_reference=_nearest(recorded, by_entry[entry].work, references),
                        )
                        for rank, entry, score, flag in picks
                    ),
                )
                events.append(
                    project.events.make(
                        "feed.ranked",
                        ranked_payload,
                        who,
                        refs=(ranking_id, fetch_id),
                        input_blob=input_blob,
                    )
                )
                shown_count = len(picks)
                explore_count = sum(1 for p in picks if p[3])
            project.record(events)
        notes = [
            n
            for n in (
                fetched.note,
                f"{skipped} record(s) without a valid arXiv id" if skipped else None,
            )
            if n
        ]
        status: RunStatusName = "partial" if not ok else "complete" if order else "nothing-new"
        return FeedRunResult(
            status=status,
            window_from=start,
            window_to=end,
            fetch_id=fetch_id,
            ranking_id=ranking_id,
            fetched=len(new),
            already_known=len(entries) - len(new),
            held=len(held),
            ranked=len(order),
            shown=shown_count,
            explore=explore_count,
            note="; ".join(notes) or None,
        )


class LazyEmbedder:
    """An embedder built on first use, so a run that is not due never needs the weights."""

    def __init__(self, built: Embedder | None, build: Callable[[], Embedder] | None) -> None:
        self._built = built
        self._build = build

    def _get(self) -> Embedder:
        if self._built is None:
            if self._build is None:
                raise _refuse("ranker", "no embedder given")
            self._built = self._build()
        return self._built

    @property
    def model_id(self) -> str:
        return self._get().model_id

    @property
    def weights_hash(self) -> str:
        return self._get().weights_hash

    @property
    def software(self) -> str:
        return self._get().software

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._get().embed(texts)


def feed_run_all(
    settings: Settings,
    *,
    embedder: Embedder | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
    source: FeedSource,
    session: str,
    clock: Clock,
    slugs: Sequence[str] | None = None,
    due: bool = True,
    dry_run: bool = False,
    cache_root: Path | None = None,
    today: date | None = None,
    actor: Actor | None = None,
) -> FeedRunAll:
    """Run the feed of each project (all of the root's when `slugs` is None), one failure never
    stopping the others. Projects without a configuration are skipped (`not-configured`, code 0).

    Exit code, as `watch run`: 0 every project not due, nothing new or complete; 1 a partial or
    failed fetch, or an unexpected error; 2 a refusal (invalid input, no reference, no ranker).
    Pass `embedder`, or `embedder_factory` (a callable) to build the ranker only when a project
    actually ranks. The cache defaults to `<root>/.feed-cache`."""
    names = list(list_projects(settings) if slugs is None else slugs)
    cache = cache_root if cache_root is not None else settings.root / CACHE_DIR
    lazy = LazyEmbedder(embedder, embedder_factory)
    outcomes: list[FeedProjectOutcome] = []
    for slug in names:
        try:
            project = open_project(settings, slug, session=session, clock=clock)
            if current_config(project) is None and slugs is None:
                outcomes.append(
                    FeedProjectOutcome(
                        slug=slug,
                        code=0,
                        result=FeedRunResult(status="not-configured", note="no feed configuration"),
                    )
                )
                continue
            result = feed_run(
                project,
                lazy,
                source,
                due=due,
                dry_run=dry_run,
                cache_root=cache,
                today=today,
                actor=actor,
            )
        except FactoryValidationError as exc:
            outcomes.append(FeedProjectOutcome(slug=slug, code=2, error=str(exc)))
        except ProjectNotFoundError as exc:
            outcomes.append(FeedProjectOutcome(slug=slug, code=2, error=str(exc)))
        except Exception as exc:
            outcomes.append(
                FeedProjectOutcome(slug=slug, code=1, error=f"{type(exc).__name__}: {exc}")
            )
        else:
            code = 1 if result.status in ("partial", "failed") else 0
            outcomes.append(FeedProjectOutcome(slug=slug, code=code, result=result))
    return FeedRunAll(
        exit_code=max((o.code for o in outcomes), default=0), outcomes=tuple(outcomes)
    )


# --- reactions and send ---


def _shown_in(
    project: Project, entry_id: str, ranking_id: str | None
) -> tuple[str, int, float, str | None]:
    """`(ranking_id, rank, score, held_work_id)` of the entry in the ranking asked for, or the
    latest ranking that showed it. Refuses an unknown entry and one not shown. The caller holds the
    write lock and has synced."""
    with project.index.connect() as conn:
        entry = conn.execute(
            text("SELECT held_work_id FROM feed_entries WHERE entry_id = :e"), {"e": entry_id}
        ).first()
        if entry is None:
            raise _refuse("entry_id", "unknown")
        rows = conn.execute(
            text("SELECT ranking_id, shown FROM feed_rankings ORDER BY event_id DESC")
        ).all()
    for ranking, shown in rows:
        if ranking_id is not None and str(ranking) != ranking_id:
            continue
        for item in json.loads(str(shown)):
            if item["entry_id"] == entry_id:
                held = None if entry[0] is None else str(entry[0])
                return str(ranking), int(item["rank"]), float(item["score"]), held
    raise _refuse("entry_id", "not-shown")


def react(
    project: Project,
    actor: Actor,
    entry_id: str,
    reaction: FeedReaction,
    *,
    ranking_id: str | None = None,
) -> str:
    """Record a reaction (`feed.reacted`) to a shown entry and return its event id. Human only;
    refused with nothing written for an unknown entry or one not shown in the ranking."""
    if actor.kind != "human":
        raise _refuse("actor", "human-only")
    with project.writing():
        project.index.sync()
        ranking, rank, score, _ = _shown_in(project, entry_id, ranking_id)
        payload = FeedReacted(
            entry_id=entry_id,
            reaction=FeedReaction(reaction),
            ranking_id=ranking,
            rank_shown=rank,
            score_shown=score,
        )
        event = project.events.make("feed.reacted", payload, actor, refs=(entry_id,))
        project.record([event])
    return event.id


def send(
    project: Project,
    actor: Actor,
    entry_id: str,
    *,
    note: FeedNote | None = None,
    ranking_id: str | None = None,
) -> str:
    """Send a shown entry to the inbox as its arXiv link and return the inbox item id. Human only.
    The inbox item (channel CLI) and `feed.sent` are written in one batch under one lock, so
    neither exists without the other. Refused with nothing written for an unknown or unshown
    entry, a held one (`held`) and one already sent (`already-sent`)."""
    if actor.kind != "human":
        raise _refuse("actor", "human-only")
    with project.writing():
        project.index.sync()
        _refuse_actor(project, actor)
        ranking, _, _, held = _shown_in(project, entry_id, ranking_id)
        if held is not None:
            raise _refuse("entry_id", "held")
        with project.index.connect() as conn:
            sent = conn.execute(
                text("SELECT 1 FROM feed_sends WHERE entry_id = :e"), {"e": entry_id}
            ).first()
        if sent is not None:
            raise _refuse("entry_id", "already-sent")
        link = LinkInput(f"https://arxiv.org/abs/{entry_id}", note=note)
        added, item_id, issues = link_event(project, actor, link, Channel.CLI)
        if added is None or item_id is None:
            raise FactoryValidationError(issues)
        payload = FeedSent(entry_id=entry_id, ranking_id=ranking, inbox_item_id=item_id, note=note)
        event = project.events.make("feed.sent", payload, actor, refs=(entry_id, item_id))
        project.record([added, event])
    return item_id
