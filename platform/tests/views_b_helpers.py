"""A small evidence and lineage world for the V-B view tests (real events).

`declared` is the screened full-text world (12 included works, all published 2020-01-01) with an
evidence schema that adds `params`, `higher_is_better` and `variant`. `acc` builds a row of the
fixture document: its table holds only the numbers 1 (cell `t1.r3.c2`) and 2 (`t1.r3.c3`), the
metric names `Low` and `High` and the method names `Lorem` and `Item`.

`vb_world` records, with both passes agreeing on every row (all rows `agreed`):

| work | group | method | row |
| --- | --- | --- | --- |
| 0 | classification / Low (higher is better) | lorem (variant v1) | own, value 2 |
| 1 | same | lorem (variant v2) | own, value 1 |
| 2 | same | lorem | copied, value 2 |
| 3 | same | item | own, value 2 |
| 4 | detection / High (no direction) | lorem | own, value 1 |
| 5 | same | lorem | own, value 2 |

Work 0 also has contribution items (base-idea, addition, limitation and a `result` linked to its
evidence row); a confirmed idea has works 0 and 1 as members; a confirmed `builds-on` edge goes
from work 0 to work 1 and an inferred one from work 1 to work 0.
"""

# ruff: noqa: F811

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput, ReportedIn
from factory.model.lineage import LineageDecision, RelationProposal
from factory.model.protocol import ExtractionSchema
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction_agreement import final_rows
from factory.services.ideas import decide_idea, propose_idea
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.relations import decide_relation, propose_relation
from tests.contribution_helpers import CONTRIB_FIELDS, ctr_a, ctr_b, ext_a, screened  # noqa: F401
from tests.evidence_helpers import run_pass
from tests.extraction_helpers import FIELDS, KEYS, SESSION_B, _declare, _extractor, _item, _r
from tests.lineage_helpers import record_both

VB_FIELDS = (*FIELDS, "params", "higher_is_better", "variant")
RowsFor = Callable[[str], list[ExtractedRowInput]]
_ANCHORS = {"1": "t1.r3.c2", "2": "t1.r3.c3"}


def acc(
    value: str = "1",
    *,
    task: str = "classification",
    params: str | None = None,
    reported_in: ReportedIn = ReportedIn.OWN,
    metric: str = "Low",
    up: bool | None = True,
    method: str = "Lorem",
    variant: str | None = None,
) -> ExtractedRowInput:
    extra: dict[str, FieldInput] = {
        "metric": FieldInput(
            value=metric, anchor="t1.r2.c2" if metric == "Low" else "t1.r2.c3", quote=metric
        ),
        "method_name": FieldInput(
            value=method,
            anchor="t1.r3.c1" if method == "Lorem" else "t1.r1.c1",
            quote=method,
        ),
    }
    if params is not None:
        extra["params"] = FieldInput(
            value=params, unit="M", anchor="t1", cell=_ANCHORS[params], quote=params
        )
    if up is not None:
        extra["higher_is_better"] = FieldInput(value=up)
    if variant is not None:
        extra["variant"] = FieldInput(value=variant)
    return _r(value, _ANCHORS[value], unit="%", task=task, reported_in=reported_in, **extra)


def run_both(project: Project, ext_a: Actor, ext_b: Actor, rows_for: RowsFor) -> None:
    run_pass(project, ext_a, PassLabel.A, rows_for)
    run_pass(project, ext_b, PassLabel.B, rows_for)


def set_year(project: Project, work_id: str, published: str | None) -> None:
    """Change a work's published date in the projection (the screened world dates all of them
    2020-01-01); `None` removes it. Event-sourced worlds cannot date a mock-source work."""
    with project.index.connect() as conn:
        if published is None:
            sql = (
                "UPDATE works SET data = json_remove(data, '$.dates.published') WHERE work_id = :w"
            )
            conn.execute(text(sql), {"w": work_id})
        else:
            sql = (
                "UPDATE works SET data = json_set(data, '$.dates.published', :d) WHERE work_id = :w"
            )
            conn.execute(text(sql), {"w": work_id, "d": published})
        conn.commit()


@pytest.fixture
def ext_b() -> Actor:
    return _extractor(SESSION_B, "claude-sonnet-5-5")


def declare_evidence(project: Project, agent: Actor, *, contribution: bool = False) -> None:
    current = current_protocol(project)
    assert current is not None
    update: dict[str, object] = {
        "extraction_schema": ExtractionSchema(
            pack="ml-benchmark",
            pack_version=1,
            fields=VB_FIELDS,
            comparability_keys=KEYS,
            dual_extract_sample=1.0,
        )
    }
    if contribution:
        update["contribution_schema"] = ExtractionSchema(
            pack="contribution",
            pack_version=1,
            fields=CONTRIB_FIELDS,
            dual_extract_sample=1.0,
            claims=False,
        )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update=update),
        reason="declare extraction",
        semantic=True,
        effects={},
    )


@pytest.fixture
def declared(project: Project, agent: Actor, screened: list[str]) -> list[str]:
    _declare(project, agent, fields=VB_FIELDS)
    return screened


@dataclass
class VbWorld:
    works: list[str]
    idea: str
    confirmed_edge: str
    inferred_edge: str


def evidence_rows(works: list[str]) -> RowsFor:
    def rows_for(work: str) -> list[ExtractedRowInput]:
        table: dict[int, ExtractedRowInput] = {
            0: acc("2", variant="v1"),
            1: acc("1", variant="v2"),
            2: acc("2", reported_in=ReportedIn.CITED),
            3: acc("2", method="Item"),
            4: acc("1", task="detection", metric="High", up=None),
            5: acc("2", task="detection", metric="High", up=None),
        }
        return [table[works.index(work)]] if works.index(work) in table else []

    return rows_for


@pytest.fixture
def vb_world(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    screened: list[str],
) -> VbWorld:
    declare_evidence(project, agent, contribution=True)
    run_both(project, ext_a, ext_b, evidence_rows(screened))
    first = screened[0]
    (row,) = [r for r in final_rows(project) if r.work_id == first]
    result = _item(
        "result",
        None,
        metric=FieldInput(value="Low", anchor="t1.r2.c2", quote="Low"),
        value=FieldInput(value="1", anchor="t1", cell="t1.r3.c2", quote="1"),
        result_row=FieldInput(value=row.row_key),
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
    return VbWorld(screened, idea, sure.relation_id, maybe.relation_id)
