"""Acceptance of slice 3c, the intuition layer (spec criteria 1-14 and 16; 15 is the pilot).

One test per criterion, through the services the tools and commands call. Marked `slow`: run at
milestones with `-m slow`.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.intuition.export import LAYER_NOTICE
from factory.lineage.graph import GraphFilter
from factory.model.intuition import ConceptInput, InterpretationInput, ReviewState, UseBasisInput
from factory.model.screening import Channel
from factory.services import check as check_module
from factory.services.check import LAYER_CHECK_CODES
from factory.services.concepts import (
    concept_history,
    decide_concept_link,
    decide_concept_source,
    define_concept,
    list_concept_links,
    list_concepts,
    merge_concepts,
    propose_concept_link,
    review_concept,
    unmerge_concepts,
)
from factory.services.context import Project
from factory.services.interpretations import (
    intuition_next,
    layer_graph,
    list_interpretations,
    record_interpretation,
    review_interpretation,
    supersede_interpretation,
)
from factory.services.lineage import graph_export, graph_query, graph_status
from factory.services.trace import trace
from tests.intuition_helpers import (
    CUL1,
    CUL2,
    IWorld,
    concept_reviewed,
    ctr_a,
    ctr_b,
    evidenced,
    ext_a,
    ext_b,
    iw,
    iwe,
    lin,
    link_proposed,
    record_event,
    recorded,
    reviewed,
    reviewer,
    rows,
    screened,
    world,
    writer_actor,
)
from tests.intuition_separation import (
    ALLOWED_IMPORTERS,
    LAYER_MODULES,
    evidence_outputs,
    imports_of,
    layer_event_count,
    package_dirs,
    package_modules,
    populate_layer,
    twin_projects,
)
from tests.lineage_helpers import with_references

pytestmark = pytest.mark.slow

TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}


def count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def agent_interpretation(project: Project, iw: IWorld, target: str | None = None) -> str:
    batch = intuition_next(project, iw.writer, targets=[target or iw.idea1]).batch
    assert batch is not None
    return record_interpretation(
        project, iw.writer, iw.entry(target or iw.idea1), task_id=batch.task_id
    )


def concept(project: Project, iw: IWorld, name: str, *, approve: bool = True) -> str:
    cid = define_concept(
        project, iw.writer, ConceptInput.model_validate({"name": name, "source": TEXTBOOK})
    )
    if approve:
        decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    return cid


def test_provenance_on_agent_events(project: Project, iw: IWorld) -> None:
    """1: every agent-written layer event carries model, skill and an input blob that exists."""
    populate_layer(project, iw)
    agent_events = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type in ("interpretation.recorded", "concept.defined", "concept.link_proposed")
        and e.actor.kind == "agent"
    ]
    assert len(agent_events) >= 5
    for event in agent_events:
        assert event.actor.model and event.actor.skill
        assert event.actor.skill.startswith("rf-intuition@")
        assert event.input_blob is not None and project.blobs.exists(event.input_blob)


def test_validation_refusals_write_nothing(project: Project, iw: IWorld) -> None:
    """2: every refusal is a structured error and writes nothing."""
    batch = intuition_next(project, iw.writer, targets=[iw.idea1]).batch
    assert batch is not None
    good = concept(project, iw, "softmax attention")
    link = propose_concept_link(project, iw.writer, iw.source, good, UseBasisInput(), note="x")
    long_text = iw.entry(text="x" * 601)
    six = iw.entry(sources=[iw.quote() for _ in range(6)])
    misquote = iw.entry(sources=[iw.quote(quote="very long sequences improve")])
    refusals = [
        lambda: record_interpretation(project, iw.writer, long_text, task_id=batch.task_id),
        lambda: record_interpretation(project, iw.writer, six, task_id=batch.task_id),
        lambda: record_interpretation(project, iw.writer, misquote, task_id=batch.task_id),
        lambda: record_interpretation(project, iw.writer, iw.entry(), task_id="tsk_missing"),
        lambda: record_interpretation(project, iw.writer, iw.entry(iw.cnv), task_id=batch.task_id),
        lambda: review_interpretation(project, iw.human, "int_nope", "reviewed", "", Channel.CLI),
        lambda: define_concept(
            project,
            iw.writer,
            ConceptInput.model_validate({"name": "Softmax Attention", "source": TEXTBOOK}),
        ),
        lambda: propose_concept_link(
            project, iw.writer, iw.source, "cpt_nope", UseBasisInput(), note="x"
        ),
        lambda: decide_concept_link(project, iw.human, link.link_id, "confirm", "", Channel.CLI),
        lambda: review_concept(project, iw.human, good, "wrong", "", Channel.CLI),
    ]
    for refuse in refusals:
        before = count(project)
        with pytest.raises(FactoryValidationError) as err:
            refuse()
        assert err.value.issues and all(i.field and i.reason for i in err.value.issues)
        assert count(project) == before


def test_review_events_only_human_and_fold(project: Project, iw: IWorld) -> None:
    """3: an agent cannot review; a review event by a non-human is kept but never folded."""
    ident = agent_interpretation(project, iw)
    with pytest.raises(FactoryValidationError) as err:
        review_interpretation(project, iw.writer, ident, "reviewed", "", Channel.CLI)
    assert err.value.issues[0].field == "actor"
    other = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W7C", "second-agent")
    record_event(project, "interpretation.reviewed", reviewed(ident, "reviewed"), other)
    [(folded, state)] = rows(
        project,
        "SELECT r.folded, i.review_state FROM interpretation_reviews r "
        "JOIN interpretations i ON i.interpretation_id = r.interpretation_id",
    )
    assert (folded, state) == (0, "unreviewed")
    review_interpretation(project, iw.human, ident, "reviewed", "ok", Channel.CLI)
    assert rows(project, "SELECT review_state FROM interpretations") == [("reviewed",)]


def test_writer_cannot_review_and_self_review_flagged(project: Project, iw: IWorld) -> None:
    """4: the writing session is refused; a lone human's own review is flagged; with another
    human present it is refused."""
    ident = agent_interpretation(project, iw)
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    with pytest.raises(FactoryValidationError) as err:
        review_interpretation(project, relay, ident, "reviewed", "", Channel.CLI)
    assert err.value.issues[0].field == "actor"
    mine = record_interpretation(project, iw.human, iw.entry(iw.idea2))
    review_interpretation(project, iw.human, mine, "reviewed", "", Channel.CLI)
    assert rows(
        project, f"SELECT self_reviewed FROM interpretations WHERE interpretation_id='{mine}'"
    ) == [(1,)]
    second = reviewer(project, "ana")
    review_interpretation(project, second, mine, "reviewed", "", Channel.CLI)  # a second human acts
    again = record_interpretation(project, iw.human, iw.entry(iw.other))
    with pytest.raises(FactoryValidationError) as err2:
        review_interpretation(project, iw.human, again, "reviewed", "", Channel.CLI)
    assert err2.value.issues[0].field == "reviewer"


def test_default_visibility_and_hidden_counts(project: Project, iw: IWorld) -> None:
    """5: wrong and superseded interpretations are hidden by default and counted."""
    populate_layer(project, iw)
    shown = list_interpretations(project)
    assert {v.review_state for v in shown.items} <= {"unreviewed", "reviewed"}
    assert (shown.hidden.wrong, shown.hidden.superseded) == (1, 1)
    everything = list_interpretations(project, states=list(ReviewState))
    assert len(everything.items) == len(shown.items) + 2
    assert all(v.label == f"interpretation · {v.review_state}" for v in everything.items)
    assert layer_graph(project).hidden.interpretations == shown.hidden


def test_concept_hidden_until_source_approved_and_definition_reviewed_by_human(
    project: Project, iw: IWorld
) -> None:
    """6: a concept shows only with an approved source; an agent's review of it never counts."""
    cid = concept(project, iw, "kernel trick", approve=False)
    assert cid not in [c.concept_id for c in list_concepts(project).items]
    assert list_concepts(project).hidden.unapproved == 1
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    [view] = list_concepts(project).items
    assert view.concept_id == cid and view.review_state.value == "unreviewed"
    definition = concept_history(project, cid)[0].event_id
    agent = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W7D", "second-agent")
    record_event(
        project, "concept.reviewed", concept_reviewed(cid, definition, "wrong", note="x"), agent
    )
    assert [c.review_state.value for c in list_concepts(project).items] == ["unreviewed"]
    review_concept(project, iw.human, cid, "wrong", "misstated", Channel.CLI)
    assert list_concepts(project).items == []
    assert list_concepts(project).hidden.wrong == 1


def test_uses_rule_and_cycle_refusal(project: Project, iw: IWorld) -> None:
    """7: stated only when the quote names the concept; concept-to-concept links are inferred;
    a link that would close a cycle is refused."""
    soft = concept(project, iw, "softmax attention")
    feature = concept(project, iw, "feature map")
    named = propose_concept_link(
        project,
        iw.writer,
        iw.source,
        soft,
        UseBasisInput(quote=iw.quote("s1.p2", "Unlike softmax attention")),
    )
    unnamed = propose_concept_link(
        project, iw.writer, iw.source, feature, UseBasisInput(quote=iw.quote("s1.p2", "Unlike"))
    )
    assert (named.status, unnamed.status) == ("stated", "inferred")
    forward = propose_concept_link(project, iw.writer, soft, feature, UseBasisInput(), note="uses")
    assert forward.status == "inferred" and forward.status_reason == "concept-to-concept"
    before = count(project)
    with pytest.raises(FactoryValidationError):
        propose_concept_link(project, iw.writer, feature, soft, UseBasisInput(), note="loop")
    assert count(project) == before
    with pytest.raises(FactoryValidationError):
        merge_concepts(project, iw.human, soft, feature, "would close the loop")
    assert count(project) == before


def test_separation_architecture_and_differential(
    tmp_path: Path, project: Project, iwe: IWorld
) -> None:
    """8: no evidence module imports the layer, and every evidence output (including the layer-
    aware reads asked for the evidence layer) is byte-identical with the full layer."""
    modules = package_modules()
    offenders = sorted(
        (a, b)
        for a, b in imports_of(modules, packages=package_dirs())
        if b in LAYER_MODULES and a not in ALLOWED_IMPORTERS | LAYER_MODULES
    )
    assert offenders == []
    plain, layered = twin_projects(tmp_path, project, iwe)
    assert layer_event_count(plain) == 0 and layer_event_count(layered) > 0
    nodes = [iwe.source, iwe.other, iwe.idea1]
    expected = evidence_outputs(plain, nodes)
    assert expected["final_rows"] not in ("[]", "")
    assert evidence_outputs(layered, nodes) == expected
    assert graph_export(layered, "json") == graph_export(plain, "json")
    assert graph_status(layered).model_dump() == graph_status(plain).model_dump()


def test_labels_in_query_trace_and_export(project: Project, iw: IWorld) -> None:
    """9: every layer item in a query, a trace and an export carries its class and state."""
    populate_layer(project, iw)
    result = graph_query(project, "descendants", node=iw.source, layer="all")
    assert result.layer is not None
    assert all(
        i.label == f"interpretation · {i.review_state}"
        for i in [*result.layer.nodes, *result.layer.edges]
    )
    ident = list_interpretations(project).items[0].interpretation_id
    for node in _walk(trace(project, ident)):
        if node.kind in ("interpretation", "concept", "concept_link"):
            assert "interpretation · " in node.label
    for fmt in ("json", "dot"):
        exported = graph_export(project, fmt, layer="all")  # type: ignore[arg-type]
        assert LAYER_NOTICE in exported and "interpretation · " in exported
    assert LAYER_NOTICE not in graph_export(project, "json")


def _walk(node: Any) -> list[Any]:
    return [node, *(n for c in node.children for n in _walk(c))]


def test_stale_source_flag_keeps_state(project: Project, iw: IWorld, agent: Actor) -> None:
    """10: a new document version flags the interpretation stale and leaves its review state."""
    ident = agent_interpretation(project, iw)
    review_interpretation(project, iw.human, ident, "reviewed", "", Channel.CLI)
    with_references(project, agent, iw.source, version="v4")
    [view] = list_interpretations(project).items
    assert view.review_state == "reviewed" and view.source_stale
    assert "source-stale" in trace(project, ident).label
    assert any(n.flags == ["source-stale"] for n in layer_graph(project).nodes)


def test_merge_round_trip(project: Project, iw: IWorld) -> None:
    """11: merge then unmerge restores the layer view and the links' endpoints."""
    keep, gone = concept(project, iw, "alpha"), concept(project, iw, "beta")
    link = propose_concept_link(
        project, iw.writer, iw.idea1, gone, UseBasisInput(), note="uses beta"
    )
    decide_concept_link(project, iw.human, link.link_id, "confirm", "yes", Channel.CLI)
    before = layer_graph(project).model_dump_json()
    merge_concepts(project, iw.human, keep, gone, "same idea")
    merged = layer_graph(project)
    assert [e.target for e in merged.edges if e.edge_type == "uses"] == [keep]
    assert {n.node_id for n in merged.nodes if n.node_type == "concept"} == {keep}
    unmerge_concepts(project, iw.human, keep, gone, "they differ")
    assert layer_graph(project).model_dump_json() == before


def test_rebuild_identical_layer_tables_and_state_hash(project: Project, iw: IWorld) -> None:
    """12: a rebuild from the log gives the same layer tables and the same state hash."""
    populate_layer(project, iw)
    tables = (
        "interpretations",
        "interpretation_sources",
        "interpretation_reviews",
        "layer_nodes",
        "layer_edges",
        "concepts",
        "concept_aliases",
        "concept_uses",
        "concept_merges",
    )
    snapshot = {t: rows(project, f"SELECT * FROM {t} ORDER BY 1, 2") for t in tables}
    digest = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == digest
    assert {t: rows(project, f"SELECT * FROM {t} ORDER BY 1, 2") for t in tables} == snapshot


def test_trace_interpretation_and_concept(project: Project, iw: IWorld) -> None:
    """13: an interpretation traces back to the question; a concept to its source and links."""
    ident = agent_interpretation(project, iw)
    kinds = {n.kind for n in _walk(trace(project, ident))}
    assert {"anchor", "conversion", "document", "attempt", "work", "protocol", "question"} <= kinds
    cid = concept(project, iw, "softmax attention")
    link = propose_concept_link(
        project,
        iw.writer,
        iw.source,
        cid,
        UseBasisInput(quote=iw.quote("s1.p2", "Unlike softmax attention")),
    )
    assert link.link_id in {n.id for n in _walk(trace(project, cid, direction="forward"))}
    assert cid in {n.id for n in _walk(trace(project, link.link_id))}


def test_every_check_code_constructed(
    project: Project, iw: IWorld, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """14: each finding of the layer fires on a constructed project."""
    ident = agent_interpretation(project, iw)  # unreviewed; stale after the new version below
    soft = concept(project, iw, "softmax attention")  # unreviewed definition
    concept(project, iw, "no source yet", approve=False)  # source missing
    mine = record_interpretation(project, iw.human, iw.entry(iw.idea2))
    review_interpretation(project, iw.human, mine, "reviewed", "", Channel.CLI)  # self-reviewed
    propose_concept_link(project, iw.writer, iw.idea1, soft, UseBasisInput(), note="x")  # inferred
    record_event(project, "interpretation.reviewed", reviewed(ident), iw.writer)  # dropped
    a, b = concept(project, iw, "alpha"), concept(project, iw, "beta")
    for link_id, src, dst in ((CUL1, a, b), (CUL2, b, a)):  # a cycle, written around the service
        record_event(
            project,
            "concept.link_proposed",
            link_proposed(
                link_id,
                from_node=src,
                from_kind="concept",
                concept=dst,
                reason="concept-to-concept",
            ),
            iw.writer,
        )
    with_references(project, agent, iw.source, version="v4")
    monkeypatch.setattr(check_module, "grouped_rows", lambda _p: ["int_01HZX3K4M5N6P7Q8R9S0T1V2WA"])
    found = {hit.code for hit in check_module._layer(project)}
    assert found == LAYER_CHECK_CODES


def test_earlier_acceptance_suites_unchanged() -> None:
    """16 (in part): this slice edited no earlier acceptance file."""
    root = Path(__file__).resolve().parent
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available")
    base = "16155ca"
    probe = subprocess.run(
        [git, "cat-file", "-e", f"{base}^{{commit}}"], cwd=root, capture_output=True, check=False
    )
    if probe.returncode != 0:
        pytest.skip("the base commit is not in this clone")
    changed = subprocess.run(
        [git, "diff", "--name-only", base, "--", "tests/test_acceptance_*.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert [c for c in changed if not c.endswith("test_acceptance_intuition.py")] == []
