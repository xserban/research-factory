"""Shared test setup for document conversion: a promoted work with one retrieved HTML document."""

from factory.model.fulltext import AttemptOutcome, Route
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.sources.fulltext.base import not_retrieved
from tests.test_fulltext_service import StubRoute, always, retrieved


def fetched_document(project: Project, work_id: str, html: bytes) -> str:
    """Fetch `html` as the arXiv HTML document of `work_id` and return the new document's id.

    The work must be promoted at title/abstract screening. The other two automatic routes never
    retrieve, so the document is the only one the work gets.
    """
    routes = {
        Route.ARXIV_HTML: StubRoute(Route.ARXIV_HTML, always(retrieved(Route.ARXIV_HTML, html))),
        Route.ARXIV_SOURCE: StubRoute(
            Route.ARXIV_SOURCE,
            always(not_retrieved(Route.ARXIV_SOURCE, AttemptOutcome.NOT_AVAILABLE, "no src")),
        ),
        Route.OA_PDF: StubRoute(
            Route.OA_PDF,
            always(not_retrieved(Route.OA_PDF, AttemptOutcome.FAILED, "no pdf")),
        ),
    }
    summary = fetch_fulltext(project, routes=routes, work_ids=[work_id])
    documents = [doc for entry in summary.works for doc in entry.documents]
    assert len(documents) == 1, f"expected one new document for {work_id}, got {documents}"
    return documents[0]
