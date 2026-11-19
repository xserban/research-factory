"""Contradiction map (night feature N10): proposals between two m-claims rows with verified
quotes, and the hub payload that groups the pairs by topic."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import MinerScope
from factory.model.findings import ContradictionInput, ContradictionProposed
from factory.model.screening import PassLabel
from factory.services import finders
from factory.services import hub_contradictions as hc
from factory.services.context import Project
from factory.services.extraction import live_rows
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)
from tests.miner_helpers import list_miner, mine_pass, miner_actor


def _refs(project: Project, agent: Actor, world: list[str]) -> tuple[str, str]:
    list_miner(project, agent, claims_spec())
    mina = miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W1E", "claude-opus-5-5")
    mine_pass(
        project, mina, PassLabel.A, lambda w: [claim_row("finding", QUOTES[0])], name="m-claims"
    )
    works = sorted(world)[:2]
    keys = {r.work_id: r.row_key for r in live_rows(project, scope=MinerScope("m-claims"))}
    return tuple(hc.row_ref(w, keys[w]) for w in works)  # type: ignore[return-value]


def _events(project: Project, kind: str) -> list[dict[str, object]]:
    from factory.events.reader import read_all

    return [
        dict(e.payload)
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == kind
    ]


def test_row_refs_are_stored_with_verified_quote_and_anchor(
    project: Project, agent: Actor, world: list[str]
) -> None:
    a, b = _refs(project, agent, world)
    ident, new = finders.propose_contradiction(
        project, agent, ContradictionInput(ref_a=a, ref_b=b, note="opposite direction")
    )
    assert new
    [payload] = _events(project, "contradiction.proposed")
    p = ContradictionProposed.model_validate(payload)
    assert p.contradiction_id == ident
    assert (p.quote_a, p.quote_b) == (QUOTES[0], QUOTES[0])
    assert (p.anchor_a, p.anchor_b) == ("s3.p1", "s3.p1")
    again, new2 = finders.propose_contradiction(
        project, agent, ContradictionInput(ref_a=b, ref_b=a, note="same pair")
    )
    assert (again, new2) == (ident, False)


def test_unknown_row_key_is_refused_and_writes_nothing(
    project: Project, agent: Actor, world: list[str]
) -> None:
    a, _b = _refs(project, agent, world)
    bad = hc.row_ref(sorted(world)[1], "no-such-key")
    with pytest.raises(FactoryValidationError) as err:
        finders.propose_contradiction(
            project, agent, ContradictionInput(ref_a=a, ref_b=bad, note="x")
        )
    assert [(i.field, i.reason) for i in err.value.issues] == [("ref_b", "ref-unknown")]
    assert _events(project, "contradiction.proposed") == []


def test_old_events_without_anchors_stay_valid() -> None:
    old = {
        "contradiction_id": "ctr_01JZ9Q3K5M7N8P0R2S4T6V8W1E",
        "ref_a": "clm_01JZ9Q3K5M7N8P0R2S4T6V8W1E",
        "ref_b": "clm_01JZ9Q3K5M7N8P0R2S4T6V8W1F",
        "work_a": "rf:a-negative-1-73bc34f9",
        "work_b": "rf:b-negative-1-73bc34f8",
        "quote_a": "q",
        "quote_b": "r",
        "note": "n",
    }
    p = ContradictionProposed.model_validate(old)
    assert p.anchor_a is None and p.anchor_b is None


def test_payload_groups_by_topic_with_state_counts_and_seed(
    project: Project, agent: Actor, other_session_human: Actor, world: list[str]
) -> None:
    a, b = _refs(project, agent, world)
    ident, _ = finders.propose_contradiction(
        project, agent, ContradictionInput(ref_a=a, ref_b=b, note="opposite")
    )
    out = hc.contradictions_payload(project)
    assert out["counts"] == {"proposed": 1, "accepted": 0, "rejected": 0, "stale": 0, "all": 1}
    [topic] = out["topics"]
    assert topic["topic"] == "a" and topic["count"] == 1
    [pair] = topic["pairs"]
    assert pair["id"] == ident and pair["state"] == "proposed"
    assert pair["note"] == "opposite"
    for side in (pair["a"], pair["b"]):
        assert side["quote"] == QUOTES[0] and side["anchor"] == "s3.p1"
        assert side["paragraph"] and QUOTES[0] in side["paragraph"]
        assert side["row_key"] and side["work_id"] in world
    assert pair["seed"]["selection"]["include"] == sorted(
        [pair["a"]["work_id"], pair["b"]["work_id"]]
    )
    assert pair["seed"]["selection"]["layers"] == ["core"]
    assert pair["seed"]["hypothesis"] == pair["a"]["claim"]
    assert pair["decide"] == {
        "confirm": f"factory contradictions confirm {ident} --rationale '...'",
        "reject": f"factory contradictions reject {ident} --rationale '...'",
    }
    # a researcher's decision moves the pair; the proposer's own event does not
    # (the human actor is a different session)
    finders.decide_contradiction(
        project, other_session_human, ident, "confirm", "same topic, opposite result"
    )
    out = hc.contradictions_payload(project)
    assert out["counts"]["accepted"] == 1 and out["counts"]["proposed"] == 0
    assert out["topics"][0]["pairs"][0]["state"] == "accepted"


def test_empty_payload_is_ready_and_counts_zero(project: Project) -> None:
    out = hc.contradictions_payload(project)
    assert out["ready"] is True and out["topics"] == [] and out["counts"]["all"] == 0


def test_page_is_registered_and_built() -> None:
    from factory.services import hub_build, hub_ui

    assert "contradictions" in hub_ui.PAGES
    assert hub_ui.PAGES["contradictions"].payloads == ("shell", "contradictions")
    assert "contradictions" in hub_build.BUILDERS
