import json
import re
from datetime import timedelta

import pytest
from pydantic import ValidationError

from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog, EventType
from factory.events.envelope import Actor, Event
from factory.events.factory import EventFactory
from factory.model.base import StrictModel
from tests.helpers import T0, Demo


def test_agent_actor_requires_model_and_skill(session_id: str) -> None:
    with pytest.raises(ValidationError):
        Actor(
            kind="agent",
            id="screener-a",
            user="obd",
            session=session_id,
            skill="rf-screen@1a2b3c4d",
        )
    with pytest.raises(ValidationError):
        Actor(
            kind="agent",
            id="screener-a",
            user="obd",
            session=session_id,
            model="claude-opus-5-5",
        )


def test_human_actor_must_not_carry_model(session_id: str) -> None:
    with pytest.raises(ValidationError):
        Actor(kind="human", id="obd", user="obd", session=session_id, model="claude-opus-5-5")


def test_actor_id_must_be_path_safe(session_id: str) -> None:
    with pytest.raises(ValidationError):
        Actor(kind="human", id="../etc", user="obd", session=session_id)


def test_actor_session_must_be_a_ulid() -> None:
    with pytest.raises(ValidationError):
        Actor(kind="human", id="obd", user="obd", session="not-a-ulid")


def test_actor_skill_must_be_name_at_hash() -> None:
    with pytest.raises(ValidationError):
        Actor(
            kind="agent",
            id="screener-a",
            user="obd",
            session="01JZ9Q3K5M7N8P0R2S4T6V8W0X",
            model="claude-opus-5-5",
            skill="RF-screen@1a2b",
        )


def test_event_line_round_trip_uses_schema_alias_and_millisecond_z(
    factory: EventFactory, human: Actor
) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human)
    line = ev.to_line()
    raw = json.loads(line)
    assert raw["schema"] == 1 and "schema_version" not in raw
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", raw["ts"])
    assert line.endswith(b"\n") and Event.from_line(line) == ev


def test_event_ts_must_match_id_timestamp(factory: EventFactory, human: Actor) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human)
    with pytest.raises(ValidationError):
        Event.model_validate({**ev.model_dump(by_alias=True), "ts": T0 + timedelta(seconds=1)})


def test_naive_ts_is_rejected(factory: EventFactory, human: Actor) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human)
    with pytest.raises(ValidationError):
        Event.model_validate({**ev.model_dump(by_alias=True), "ts": T0.replace(tzinfo=None)})


def test_agent_event_requires_input_blob(factory: EventFactory, agent: Actor) -> None:
    with pytest.raises(ValidationError):
        factory.make("demo.recorded", Demo(n=1), agent)


def test_agent_event_accepts_input_blob(
    factory: EventFactory, agent: Actor, blobs: BlobStore
) -> None:
    ref = blobs.put(b"input")
    ev = factory.make("demo.recorded", Demo(n=1), agent, input_blob=ref)
    assert ev.input_blob == ref


def test_refs_must_be_non_empty_strings(factory: EventFactory, human: Actor) -> None:
    with pytest.raises(ValidationError):
        factory.make("demo.recorded", Demo(n=1), human, refs=[""])


def test_make_rejects_payload_of_the_wrong_model(factory: EventFactory, human: Actor) -> None:
    class Other(StrictModel):
        n: int

    with pytest.raises(TypeError):
        factory.make("demo.recorded", Other(n=1), human)


def test_catalog_rejects_duplicates_and_bad_names() -> None:
    cat = EventCatalog()
    cat.register(EventType("demo.recorded", Demo, 1))
    with pytest.raises(ValueError):
        cat.register(EventType("demo.recorded", Demo, 1))
    with pytest.raises(ValueError):
        cat.register(EventType("Demo", Demo, 1))
