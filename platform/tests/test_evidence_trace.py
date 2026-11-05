"""`trace` from evidence-report cells and claims (plan E, task 6).

Identifiers are those the report prints: `<row_key>/<field>` for a cell (a bare row key means the
`value` cell) and `clm_...` for a claim. Values are invented; no literature text.
"""

import re
from collections.abc import Callable, Mapping

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.evidence_report import EvidenceReport, EvidenceRow, evidence_report
from factory.services.extraction import live_rows
from factory.services.trace import _CELL_RE, TraceNode, agent_trace, dangling_refs, trace
from factory.sources.registry import SourceFactory
from tests.evidence_helpers import claim_input, run_pass
from tests.extraction_helpers import FIELDS, SESSION_A, SESSION_B, _declare, _extractor, _r
from tests.fulltext_helpers import _screened_full_text_world

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
ABSENT = "rk_" + "0" * 12


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def ext_b() -> Actor:
    return _extractor(SESSION_B, "claude-sonnet-5-5")


def _rows() -> list[ExtractedRowInput]:
    row = _r()
    row.fields["params"] = FieldInput(value="2", anchor="t1", cell="t1.r3.c3", quote="2")
    return [row]


@pytest.fixture
def world(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    mock_sources: SourcesFor,
) -> EvidenceReport:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent, fields=(*FIELDS, "params"))
    run_pass(project, ext_a, PassLabel.A, lambda _w: _rows(), lambda _w: [claim_input()])
    run_pass(project, ext_b, PassLabel.B, lambda _w: _rows())
    return evidence_report(project)


def _row(world: EvidenceReport) -> EvidenceRow:
    return world.groups[0].rows[0]


def _nodes(node: TraceNode) -> dict[str, str]:
    out = {node.id: node.kind}
    for child in node.children:
        out.update(_nodes(child))
    return out


def test_trace_from_report_cell_reaches_question(world: EvidenceReport, project: Project) -> None:
    row = _row(world)
    tree = trace(project, f"{row.row_key}/value")
    assert tree.kind == "cell"
    assert tree.label == f"value cell of {row.work_id}"
    assert set(_nodes(tree).values()) >= {
        "cell",
        "extraction",
        "anchor",
        "conversion",
        "document",
        "attempt",
        "work",
        "decision",
        "protocol",
        "question",
    }


def test_chain_passes_through_document_version_and_retrieval_attempt(
    world: EvidenceReport, project: Project
) -> None:
    row = _row(world)
    nodes = _nodes(trace(project, f"{row.row_key}/value"))
    assert nodes[row.document_id] == "document"
    assert nodes[row.conversion_id] == "conversion"
    assert "attempt" in nodes.values()


def test_bare_row_key_means_value_cell(world: EvidenceReport, project: Project) -> None:
    row = _row(world)
    bare = trace(project, row.row_key)
    full = trace(project, f"{row.row_key}/value")
    assert bare.kind == "cell" and bare.label == full.label and bare.event_id == full.event_id
    assert [c.id for c in bare.children] == [c.id for c in full.children]


def test_both_passes_listed_and_superseded_row_linked(
    world: EvidenceReport, project: Project
) -> None:
    row = _row(world)
    tree = trace(project, f"{row.row_key}/value")
    listed = {c.id for c in tree.children if c.kind == "extraction"}
    expected = {
        r.extraction_id
        for label in (PassLabel.A, PassLabel.B)
        for r in live_rows(project, label, work_id=row.work_id)
        if r.row_key == row.row_key
    }
    assert len(expected) == 2 and expected <= listed
    assert row.value.extraction_id in listed
    assert tree.event_id  # the earliest extraction's event


def test_cost_cell_traces_to_its_own_anchor(world: EvidenceReport, project: Project) -> None:
    row = _row(world)
    tree = trace(project, f"{row.row_key}/params")
    assert tree.label == f"params cell of {row.work_id}"
    assert _nodes(tree)[f"{row.conversion_id}/t1.r3.c3"] == "anchor"


def test_claim_traces_back_to_question(world: EvidenceReport, project: Project) -> None:
    claim_id = world.claims["finding"][0].claim_id
    assert "question" in _nodes(trace(project, claim_id)).values()


def test_unknown_cell_is_unknown_id_error(world: EvidenceReport, project: Project) -> None:
    row = _row(world)
    for ref in (ABSENT, f"{ABSENT}/value", f"{row.row_key}/nofield"):
        with pytest.raises(FactoryValidationError) as exc:
            trace(project, ref)
        assert exc.value.issues == [ValidationIssue("ref", "unknown id")]
    assert dangling_refs(project, [f"{ABSENT}/value", f"{row.row_key}/value"]) == [
        f"{ABSENT}/value"
    ]


def test_agent_trace_works_for_cells_and_hides_seed_nodes(
    world: EvidenceReport, project: Project
) -> None:
    row = _row(world)
    tree = agent_trace(project, f"{row.row_key}/value")
    assert tree.kind == "cell" and "seed" not in _nodes(tree).values()


def test_every_report_trace_id_resolves(world: EvidenceReport, project: Project) -> None:
    ids: set[str] = set()
    for g in world.groups:
        for r in g.rows:
            ids.add(r.value.trace_id)
            ids.update(p.trace_id for p in r.costs.values())
    ids.update(c.trace_id for entries in world.claims.values() for c in entries)
    assert ids
    assert dangling_refs(project, sorted(ids)) == []
    for ref in sorted(ids):
        trace(project, ref)


@pytest.mark.parametrize(
    "ref",
    ["rk_0123456789ab", "rk_0123456789ab/value", "rk_0123456789ab/p2_flops", "rk_0123456789ab/a-b"],
)
def test_cell_pattern_matches_any_field_name(ref: str) -> None:
    assert re.fullmatch(_CELL_RE, ref)


@pytest.mark.parametrize("ref", ["rk_0123456789ab/*", "rk_0123456789ab/", "rk_xyz/value"])
def test_cell_pattern_rejects_the_whole_row_marker_and_bad_keys(ref: str) -> None:
    assert not re.fullmatch(_CELL_RE, ref)
