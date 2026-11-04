"""`check` and restore of document conversions (plan 2B2, task 5).

A conversion whose Markdown or manifest blob is absent is `library-missing` (warning); one whose
blob no longer hashes to its reference is `library-corrupt` (error). `restore_conversions`
regenerates those blobs with the recorded converter and version, and writes no event.
"""

from factory.model.document import Converted
from factory.services.check import check
from factory.services.context import Project
from factory.services.document_convert import restore_conversions
from tests.document_helpers import fetched_document
from tests.test_document_convert import (
    ARTICLE,
    StubConverter,
    _event_bytes,
    _events,
    _promoted,
    _registry,
    _run,
)


class _Drifted(StubConverter):
    """The same converter version, with output that differs from the recorded Markdown."""

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        markdown, warnings = super().to_markdown(raw, media_type)
        return markdown + "\n\nA drifted paragraph.\n", warnings


def _converted_one(project: Project) -> tuple[str, str, Converted]:
    """Fetch and convert the first promoted work. Returns (work, document, the conversion)."""
    work = _promoted(project)[0]
    document = fetched_document(project, work, ARTICLE)
    _run(project, _registry())
    [event] = _events(project, "document.converted")
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

    summary = restore_conversions(project, _registry())

    assert [(o.status, o.conversion_id) for o in summary.outcomes] == [
        ("restored", conversion.conversion_id)
    ]
    assert summary.restored == 1
    assert summary.failed == 0
    assert (summary.outcomes[0].document_id, summary.outcomes[0].work_id) == (document, work)
    assert project.library.path(conversion.markdown_hash).is_file()
    assert _findings(project, "library-missing") == []
    assert _findings(project, "library-corrupt") == []


def test_restore_replaces_corrupt_blob(project: Project, corpus: None) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.manifest_hash).write_bytes(b"tampered")

    summary = restore_conversions(project, _registry())

    assert [o.status for o in summary.outcomes] == ["restored"]
    assert _findings(project, "library-corrupt") == []
    assert project.library.get(conversion.manifest_hash)


def test_restore_with_other_converter_version_fails_cleanly(project: Project, corpus: None) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.markdown_hash).unlink()

    summary = restore_conversions(project, _registry(StubConverter(version="1.0+other")))

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
    before = _event_bytes(project)

    summary = restore_conversions(project, _registry(_Drifted()))

    assert [(o.status, o.reason) for o in summary.outcomes] == [("failed", "hash-differs")]
    assert not project.library.path(conversion.markdown_hash).exists()
    assert not project.library.path(conversion.manifest_hash).exists()
    assert _event_bytes(project) == before


def test_restore_writes_no_event(project: Project, corpus: None) -> None:
    _, _, conversion = _converted_one(project)
    project.library.path(conversion.markdown_hash).unlink()
    before = _event_bytes(project)

    restore_conversions(project, _registry())

    assert _event_bytes(project) == before
    assert len(_events(project, "document.converted")) == 1


def test_restore_skips_intact_conversions(project: Project, corpus: None) -> None:
    _converted_one(project)
    before = _event_bytes(project)

    summary = restore_conversions(project, _registry())

    assert summary.outcomes == []
    assert summary.restored == 0
    assert _event_bytes(project) == before


def test_no_conversions_no_findings(project: Project, corpus: None) -> None:
    assert _findings(project, "library-missing") == []
    assert _findings(project, "library-corrupt") == []
    assert restore_conversions(project, _registry()).outcomes == []
