"""Chat read service: quote verification and work outline (plan chat T4a).

Documents are converted by a pass-through converter, so each test fixes the anchored Markdown.
"""

import pytest

from factory.document.anchors import AnchorKind
from factory.errors import FactoryValidationError
from factory.services.chat_read import VerifyItem, chat_sections, chat_verify
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import document_read
from tests.document_helpers import fetched_document
from tests.test_document_read import _convert, _promoted

MD = b"""# Study

Opening sentence of the study.

## 1 Method

Method paragraph with team\\_size and Planning &amp; Control.

Second method paragraph.

### 1.1 Detail

Detail paragraph.

## 2 Results

| Name | Value |
| --- | --- |
| alpha | 0.5 |
| beta | 0.9 |

Closing sentence.
"""


def _setup(project: Project) -> tuple[str, str]:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)
    return work, document_read(project, work_id=work).conversion_id


def _anchor_with(project: Project, conversion: str, needle: str) -> str:
    manifest = conversion_manifest(project, conversion)
    return next(
        a.id for a in manifest.anchors if needle in a.text and a.kind is not AnchorKind.SECTION
    )


@pytest.mark.usefixtures("corpus")
def test_accepts_quotes_as_served(project: Project) -> None:
    work, conv = _setup(project)
    a = _anchor_with(project, conv, "Method paragraph")
    items = [
        VerifyItem(work, a, "Method paragraph with"),
        VerifyItem(work, a, "team\\_size"),
        VerifyItem(work, a, "team_size"),
        VerifyItem(work, a, "Planning &amp; Control"),
        VerifyItem(work, a, "Planning & Control"),
    ]
    results = chat_verify(project, items)
    assert [r.status for r in results] == ["accepted"] * 5
    assert all(r.conversion_id == conv and r.markdown_hash for r in results)


@pytest.mark.usefixtures("corpus")
def test_refusals_and_order(project: Project) -> None:
    work, conv = _setup(project)
    a = _anchor_with(project, conv, "Method paragraph")
    items = [
        VerifyItem(work, a, "not in the paragraph"),
        VerifyItem(work, "s9.p9", "x"),
        VerifyItem("W-nope", a, "x"),
        VerifyItem(work, a, "Method", conversion_id="cv-foreign"),
        VerifyItem(work, a, "Method"),
    ]
    results = chat_verify(project, items)
    assert [r.status for r in results] == [
        "quote-not-in-anchor",
        "anchor-missing",
        "unknown-work",
        "no-conversion",
        "accepted",
    ]
    assert [r.item for r in results] == items
    assert results[2].conversion_id is None and results[2].markdown_hash is None
    assert results[3].conversion_id is None
    assert results[0].conversion_id == conv


@pytest.mark.usefixtures("corpus")
def test_table_cell_anchor(project: Project) -> None:
    work, conv = _setup(project)
    manifest = conversion_manifest(project, conv)
    cell = next(a for a in manifest.anchors if a.kind is AnchorKind.CELL and a.text == "0.9")
    results = chat_verify(
        project,
        [VerifyItem(work, cell.id, "0.9", conv), VerifyItem(work, cell.id, "0.5", conv)],
    )
    assert [r.status for r in results] == ["accepted", "quote-not-in-anchor"]


@pytest.mark.usefixtures("corpus")
def test_sections_outline(project: Project) -> None:
    work, conv = _setup(project)
    outline = chat_sections(project, work)
    assert outline.work_id == work and outline.conversion_id == conv and outline.markdown_hash
    heads = [(s.heading, s.depth) for s in outline.sections]
    assert heads == [("Study", 1), ("1 Method", 1), ("1.1 Detail", 2), ("2 Results", 1)]
    by = {s.heading: s for s in outline.sections}
    assert by["1 Method"].paragraphs == 2
    assert by["1 Method"].words == 8 + 3
    assert by["1.1 Detail"].paragraphs == 1
    assert by["2 Results"].paragraphs == 1
    assert outline == chat_sections(project, work, conv)


@pytest.mark.usefixtures("corpus")
def test_sections_refusals(project: Project) -> None:
    work, _ = _setup(project)
    with pytest.raises(FactoryValidationError) as exc:
        chat_sections(project, "W-nope")
    assert exc.value.issues[0].field == "work_id"
    with pytest.raises(FactoryValidationError) as exc:
        chat_sections(project, work, "cv-foreign")
    assert exc.value.issues[0].field == "conversion_id"


@pytest.mark.usefixtures("corpus")
def test_section_headings_are_scrubbed(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from factory.services import chat_read as cr

    work, _conv = _setup(project)
    monkeypatch.setattr(cr, "held_out_tokens", lambda _p, include_work_ids=True: {"Detail"})
    heads = [s.heading for s in chat_sections(project, work).sections]
    assert heads == ["Study", "1 Method", "1.1 [withheld]", "2 Results"]


@pytest.mark.usefixtures("corpus")
def test_whitespace_runs_in_element_and_quote_are_normalised(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, b"## 1 Method\n\nLine one of\nthe  claim   text here.\n")
    _convert(project)
    conv = document_read(project, work_id=work).conversion_id
    a = _anchor_with(project, conv, "claim")
    # a digest quote has its whitespace collapsed; the element holds a newline and double spaces
    items = [
        VerifyItem(work, a, "Line one of the claim text here."),
        VerifyItem(work, a, "of\n  the claim"),
    ]
    assert [r.status for r in chat_verify(project, items)] == ["accepted", "accepted"]
