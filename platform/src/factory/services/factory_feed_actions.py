"""The factory feed's writes: react, train, and the ranker's status (decision 169).

Invariants:
- A reaction is a human act in the factory scope. An entry in no factory ranking's order is
  refused with `entry_id: not-ranked` and nothing is written (as a project's `feed.react`).
- Training happens only when asked (ruling 4); the callers are the CLI and the hub's Train button.
  The labels are the latest `like` or `dislike` per arXiv id over the factory scope and every
  project's `feed.reacted`, by event id; `unset` withdraws a label; save and dismiss are not
  labels (A1). Labels of entries outside the pool cannot be embedded and are left out (counted
  in `TrainResult.skipped`).
- Below the thresholds nothing is written and the refusal names the reason (A2). The state blob
  is JSON, never a pickle. `feed.ranker_trained` is a system event naming the human command in
  `triggered_by`; the next version is the newest folded plus one.
- After a training the pool is ranked again, so Today reflects the new ranker at once.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select, text

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.index import factory_scope as fx
from factory.model.feed import FEED_ENTRY_RE, FeedRankerTrained, FeedReacted, FeedReaction
from factory.services import factory_feed, feed_ranker
from factory.services.context import list_projects, open_project
from factory.services.factory_scope import FactoryScope, factory_scope_exists, open_factory_scope
from factory.services.ranking import entry_text
from factory.services.ranking_model import Embedder

_LOG = logging.getLogger(__name__)

_READ_SESSION = "0" * 26  # a read opens the scopes but never mints an event
_ENTRY = re.compile(FEED_ENTRY_RE)
_LABELS = {FeedReaction.LIKE.value: True, FeedReaction.DISLIKE.value: False}


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


# --- react ---


def factory_placement(
    settings: Settings, entry_id: str, ranking_id: str | None = None, *, clock: Clock
) -> tuple[str, int] | None:
    """`(ranking_id, rank)` of the entry in the newest factory ranking (or the one named), or None
    when the factory has no ranking holding it. Reads only."""
    if not factory_scope_exists(settings):
        return None
    scope = open_factory_scope(settings, session=_READ_SESSION, clock=clock)
    try:
        ranking, rank, _, _ = _placement(scope, entry_id, ranking_id)
    except FactoryValidationError:
        return None
    return ranking, rank


def _placement(
    scope: FactoryScope, entry_id: str, ranking_id: str | None
) -> tuple[str, int, float, bool]:
    """`(ranking_id, rank, score, beyond_shown)` from the newest factory ranking (or the one named)
    whose order holds the entry; refuses `not-ranked` when there is none."""
    rankings = scope.tables["rankings"]
    rows = scope.read(
        lambda conn: conn.execute(
            select(rankings.c.ranking_id, rankings.c.order_blob, rankings.c.shown).order_by(
                rankings.c.event_id.desc()
            )
        ).all()
    )
    for ranking, order_blob, shown in rows:
        if ranking_id is not None and str(ranking) != ranking_id:
            continue
        for item in json.loads(str(shown)):
            if item.get("entry_id") == entry_id:
                return str(ranking), int(item["rank"]), float(item["score"]), False
        try:
            order = scope.blobs.get_json(str(order_blob))
        except (FactoryError, OSError, ValueError):  # a lost blob: as not ranked
            continue
        for row in order if isinstance(order, list) else []:
            if isinstance(row, dict) and row.get("entry_id") == entry_id:
                score = row.get("score")
                rank = int(str(row["rank"]))
                return str(ranking), rank, 0.0 if score is None else float(str(score)), True
    raise _refuse("entry_id", "not-ranked")


def react(
    settings: Settings,
    *,
    entry_id: str,
    reaction: FeedReaction | str,
    ranking_id: str | None = None,
    rank_shown: int | None = None,
    score_shown: float | None = None,
    session: str,
    clock: Clock,
) -> str:
    """Record a human `feed.reacted` in the factory scope and return its event id.

    `ranking_id`, `rank_shown` and `score_shown` default to where the newest factory ranking holds
    the entry (the card's own values when the caller has them). Refuses an invalid reaction or
    entry id, and an entry in no ranking (`not-ranked`); nothing is written then."""
    try:
        parsed = FeedReaction(reaction)
    except ValueError:
        raise _refuse(
            "reaction", "must be one of " + ", ".join(r.value for r in FeedReaction)
        ) from None
    if not _ENTRY.match(entry_id):
        raise _refuse("entry_id", "not an arXiv id")
    if not factory_scope_exists(settings):
        raise _refuse("entry_id", "not-ranked")
    scope = open_factory_scope(settings, session=session, clock=clock)
    with scope.writing():  # the event id is minted under the lock, above the log's newest
        ranking, rank, score, beyond = _placement(scope, entry_id, ranking_id)
        payload = FeedReacted(
            entry_id=entry_id,
            reaction=parsed,
            ranking_id=ranking,
            rank_shown=rank_shown if rank_shown is not None else rank,
            score_shown=score_shown if score_shown is not None else score,
            beyond_shown=beyond,
        )
        event = scope.events.make("feed.reacted", payload, scope.human_actor(), refs=(entry_id,))
        scope.record([event])
    factory_feed.invalidate_cache()
    return event.id


# --- labels ---


def collect_labels(settings: Settings, *, clock: Clock) -> dict[str, bool]:
    """The latest like (True) or dislike (False) per arXiv id over the factory scope and every
    project's `feed.reacted`, by event id. An `unset` withdraws the label."""
    events: list[tuple[str, str, str]] = []
    if factory_scope_exists(settings):
        scope = open_factory_scope(settings, session=_READ_SESSION, clock=clock)
        table = scope.tables["reactions"]
        events += [
            (str(e), str(i), str(r))
            for e, i, r in scope.read(
                lambda conn: conn.execute(
                    select(table.c.event_id, table.c.entry_id, table.c.reaction)
                ).all()
            )
        ]
    for slug in list_projects(settings):
        project = open_project(settings, slug, session=_READ_SESSION, clock=clock)
        project.index.sync()
        with project.index.connect() as conn:
            events += [
                (str(e), str(i), str(r))
                for e, i, r in conn.execute(
                    text("SELECT event_id, entry_id, reaction FROM feed_reactions")
                ).all()
            ]
    labels: dict[str, bool] = {}
    for _, entry_id, reaction in sorted(events):
        if reaction in _LABELS:
            labels[entry_id] = _LABELS[reaction]
        elif reaction == FeedReaction.UNSET.value:
            labels.pop(entry_id, None)
    return labels


# --- status ---


@dataclass(frozen=True)
class RankerStatus:
    version: int | None
    """The newest folded training, None before the first."""
    trained_at: str | None
    likes: int
    """Labels now (not those of the last training)."""
    dislikes: int
    trained_likes: int | None
    trained_dislikes: int | None
    can_train: bool
    reason: str | None
    """Why Train is not possible now; None when it is."""


def ranker_status(settings: Settings, *, clock: Clock) -> RankerStatus:
    labels = collect_labels(settings, clock=clock)
    likes = sum(1 for v in labels.values() if v)
    dislikes = len(labels) - likes
    short = feed_ranker.check_thresholds(labels)
    version: int | None = None
    at: str | None = None
    t_likes: int | None = None
    t_dislikes: int | None = None
    if factory_scope_exists(settings):
        scope = open_factory_scope(settings, session=_READ_SESSION, clock=clock)
        t = scope.tables["trainings"]
        row = scope.read(
            lambda conn: conn.execute(
                select(t.c.ranker_version, t.c.ts, t.c.likes, t.c.dislikes)
                .order_by(t.c.ranker_version.desc())
                .limit(1)
            ).first()
        )
        if row is not None:
            version, at, t_likes, t_dislikes = int(row[0]), str(row[1]), int(row[2]), int(row[3])
    return RankerStatus(
        version=version,
        trained_at=at,
        likes=likes,
        dislikes=dislikes,
        trained_likes=t_likes,
        trained_dislikes=t_dislikes,
        can_train=short is None,
        reason=None if short is None else short.reason,
    )


# --- train ---


@dataclass(frozen=True)
class TrainResult:
    version: int
    event_id: str
    likes: int
    dislikes: int
    training_set_hash: str
    skipped: int
    """Labelled entries outside the pool, left out of the training set."""
    ranking_id: str | None
    """The ranking written after the training; None when the pool was empty."""


def train(
    settings: Settings,
    embedder: Embedder,
    *,
    session: str,
    clock: Clock,
    command_ref: str,
) -> TrainResult:
    """Train the general ranker on the labels now and rank the pool with it.

    Refuses with the thresholds' reason (nothing written) and with `ranker` when the extra or the
    weights are missing. `command_ref` names the human command (`cli:feed train`, `hub:feed
    train`)."""
    labels_all = collect_labels(settings, clock=clock)
    pool = {e.entry_id: e for e in factory_feed.load_pool(settings, clock=clock)}
    labels = {k: v for k, v in labels_all.items() if k in pool}
    short = feed_ranker.check_thresholds(labels)
    if short is not None:
        raise _refuse("labels", short.reason)
    ids = sorted(labels)
    texts = [entry_text(pool[i].title, pool[i].abstract) for i in ids]
    distinct = list(dict.fromkeys(texts))
    embedded = embedder.embed(distinct)
    if len(embedded) != len(distinct):
        raise _refuse("embedder", f"{len(embedded)} vectors for {len(distinct)} texts")
    by_text = dict(zip(distinct, embedded, strict=True))
    vectors = {i: by_text[t] for i, t in zip(ids, texts, strict=True)}
    state = feed_ranker.train(labels, vectors, embedding_model=embedder.model_id)
    scope = open_factory_scope(settings, session=session, clock=clock)
    blob = scope.blobs.put(state.to_json().encode("utf-8"))
    with scope.writing():  # the version and the event id are taken under the lock
        version = scope.read(lambda conn: fx.latest_version(conn, scope.tables)) + 1
        payload = FeedRankerTrained(
            training_set_hash=state.training_set_hash,
            ids=tuple(ids),
            likes=state.n_likes,
            dislikes=state.n_dislikes,
            features=state.feature_names,
            library_versions=dict(state.library_versions),
            state_blob=blob,
            ranker_version=version,
            triggered_by=command_ref,
        )
        event = scope.events.make("feed.ranker_trained", payload, scope.system_actor())
        scope.record([event])
    ranked = factory_feed.rank_pool(settings, embedder, session=session, clock=clock)
    factory_feed.invalidate_cache()
    return TrainResult(
        version=version,
        event_id=event.id,
        likes=state.n_likes,
        dislikes=state.n_dislikes,
        training_set_hash=state.training_set_hash,
        skipped=len(labels_all) - len(labels),
        ranking_id=ranked.ranking_id,
    )


def rank_after_fetch(
    settings: Settings,
    embedder_factory: Callable[[], Embedder],
    *,
    session: str,
    clock: Clock,
) -> str:
    """After a hub feed run: rank the factory pool when it holds unranked fetches
    (`factory_feed.rank_if_stale`) and return the runner's note. A failure (no weights, the
    encoder, a refused write) becomes a `failed: ...` note: the fetch itself has succeeded."""
    try:
        ranked = factory_feed.rank_if_stale(
            settings, embedder_factory, session=session, clock=clock
        )
    except Exception as exc:  # the runner thread reports, never raises
        _LOG.exception("the factory ranking after the feed run failed")
        return f"failed: {type(exc).__name__}: {exc}"
    if ranked is None:
        return "up to date"
    return f"ranked {ranked.entries} papers"
