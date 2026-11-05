"""Projection of concept events and the merge-aware layer rows (slice 3c, plan G3-B, task 2)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from factory.events.envelope import Actor
from factory.index.default import PROJECTION_VERSION
from factory.index.index import OMITTED_WHEN_EMPTY
from factory.services.context import Project
from tests.intuition_helpers import (
    CPT1,
    CPT2,
    CUL1,
    CUL2,
    IDEA1,
    PAPER1,
    concept_reviewed,
    concept_source,
    defined,
    link_decided,
    link_proposed,
    merged,
    record_event,
    rows,
    source_decided,
)

TEXTBOOK = concept_source()
OTHER = concept_source(citation="A survey, section 2", kind="survey")
CONCEPT_TABLES = (
    "concepts",
    "concept_aliases",
    "concept_definitions",
    "concept_reviews",
    "concept_quotes",
    "concept_source_decisions",
    "concept_uses",
    "concept_merges",
)


def _state(project: Project, cid: str = CPT1) -> tuple[str, str]:
    [row] = rows(
        project, f"SELECT source_state, review_state FROM concepts WHERE concept_id = '{cid}'"
    )
    return str(row[0]), str(row[1])


def _node(project: Project, cid: str = CPT1) -> tuple[str, str, str]:
    [row] = rows(
        project,
        f"SELECT node_type, \"class\", review_state FROM layer_nodes WHERE node_id = '{cid}'",
    )
    return (str(row[0]), str(row[1]), str(row[2]))


def _dump(project: Project, tables: tuple[str, ...]) -> dict[str, list[tuple[object, ...]]]:
    return {t: rows(project, f"SELECT * FROM {t} ORDER BY 1, 2") for t in tables}


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "50"


def test_concept_tables_are_omitted_when_empty() -> None:
    assert set(CONCEPT_TABLES) <= OMITTED_WHEN_EMPTY


def test_definition_without_approval_is_unreviewed_and_hidden(
    project: Project, agent: Actor
) -> None:
    ev = record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    assert _state(project) == ("proposed", "unreviewed")
    assert _node(project) == ("concept", "interpretation", "unreviewed")
    [row] = rows(
        project,
        "SELECT name, name_folded, author, writer_model, definition_event, event_id, "
        "source_kind, source_digest, source_verifiable, input_blob FROM concepts",
    )
    assert row == (
        "random features", "random features", "agent", "claude-opus-5-5", ev.id, ev.id,
        "textbook", TEXTBOOK["digest"], 0, ev.input_blob,
    )  # fmt: skip
    assert rows(project, "SELECT item, reason, n FROM layer_hidden") == [
        ("concept", "unapproved", 1)
    ]


def test_concept_without_source_has_state_none(project: Project, agent: Actor) -> None:
    record_event(project, "concept.defined", defined(), agent)
    assert _state(project) == ("none", "unreviewed")


def test_aliases_and_quotes_follow_the_live_definition(project: Project, agent: Actor) -> None:
    first = record_event(
        project,
        "concept.defined",
        defined(aliases=("RFF", "Random Fourier Features"), source=TEXTBOOK),
        agent,
    )
    assert rows(project, "SELECT alias, alias_folded FROM concept_aliases ORDER BY 1") == [
        ("RFF", "rff"),
        ("Random Fourier Features", "random fourier features"),
    ]
    record_event(project, "concept.defined", defined(aliases=("RF",), supersedes=first.id), agent)
    assert rows(project, "SELECT alias FROM concept_aliases") == [("RF",)]
    assert rows(project, "SELECT COUNT(*) FROM concept_definitions") == [(2,)]


def test_redefinition_not_naming_the_live_definition_is_ignored(
    project: Project, agent: Actor
) -> None:
    record_event(project, "concept.defined", defined(name="a"), agent)
    record_event(project, "concept.defined", defined(name="b", supersedes=None), agent)
    record_event(project, "concept.defined", defined(CPT2, name="c", supersedes="evt_x"), agent)
    assert rows(project, "SELECT concept_id, name FROM concepts") == [(CPT1, "a")]


def test_approval_bound_to_digest(project: Project, agent: Actor) -> None:  # ruling B1
    first = record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(
        project, "concept.source_decided", source_decided(CPT1, "approve", TEXTBOOK["digest"])
    )
    assert _state(project)[0] == "approved"
    second = record_event(
        project, "concept.defined", defined(source=OTHER, supersedes=first.id), agent
    )
    assert _state(project)[0] == "proposed"
    record_event(project, "concept.defined", defined(source=TEXTBOOK, supersedes=second.id), agent)
    assert _state(project)[0] == "approved"


def test_latest_source_decision_wins(project: Project, agent: Actor) -> None:
    record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(
        project, "concept.source_decided", source_decided(CPT1, "approve", TEXTBOOK["digest"])
    )
    record_event(
        project,
        "concept.source_decided",
        source_decided(CPT1, "reject", TEXTBOOK["digest"], note="wrong book"),
    )
    assert _state(project)[0] == "rejected"
    assert rows(project, "SELECT COUNT(*) FROM concept_source_decisions") == [(2,)]


def test_non_human_and_writer_session_source_decisions_not_folded(
    project: Project, agent: Actor
) -> None:
    record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(
        project,
        "concept.source_decided",
        source_decided(CPT1, "approve", TEXTBOOK["digest"]),
        agent,
    )
    relay = project.human_actor().model_copy(update={"session": agent.session})
    record_event(
        project,
        "concept.source_decided",
        source_decided(CPT1, "approve", TEXTBOOK["digest"], channel="mcp"),
        relay,
    )
    assert _state(project)[0] == "proposed"
    assert rows(project, "SELECT COUNT(*) FROM concept_source_decisions") == [(0,)]


def test_review_binds_to_live_definition(project: Project, agent: Actor) -> None:  # ruling B2
    d1 = record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(
        project, "concept.source_decided", source_decided(CPT1, "approve", TEXTBOOK["digest"])
    )
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, d1.id))
    assert _state(project) == ("approved", "reviewed")
    d2 = record_event(project, "concept.defined", defined(source=TEXTBOOK, supersedes=d1.id), agent)
    assert _state(project) == ("approved", "unreviewed")
    # a review of the superseded definition is kept as history and changes nothing
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, d1.id, "wrong", note="old"))
    assert _state(project) == ("approved", "unreviewed")
    record_event(
        project, "concept.reviewed", concept_reviewed(CPT1, d2.id, "wrong", note="misstates")
    )
    assert _state(project) == ("approved", "wrong")
    assert _node(project)[2] == "wrong"
    assert rows(project, "SELECT COUNT(*) FROM concept_reviews") == [(3,)]
    assert rows(project, "SELECT item, reason, n FROM layer_hidden") == [("concept", "wrong", 1)]


def test_non_human_or_writer_session_review_not_folded(project: Project, agent: Actor) -> None:
    d1 = record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, d1.id), agent)
    relay = project.human_actor().model_copy(update={"session": agent.session})
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, d1.id, channel="mcp"), relay)
    assert _state(project)[1] == "unreviewed"
    # kept in the history, never counted (folded = 0)
    assert rows(project, "SELECT folded FROM concept_reviews ORDER BY event_id") == [(0,), (0,)]


def test_a_concept_review_writes_no_screening_table(project: Project, agent: Actor) -> None:
    d1 = record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, d1.id))
    assert rows(project, "SELECT COUNT(*) FROM label_sessions") == [(0,)]
    assert rows(project, "SELECT folded FROM concept_reviews") == [(1,)]
    assert _state(project)[1] == "reviewed"


def test_self_review_flag_is_projected(project: Project) -> None:
    d1 = record_event(project, "concept.defined", defined(author="human", source=TEXTBOOK))
    record_event(project, "concept.reviewed", concept_reviewed(CPT1, d1.id, self_reviewed=True))
    assert rows(project, "SELECT self_reviewed FROM concepts") == [(1,)]


def test_link_projection_and_decision_folds_latest(project: Project, agent: Actor) -> None:
    record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(project, "concept.link_proposed", link_proposed(), agent)
    assert rows(project, "SELECT status, proposed_status, status_reason FROM concept_uses") == [
        ("inferred", "inferred", "no-basis")
    ]
    assert rows(
        project, 'SELECT edge_id, edge_type, source, target, "class", review_state FROM layer_edges'
    ) == [(f"uses:{CUL1}", "uses", IDEA1, CPT1, "interpretation", "inferred")]
    record_event(project, "concept.link_decided", link_decided(CUL1, "confirm"))
    assert rows(project, "SELECT status, decided_by FROM concept_uses")[0][0] == "confirmed"
    assert rows(project, "SELECT review_state FROM layer_edges") == [("confirmed",)]
    record_event(project, "concept.link_decided", link_decided(CUL1, "reject", "no"))
    assert rows(project, "SELECT status, proposed_status FROM concept_uses") == [
        ("rejected", "inferred")
    ]
    assert rows(project, "SELECT review_state FROM layer_edges") == [("rejected",)]
    assert rows(project, "SELECT item, reason, n FROM layer_hidden ORDER BY 1, 2") == [
        ("concept", "unapproved", 1),
        ("concept_link", "rejected", 1),
    ]


def test_link_decision_by_non_human_or_proposer_session_not_folded(
    project: Project, agent: Actor
) -> None:
    record_event(project, "concept.defined", defined(source=TEXTBOOK), agent)
    record_event(project, "concept.link_proposed", link_proposed(), agent)
    relay = project.human_actor().model_copy(update={"session": agent.session})
    record_event(project, "concept.link_decided", link_decided(CUL1, "confirm"), relay)
    record_event(project, "concept.link_decided", link_decided(CUL1, "confirm"), agent)
    assert rows(project, "SELECT status FROM concept_uses") == [("inferred",)]


def test_stated_link_with_quote_basis_columns(project: Project, agent: Actor) -> None:
    from tests.intuition_helpers import quote_src

    record_event(project, "concept.defined", defined(), agent)
    record_event(
        project,
        "concept.link_proposed",
        link_proposed(
            from_node=PAPER1, from_kind="paper", status="stated", reason="name-in-quote",
            quote=quote_src(), note=None,
        ),
        agent,
    )  # fmt: skip
    assert rows(
        project, "SELECT basis_kind, basis_work, basis_anchor, basis_document FROM concept_uses"
    ) == [("quote", PAPER1, "s1.p2", "doc_01HZX3K4M5N6P7Q8R9S0T1V2WA")]


def _linked(project: Project, agent: Actor) -> None:
    """C1 and C2 defined; the idea uses C2; C2 uses C1 (concept to concept); C2 has alias RFF."""
    record_event(project, "concept.defined", defined(CPT1, name="kernel", source=TEXTBOOK), agent)
    record_event(
        project,
        "concept.defined",
        defined(CPT2, name="random features", aliases=("RFF",), source=OTHER),
        agent,
    )
    record_event(project, "concept.link_proposed", link_proposed(CUL1, concept=CPT2), agent)
    record_event(
        project,
        "concept.link_proposed",
        link_proposed(CUL2, from_node=CPT2, from_kind="concept", concept=CPT1),
        agent,
    )


def test_merge_repoints_edges_and_marks_node(project: Project, agent: Actor) -> None:
    _linked(project, agent)
    record_event(project, "concept.merged", merged(CPT1, CPT2))
    assert rows(project, "SELECT edge_id, source, target FROM layer_edges ORDER BY 1") == [
        (f"uses:{CUL1}", IDEA1, CPT1),
        (f"uses:{CUL2}", CPT1, CPT1),
    ]
    assert _node(project, CPT2)[2] == "merged" and _state(project, CPT2)[1] == "merged"
    assert rows(project, "SELECT merged_into FROM concepts ORDER BY concept_id") == [
        (None,),
        (CPT1,),
    ]
    # raw link rows are never re-pointed
    assert rows(project, "SELECT link_id, from_node, concept_id FROM concept_uses ORDER BY 1") == [
        (CUL1, IDEA1, CPT2),
        (CUL2, CPT2, CPT1),
    ]
    assert ("concept", "merged", 1) in rows(project, "SELECT item, reason, n FROM layer_hidden")


def test_merge_then_unmerge_restores_tables_exactly(project: Project, agent: Actor) -> None:
    _linked(project, agent)  # acceptance 11
    tables = ("concepts", "concept_aliases", "concept_uses", "layer_nodes", "layer_edges")
    before = _dump(project, tables)
    record_event(project, "concept.merged", merged(CPT1, CPT2))
    assert _dump(project, tables) != before
    record_event(project, "concept.unmerged", merged(CPT1, CPT2, "split again"))
    assert _dump(project, tables) == before
    record_event(project, "concept.merged", merged(CPT1, CPT2, "again"))
    assert _node(project, CPT2)[2] == "merged"


def test_merge_handler_is_total(project: Project, agent: Actor) -> None:
    _linked(project, agent)
    record_event(project, "concept.merged", merged(CPT1, CPT1))
    record_event(project, "concept.merged", merged(CPT1, "cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ"))
    record_event(project, "concept.unmerged", merged(CPT1, CPT2))
    assert rows(project, "SELECT COUNT(*) FROM concept_merges WHERE active = 1") == [(0,)]


def test_layer_hidden_counts_concepts_and_links(project: Project, agent: Actor) -> None:
    _linked(project, agent)  # both unapproved, two inferred links
    record_event(project, "concept.link_decided", link_decided(CUL2, "reject", "no"))
    assert rows(project, "SELECT item, reason, n FROM layer_hidden ORDER BY 1, 2") == [
        ("concept", "unapproved", 2),
        ("concept_link", "inferred", 1),
        ("concept_link", "rejected", 1),
    ]


def test_rebuild_state_hash_stable_with_concepts(project: Project, agent: Actor) -> None:
    _linked(project, agent)  # acceptance 12
    d = record_event(project, "concept.defined", defined("cpt_01HZX3K4M5N6P7Q8R9S0T1V2WC"), agent)
    record_event(
        project, "concept.source_decided", source_decided(CPT2, "approve", OTHER["digest"])
    )
    record_event(
        project,
        "concept.reviewed",
        concept_reviewed(
            CPT2,
            rows(project, f"SELECT definition_event FROM concepts WHERE concept_id = '{CPT2}'")[0][
                0
            ],
        ),
    )
    record_event(project, "concept.merged", merged(CPT1, CPT2))
    record_event(project, "concept.link_decided", link_decided(CUL1, "confirm"))
    assert d.id
    project.index.sync()
    before = project.index.state_hash()
    layer = _dump(project, (*CONCEPT_TABLES, "layer_nodes", "layer_edges"))
    assert project.index.rebuild() == before
    assert _dump(project, (*CONCEPT_TABLES, "layer_nodes", "layer_edges")) == layer


def test_concept_layer_class_enforced_for_edges(project: Project, agent: Actor) -> None:
    _linked(project, agent)
    with project.index.connect() as conn, pytest.raises(IntegrityError):
        from sqlalchemy import text

        conn.execute(text("UPDATE layer_edges SET \"class\" = 'evidence'"))


def test_g2_tables_unchanged_by_concepts(project: Project, agent: Actor) -> None:
    before = (
        rows(project, "SELECT * FROM graph_nodes ORDER BY 1"),
        rows(project, "SELECT * FROM graph_edges ORDER BY 1"),
    )
    _linked(project, agent)
    record_event(project, "concept.merged", merged(CPT1, CPT2))
    after = (
        rows(project, "SELECT * FROM graph_nodes ORDER BY 1"),
        rows(project, "SELECT * FROM graph_edges ORDER BY 1"),
    )
    assert after == before
