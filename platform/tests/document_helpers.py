"""Shared test setup for document conversion: a promoted work with one retrieved HTML document,
the stub converter and registry, and event and promotion readers."""

from pathlib import Path
from typing import Any

from factory.document.converter import ConverterUnavailable
from factory.document.latexml_html import LatexmlHtmlConverter
from factory.document.registry import ConverterRegistry
from factory.events.catalog import default_catalog
from factory.events.envelope import Event
from factory.events.reader import read_all
from factory.model.fulltext import AttemptOutcome, Route
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_convert import ConvertSummary, convert_documents
from factory.services.fulltext import fetch_fulltext
from factory.sources.fulltext.base import not_retrieved
from tests.test_fulltext_service import StubRoute, always, retrieved

ARTICLE = (Path(__file__).parent / "fixtures" / "document" / "latexml_article.html").read_bytes()


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


class StubConverter:
    """LaTeXML HTML behaviour, with a scripted version and scripted failures.

    `unavailable` makes `version` raise `ConverterUnavailable`. `fail_on` makes `to_markdown`
    raise `error` for any raw bytes that contain it.
    """

    name = "latexml-html"
    accepts = frozenset({"text/html"})

    def __init__(
        self,
        *,
        version: str = "1.0+stub",
        unavailable: bool = False,
        fail_on: bytes | None = None,
        error: Exception | None = None,
        extra_warnings: tuple[str, ...] = (),
    ) -> None:
        self._inner = LatexmlHtmlConverter()
        self._extra_warnings = extra_warnings
        self._version = version
        self._unavailable = unavailable
        self._fail_on = fail_on
        self._error = error

    def version(self) -> str:
        if self._unavailable:
            raise ConverterUnavailable("stub tool is not installed")
        return self._version

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        if self._fail_on is not None and self._fail_on in raw:
            assert self._error is not None
            raise self._error
        markdown, warnings = self._inner.to_markdown(raw, media_type)
        return markdown, tuple(warnings) + self._extra_warnings


def make_registry(converter: StubConverter | None = None) -> ConverterRegistry:
    return ConverterRegistry([converter or StubConverter()])


def run_convert(project: Project, registry: ConverterRegistry, **kwargs: Any) -> ConvertSummary:
    return convert_documents(project, registry, **kwargs)


def events_of_type(project: Project, event_type: str) -> list[Event]:
    return [
        event
        for event in read_all(project.paths.events_dir, default_catalog())
        if event.type == event_type
    ]


def event_bytes(project: Project) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in sorted(project.paths.events_dir.rglob("*")) if p.is_file()}


def promoted_works(project: Project) -> list[str]:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )
