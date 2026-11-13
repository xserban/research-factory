"""Plan-A follow-ups IDEA-25 to IDEA-29: tests that pin behaviour built under plan FL.

The backlog entries describe the state before plan FL; these tests show each point is closed:
per-document outcomes in `restore_missing` (27), no re-request of an unresolved changed source
(27/25), rotation of `refresh` by last attempt (28), identical bytes under another version
recorded visibly (29), and a recorded human resolution of a changed source (25).
"""

from datetime import timedelta
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.fulltext import AttemptOutcome, Route, SourceDecision
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.fulltext import (
    fetch_fulltext,
    resolve_source_change,
    restore_document,
    restore_missing,
)
from factory.services.screening import open_pass
from tests.fulltext_helpers import _include_all
from tests.helpers import _setup
from tests.route_helpers import StubRoute, always, retrieved, routes_for
from tests.screening_helpers import _draw
from tests.test_fulltext_restore import _fetched_document, _forget, _of_type


@pytest.fixture
def corpus(project: Project, agent: Actor, human: Actor, mock_sources: Any) -> None:
    """Both passes opened and every ordinary work included, so works are promoted."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)


def _html(content: bytes, version: str = "v2") -> dict[Route, StubRoute]:
    return routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, content, version=version)))


def test_restore_missing_reports_each_document_and_survives_an_exception(
    project: Project, corpus: None
) -> None:
    _work, document, raw_hash = _fetched_document(project, b"bytes one")
    _forget(project, raw_hash)

    class Boom(StubRoute):
        def fetch(self, work: Any, *, version: str | None = None) -> Any:
            raise RuntimeError("unexpected")

    routes = {Route.ARXIV_HTML: Boom(Route.ARXIV_HTML, lambda _w: None)}  # type: ignore[arg-type,return-value]

    outcomes = list(restore_missing(project, routes))  # type: ignore[arg-type]

    assert [(o.document_id, o.status) for o in outcomes] == [(document, "failed: RuntimeError")]


def test_unresolved_changed_source_is_not_requested_again(project: Project, corpus: None) -> None:
    _work, document, original = _fetched_document(project, b"original")
    _forget(project, original)
    changed = _html(b"edited")
    assert restore_document(project, document, routes=changed) == "source-changed"
    attempts = len(_of_type(project, "fulltext.attempted"))

    again = _html(b"edited")
    status = restore_document(project, document, routes=again)

    assert status == "source-changed-unresolved"
    assert again[Route.ARXIV_HTML].calls == []
    assert len(_of_type(project, "fulltext.attempted")) == attempts
    outcomes = list(restore_missing(project, again))
    assert [o.status for o in outcomes] == ["source-changed-unresolved"]
    assert again[Route.ARXIV_HTML].calls == []


def test_unavailable_changes_no_document_and_is_reported(project: Project, corpus: None) -> None:
    _work, document, raw_hash = _fetched_document(project, b"gone")
    _forget(project, raw_hash)
    routes = routes_for()  # every route answers "none"

    outcomes = list(restore_missing(project, routes))

    assert [(o.document_id, o.status) for o in outcomes] == [(document, "unavailable")]
    assert len(_of_type(project, "fulltext.document_added")) == 1
    assert _of_type(project, "fulltext.source_changed") == []


def test_identical_bytes_under_another_version_is_recorded(project: Project, corpus: None) -> None:
    _work, document, raw_hash = _fetched_document(project, b"same bytes")
    _forget(project, raw_hash)

    status = restore_document(project, document, routes=_html(b"same bytes", version="v9"))

    assert status == "restored"
    attempt = _of_type(project, "fulltext.attempted")[-1].payload
    assert attempt["outcome"] == AttemptOutcome.RESTORED.value
    assert attempt["version_differs"] == "v9"


def test_identical_bytes_under_the_same_version_records_no_difference(
    project: Project, corpus: None
) -> None:
    _work, document, raw_hash = _fetched_document(project, b"same bytes")
    _forget(project, raw_hash)

    restore_document(project, document, routes=_html(b"same bytes", version="v2"))

    assert _of_type(project, "fulltext.attempted")[-1].payload["version_differs"] is None


def test_refresh_with_small_limit_reaches_every_work_by_rotation(
    project: Project, corpus: None
) -> None:
    stub = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"x")))
    first = fetch_fulltext(project, routes=stub, refresh=True, limit=200)
    everyone = [w.work_id for w in first.works]
    assert len(everyone) > 1
    seen: list[str] = []
    for _round in range(len(everyone)):
        project.clock.advance(timedelta(seconds=1))  # type: ignore[attr-defined]
        summary = fetch_fulltext(project, routes=stub, refresh=True, limit=1)
        assert len(summary.works) == 1
        seen.append(summary.works[0].work_id)
    assert sorted(seen) == sorted(everyone)


def test_resolution_of_a_changed_source_is_a_recorded_human_act(
    project: Project, human: Actor, agent: Actor, corpus: None
) -> None:
    _work, document, original = _fetched_document(project, b"original")
    _forget(project, original)
    restore_document(project, document, routes=_html(b"edited"))
    observed = str(_of_type(project, "fulltext.source_changed")[0].payload["observed_hash"])

    with pytest.raises(FactoryValidationError):
        resolve_source_change(
            project, agent, document, observed, SourceDecision.KEEP_ORIGINAL, rationale="x"
        )
    assert _of_type(project, "fulltext.source_resolved") == []

    resolve_source_change(
        project, human, document, observed, SourceDecision.KEEP_ORIGINAL, rationale="checked"
    )
    resolved = _of_type(project, "fulltext.source_resolved")
    assert len(resolved) == 1 and resolved[0].payload["document_id"] == document
