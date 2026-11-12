"""One-click add (slice 4c, H3): `send` then resolve exactly that inbox item.

The feed world is recorded directly as in `test_feed_actions`; the lookup runs through the
identifier-keyed fixture sources, so no network is involved."""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.work import ProvenanceMethod
from factory.services.context import Project
from factory.services.feed import add
from factory.services.inbox import list_items, resolve_links
from factory.services.search import get_work
from tests.helpers import SourcesFor, ready_protocol
from tests.inbox_helpers import Keyed, capture, link_item, raising_sources
from tests.test_feed_actions import (
    ENTRY,
    FETCH,
    HELD_WORK,
    OTHER,
    RANKING,
    UNSHOWN,
    _ranking,
    _record,
    _shown,
)

HELD = "2611.01236"


def _world(project: Project) -> Project:
    entries = [
        {"id": ENTRY, "version": "v1", "title": "A paper"},
        {"id": OTHER, "version": "v1", "title": "Another paper"},
        {"id": HELD, "version": "v1", "title": "Held paper", "held_work_id": HELD_WORK},
        {"id": UNSHOWN, "version": "v1", "title": "Never shown"},
    ]
    payload = {
        "fetch_id": FETCH,
        "categories": ["cs.AI"],
        "window_from": "2026-11-10",
        "window_to": "2026-11-11",
        "raw_blobs": [],
        "entries_blob": project.blobs.put_json(entries),  # type: ignore[arg-type]
        "count": 4,
        "held_count": 1,
        "complete": True,
    }
    _record(project, "feed.fetched", payload, project.system_actor())
    _ranking(project, RANKING, [_shown(ENTRY, 1, 0.9), _shown(OTHER, 2, 0.5)])
    return project


def _keyed(*, found: bool = True) -> Keyed:
    atom = [(f"{ENTRY}v1", "A paper", 2026, "Ana Roe")]
    return Keyed(arxiv={ENTRY: atom} if found else {})


def _events(project: Project) -> list[Event]:
    return list(read_all(project.paths.events_dir, project.catalog))


def _types(project: Project, type_: str) -> list[Event]:
    return [e for e in _events(project) if e.type == type_]


@pytest.fixture
def open_world(explore_project: Project) -> Project:
    return _world(explore_project)


def test_add_sends_and_resolves_the_item(open_world: Project, human: Actor) -> None:
    result = add(open_world, human, ENTRY, sources=_keyed().sources(), note="for review")

    assert result.outcome == "new" and result.reason is None
    assert result.work_id is not None
    [sent] = _types(open_world, "feed.sent")
    assert sent.payload["inbox_item_id"] == result.inbox_item_id
    [resolved] = _types(open_world, "inbox.link_resolved")
    assert resolved.payload["item_id"] == result.inbox_item_id
    work = get_work(open_world, result.work_id)
    assert work is not None
    assert [p.method for p in work.provenance] == [ProvenanceMethod.SUPPLIED]
    assert list_items(open_world).items[0].status == "resolved"


def test_add_resolves_only_its_own_item(open_world: Project, human: Actor) -> None:
    [earlier] = capture(open_world, human, "10.2000/s1")
    keyed = Keyed(
        openalex={"doi:10.2000/s1": [link_item(1)]},
        arxiv={ENTRY: [(f"{ENTRY}v1", "A paper", 2026, "Ana Roe")]},
    )

    result = add(open_world, human, ENTRY, sources=keyed.sources())

    assert result.inbox_item_id != earlier
    assert [e.payload["item_id"] for e in _types(open_world, "inbox.link_resolved")] == [
        result.inbox_item_id
    ]


def test_failed_lookup_keeps_the_send(open_world: Project, human: Actor) -> None:
    result = add(open_world, human, ENTRY, sources=_keyed(found=False).sources())

    assert result.outcome == "not-found" and result.work_id is None
    assert len(_types(open_world, "feed.sent")) == 1


def test_unavailable_source_reports_lookup_failed_and_keeps_the_send(
    open_world: Project, human: Actor
) -> None:
    result = add(open_world, human, ENTRY, sources=Keyed(fail=True).sources())

    assert result.outcome == "lookup-failed" and result.work_id is None
    assert len(_types(open_world, "feed.sent")) == 1
    [resolved] = _types(open_world, "inbox.link_resolved")
    assert resolved.payload["status"] == "failed"
    assert list_items(open_world).items[0].status == "open"


def test_gate_refusal_is_surfaced_and_the_send_stands(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    _world(project)

    result = add(project, human, ENTRY, sources=_keyed().sources())

    assert result.outcome == "refused"
    assert result.reason is not None and "query" in result.reason
    assert result.work_id is None and result.run_id is None
    assert len(_types(project, "feed.sent")) == 1
    assert _types(project, "inbox.link_resolved") == []


def test_agent_actor_is_refused_and_writes_nothing(open_world: Project, agent: Actor) -> None:
    before = len(_events(open_world))
    with pytest.raises(FactoryValidationError) as caught:
        add(open_world, agent, ENTRY, sources=raising_sources())
    assert (caught.value.issues[0].field, caught.value.issues[0].reason) == ("actor", "human-only")
    assert len(_events(open_world)) == before


def test_refused_send_writes_nothing_and_never_looks_up(open_world: Project, human: Actor) -> None:
    before = len(_events(open_world))
    with pytest.raises(FactoryValidationError):
        add(open_world, human, UNSHOWN, sources=raising_sources())
    assert len(_events(open_world)) == before


def test_resolve_links_without_item_ids_still_resolves_every_open_item(
    open_world: Project, human: Actor
) -> None:
    capture(open_world, human, "10.2000/s1")
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})
    [outcome] = resolve_links(open_world, human, sources=keyed.sources())
    assert outcome.status is not None
