"""The view header and the log head (slice 7b, plan V-A, task 1)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import JsonValue

from factory.clock import FixedClock
from factory.events.blobs import BlobStore
from factory.events.envelope import Actor
from factory.events.factory import EventFactory
from factory.events.writer import EventWriter
from factory.model.identity import IdGenerator
from factory.model.views import ViewMeta, ViewNotice
from factory.services.context import Project
from factory.services.views import to_json, view_meta
from tests.helpers import SESSION, Demo
from tests.screening_helpers import demo_catalog, make_index


def _log(tmp_path: Path, clock: FixedClock, n: int) -> tuple[Path, EventWriter, EventFactory]:
    root = tmp_path / "project"
    catalog = demo_catalog()
    writer = EventWriter(
        root / "events", project="demo", catalog=catalog, blobs=BlobStore(root / "blobs")
    )
    factory = EventFactory("demo", catalog, IdGenerator(clock))
    _append(writer, factory, range(n))
    return root, writer, factory


def _append(writer: EventWriter, factory: EventFactory, numbers: range) -> list[str]:
    actor = Actor(kind="human", id="obd", user="obd", session=SESSION)
    events = [factory.make("demo.recorded", Demo(n=i), actor) for i in numbers]
    if events:
        writer.append(events)
    return [e.id for e in events]


def test_head_is_last_event(tmp_path: Path, clock: FixedClock) -> None:
    root, writer, factory = _log(tmp_path, clock, 0)
    ids = _append(writer, factory, range(3))
    assert make_index(root).head() == ids[-1]


def test_head_none_for_empty_log(tmp_path: Path, clock: FixedClock) -> None:
    root, _, _ = _log(tmp_path, clock, 0)
    assert make_index(root).head() is None


def test_head_survives_rebuild(tmp_path: Path, clock: FixedClock) -> None:
    root, writer, factory = _log(tmp_path, clock, 0)
    ids = _append(writer, factory, range(2))
    index = make_index(root)
    before = index.head()
    index.rebuild()
    assert index.head() == before == ids[-1]


def test_head_follows_appended_events(tmp_path: Path, clock: FixedClock) -> None:
    root, writer, factory = _log(tmp_path, clock, 0)
    _append(writer, factory, range(2))
    index = make_index(root)
    first = index.head()
    ids = _append(writer, factory, range(2, 4))
    assert first is not None and index.head() == ids[-1] != first


def test_meta_states_filter_and_as_of(project: Project) -> None:
    meta = view_meta(project, "onion", 1, {"max_ring": 2})
    assert meta.as_of == project.index.head() and meta.as_of is not None
    assert meta.filter == {"max_ring": 2}
    assert (meta.view, meta.version, meta.project) == ("onion", 1, "demo")
    assert meta.truncated is False and meta.notices == []


def test_meta_carries_truncation_and_notices(project: Project) -> None:
    notice = ViewNotice(code="ring-clamped", text="clamped")
    meta = view_meta(project, "onion", 1, {}, truncated=True, notices=[notice])
    assert meta.truncated is True and meta.notices == [notice]


def test_to_json_deterministic() -> None:
    flt: dict[str, JsonValue] = {"b": 1, "a": [2, 1]}
    meta = ViewMeta(view="v", version=1, project="p", as_of=None, filter=flt)
    out = to_json(meta)
    assert out == to_json(meta)
    assert out.endswith("\n") and ": " not in out and ", " not in out
    assert out.index('"as_of"') < out.index('"filter"') < out.index('"project"')
    assert json.loads(out)["filter"] == {"a": [2, 1], "b": 1}
