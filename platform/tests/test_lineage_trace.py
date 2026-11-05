# ruff: noqa: F401, F811
"""`trace` from relations, ideas, cites edges and items (slice 3b, plan G2-E, task 2)."""

from __future__ import annotations

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.model.lineage import RelationProposal
from factory.model.references import ReferenceResolutionDecided
from factory.services.context import Project
from factory.services.contributions import contribution_item
from factory.services.extraction import ExtractionRow
from factory.services.ideas import merge_ideas, propose_idea
from factory.services.references import extract_references
from factory.services.relations import propose_relation
from factory.services.trace import KINDS, TraceNode, agent_trace, trace
from tests.document_helpers import StubConverter, make_registry, run_convert
from tests.helpers import open_session
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world


def flat(node: TraceNode) -> list[TraceNode]:
    out = [node]
    for child in node.children:
        out += flat(child)
    return out


def kinds(node: TraceNode) -> set[str]:
    return {n.kind for n in flat(node)}


def _relation(project: Project, agent: Actor, lin: Lineage, target: str, basis: str | None) -> str:
    p = RelationProposal(
        source_work=lin.source, target=target, edge_type="builds-on", basis_item=basis
    )
    return propose_relation(project, agent, p).relation_id


def test_kinds_follow_claim() -> None:
    i = KINDS.index("claim")
    assert KINDS[i + 1 : i + 5] == ("relation", "idea", "cites", "quote")


def test_trace_edge_reaches_question(project: Project, agent: Actor, lin: Lineage) -> None:
    rid = _relation(project, agent, lin, lin.target5, lin.base)  # acceptance 16
    tree = trace(project, rid)
    assert tree.kind == "relation" and tree.id == rid
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
        "reference_extraction",
    } <= kinds(tree)
    ids = {n.id for n in flat(tree)}
    assert lin.rex in ids and lin.base in ids and lin.source in ids and lin.target5 in ids


def test_trace_quote_node_is_the_verified_quote(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    rid = _relation(project, agent, lin, lin.target5, lin.base)
    [quote] = [n for n in flat(trace(project, rid)) if n.kind == "quote"]
    view = contribution_item(project, lin.base)
    assert view is not None and view.quote
    assert quote.id == f"{lin.base}/quote" and quote.label == view.quote
    assert quote.event_id == view.event_id
    assert trace(project, quote.id).kind == "quote"


def test_trace_cites_edge_reaches_link_and_target(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    tree = trace(project, f"cit:{lin.rex}:5")
    assert tree.kind == "cites" and "stated" in tree.label
    assert {"reference_extraction", "work", "conversion", "document", "protocol"} <= kinds(tree)
    ids = {n.id for n in flat(tree)}
    assert lin.rex in ids and lin.target5 in ids and lin.source in ids
    with pytest.raises(FactoryValidationError):
        trace(project, f"cit:{lin.rex}:99")


def test_trace_superseded_cites_edge(  # Review Focus 3
    project: Project, agent: Actor, lin: Lineage
) -> None:
    run_convert(project, make_registry(StubConverter(version="9.9+trace")))
    extract_references(project, agent, [lin.source], sources=lin.lookups.sources())
    tree = trace(project, f"cit:{lin.rex}:5")
    old = next(n for n in flat(tree) if n.id == lin.rex)
    assert "superseded" in old.label
    assert {"conversion", "document", "work"} <= kinds(tree)


def test_trace_forward_from_item_lists_relations_and_ideas(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    rid = _relation(project, agent, lin, lin.target5, lin.base)
    idea = propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    tree = trace(project, lin.base, direction="forward")
    assert {(n.kind, n.id) for n in flat(tree)} >= {("relation", rid), ("idea", idea)}


def test_trace_idea_lists_name_item_origin_members_merges(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    lin: Lineage,
    world: list[str],
) -> None:
    other = next(w for w in world if w != lin.source)
    a = propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source, other])
    b = propose_idea(project, agent, "Linear attention", lin.source, lin.base, [lin.source])
    merge_ideas(project, other_session_human, b, a, "same method")
    tree = trace(project, a)
    ids = {(n.kind, n.id) for n in flat(tree)}
    assert ("extraction", lin.base) in ids and ("work", lin.source) in ids
    assert ("work", other) in ids and ("idea", b) in ids
    assert {"conversion", "protocol", "question"} <= kinds(tree)
    assert ("idea", a) in {(n.kind, n.id) for n in flat(trace(project, b, direction="forward"))}


def test_labels_carry_no_text_except_quote_nodes(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    rid = _relation(project, agent, lin, lin.target3, lin.base)
    propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    for root in (rid, f"cit:{lin.rex}:5", lin.base):
        for node in flat(trace(project, root)):
            if node.kind == "quote":
                continue
            assert "we build on" not in node.label.lower(), node
            assert "unlike softmax" not in node.label.lower(), node


def test_agent_trace_of_a_relation(project: Project, agent: Actor, lin: Lineage) -> None:
    rid = _relation(project, agent, lin, lin.target5, lin.base)
    assert agent_trace(project, rid).kind == "relation"


@pytest.mark.anyio
async def test_trace_refused_to_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    lin: Lineage,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rid = _relation(project, agent, lin, lin.target5, lin.base)

    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return ctr_a.session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)
    async with open_session(settings, clock) as client:
        out = await client.call("trace", project="demo", ref=rid)
    assert out["ok"] is False and out["errors"][0]["field"] == "session"


def test_rejected_cites_edge_reads_rejected_in_trace_and_graph(
    project: Project, agent: Actor, human: Actor, lin: Lineage
) -> None:
    from factory.lineage.graph import GraphFilter
    from factory.services.lineage import iter_edges

    edge = f"cit:{lin.rex}:5"
    assert "cites stated" in trace(project, edge).label
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
                        "rationale": "wrong paper",
                        "quotes": [],
                        "confirmed_by": "human",
                    }
                ),
                human,
            )
        ]
    )
    assert trace(project, edge).label.startswith("cites rejected")
    shown = {
        e.edge_id
        for e in iter_edges(project, GraphFilter(include_inferred=True, include_stale=True))
    }
    assert edge not in shown  # the graph hides a rejected link: both read it as rejected
