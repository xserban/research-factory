"""`fulltext_status` and the full-text findings of `check` (plan 2A, task 11).

The status is read from the projection and the final outcomes only. Removing a library entry
changes no count, and a rebuild from the event log gives the same status.
"""

from typing import Any

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.fulltext import AttemptOutcome, Route
from factory.model.screening import PassLabel
from factory.model.work import Work
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.fulltext_status import fulltext_status
from factory.services.screening import open_pass
from factory.sources.fulltext.base import RouteResult, not_retrieved
from tests.helpers import _setup
from tests.test_fulltext_service import StubRoute, _include_all
from tests.test_screening_next import _draw


@pytest.fixture
def corpus(project: Project, agent: Actor, human: Actor, mock_sources: Any) -> None:
    """Both passes opened and every ordinary work included, so several works are promoted."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)


def _promoted(project: Project) -> list[str]:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _routes(retrieve: str, content: bytes) -> dict[Route, StubRoute]:
    """arXiv HTML retrieves `content` for the work `retrieve` and says why not for any other.
    The other two routes never retrieve, each with its own reason."""

    def html(work: Work) -> RouteResult:
        if work.id == retrieve:
            return RouteResult(
                route=Route.ARXIV_HTML,
                outcome=AttemptOutcome.RETRIEVED,
                url="https://arxiv.org/html/2101.00001v2",
                http_status=200,
                content=content,
                media_type="text/html",
                source_version="v2",
            )
        return not_retrieved(Route.ARXIV_HTML, AttemptOutcome.NOT_AVAILABLE, "no html")

    return {
        Route.ARXIV_HTML: StubRoute(Route.ARXIV_HTML, html),
        Route.ARXIV_SOURCE: StubRoute(
            Route.ARXIV_SOURCE,
            lambda _work: not_retrieved(Route.ARXIV_SOURCE, AttemptOutcome.NOT_AVAILABLE, "no src"),
        ),
        Route.OA_PDF: StubRoute(
            Route.OA_PDF,
            lambda _work: not_retrieved(Route.OA_PDF, AttemptOutcome.FAILED, "no pdf"),
        ),
    }


def _fetch_two(project: Project, retrieved_work: str, missed_work: str) -> None:
    fetch_fulltext(
        project,
        routes=_routes(retrieved_work, b"the retrieved work"),
        work_ids=[retrieved_work, missed_work],
    )


def test_status_counts_and_reasons(project: Project, corpus: None) -> None:
    promoted = _promoted(project)
    assert len(promoted) >= 3
    retrieved_work, missed_work = promoted[0], promoted[1]
    _fetch_two(project, retrieved_work, missed_work)

    status = fulltext_status(project)

    assert status.promoted == len(promoted)
    assert status.retrieved == 1
    assert status.not_retrieved == 1
    assert status.unsought == len(promoted) - 2
    assert status.by_route[Route.ARXIV_HTML] == 1
    assert status.by_route[Route.ARXIV_SOURCE] == 0
    assert status.by_route[Route.OA_PDF] == 0
    by_work = {entry.work_id: entry for entry in status.works}
    assert set(by_work) == set(promoted)

    found = by_work[retrieved_work]
    assert found.state == "retrieved"
    assert len(found.documents) == 1
    assert found.reasons == {}

    missed = by_work[missed_work]
    assert missed.state == "not-retrieved"
    assert missed.documents == []
    assert missed.reasons == {
        Route.ARXIV_HTML: "no html",
        Route.ARXIV_SOURCE: "no src",
        Route.OA_PDF: "no pdf",
    }

    untouched = by_work[promoted[2]]
    assert untouched.state == "unsought"
    assert untouched.documents == []
    assert untouched.reasons == {}


def test_status_restricted_to_named_works(project: Project, corpus: None) -> None:
    promoted = _promoted(project)
    _fetch_two(project, promoted[0], promoted[1])

    status = fulltext_status(project, work_ids=[promoted[1]])

    assert status.promoted == 1
    assert [entry.work_id for entry in status.works] == [promoted[1]]
    assert status.not_retrieved == 1
    assert status.retrieved == 0


def test_status_refuses_an_unpromoted_work(project: Project, corpus: None) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        fulltext_status(project, work_ids=["rf:nope-00000000"])

    assert raised.value.issues == [
        ValidationIssue("work_ids", "rf:nope-00000000: not promoted at title/abstract")
    ]


def test_status_and_rebuild_without_library(project: Project, corpus: None) -> None:
    promoted = _promoted(project)
    _fetch_two(project, promoted[0], promoted[1])
    before = fulltext_status(project)
    library_files = [p for p in project.paths.library_dir.rglob("*") if p.is_file()]
    assert library_files, "the fetch must have put the retrieved bytes in the library"
    for path in library_files:
        path.unlink()

    without_library = fulltext_status(project)
    project.index.rebuild()
    after_rebuild = fulltext_status(project)

    assert without_library == before
    assert after_rebuild == before
