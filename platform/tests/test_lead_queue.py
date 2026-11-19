"""The lead queue (hypothesis engine, task 2): measures, the printed order, determinism."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.lead_engine import (
    DEFAULT_ORDER,
    MEASURES,
    Measures,
    QueueItem,
    Verification,
)
from factory.services import lead_queue as lq
from factory.services.chat_read import VerifyResult
from factory.services.context import Project
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_queue import _balanced, _sort_key, lead_queue
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
    combo = by_id["technique-combination:exp-01+ide-02"]
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


def test_the_top_is_balanced_across_sources_unless_global_order_is_asked(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    fresh = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    sources = {c.source for c in fresh.candidates}
    assert len(sources) > 1
    flat = lead_queue(project, candidates=fresh, order_by=("support",), top=50, balance=False)
    for top in range(len(sources), len(flat.items) + 1):
        queue = lead_queue(project, candidates=fresh, order_by=("support",), top=top)
        assert {i.source for i in queue.items} == sources
        assert len(queue.items) <= top
        assert [i.rank for i in queue.items] == list(range(1, len(queue.items) + 1))
        order = [i.entry_id for i in flat.items]
        got = [i.entry_id for i in queue.items]
        assert got == sorted(got, key=order.index)  # merged by the global order
        assert queue.parameters["balance"] == 1
    narrow = lead_queue(project, candidates=fresh, order_by=("support",), top=1, balance=False)
    assert [i.entry_id for i in narrow.items] == [flat.items[0].entry_id]
    assert narrow.parameters["balance"] == 0
    assert flat.total_candidates == len(fresh.candidates)
    one = lead_queue(project, candidates=fresh, order_by=("support",), top=50, per_source_top=1)
    assert len(one.items) == len(sources) and one.parameters["per_source_top"] == 1
    for bad in ({"per_source_top": 0}, {"per_source_top": 2, "balance": False}):
        with pytest.raises(FactoryValidationError) as caught:
            lead_queue(project, **bad)  # type: ignore[arg-type]
        assert caught.value.issues[0].field == "per_source_top"


def _src(entry: str, source: str) -> QueueItem:
    return _q(entry).model_copy(update={"source": source})


def test_balanced_edge_cases_sources_above_top_empty_source_and_freed_slots() -> None:
    many = [_src(f"{s}:0", s) for s in "abcde"]
    assert [i.entry_id for i in _balanced(many, 1, 3)] == ["a:0", "b:0", "c:0"]  # global order
    # a source with fewer entries than its share frees its slots for the others
    ordered = [_src(f"a:{n}", "a") for n in range(10)] + [_src("b:0", "b")]
    got = _balanced(ordered, 3, 6)
    assert len(got) == 6 and "b:0" in {i.entry_id for i in got}
    assert [i.entry_id for i in got if i.source == "a"] == [f"a:{n}" for n in range(5)]
    assert len(_balanced(ordered, 3, 6, fill=False)) == 4  # an explicit cap is kept
    # a source with no entry takes no slot: the one source left fills the top
    only = [_src(f"a:{n}", "a") for n in range(10)]
    assert len(_balanced(only, 3, 6)) == 6
    # quota above top: the entries that are not a source's first go from the global tail
    two = [_src(f"{s}:{n}", s) for n in range(4) for s in "ab"]
    assert [i.entry_id for i in _balanced(two, 4, 3)] == ["a:0", "b:0", "a:1"]
    # ties: the given order is kept
    tied = [_src("a:0", "a"), _src("b:0", "b"), _src("a:1", "a"), _src("b:1", "b")]
    assert [i.entry_id for i in _balanced(tied, 1, 4)] == ["a:0", "b:0", "a:1", "b:1"]


def test_one_source_is_not_balanced_and_per_source_top_is_not_applied(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    one = lead_queue(
        project, sources=("technique-gap",), top=5, per_source_top=1, order_by=("support",), **KNOBS
    )  # type: ignore[arg-type]
    assert len({i.source for i in one.items}) == 1 and one.parameters["per_source_top"] is None
    assert len(one.items) == min(5, one.total_candidates)


def test_a_measure_without_a_value_sorts_last_never_as_zero() -> None:
    def v(ok: int, total: int, share: float | None) -> Verification:
        return Verification(verified=ok, total=total, share=share)

    items = [
        _q("a", supportive_share=None, overlap=None, verification=v(0, 0, None)),
        _q("b", supportive_share=0.0, overlap=7, verification=v(0, 2, 0.0)),
        _q("c", supportive_share=0.5, overlap=0, verification=v(1, 2, 0.5)),
    ]
    for measure, want in (
        ("supportive_share", ["c", "b", "a"]),
        ("overlap", ["c", "b", "a"]),
        ("verification", ["c", "b", "a"]),
    ):
        ranked = sorted(items, key=lambda i: _sort_key(i, (measure,)))
        assert [i.entry_id for i in ranked] == want, measure


def _count_verify(monkeypatch: pytest.MonkeyPatch, status: str | None) -> list[int]:
    real = lq.chat_verify
    calls: list[int] = []

    def fake(project: Project, items: list[object]) -> list[VerifyResult]:
        calls.append(len(items))
        out = real(project, items)  # type: ignore[arg-type]
        if status is None:
            return out
        return [VerifyResult(r.item, status, None, None) for r in out]

    monkeypatch.setattr(lq, "chat_verify", fake)
    return calls


def _share(project: Project) -> float | None:
    queue = lead_queue(project, order_by=("support",), **KNOBS)  # type: ignore[arg-type]
    claim = next(i for i in queue.items if i.source == "claims-limitation")
    return claim.measures.verification.share


def test_only_accepted_verifications_are_remembered(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_world(project, agent, human, world)
    lq._VERIFIED.clear()
    with monkeypatch.context() as m:  # a transient failure: conversion unreadable now
        _count_verify(m, "no-conversion")
        assert _share(project) == 0.0
    assert not lq._VERIFIED  # a negative result is never stored
    calls = _count_verify(monkeypatch, None)
    assert _share(project) == 1.0 and calls  # readable again: verified
    assert lq._VERIFIED
    calls.clear()
    assert _share(project) == 1.0 and not calls  # accepted verdicts are served from the memo


def test_a_changed_conversion_at_the_same_path_is_verified_again(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_world(project, agent, human, world)
    lq._VERIFIED.clear()
    assert _share(project) == 1.0 and lq._VERIFIED
    real = lq.conversion_of

    class _Other:
        markdown_hash = "a-different-markdown"

    monkeypatch.setattr(
        lq, "conversion_of", lambda p, cid: None if real(p, cid) is None else _Other()
    )
    calls = _count_verify(monkeypatch, "quote-not-in-anchor")
    assert _share(project) == 0.0 and calls  # the old verdict is not served for new content
    assert len(lq._VERIFIED) >= 1


def test_a_stored_row_without_a_quote_is_unverified_and_flagged_not_read_as_its_value(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    lq._VERIFIED.clear()
    fresh = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    claim = next(c for c in fresh.candidates if c.source == "claims-limitation")
    [ext] = [t.ref for t in claim.triggers if t.kind == "item"]
    with project.index._engine.begin() as conn:  # a test world: the projection is rebuildable
        conn.execute(
            text(
                "UPDATE extraction_fields SET quote = NULL "
                "WHERE extraction_id = :e AND field = 'claim_quote'"
            ),
            {"e": ext},
        )
    queue = lead_queue(project, candidates=fresh, order_by=("support",), **KNOBS)  # type: ignore[arg-type]
    item = next(i for i in queue.items if i.entry_id == claim.candidate_id)
    assert item.measures.verification == Verification(verified=0, total=1, share=0.0)
    assert "no-stored-quote" in item.flags
