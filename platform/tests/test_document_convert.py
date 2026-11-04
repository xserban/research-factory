"""Document conversion service: events, idempotence, failures and scope (plan 2B2, task 3).

Each conversion is an event with hashes and counts; Markdown and manifest bytes live in the
project library. A repeat of the same converter version writes nothing; a failure is an event
with a fixed reason and never the error text.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from factory.document.anchors import AnchorKind, ManifestError
from factory.document.converter import ConverterUnavailable, convert
from factory.document.latexml_html import LatexmlHtmlConverter
from factory.document.registry import ConverterRegistry, default_converters
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.catalog import default_catalog
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.document import Converted
from factory.model.fulltext import AttemptOutcome, Route
from factory.model.screening import PassLabel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_convert import ConvertSummary, convert_documents
from factory.services.fulltext import fetch_fulltext, record_supplied_document
from factory.services.screening import open_pass
from factory.sources.fulltext.base import not_retrieved
from tests.document_helpers import fetched_document
from tests.helpers import _setup
from tests.test_fulltext_service import StubRoute, _include_all, always, retrieved
from tests.test_screening_next import _draw

ARTICLE = (Path(__file__).parent / "fixtures" / "document" / "latexml_article.html").read_bytes()
SENTENCE = b"Ut enim ad minim veniam"
MARKER = b"FAIL-ME"
PDF = b"%PDF-1.4 synthetic"


@pytest.fixture
def corpus(project: Project, agent: Actor, human: Actor, mock_sources: Any) -> None:
    """Both passes opened and every ordinary work included, so several works are promoted."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)


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
    ) -> None:
        self._inner = LatexmlHtmlConverter()
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
        return self._inner.to_markdown(raw, media_type)


def _registry(converter: StubConverter | None = None) -> ConverterRegistry:
    return ConverterRegistry([converter or StubConverter()])


def _run(project: Project, registry: ConverterRegistry, **kwargs: Any) -> ConvertSummary:
    return convert_documents(project, registry, **kwargs)


def _events(project: Project, event_type: str) -> list[Event]:
    return [
        event
        for event in read_all(project.paths.events_dir, default_catalog())
        if event.type == event_type
    ]


def _event_bytes(project: Project) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in sorted(project.paths.events_dir.rglob("*")) if p.is_file()}


def _promoted(project: Project) -> list[str]:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _sha(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _statuses(summary: ConvertSummary) -> list[str]:
    return [outcome.status for outcome in summary.outcomes]


def _strip_library(project: Project) -> None:
    for path in project.paths.library_dir.rglob("*"):
        if path.is_file():
            path.unlink()


def test_converts_html_document(project: Project, corpus: None) -> None:
    work = _promoted(project)[0]
    document = fetched_document(project, work, ARTICLE)

    summary = _run(project, default_converters())

    direct = convert(LatexmlHtmlConverter(), ARTICLE, "text/html")
    [event] = _events(project, "document.converted")
    payload = Converted.model_validate(event.payload)
    assert event.actor == project.human_actor()
    assert payload.document_id == document
    assert payload.converter == direct.converter
    assert payload.converter_version == direct.converter_version
    assert payload.markdown_hash == direct.markdown_hash
    assert payload.manifest_hash == _sha(direct.manifest.to_json())
    assert payload.raw_hash == _sha(ARTICLE)
    assert list(payload.warnings) == list(direct.warnings)
    expected_counts = {
        kind.value: sum(1 for a in direct.manifest.anchors if a.kind is kind) for kind in AnchorKind
    }
    assert payload.counts == expected_counts
    assert payload.counts[AnchorKind.SECTION.value] > 0

    assert project.library.get(payload.markdown_hash) == direct.markdown.encode("utf-8")
    assert project.library.get(payload.manifest_hash) == direct.manifest.to_json()

    assert _statuses(summary) == ["converted"]
    assert summary.converted == 1
    assert summary.outcomes[0].conversion_id == payload.conversion_id
    assert summary.outcomes[0].work_id == work
    assert summary.outcomes[0].document_id == document


def test_second_run_is_unchanged_and_writes_nothing(project: Project, corpus: None) -> None:
    fetched_document(project, _promoted(project)[0], ARTICLE)
    _run(project, _registry())
    before = _event_bytes(project)
    library_before = {p for p in project.paths.library_dir.rglob("*") if p.is_file()}

    summary = _run(project, _registry())

    assert _statuses(summary) == ["unchanged"]
    assert summary.unchanged == 1
    assert summary.outcomes[0].conversion_id is None
    assert _event_bytes(project) == before
    assert {p for p in project.paths.library_dir.rglob("*") if p.is_file()} == library_before


def test_version_bump_writes_second_conversion(project: Project, corpus: None) -> None:
    fetched_document(project, _promoted(project)[0], ARTICLE)
    _run(project, _registry(StubConverter(version="1.0+a")))

    summary = _run(project, _registry(StubConverter(version="1.0+b")))

    assert _statuses(summary) == ["converted"]
    versions = [
        Converted.model_validate(e.payload).converter_version
        for e in _events(project, "document.converted")
    ]
    assert versions == ["1.0+a", "1.0+b"]


def test_no_converter_records_failure(project: Project, corpus: None) -> None:
    work = _promoted(project)[0]
    with project.index.exclusive():
        project.index.sync()
        document = record_supplied_document(
            project,
            work,
            content=PDF,
            source_version="v1",
            media_type="application/pdf",
            actor=project.human_actor(),
        )
    assert document is not None

    summary = _run(project, _registry())

    assert _statuses(summary) == ["failed"]
    assert summary.failed == 1
    assert summary.outcomes[0].reason == "no-converter"
    assert summary.outcomes[0].conversion_id is None
    [event] = _events(project, "document.conversion_failed")
    assert event.payload == {
        "document_id": document,
        "converter": None,
        "reason": "no-converter",
        "error_class": None,
    }


def test_converter_unavailable_records_failure(project: Project, corpus: None) -> None:
    fetched_document(project, _promoted(project)[0], ARTICLE)

    summary = _run(project, _registry(StubConverter(unavailable=True)))

    assert _statuses(summary) == ["failed"]
    assert summary.outcomes[0].reason == "converter-unavailable"
    [event] = _events(project, "document.conversion_failed")
    assert event.payload["reason"] == "converter-unavailable"
    assert event.payload["converter"] == "latexml-html"
    assert event.payload["error_class"] is None
    assert _events(project, "document.converted") == []


def test_manifest_error_records_failure_and_batch_continues(project: Project, corpus: None) -> None:
    """Review Focus 1: the first of two documents raises, and the second still converts."""
    first_work, second_work = _promoted(project)[0], _promoted(project)[1]
    bad = fetched_document(project, first_work, ARTICLE + b"<!-- " + MARKER + b" -->")
    good = fetched_document(project, second_work, ARTICLE)
    registry = _registry(
        StubConverter(fail_on=MARKER, error=ManifestError("anchor grammar broken: secret text"))
    )

    summary = _run(project, registry)

    assert _statuses(summary) == ["failed", "converted"]
    assert summary.failed == 1
    assert summary.converted == 1
    assert summary.outcomes[0].document_id == bad
    assert summary.outcomes[0].reason == "conversion-error"
    [failure] = _events(project, "document.conversion_failed")
    assert failure.payload == {
        "document_id": bad,
        "converter": "latexml-html",
        "reason": "conversion-error",
        "error_class": "ManifestError",
    }
    [converted] = _events(project, "document.converted")
    assert converted.payload["document_id"] == good


def test_raw_missing_reports_without_event(project: Project, corpus: None) -> None:
    fetched_document(project, _promoted(project)[0], ARTICLE)
    _strip_library(project)
    before = _event_bytes(project)

    summary = _run(project, _registry())

    assert _statuses(summary) == ["raw-missing"]
    assert summary.raw_missing == 1
    assert summary.outcomes[0].conversion_id is None
    assert _event_bytes(project) == before
    assert not [p for p in project.paths.library_dir.rglob("*") if p.is_file()]


def test_named_unknown_document_refused_and_writes_nothing(project: Project, corpus: None) -> None:
    work = _promoted(project)[0]
    old = fetched_document(project, work, ARTICLE)
    routes = {
        Route.ARXIV_HTML: StubRoute(
            Route.ARXIV_HTML, always(retrieved(Route.ARXIV_HTML, b"newer", version="v3"))
        ),
        Route.ARXIV_SOURCE: StubRoute(
            Route.ARXIV_SOURCE,
            always(not_retrieved(Route.ARXIV_SOURCE, AttemptOutcome.NOT_AVAILABLE, "no src")),
        ),
        Route.OA_PDF: StubRoute(
            Route.OA_PDF, always(not_retrieved(Route.OA_PDF, AttemptOutcome.FAILED, "no pdf"))
        ),
    }
    fetch_fulltext(project, routes=routes, work_ids=[work], refresh=True)
    before = _event_bytes(project)

    with pytest.raises(FactoryValidationError) as raised:
        _run(project, _registry(), document_ids=[old, "doc_nope"])

    assert raised.value.issues == [
        ValidationIssue("document_ids", f"{old}: unknown or superseded"),
        ValidationIssue("document_ids", "doc_nope: unknown or superseded"),
    ]
    assert _event_bytes(project) == before


def test_named_unpromoted_work_refused(project: Project, corpus: None) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        _run(project, _registry(), work_ids=["rf:nope-00000000"])

    assert raised.value.issues == [
        ValidationIssue("work_ids", "rf:nope-00000000: not promoted at title/abstract")
    ]


def test_event_carries_no_document_text(project: Project, corpus: None) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, ARTICLE)
    _run(project, default_converters())
    _run(project, _registry(StubConverter(unavailable=True)))
    [converted] = _events(project, "document.converted")

    markdown = project.library.get(Converted.model_validate(converted.payload).markdown_hash)
    assert SENTENCE in markdown, "the sentence must be real document text for this check"
    for path in project.paths.events_dir.rglob("*"):
        if path.is_file():
            assert SENTENCE not in path.read_bytes(), path.name


def test_library_untracked(project: Project, corpus: None) -> None:
    fetched_document(project, _promoted(project)[0], ARTICLE)
    summary = _run(project, default_converters())

    payload = Converted.model_validate(_events(project, "document.converted")[0].payload)
    library = project.paths.library_dir
    assert project.library.path(payload.markdown_hash).is_relative_to(library)
    assert project.library.path(payload.manifest_hash).is_relative_to(library)
    assert not project.blobs.exists(payload.markdown_hash)
    assert not project.blobs.exists(payload.manifest_hash)
    for path in project.paths.events_dir.rglob("*"):
        if path.is_file():
            assert path.suffix == ".jsonl", path
    assert summary.converted == 1
