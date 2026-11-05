"""The layer view and the `layer` filter (slice 3c, plan G3-C, task 1).

The default is unchanged byte for byte with a populated layer; `all` adds the layer as a separate,
labelled part; hidden items are absent and counted.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.lineage.graph import GraphFilter
from factory.model.intuition import ConceptInput, LinkStatus, UseBasisInput
from factory.model.screening import Channel
from factory.services.concepts import (
    decide_concept_link,
    decide_concept_source,
    define_concept,
    propose_concept_link,
    visible_concept_count,
)
from factory.services.context import Project
from factory.services.interpretations import (
    layer_counts,
    layer_graph,
    record_interpretation,
    review_interpretation,
)
from factory.services.layer_view import iter_layer_nodes
from factory.services.lineage import graph_export, graph_query, graph_status
from tests.helpers import open_session
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world
from tests.intuition_separation import populate_layer, twin_projects


def _ids(layer: Any) -> set[str]:
    return {n.node_id for n in layer.nodes} | {e.edge_id for e in layer.edges}


def _event_count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _outputs(project: Project, iw: IWorld) -> dict[str, str]:
    out: dict[str, str] = {}
    for flt in (GraphFilter(), GraphFilter(include_inferred=True, include_stale=True)):
        tag = json.dumps(flt.as_dict(), sort_keys=True)
        for node in (iw.source, iw.other, iw.idea1):
            for kind in ("ancestors", "descendants"):
                out[f"{kind}:{node}:{tag}"] = graph_query(
                    project, kind, node=node, flt=flt
                ).model_dump_json()
        out[f"export:{tag}"] = graph_export(project, "json", flt=flt) + graph_export(
            project, "dot", flt=flt
        )
    out["status"] = graph_status(project).model_dump_json()
    return out


def test_default_query_unchanged_with_layer_populated(
    tmp_path: Path, project: Project, iw: IWorld
) -> None:
    """Review Focus 1, acceptance 8: no `layer` argument, and `layer="evidence"`, give the same
    bytes with and without a layer."""
    plain, layered = twin_projects(tmp_path, project, iw)
    before = _outputs(plain, iw)
    assert _outputs(layered, iw) == before
    assert "layer" not in before["status"] and '"layer"' not in str(before)
    explicit = graph_query(layered, "descendants", node=iw.source, layer="evidence")
    assert (
        explicit.model_dump_json()
        == graph_query(layered, "descendants", node=iw.source).model_dump_json()
    )
    assert graph_status(layered, layer="evidence").model_dump_json() == before["status"]


def test_all_attaches_layer_separately_and_labelled(project: Project, iw: IWorld) -> None:
    """Acceptance 9."""
    populate_layer(project, iw)
    plain = graph_query(project, "descendants", node=iw.source, depth=3)
    r = graph_query(project, "descendants", node=iw.source, depth=3, layer="all")
    assert r.nodes == plain.nodes and r.edges == plain.edges
    assert r.layer is not None and r.layer.nodes
    assert all(
        n.class_ == "interpretation" and n.label.startswith("interpretation · ")
        for n in r.layer.nodes
    )
    assert all(e.class_ == "interpretation" for e in r.layer.edges)
    dumped = r.model_dump(mode="json")
    assert dumped["layer"]["nodes"][0]["class"] == "interpretation"
    assert all(n["id"].startswith(("rf:", "ida_")) for n in dumped["nodes"])  # evidence only


def test_hidden_items_absent_and_counted(project: Project, iw: IWorld) -> None:
    """Acceptance 5, Review Focus 2: a `uses` edge to a hidden concept is dropped and counted."""
    populate_layer(project, iw)
    bad = _concept(project, "feature map")
    link = propose_concept_link(project, iw.writer, iw.other, bad, UseBasisInput(), note="x")
    decide_concept_link(project, iw.human, link.link_id, "confirm", "checked", Channel.CLI)
    g = layer_graph(project)
    ids = _ids(g)
    assert bad not in ids and f"uses:{link.link_id}" not in ids
    shown = {n.node_id for n in g.nodes if n.node_type == "interpretation"}
    assert len(shown) == 2  # the human replacement and the relayed one; wrong and superseded hide
    assert (g.hidden.interpretations.wrong, g.hidden.interpretations.superseded) == (1, 1)
    assert (g.hidden.concepts.unapproved, g.hidden.concepts.wrong, g.hidden.concepts.merged) == (
        1,
        1,
        1,
    )
    assert g.hidden.endpoint_hidden == 1
    assert all(n.review_state in ("unreviewed", "reviewed") for n in g.nodes)


def _concept(project: Project, name: str) -> str:
    with project.index.connect() as conn:
        return str(
            conn.execute(
                text("SELECT concept_id FROM concepts WHERE name = :n"), {"n": name}
            ).scalar_one()
        )


def test_inferred_uses_only_with_flag(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    default = layer_graph(project)
    wide = layer_graph(project, include_inferred=True)
    inferred = {e.edge_id for e in wide.edges if e.review_state == "inferred"}
    assert inferred and not inferred & _ids(default)
    assert all(e.label == "interpretation · inferred" for e in wide.edges if e.edge_id in inferred)
    # the idea's inferred link shows; the concept-to-concept link from a merged concept hides
    assert wide.hidden.endpoint_hidden == default.hidden.endpoint_hidden + 1


def test_concept_closure_included_for_attached_nodes(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    good = _concept(project, "softmax attention")
    deep = define_concept(
        project,
        iw.writer,
        ConceptInput.model_validate(
            {"name": "inner product", "source": {"kind": "textbook", "citation": "Book, ch. 1"}}
        ),
    )
    decide_concept_source(project, iw.human, deep, "approve", "", Channel.CLI)
    propose_concept_link(project, iw.writer, good, deep, UseBasisInput(), note="builds on")
    only_source = layer_graph(project, attach_to=[iw.source], include_inferred=True)
    concepts = {n.node_id for n in only_source.nodes if n.node_type == "concept"}
    assert concepts == {good, deep}  # the closure follows good -> deep
    assert {e.source for e in only_source.edges if e.edge_type == "uses"} == {iw.source, good}
    # nothing attached to an unrelated node
    none = layer_graph(project, attach_to=[iw.third])
    assert none.nodes == [] and none.edges == []


def test_attachment_limits_interpretations_to_the_attached_nodes(
    project: Project, iw: IWorld
) -> None:
    populate_layer(project, iw)
    g = layer_graph(project, attach_to=[iw.other])
    assert [e.target for e in g.edges if e.edge_type == "explains"] == [iw.other]
    assert g.hidden.interpretations.wrong == 0  # the wrong one targets idea2


def test_graph_status_layer_counts_separate_no_total(project: Project, iw: IWorld) -> None:
    """Acceptance 8."""
    populate_layer(project, iw)
    plain = graph_status(project).model_dump(mode="json")
    s = graph_status(project, layer="all").model_dump(mode="json")
    assert {k: v for k, v in s.items() if k != "layer"} == plain
    assert "total" not in json.dumps(s)
    counts = layer_counts(project)
    assert s["layer"]["interpretations"] == {
        "unreviewed": 2,  # the relayed (mcp channel) review does not count
        "reviewed": 0,
        "wrong": 1,
        "superseded": 1,
    }
    assert s["layer"]["concepts"]["unapproved"] == 1 and s["layer"]["concepts"]["wrong"] == 1
    assert s["layer"]["explains"] == 2 and s["layer"]["uses"]["stated"] == 1
    assert counts.hidden.interpretations.wrong == 1


def test_invalid_layer_is_a_structured_error_and_writes_nothing(
    project: Project, iw: IWorld
) -> None:
    before = _event_count(project)
    for call in (
        lambda: graph_query(project, "descendants", node=iw.source, layer="x"),  # type: ignore[arg-type]
        lambda: graph_status(project, layer="x"),  # type: ignore[arg-type]
    ):
        with pytest.raises(FactoryValidationError) as err:
            call()
        assert [(i.field, i.reason) for i in err.value.issues] == [
            ("layer", "must be evidence or all")
        ]
    assert _event_count(project) == before


def test_wrong_concept_hidden_and_unreviewed_concept_labelled(project: Project, iw: IWorld) -> None:
    """G3-B ruling B2: an approved, unreviewed definition is shown, labelled `unreviewed`; a
    definition reviewed `wrong` is hidden."""
    populate_layer(project, iw)
    names = {n.name: n for n in layer_graph(project).nodes if n.node_type == "concept"}
    assert set(names) == {"softmax attention"}
    assert names["softmax attention"].label == "interpretation · reviewed"
    fresh = define_concept(
        project,
        iw.writer,
        ConceptInput.model_validate(
            {"name": "unreviewed idea", "source": {"kind": "textbook", "citation": "B, 2"}}
        ),
    )
    decide_concept_source(project, iw.human, fresh, "approve", "", Channel.CLI)
    node = next(n for n in layer_graph(project).nodes if n.node_id == fresh)
    assert node.label == "interpretation · unreviewed" and node.review_state == "unreviewed"


def test_visibility_predicate_matches_the_concepts_service(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    shown = [n for n in iter_layer_nodes(project) if n.node_type == "concept"]
    assert len(shown) == visible_concept_count(project)


def test_flags_mark_self_review_and_unverifiable_source(project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    flags = {n.node_id: n.flags for n in layer_graph(project).nodes}
    # a textbook source has no work id, so it cannot be verified
    assert any("unverifiable-source" in f for f in flags.values())
    # the lone human reviewing their own interpretation is flagged
    mine = record_interpretation(project, iw.human, iw.entry(iw.idea2))
    review_interpretation(project, iw.human, mine, "reviewed", "", Channel.CLI)
    flags = {n.node_id: n.flags for n in layer_graph(project).nodes}
    assert flags[mine] == ["self-reviewed"]


@pytest.mark.anyio
async def test_mcp_layer_parameter_validated(
    settings: Settings, project: Project, clock: FixedClock, iw: IWorld
) -> None:
    populate_layer(project, iw)
    async with open_session(settings, clock) as client:
        bad = await client.call("graph_status", project="demo", layer="x")
        good = await client.call("graph_status", project="demo", layer="all")
        query = await client.call(
            "graph_query", project="demo", query="descendants", node=iw.source, layer="all"
        )
        default = await client.call("graph_status", project="demo")
    assert bad["ok"] is False and bad["errors"][0]["field"] == "layer"
    assert good["ok"] is True and good["data"]["layer"]["interpretations"]["wrong"] == 1
    assert "layer" not in default["data"]
    assert query["ok"] is True and query["data"]["layer"]["nodes"][0]["class"] == "interpretation"
