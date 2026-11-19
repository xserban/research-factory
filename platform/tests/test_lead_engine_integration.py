"""The candidate layer against the real lead service (hypothesis engine, task 5): the first
candidate of each source is accepted by `record_lead`, a prior shows up in M7 after a park, a
superseded row is flagged by M9, and a miner `rk_` is refused as a `row` trigger (B2)."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import MinerScope
from factory.model.hypotheses import LeadInput, Trigger, TriggerKind
from factory.model.lead_engine import SOURCES, Candidate, CandidateTrigger
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import live_rows
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_queue import lead_queue
from factory.services.leads import decide_lead, list_leads, record_lead, trigger_issues
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.hypothesis_helpers import LEAD_AUTHOR, LEAD_TEXT
from tests.lead_engine_helpers import (
    engine_world,
    mine_claims_superseding,
    mine_technique,
    register_technique_miners,
)

KNOBS = {"layer": "all", "technique_min_works": 1}


def _triggers(candidate: Candidate) -> tuple[Trigger, ...]:
    return tuple(Trigger(kind=TriggerKind(t.kind), ref=t.ref) for t in candidate.triggers)


def _first_of_each(project: Project) -> dict[str, Candidate]:
    first: dict[str, Candidate] = {}
    for c in lead_candidates(project, **KNOBS).candidates:  # type: ignore[arg-type]
        first.setdefault(c.source, c)
    assert set(first) == set(SOURCES)
    return first


def _record(project: Project, candidate: Candidate, text: str = LEAD_TEXT) -> str:
    return record_lead(project, LEAD_AUTHOR, LeadInput(text=text, triggers=_triggers(candidate)))


def test_the_first_candidate_of_each_source_is_accepted_by_lead_record(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    first = _first_of_each(project)
    for candidate in first.values():
        assert trigger_issues(project, _triggers(candidate)) == []
    ids = {source: _record(project, c) for source, c in first.items()}
    assert len(set(ids.values())) == 4
    assert {v.state for v in list_leads(project)} == {"open"}
    # a made-up item is refused, as the plan's test 9 says
    with pytest.raises(FactoryValidationError) as caught:
        record_lead(
            project,
            LEAD_AUTHOR,
            LeadInput(
                text=LEAD_TEXT,
                triggers=(Trigger(kind=TriggerKind.ITEM, ref="ext_01JZ9Q3K5M7N8P0R2S4T6V8WZZ"),),
            ),
        )
    assert caught.value.issues[0].field == "triggers.0"


def test_a_miner_row_key_is_not_a_row_trigger(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """B2: `rk_` of a miner row resolves only as an evidence cell, so `row` is refused; the
    candidates therefore never carry `row`."""
    engine_world(project, agent, human, world)
    row = live_rows(project, PassLabel.A, scope=MinerScope("m-tech-ideation"))[0]
    with pytest.raises(FactoryValidationError) as caught:
        record_lead(
            project,
            LEAD_AUTHOR,
            LeadInput(text=LEAD_TEXT, triggers=(Trigger(kind=TriggerKind.ROW, ref=row.row_key),)),
        )
    assert caught.value.issues[0].field == "triggers.0"
    for scope in ("m-tech-ideation", "m-tech-experiment", "m-claims"):  # every miner family
        for r in live_rows(project, PassLabel.A, scope=MinerScope(scope)):
            with pytest.raises(FactoryValidationError):
                record_lead(
                    project,
                    LEAD_AUTHOR,
                    LeadInput(
                        text=LEAD_TEXT, triggers=(Trigger(kind=TriggerKind.ROW, ref=r.row_key),)
                    ),
                )
    for c in lead_candidates(project, **KNOBS).candidates:  # type: ignore[arg-type]
        assert {t.kind for t in c.triggers} <= {"item", "work"}


def test_a_parked_lead_shows_as_a_prior_hit_with_narrow_and_broad_collisions(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = engine_world(project, agent, human, world)
    first = _first_of_each(project)
    challenge, claim = first["technique-challenge"], first["claims-limitation"]
    parked = _record(project, challenge)
    other = _record(project, claim)
    decide_lead(project, human, parked, "park")
    before = lead_queue(project, **KNOBS)  # type: ignore[arg-type]
    hit_item = next(i for i in before.items if i.entry_id == challenge.candidate_id)
    [hit] = hit_item.prior
    assert (hit.kind, hit.id, hit.detail) == ("lead", parked, "parked")
    assert set(hit.shared_items) == {t.ref for t in challenge.triggers if t.kind == "item"}
    assert set(hit.shared_works) == set(ordered[:2])
    assert hit_item.measures.prior_hits == 1 and hit_item.measures.narrow_prior_hits == 1
    # the claims candidate shares only a work with the parked lead: a broad hit, not a narrow one
    sharing_work = [i for i in before.items if i.source == "claims-limitation"]
    broad = [h for i in sharing_work for h in i.prior if not h.shared_items]
    assert broad and all(h.id == parked and h.shared_works for h in broad)
    # fewest prior hits first (closed direction, narrow, then all): the key never decreases
    keys = [
        (m.closed_direction_hit, m.narrow_prior_hits, m.prior_hits)
        for m in (i.measures for i in before.items)
    ]
    assert keys == sorted(keys)
    # the open lead is in the queue's lead list, its own id never a hit against itself
    assert [i.entry_id for i in before.leads] == [other]
    assert before.leads[0].source == "claims" and before.leads[0].measures.basis == "live"
    left = lead_queue(project, exclude_prior=True, **KNOBS)  # type: ignore[arg-type]
    assert challenge.candidate_id in {e.candidate_id for e in left.excluded}
    assert challenge.candidate_id not in {i.entry_id for i in left.items}


def test_diversity_counts_shared_items_and_approaches_never_shared_works(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    first = _first_of_each(project)
    promoted = _record(project, first["claims-limitation"])
    decide_lead(project, human, promoted, "promote")
    queue = lead_queue(project, **KNOBS)  # type: ignore[arg-type]
    by_id = {i.entry_id: i for i in queue.items}
    same = by_id[first["claims-limitation"].candidate_id].measures
    assert same.diversity == 0.0 and same.diversity_vs == promoted
    # a technique candidate over the same work (W0) shares a work only: fully diverse
    assert by_id[first["technique-challenge"].candidate_id].measures.diversity == 1.0
    assert queue.leads == ()  # promoted leads are not undecided


def test_a_lead_citing_a_superseded_row_is_flagged_by_m9_and_sorted_last(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """B5: `item` resolves a superseded row, so `record_lead` accepts it; the queue recomputes
    liveness and flags the lead instead of dropping it, and the candidate service never offers the
    superseded row."""
    ordered = register_technique_miners(project, agent, human, world)
    mine_technique(project, ordered)
    old, new = mine_claims_superseding(project, agent, ordered)
    assert old and new and old != new
    fresh = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    offered = {t.ref for c in fresh.candidates for t in c.triggers}
    assert old not in offered and new in offered
    stale_lead = record_lead(
        project,
        LEAD_AUTHOR,
        LeadInput(text=LEAD_TEXT, triggers=(Trigger(kind=TriggerKind.ITEM, ref=old),)),
    )
    live_claim = next(c for c in fresh.candidates if new in {t.ref for t in c.triggers})
    live_lead = _record(project, live_claim)
    queue = lead_queue(project, candidates=fresh, **KNOBS)  # type: ignore[arg-type]
    by_lead = {i.entry_id: i for i in queue.leads}
    assert by_lead[stale_lead].measures.basis == "superseded"
    assert (
        by_lead[stale_lead].stale_refs == (old,) and "basis-superseded" in by_lead[stale_lead].flags
    )
    assert by_lead[live_lead].measures.basis == "live"
    assert [i.entry_id for i in queue.leads] == [live_lead, stale_lead]  # flagged last, kept
    # a candidate handed in after its row changed is flagged and sorted last, never dropped
    stale = live_claim.model_copy(
        update={
            "candidate_id": "claims-limitation:stale",
            "triggers": (CandidateTrigger(kind="item", ref=old),),
        }
    )
    ghost = live_claim.model_copy(
        update={
            "candidate_id": "claims-limitation:ghost",
            "triggers": (CandidateTrigger(kind="item", ref="ext_01JZ9Q3K5M7N8P0R2S4T6V8WZZ"),),
        }
    )
    handed = fresh.model_copy(update={"candidates": (stale, ghost, *fresh.candidates)})
    again = lead_queue(project, candidates=handed, **KNOBS)  # type: ignore[arg-type]
    assert {i.entry_id for i in again.items[-2:]} == {
        "claims-limitation:ghost",
        "claims-limitation:stale",
    }
    states = {i.entry_id: i.measures.basis for i in again.items[-2:]}
    assert states == {
        "claims-limitation:stale": "superseded",
        "claims-limitation:ghost": "unknown",
    }
    assert len(again.items) == len(fresh.candidates) + 2


def test_a_stale_basis_is_flagged_sorted_last_and_kept(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M9 `stale`: the ledger of a scope names a row stale (an amendment recorded after it); the
    queue flags every candidate citing it, sorts it last and keeps it."""
    from factory.services import lead_queue as lq

    engine_world(project, agent, human, world)
    fresh = lead_candidates(project, **KNOBS)  # type: ignore[arg-type]
    victim = next(c for c in fresh.candidates if c.source == "claims-limitation")
    [ext] = [t.ref for t in victim.triggers if t.kind == "item"]
    real = lq._stale
    monkeypatch.setattr(
        lq, "_stale", lambda p, scope: real(p, scope) | ({ext} if scope == "m-claims" else set())
    )
    queue = lead_queue(project, candidates=fresh, order_by=("support",), **KNOBS)  # type: ignore[arg-type]
    last = queue.items[-1]
    assert last.entry_id == victim.candidate_id and last.measures.basis == "stale"
    assert last.stale_refs == (ext,) and "basis-stale" in last.flags
    assert len(queue.items) == len(fresh.candidates)
