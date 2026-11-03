"""Restoring a library entry by its recorded route (plan 2A, ruling 9).

Routes are stubs, as in `test_fulltext_service`, so no test touches the network. A restore writes
nothing before its request is validated; a hash match restores the entry; a hash mismatch keeps the
new bytes and records `fulltext.source_changed` against the existing document.
"""

from typing import Any

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.fulltext import AttemptOutcome, DocumentAdded, Quality, Route
from factory.model.screening import PassLabel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext, restore_document
from factory.services.screening import open_pass
from factory.sources.fulltext.base import not_retrieved
from tests.helpers import _setup
from tests.test_fulltext_service import _include_all, always, missing, retrieved, routes_for
from tests.test_screening_next import _draw


@pytest.fixture
def corpus(project: Project, agent: Actor, human: Actor, mock_sources: Any) -> None:
    """A corpus with both passes opened and every ordinary work included, so works are promoted."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _of_type(project: Project, type_: str) -> list[Event]:
    return [event for event in _events(project) if event.type == type_]


def _promoted_work(project: Project) -> str:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )[0]


def _fetched_document(project: Project, content: bytes) -> tuple[str, str, str]:
    """Fetch one promoted work from arXiv HTML. Returns (work, document, raw_hash)."""
    work = _promoted_work(project)
    summary = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, content))),
        work_ids=[work],
    )
    document = summary.works[0].documents[0]
    raw_hash = str(_of_type(project, "fulltext.document_added")[0].payload["raw_hash"])
    return work, document, raw_hash


def _forget(project: Project, raw_hash: str) -> None:
    """Remove a library entry, as if it had been lost, so restore has work to do."""
    project.library.path(raw_hash).unlink()


def test_restore_same_hash(project: Project, corpus: None) -> None:
    work, document, raw_hash = _fetched_document(project, b"same bytes")
    _forget(project, raw_hash)
    assert not project.library.exists(raw_hash)
    documents_before = len(_of_type(project, "fulltext.document_added"))
    stub = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"same bytes")))

    status = restore_document(project, document, routes=stub)

    assert status == "restored"
    assert project.library.exists(raw_hash)
    assert len(_of_type(project, "fulltext.document_added")) == documents_before
    assert _of_type(project, "fulltext.source_changed") == []
    attempt = _of_type(project, "fulltext.attempted")[-1].payload
    assert attempt["outcome"] == AttemptOutcome.RESTORED.value
    assert attempt["fetch_id"] is None
    assert attempt["document_id"] == document
    assert attempt["raw_hash"] == raw_hash
    assert attempt["work_id"] == work


def test_restore_changed_source_records_event(project: Project, corpus: None) -> None:
    _work, document, original = _fetched_document(project, b"original bytes")
    _forget(project, original)
    stub = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"edited bytes")))

    status = restore_document(project, document, routes=stub)

    assert status == "source-changed"
    change = _of_type(project, "fulltext.source_changed")
    assert len(change) == 1
    observed = str(change[0].payload["observed_hash"])
    assert change[0].payload["document_id"] == document
    assert change[0].payload["expected_hash"] == original
    assert observed != original
    assert project.library.exists(observed)
    attempt = _of_type(project, "fulltext.attempted")[-1].payload
    assert attempt["outcome"] == AttemptOutcome.RESTORED.value
    assert attempt["document_id"] == document
    assert attempt["raw_hash"] == observed
    assert len(_of_type(project, "fulltext.document_added")) == 1


def test_restore_present_is_noop(project: Project, corpus: None) -> None:
    _work, document, raw_hash = _fetched_document(project, b"present bytes")
    before = len(_events(project))
    stub = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"present bytes")))

    status = restore_document(project, document, routes=stub)

    assert status == "present"
    assert len(_events(project)) == before
    assert stub[Route.ARXIV_HTML].calls == []
    assert project.library.exists(raw_hash)


def test_restore_researcher_supplied_refused(project: Project, corpus: None) -> None:
    work = _promoted_work(project)
    raw_hash = project.library.put(b"researcher pdf")
    added = DocumentAdded(
        document_id=project.ids.new("doc"),
        work_id=work,
        route=Route.RESEARCHER,
        quality=Quality.PDF_TEXT,
        source_version="researcher-file",
        raw_hash=raw_hash,
        media_type="application/pdf",
        attempt_id=project.ids.new("att"),
        provenance="researcher-supplied",
    )
    project.record([project.events.make("fulltext.document_added", added, project.system_actor())])
    _forget(project, raw_hash)
    before = len(_events(project))
    stub = routes_for()

    with pytest.raises(FactoryValidationError) as raised:
        restore_document(project, added.document_id, routes=stub)

    assert raised.value.issues == [
        ValidationIssue("document_id", "researcher-supplied: re-import the file")
    ]
    assert len(_events(project)) == before
    assert not project.library.exists(raw_hash)


# --- Validation and failure paths ---


def test_restore_unknown_document_refused(project: Project) -> None:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as raised:
        restore_document(project, project.ids.new("doc"), routes=routes_for())
    assert raised.value.issues == [ValidationIssue("document_id", "unknown document")]
    assert len(_events(project)) == before


def test_restore_route_not_supplied_refused(project: Project, corpus: None) -> None:
    _work, document, raw_hash = _fetched_document(project, b"needs html")
    _forget(project, raw_hash)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as raised:
        restore_document(project, document, routes={})

    assert raised.value.issues == [ValidationIssue("routes", "no route supplied for arxiv-html")]
    assert len(_events(project)) == before


def test_restore_unavailable_records_attempt_only(project: Project, corpus: None) -> None:
    _work, document, raw_hash = _fetched_document(project, b"gone bytes")
    _forget(project, raw_hash)
    stub = routes_for(arxiv_html=always(missing(Route.ARXIV_HTML, "no-html-rendering")))

    status = restore_document(project, document, routes=stub)

    assert status == "unavailable"
    assert not project.library.exists(raw_hash)
    assert len(_of_type(project, "fulltext.document_added")) == 1
    assert _of_type(project, "fulltext.source_changed") == []
    attempt = _of_type(project, "fulltext.attempted")[-1].payload
    assert attempt["outcome"] == AttemptOutcome.NOT_AVAILABLE.value
    assert attempt["reason"] == "no-html-rendering"
    assert attempt["document_id"] is None
    assert attempt["raw_hash"] is None


def test_restore_failed_route_result_is_unavailable(project: Project, corpus: None) -> None:
    _work, document, raw_hash = _fetched_document(project, b"flaky bytes")
    _forget(project, raw_hash)
    stub = routes_for(
        arxiv_html=always(
            not_retrieved(Route.ARXIV_HTML, AttemptOutcome.FAILED, "not-a-pdf", http_status=200)
        )
    )

    status = restore_document(project, document, routes=stub)

    assert status == "unavailable"
    attempt = _of_type(project, "fulltext.attempted")[-1].payload
    assert attempt["outcome"] == AttemptOutcome.FAILED.value
    assert attempt["reason"] == "not-a-pdf"
    assert attempt["document_id"] is None


def test_restore_agent_trigger_keeps_input_blob(
    project: Project, agent: Actor, corpus: None
) -> None:
    _work, document, raw_hash = _fetched_document(project, b"agent bytes")
    _forget(project, raw_hash)
    stub = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"agent bytes")))

    status = restore_document(project, document, routes=stub, actor=agent)

    assert status == "restored"
    last = _of_type(project, "fulltext.attempted")[-1]
    assert last.actor.kind == "agent"
    assert last.input_blob is not None
    assert project.blobs.exists(last.input_blob)
