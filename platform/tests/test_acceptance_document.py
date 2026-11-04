"""Acceptance for document conversion (plan 2B2): AC 1, 2, 3, 7 (platform part) and 15 (part).

Offline throughout: the corpus is built from the slice-1 and plan 2A helpers, and the converter is
the LaTeXML HTML converter, whose tools are part of the platform. The rebuild check is the slice-1
projection check, applied to the document tables as well.
"""

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.document.anchors import Anchor, AnchorKind
from factory.document.latexml_html import LatexmlHtmlConverter
from factory.document.quotes import quote_in_element
from factory.document.registry import ConverterRegistry, default_converters
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.document import Converted
from factory.model.screening import PassLabel
from factory.services.context import Project, open_project
from factory.services.document_convert import convert_documents
from factory.services.document_read import (
    conversion_manifest,
    document_read,
    resolve_anchor,
)
from factory.services.fulltext import record_supplied_document
from factory.services.project import init_project
from factory.services.screening import open_pass
from tests.document_helpers import (
    ARTICLE,
    event_bytes,
    events_of_type,
    fetched_document,
    promoted_works,
    run_convert,
)
from tests.helpers import SESSION, _setup, install_skill
from tests.test_fulltext_service import _include_all
from tests.test_screening_next import _draw

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

SENTENCE = "Ut enim ad minim veniam"
PDF = b"%PDF-1.4 synthetic"
CELL_ID = re.compile(r"t\d+\.r\d+\.c\d+")


class _BumpedConverter:
    """The LaTeXML HTML converter reporting a newer version, as after a tool upgrade."""

    name = "latexml-html"
    accepts = frozenset({"text/html"})

    def __init__(self) -> None:
        self._inner = LatexmlHtmlConverter()

    def version(self) -> str:
        return self._inner.version() + "+bumped"

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        return self._inner.to_markdown(raw, media_type)


def _sha(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _build_corpus(project: Project, agent: Actor, human: Actor, mock_sources: Any) -> None:
    """The corpus of the `corpus` fixture in conftest, for any project."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)


def _document_tables(project: Project) -> dict[str, list[dict[str, Any]]]:
    """The two document projection tables, in a fixed order, as plain rows."""
    with project.index.connect() as conn:
        conversions = conn.execute(
            text("SELECT * FROM document_conversions ORDER BY conversion_id")
        ).mappings()
        failures = conn.execute(
            text("SELECT * FROM document_failures ORDER BY event_id")
        ).mappings()
        return {
            "document_conversions": [dict(row) for row in conversions],
            "document_failures": [dict(row) for row in failures],
        }


def _first_paragraph_with(project: Project, conversion_id: str, sentence: str) -> Anchor:
    manifest = conversion_manifest(project, conversion_id)
    return next(
        a for a in manifest.anchors if a.kind is AnchorKind.PARAGRAPH and sentence in a.text
    )


# --- AC 2: the same raw bytes and converter give the same hashes and counts ---


def test_conversion_is_deterministic(
    project: Project,
    corpus: None,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
    clock: FixedClock,
    tmp_path: Path,
) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, default_converters())
    [first_event] = events_of_type(project, "document.converted")

    other_settings = Settings(root=tmp_path / "other", user="obd")
    install_skill(other_settings, "rf-screen")
    other = init_project(other_settings, "demo", "pilot", session=SESSION, clock=clock)
    _build_corpus(other, agent, human, mock_sources)
    fetched_document(other, promoted_works(other)[0], ARTICLE)
    run_convert(other, default_converters())
    [second_event] = events_of_type(other, "document.converted")

    first = Converted.model_validate(first_event.payload)
    second = Converted.model_validate(second_event.payload)
    assert first.raw_hash == second.raw_hash == _sha(ARTICLE)
    assert first.markdown_hash == second.markdown_hash
    assert first.manifest_hash == second.manifest_hash
    assert first.counts == second.counts
    assert first.counts[AnchorKind.SECTION.value] > 0


# --- AC 3: a quote verified against the first conversion still verifies after a new version ---


def test_old_quote_still_verifies_after_new_version(project: Project, corpus: None) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    run_convert(project, default_converters())
    [first_event] = events_of_type(project, "document.converted")
    first = Converted.model_validate(first_event.payload)

    paragraph = _first_paragraph_with(project, first.conversion_id, SENTENCE)
    assert quote_in_element(paragraph.text, SENTENCE)

    # A version bump writes a second conversion of the same document.
    summary = convert_documents(project, ConverterRegistry([_BumpedConverter()]))
    assert [o.status for o in summary.outcomes] == ["converted"]
    [_, second_event] = events_of_type(project, "document.converted")
    second = Converted.model_validate(second_event.payload)
    assert second.converter_version != first.converter_version

    # The quote still verifies against the first conversion, by its id.
    anchor = resolve_anchor(project, first.conversion_id, paragraph.id)
    assert quote_in_element(anchor.text, SENTENCE)

    old_page = document_read(project, work_id=work, conversion_id=first.conversion_id)
    assert old_page.markdown_hash == first.markdown_hash
    assert old_page.converter_version == first.converter_version

    new_page = document_read(project, work_id=work)
    assert new_page.conversion_id == second.conversion_id
    assert new_page.converter_version == second.converter_version
    assert new_page.markdown_hash == second.markdown_hash


# --- AC 7 (platform part): a cell anchor resolves to exactly one cell ---


def test_cell_anchor_resolves_to_one_cell(project: Project, corpus: None) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    run_convert(project, default_converters())
    conversion_id = document_read(project, work_id=work).conversion_id

    anchors = conversion_manifest(project, conversion_id).anchors
    cells = [a for a in anchors if a.kind is AnchorKind.CELL]
    assert cells, "the fixture table yields cell anchors"
    target = next(a for a in cells if a.text == "Lorem")
    assert CELL_ID.fullmatch(target.id)

    resolved = resolve_anchor(project, conversion_id, target.id)
    assert resolved == target
    assert resolved.text == "Lorem"

    with pytest.raises(FactoryValidationError) as raised:
        resolve_anchor(project, conversion_id, f"{target.parent}.r99.c99")
    assert [issue.field for issue in raised.value.issues] == ["anchor"]


# --- AC 15 (part): library Markdown and manifest are git-ignored; no event holds the text ---


def test_no_literature_in_tracked_paths(project: Project, corpus: None) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    run_convert(project, default_converters())

    [event] = events_of_type(project, "document.converted")
    payload = Converted.model_validate(event.payload)
    for ref in (payload.markdown_hash, payload.manifest_hash):
        path = project.library.path(ref)
        assert path.is_file()
        relative = path.relative_to(project.paths.root).as_posix()
        ignored = _git_ignored(relative)
        if ignored is None:
            pytest.skip("not a git repository")
        assert ignored, f"{relative} is not git-ignored"

    for path in project.paths.events_dir.rglob("*"):
        if path.is_file():
            assert SENTENCE.encode() not in path.read_bytes(), path.name


def _git_ignored(relative: str) -> bool | None:
    """Whether the repository's ignore rules match `relative`; None if there is no repository."""
    repo = Path(__file__).resolve().parents[2]
    probe = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    check = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "--no-index", relative],
        check=False,
    )
    return check.returncode == 0


# --- Rebuild: the projection from events equals the live projection, document tables included ---


def test_rebuild_from_events_matches(
    project: Project, corpus: None, settings: Settings, clock: FixedClock
) -> None:
    works = promoted_works(project)
    fetched_document(project, works[0], ARTICLE)
    run_convert(project, default_converters())

    # One failure: a PDF document, for which no converter is registered.
    with project.index.exclusive():
        project.index.sync()
        pdf_document = record_supplied_document(
            project,
            works[1],
            content=PDF,
            source_version="v1",
            media_type="application/pdf",
            actor=project.human_actor(),
        )
    assert pdf_document is not None
    run_convert(project, default_converters())
    assert len(events_of_type(project, "document.converted")) == 1
    assert len(events_of_type(project, "document.conversion_failed")) == 1

    before_hash = project.index.state_hash()
    before_tables = _document_tables(project)
    assert before_tables["document_conversions"]
    assert before_tables["document_failures"]
    before_events = event_bytes(project)

    shutil.rmtree(project.paths.dir / ".index")
    fresh = open_project(settings, "demo", session=SESSION, clock=clock)
    assert fresh.index.rebuild() == before_hash
    assert _document_tables(fresh) == before_tables
    assert event_bytes(fresh) == before_events
