from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog
from factory.events.envelope import Actor
from factory.events.factory import EventFactory
from factory.events.validation import validate_event
from tests.helpers import Demo


def test_valid_event_has_no_issues(
    factory: EventFactory, human: Actor, blobs: BlobStore, cat: EventCatalog
) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human)
    assert validate_event(ev, catalog=cat, blobs=blobs, project="demo") == []


def test_unknown_type_is_reported(
    factory: EventFactory, human: Actor, blobs: BlobStore, cat: EventCatalog
) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human).model_copy(update={"type": "demo.unknown"})
    issues = validate_event(ev, catalog=cat, blobs=blobs, project="demo")
    assert [i.field for i in issues] == ["type"]


def test_schema_mismatch_is_reported(
    factory: EventFactory, human: Actor, blobs: BlobStore, cat: EventCatalog
) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human).model_copy(update={"schema_version": 2})
    issues = validate_event(ev, catalog=cat, blobs=blobs, project="demo")
    assert [i.field for i in issues] == ["schema"]


def test_payload_errors_are_located(
    factory: EventFactory, human: Actor, blobs: BlobStore, cat: EventCatalog
) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human)
    bad = ev.model_copy(update={"payload": {"n": "x"}})
    assert validate_event(bad, catalog=cat, blobs=blobs, project="demo")[0].field == "payload.n"


def test_wrong_project_is_reported(
    factory: EventFactory, human: Actor, blobs: BlobStore, cat: EventCatalog
) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), human)
    issues = validate_event(ev, catalog=cat, blobs=blobs, project="other")
    assert [i.field for i in issues] == ["project"]


def test_missing_input_blob_is_reported(
    factory: EventFactory, agent: Actor, blobs: BlobStore, cat: EventCatalog
) -> None:
    ev = factory.make("demo.recorded", Demo(n=1), agent, input_blob="sha256:" + "0" * 64)
    assert [i.field for i in validate_event(ev, catalog=cat, blobs=blobs, project="demo")] == [
        "input_blob"
    ]


def test_present_input_blob_is_accepted(
    factory: EventFactory, agent: Actor, blobs: BlobStore, cat: EventCatalog
) -> None:
    ref = blobs.put(b"input")
    ev = factory.make("demo.recorded", Demo(n=1), agent, input_blob=ref)
    assert validate_event(ev, catalog=cat, blobs=blobs, project="demo") == []
