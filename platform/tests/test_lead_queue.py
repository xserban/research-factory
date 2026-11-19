"""The lead queue (hypothesis engine, task 2): measures, the printed order, determinism."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.lead_engine import (
    DEFAULT_ORDER,
    MEASURES,
    Measures,
    QueueItem,
    Verification,
)
from factory.services.context import Project
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_queue import _sort_key, lead_queue
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.lead_engine_helpers import engine_world

KNOBS = {"layer": "all", "technique_min_works": 1}


def _m(**over: object) -> Measures:
    base: dict[str, object] = {
        "support": 1,
        "independence": 1,
        "verification": Verification(verified=1, total=1, share=1.0),
        "supportive_share": None,
        "overlap": None,
        "diversity": 1.0,
        "diversity_vs": None,
        "prior_hits": 0,
        "narrow_prior_hits": 0,
        "closed_direction_hit": False,
        "score": 0.0,
        "score_flag": None,
        "basis": "live",
    }
    base.update(over)
    return Measures.model_validate(base)


def _q(entry: str, **over: object) -> QueueItem:
    return QueueItem(
        kind="candidate",
        entry_id=entry,
        source="technique-gap",
        rank=0,
        measures=_m(**over),
        prior=(),
        flags=(),
    )


def test_the_order_is_lexicographic_with_non_live_rows_last_and_ties_by_id() -> None:
    items = [
        _q("c", support=5, independence=2),
        _q("a", support=1, independence=2),
        _q("b", support=9, independence=1),
        _q("z", support=99, independence=9, basis="superseded"),
        _q("d", support=5, independence=2, prior_hits=1, narrow_prior_hits=1),
        _q("e", support=5, independence=2, prior_hits=1, closed_direction_hit=True),
    ]
    order = ("prior_hits", "independence", "support")
    ranked = sorted(items, key=lambda i: _sort_key(i, order))
    assert [i.entry_id for i in ranked] == ["c", "a", "b", "d", "e", "z"]
    by_support = sorted(items, key=lambda i: _sort_key(i, ("support",)))
    assert [i.entry_id for i in by_support] == ["b", "c", "d", "e", "a", "z"]
    assert set(MEASURES) >= set(DEFAULT_ORDER)


def test_measures_of_the_candidates_of_a_world(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = engine_world(project, agent, human, world)
    queue = lead_queue(project, **KNOBS)
    assert queue.exploratory and queue.klass == "interpretation"
    assert queue.order_by == DEFAULT_ORDER and "ties by entry id" in queue.order_rule
    assert "comparable only within this call" in queue.comparability
    assert queue.leads == () and queue.total_candidates == len(queue.items)
    assert [i.rank for i in queue.items] == list(range(1, len(queue.items) + 1))
    by_id = {i.entry_id: i for i in queue.items}
    challenge = by_id["technique-challenge:ide-01"].measures
    assert (challenge.support, challenge.independence) == (2, 2)
    assert challenge.verification == Verification(verified=2, total=2, share=1.0)
    assert challenge.supportive_share == 0.5 and challenge.score_flag is not None
    assert challenge.basis == "live" and challenge.prior_hits == 0 and challenge.diversity == 1.0
    claim = next(i for i in queue.items if i.source == "claims-limitation")
    assert claim.measures.support == 1 and claim.measures.supportive_share is None
    assert claim.measures.verification.share == 1.0 and "no-score" in claim.flags
    combo = by_id["technique-combination:ide-02+exp-01"]
    assert (
        combo.measures.overlap == 0 and combo.measures.score > 0 and "no-score" not in combo.flags
    )
    assert combo.candidate is not None and ordered[0] in {w.work_id for w in combo.candidate.works}
    again = lead_queue(project, **KNOBS)
    assert queue.model_dump_json(by_alias=True) == again.model_dump_json(by_alias=True)


def test_the_order_and_the_top_cap_are_runtime_knobs(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    fresh = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    by_support = lead_queue(project, candidates=fresh, order_by=("support",), top=3)
    assert len(by_support.items) == 3 and by_support.total_candidates == len(fresh.candidates)
    supports = [i.measures.support for i in by_support.items]
    assert supports == sorted(supports, reverse=True)
    assert by_support.order_by == ("support",) and "support (descending)" in by_support.order_rule
    for bad in ({"order_by": ("nope",)}, {"order_by": ()}, {"top": 0}, {"per_source": 0}):
        with pytest.raises(FactoryValidationError) as caught:
            lead_queue(project, **bad)  # type: ignore[arg-type]
        assert caught.value.issues[0].field == next(iter(bad))
