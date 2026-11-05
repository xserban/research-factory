"""Projection of vocabulary and card events (slice 6, plan H-A, task 1).

Events are recorded directly, as the other index tests do.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.index.default import PROJECTION_VERSION
from factory.index.index import OMITTED_WHEN_EMPTY
from factory.services.context import Project

ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W1C"
CARD = f"mcd_{ULID}"
CARD_P = f"pbd_{ULID}"
PA1 = f"pas_{ULID}"
PA2 = "pas_01JZ9Q3K5M7N8P0R2S4T6V8W1D"
CNV = "cnv_01JZ9Q3K5M7N8P0R2S4T6V8W1C"
WORK = "rf:smith-2020-a1b2c3d4"
SAMPLING = {
    "key": "pr:sampling",
    "kind": "enum",
    "allowed": ["regular", "irregular"],
    "match": "equal",
    "applies_to": "both",
}
TAGS = {
    "key": "pr:tags",
    "kind": "set",
    "allowed": ["a", "b", "c"],
    "match": "covers",
    "applies_to": "method",
}


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


def _asserted(aid: str, prop: str, value: Any, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "assertion_id": aid,
        "card_id": CARD,
        "property": prop,
        "value": value,
        "basis_kind": "inferred",
        "basis": {"note": "reasoned"},
        "status": "inferred",
        "vocabulary_version": "V@00000000",
    }
    base.update(over)
    return base


def _card(project: Project) -> None:
    _record(
        project,
        "card.created",
        {"card_id": CARD, "kind": "method", "subject": WORK, "owner": "obd"},
    )


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "53"


def test_new_tables_are_omitted_when_empty() -> None:
    assert {
        "properties",
        "property_merges",
        "cards",
        "card_assertions",
        "card_props",
    } <= OMITTED_WHEN_EMPTY


def test_proposal_then_human_decision(project: Project, agent: Actor) -> None:
    _record(project, "vocabulary.property_proposed", {"definition": SAMPLING}, agent)
    assert _rows(project, "SELECT key, state FROM properties") == [("pr:sampling", "proposed")]
    decision = {"key": "pr:sampling", "decision": "approve", "rationale": "ok"}
    _record(project, "vocabulary.property_decided", decision)
    assert _rows(project, "SELECT key, state FROM properties") == [("pr:sampling", "approved")]


def test_projector_ignores_agent_decisions(project: Project, agent: Actor) -> None:
    _record(project, "vocabulary.property_proposed", {"definition": SAMPLING}, agent)
    decision = {"key": "pr:sampling", "decision": "approve", "rationale": "ok"}
    _record(project, "vocabulary.property_decided", decision, agent)
    assert _rows(project, "SELECT state FROM properties") == [("proposed",)]
    _card(project)
    _record(project, "card.asserted", _asserted(PA1, "pr:sampling", "irregular"), agent)
    verdict = {"assertion_id": PA1, "decision": "confirm", "rationale": "ok"}
    _record(project, "card.assertion_decided", verdict, agent)
    assert _rows(project, "SELECT decision FROM card_assertions") == [(None,)]
    _record(project, "card.assertion_decided", verdict)
    assert _rows(project, "SELECT decision FROM card_assertions") == [("confirm",)]
    _record(
        project,
        "vocabulary.property_merged",
        {"from_key": "pr:sampling", "into": "pr:other-key", "reason": "r"},
        agent,
    )
    assert _rows(project, "SELECT count(*) FROM property_merges") == [(0,)]


def test_supersession_sets_superseded_by(project: Project, agent: Actor) -> None:
    _card(project)
    _record(project, "card.asserted", _asserted(PA1, "pr:sampling", "regular"), agent)
    _record(
        project, "card.asserted", _asserted(PA2, "pr:sampling", "irregular", supersedes=PA1), agent
    )
    assert _rows(
        project, "SELECT assertion_id, superseded_by FROM card_assertions ORDER BY assertion_id"
    ) == [(PA1, PA2), (PA2, None)]
    # the superseded assertion leaves card_props
    assert _rows(project, "SELECT assertion_id, value_norm FROM card_props") == [(PA2, "irregular")]


def test_first_write_wins_on_ids(project: Project, agent: Actor) -> None:
    _card(project)
    _record(project, "card.asserted", _asserted(PA1, "pr:sampling", "regular"), agent)
    _record(project, "card.asserted", _asserted(PA1, "pr:sampling", "irregular"), agent)
    assert _rows(project, "SELECT value_json FROM card_assertions") == [('"regular"',)]
    _card(project)
    assert _rows(project, "SELECT count(*) FROM cards") == [(1,)]


def test_set_values_expand_to_card_props(project: Project, agent: Actor) -> None:
    _card(project)
    _record(project, "card.asserted", _asserted(PA1, "pr:tags", ["a", "c"]), agent)
    _record(
        project,
        "card.asserted",
        _asserted(PA2, "pr:mem", "12", canonical="12", unit=None),
        agent,
    )
    assert _rows(
        project, "SELECT property_key, value_norm, number_canonical FROM card_props ORDER BY 1, 2"
    ) == [("pr:mem", "12", "12"), ("pr:tags", "a", None), ("pr:tags", "c", None)]
    verdict = {"assertion_id": PA1, "decision": "confirm", "rationale": "ok"}
    _record(project, "card.assertion_decided", verdict)
    assert _rows(
        project, f"SELECT DISTINCT status FROM card_props WHERE assertion_id = '{PA1}'"
    ) == [("confirmed",)]


def test_merge_unmerge_fold(project: Project) -> None:
    merged = {"from_key": "pr:old-key", "into": "pr:sampling", "reason": "same"}
    _record(project, "vocabulary.property_merged", merged)
    assert _rows(project, "SELECT kind, from_key, into_key FROM property_merges") == [
        ("merged", "pr:old-key", "pr:sampling")
    ]
    _record(project, "vocabulary.property_unmerged", merged)
    assert _rows(project, "SELECT kind FROM property_merges ORDER BY event_id") == [
        ("merged",),
        ("unmerged",),
    ]


def test_rebuild_state_hash_stable(project: Project, agent: Actor) -> None:
    _record(project, "vocabulary.property_proposed", {"definition": SAMPLING}, agent)
    _record(
        project,
        "vocabulary.property_decided",
        {"key": "pr:sampling", "decision": "approve", "rationale": "ok"},
    )
    _card(project)
    _record(project, "card.asserted", _asserted(PA1, "pr:tags", ["a", "b"]), agent)
    project.index.sync()
    before = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == before
