import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.clock import FixedClock
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog, EventType
from factory.events.envelope import Actor, Event
from factory.events.factory import EventFactory
from factory.events.writer import EventWriter
from factory.index.index import Index, SyncResult
from factory.index.projection import Projection, core_tables
from factory.model.identity import IdGenerator
from tests.helpers import S2, SESSION, T0, Demo


def demo_catalog() -> EventCatalog:
    catalog = EventCatalog()
    catalog.register(EventType("demo.recorded", Demo, 1))
    # Registered without a handler: its events must still get an `events` row.
    catalog.register(EventType("demo.noted", Demo, 1))
    return catalog


def demo_projection(version: str = "t1") -> Projection:
    metadata = MetaData()
    core_tables(metadata)
    totals = Table(
        "demo_totals",
        metadata,
        Column("key", String, primary_key=True),
        Column("total", Integer, nullable=False),
    )

    def record(conn: Connection, event: Event) -> None:
        n = event.payload["n"]
        assert isinstance(n, int)
        conn.execute(
            sqlite_insert(totals)
            .values(key="all", total=n)
            .on_conflict_do_update(index_elements=["key"], set_={"total": totals.c.total + n})
        )

    return Projection(version=version, metadata=metadata, handlers={"demo.recorded": record})


def make_index(project_dir: Path, version: str = "t1") -> Index:
    return Index(
        project_dir / ".index" / "factory.sqlite",
        project_dir / "events",
        demo_catalog(),
        demo_projection(version),
    )


def total(index: Index) -> int:
    with index.connect() as conn:
        value = conn.execute(
            text("SELECT COALESCE((SELECT total FROM demo_totals WHERE key = 'all'), 0)")
        ).scalar_one()
    return int(value)


@dataclass
class PopulatedProject:
    dir: Path
    index: Index


@pytest.fixture
def index(tmp_path: Path) -> Index:
    return make_index(tmp_path)


@pytest.fixture
def populated_project(tmp_path: Path, clock: FixedClock) -> PopulatedProject:
    project = tmp_path / "project"
    catalog = demo_catalog()
    writer = EventWriter(
        project / "events", project="demo", catalog=catalog, blobs=BlobStore(project / "blobs")
    )
    factory = EventFactory("demo", catalog, IdGenerator(clock))
    obd = Actor(kind="human", id="obd", user="obd", session=SESSION)
    other = Actor(kind="human", id="obd", user="obd", session=S2)
    writer.append(
        [
            factory.make("demo.recorded", Demo(n=1), obd),
            factory.make("demo.recorded", Demo(n=2), other),
            factory.make("demo.recorded", Demo(n=3), obd),
        ]
    )
    writer.append([factory.make("demo.recorded", Demo(n=4), other)])
    return PopulatedProject(dir=project, index=make_index(project))


def test_rebuild_is_deterministic_and_location_independent(
    tmp_path: Path, populated_project: PopulatedProject
) -> None:
    h1 = populated_project.index.rebuild()
    # Same events, same projection: rebuilding again yields the identical state hash.
    assert populated_project.index.rebuild() == h1
    # A copy of the project at another location hashes identically (no paths in state).
    copy = tmp_path / "copy"
    shutil.copytree(populated_project.dir, copy, ignore=shutil.ignore_patterns(".index"))
    assert make_index(copy).rebuild() == h1


def test_incremental_sync_equals_rebuild(
    writer: EventWriter, factory: EventFactory, human: Actor, index: Index
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    # First sync builds the DB and applies the one event.
    assert index.sync() == SyncResult(applied=1, rebuilt=True)
    writer.append([factory.make("demo.recorded", Demo(n=2), human)])
    # Ordinary append: applied incrementally, no rebuild.
    assert index.sync() == SyncResult(applied=1, rebuilt=False)
    incremental = index.state_hash()
    # The incrementally maintained state equals a from-scratch rebuild.
    assert index.rebuild() == incremental
    assert total(index) == 3


def test_out_of_order_events_trigger_rebuild(
    writer: EventWriter,
    human: Actor,
    other_session_human: Actor,
    index: Index,
    clock: FixedClock,
    cat: EventCatalog,
) -> None:
    early = EventFactory("demo", cat, IdGenerator(FixedClock(T0 - timedelta(hours=1))))
    late = EventFactory("demo", cat, IdGenerator(clock))
    writer.append([late.make("demo.recorded", Demo(n=1), human)])
    index.sync()
    # An event from another session with an earlier id arrives after a later one was applied.
    writer.append([early.make("demo.recorded", Demo(n=5), other_session_human)])
    # Applying it incrementally would violate global id order, so sync must rebuild.
    assert index.sync().rebuilt
    assert index.state_hash() == index.rebuild() and total(index) == 6


def test_projection_version_change_rebuilds(
    tmp_path: Path, writer: EventWriter, factory: EventFactory, human: Actor, index: Index
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    assert index.sync() == SyncResult(applied=1, rebuilt=True)
    # A new projection version invalidates the stored index: the DB must be rebuilt.
    upgraded = make_index(tmp_path, version="t2")
    assert upgraded.sync().rebuilt
    # After the rebuild under t2, the index is current again and an idle sync does nothing.
    assert upgraded.sync() == SyncResult(applied=0, rebuilt=False)


def test_shrunk_or_missing_file_rebuilds(
    tmp_path: Path,
    writer: EventWriter,
    factory: EventFactory,
    human: Actor,
    other_session_human: Actor,
    index: Index,
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    writer.append([factory.make("demo.recorded", Demo(n=10), other_session_human)])
    index.sync()
    assert total(index) == 11

    # A synced file truncated to zero bytes (history rewritten): rebuild, keeping the survivor.
    (tmp_path / "events" / "obd" / f"{S2}.jsonl").write_bytes(b"")
    assert index.sync().rebuilt
    assert total(index) == 1

    # A synced file that disappears: rebuild, dropping its events.
    (tmp_path / "events" / "obd" / f"{SESSION}.jsonl").unlink()
    assert index.sync().rebuilt
    assert total(index) == 0


def test_truncated_tail_applied_once_complete(
    tmp_path: Path, writer: EventWriter, factory: EventFactory, human: Actor, index: Index
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    index.sync()
    line = factory.make("demo.recorded", Demo(n=2), human).to_line()
    path = tmp_path / "events" / "obd" / f"{SESSION}.jsonl"

    # A crash left an unterminated partial line: it must not be applied yet.
    with path.open("ab") as handle:
        handle.write(line[:20])
    assert index.sync() == SyncResult(applied=0, rebuilt=False)

    # Once the line is completed, it is applied exactly once.
    with path.open("ab") as handle:
        handle.write(line[20:])
    assert index.sync() == SyncResult(applied=1, rebuilt=False)
    assert total(index) == 3
    assert index.sync() == SyncResult(applied=0, rebuilt=False)


def test_events_table_has_row_per_event(
    tmp_path: Path, clock: FixedClock, human: Actor, blobs: BlobStore, index: Index
) -> None:
    catalog = demo_catalog()
    writer = EventWriter(tmp_path / "events", project="demo", catalog=catalog, blobs=blobs)
    factory = EventFactory("demo", catalog, IdGenerator(clock))
    writer.append(
        [
            factory.make("demo.recorded", Demo(n=1), human),
            factory.make("demo.noted", Demo(n=2), human),
        ]
    )
    index.sync()
    # Both events are stored, including the type that has no handler.
    with index.connect() as conn:
        types = conn.execute(text("SELECT type FROM events ORDER BY id")).scalars().all()
    assert list(types) == ["demo.recorded", "demo.noted"]


def test_deleted_index_is_rebuilt_on_sync(
    tmp_path: Path, writer: EventWriter, factory: EventFactory, human: Actor, index: Index
) -> None:
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    index.sync()
    before = index.state_hash()
    (tmp_path / ".index" / "factory.sqlite").unlink()
    result = index.sync()
    # A missing DB is rebuilt from the event log and yields the same state.
    assert result.rebuilt
    assert index.state_hash() == before


def test_handler_failure_mid_batch_leaves_the_index_unchanged(
    tmp_path: Path, clock: FixedClock
) -> None:
    metadata = MetaData()
    core_tables(metadata)

    def explode(conn: Connection, event: Event) -> None:
        if event.payload["n"] == 99:
            raise RuntimeError("bad event")

    projection = Projection(version="t1", metadata=metadata, handlers={"demo.recorded": explode})
    index = Index(
        tmp_path / ".index" / "factory.sqlite", tmp_path / "events", demo_catalog(), projection
    )
    writer = EventWriter(
        tmp_path / "events", project="demo", catalog=demo_catalog(), blobs=BlobStore(tmp_path / "b")
    )
    factory = EventFactory("demo", demo_catalog(), IdGenerator(clock))
    actor = Actor(kind="human", id="obd", user="obd", session=SESSION)
    writer.append([factory.make("demo.recorded", Demo(n=1), actor)])
    index.sync()

    def snapshot() -> tuple[str, list[tuple[str, int]], int]:
        with index.connect() as conn:
            offsets = [
                (str(f), int(o))
                for f, o in conn.execute(text("SELECT file, offset FROM sync_state ORDER BY file"))
            ]
            count = int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())
        return index.state_hash(), offsets, count

    before = snapshot()
    clock.advance(timedelta(milliseconds=1))
    writer.append(
        [
            factory.make("demo.recorded", Demo(n=2), actor),
            factory.make("demo.recorded", Demo(n=99), actor),
        ]
    )
    with pytest.raises(RuntimeError):
        index.sync()
    assert snapshot() == before


def test_chase_tables_rebuild_reproduces_live_fold(tmp_path: Path, clock: FixedClock) -> None:
    """Chase rounds, sample extensions and admissions fold the same way after a full rebuild."""
    from factory.events.catalog import default_catalog
    from factory.index.chase import considered_works, extended_works, round_texts
    from factory.index.default import default_projection
    from factory.model.chase import ChaseDirection, ChaseRoundStarted, SampleExtended, SeedAdmitted
    from factory.model.identity import IdGenerator
    from factory.model.screening import PassLabel
    from tests.helpers import SESSION

    w1 = "rf:jones2021-sparse-1e2f3a4b"
    w2 = "rf:smith2020-attention-0a1b2c3d"
    project = tmp_path / "project"
    catalog = default_catalog()
    writer = EventWriter(
        project / "events", project="demo", catalog=catalog, blobs=BlobStore(project / "blobs")
    )
    factory = EventFactory("demo", catalog, IdGenerator(clock))
    obd = Actor(kind="human", id="obd", user="obd", session=SESSION)
    index = Index(
        project / ".index" / "factory.sqlite", project / "events", catalog, default_projection()
    )
    writer.append(
        [
            factory.make(
                "chase.round_started",
                ChaseRoundStarted(
                    round_id="chs_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
                    directions=(ChaseDirection.BACKWARD, ChaseDirection.FORWARD),
                    from_works=(w1, w2),
                    unchasable=(),
                    queries=("cited_by:W1|W2", "cites:W1|W2"),
                ),
                obd,
            ),
            factory.make(
                "screening.sample_extended",
                SampleExtended(
                    pass_label=PassLabel.B, random_seed=7, considered=(w1, w2), added=(w2,)
                ),
                obd,
            ),
            factory.make(
                "seed.admitted",
                SeedAdmitted(seed_id="SEED01", run_id="run_01HZX3K4M5N6P7Q8R9S0TVWXYZ", work_id=w1),
                obd,
            ),
        ]
    )

    def fold() -> tuple[set[str], set[str], set[str]]:
        with index.connect() as conn:
            return round_texts(conn), extended_works(conn), considered_works(conn)

    index.sync()
    live = fold()
    assert live == ({"cited_by:W1|W2", "cites:W1|W2"}, {w2}, {w1, w2})
    index.rebuild()
    assert fold() == live
