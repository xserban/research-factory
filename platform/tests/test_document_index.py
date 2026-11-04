from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from factory.document.anchors import AnchorKind
from factory.events.envelope import Actor, Event
from factory.index.default import default_projection
from factory.model.document import ConversionFailed, Converted, FailureReason
from factory.services.context import Project

CNV = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
CNV_2 = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXY1"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _actor(project: Project) -> Actor:
    return Actor(
        kind="agent",
        id="document",
        user="obd",
        session=project.session,
        model="claude-opus-5-5",
        skill="rf-document@1a2b3c4d",
    )


def _record(project: Project, type_: str, payload: Any) -> Event:
    blob = project.blobs.put(b"instruction")
    event = project.events.make(type_, payload, _actor(project), input_blob=blob)
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[dict[str, Any]]:
    with project.index.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql)).mappings().all()]


def _converted(**overrides: Any) -> Converted:
    base: dict[str, Any] = {
        "conversion_id": CNV,
        "document_id": DOC,
        "converter": "latexml",
        "converter_version": "0.8.7",
        "raw_hash": HASH_A,
        "markdown_hash": HASH_B,
        "manifest_hash": HASH_C,
        "counts": {kind.value: 2 for kind in AnchorKind},
        "warnings": ["table 3 has merged cells"],
    }
    base.update(overrides)
    return Converted(**base)


def test_converted_projects_one_row(project: Project) -> None:
    event = _record(project, "document.converted", _converted())
    [row] = _rows(project, "SELECT * FROM document_conversions")
    assert row["conversion_id"] == CNV
    assert row["document_id"] == DOC
    assert row["converter"] == "latexml"
    assert row["converter_version"] == "0.8.7"
    assert row["raw_hash"] == HASH_A
    assert row["markdown_hash"] == HASH_B
    assert row["manifest_hash"] == HASH_C
    assert row["event_id"] == event.id
    assert '"paragraph": 2' in row["counts"]
    assert row["warnings"] == '["table 3 has merged cells"]'


def test_repeated_event_changes_nothing(project: Project, tmp_path: Path) -> None:
    event = _record(project, "document.converted", _converted())
    projection = default_projection()
    engine = create_engine(f"sqlite:///{tmp_path / 'replay.db'}")
    projection.metadata.create_all(engine)
    handler = projection.handlers["document.converted"]
    with engine.begin() as conn:
        handler(conn, event)
        handler(conn, event)
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM document_conversions")).scalar_one()
    assert count == 1


def test_second_version_gives_second_row(project: Project) -> None:
    _record(project, "document.converted", _converted())
    _record(
        project,
        "document.converted",
        _converted(conversion_id=CNV_2, converter_version="0.9.0"),
    )
    rows = _rows(project, "SELECT conversion_id FROM document_conversions")
    assert {row["conversion_id"] for row in rows} == {CNV, CNV_2}


def test_failure_projects(project: Project) -> None:
    event = _record(
        project,
        "document.conversion_failed",
        ConversionFailed(
            document_id=DOC,
            converter="latexml",
            reason=FailureReason.CONVERSION_ERROR,
            error_class="ValueError",
        ),
    )
    [row] = _rows(project, "SELECT * FROM document_failures")
    assert row == {
        "event_id": event.id,
        "document_id": DOC,
        "converter": "latexml",
        "reason": "conversion-error",
        "error_class": "ValueError",
    }


def test_rebuild_gives_same_state_hash(project: Project) -> None:
    _record(project, "document.converted", _converted())
    _record(
        project,
        "document.conversion_failed",
        ConversionFailed(
            document_id=DOC,
            converter=None,
            reason=FailureReason.NO_CONVERTER,
            error_class=None,
        ),
    )
    incremental = project.index.state_hash()
    assert project.index.rebuild() == incremental
