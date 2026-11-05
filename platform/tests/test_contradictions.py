"""Claim contradiction proposals with human decisions (slice 6, plan H-B, task 4).

The world is the G2 lineage world (contribution items of the source work) plus a pass-A evidence
extraction with one claim in each of two other works; the second claim is recorded in a task that
is still open, so the test can supersede it."""

# ruff: noqa: F401, F811

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.findings import (
    CONTRADICTION_ID_RE,
    ContradictionDecided,
    ContradictionInput,
)
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.evidence_report import evidence_report
from factory.services.extraction import extract_next, extract_record, live_claims
from factory.services.finders import (
    decide_contradiction,
    list_contradictions,
    propose_contradiction,
)
from tests.contribution_helpers import ext_a
from tests.evidence_helpers import claim_input
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world


@dataclass
class CtrWorld:
    lin: Lineage
    item: str
    """A contribution item of the source work."""
    item_other: str
    """Another contribution item of the source work."""
    claim_x: str
    work_x: str
    claim_y: str
    work_y: str
    task_y: str
    """The open pass-A task holding `claim_y`."""


@pytest.fixture
def ctrw(project: Project, ext_a: Actor, lin: Lineage, world: list[str]) -> CtrWorld:
    claims: list[tuple[str, str, str]] = []
    task_y = ""
    for _ in range(40):
        batch = extract_next(project, ext_a, PassLabel.A).batch
        if batch is None:
            break
        work = batch.records[0]["work_id"]
        if work == lin.source:
            extract_record(project, ext_a, batch.task_id, [], finish=True, reason="no result")
            continue
        res = extract_record(
            project, ext_a, batch.task_id, [], [claim_input()], finish=len(claims) == 0
        )
        assert res.claims.rejected == [], res.claims.rejected
        claims.append((res.claims.written[0], work, batch.task_id))
        if len(claims) == 2:  # the second task stays open: no further `extract_next`
            break
    (cx, wx, _), (cy, wy, task_y) = claims
    return CtrWorld(lin, lin.base, lin.addition, cx, wx, cy, wy, task_y)


def _events(project: Project, kind: str) -> list[object]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def test_propose_stores_quotes_and_sorted_refs(
    project: Project, agent: Actor, ctrw: CtrWorld
) -> None:
    cid, written = propose_contradiction(
        project,
        agent,
        ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note="the claim negates the item"),
    )
    assert written and CONTRADICTION_ID_RE and cid.startswith("ctr_")
    [event] = _events(project, "contradiction.proposed")
    payload = event.payload  # type: ignore[attr-defined]
    assert [payload["ref_a"], payload["ref_b"]] == sorted([ctrw.claim_x, ctrw.item])
    assert {payload["work_a"], payload["work_b"]} == {ctrw.work_x, ctrw.lin.source}
    assert "Lorem ipsum" in payload["quote_a"] + payload["quote_b"]
    assert event.actor.kind == "agent" and event.input_blob  # type: ignore[attr-defined]


def test_idempotent_unordered_pair(project: Project, agent: Actor, ctrw: CtrWorld) -> None:
    one = propose_contradiction(
        project, agent, ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note="n")
    )
    two = propose_contradiction(
        project, agent, ContradictionInput(ref_a=ctrw.item, ref_b=ctrw.claim_x, note="other note")
    )
    assert two == (one[0], False)
    assert len(_events(project, "contradiction.proposed")) == 1


def test_refusals_each_reason(project: Project, agent: Actor, ctrw: CtrWorld) -> None:
    def refused(a: str, b: str, field: str, reason: str, note: str = "n") -> None:
        before = len(_events(project, "contradiction.proposed"))
        with pytest.raises(FactoryValidationError) as e:
            propose_contradiction(project, agent, ContradictionInput(ref_a=a, ref_b=b, note=note))
        assert (e.value.issues[0].field, e.value.issues[0].reason) == (field, reason)
        assert len(_events(project, "contradiction.proposed")) == before

    refused(ctrw.claim_x, "clm_01JZ9Q3K5M7N8P0R2S4T6V8W9Z", "ref_b", "ref-unknown")
    refused(ctrw.claim_x, ctrw.claim_x, "ref_b", "same-ref")
    refused(ctrw.item, ctrw.item_other, "ref_b", "same-work")
    # superseding claim_y leaves the old claim not live
    extract_record(
        project,
        _extractor_of(project),
        ctrw.task_y,
        [],
        [claim_input()],
        finish=True,
        claim_supersedes={0: ctrw.claim_y},
    )
    refused(ctrw.claim_y, ctrw.item, "ref_a", "ref-not-live")
    with pytest.raises(ValidationError):
        ContradictionInput(ref_a="bogus", ref_b=ctrw.item, note="n")
    with pytest.raises(ValidationError):
        ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note="x" * 501)
    with pytest.raises(ValidationError):
        ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note=" ")


def _extractor_of(project: Project) -> Actor:
    from tests.extraction_helpers import SESSION_A, _extractor

    return _extractor(SESSION_A, "claude-opus-5-5")


def _propose(project: Project, agent: Actor, w: CtrWorld) -> str:
    cid, _ = propose_contradiction(
        project, agent, ContradictionInput(ref_a=w.claim_x, ref_b=w.item, note="n")
    )
    return cid


def test_agent_cannot_decide(project: Project, agent: Actor, ctrw: CtrWorld) -> None:
    cid = _propose(project, agent, ctrw)
    with pytest.raises(FactoryValidationError) as e:
        decide_contradiction(project, agent, cid, "confirm", "looks right")
    assert (e.value.issues[0].field, e.value.issues[0].reason) == ("actor", "human-only")
    assert _events(project, "contradiction.decided") == []


def test_proposer_session_cannot_decide(
    project: Project, agent: Actor, human: Actor, ctrw: CtrWorld
) -> None:
    cid = _propose(project, agent, ctrw)  # the agent and `human` share a session
    with pytest.raises(FactoryValidationError) as e:
        decide_contradiction(project, human, cid, "confirm", "same session")
    assert e.value.issues[0].reason == "proposer-session"


def test_decision_refusals(
    project: Project, agent: Actor, other_session_human: Actor, ctrw: CtrWorld
) -> None:
    cid = _propose(project, agent, ctrw)
    for bad_id, bad_rationale, field in (
        ("ctr_01JZ9Q3K5M7N8P0R2S4T6V8W9Z", "r", "contradiction_id"),
        (cid, "  ", "rationale"),
    ):
        with pytest.raises(FactoryValidationError) as e:
            decide_contradiction(project, other_session_human, bad_id, "confirm", bad_rationale)
        assert e.value.issues[0].field == field
    assert _events(project, "contradiction.decided") == []


def test_projector_ignores_agent_decisions(project: Project, agent: Actor, ctrw: CtrWorld) -> None:
    cid = _propose(project, agent, ctrw)
    forged = project.events.make(
        "contradiction.decided",
        ContradictionDecided(contradiction_id=cid, decision="confirm", rationale="forged"),
        agent,
        refs=[cid],
        input_blob=project.blobs.put_json({"forged": True}),
    )
    project.record([forged])
    assert list_contradictions(project, states=("confirmed",)) == []
    [view] = list_contradictions(project, states=("inferred",))
    assert view.state == "inferred"


def test_default_list_only_confirmed(
    project: Project, agent: Actor, other_session_human: Actor, ctrw: CtrWorld
) -> None:
    cid = _propose(project, agent, ctrw)
    assert list_contradictions(project) == []
    decide_contradiction(project, other_session_human, cid, "confirm", "both quotes say so")
    [view] = list_contradictions(project)
    assert (view.contradiction_id, view.state) == (cid, "confirmed")
    assert {view.ref_a, view.ref_b} == {ctrw.claim_x, ctrw.item}
    assert {view.work_a, view.work_b} == {ctrw.work_x, ctrw.lin.source}
    decide_contradiction(project, other_session_human, cid, "reject", "on second reading")
    assert list_contradictions(project) == []
    [rejected] = list_contradictions(project, states=("rejected",))
    assert rejected.state == "rejected"


def test_superseded_claim_stales_contradiction(
    project: Project, agent: Actor, other_session_human: Actor, ctrw: CtrWorld
) -> None:
    cid, _ = propose_contradiction(
        project, agent, ContradictionInput(ref_a=ctrw.claim_y, ref_b=ctrw.item, note="n")
    )
    decide_contradiction(project, other_session_human, cid, "confirm", "yes")
    assert [v.contradiction_id for v in list_contradictions(project)] == [cid]
    extract_record(
        project,
        _extractor_of(project),
        ctrw.task_y,
        [],
        [claim_input()],
        finish=True,
        claim_supersedes={0: ctrw.claim_y},
    )
    assert list_contradictions(project) == []
    [stale] = list_contradictions(project, states=("stale",))
    assert (stale.contradiction_id, stale.state) == (cid, "stale")


def test_evidence_report_unchanged_by_contradictions(
    project: Project, agent: Actor, other_session_human: Actor, ctrw: CtrWorld
) -> None:  # Review Focus 4
    before = evidence_report(project).model_dump_json()
    cid = _propose(project, agent, ctrw)
    decide_contradiction(project, other_session_human, cid, "confirm", "yes")
    assert evidence_report(project).model_dump_json() == before
