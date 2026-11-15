"""Re-anchoring recorded conversions: a new conversion, the old one kept and still valid."""

from functools import partial

import pytest

from factory.document.anchorise import anchorise
from factory.document.converter import convert
from factory.model.document import Converted
from factory.services import document_convert, reanchor
from factory.services.context import Project
from factory.services.document_read import document_read
from factory.services.reanchor import reanchor_conversions
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

MARKDOWN = (
    "# 1 Intro\n\nBody.\n\n- first item here\n- second item here\n\n"
    "# References\n\n"
    "1. Guan, Y. et al. Drug repurposing (2025). 2. Penades, J. et al. AI Cell (2025).\n"
)


class ListConverter(StubConverter):
    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        return MARKDOWN, ()


def _convert_v1(project: Project, monkeypatch: pytest.MonkeyPatch) -> str:
    """Record a conversion under the legacy anchoring rules; return its document id."""
    document = fetched_document(project, promoted_works(project)[0], ARTICLE)
    legacy = partial(convert, anchor_version=1)
    monkeypatch.setattr(document_convert, "convert", legacy)
    run_convert(project, make_registry(ListConverter()))
    monkeypatch.undo()
    return document


def test_reanchor_records_a_new_conversion_and_keeps_the_old(
    project: Project, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert_v1(project, monkeypatch)
    [old_event] = events_of_type(project, "document.converted")
    old = Converted.model_validate(old_event.payload)
    assert "+anchors" not in old.converter_version
    stored = project.library.get(old.markdown_hash).decode("utf-8")
    assert "- first item here" in stored  # legacy: list unanchored
    assert anchorise(stored, version=1) == stored  # byte-for-byte soundness

    summary = reanchor_conversions(project, converter="latexml-html")

    assert summary.converted == 1
    new_events = events_of_type(project, "document.converted")
    assert len(new_events) == 2
    assert new_events[0].id == old_event.id  # the old event is untouched
    new = Converted.model_validate(new_events[1].payload)
    assert new.converter_version == old.converter_version + "+anchors2"
    assert new.raw_hash == old.raw_hash and new.warnings == old.warnings
    assert project.library.get(old.markdown_hash).decode("utf-8") == stored
    new_md = project.library.get(new.markdown_hash).decode("utf-8")
    assert new_md == anchorise(MARKDOWN) and '<a id="b2"></a>\n[2] Penades' in new_md
    # The new conversion is the one read.
    work = promoted_works(project)[0]
    page = document_read(project, work_id=work)
    assert page.conversion_id == new.conversion_id


def test_reanchor_twice_changes_nothing(
    project: Project, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert_v1(project, monkeypatch)
    reanchor_conversions(project)
    before = event_bytes(project)

    summary = reanchor_conversions(project)

    assert summary.unchanged == 1 and summary.converted == 0
    assert event_bytes(project) == before


def test_converter_filter_and_current_conversions_are_unchanged(
    project: Project, corpus: None
) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, make_registry())
    before = event_bytes(project)

    assert reanchor_conversions(project, converter="docling").outcomes == []
    assert reanchor_conversions(project).unchanged == 1
    assert event_bytes(project) == before


def test_dry_run_reports_but_writes_nothing(
    project: Project, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert_v1(project, monkeypatch)
    before = event_bytes(project)

    summary = reanchor_conversions(project, dry_run=True)

    assert summary.converted == 1
    assert summary.outcomes[0].conversion_id is None
    assert event_bytes(project) == before
    assert reanchor_conversions(project).converted == 1  # the real run still has work to do


def test_a_bad_document_fails_without_aborting_the_run(
    project: Project, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert_v1(project, monkeypatch)
    before = event_bytes(project)

    def boom(markdown: str) -> None:
        raise ValueError("bad manifest")

    monkeypatch.setattr(reanchor, "parse_manifest", boom)
    summary = reanchor_conversions(project)

    assert summary.failed == 1 and summary.converted == 0
    assert summary.outcomes[0].reason == "conversion-error"
    assert event_bytes(project) == before
