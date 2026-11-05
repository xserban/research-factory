"""A small evidence, claim and lineage world for the writing tests (real events).

Built on the V-B world (`tests/views_b_helpers.py`: 12 screened works, both passes agreeing on six
rows in two groups, work 0's contribution items, one confirmed idea with works 0 and 1, a confirmed
`builds-on` edge from work 0 to work 1 and an inferred one back) with one change: pass A also
records one claim per work, so claim supports exist.

| work | group | method | row |
| --- | --- | --- | --- |
| 0 | classification / Low | lorem (v1) | own, value 2 |
| 1 | same | lorem (v2) | own, value 1 |
| 2 | same | lorem | copied, value 2 |
| 3 | same | item | own, value 2 |
| 4 | detection / High | lorem | own, value 1 |
| 5 | same | lorem | own, value 2 |
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from dataclasses import dataclass

import pytest

from factory.events.envelope import Actor
from factory.model.extraction import FieldInput
from factory.model.lineage import LineageDecision, RelationProposal
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.contributions import contribution_next, contribution_record
from factory.services.extraction import live_claims
from factory.services.extraction_agreement import final_rows
from factory.services.ideas import decide_idea, propose_idea
from factory.services.relations import decide_relation, propose_relation
from tests.contribution_helpers import ctr_a, ctr_b, ext_a, screened
from tests.evidence_helpers import claim_input, run_pass
from tests.extraction_helpers import _item
from tests.lineage_helpers import record_both
from tests.views_b_helpers import (
    declare_evidence,
    evidence_rows,
    ext_b,
    run_both,
)


@dataclass
class WWorld:
    works: list[str]
    idea: str
    base_item: str
    result_item: str
    confirmed_edge: str
    inferred_edge: str
    claims: dict[str, str]
    """work -> its pass-A claim id."""
    rows: dict[str, str]
    """work -> its row key (one row each, works 0 to 5)."""

    def cell(self, work: int, name: str = "value") -> str:
        return f"cell:{self.rows[self.works[work]]}/{name}"

    def claim(self, work: int) -> str:
        return f"claim:{self.claims[self.works[work]]}"


@pytest.fixture
def ww(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    screened: list[str],
) -> WWorld:
    declare_evidence(project, agent, contribution=True)
    rows_for = evidence_rows(screened)
    run_pass(project, ext_a, PassLabel.A, rows_for, lambda _w: [claim_input()])
    run_pass(project, ext_b, PassLabel.B, rows_for)
    first = screened[0]
    final = {r.work_id: r for r in final_rows(project)}
    result = _item(
        "result",
        None,
        metric=FieldInput(value="Low", anchor="t1.r2.c2", quote="Low"),
        value=FieldInput(value="1", anchor="t1", cell="t1.r3.c2", quote="1"),
        result_row=FieldInput(value=final[first].row_key),
    )
    items = [_item("base-idea"), _item("addition"), _item("limitation"), result]
    ids_a, _ = record_both(project, ctr_a, ctr_b, first, items)
    idea = propose_idea(project, agent, "Lorem", first, ids_a[0], [first, screened[1]])
    decide_idea(project, other_session_human, idea, LineageDecision.CONFIRM, "named")
    sure = propose_relation(
        project,
        agent,
        RelationProposal(
            source_work=first, target=screened[1], edge_type="builds-on", note="builds on it"
        ),
    )
    decide_relation(project, other_session_human, sure.relation_id, LineageDecision.CONFIRM, "ok")
    maybe = propose_relation(
        project,
        agent,
        RelationProposal(
            source_work=screened[1], target=first, edge_type="builds-on", note="maybe"
        ),
    )
    return WWorld(
        works=screened,
        idea=idea,
        base_item=ids_a[0],
        result_item=ids_a[3],
        confirmed_edge=sure.relation_id,
        inferred_edge=maybe.relation_id,
        claims={c.work_id: c.claim_id for c in live_claims(project, PassLabel.A)},
        rows={w: r.row_key for w, r in final.items()},
    )


def item_per_work(project: Project, ctr_a: Actor, ctr_b: Actor, works: list[str]) -> dict[str, str]:
    """Both contribution passes record one base-idea item for each of `works` and close every
    other unit. Returns work -> its pass-A item."""
    ids: dict[str, str] = {}
    for actor, label in ((ctr_a, PassLabel.A), (ctr_b, PassLabel.B)):
        while (served := contribution_next(project, actor, label).batch) is not None:
            work = str(served.records[0]["work_id"])
            rows = (
                [_item(k) for k in ("base-idea", "addition", "limitation")] if work in works else []
            )
            res = contribution_record(
                project, actor, served.task_id, rows, finish=True, reason="no results"
            )
            if rows and label is PassLabel.A:
                ids[work] = res.rows.written[0]
    return ids


def confirmed_idea(project: Project, agent: Actor, human: Actor, work: str, item: str) -> str:
    idea = propose_idea(project, agent, "Lorem", work, item, [work])
    decide_idea(project, human, idea, LineageDecision.CONFIRM, "named")
    return idea


def confirmed_edge(
    project: Project, agent: Actor, human: Actor, source: str, target: str, edge_type: str
) -> str:
    made = propose_relation(
        project,
        agent,
        RelationProposal(source_work=source, target=target, edge_type=edge_type, note="stated"),
    )
    decide_relation(project, human, made.relation_id, LineageDecision.CONFIRM, "ok")
    return made.relation_id
