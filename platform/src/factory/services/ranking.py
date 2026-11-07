"""Rank the records still to be screened by similarity to the development seeds (decision 116).

A ranking orders; it judges nothing and removes nothing from the corpus or the screening queue.

Invariants:
- The reference texts are the development positive seeds only, read through `agent_seeds`, which
  never returns a held-out seed (R-20). A held-out seed's text is never embedded as a reference. A
  held-out seed's work, when a search found it, is a corpus record like any other (decision 37.9)
  and is ranked as one; nothing marks it.
- The works ranked are those of the title/abstract population (`stage_population`) that no live
  decision covers yet.
- A work's score is its maximum cosine similarity to any reference text (not the mean), rounded to
  six decimals. The order is score descending, ties broken by work id ascending. For fixed weights
  and inputs the order, scores and event content are the same.
- Embeddings are computed outside `project.writing()`. Inside it the ranked set and the
  references are read again; if either changed, nothing is written and the ranking is run again.
- The event is the system's; the order is a blob (see `model.ranking`); a later ranking replaces
  the earlier one in the projection and the earlier event stays in the log.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import Field
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.index.ranking import corpus_hash
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.model.ranking import RankingComputed, RankingParameters
from factory.model.seed import SeedKind
from factory.model.work import Work
from factory.services.calibration import stage_population
from factory.services.context import Project
from factory.services.ranked_queue import ranking_positions as ranking_positions
from factory.services.ranking_model import Embedder
from factory.services.screening import live_decisions
from factory.services.search import get_work, list_works
from factory.services.seeds import agent_seeds

SEPARATOR = "[SEP]"
SCORE_DECIMALS = 6


class RankedWork(StrictModel):
    """One work of the latest ranking."""

    position: int = Field(ge=1)
    work_id: str
    score: float


class RankingView(StrictModel):
    """The latest ranking: its provenance and the first `shown` of `count` works."""

    ranking_id: str
    model_id: str
    weights_hash: str
    software: str
    count: int
    ranked: list[RankedWork]


def ranking_text(work: Work) -> str:
    """The embedded text of a work: `title [SEP] abstract`."""
    return f"{work.title.strip()} {SEPARATOR} {(work.abstract or '').strip()}".strip()


def to_rank(project: Project) -> list[str]:
    """The works still to be screened: the title/abstract population without a live decision,
    sorted by work id."""
    decided = {d.work_id for d in live_decisions(project)}
    return sorted(stage_population(project, ScreeningStage.TITLE_ABSTRACT) - decided)


def reference_works(project: Project) -> tuple[list[Work], int]:
    """The development positive seeds' works with a title, in seed order, and how many development
    positives could not be used (no resolved work, or no title). Held-out seeds are not seen: the
    list comes from `agent_seeds`."""
    works: list[Work] = []
    skipped = 0
    for seed in agent_seeds(project):
        if seed.kind is not SeedKind.POSITIVE:
            continue
        work = None if seed.work_id is None else get_work(project, seed.work_id)
        if work is None or not work.title.strip():
            skipped += 1
        else:
            works.append(work)
    return works, skipped


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(math.fsum(x * x for x in vector))
    return [x / norm for x in vector] if norm > 0 else [0.0] * len(vector)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def order_by_score(scores: dict[str, float]) -> list[tuple[str, float]]:
    """Score descending, work id ascending on a tie."""
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def max_cosine_scores(
    embedder: Embedder, references: Sequence[Work], candidates: Sequence[Work]
) -> dict[str, float]:
    """Each candidate's maximum cosine to any reference text, rounded to `SCORE_DECIMALS`, by work
    id. One embedder call, references first. Used by the ranking and by a capped forward round."""
    vectors = embedder.embed([ranking_text(w) for w in [*references, *candidates]])
    if len(vectors) != len(references) + len(candidates):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "embedder",
                    f"the embedder returned {len(vectors)} vectors for "
                    f"{len(references) + len(candidates)} texts; check the ranker's extra and "
                    "weights, then run it again",
                )
            ]
        )
    units = [_unit(v) for v in vectors]
    reference_units, candidate_units = units[: len(references)], units[len(references) :]
    return {
        work.id: round(max(_dot(unit, ref) for ref in reference_units), SCORE_DECIMALS)
        for work, unit in zip(candidates, candidate_units, strict=True)
    }


def compute_ranking(project: Project, embedder: Embedder) -> RankingComputed:
    """Rank the works still to be screened and record `ranking.computed` as the system.

    Refused, with nothing written, when there is nothing to rank or no development seed can be
    embedded, and when the ranked set or the references changed while embedding."""
    project.index.sync()
    ids = to_rank(project)
    refs, skipped = reference_works(project)
    issues: list[ValidationIssue] = []
    if not ids:
        issues.append(ValidationIssue("corpus", "no record is left to screen"))
    if not refs:
        issues.append(ValidationIssue("seeds", "no development positive seed has a title"))
    if issues:
        raise FactoryValidationError(issues)
    by_id = {work.id: work for work in list_works(project)}
    missing = [work_id for work_id in ids if work_id not in by_id]
    if missing:
        raise FactoryValidationError(
            [ValidationIssue("corpus", f"{len(missing)} works to rank are not in the corpus")]
        )
    candidates = [by_id[work_id] for work_id in ids]
    scores = max_cosine_scores(embedder, refs, candidates)
    ordered = order_by_score(scores)
    parameters = RankingParameters(references=tuple(w.id for w in refs), skipped_seeds=skipped)
    with project.writing():
        project.index.sync()
        now_refs, _ = reference_works(project)
        if to_rank(project) != ids or [w.id for w in now_refs] != [w.id for w in refs]:
            raise FactoryValidationError(
                [ValidationIssue("corpus", "the corpus or the seeds changed; rank again")]
            )
        payload = RankingComputed(
            ranking_id=project.ids.new("rnk"),
            model_id=embedder.model_id,
            weights_hash=embedder.weights_hash,
            software=embedder.software,
            parameters=parameters,
            corpus_hash=corpus_hash(ids),
            count=len(ids),
            order=project.blobs.put_json(
                [{"work_id": work, "score": score} for work, score in ordered]
            ),
        )
        event = project.events.make(
            "ranking.computed", payload, project.system_actor(), refs=(payload.ranking_id,)
        )
        project.record([event])
    return payload


def latest_ranking(project: Project, top: int | None = None) -> RankingView | None:
    """The latest ranking with its first `top` works (all when None), or None before any."""
    project.index.sync()
    with project.index.connect() as conn:
        head = conn.execute(
            text(
                "SELECT ranking_id, model_id, weights_hash, software, count FROM rankings "
                "ORDER BY event_id DESC LIMIT 1"
            )
        ).first()
        if head is None:
            return None
        sql = "SELECT position, work_id, score FROM ranking_positions ORDER BY position"
        params: dict[str, int] = {}
        if top is not None:
            sql += " LIMIT :top"
            params["top"] = max(top, 0)
        rows = conn.execute(text(sql), params).all()
    return RankingView(
        ranking_id=str(head[0]),
        model_id=str(head[1]),
        weights_hash=str(head[2]),
        software=str(head[3]),
        count=int(head[4]),
        ranked=[RankedWork(position=int(p), work_id=str(w), score=float(s)) for p, w, s in rows],
    )
