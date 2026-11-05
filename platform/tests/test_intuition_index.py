"""Projection of interpretation events and the layer graph tables (slice 3c, plan G3-A, task 2)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from factory.events.envelope import Actor
from factory.index.default import PROJECTION_VERSION
from factory.index.index import OMITTED_WHEN_EMPTY
from factory.lineage.graph import GraphFilter
from factory.services.context import Project
from factory.services.lineage import graph_export, graph_query, graph_status
from tests.intuition_helpers import (
    DOC1,
    IDEA1,
    INT1,
    INT2,
    PAPER1,
    cite_src,
    quote_src,
    record_event,
    recorded,
    reviewed,
    rows,
)
from tests.lineage_graph_helpers import stand_in_basis, write_fixture

REX = "rex_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
ALL = GraphFilter(include_inferred=True, include_stale=True)


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "38"


def test_layer_tables_are_omitted_when_empty() -> None:
    assert {
        "interpretations",
        "interpretation_sources",
        "interpretation_reviews",
        "layer_nodes",
        "layer_edges",
    } <= OMITTED_WHEN_EMPTY


def test_record_projects_row_sources_and_graph_rows(project: Project, agent: Actor) -> None:
    sources = [quote_src(), cite_src(reference=f"{REX}:4")]
    event = record_event(project, "interpretation.recorded", recorded(sources=sources), agent)
    [row] = rows(
        project,
        "SELECT interpretation_id, target, target_kind, author, writer_model, review_state, "
        "self_reviewed, supersedes, superseded_by, input_blob, event_id FROM interpretations",
    )
    assert row == (
        INT1, IDEA1, "idea", "agent", "claude-opus-5-5", "unreviewed", 0, None, None,
        event.input_blob, event.id,
    )  # fmt: skip
    assert rows(
        project, "SELECT position, kind, role, document_id FROM interpretation_sources"
    ) == [(0, "quote", "supports", DOC1), (1, "citation", "background", None)]
    assert rows(project, 'SELECT node_id, node_type, "class", review_state FROM layer_nodes') == [
        (INT1, "interpretation", "interpretation", "unreviewed")
    ]
    assert rows(
        project,
        'SELECT edge_id, edge_type, source, target, "class", review_state, basis FROM layer_edges',
    ) == [(f"explains:{INT1}", "explains", INT1, IDEA1, "interpretation", "unreviewed", INT1)]


def test_review_fold_latest_wins_and_history_kept(project: Project, agent: Actor) -> None:
    record_event(project, "interpretation.recorded", recorded(), agent)
    record_event(project, "interpretation.reviewed", reviewed(state="reviewed"))
    record_event(project, "interpretation.reviewed", reviewed(state="wrong", note="misreads"))
    assert rows(project, "SELECT review_state, self_reviewed FROM interpretations") == [
        ("wrong", 0)
    ]
    assert [r[0] for r in rows(project, "SELECT state FROM interpretation_reviews ORDER BY 1")] == [
        "reviewed",
        "wrong",
    ]
    assert rows(project, "SELECT review_state FROM layer_nodes") == [("wrong",)]
    assert rows(project, "SELECT review_state FROM layer_edges") == [("wrong",)]


def test_supersession_marks_prior_and_both_remain(project: Project, agent: Actor) -> None:
    record_event(project, "interpretation.recorded", recorded(INT1), agent)
    record_event(project, "interpretation.recorded", recorded(INT2, supersedes=INT1), agent)
    assert rows(
        project,
        "SELECT interpretation_id, review_state, superseded_by FROM interpretations ORDER BY 1",
    ) == [(INT1, "superseded", INT2), (INT2, "unreviewed", None)]
    assert rows(project, "SELECT node_id, review_state FROM layer_nodes ORDER BY 1") == [
        (INT1, "superseded"),
        (INT2, "unreviewed"),
    ]


def test_review_of_superseded_row_kept_in_history_state_unchanged(
    project: Project, agent: Actor
) -> None:
    record_event(project, "interpretation.recorded", recorded(INT1), agent)
    record_event(project, "interpretation.recorded", recorded(INT2, supersedes=INT1), agent)
    record_event(project, "interpretation.reviewed", reviewed(INT1, "reviewed"))
    assert rows(
        project, f"SELECT review_state FROM interpretations WHERE interpretation_id = '{INT1}'"
    ) == [("superseded",)]
    assert rows(project, "SELECT COUNT(*) FROM interpretation_reviews") == [(1,)]


def test_non_human_review_is_stored_unfolded(project: Project, agent: Actor) -> None:
    record_event(project, "interpretation.recorded", recorded(), agent)
    other = agent.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W1A"})
    record_event(project, "interpretation.reviewed", reviewed(), other)
    assert rows(project, "SELECT review_state FROM interpretations") == [("unreviewed",)]
    assert rows(project, "SELECT folded FROM interpretation_reviews") == [(0,)]


def test_review_from_the_writing_session_is_stored_unfolded(project: Project, agent: Actor) -> None:
    """A human answer relayed by the session that wrote the interpretation (R-51)."""
    record_event(project, "interpretation.recorded", recorded(), agent)
    relay = project.human_actor().model_copy(update={"session": agent.session})
    record_event(project, "interpretation.reviewed", reviewed(channel="mcp"), relay)
    assert rows(project, "SELECT review_state FROM interpretations") == [("unreviewed",)]
    assert rows(project, "SELECT folded FROM interpretation_reviews") == [(0,)]


def test_folded_review_is_marked_and_writes_no_screening_row(
    project: Project, agent: Actor
) -> None:
    record_event(project, "interpretation.recorded", recorded(), agent)
    relay = project.human_actor().model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W1B"})
    record_event(project, "interpretation.reviewed", reviewed(channel="mcp"), relay)
    # a review over the MCP channel (a relay) is kept but never counts
    assert rows(project, "SELECT folded FROM interpretation_reviews") == [(0,)]
    assert rows(project, "SELECT review_state FROM interpretations") == [("unreviewed",)]
    assert rows(project, "SELECT session FROM label_sessions") == []


def test_unknown_interpretation_is_total(project: Project) -> None:
    record_event(project, "interpretation.reviewed", reviewed(INT2))
    assert rows(project, "SELECT COUNT(*) FROM interpretations") == [(0,)]
    assert rows(project, "SELECT folded FROM interpretation_reviews") == [(0,)]


def test_layer_hidden_view_counts(project: Project, agent: Actor) -> None:
    record_event(project, "interpretation.recorded", recorded(INT1), agent)
    record_event(project, "interpretation.recorded", recorded(INT2, supersedes=INT1), agent)
    third = INT1[:-1] + "C"
    record_event(project, "interpretation.recorded", recorded(third), agent)
    record_event(project, "interpretation.reviewed", reviewed(third, "wrong", note="x"))
    assert rows(project, "SELECT item, reason, n FROM layer_hidden ORDER BY reason") == [
        ("interpretation", "superseded", 1),
        ("interpretation", "wrong", 1),
    ]


def test_layer_class_is_enforced_by_the_table(project: Project, agent: Actor) -> None:
    record_event(project, "interpretation.recorded", recorded(), agent)
    with project.index.connect() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                'INSERT INTO layer_nodes (node_id, node_type, "class", review_state, event_id) '
                "VALUES ('x', 'interpretation', 'evidence', 'unreviewed', 'e')"
            )
        )


def test_rebuild_state_hash_stable(project: Project, agent: Actor) -> None:
    record_event(project, "interpretation.recorded", recorded(INT1), agent)
    record_event(project, "interpretation.recorded", recorded(INT2, supersedes=INT1), agent)
    record_event(project, "interpretation.reviewed", reviewed(INT2, "reviewed", self_reviewed=True))
    project.index.sync()
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert project.index.rebuild() == before


def _g2_outputs(project: Project) -> dict[str, Any]:
    out: dict[str, Any] = {"status": graph_status(project).model_dump(mode="json")}
    for flt in (GraphFilter(), ALL):
        for kind, kw in (
            ("ancestors", {"node": IDEA1}),
            ("descendants", {"node": PAPER1}),
            ("improvements_on", {"node": "rf:p3-00000003"}),
            ("cited_by_at_least", {"k": 1}),
            ("no_stated_base", {}),
        ):
            result = graph_query(project, kind, flt=flt, **kw)
            out[f"{kind}:{flt}"] = result.model_dump(mode="json")
        for fmt in ("json", "dot"):
            out[f"export:{fmt}:{flt}"] = graph_export(project, fmt, flt=flt)  # type: ignore[arg-type]
    return out


def test_g2_outputs_and_tables_unchanged_by_layer(
    project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 4: a populated layer changes no G2 output and no graph table."""
    stand_in_basis(monkeypatch)
    write_fixture(project, agent)
    base = _g2_outputs(project)
    graph_rows = rows(project, "SELECT * FROM graph_nodes ORDER BY 1")
    edge_rows = rows(project, "SELECT * FROM graph_edges ORDER BY 1")
    node_columns = rows(project, "SELECT name FROM pragma_table_info('graph_nodes')")
    edge_columns = rows(project, "SELECT name FROM pragma_table_info('graph_edges')")
    record_event(project, "interpretation.recorded", recorded(INT1, target=IDEA1), agent)
    record_event(
        project,
        "interpretation.recorded",
        recorded(INT2, target=PAPER1, target_kind="paper", supersedes=INT1),
        agent,
    )
    record_event(project, "interpretation.reviewed", reviewed(INT2, "reviewed"))
    assert rows(project, "SELECT COUNT(*) FROM layer_edges") == [(2,)]
    assert _g2_outputs(project) == base
    assert rows(project, "SELECT * FROM graph_nodes ORDER BY 1") == graph_rows
    assert rows(project, "SELECT * FROM graph_edges ORDER BY 1") == edge_rows
    assert rows(project, "SELECT name FROM pragma_table_info('graph_nodes')") == node_columns
    assert rows(project, "SELECT name FROM pragma_table_info('graph_edges')") == edge_columns
    assert json.loads(graph_export(project, "json"))  # still parses
    assert INT1 not in json.dumps(base)
