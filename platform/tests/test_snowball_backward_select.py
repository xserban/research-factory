"""Selected backward rounds (decision 135): publication window, cited-by floor and similarity to
the development seeds, taken offline from the stored records.

A fake embedder stands in for SPECTER2, so no torch or weights are needed. Every work is invented.
The world is that of `tests/test_snowball_round.py`: three candidates, a lattice paper cited by
both source works (arXiv, 2020), a reed paper (OpenAlex, 2021) and a no-source-record entry.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import SnowballPlan
from factory.model.references import (
    BackwardSelection,
    Direction,
    SnowballRoundStarted,
    TakenCandidate,
)
from factory.services import snowball
from factory.services.context import Project
from factory.services.search import list_works
from factory.services.snowball import RoundResult, plan_round, recorded_rounds, snowball_round
from tests.document_helpers import event_bytes, events_of_type
from tests.test_snowball_round import (  # noqa: F401
    _amend,
    _sources,
    world,
)

pytestmark = pytest.mark.usefixtures("world")

PLAN = SnowballPlan(max_backward_rounds=2, max_forward_rounds=0)


class WordEmbedder:
    """Titles with `lattice` embed to [0, 1], with `reed` to [1, 1]; any other text (the seed
    references) to [0, 1]. A candidate's score is therefore 1.0 (lattice) or ~0.707 (reed)."""

    model_id = "fake/words"
    weights_hash = hashlib.sha256(b"words").hexdigest()
    software = "fake==1"

    def __init__(self, project: Project | None = None) -> None:
        self.project = project
        self.calls: list[list[str]] = []
        self.holding: list[bool] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.project is not None:
            self.holding.append(self.project.index._holding)
        return [[1.0, 1.0] if "reed" in t.lower() else [0.0, 1.0] for t in texts]


def _planned(project: Project, agent: Actor, **options: Any) -> None:
    _amend(project, agent, PLAN.model_copy(update=options))


def _round(
    project: Project, agent: Actor, *, dry_run: bool, embedder: WordEmbedder | None = None
) -> RoundResult:
    return snowball_round(
        project,
        agent,
        Direction.BACKWARD,
        sources=_sources(),
        dry_run=dry_run,
        embedder=embedder,
    )


def _titles(project: Project, result: RoundResult) -> set[str]:
    ids = {str(c.work_id) for c in result.candidates}
    return {w.title for w in snowball.stored_works(project, sorted(ids)).values()}


def test_a_plan_without_options_takes_every_candidate(project: Project, agent: Actor) -> None:
    _planned(project, agent)
    result = _round(project, agent, dry_run=True)
    assert len(result.candidates) == 3 and result.backward_selection is None
    # an unselected round routes as before: network sources, never `stored`
    assert {q.source for q in result.queries} == {"openalex", "arxiv", "reflist"}


def test_selected_round_routes_stored_candidates_to_stored_and_no_source_to_reflist(
    project: Project, agent: Actor
) -> None:
    _planned(project, agent, backward_min_cited_by=1)
    result = _round(project, agent, dry_run=True)
    assert {q.source for q in result.queries} == {"stored", "reflist"}


def test_published_window_drops_before_and_undated_candidates(
    project: Project, agent: Actor
) -> None:
    _planned(project, agent, backward_published_from=date(2021, 1, 1))
    result = _round(project, agent, dry_run=True)
    selection = result.backward_selection
    assert selection is not None and selection.published_from == date(2021, 1, 1)
    assert (selection.considered, selection.dropped_before_window, selection.dropped_undated) == (
        3,
        1,
        1,
    )
    assert [t.cited_by for t in selection.taken] == [1] and selection.not_taken == 2
    assert _titles(project, result) == {"Efficient Reed Transformers"}


def test_cited_by_floor_keeps_the_works_cited_by_enough_sources(
    project: Project, agent: Actor
) -> None:
    _planned(project, agent, backward_min_cited_by=2)
    result = _round(project, agent, dry_run=True)
    selection = result.backward_selection
    assert selection is not None and selection.dropped_cited_by == 2
    assert [(t.cited_by, t.score) for t in selection.taken] == [(2, None)]
    assert [c.cited_by_included for c in result.candidates] == [2]
    assert [q.source for q in result.queries] == ["stored"]


def test_similarity_embeds_only_the_survivors_of_the_earlier_steps(
    project: Project, agent: Actor
) -> None:
    _planned(project, agent, backward_min_cited_by=1, backward_min_similarity=0.9)
    embedder = WordEmbedder(project)
    result = _round(project, agent, dry_run=True, embedder=embedder)
    selection = result.backward_selection
    assert selection is not None
    assert selection.model_id == "fake/words" and selection.weights_hash == embedder.weights_hash
    # The no-source entry has no stored work to embed; the reed paper scores ~0.707.
    assert (selection.dropped_unscored, selection.dropped_similarity) == (1, 1)
    assert [t.score for t in selection.taken] == [1.0]
    assert _titles(project, result) == {"A lattice is worth sixteen tokens"}
    # Embedded outside the write lock, once.
    assert embedder.holding == [False] and len(embedder.calls) == 1
    assert len(embedder.calls[0]) > 2

    _planned(project, agent, backward_min_cited_by=2, backward_min_similarity=0.9)
    narrow = WordEmbedder()
    _round(project, agent, dry_run=True, embedder=narrow)
    # Only the cited-by survivor is embedded after the references.
    assert len(narrow.calls[0]) == len(embedder.calls[0]) - 1


def test_dry_run_writes_nothing_and_a_recorded_round_takes_the_chosen_offline(
    project: Project, agent: Actor
) -> None:
    _planned(project, agent, backward_min_cited_by=2, backward_min_similarity=0.9)
    before = event_bytes(project)
    dry = _round(project, agent, dry_run=True, embedder=WordEmbedder())
    assert event_bytes(project) == before and dry.round_id is None and dry.state.allowed

    held = {w.id for w in list_works(project)}
    result = _round(project, agent, dry_run=False, embedder=WordEmbedder())
    assert result.round_id is not None and result.new_works == 1
    assert [q.source for q in result.queries] == ["stored"]
    assert result.backward_selection == dry.backward_selection
    new = {w.title for w in list_works(project) if w.id not in held}
    assert new == {"A lattice is worth sixteen tokens"}
    [ledger] = events_of_type(project, "snowball.round_started")
    payload = SnowballRoundStarted.model_validate(ledger.payload)
    assert payload.backward_selection == result.backward_selection
    assert [c.work_key for c in payload.candidates] == [
        t.work_key
        for t in payload.backward_selection.taken  # type: ignore[union-attr]
    ]
    [recorded] = recorded_rounds(project)
    assert recorded.backward_selection == result.backward_selection
    assert recorded.selection is None


def test_a_round_without_a_selection_records_none(project: Project, agent: Actor) -> None:
    _planned(project, agent)
    _round(project, agent, dry_run=False)
    [ledger] = events_of_type(project, "snowball.round_started")
    assert "backward_selection" not in ledger.payload and "selection" not in ledger.payload
    [recorded] = recorded_rounds(project)
    assert recorded.backward_selection is None and recorded.selection is None


def test_similarity_without_the_extra_is_refused_with_the_remedy(
    project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACTORY_RANKER_MODEL", raising=False)
    _planned(project, agent, backward_min_similarity=0.9)
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as refused:
        _round(project, agent, dry_run=False)
    assert "FACTORY_RANKER_MODEL" in str(refused.value) and "uv sync --extra ranker" in str(
        refused.value
    )
    assert event_bytes(project) == before


def test_changed_seeds_between_ranking_and_recording_refuse_the_round(
    project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _planned(project, agent, backward_min_similarity=0.9)
    embedder = WordEmbedder()
    real = embedder.embed

    def embed_then_change_seeds(texts: Sequence[str]) -> list[list[float]]:
        out = real(texts)
        monkeypatch.setattr(snowball, "reference_works", lambda _p: ([], 0))
        return out

    embedder.embed = embed_then_change_seeds  # type: ignore[method-assign]
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as refused:
        _round(project, agent, dry_run=False, embedder=embedder)
    assert [i.field for i in refused.value.issues] == ["seeds"]
    assert event_bytes(project) == before


def test_a_selection_that_takes_nothing_is_refused(project: Project, agent: Actor) -> None:
    _planned(project, agent, backward_published_from=date(2030, 1, 1))
    before = event_bytes(project)
    dry = _round(project, agent, dry_run=True)
    assert not dry.state.allowed and [i.field for i in dry.state.refusals] == ["candidates"]
    with pytest.raises(FactoryValidationError):
        _round(project, agent, dry_run=False)
    assert event_bytes(project) == before
    assert plan_round(project, Direction.BACKWARD).candidates  # the plan itself is unfiltered


def test_selection_model_invariants() -> None:
    kept = TakenCandidate(work_key="rf:a-00000000", cited_by=2, score=0.95)
    with pytest.raises(ValueError, match="at least one threshold"):
        BackwardSelection(considered=0)
    with pytest.raises(ValueError, match="dropped by one step or taken"):
        BackwardSelection(min_cited_by=2, considered=3, taken=(kept,))
    with pytest.raises(ValueError, match="records its model"):
        BackwardSelection(min_similarity=0.9, considered=1, taken=(kept,))
    with pytest.raises(ValueError, match="only when the similarity step ran"):
        BackwardSelection(min_cited_by=2, model_id="m", considered=1, taken=(kept,))
    ok = BackwardSelection(min_cited_by=2, considered=3, dropped_cited_by=2, taken=(kept,))
    assert ok.not_taken == 2
    with pytest.raises(ValueError, match="at least the similarity threshold"):
        BackwardSelection(
            min_similarity=0.99,
            model_id="m",
            weights_hash="a" * 64,
            software="s",
            considered=1,
            taken=(kept,),
        )


def test_plan_and_result_lines_show_the_selection(project: Project, agent: Actor) -> None:
    from factory.cli.render import round_plan_lines, round_result_lines

    _planned(project, agent, backward_min_cited_by=1, backward_min_similarity=0.9)
    dry = _round(project, agent, dry_run=True, embedder=WordEmbedder())
    text = "\n".join(round_plan_lines("backward", dry, []))
    assert "selection: cited by at least 1, similarity at least 0.9" in text
    assert "model fake/words" in text and "taken 1, not taken 2" in text
    assert "score 1.0000, cited by 2" in text
    done = _round(project, agent, dry_run=False, embedder=WordEmbedder())
    assert "taken 1, not taken 2" in "\n".join(round_result_lines(done))
