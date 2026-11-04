"""`check` and restore of document conversions (plan 2B2, task 5).

A conversion whose Markdown or manifest blob is absent is `library-missing` (warning); one whose
blob no longer hashes to its reference is `library-corrupt` (error). `restore_conversions`
regenerates those blobs with the recorded converter and version, and writes no event.
"""

from pytest import MonkeyPatch

from factory.model.document import Converted
from factory.services.check import check
from factory.services.context import Project
from factory.services.document_convert import restore_conversions
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

OTHER = ARTICLE.replace(b"Ut enim ad minim veniam", b"Sed ut perspiciatis unde")
"""The same article with one sentence changed: its Markdown and blobs differ from ARTICLE's."""


class _Drifted(StubConverter):
    """The same converter version, with output that differs from the recorded Markdown."""

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        markdown, warnings = super().to_markdown(raw, media_type)
        return markdown + "\n\nA drifted paragraph.\n", warnings


def _converted_one(project: Project) -> tuple[str, str, Converted]:
    """Fetch and convert the first promoted work. Returns (work, document, the conversion)."""
    work = promoted_works(project)[0]
    document = fetched_document(project, work, ARTICLE)
    run_convert(project, make_registry())
    [event] = events_of_type(project, "document.converted")
    return work, document, Converted.model_validate(event.payload)


def _findings(project: Project, code: str) -> list[tuple[str, list[str]]]:
    return [(f.severity, f.refs) for f in check(project).findings if f.code == code]


def test_check_warns_on_missing_markdown(project: Project, corpus: None) -> None:
    work, document, conversion = _converted_one(project)
    assert _findings(project, "library-missing") == []
    project.library.path(conversion.markdown_hash).unlink()

    assert _findings(project, "library-missing") == [
        ("warning", [document, work, conversion.conversion_id])
    ]
    assert _findings(project, "library-corrupt") == []


def test_check_errors_on_corrupt_manifest(project: Project, corpus: None) -> None:
    work, document, conversion = _converted_one(project)
    project.library.path(conversion.manifest_hash).write_bytes(b"tampered")

    assert _findings(project, "library-corrupt") == [
        ("error", [document, work, conversion.conversion_id])
    ]
    assert _findings(project, "library-missing") == []
    assert not check(project).ok


def test_restore_regenerates_same_hash(project: Project, corpus: None) -> None:
    work, document, conversion = _converted_one(project)
    project.library.path(conversion.markdown_hash).unlink()
    assert _findings(project, "library-missing") != []

    summary = restore_conversions(project, make_registry())

    assert [(o.status, o.conversion_id) for o in summary.outcomes] == [
        ("restored", conversion.conversion_id)
    ]
    assert summary.restored == 1
    assert summary.failed == 0
    assert (summary.outcomes[0].document_id, summary.outcomes[0].work_id) == (document, work)
    assert project.library.get(conversion.markdown_hash)
    assert project.library.get(conversion.manifest_hash)
    assert _findings(project, "library-missing") == []
    assert _findings(project, "library-corrupt") == []


def test_restore_replaces_corrupt_blob(project: Project, corpus: None) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.manifest_hash).write_bytes(b"tampered")

    summary = restore_conversions(project, make_registry())

    assert [o.status for o in summary.outcomes] == ["restored"]
    assert _findings(project, "library-corrupt") == []
    assert project.library.get(conversion.manifest_hash)


def test_restore_with_other_converter_version_fails_cleanly(project: Project, corpus: None) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.markdown_hash).unlink()

    summary = restore_conversions(project, make_registry(StubConverter(version="1.0+other")))

    assert [(o.status, o.reason, o.conversion_id) for o in summary.outcomes] == [
        ("failed", "version-unavailable", None)
    ]
    assert summary.failed == 1
    assert summary.restored == 0
    assert not project.library.path(conversion.markdown_hash).exists()
    assert _findings(project, "library-missing") != []


def test_restore_with_drifted_output_fails_and_stores_nothing(
    project: Project, corpus: None
) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.markdown_hash).unlink()
    project.library.path(conversion.manifest_hash).unlink()
    before = event_bytes(project)

    summary = restore_conversions(project, make_registry(_Drifted()))

    assert [(o.status, o.reason) for o in summary.outcomes] == [("failed", "hash-differs")]
    assert not project.library.path(conversion.markdown_hash).exists()
    assert not project.library.path(conversion.manifest_hash).exists()
    assert event_bytes(project) == before


def test_restore_writes_no_event(project: Project, corpus: None) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.markdown_hash).unlink()
    before = event_bytes(project)

    restore_conversions(project, make_registry())

    assert event_bytes(project) == before
    assert len(events_of_type(project, "document.converted")) == 1


def test_restore_skips_intact_conversions(project: Project, corpus: None) -> None:
    _converted_one(project)
    before = event_bytes(project)

    summary = restore_conversions(project, make_registry())

    assert summary.outcomes == []
    assert summary.restored == 0
    assert event_bytes(project) == before


def test_no_conversions_no_findings(project: Project, corpus: None) -> None:
    assert _findings(project, "library-missing") == []
    assert _findings(project, "library-corrupt") == []
    assert restore_conversions(project, make_registry()).outcomes == []


def test_restore_both_blobs_missing(project: Project, corpus: None) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.markdown_hash).unlink()
    project.library.path(conversion.manifest_hash).unlink()

    summary = restore_conversions(project, make_registry())

    assert [o.status for o in summary.outcomes] == ["restored"]
    assert project.library.get(conversion.markdown_hash)
    assert project.library.get(conversion.manifest_hash)


def test_restore_batch_continues_past_store_error(
    project: Project, corpus: None, monkeypatch: MonkeyPatch
) -> None:
    """The first store fails once with an OSError: that conversion is `failed` with
    `store-error`, nothing from it is stored under a new record, and the second is restored. A
    rerun repairs the first."""
    first_work, second_work = promoted_works(project)[0], promoted_works(project)[1]
    fetched_document(project, first_work, ARTICLE)
    fetched_document(project, second_work, OTHER)
    run_convert(project, make_registry())
    conversions = [
        Converted.model_validate(e.payload) for e in events_of_type(project, "document.converted")
    ]
    for conversion in conversions:
        project.library.path(conversion.markdown_hash).unlink()
    real_put = project.library.put
    failures: list[bytes] = []

    def put_once_failing(data: bytes) -> str:
        if not failures:
            failures.append(data)
            raise OSError("disk full")
        return real_put(data)

    monkeypatch.setattr(project.library, "put", put_once_failing)
    first, second = conversions
    assert first.markdown_hash != second.markdown_hash
    summary = restore_conversions(project, make_registry())

    assert [(o.status, o.reason, o.conversion_id) for o in summary.outcomes] == [
        ("failed", "store-error", None),
        ("restored", None, second.conversion_id),
    ]
    assert summary.failed == 1
    assert summary.restored == 1
    assert not project.library.path(first.markdown_hash).exists()

    monkeypatch.undo()
    rerun = restore_conversions(project, make_registry())

    assert [(o.status, o.conversion_id) for o in rerun.outcomes] == [
        ("restored", first.conversion_id)
    ]
    assert project.library.get(first.markdown_hash)
    assert project.library.get(first.manifest_hash)


def test_restore_corrupt_raw_is_raw_missing_and_batch_continues(
    project: Project, corpus: None
) -> None:
    first_work, second_work = promoted_works(project)[0], promoted_works(project)[1]
    fetched_document(project, first_work, ARTICLE)
    fetched_document(project, second_work, OTHER)
    run_convert(project, make_registry())
    first, second = [
        Converted.model_validate(e.payload) for e in events_of_type(project, "document.converted")
    ]
    assert first.markdown_hash != second.markdown_hash
    for conversion in (first, second):
        project.library.path(conversion.markdown_hash).unlink()
    project.library.path(first.raw_hash).write_bytes(b"tampered")
    before = event_bytes(project)

    summary = restore_conversions(project, make_registry())

    assert [(o.status, o.conversion_id) for o in summary.outcomes] == [
        ("raw-missing", None),
        ("restored", second.conversion_id),
    ]
    assert summary.raw_missing == 1
    assert event_bytes(project) == before
