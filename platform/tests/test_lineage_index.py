"""Projection of relation and idea events (slice 3b, plan G2-C).

Events are recorded directly, as the other index tests do.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.index.default import PROJECTION_VERSION
from factory.index.index import OMITTED_WHEN_EMPTY
from factory.services.context import Project
from tests.lineage_payloads import (
    IDA,
    IDA2,
    IDA3,
    ITEM,
    REL,
    REL2,
    SRC,
    TGT,
    decided,
    idea,
    inferred,
    merge,
    stated,
)


def _record(project: Project, type_: str, payload: Any, actor: Actor | None = None) -> Event:
    model = project.catalog.get(type_).payload.model_validate(payload)
    actor = actor or project.human_actor()
    blob = project.blobs.put_json(payload) if actor.kind == "agent" else None
    event = project.events.make(type_, model, actor, input_blob=blob)
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def _decision(project: Project, relation_id: str = REL) -> Any:
    [(value,)] = _rows(
        project, f"SELECT decision FROM relations WHERE relation_id = '{relation_id}'"
    )
    return value


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "92"


def test_new_tables_are_omitted_when_empty() -> None:
    assert {"relations", "ideas", "idea_members", "idea_merges"} <= OMITTED_WHEN_EMPTY


def test_relation_projected(project: Project, agent: Actor) -> None:
    event = _record(project, "relation.proposed", stated(flags=["uncited-base"]), agent)
    assert _rows(
        project,
        "SELECT relation_id, source_work, target, edge_type, basis_item, status, status_reason,"
        " resolved_target, reference_extraction_id, cited_entry, flags, supersedes, superseded_by,"
        " decision, decision_event_id, event_id FROM relations",
    ) == [
        (
            REL,
            SRC,
            TGT,
            "builds-on",
            ITEM,
            "stated",
            None,
            TGT,
            stated()["reference_extraction_id"],
            5,
            '["uncited-base"]',
            None,
            None,
            None,
            None,
            event.id,
        )
    ]


def test_supersession_sets_superseded_by(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", inferred(), agent)
    _record(project, "relation.proposed", stated(relation_id=REL2, supersedes=REL), agent)
    assert _rows(
        project, "SELECT relation_id, superseded_by FROM relations ORDER BY relation_id"
    ) == [
        (REL, REL2),
        (REL2, None),
    ]


def test_first_write_wins_on_relation_id(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", inferred(), agent)
    _record(project, "relation.proposed", stated(), agent)
    assert _rows(project, "SELECT status FROM relations") == [("inferred",)]


def test_decision_latest_wins(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", inferred(), agent)
    _record(project, "relation.decided", decided(decision="confirm"))
    assert _decision(project) == "confirm"
    last = _record(project, "relation.decided", decided(decision="reject"))
    assert _decision(project) == "reject"
    assert _rows(project, "SELECT decision_event_id FROM relations") == [(last.id,)]


def test_projector_ignores_non_human_decisions(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", inferred(), agent)
    _record(project, "relation.decided", decided(), agent)
    assert _decision(project) is None
    _record(project, "idea.proposed", idea(), agent)
    _record(
        project, "idea.decided", {"idea_id": IDA, "decision": "confirm", "rationale": "x"}, agent
    )
    _record(project, "idea.merged", merge(), agent)
    assert _rows(project, "SELECT decision, merged_into FROM ideas") == [(None, None)]
    assert _rows(project, "SELECT COUNT(*) FROM idea_merges") == [(0,)]


def test_decision_for_unknown_relation_changes_nothing(project: Project) -> None:
    _record(project, "relation.decided", decided())
    assert _rows(project, "SELECT COUNT(*) FROM relations") == [(0,)]


def test_idea_projected_with_members(project: Project, agent: Actor) -> None:
    event = _record(project, "idea.proposed", idea(), agent)
    assert _rows(
        project,
        "SELECT idea_id, name, name_item, origin, supersedes, superseded_by, decision,"
        " merged_into, event_id FROM ideas",
    ) == [(IDA, "Linear attention", ITEM, TGT, None, None, None, None, event.id)]
    assert _rows(
        project, f"SELECT work_id FROM idea_members WHERE idea_id = '{IDA}' ORDER BY work_id"
    ) == [(TGT,), (SRC,)]
    assert _rows(project, "SELECT name FROM sqlite_master WHERE name = 'ix_idea_members_work'")


def test_idea_supersession_replaces_members(project: Project, agent: Actor) -> None:
    _record(project, "idea.proposed", idea(), agent)
    _record(project, "idea.proposed", idea(idea_id=IDA2, members=[TGT], supersedes=IDA), agent)
    assert _rows(project, "SELECT idea_id, superseded_by FROM ideas ORDER BY idea_id") == [
        (IDA, IDA2),
        (IDA2, None),
    ]


def test_merge_unmerge_fold(project: Project, agent: Actor) -> None:
    _record(project, "idea.proposed", idea(), agent)
    _record(project, "idea.proposed", idea(idea_id=IDA2), agent)
    _record(project, "idea.proposed", idea(idea_id=IDA3), agent)
    _record(project, "idea.merged", merge(IDA, IDA2))
    assert _rows(project, "SELECT idea_id, merged_into FROM ideas ORDER BY idea_id") == [
        (IDA, IDA2),
        (IDA2, None),
        (IDA3, None),
    ]
    _record(project, "idea.unmerged", merge(IDA, IDA2, "split again"))
    _record(project, "idea.merged", merge(IDA, IDA3))
    assert _rows(project, "SELECT merged_into FROM ideas WHERE idea_id = '" + IDA + "'") == [
        (IDA3,)
    ]
    assert _rows(
        project, "SELECT kind, from_idea, into_idea FROM idea_merges ORDER BY event_id"
    ) == [
        ("merged", IDA, IDA2),
        ("unmerged", IDA, IDA2),
        ("merged", IDA, IDA3),
    ]
    _record(project, "idea.unmerged", merge(IDA, IDA3, "again"))
    assert _rows(project, "SELECT merged_into FROM ideas WHERE idea_id = '" + IDA + "'") == [
        (None,)
    ]


def test_rebuild_state_hash_stable(project: Project, agent: Actor) -> None:
    _record(project, "relation.proposed", inferred(), agent)
    _record(project, "relation.decided", decided())
    _record(project, "idea.proposed", idea(), agent)
    _record(project, "idea.proposed", idea(idea_id=IDA2), agent)
    _record(project, "idea.merged", merge())
    project.index.sync()
    before = project.index.state_hash()
    assert project.index.rebuild() == before
