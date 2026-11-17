"""The screening ranking: references, determinism, ties, fold and supersession (decision 116).

A fake embedder stands in for the model, so no torch or weights are needed."""

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.index.ranking import corpus_hash
from factory.model.seed import SeedKind
from factory.services.context import Project
from factory.services.ranking import (
    SEPARATOR,
    compute_ranking,
    latest_ranking,
    ranking_positions,
    to_rank,
)
from factory.services.ranking_model import Specter2Embedder
from factory.services.seeds import SeedRole, all_seeds
from tests.helpers import SourcesFor, _setup
from tests.screening_helpers import decide


class FakeEmbedder:
    """Vectors from a hash of the text; records every call."""

    model_id = "fake/model"
    weights_hash = "a" * 64
    software = "fake==1"

    def __init__(self, constant: bool = False, salt: str = "") -> None:
        self.constant = constant
        self.salt = salt
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.constant:
            return [[1.0, 2.0, 3.0] for _ in texts]
        return [
            [float(b) - 127.5 for b in hashlib.sha256((self.salt + t).encode()).digest()[:8]]
            for t in texts
        ]


def _world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
    return _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=3)


def test_held_out_seeds_are_never_references(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    held = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    development = [
        s
        for s in all_seeds(project)
        if s.kind is SeedKind.POSITIVE and s.role is not SeedRole.HELD_OUT
    ]
    assert held and development
    embedder = FakeEmbedder()
    event = compute_ranking(project, embedder)
    references = set(event.parameters.references)
    assert references == {s.work_id for s in development}
    assert not references & {s.work_id for s in held}
    # The texts embedded as references are the first ones of the one call.
    texts = embedder.calls[0][: len(references)]
    for seed in held:
        assert not any(t.startswith(f"{seed.cite} {SEPARATOR}") for t in texts)


def test_held_out_work_is_ranked_like_any_corpus_record(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    held = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT and s.work_id}
    compute_ranking(project, FakeEmbedder())
    assert held <= set(ranking_positions(project))  # decision 37.9: no work is masked


def test_ranking_is_deterministic_and_complete(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    first = compute_ranking(project, FakeEmbedder())
    second = compute_ranking(project, FakeEmbedder())
    assert first.order == second.order  # same content, same blob
    assert first.ranking_id != second.ranking_id
    ids = to_rank(project)
    assert first.count == len(ids)
    assert first.corpus_hash == corpus_hash(ids)


def test_ties_break_by_work_id(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    compute_ranking(project, FakeEmbedder(constant=True))
    view = latest_ranking(project)
    assert view is not None
    ids = [item.work_id for item in view.ranked]
    assert ids == sorted(ids)
    assert {item.score for item in view.ranked} == {1.0}


def test_fold_and_supersession(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    assert latest_ranking(project) is None and ranking_positions(project) == {}
    first = compute_ranking(project, FakeEmbedder())
    view = latest_ranking(project, top=3)
    assert view is not None and view.ranking_id == first.ranking_id
    assert [item.position for item in view.ranked] == [1, 2, 3]
    assert view.model_id == "fake/model" and view.weights_hash == "a" * 64
    second = compute_ranking(project, FakeEmbedder(salt="other"))
    after = latest_ranking(project)
    assert after is not None and after.ranking_id == second.ranking_id
    positions = ranking_positions(project)
    assert sorted(positions.values()) == list(range(1, second.count + 1))
    with project.index.connect() as conn:
        from sqlalchemy import text

        assert conn.execute(text("SELECT count(*) FROM rankings")).scalar_one() == 2


@pytest.mark.parametrize("bad_score", [2.5, -3.0, 10**400, "0.5", True, None])
def test_a_malformed_ranking_event_changes_nothing_and_rebuild_agrees(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, bad_score: object
) -> None:
    from factory.model.ranking import RankingComputed

    _world(project, agent, human, mock_sources)
    good = compute_ranking(project, FakeEmbedder())
    ids = ["W1", "W2"]
    order = project.blobs.put_json(
        [{"work_id": ids[0], "score": bad_score}, {"work_id": ids[1], "score": 0.1}]
    )
    forged = RankingComputed.model_construct(
        **{
            **good.model_dump(),
            "ranking_id": "rnk_bad",
            "count": 2,
            "corpus_hash": corpus_hash(ids),
            "order": order,
        }
    )
    malformed = RankingComputed.model_construct(
        **{**good.model_dump(), "ranking_id": 7, "count": "x"}
    )
    events = [
        project.events.make("ranking.computed", forged, project.system_actor()),
        project.events.make("ranking.computed", malformed, project.system_actor()),
    ]

    def folded() -> tuple[object, ...]:
        from sqlalchemy import text

        project.index.sync()
        latest = latest_ranking(project)
        with project.index.connect() as conn:
            rows = sorted(repr(tuple(r)) for r in conn.execute(text("SELECT * FROM rankings")))
        return (latest and latest.ranking_id, ranking_positions(project), rows)

    before = folded()
    # Hand-written: the writer refuses a payload that fails its model (`rnk_` + ULID ids, integer
    # counts), so the lines go into the log directly, as a forged file would. The log gains the
    # events (the state hash covers them); the ranking tables must not move, on sync or rebuild.
    with project.writing():
        for event in events:
            path = project.paths.events_dir / event.actor.id / f"{event.actor.session}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as handle:
                handle.write(event.to_line())
    assert folded() == before
    project.index.rebuild()
    assert folded() == before


def test_screened_works_are_not_ranked(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _world(project, agent, human, mock_sources)
    before = to_rank(project)
    decide(project, agent, before[0], protocol_id, "include")
    after = to_rank(project)
    assert after == before[1:]
    event = compute_ranking(project, FakeEmbedder())
    assert event.count == len(after)
    assert before[0] not in ranking_positions(project)


def test_nothing_to_rank_or_no_reference_is_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        compute_ranking(project, FakeEmbedder())
    assert latest_ranking(project) is None


def test_missing_weights_or_extra_is_a_clear_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FACTORY_RANKER_MODEL", raising=False)
    with pytest.raises(FactoryValidationError) as unset:
        Specter2Embedder()
    assert "FACTORY_RANKER_MODEL" in str(unset.value)
    with pytest.raises(FactoryValidationError):
        Specter2Embedder(tmp_path / "absent")
    empty = tmp_path / "empty"
    empty.mkdir()
    embedder = Specter2Embedder(empty)
    assert len(embedder.weights_hash) == 64  # a tree hash of nothing is still a hash
    with pytest.raises(FactoryValidationError):
        embedder.embed(["a title [SEP] an abstract"])  # no loadable model there
