"""Projection of inbox events (slice 4a, Index tables).

Events are recorded directly, as the other index tests do.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import MetaData, text

from factory.canonical import canonical_json
from factory.events.envelope import Actor, Event
from factory.index.default import PROJECTION_VERSION, default_projection
from factory.index.index import NON_STATE_TABLES, Index
from factory.index.projection import Projection
from factory.services.context import Project
from tests.test_inbox_model import DOC, ITEM, WORK, added, resolved

ITEM2 = "inb_01HZX3K4M5N6P7Q8R9S0TVWXZ0"
INBOX_TABLES = frozenset({"inbox_items", "inbox_resolutions"})


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


def _status(project: Project, item_id: str = ITEM) -> str:
    [(status,)] = _rows(project, f"SELECT status FROM inbox_items WHERE item_id = '{item_id}'")
    return str(status)


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "45"


def test_added_item_is_open(project: Project) -> None:
    event = _record(project, "inbox.link_added", added())
    rows = _rows(
        project,
        "SELECT item_id, route, identifier_kind, identifier_value, identifier_version, link,"
        " actor_kind, session, channel, basis, note, added_event_id, status, withdrawn_event_id"
        " FROM inbox_items",
    )
    assert rows == [
        (
            ITEM,
            "link",
            "arxiv",
            "2103.14030",
            "v2",
            "https://arxiv.org/abs/2103.14030v2",
            "human",
            project.session,
            "cli",
            None,
            "from a colleague",
            event.id,
            "open",
            None,
        )
    ]


def test_agent_basis_is_projected_as_canonical_json(project: Project, agent: Actor) -> None:
    basis = {"kind": "document", "document_id": DOC, "anchor": "b3"}
    _record(project, "inbox.link_added", added(note=None, basis=basis, channel="mcp"), agent)
    [(kind, stored)] = _rows(project, "SELECT actor_kind, basis FROM inbox_items")
    assert kind == "agent"
    assert stored == canonical_json(basis).decode()


def test_failed_resolution_keeps_item_open(project: Project) -> None:
    _record(project, "inbox.link_added", added())
    event = _record(project, "inbox.link_resolved", resolved(status="failed", work_id=None))
    assert _status(project) == "open"
    rows = _rows(
        project,
        "SELECT event_id, item_id, query_id, run_id, status, work_id FROM inbox_resolutions",
    )
    assert rows == [(event.id, ITEM, resolved()["query_id"], resolved()["run_id"], "failed", None)]


def test_new_resolution_closes_item(project: Project) -> None:
    _record(project, "inbox.link_added", added())
    _record(project, "inbox.link_resolved", resolved(status="failed", work_id=None))
    _record(project, "inbox.link_resolved", resolved())
    assert _status(project) == "resolved"
    statuses = _rows(project, "SELECT status, work_id FROM inbox_resolutions ORDER BY event_id")
    assert statuses == [("failed", None), ("new", WORK)]


def test_not_found_closes_item(project: Project) -> None:
    _record(project, "inbox.link_added", added())
    _record(project, "inbox.link_resolved", resolved(status="not-found", work_id=None))
    assert _status(project) == "resolved"


def test_withdrawal(project: Project) -> None:
    _record(project, "inbox.link_added", added())
    event = _record(project, "inbox.link_withdrawn", {"item_id": ITEM, "reason": "wrong paper"})
    rows = _rows(project, "SELECT status, withdrawn_event_id FROM inbox_items")
    assert rows == [("withdrawn", event.id)]


def test_events_on_unknown_or_closed_items_are_ignored(project: Project) -> None:
    # Unknown item: nothing is projected.
    _record(project, "inbox.link_resolved", resolved(item_id=ITEM2))
    _record(project, "inbox.link_withdrawn", {"item_id": ITEM2, "reason": "x"})
    assert _rows(project, "SELECT * FROM inbox_items") == []
    assert _rows(project, "SELECT * FROM inbox_resolutions") == []
    # Withdrawn item: a later resolution changes nothing.
    _record(project, "inbox.link_added", added())
    _record(project, "inbox.link_withdrawn", {"item_id": ITEM, "reason": "x"})
    _record(project, "inbox.link_resolved", resolved())
    assert _status(project) == "withdrawn"
    assert _rows(project, "SELECT * FROM inbox_resolutions") == []
    # Resolved item: a withdrawal or a second resolution changes nothing.
    _record(project, "inbox.link_added", added(item_id=ITEM2))
    _record(project, "inbox.link_resolved", resolved(item_id=ITEM2))
    _record(project, "inbox.link_withdrawn", {"item_id": ITEM2, "reason": "x"})
    _record(project, "inbox.link_resolved", resolved(item_id=ITEM2, status="in-corpus"))
    assert _status(project, ITEM2) == "resolved"
    assert _rows(project, "SELECT status FROM inbox_resolutions") == [("new",)]
    # A second capture under an existing id is ignored too.
    _record(project, "inbox.link_added", added(item_id=ITEM2, link="2103.00001"))
    [(link,)] = _rows(project, f"SELECT link FROM inbox_items WHERE item_id = '{ITEM2}'")
    assert link == added()["link"]


def test_rebuild_is_deterministic(project: Project) -> None:
    _record(project, "inbox.link_added", added())
    _record(project, "inbox.link_added", added(item_id=ITEM2))
    _record(project, "inbox.link_resolved", resolved(status="failed", work_id=None))
    _record(project, "inbox.link_resolved", resolved())
    _record(project, "inbox.link_withdrawn", {"item_id": ITEM2, "reason": "x"})
    project.index.sync()
    before = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == before
    project.index.rebuild()
    assert project.index.state_hash() == before


def _digest(index: Index, skip: frozenset[str]) -> str:
    """`Index.state_hash` restricted to the tables not in `skip`."""
    digest = hashlib.sha256()
    with index.connect() as conn:
        names = [
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        ]
        for name in sorted(n for n in names if n not in NON_STATE_TABLES | skip):
            digest.update(f"{name}\n".encode())
            rows = conn.execute(text(f'SELECT * FROM "{name}"'))
            for line in sorted(canonical_json(dict(row._mapping)) for row in rows):
                digest.update(line + b"\n")
    return digest.hexdigest()


def _without_inbox() -> Projection:
    """The default projection with the inbox tables and handlers removed: the previous state."""
    full = default_projection()
    metadata = MetaData()
    for table in full.metadata.tables.values():
        if table.name not in INBOX_TABLES:
            table.to_metadata(metadata)
    handlers = {k: v for k, v in full.handlers.items() if not k.startswith("inbox.")}
    return Projection(version="previous", metadata=metadata, handlers=handlers)


def test_log_without_inbox_events_keeps_previous_state(project: Project) -> None:
    spec = {"kind": "positive", "cite": "Zhou 2021", "arxiv": "2103.14030"}
    _record(project, "seed.added", {"seed_id": "SEED01", "spec": spec})
    project.index.sync()
    previous = Index(
        project.paths.dir / "previous.sqlite",
        project.paths.events_dir,
        project.catalog,
        _without_inbox(),
    )
    previous.rebuild()
    assert _rows(project, "SELECT * FROM inbox_items") == []
    assert _digest(project.index, INBOX_TABLES) == _digest(previous, frozenset())
    # The comparison is not vacuous: the previous projection holds the seed.
    with previous.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM seeds")).scalar_one() == 1
