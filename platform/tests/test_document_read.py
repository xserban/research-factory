"""Document read service: default document, paging, gate, blobs and anchors (plan 2B2, task 4).

The documents here are converted by a pass-through converter, so each test controls the anchored
Markdown exactly. Anchor ids are taken from the manifest, never written by hand.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.document.anchorise import stamp_version
from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.document.converter import convert
from factory.document.registry import ConverterRegistry
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.fulltext import Route
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_convert import convert_documents
from factory.services.document_read import (
    Segment,
    _page,
    conversion_manifest,
    document_read,
    resolve_anchor,
)
from factory.services.fulltext import fetch_fulltext, record_supplied_document
from tests.document_helpers import excluded_after_conversion, fetched_document
from tests.route_helpers import StubRoute, always, retrieved

MD = b"""# Study

Opening sentence of the study.

## 1 Method

Method paragraph.

## 2 Results

| Name | Value |
| --- | --- |
| alpha | 0.5 |
| beta | 0.9 |

Closing sentence.
"""
MD_OTHER = b"# Other\n\nA different paragraph from the other route.\n"


class PassThroughConverter:
    """Reads the raw bytes as Markdown, so a test fixes the anchored document exactly."""

    name = "passthrough"
    accepts = frozenset({"text/html"})

    def __init__(self, version: str = "1.0") -> None:
        self._version = version

    def version(self) -> str:
        return self._version

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        return raw.decode("utf-8"), ()


def _registry(version: str = "1.0") -> ConverterRegistry:
    return ConverterRegistry([PassThroughConverter(version)])


def _promoted(project: Project) -> list[str]:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _convert(project: Project, version: str = "1.0", *, upgrade: bool = False) -> str | None:
    """Convert everything in scope with `version`; return the first new conversion id, if any.
    `upgrade` re-converts documents whose latest conversion is an older version (IDEA-48)."""
    summary = convert_documents(project, _registry(version), upgrade=upgrade)
    converted = [o.conversion_id for o in summary.outcomes if o.conversion_id is not None]
    return converted[0] if converted else None


def _fetch_only(project: Project, work_id: str, route: Route, content: bytes) -> str:
    """Fetch `content` on one route only, so a second document can join an existing one."""
    routes = {route: StubRoute(route, always(retrieved(route, content)))}
    summary = fetch_fulltext(project, routes=routes, work_ids=[work_id], only=[route])
    documents = [doc for entry in summary.works for doc in entry.documents]
    assert len(documents) == 1, documents
    return documents[0]


def _manifest(project: Project, conversion_id: str) -> Manifest:
    return conversion_manifest(project, conversion_id)


def _non_cell_ids(manifest: Manifest) -> list[str]:
    return [a.id for a in manifest.anchors if a.kind is not AnchorKind.CELL]


def _strip_blob(project: Project, ref: str) -> None:
    project.library.path(ref).unlink()


def _snapshot(project: Project) -> tuple[dict[Path, bytes], set[Path]]:
    events = {p: p.read_bytes() for p in sorted(project.paths.events_dir.rglob("*")) if p.is_file()}
    library = {p for p in project.paths.library_dir.rglob("*") if p.is_file()}
    return events, library


@pytest.mark.usefixtures("corpus")
def test_default_document_follows_route_order(project: Project) -> None:
    """The oa-pdf document is fetched first and the arXiv HTML document second, so event order
    favours oa-pdf; route order must still pick arXiv HTML."""
    work = _promoted(project)[0]
    oa = _fetch_only(project, work, Route.OA_PDF, MD_OTHER)
    arxiv = _fetch_only(project, work, Route.ARXIV_HTML, MD)
    _convert(project)

    page = document_read(project, work_id=work)

    assert oa != arxiv
    assert page.document_id == arxiv
    assert page.route is Route.ARXIV_HTML
    assert page.work_id == work


@pytest.mark.usefixtures("corpus")
def test_pages_cover_every_non_cell_anchor_exactly_once(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)
    expected = _non_cell_ids(_manifest(project, _conversion_of(project, work)))

    seen: list[str] = []
    after: str | None = None
    pages = 0
    while True:
        page = document_read(project, work_id=work, after=after, limit=2)
        pages += 1
        seen += [segment.anchor for segment in page.segments]
        assert page.total_segments == len(expected)
        if page.next_after is None:
            break
        assert page.segments, "a page with more to come must not be empty"
        after = page.next_after

    assert seen == expected
    assert len(seen) == len(set(seen))
    assert pages == -(-len(expected) // 2)


@pytest.mark.usefixtures("corpus")
def test_page_bounded_by_max_chars(project: Project) -> None:
    work = _promoted(project)[0]
    body = "\n\n".join(f"Paragraph {i}. " + "word " * 180 for i in range(3))
    fetched_document(project, work, f"{body}\n".encode())
    _convert(project)

    page = document_read(project, work_id=work, max_chars=1000)

    assert len(page.segments) == 1
    assert page.next_after == page.segments[0].anchor
    assert page.total_segments == 3


@pytest.mark.usefixtures("corpus")
def test_pdf_only_work_refused_naming_convert(project: Project) -> None:
    """A work whose only document has no converter is refused, naming the convert command."""
    work = _promoted(project)[0]
    with project.index.exclusive():
        project.index.sync()
        record_supplied_document(
            project,
            work,
            content=b"%PDF-1.4 synthetic",
            source_version="v1",
            media_type="application/pdf",
            actor=project.human_actor(),
        )
    summary = convert_documents(project, _registry())
    assert [o.reason for o in summary.outcomes] == ["no-converter"]

    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=work)

    [issue] = raised.value.issues
    assert issue.field == "work_id"
    assert "factory document convert" in issue.reason


@pytest.mark.usefixtures("corpus")
def test_max_chars_first_segment_always_returned_and_paging_covers_all(project: Project) -> None:
    work = _promoted(project)[0]
    long_paragraph = "lorem ipsum " * 130
    body = f"{long_paragraph}\n\n# Next\n\nShort one.\n\n## Sub\n\nAnother short.\n"
    fetched_document(project, work, body.encode())
    _convert(project)
    expected = _non_cell_ids(_manifest(project, _conversion_of(project, work)))

    first = document_read(project, work_id=work, max_chars=1000)

    assert len(first.segments) == 1
    assert first.segments[0].anchor == expected[0]
    assert len(first.segments[0].text) > 1000
    assert first.next_after == expected[0]

    seen: list[str] = []
    after: str | None = None
    while True:
        page = document_read(project, work_id=work, after=after, max_chars=1000)
        seen += [segment.anchor for segment in page.segments]
        if page.next_after is None:
            break
        after = page.next_after
    assert seen == expected


def test_work_not_included_refused(project: Project, corpus_leaving: str) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=corpus_leaving)

    assert [(i.field, i.reason) for i in raised.value.issues] == [
        ("work_id", f"{corpus_leaving}: not promoted at title/abstract")
    ]


@pytest.mark.usefixtures("corpus")
def test_converted_work_no_longer_included_refused_by_the_gate(
    project: Project, agent: Actor
) -> None:
    """The work has a live conversion, so only the INCLUDED gate can refuse the read."""
    work = _promoted(project)[0]
    excluded_after_conversion(project, agent, work)
    assert work not in _promoted(project)

    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=work)

    assert [(i.field, i.reason) for i in raised.value.issues] == [
        ("work_id", f"{work}: not promoted at title/abstract")
    ]


@pytest.mark.usefixtures("corpus")
def test_unconverted_work_refused_naming_convert_command(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)

    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=work)

    [issue] = raised.value.issues
    assert issue.field == "work_id"
    assert "factory document convert" in issue.reason


@pytest.mark.usefixtures("corpus")
def test_old_conversion_readable_by_id(project: Project) -> None:
    """Review Focus 3: a version bump writes a second conversion; the first stays readable."""
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    old = _convert(project, "1.0+a")
    new = _convert(project, "1.0+b", upgrade=True)
    assert old is not None and new is not None

    latest = document_read(project, work_id=work)
    first = document_read(project, work_id=work, conversion_id=old)

    assert latest.conversion_id == new
    assert latest.converter_version == stamp_version("1.0+b")
    assert first.conversion_id == old
    assert first.converter_version == stamp_version("1.0+a")
    direct = convert(PassThroughConverter("1.0+a"), MD, "text/html")
    assert _manifest(project, old) == direct.manifest
    assert [s.anchor for s in first.segments] == [
        a.id for a in direct.manifest.anchors if a.kind is not AnchorKind.CELL
    ]
    assert first.total_segments == len(first.segments)


@pytest.mark.usefixtures("corpus")
def test_cell_anchor_read_returns_exact_cell(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)
    manifest = _manifest(project, _conversion_of(project, work))
    cell = next(a for a in manifest.anchors if a.kind is AnchorKind.CELL and a.text == "0.9")

    page = document_read(project, work_id=work, anchor=cell.id)

    assert page.segments == [
        Segment(
            anchor=cell.id, kind=AnchorKind.CELL, parent=cell.parent, text="0.9", truncated=False
        )
    ]
    assert page.next_after is None
    assert all(s.kind is not AnchorKind.CELL for s in document_read(project, work_id=work).segments)


@pytest.mark.usefixtures("corpus")
def test_long_segment_truncated_and_flagged(project: Project) -> None:
    work = _promoted(project)[0]
    long_text = "abcdefghi " * 4500
    fetched_document(project, work, f"# Long\n\n{long_text}\n".encode())
    _convert(project)
    manifest = _manifest(project, _conversion_of(project, work))
    paragraph = next(a for a in manifest.anchors if a.kind is AnchorKind.PARAGRAPH)
    assert len(paragraph.text) > 40000

    page = document_read(project, work_id=work, max_chars=100000)
    [segment] = [s for s in page.segments if s.anchor == paragraph.id]
    assert segment.truncated is True
    assert segment.text == paragraph.text[:8000]

    single = document_read(project, work_id=work, anchor=paragraph.id)
    [only] = single.segments
    assert only.truncated is True
    assert only.text == paragraph.text[:40000]


@pytest.mark.usefixtures("corpus")
def test_unknown_anchor_refused(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)

    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=work, anchor="s99")
    conversion_id = _conversion_of(project, work)
    assert raised.value.issues == [
        ValidationIssue("anchor", f"s99: not an anchor of {conversion_id}")
    ]

    with pytest.raises(FactoryValidationError) as after_raised:
        document_read(project, work_id=work, after="s99")
    assert [i.field for i in after_raised.value.issues] == ["after"]


@pytest.mark.usefixtures("corpus")
def test_anchor_and_after_together_refused(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)

    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=work, anchor="s1", after="s1")
    assert [i.field for i in raised.value.issues] == ["after"]


@pytest.mark.usefixtures("corpus")
@pytest.mark.parametrize("field", ["markdown_hash", "manifest_hash"])
def test_missing_blob_names_restore(project: Project, field: str) -> None:
    """Review Focus 5: a deleted Markdown (or manifest) blob names the restore command."""
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)
    conversion_id = _conversion_of(project, work)
    _strip_blob(project, _conversion_row(project, conversion_id)[field])

    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=work)

    [issue] = raised.value.issues
    assert issue.field == "conversion_id"
    assert "factory document convert --restore" in issue.reason


@pytest.mark.usefixtures("corpus")
def test_manifest_entry_points_verify_markdown_blob(project: Project) -> None:
    """conversion_manifest and resolve_anchor refuse a missing Markdown blob, naming restore."""
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)
    conversion_id = _conversion_of(project, work)
    _strip_blob(project, _conversion_row(project, conversion_id)["markdown_hash"])

    with pytest.raises(FactoryValidationError) as manifest_error:
        conversion_manifest(project, conversion_id)
    with pytest.raises(FactoryValidationError) as anchor_error:
        resolve_anchor(project, conversion_id, "s1")

    for raised in (manifest_error, anchor_error):
        [issue] = raised.value.issues
        assert issue.field == "conversion_id"
        assert "factory document convert --restore" in issue.reason


@pytest.mark.usefixtures("corpus")
def test_resolve_anchor_matches_manifest(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)
    conversion_id = _conversion_of(project, work)
    manifest = _manifest(project, conversion_id)

    for anchor in manifest.anchors:
        assert resolve_anchor(project, conversion_id, anchor.id) == anchor

    with pytest.raises(FactoryValidationError) as missing_anchor:
        resolve_anchor(project, conversion_id, "s99")
    assert [i.field for i in missing_anchor.value.issues] == ["anchor"]

    with pytest.raises(FactoryValidationError) as missing_conversion:
        resolve_anchor(project, "cnv_01ZZZZZZZZZZZZZZZZZZZZZZZZ", "s1")
    assert [i.field for i in missing_conversion.value.issues] == ["conversion_id"]


@pytest.mark.usefixtures("corpus")
def test_limits_validated(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)

    with pytest.raises(FactoryValidationError) as raised:
        document_read(project, work_id=work, limit=0, max_chars=999)
    assert [i.field for i in raised.value.issues] == ["limit", "max_chars"]

    with pytest.raises(FactoryValidationError) as high:
        document_read(project, work_id=work, limit=201, max_chars=100001)
    assert [i.field for i in high.value.issues] == ["limit", "max_chars"]

    assert document_read(project, work_id=work, limit=1, max_chars=1000).segments
    assert document_read(project, work_id=work, limit=200, max_chars=100000).segments


@pytest.mark.usefixtures("corpus")
def test_read_writes_nothing(project: Project) -> None:
    work = _promoted(project)[0]
    fetched_document(project, work, MD)
    _convert(project)
    before = _snapshot(project)

    document_read(project, work_id=work)
    document_read(project, work_id=work, anchor="s1")
    resolve_anchor(project, _conversion_of(project, work), "s1")

    assert _snapshot(project) == before


@pytest.mark.usefixtures("corpus")
def test_document_and_conversion_must_belong_to_work(project: Project) -> None:
    first, second = _promoted(project)[0], _promoted(project)[1]
    other_doc = fetched_document(project, second, MD_OTHER)
    fetched_document(project, first, MD)
    _convert(project)
    other_conversion = _conversion_of(project, second)

    with pytest.raises(FactoryValidationError) as wrong_doc:
        document_read(project, work_id=first, document_id=other_doc)
    assert [i.field for i in wrong_doc.value.issues] == ["document_id"]

    with pytest.raises(FactoryValidationError) as wrong_conv:
        document_read(project, work_id=first, conversion_id=other_conversion)
    assert [i.field for i in wrong_conv.value.issues] == ["conversion_id"]


def _conversion_of(project: Project, work_id: str) -> str:
    """The id of the latest conversion of `work_id`'s default document."""
    return document_read(project, work_id=work_id).conversion_id


def _conversion_row(project: Project, conversion_id: str) -> dict[str, Any]:
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text("SELECT * FROM document_conversions WHERE conversion_id = :cid"),
                {"cid": conversion_id},
            )
            .mappings()
            .one()
        )
    return dict(row)


class _CountingAnchor(Anchor):
    """An anchor that counts attribute reads in a shared counter."""

    reads = 0

    def __getattribute__(self, name: str) -> Any:
        if name in ("id", "kind"):
            _CountingAnchor.reads += 1
        return object.__getattribute__(self, name)


def _counting_manifest(count: int) -> Manifest:
    anchors: list[Anchor] = []
    for i in range(count):
        if i % 10 == 9:
            anchors.append(_CountingAnchor(f"t1r1c{i}", AnchorKind.CELL, "t1", "x"))
        else:
            anchors.append(_CountingAnchor(f"p{i}", AnchorKind.PARAGRAPH, "s0", "x"))
    return Manifest(tuple(anchors))


def test_paging_a_large_manifest_does_not_rescan() -> None:
    manifest = _counting_manifest(20_000)
    expected = [a.id for a in manifest.anchors if a.kind is not AnchorKind.CELL]
    _CountingAnchor.reads = 0
    seen: list[str] = []
    after: str | None = None
    while True:
        segments, after = _page(manifest, after, 50, 10**9, "c1")
        seen += [s.anchor for s in segments]
        if after is None:
            break
    assert _CountingAnchor.reads <= 6 * 20_000
    assert seen == expected


def test_after_cell_anchor_resumes_at_next_non_cell_anchor() -> None:
    manifest = Manifest(
        (
            Anchor("p1", AnchorKind.PARAGRAPH, "s0", "a"),
            Anchor("t1r1c1", AnchorKind.CELL, "t1", "b"),
            Anchor("t1r1c2", AnchorKind.CELL, "t1", "c"),
            Anchor("p2", AnchorKind.PARAGRAPH, "s0", "d"),
        )
    )
    segments, after = _page(manifest, "t1r1c2", 10, 1000, "c1")
    assert [s.anchor for s in segments] == ["p2"]
    assert after is None


def test_page_with_only_serves_just_the_selected_anchors_and_pages_through_them() -> None:
    from factory.document.anchorise import anchorise
    from factory.document.anchors import AnchorKind, parse_manifest
    from factory.services.document_read import _page

    manifest = parse_manifest(
        anchorise("# 1 Intro\n\nFirst.\n\nSecond.\n\nThird.\n\n# 2 End\n\nLast.\n")
    )
    paragraphs = [a.id for a in manifest.anchors if a.kind is AnchorKind.PARAGRAPH]
    only = frozenset({paragraphs[0], paragraphs[2], paragraphs[3]})
    first, nxt = _page(manifest, None, 2, 20_000, "c", only)
    assert [s.anchor for s in first] == [paragraphs[0], paragraphs[2]]
    assert nxt == paragraphs[2]
    second, done = _page(manifest, nxt, 2, 20_000, "c", only)
    assert [s.anchor for s in second] == [paragraphs[3]]
    assert done is None
