"""Projection of full-text acquisition events: fetches, attempts, documents and source changes."""

import shutil
from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.index.default import PROJECTION_VERSION
from factory.model.fulltext import (
    Attempted,
    AttemptOutcome,
    DocumentAdded,
    FetchStarted,
    LicenceStatus,
    Quality,
    Route,
    SourceChanged,
)
from factory.services.context import Project

FETCH = "fft_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
ATTEMPT = "att_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
ATTEMPT_2 = "att_01HZX3K4M5N6P7Q8R9S0TVWXY1"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DOC_2 = "doc_01HZX3K4M5N6P7Q8R9S0TVWXY1"
WORK = "rf:jones2021-sparse-1e2f3a4b"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _actor(project: Project) -> Actor:
    return Actor(
        kind="agent",
        id="fulltext",
        user="obd",
        session=project.session,
        model="claude-opus-5-5",
        skill="rf-fulltext@1a2b3c4d",
    )


def _record(project: Project, type_: str, payload: Any) -> Event:
    blob = project.blobs.put(b"instruction")
    event = project.events.make(type_, payload, _actor(project), input_blob=blob)
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[dict[str, Any]]:
    with project.index.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql)).mappings().all()]


def _fetch(project: Project) -> Event:
    payload = FetchStarted(fetch_id=FETCH, work_ids=[WORK], routes=None, refresh=False)
    return _record(project, "fulltext.fetch_started", payload)


def _retrieved(**overrides: Any) -> Attempted:
    base: dict[str, Any] = {
        "attempt_id": ATTEMPT,
        "fetch_id": FETCH,
        "work_id": WORK,
        "route": Route.ARXIV_HTML,
        "url": "https://arxiv.org/html/2101.00001v2",
        "http_status": 200,
        "outcome": AttemptOutcome.RETRIEVED,
        "reason": None,
        "retrieved_at": "2026-11-03T12:00:00Z",
        "source_version": "v2",
        "licence": "cc-by-4.0",
        "licence_status": LicenceStatus.REPORTED,
        "media_type": "text/html",
        "raw_hash": HASH_A,
        "metadata_blob": None,
        "document_id": DOC,
    }
    base.update(overrides)
    return Attempted(**base)


def _document(**overrides: Any) -> DocumentAdded:
    base: dict[str, Any] = {
        "document_id": DOC,
        "work_id": WORK,
        "route": Route.ARXIV_HTML,
        "quality": Quality.STRUCTURED_HTML,
        "source_version": "v2",
        "raw_hash": HASH_A,
        "media_type": "text/html",
        "attempt_id": ATTEMPT,
        "provenance": "retrieved",
        "supersedes": None,
    }
    base.update(overrides)
    return DocumentAdded(**base)


def test_attempts_and_documents_project(project: Project) -> None:
    fetch = _fetch(project)
    attempt = _record(project, "fulltext.attempted", _retrieved())
    failed = _record(
        project,
        "fulltext.attempted",
        Attempted(
            attempt_id=ATTEMPT_2,
            fetch_id=FETCH,
            work_id=WORK,
            route=Route.OA_PDF,
            url=None,
            http_status=None,
            outcome=AttemptOutcome.NOT_AVAILABLE,
            reason="no open-access copy",
            retrieved_at="2026-11-03T12:01:00Z",
            source_version=None,
            licence=None,
            licence_status=LicenceStatus.NOT_REPORTED,
            media_type=None,
            raw_hash=None,
            metadata_blob=None,
            document_id=None,
        ),
    )
    doc = _record(project, "fulltext.document_added", _document())

    [fetch_row] = _rows(project, "SELECT * FROM fulltext_fetches")
    assert fetch_row == {"fetch_id": FETCH, "event_id": fetch.id, "actor_kind": "agent"}

    attempts = {row["attempt_id"]: row for row in _rows(project, "SELECT * FROM fulltext_attempts")}
    assert attempts[ATTEMPT]["event_id"] == attempt.id
    assert attempts[ATTEMPT]["route"] == "arxiv-html"
    assert attempts[ATTEMPT]["outcome"] == "retrieved"
    assert attempts[ATTEMPT]["licence"] == "cc-by-4.0"
    assert attempts[ATTEMPT]["raw_hash"] == HASH_A
    assert attempts[ATTEMPT]["document_id"] == DOC
    assert attempts[ATTEMPT_2]["event_id"] == failed.id
    assert attempts[ATTEMPT_2]["outcome"] == "not-available"
    assert attempts[ATTEMPT_2]["reason"] == "no open-access copy"
    assert attempts[ATTEMPT_2]["raw_hash"] is None
    assert attempts[ATTEMPT_2]["licence"] is None

    [doc_row] = _rows(project, "SELECT * FROM fulltext_documents")
    assert doc_row["event_id"] == doc.id
    assert doc_row["route"] == "arxiv-html"
    assert doc_row["quality"] == "structured-html"
    assert doc_row["provenance"] == "retrieved"
    assert doc_row["superseded_by"] is None


def test_supersedes_marks_previous_document(project: Project) -> None:
    _record(project, "fulltext.document_added", _document())
    _record(
        project,
        "fulltext.document_added",
        _document(
            document_id=DOC_2,
            route=Route.ARXIV_SOURCE,
            quality=Quality.LATEX,
            media_type="application/x-tex",
            raw_hash=HASH_B,
            supersedes=DOC,
        ),
    )

    docs = {row["document_id"]: row for row in _rows(project, "SELECT * FROM fulltext_documents")}
    assert docs[DOC]["superseded_by"] == DOC_2
    assert docs[DOC_2]["superseded_by"] is None
    assert docs[DOC_2]["supersedes"] == DOC


def test_source_change_projects(project: Project) -> None:
    event = _record(
        project,
        "fulltext.source_changed",
        SourceChanged(
            document_id=DOC,
            attempt_id=ATTEMPT_2,
            expected_hash=HASH_A,
            observed_hash=HASH_B,
        ),
    )
    [row] = _rows(project, "SELECT * FROM fulltext_source_changes")
    assert row == {
        "attempt_id": ATTEMPT_2,
        "document_id": DOC,
        "expected_hash": HASH_A,
        "observed_hash": HASH_B,
        "event_id": event.id,
    }


def test_rebuild_is_identical(project: Project) -> None:
    _fetch(project)
    _record(project, "fulltext.attempted", _retrieved())
    _record(project, "fulltext.document_added", _document())
    _record(
        project,
        "fulltext.document_added",
        _document(
            document_id=DOC_2,
            route=Route.ARXIV_SOURCE,
            quality=Quality.LATEX,
            media_type="application/x-tex",
            raw_hash=HASH_B,
            supersedes=DOC,
        ),
    )
    _record(
        project,
        "fulltext.source_changed",
        SourceChanged(
            document_id=DOC, attempt_id=ATTEMPT, expected_hash=HASH_A, observed_hash=HASH_B
        ),
    )

    incremental = project.index.state_hash()
    assert project.index.rebuild() == incremental


def test_projection_never_opens_library(project: Project) -> None:
    library = project.paths.library_dir
    library.mkdir(parents=True, exist_ok=True)
    (library / "placeholder.bin").write_bytes(b"full text")
    _fetch(project)
    _record(project, "fulltext.attempted", _retrieved())
    _record(project, "fulltext.document_added", _document())

    before = project.index.state_hash()
    shutil.rmtree(library)
    assert project.index.rebuild() == before


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "44"
