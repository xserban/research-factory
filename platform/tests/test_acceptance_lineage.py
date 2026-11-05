"""Acceptance of slice 3b (lineage), criteria 1-17 and the no-literature-text scan.

Hand-written documents and G1 lookups, no network. The world is that of the G2-B/G2-C tests: the
full-text screened corpus with both schemas declared, a source work with a bibliography whose
entries 5 and 3 resolve exactly (entry 4 only fuzzily), and four agreed items. Criterion 18 is the
pilot (plan G2-E task 4, Later); criterion 19 is the quality gate.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.lineage.graph import GraphFilter
from factory.model.extraction import ExtractedRowInput, FieldInput, Scope
from factory.model.lineage import EdgeStatus, LineageDecision, RelationProposal, RelationProposed
from factory.model.project import RigorMode
from factory.model.references import ReferenceResolutionDecided
from factory.model.screening import Channel, PassLabel
from factory.services.check import Finding, _findings_as
from factory.services.context import Project
from factory.services.contributions import (
    contribution_agreement,
    contribution_audit_record,
    contribution_audit_report,
    contribution_audit_sample,
    contribution_next,
    contribution_record,
    contribution_status,
    live_items,
    resolve_contribution,
)
from factory.services.evidence_report import evidence_report
from factory.services.extraction import (
    ContributionBatch,
    live_claims,
    live_rows,
    stale_extractions,
)
from factory.services.extraction_agreement import final_rows, grouped_rows, independence_counts
from factory.services.ideas import (
    decide_idea,
    list_ideas,
    merge_ideas,
    propose_idea,
    unmerge_idea,
)
from factory.services.lineage import (
    graph_export,
    graph_query,
    graph_status,
    iter_edges,
    iter_nodes,
    no_stated_base,
)
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.references import extract_references
from factory.services.relations import (
    decide_relation,
    list_relations,
    propose_relation,
    relation_view,
)
from factory.services.trace import trace
from tests.contribution_helpers import (
    ENTRIES,
    P1,
    P2,
    P3,
    P4,
    P5,
    declare_both,
    field,
    item,
    not_stated,
    with_references,
)
from tests.document_helpers import StubConverter, make_registry, run_convert
from tests.extraction_helpers import _both, _r, ext_a, ext_b
from tests.lineage_helpers import (
    ITEMS,
    Lineage,
    build_lineage,
    ctr_a,
    ctr_b,
    disputed,
    lin,
    record_both,
    screened,
    world,
)
from tests.lineage_payloads import stated
from tests.test_contribution_agreement import _lorem
from tests.test_lineage_check import LINEAGE_CODES, _found, _park_everything

pytestmark = pytest.mark.slow

CH = Channel.CLI
ALL = GraphFilter(include_inferred=True, include_stale=True)


def _rel(
    project: Project,
    agent: Actor,
    lin: Lineage,
    target: str,
    basis: str | None,
    *,
    edge: str = "builds-on",
    note: str | None = None,
    source: str | None = None,
) -> str:
    p = RelationProposal(
        source_work=source or lin.source,
        target=target,
        edge_type=edge,  # type: ignore[arg-type]
        basis_item=basis,
        note=note,
    )
    return propose_relation(project, agent, p).relation_id


def _kinds(node: Any) -> set[str]:
    return {node.kind}.union(*(_kinds(c) for c in node.children))


def _reconvert(project: Project) -> None:
    run_convert(project, make_registry(StubConverter(version="9.9+acceptance")))


# 1
def test_schema_before_reading(
    project: Project, agent: Actor, ctr_a: Actor, screened: list[str]
) -> None:
    with pytest.raises(FactoryValidationError):
        contribution_next(project, ctr_a, PassLabel.A)
    before = project.index.state_hash()
    protocol = current_protocol(project)
    assert protocol is not None and protocol.spec.contribution_schema is None
    assert project.index.rebuild() == before  # a log without the section replays identically
    declare_both(project, agent)
    assert isinstance(contribution_next(project, ctr_a, PassLabel.A).batch, ContributionBatch)


# 2, 3, 4, 5
def test_quote_number_not_stated_and_cited_entry_rules(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    with_references(project, agent, world[0])
    batch = contribution_next(project, ctr_a, PassLabel.A).batch
    assert isinstance(batch, ContributionBatch)
    good = item("base-idea", P1, name="linear attention", cited_entry=field(5))
    bad_quote = item(
        "base-idea", ("s1.p1", "We build on quadratic attention [5]."), name="quadratic"
    )
    name_absent = item("base-idea", P1, name="softmax attention")
    wrong_number = item(
        "result",
        P3,
        statement="82.4% top-1",
        metric=field("top-1", *P3),
        value=field("82.5", *P3, unit="%"),
    )
    bad_not_stated = [
        ExtractedRowInput(
            fields={"item_kind": FieldInput(value="not-stated"), "absent_kind": FieldInput(value=k)}
        )
        for k in ("addition", "result")
    ]
    no_such_entry = item("base-idea", P5, name="Plain text", cited_entry=field(99))
    mismatch = item("base-idea", P2, name="softmax attention", cited_entry=field(4))
    res = contribution_record(
        project,
        ctr_a,
        batch.task_id,
        [good, bad_quote, name_absent, wrong_number, *bad_not_stated, no_such_entry, mismatch],
    )
    assert len(res.rows.written) == 2  # 2: partial acceptance; the rest are refused
    reasons = {i.reason for e in res.rows.rejected for i in e.issues}
    assert {"quote-not-in-anchor", "text-not-in-quote", "number-not-in-text"} <= reasons
    assert not any("quadratic" in r or "attention" in r for r in reasons)  # no document text
    assert {e.index for e in res.rows.rejected} == {1, 2, 3, 4, 5, 6}  # 3, 4, 5 refused
    markers = {(i.cited_entry, i.cited.marker) for i in live_items(project) if i.cited}
    assert markers == {
        (5, "matched"),
        (4, "mismatch"),
    }  # 5: a marker that maps elsewhere is flagged
    copied = contribution_record(  # 3: a value read next to a citation marker is flagged (R-44)
        project,
        ctr_a,
        batch.task_id,
        [
            item(
                "result",
                P2,
                statement="softmax attention [3]",
                metric=field("softmax", *P2),
                value=field("3", *P2),
            )
        ],
    )
    assert len(copied.rows.written) == 1, copied.rows.rejected
    row = next(
        r
        for r in live_rows(project, scope=Scope.CONTRIBUTION)
        if r.extraction_id == copied.rows.written[0]
    )
    assert row.fields["value"].copy_marker is True
    assert all(
        not r.fields["value"].copy_marker
        for r in [
            r
            for r in live_rows(project, scope=Scope.CONTRIBUTION)
            if "value" in r.fields and r.extraction_id != row.extraction_id
        ]
    )
    batch_b = contribution_next(project, ctr_b, PassLabel.B).batch  # a unit of its own
    assert isinstance(batch_b, ContributionBatch)
    ns = contribution_record(
        project,
        ctr_b,
        batch_b.task_id,
        [not_stated("base-idea"), not_stated("limitation")],
    )
    assert len(ns.rows.written) == 2
    derived = Counter(i.absent_kind for i in live_items(project) if i.item_kind == "not-stated")
    assert derived == {"base-idea": 1, "limitation": 1}  # the count is computed from the rows
    with pytest.raises(FactoryValidationError):  # no items and no reason
        contribution_record(project, ctr_b, batch_b.task_id, [], finish=True)


# 4
def test_closure_rules(project: Project, agent: Actor, ctr_a: Actor, world: list[str]) -> None:
    with_references(project, agent, world[0])
    batch = contribution_next(project, ctr_a, PassLabel.A).batch
    assert isinstance(batch, ContributionBatch)
    base = item("base-idea", P1, name="linear attention", cited_entry=field(5))
    addition = item("addition", P2, name="softmax attention")
    limitation = item(
        "limitation", P4, name="long sequences", statement="very long sequences degrade"
    )

    def refused(rows: list[ExtractedRowInput], reason: str | None) -> set[tuple[str, str]]:
        with pytest.raises(FactoryValidationError) as e:
            contribution_record(project, ctr_a, batch.task_id, rows, finish=True, reason=reason)
        return {(i.field, i.reason) for i in e.value.issues}

    assert ("finish", "no-addition") in refused([base, limitation], "no results")
    assert ("finish", "base-idea-not-covered") in refused([addition, limitation], "no results")
    assert ("finish", "limitation-not-covered") in refused([base, addition], "no results")
    assert ("reason", "no-result-needs-reason") in refused([base, addition, limitation], None)
    assert live_items(project) == []  # every refused close wrote nothing
    done = contribution_record(
        project,
        ctr_a,
        batch.task_id,
        [base, addition, limitation],
        finish=True,
        reason="no results",
    )
    assert done.completed


# 6 (independence)
def test_pass_independence(project: Project, ctr_a: Actor, world: list[str]) -> None:
    assert contribution_next(project, ctr_a, PassLabel.A).batch is not None
    same_model = ctr_a.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W1F"})
    with pytest.raises(FactoryValidationError) as e:
        contribution_next(project, same_model, PassLabel.B)
    assert e.value.issues[0].field == "model"
    same_session = ctr_a.model_copy(update={"model": "claude-sonnet-5-5"})
    with pytest.raises(FactoryValidationError):
        contribution_next(project, same_session, PassLabel.B)


# 6
def test_dual_extraction_agreement_resolution_audit(
    project: Project, human: Actor, disputed: Lineage
) -> None:
    keys = {
        label: {r.row_key for r in live_rows(project, label, scope=Scope.CONTRIBUTION)}
        for label in PassLabel
    }
    assert keys[PassLabel.A] & keys[PassLabel.B]  # rows align on row_key across the passes
    agreement = contribution_agreement(project, human)
    (d,) = agreement.disagreements
    resolve_contribution(project, human, d.work_id, d.row_key, d.field, "a", "checked", CH)
    assert contribution_agreement(project, human).disagreements == []
    sampled = contribution_audit_sample(project, human, random_seed=3)
    assert sampled.pack == "contribution" and sampled.items
    for s in sampled.items:
        contribution_audit_record(
            project, human, sampled.audit_id, s.work_id, s.row_key, s.field, True, "", CH
        )
    report = contribution_audit_report(project)
    assert report is not None and report.labelled == len(sampled.items)
    assert report.error_rate == 0 and not report.above_ceiling


# 7
def test_separation_from_evidence_table(
    project: Project,
    agent: Actor,
    human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    world: list[str],
) -> None:
    with_references(project, agent, world[0])  # the lineage reading's document, before any row

    def rows_for(work: str) -> list[ExtractedRowInput]:
        return [] if work == world[0] else [_r()]

    _both(project, ext_a, ext_b, rows_for, rows_for)  # final ml-benchmark rows

    def snapshot() -> tuple[str, ...]:
        return (
            json.dumps([r.model_dump(mode="json") for r in final_rows(project)], sort_keys=True),
            grouped_rows(project).model_dump_json(),
            independence_counts(final_rows(project)).model_dump_json(),
            json.dumps([c.model_dump(mode="json") for c in live_claims(project)], sort_keys=True),
            evidence_report(project).model_dump_json(),
        )

    before = snapshot()
    assert final_rows(project)  # there is something to compare
    record_both(project, ctr_a, ctr_b, world[0], ITEMS)  # recording and closing
    _park_everything(project, ctr_a, ctr_b)
    contribution_agreement(project, human)
    sampled = contribution_audit_sample(project, human, random_seed=5)
    for s in sampled.items:
        contribution_audit_record(
            project, human, sampled.audit_id, s.work_id, s.row_key, s.field, True, "", CH
        )
    assert live_items(project)  # contribution rows exist
    assert snapshot() == before


# 8, 9
def test_stated_rule_and_human_only_confirmation(
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage
) -> None:
    stated = _rel(project, agent, lin, lin.target5, lin.base)
    differs = _rel(project, agent, lin, lin.target3, lin.base)
    no_basis = _rel(
        project, agent, lin, lin.target5, None, edge="improves-on", note="from the abstract"
    )
    views = {r: relation_view(project, r) for r in (stated, differs, no_basis)}
    assert [(v.proposal_status, v.status_reason) for v in views.values() if v] == [
        ("stated", None),
        ("inferred", "target-differs"),
        ("inferred", "no-basis"),
    ]
    with pytest.raises(ValidationError):  # the agent cannot set the status
        RelationProposal.model_validate(
            {
                "source_work": lin.source,
                "target": lin.target5,
                "edge_type": "builds-on",
                "basis_item": lin.base,
                "status": "stated",
            }
        )
    with pytest.raises(FactoryValidationError):
        decide_relation(project, agent, differs, LineageDecision.CONFIRM, "I am sure")
    assert [r.relation_id for r in list_relations(project)] == [stated]  # inferred hidden
    decide_relation(project, other_session_human, differs, LineageDecision.CONFIRM, "checked")
    assert {r.relation_id for r in list_relations(project)} == {stated, differs}
    decide_relation(project, other_session_human, differs, LineageDecision.REJECT, "no, after all")
    assert [r.relation_id for r in list_relations(project)] == [stated]  # a rejection supersedes
    assert relation_view(project, differs).effective is EdgeStatus.REJECTED  # type: ignore[union-attr]


# 10
def test_edges_carry_basis(project: Project, agent: Actor, lin: Lineage) -> None:
    _rel(project, agent, lin, lin.target5, lin.base)
    _rel(project, agent, lin, lin.target3, lin.addition, edge="improves-on")
    edges = list(iter_edges(project, ALL))
    assert {e.edge_type.value for e in edges} >= {"cites", "builds-on", "improves-on"}
    assert all(e.basis for e in edges)
    cites = [e for e in edges if e.edge_type.value == "cites"]
    assert cites and all(e.status in (EdgeStatus.STATED, EdgeStatus.CONFIRMED) for e in cites)
    with pytest.raises(FactoryValidationError):  # nothing is stored for a basis that is not live
        _rel(project, agent, lin, lin.target5, "ext_01HZX3K4M5N6P7Q8R9S0TVWXYZ")


# 11
@pytest.mark.parametrize("cause", ["version", "g1", "amendment"])
def test_staleness(project: Project, agent: Actor, lin: Lineage, cause: str) -> None:
    rid = _rel(project, agent, lin, lin.target5, lin.base)
    assert relation_view(project, rid).effective is EdgeStatus.STATED  # type: ignore[union-attr]
    if cause == "version":
        with_references(project, agent, lin.source, version="v4", sources=lin.lookups.sources())
    elif cause == "g1":
        _reconvert(project)
        extract_references(project, agent, [lin.source], sources=lin.lookups.sources())
    else:
        current = current_protocol(project)
        assert current is not None and current.spec.contribution_schema is not None
        schema = current.spec.contribution_schema
        narrowed = schema.model_copy(
            update={"fields": tuple(f for f in schema.fields if f != "cited_entry")}
        )
        amend_protocol(
            project,
            agent,
            current.spec.model_copy(update={"contribution_schema": narrowed}),
            reason="narrow",
            semantic=True,
            effects={},
        )
    assert relation_view(project, rid).effective is EdgeStatus.STALE  # type: ignore[union-attr]
    assert list_relations(project) == []  # out of the default views
    assert rid in _found(project)["relation-stale"].refs  # and in check


def test_staleness_by_superseded_item(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, lin: Lineage
) -> None:
    rid = _rel(project, agent, lin, lin.target5, lin.uncited_base)
    _reconvert(project)
    extract_references(project, agent, [lin.source], sources=lin.lookups.sources())
    fixed = [
        item("base-idea", P5, name="Plain text", statement="Plain text with no marker"),
        item("limitation", P4, name="long sequences", statement="very long sequences degrade"),
        item("addition", P2, name="softmax attention"),
    ]
    record_both(
        project,
        ctr_a,
        ctr_b,
        lin.source,
        fixed,
        supersedes_a={0: lin.uncited_base, 1: lin.limitation},
        supersedes_b={0: lin.ids_b[2], 1: lin.ids_b[3]},
    )
    view = relation_view(project, rid)
    assert view is not None and view.effective is EdgeStatus.STALE
    assert rid in _found(project)["relation-stale"].refs


# 12
def test_ideas(
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage, world: list[str]
) -> None:
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as refusal:  # the name is not in a verified quote
        propose_idea(project, agent, "Performer", lin.source, lin.base, [lin.source])
    assert (refusal.value.issues[0].field, refusal.value.issues[0].reason) == (
        "name",
        "name-not-in-quote",
    )
    assert len(read_all(project.paths.events_dir, project.catalog)) == before  # nothing written
    other = next(w for w in world if w != lin.source)
    a = propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source, other])
    b = propose_idea(project, agent, "Linear attention", lin.source, lin.base, [lin.source])
    assert list_ideas(project) == []  # unconfirmed ideas are not drawn
    assert not [n for n in iter_nodes(project) if n.node_id.startswith("ida_")]
    assert a not in graph_export(project, "json")  # not drawn while unconfirmed
    decide_idea(project, other_session_human, a, LineageDecision.CONFIRM, "ok")
    decide_idea(project, other_session_human, b, LineageDecision.CONFIRM, "ok")
    assert a in graph_export(project, "json")
    before = graph_export(project, "json", flt=ALL)
    dot_before = graph_export(project, "dot", flt=ALL)
    merge_ideas(project, other_session_human, b, a, "naming variant")
    assert graph_export(project, "json", flt=ALL) != before
    unmerge_idea(project, other_session_human, b, "wrong merge")
    assert graph_export(project, "json", flt=ALL) == before  # the reversal restores it exactly
    assert graph_export(project, "dot", flt=ALL) == dot_before


# 13
def test_queries_on_a_constructed_graph(
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage, world: list[str]
) -> None:
    other = next(w for w in world if w != lin.source)
    _rel(project, agent, lin, lin.target5, lin.base)
    _rel(project, agent, lin, lin.target3, lin.addition, edge="improves-on")
    chain = _rel(project, agent, lin, lin.source, None, note="the abstract says so", source=other)

    def ids(result: Any) -> list[str]:
        return [str(n["id"]) for n in result.nodes]

    default = GraphFilter()
    wide = GraphFilter(include_inferred=True)
    assert ids(graph_query(project, "ancestors", node=lin.source)) == sorted(
        [lin.target3, lin.target5]
    )
    assert other not in ids(graph_query(project, "descendants", node=lin.target5, flt=default))
    assert set(ids(graph_query(project, "descendants", node=lin.target5, flt=wide))) == {
        lin.source,
        other,
    }
    assert ids(graph_query(project, "path", node=other, target=lin.target5, flt=wide)) == [
        other,
        lin.source,
        lin.target5,
    ]
    assert ids(graph_query(project, "path", node=other, target=lin.target5, flt=default)) == []
    decide_relation(project, other_session_human, chain, LineageDecision.CONFIRM, "checked")
    assert ids(graph_query(project, "path", node=other, target=lin.target5)) == [
        other,
        lin.source,
        lin.target5,
    ]
    assert ids(graph_query(project, "improvements_on", node=lin.target3)) == [lin.source]
    assert {lin.target3, lin.target5} <= set(ids(graph_query(project, "cited_by_at_least", k=1)))
    base = no_stated_base(project)
    listed = {w for c in (base.unextracted, base.not_stated, base.no_relation) for w in c}
    assert lin.source not in listed and base.unextracted  # it has a stated base; others unread
    clamped = graph_query(project, "ancestors", node=other, depth=10_000)
    assert clamped.depth_clamped and clamped.truncated is False
    assert graph_query(project, "ancestors", node=other).filter["include_inferred"] is False


# 14, 15
def test_exports_and_rebuild(project: Project, agent: Actor, lin: Lineage) -> None:
    _rel(project, agent, lin, lin.target5, lin.base)
    inferred = _rel(project, agent, lin, lin.target3, lin.base)
    exports = {fmt: graph_export(project, fmt, flt=ALL) for fmt in ("json", "dot")}  # type: ignore[arg-type]
    doc = json.loads(exports["json"])
    flat = json.dumps(doc)
    assert inferred in flat and lin.base in flat  # status and basis ids
    assert "inferred" in flat and "stated" in flat
    assert "dashed" in exports["dot"]  # an inferred edge is marked in DOT
    default_dot = graph_export(project, "dot")
    assert "dashed" not in default_dot  # and absent from the default view
    before = (
        exports,
        project.index.state_hash(),
        [list(e.__dict__.values()) for e in iter_edges(project, ALL)],
    )
    after_hash = project.index.rebuild()  # 15
    after = (
        {fmt: graph_export(project, fmt, flt=ALL) for fmt in ("json", "dot")},  # type: ignore[arg-type]
        after_hash,
        [list(e.__dict__.values()) for e in iter_edges(project, ALL)],
    )
    assert after == before


# 16
def test_trace_edge_to_question(project: Project, agent: Actor, lin: Lineage) -> None:
    rid = _rel(project, agent, lin, lin.target5, lin.base)
    assert {
        "relation",
        "extraction",
        "quote",
        "anchor",
        "conversion",
        "document",
        "attempt",
        "work",
        "decision",
        "protocol",
        "question",
    } <= _kinds(trace(project, rid))
    assert {"reference_extraction", "question"} <= _kinds(trace(project, f"cit:{lin.rex}:5"))


# 17
def test_check_findings(
    project: Project,
    agent: Actor,
    human: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    lin: Lineage,
    world: list[str],
) -> None:
    other = next(w for w in world if w != lin.source)
    stated = _rel(project, agent, lin, lin.target5, lin.base)
    _rel(project, agent, lin, other, lin.base)  # inferred and uncited
    propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    record_both(
        project, ctr_a, ctr_b, other, [not_stated("base-idea"), _lorem(), not_stated("limitation")]
    )  # items on a work with no G1 extraction
    served = contribution_next(project, ctr_a, PassLabel.A).batch
    assert isinstance(served, ContributionBatch)
    contribution_record(project, ctr_a, served.task_id, [], finish=True, reason="no text")
    project.record(
        [
            project.events.make(
                "reference.resolution_decided",
                ReferenceResolutionDecided.model_validate(
                    {
                        "extraction_id": lin.rex,
                        "ordinal": 5,
                        "decision": "reject",
                        "work_id": None,
                        "rationale": "wrong",
                        "quotes": [],
                        "confirmed_by": "human",
                    }
                ),
                human,
            )
        ]
    )
    found = {f.code: f for f in _findings_as(project, RigorMode.PILOT)}
    for code in (
        "contribution-missing-extraction",
        "contribution-closed-without-items",
        "graph-extraction-missing",
        "relation-stale",
        "relation-unconfirmed",
        "relation-uncited-base",
        "idea-unconfirmed",
    ):
        assert code in found, code
    assert stated in found["relation-stale"].refs
    text = " ".join(f.message for f in found.values())
    for needle in ("linear attention", "Softmax", "Lorem", "Plain text"):
        assert needle not in text


# 17 (the remaining codes)
def test_check_findings_remaining(
    project: Project,
    agent: Actor,
    human: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    lin: Lineage,
) -> None:
    _park_everything(project, ctr_a, ctr_b)
    contribution_agreement(project, human)
    sampled = contribution_audit_sample(project, human, random_seed=11)
    for s in sampled.items:
        contribution_audit_record(
            project, human, sampled.audit_id, s.work_id, s.row_key, s.field, False, "", CH
        )
    payload = RelationProposed.model_validate(
        stated(source_work=lin.source, target=lin.target5, resolved_target=lin.target5)
    )
    project.record(
        [
            project.events.make(
                "relation.proposed",
                payload,
                agent,
                refs=[payload.relation_id],
                input_blob=project.blobs.put_json({"by": "hand"}),
            )
        ]
    )
    found = _found(project)
    assert found["contribution-error-ceiling"].refs == [sampled.audit_id]
    assert found["relation-without-basis"].refs == [payload.relation_id]
    current = current_protocol(project)
    assert current is not None and current.spec.contribution_schema is not None
    schema = current.spec.contribution_schema
    narrowed = schema.model_copy(
        update={"fields": tuple(f for f in schema.fields if f != "cited_entry")}
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"contribution_schema": narrowed}),
        reason="narrow",
        semantic=True,
        effects={},
    )
    assert lin.source in _found(project)["contribution-stale"].refs


def test_schema_missing_after_g1(project: Project, agent: Actor, screened: list[str]) -> None:
    with_references(project, agent, screened[0])
    assert "contribution-schema-missing" in _found(project, RigorMode.SYSTEMATIC)
    assert "contribution-schema-missing" not in _found(project, RigorMode.EXPLORATORY)


# no literature text outside verified quotes (R-47, Review Focus 5)
def test_no_literature_text_outside_quotes(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    secret = "AGENT-NOTE-SENTINEL"
    _rel(project, agent, lin, lin.target3, None, note=secret)
    _rel(project, agent, lin, lin.target5, lin.base)
    propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    # A statement longer than its quote would carry paper text beyond the verified span.
    checked = 0
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type != "extraction.recorded":
            continue
        statement = event.payload["fields"].get("statement")
        if statement and statement.get("quote"):
            checked += 1
            assert len(str(statement["value"])) <= len(str(statement["quote"]))
    assert checked > 0
    raw_entries = [e for e in ENTRIES]
    exports = [graph_export(project, fmt, flt=ALL) for fmt in ("json", "dot")]  # type: ignore[arg-type]
    for out in exports:
        assert secret not in out
        assert not any(raw in out for raw in raw_entries)
    tracked = [project.paths.events_dir, project.paths.blobs_dir]  # the library is git-ignored
    scanned = 0
    for root in tracked:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            scanned += 1
            data = path.read_text(errors="ignore")
            assert not any(raw in data for raw in raw_entries), path  # no raw entry text
    assert scanned > 0
