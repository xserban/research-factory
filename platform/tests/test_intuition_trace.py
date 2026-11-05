# ruff: noqa: F401, F811
"""`trace` from and to interpretations, concepts and links (slice 3c, plan G3-C, task 4)."""

from __future__ import annotations

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.intuition import ConceptInput, UseBasisInput
from factory.model.screening import Channel
from factory.services.concepts import (
    decide_concept_source,
    define_concept,
    merge_concepts,
    propose_concept_link,
    review_concept,
)
from factory.services.context import Project
from factory.services.interpretations import (
    intuition_next,
    record_interpretation,
    review_interpretation,
    supersede_interpretation,
)
from factory.services.trace import KINDS, TraceNode, agent_trace, trace
from tests.helpers import open_session
from tests.intuition_helpers import (
    SKILL,
    WRITER_MODEL,
    IWorld,
    ctr_a,
    ctr_b,
    iw,
    lin,
    rows,
    screened,
    world,
)
from tests.intuition_separation import populate_layer
from tests.lineage_helpers import with_references


def flat(node: TraceNode) -> list[TraceNode]:
    out = [node]
    for child in node.children:
        out.extend(flat(child))
    return out


def kinds(node: TraceNode) -> set[str]:
    return {n.kind for n in flat(node)}


def agent_interpretation(project: Project, iw: IWorld) -> str:
    batch = intuition_next(project, iw.writer, targets=[iw.idea1]).batch
    assert batch is not None
    return record_interpretation(project, iw.writer, iw.entry(iw.idea1), task_id=batch.task_id)


def concept(project: Project, iw: IWorld, name: str = "softmax attention", **source: object) -> str:
    spec = source or {"kind": "textbook", "citation": "Textbook, chapter 3"}
    cid = define_concept(
        project, iw.writer, ConceptInput.model_validate({"name": name, "source": spec})
    )
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    return cid


def test_the_layer_kinds_close_the_chain_order() -> None:
    assert KINDS[-3:] == ("interpretation", "concept", "concept_link")
    i = KINDS.index("claim")  # G2's order after claim is unchanged
    assert KINDS[i + 1 : i + 5] == ("relation", "idea", "cites", "quote")


def test_trace_interpretation_back_reaches_question(project: Project, iw: IWorld) -> None:
    """Acceptance 13: interpretation -> anchor -> conversion -> document -> attempt -> work ->
    full-text decision -> protocol -> question."""
    ident = agent_interpretation(project, iw)
    tree = trace(project, ident)
    assert tree.kind == "interpretation" and tree.id == ident
    assert {"anchor", "conversion", "document", "attempt", "work", "protocol", "question"} <= kinds(
        tree
    )
    assert f"{iw.cnv}/s1.p4" in {n.id for n in flat(tree) if n.kind == "anchor"}
    assert iw.idea1 in {n.id for n in flat(tree) if n.kind == "idea"}


def test_trace_interpretation_shows_history_and_provenance(project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    review_interpretation(project, iw.human, ident, "reviewed", "checked", Channel.CLI)
    tree = trace(project, ident)
    assert tree.label.startswith(f"interpretation {ident} · interpretation · reviewed")
    assert WRITER_MODEL in tree.label and SKILL.split("@")[0] in tree.label
    assert "input_blob" in tree.label and "Long sequences are the stated limit" in tree.label
    [(recorded_event,)] = rows(
        project, f"SELECT event_id FROM interpretations WHERE interpretation_id='{ident}'"
    )
    assert tree.event_id == recorded_event
    [(review_event,)] = rows(
        project, f"SELECT event_id FROM interpretation_reviews WHERE interpretation_id='{ident}'"
    )
    history = [n for n in flat(tree) if n.event_id == review_event]
    assert history and history[0].kind == "interpretation"
    assert "reviewed" in history[0].label and "checked" not in history[0].label  # note is not shown


def test_trace_follows_supersession(project: Project, iw: IWorld) -> None:
    first = agent_interpretation(project, iw)
    second = supersede_interpretation(
        project, iw.human, first, "A human replacement.", [iw.quote()]
    )
    assert first in {n.id for n in flat(trace(project, second))}
    forward = trace(project, first, direction="forward")
    assert second in {n.id for n in flat(forward)}
    assert "superseded" in forward.label


def test_trace_concept_shows_source_and_uses_links(project: Project, iw: IWorld) -> None:
    """Acceptance 13."""
    cid = concept(
        project, iw, "softmax attention", kind="corpus-paper", citation="Zhou", work_id=iw.other
    )
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)
    link = propose_concept_link(
        project,
        iw.writer,
        iw.source,
        cid,
        UseBasisInput(quote=iw.quote("s1.p2", "Unlike softmax attention")),
    )
    back = trace(project, cid)
    assert back.kind == "concept" and back.label.startswith(
        f"concept {cid} · interpretation · reviewed"
    )
    assert iw.other in {n.id for n in flat(back) if n.kind == "work"}  # the approved source
    forward = trace(project, cid, direction="forward")
    assert link.link_id in {n.id for n in flat(forward) if n.kind == "concept_link"}
    link_tree = trace(project, link.link_id)
    assert link_tree.kind == "concept_link" and "stated" in link_tree.label
    # the concept, the from-node (a work, reached once, under the anchor branch) and the basis
    assert {"concept", "work", "anchor"} <= kinds(link_tree)
    assert "concept" in {n.kind for n in link_tree.children}


def test_trace_merge_leads_to_the_surviving_concept(project: Project, iw: IWorld) -> None:
    keep = concept(project, iw, "alpha")
    gone = concept(project, iw, "beta")
    merge_concepts(project, iw.human, keep, gone, "same idea")
    assert keep in {n.id for n in flat(trace(project, gone))}
    assert "merged" in trace(project, gone).label


def test_trace_stale_source_labelled(project: Project, iw: IWorld, agent: Actor) -> None:
    """Review Focus 4: the label says so and the walk still reaches the document and question."""
    ident = agent_interpretation(project, iw)
    with_references(project, agent, iw.source, version="v4")
    tree = trace(project, ident)
    assert "source-stale" in tree.label
    assert {"document", "question"} <= kinds(tree)


def test_flags_in_labels(project: Project, iw: IWorld) -> None:
    mine = record_interpretation(project, iw.human, iw.entry(iw.idea2))
    review_interpretation(project, iw.human, mine, "reviewed", "", Channel.CLI)
    assert "self-reviewed" in trace(project, mine).label
    cid = concept(project, iw)
    assert "unverifiable-source" in trace(project, cid).label


def test_trace_forward_from_anchor_lists_layer_items_labelled(project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    anchor = f"{iw.cnv}/s1.p4"
    default = trace(project, anchor, direction="forward")
    assert ident not in {n.id for n in flat(default)}  # evidence traces never gain layer nodes
    withl = trace(project, anchor, direction="forward", layer="all")
    [hit] = [n for n in flat(withl) if n.id == ident]
    assert hit.label.startswith(f"interpretation {ident} · interpretation · unreviewed")
    for node in flat(withl):
        if node.kind in ("interpretation", "concept", "concept_link"):
            assert "interpretation · " in node.label


def test_trace_forward_from_work_and_idea_with_layer(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    other = trace(project, iw.other, direction="forward", layer="all")
    assert {n.kind for n in flat(other)} & {"interpretation"}
    idea = trace(project, iw.idea1, direction="forward", layer="all")
    assert "interpretation" in kinds(idea)
    assert kinds(trace(project, iw.other, direction="forward")).isdisjoint(
        {"interpretation", "concept", "concept_link"}
    )


def test_evidence_traces_are_unchanged_by_the_layer(project: Project, iw: IWorld) -> None:
    before = {
        (n, d): trace(project, n, direction=d)  # type: ignore[arg-type]
        for n in (iw.source, iw.other, iw.idea1)
        for d in ("back", "forward")
    }
    populate_layer(project, iw)
    for (n, d), tree in before.items():
        assert trace(project, n, direction=d) == tree  # type: ignore[arg-type]


def test_unknown_layer_ids_and_bad_layer_are_refused(project: Project, iw: IWorld) -> None:
    for ref in ("int_01HZX3K4M5N6P7Q8R9S0T1V2WA", "cpt_01HZX3K4M5N6P7Q8R9S0T1V2WA"):
        with pytest.raises(FactoryValidationError) as err:
            trace(project, ref)
        assert err.value.issues[0].reason == "unknown id"
    with pytest.raises(FactoryValidationError):
        trace(project, iw.source, layer="x")  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_mcp_trace_layer_parameter(
    settings: Settings, project: Project, clock: FixedClock, iw: IWorld
) -> None:
    ident = agent_interpretation(project, iw)
    anchor = f"{iw.cnv}/s1.p4"
    async with open_session(settings, clock) as client:
        plain = await client.call("trace", project="demo", ref=anchor, direction="forward")
        withl = await client.call(
            "trace", project="demo", ref=anchor, direction="forward", layer="all"
        )
        own = await client.call("trace", project="demo", ref=ident)
        bad = await client.call("trace", project="demo", ref=anchor, layer="x")
    assert plain["ok"] is True and ident not in str(plain["data"])
    assert withl["ok"] is True and ident in str(withl["data"])
    assert own["ok"] is True and own["data"]["kind"] == "interpretation"
    assert bad["ok"] is False and bad["errors"][0]["field"] == "layer"


def test_agent_trace_carries_the_layer_with_the_same_labels(project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    tree = agent_trace(project, ident)
    assert tree.label == trace(project, ident).label
    withl = agent_trace(project, f"{iw.cnv}/s1.p4", direction="forward", layer="all")
    assert ident in {n.id for n in flat(withl)}
