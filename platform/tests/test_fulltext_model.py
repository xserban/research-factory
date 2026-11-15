from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.model.fulltext import (
    QUALITY,
    ROUTE_ORDER,
    Attempted,
    AttemptOutcome,
    DocumentAdded,
    FetchStarted,
    LicenceStatus,
    Quality,
    Route,
    SourceChanged,
)

FETCH = "fft_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
ATTEMPT = "att_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
WORK = "rf:jones2021-sparse-1e2f3a4b"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def attempt_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "attempt_id": ATTEMPT,
        "fetch_id": FETCH,
        "work_id": WORK,
        "route": Route.ARXIV_HTML,
        "url": "https://arxiv.org/html/2101.00001v2",
        "http_status": 200,
        "outcome": AttemptOutcome.RETRIEVED,
        "reason": None,
        "retrieved_at": NOW,
        "source_version": "v2",
        "licence": "cc-by-4.0",
        "licence_status": LicenceStatus.REPORTED,
        "media_type": "text/html",
        "raw_hash": HASH_A,
        "metadata_blob": None,
        "document_id": DOC,
    }
    base.update(overrides)
    return base


def document_kwargs(**overrides: Any) -> dict[str, Any]:
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
    return base


def test_retrieved_attempt_requires_hash_and_document() -> None:
    Attempted(**attempt_kwargs())
    Attempted(**attempt_kwargs(outcome=AttemptOutcome.RESTORED))
    with pytest.raises(ValidationError):
        Attempted(**attempt_kwargs(raw_hash=None))
    with pytest.raises(ValidationError):
        Attempted(**attempt_kwargs(document_id=None))
    # The converse holds too: a non-retrieval carries no hash or document.
    with pytest.raises(ValidationError):
        Attempted(
            **attempt_kwargs(
                outcome=AttemptOutcome.FAILED, reason="timeout", raw_hash=HASH_A, document_id=None
            )
        )


def test_failed_attempt_requires_reason() -> None:
    not_retrieved: dict[str, Any] = {
        "outcome": AttemptOutcome.FAILED,
        "raw_hash": None,
        "document_id": None,
        "licence": None,
        "licence_status": LicenceStatus.NOT_REPORTED,
    }
    Attempted(**attempt_kwargs(**not_retrieved, reason="HTTP 503"))
    with pytest.raises(ValidationError):
        Attempted(**attempt_kwargs(**not_retrieved, reason=None))
    with pytest.raises(ValidationError):
        Attempted(**attempt_kwargs(**not_retrieved, reason="   "))
    with pytest.raises(ValidationError):
        Attempted(
            **attempt_kwargs(**{**not_retrieved, "outcome": AttemptOutcome.NOT_AVAILABLE}),
        )


def test_licence_status_consistent() -> None:
    Attempted(**attempt_kwargs())
    Attempted(
        **attempt_kwargs(licence=None, licence_status=LicenceStatus.NOT_REPORTED),
    )
    with pytest.raises(ValidationError):
        Attempted(**attempt_kwargs(licence=None))
    with pytest.raises(ValidationError):
        Attempted(**attempt_kwargs(licence_status=LicenceStatus.NOT_REPORTED))


def test_catalog_registers_fulltext_events() -> None:
    catalog = default_catalog()
    expected = {
        "fulltext.fetch_started": FetchStarted,
        "fulltext.attempted": Attempted,
        "fulltext.document_added": DocumentAdded,
        "fulltext.source_changed": SourceChanged,
    }
    for name, payload in expected.items():
        assert name in catalog
        assert catalog.get(name).schema == 1
        assert catalog.get(name).payload is payload


def test_route_order_excludes_researcher() -> None:
    assert ROUTE_ORDER == (Route.ARXIV_HTML, Route.ARXIV_SOURCE, Route.PMC_JATS, Route.EUROPEPMC_JATS, Route.OA_PDF)
    assert Route.RESEARCHER not in ROUTE_ORDER
    # LAB_LIBRARY has no quality of its own: an adopted document keeps its own (c52130a).
    assert set(QUALITY) == set(Route) - {Route.LAB_LIBRARY}
    assert QUALITY[Route.ARXIV_HTML] is Quality.STRUCTURED_HTML
    assert QUALITY[Route.ARXIV_SOURCE] is Quality.LATEX
    assert QUALITY[Route.PMC_JATS] is Quality.STRUCTURED_XML
    assert QUALITY[Route.EUROPEPMC_JATS] is Quality.STRUCTURED_XML
    assert QUALITY[Route.OA_PDF] is Quality.PDF_TEXT


def test_fetch_started_refuses_researcher_route() -> None:
    FetchStarted(fetch_id=FETCH, work_ids=[WORK], routes=[Route.OA_PDF], refresh=False)
    FetchStarted(fetch_id=FETCH, work_ids=[WORK], routes=None, refresh=True)
    with pytest.raises(ValidationError):
        FetchStarted(fetch_id=FETCH, work_ids=[WORK], routes=[Route.RESEARCHER], refresh=False)
    with pytest.raises(ValidationError):
        FetchStarted(
            fetch_id=FETCH,
            work_ids=[WORK],
            routes=[Route.OA_PDF, Route.OA_PDF],
            refresh=False,
        )


def test_document_provenance_and_quality_follow_route() -> None:
    DocumentAdded(**document_kwargs())
    with pytest.raises(ValidationError):
        DocumentAdded(**document_kwargs(quality=Quality.PDF_TEXT))
    with pytest.raises(ValidationError):
        DocumentAdded(**document_kwargs(provenance="researcher-supplied"))
    DocumentAdded(
        **document_kwargs(
            route=Route.RESEARCHER,
            quality=Quality.PDF_TEXT,
            provenance="researcher-supplied",
            media_type="application/pdf",
        )
    )
    with pytest.raises(ValidationError):
        DocumentAdded(**document_kwargs(supersedes=DOC))


def test_source_changed_requires_different_hashes() -> None:
    SourceChanged(document_id=DOC, attempt_id=ATTEMPT, expected_hash=HASH_A, observed_hash=HASH_B)
    with pytest.raises(ValidationError):
        SourceChanged(
            document_id=DOC, attempt_id=ATTEMPT, expected_hash=HASH_A, observed_hash=HASH_A
        )
    with pytest.raises(ValidationError):
        SourceChanged(
            document_id=DOC, attempt_id=ATTEMPT, expected_hash="md5:x", observed_hash=HASH_B
        )
