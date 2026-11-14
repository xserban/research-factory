"""Document conversion service: events, idempotence, failures and scope (plan 2B2, task 3).

Each conversion is an event with hashes and counts; Markdown and manifest bytes live in the
project library. A repeat of the same converter version writes nothing; a failure is an event
with a fixed reason and never the error text.
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

from factory.document.anchors import AnchorKind, ManifestError
from factory.document.converter import convert
from factory.document.latexml_html import LatexmlHtmlConverter
from factory.document.registry import default_converters
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.document import Converted, FailureReason
from factory.model.fulltext import AttemptOutcome, Route
from factory.services.context import Project
from factory.services.document_convert import (
    ConvertSummary,
    convert_or_restore,
    document_status,
)
from factory.services.fulltext import fetch_fulltext, record_supplied_document
from factory.sources.fulltext.base import not_retrieved
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    event_bytes,
    events_of_type,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.route_helpers import StubRoute, always, retrieved

SENTENCE = b"Ut enim ad minim veniam"
MARKER = b"FAIL-ME"
PDF = b"%PDF-1.4 synthetic"


def _sha(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _statuses(summary: ConvertSummary) -> list[str]:
    return [outcome.status for outcome in summary.outcomes]


def _git_ignored(relative: str) -> bool | None:
    """Whether the repository's ignore rules match `relative`; None if there is no repository."""
    root = Path(__file__).resolve().parents[2]
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    check = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--no-index", relative],
        check=False,
    )
    return check.returncode == 0


def _strip_library(project: Project) -> None:
    for path in project.paths.library_dir.rglob("*"):
        if path.is_file():
            path.unlink()


def test_converts_html_document(project: Project, corpus: None) -> None:
    work = promoted_works(project)[0]
    document = fetched_document(project, work, ARTICLE)

    summary = run_convert(project, default_converters())

    direct = convert(LatexmlHtmlConverter(), ARTICLE, "text/html")
    [event] = events_of_type(project, "document.converted")
    payload = Converted.model_validate(event.payload)
    assert event.actor == project.human_actor()
    assert payload.document_id == document
    assert payload.converter == direct.converter
    assert payload.converter_version == direct.converter_version
    assert payload.markdown_hash == direct.markdown_hash
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
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry())
    before = event_bytes(project)
    library_before = {p for p in project.paths.library_dir.rglob("*") if p.is_file()}

    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["unchanged"]
    assert summary.unchanged == 1
    assert summary.outcomes[0].conversion_id is None
    assert event_bytes(project) == before
    assert {p for p in project.paths.library_dir.rglob("*") if p.is_file()} == library_before


def test_plain_run_skips_an_older_version_and_reports_it(project: Project, corpus: None) -> None:
    """IDEA-48: after a version bump a plain run leaves the document alone and reports it."""
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry(StubConverter(version="1.0+a")))
    before = event_bytes(project)

    summary = run_convert(project, make_registry(StubConverter(version="1.0+b")))

    assert _statuses(summary) == ["outdated"]
    assert summary.outdated == 1
    assert summary.converted == 0
    assert summary.outcomes[0].conversion_id is None
    assert summary.outcomes[0].reason == "other-converter-version"
    assert event_bytes(project) == before
    assert len(events_of_type(project, "document.converted")) == 1


def test_upgrade_reconverts_an_older_version_and_keeps_the_old(
    project: Project, corpus: None
) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry(StubConverter(version="1.0+a")))
    old = Converted.model_validate(events_of_type(project, "document.converted")[0].payload)

    summary = run_convert(project, make_registry(StubConverter(version="1.0+b")), upgrade=True)

    assert _statuses(summary) == ["converted"]
    assert summary.outdated == 0
    assert summary.outcomes[0].conversion_id is not None
    assert project.library.exists(old.markdown_hash) and project.library.exists(old.manifest_hash)
    versions = [
        Converted.model_validate(e.payload).converter_version
        for e in events_of_type(project, "document.converted")
    ]
    assert versions == ["1.0+a", "1.0+b"]


def test_current_version_is_unchanged_with_or_without_upgrade(
    project: Project, corpus: None
) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry(StubConverter(version="1.0+a")))
    before = event_bytes(project)

    plain = run_convert(project, make_registry(StubConverter(version="1.0+a")))
    upgraded = run_convert(project, make_registry(StubConverter(version="1.0+a")), upgrade=True)

    assert _statuses(plain) == ["unchanged"]
    assert _statuses(upgraded) == ["unchanged"]
    assert event_bytes(project) == before


def test_version_bump_writes_second_conversion(project: Project, corpus: None) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry(StubConverter(version="1.0+a")))

    summary = run_convert(project, make_registry(StubConverter(version="1.0+b")), upgrade=True)

    assert _statuses(summary) == ["converted"]
    versions = [
        Converted.model_validate(e.payload).converter_version
        for e in events_of_type(project, "document.converted")
    ]
    assert versions == ["1.0+a", "1.0+b"]


def test_version_bump_keeps_the_old_conversion_referenced(project: Project, corpus: None) -> None:
    """A converter version bump (IDEA-48) adds a conversion; the old one, its events and its blobs
    stay, so anchors cited against it still resolve. Nothing is replaced or deleted."""
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry(StubConverter(version="1.0+a")))
    old = Converted.model_validate(events_of_type(project, "document.converted")[0].payload)
    before = event_bytes(project)

    run_convert(project, make_registry(StubConverter(version="1.0+b")), upgrade=True)

    after = event_bytes(project)
    assert all(after[path].startswith(data) for path, data in before.items())  # append-only
    assert project.library.exists(old.markdown_hash) and project.library.exists(old.manifest_hash)
    assert len(events_of_type(project, "document.converted")) == 2


def test_no_converter_records_failure(project: Project, corpus: None) -> None:
    work = promoted_works(project)[0]
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

    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["failed"]
    assert summary.failed == 1
    assert summary.outcomes[0].reason == "no-converter"
    assert summary.outcomes[0].conversion_id is None
    [event] = events_of_type(project, "document.conversion_failed")
    assert event.payload == {
        "document_id": document,
        "converter": None,
        "reason": "no-converter",
        "error_class": None,
    }


def test_converter_unavailable_records_failure(project: Project, corpus: None) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)

    summary = run_convert(project, make_registry(StubConverter(unavailable=True)))

    assert _statuses(summary) == ["failed"]
    assert summary.outcomes[0].reason == "converter-unavailable"
    [event] = events_of_type(project, "document.conversion_failed")
    assert event.payload["reason"] == "converter-unavailable"
    assert event.payload["converter"] == "latexml-html"
    assert event.payload["error_class"] is None
    assert events_of_type(project, "document.converted") == []


def test_manifest_error_records_failure_and_batch_continues(project: Project, corpus: None) -> None:
    """Review Focus 1: the first of two documents raises, and the second still converts."""
    first_work, second_work = promoted_works(project)[0], promoted_works(project)[1]
    bad = fetched_document(project, first_work, ARTICLE + b"<!-- " + MARKER + b" -->")
    good = fetched_document(project, second_work, ARTICLE)
    registry = make_registry(
        StubConverter(fail_on=MARKER, error=ManifestError("anchor grammar broken: secret text"))
    )

    summary = run_convert(project, registry)

    assert _statuses(summary) == ["failed", "converted"]
    assert summary.failed == 1
    assert summary.converted == 1
    assert summary.outcomes[0].document_id == bad
    assert summary.outcomes[0].reason == "conversion-error"
    [failure] = events_of_type(project, "document.conversion_failed")
    assert failure.payload == {
        "document_id": bad,
        "converter": "latexml-html",
        "reason": "conversion-error",
        "error_class": "ManifestError",
    }
    [converted] = events_of_type(project, "document.converted")
    assert converted.payload["document_id"] == good


def test_raw_missing_reports_without_event(project: Project, corpus: None) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    _strip_library(project)
    before = event_bytes(project)

    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["raw-missing"]
    assert summary.raw_missing == 1
    assert summary.outcomes[0].conversion_id is None
    assert event_bytes(project) == before
    assert not [p for p in project.paths.library_dir.rglob("*") if p.is_file()]


def test_named_unknown_document_refused_and_writes_nothing(project: Project, corpus: None) -> None:
    work = promoted_works(project)[0]
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
    before = event_bytes(project)

    with pytest.raises(FactoryValidationError) as raised:
        run_convert(project, make_registry(), document_ids=[old, "doc_nope"])

    assert raised.value.issues == [
        ValidationIssue("document_ids", f"{old}: unknown or superseded"),
        ValidationIssue("document_ids", "doc_nope: unknown or superseded"),
    ]
    assert event_bytes(project) == before


def test_named_unpromoted_work_refused(project: Project, corpus: None) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        run_convert(project, make_registry(), work_ids=["rf:nope-00000000"])

    assert raised.value.issues == [
        ValidationIssue("work_ids", "rf:nope-00000000: not promoted at title/abstract")
    ]


def test_event_carries_no_document_text(project: Project, corpus: None) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    run_convert(project, default_converters())
    run_convert(project, make_registry(StubConverter(unavailable=True)))
    [converted] = events_of_type(project, "document.converted")

    markdown = project.library.get(Converted.model_validate(converted.payload).markdown_hash)
    assert SENTENCE in markdown, "the sentence must be real document text for this check"
    for path in project.paths.events_dir.rglob("*"):
        if path.is_file():
            assert SENTENCE not in path.read_bytes(), path.name


def test_library_untracked(project: Project, corpus: None) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    summary = run_convert(project, default_converters())

    payload = Converted.model_validate(events_of_type(project, "document.converted")[0].payload)
    library = project.paths.library_dir
    assert project.library.path(payload.markdown_hash).is_relative_to(library)
    assert project.library.path(payload.manifest_hash).is_relative_to(library)
    assert not project.blobs.exists(payload.markdown_hash)
    assert not project.blobs.exists(payload.manifest_hash)
    relative = project.library.path(payload.markdown_hash).relative_to(project.paths.root)
    ignored = _git_ignored(relative.as_posix())
    if ignored is None:
        pytest.skip("not a git repository")
    assert ignored, f"{relative} is not ignored by git"
    for path in project.paths.events_dir.rglob("*"):
        if path.is_file():
            assert path.suffix == ".jsonl", path
    assert summary.converted == 1


def test_already_converted_with_raw_removed_is_unchanged(project: Project, corpus: None) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry())
    before = event_bytes(project)
    _strip_library(project)

    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["unchanged"]
    assert event_bytes(project) == before


def test_no_converter_with_raw_removed_is_raw_missing(project: Project, corpus: None) -> None:
    with project.index.exclusive():
        project.index.sync()
        record_supplied_document(
            project,
            promoted_works(project)[0],
            content=PDF,
            source_version="v1",
            media_type="application/pdf",
            actor=project.human_actor(),
        )
    _strip_library(project)
    before = event_bytes(project)

    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["raw-missing"]
    assert event_bytes(project) == before


def test_unavailable_converter_with_raw_removed_is_raw_missing(
    project: Project, corpus: None
) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    _strip_library(project)
    before = event_bytes(project)

    summary = run_convert(project, make_registry(StubConverter(unavailable=True)))

    assert _statuses(summary) == ["raw-missing"]
    assert event_bytes(project) == before


def test_overlong_and_excess_warnings_are_capped(project: Project, corpus: None) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    extra = tuple(f"w{index} " + "x" * 300 for index in range(60))

    summary = run_convert(project, make_registry(StubConverter(extra_warnings=extra)))

    assert _statuses(summary) == ["converted"]
    base = convert(LatexmlHtmlConverter(), ARTICLE, "text/html").warnings
    expected = [w[:200] for w in (*base, *extra)][:50]
    [event] = events_of_type(project, "document.converted")
    assert event.payload["warnings"] == expected
    assert len(expected) == 50


def test_scope_excludes_unpromoted_work_and_intersects(
    project: Project, corpus_leaving: str
) -> None:
    leave = corpus_leaving
    promoted = promoted_works(project)
    assert leave not in promoted
    live = fetched_document(project, promoted[0], ARTICLE)
    with project.index.exclusive():
        project.index.sync()
        stray = record_supplied_document(
            project,
            leave,
            content=ARTICLE,
            source_version="v1",
            media_type="text/html",
            actor=project.human_actor(),
        )
    assert stray is not None

    both = run_convert(project, make_registry(), work_ids=[promoted[0]], document_ids=[stray])
    assert both.outcomes == []

    default = run_convert(project, make_registry())
    assert [o.document_id for o in default.outcomes] == [live]

    named = run_convert(project, make_registry(), document_ids=[stray])
    assert [o.document_id for o in named.outcomes] == [stray]


def test_corrupt_raw_is_raw_missing_and_batch_continues(project: Project, corpus: None) -> None:
    """A raw blob that no longer hashes to its reference gives `raw-missing` for its document,
    with no event, and the next document still converts."""
    first_work, second_work = promoted_works(project)[0], promoted_works(project)[1]
    corrupt = ARTICLE + b"<!-- corrupt -->"
    fetched_document(project, first_work, corrupt)
    fetched_document(project, second_work, ARTICLE)
    project.library.path(_sha(corrupt)).write_bytes(b"tampered")

    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["raw-missing", "converted"]
    assert summary.raw_missing == 1
    assert summary.converted == 1
    assert summary.outcomes[0].conversion_id is None
    assert [e.payload["document_id"] for e in events_of_type(project, "document.converted")] == [
        summary.outcomes[1].document_id
    ]
    assert events_of_type(project, "document.conversion_failed") == []


def test_status_reports_latest_conversion_and_failure(project: Project, corpus: None) -> None:
    """Status is read-only; a failed document shows its failure, and a converted one its latest
    conversion's converter, version and counts, with the failure it recorded before."""
    work = promoted_works(project)[0]
    document = fetched_document(project, work, ARTICLE)
    run_convert(project, make_registry(StubConverter(unavailable=True)))
    before = event_bytes(project)

    [entry] = document_status(project).documents
    assert entry.document_id == document and entry.work_id == work
    assert entry.converted is False and entry.conversion_id is None
    assert entry.converter is None and entry.counts is None
    assert entry.latest_failure is FailureReason.CONVERTER_UNAVAILABLE
    assert event_bytes(project) == before

    run_convert(project, make_registry())
    direct = convert(LatexmlHtmlConverter(), ARTICLE, "text/html")
    [entry] = document_status(project).documents
    assert entry.converted is True
    assert entry.converter == direct.converter
    assert entry.converter_version == "1.0+stub"
    assert entry.counts == {
        kind.value: sum(1 for a in direct.manifest.anchors if a.kind is kind) for kind in AnchorKind
    }
    assert entry.latest_failure is FailureReason.CONVERTER_UNAVAILABLE
    assert event_bytes(project) != before


def test_convert_or_restore_refuses_a_scope_with_restore(project: Project, corpus: None) -> None:
    """The restore rule lives in the service: refused before anything is read or written."""
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    before = event_bytes(project)

    with pytest.raises(FactoryValidationError) as raised:
        convert_or_restore(
            project, make_registry(), restore=True, work_ids=[work], document_ids=None
        )

    assert [(i.field, i.reason) for i in raised.value.issues] == [
        ("restore", "takes no --work or --document")
    ]
    assert event_bytes(project) == before


def test_store_error_is_failed_outcome_without_event_and_batch_continues(
    project: Project, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first library write raises OSError: that document is `failed` with `store-error` and
    no event, the next document still converts, and a later run converts the first."""
    first_work, second_work = promoted_works(project)[0], promoted_works(project)[1]
    first = fetched_document(project, first_work, ARTICLE)
    second_html = ARTICLE.replace(SENTENCE, b"Sed ut perspiciatis unde")
    second = fetched_document(project, second_work, second_html)
    real_put = project.library.put
    calls: list[bytes] = []

    def put_first_failing(data: bytes) -> str:
        calls.append(data)
        if len(calls) == 1:
            raise OSError("disk full")
        return real_put(data)

    monkeypatch.setattr(project.library, "put", put_first_failing)
    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["failed", "converted"]
    assert summary.outcomes[0].reason == "store-error"
    assert summary.outcomes[0].conversion_id is None
    assert summary.failed == 1
    assert summary.converted == 1
    assert [e.payload["document_id"] for e in events_of_type(project, "document.converted")] == [
        second
    ]
    assert events_of_type(project, "document.conversion_failed") == []

    monkeypatch.undo()
    rerun = run_convert(project, make_registry())

    assert _statuses(rerun) == ["converted", "unchanged"]
    assert rerun.outcomes[0].document_id == first


def test_corrupt_blob_at_markdown_path_is_replaced_by_convert(
    project: Project, corpus: None
) -> None:
    """A corrupt file already at the Markdown's hash path is replaced, not reused."""
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    direct = convert(LatexmlHtmlConverter(), ARTICLE, "text/html")
    path = project.library.path(direct.markdown_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"tampered")

    summary = run_convert(project, make_registry())

    assert _statuses(summary) == ["converted"]
    assert project.library.get(direct.markdown_hash) == direct.markdown.encode("utf-8")
