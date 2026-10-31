from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.catalog import EventCatalog
from factory.events.envelope import Actor
from factory.events.factory import EventFactory
from factory.events.reader import EventLogCorruptError, event_files, read_all, read_file
from factory.events.writer import EventWriter
from tests.helpers import Demo


def test_append_writes_one_file_per_actor_and_session(
    writer: EventWriter,
    factory: EventFactory,
    human: Actor,
    other_session_human: Actor,
    events_dir: Path,
) -> None:
    a = factory.make("demo.recorded", Demo(n=1), human)
    b = factory.make("demo.recorded", Demo(n=2), other_session_human)
    writer.append([a, b])
    assert sorted(p.relative_to(events_dir).as_posix() for p in event_files(events_dir)) == sorted(
        [f"obd/{human.session}.jsonl", f"obd/{other_session_human.session}.jsonl"]
    )


def test_invalid_batch_writes_nothing(
    writer: EventWriter, factory: EventFactory, human: Actor, events_dir: Path
) -> None:
    good = factory.make("demo.recorded", Demo(n=1), human)
    writer.append([good])
    before = event_files(events_dir)[0].read_bytes()
    bad = good.model_copy(update={"project": "other"})
    with pytest.raises(FactoryValidationError) as err:
        writer.append([factory.make("demo.recorded", Demo(n=2), human), bad])
    assert err.value.issues[0].field == "events[1].project"
    assert event_files(events_dir)[0].read_bytes() == before


def test_append_of_nothing_is_a_no_op(writer: EventWriter, events_dir: Path) -> None:
    writer.append([])
    assert not events_dir.exists()


def test_read_all_merges_files_in_id_order(
    writer: EventWriter,
    factory: EventFactory,
    human: Actor,
    other_session_human: Actor,
    events_dir: Path,
    cat: EventCatalog,
) -> None:
    first = factory.make("demo.recorded", Demo(n=1), human)
    second = factory.make("demo.recorded", Demo(n=2), other_session_human)
    third = factory.make("demo.recorded", Demo(n=3), human)
    writer.append([third, first])
    writer.append([second])
    assert [e.id for e in read_all(events_dir, cat)] == [first.id, second.id, third.id]


def test_truncated_tail_is_not_consumed(
    writer: EventWriter, factory: EventFactory, human: Actor, events_dir: Path, cat: EventCatalog
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    path = event_files(events_dir)[0]
    full = path.stat().st_size
    with path.open("ab") as f:
        f.write(b'{"id": "ev_')
    res = read_file(path, cat)
    assert len(res.events) == 1 and res.end_offset == full and res.truncated_tail


def test_corrupt_complete_line_raises_with_location(
    writer: EventWriter, factory: EventFactory, human: Actor, events_dir: Path, cat: EventCatalog
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    path = event_files(events_dir)[0]
    offset = path.stat().st_size
    with path.open("ab") as f:
        f.write(b"not json\n")
    with pytest.raises(EventLogCorruptError) as err:
        read_file(path, cat)
    assert err.value.path == path and err.value.offset == offset


def test_unknown_event_type_is_corrupt(
    writer: EventWriter, factory: EventFactory, human: Actor, events_dir: Path, cat: EventCatalog
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    path = event_files(events_dir)[0]
    unknown = factory.make("demo.recorded", Demo(n=2), human).model_copy(
        update={"type": "demo.unknown"}
    )
    offset = path.stat().st_size
    with path.open("ab") as f:
        f.write(unknown.to_line())
    with pytest.raises(EventLogCorruptError) as err:
        read_file(path, cat)
    assert err.value.offset == offset


def test_read_from_offset_returns_only_new_events(
    writer: EventWriter, factory: EventFactory, human: Actor, events_dir: Path, cat: EventCatalog
) -> None:
    first_event = factory.make("demo.recorded", Demo(n=1), human)
    writer.append([first_event])
    path = event_files(events_dir)[0]
    first = read_file(path, cat)
    second_event = factory.make("demo.recorded", Demo(n=2), human)
    writer.append([second_event])
    res = read_file(path, cat, start=first.end_offset)
    assert [e.id for e in res.events] == [second_event.id]
    assert res.end_offset == path.stat().st_size and not res.truncated_tail
