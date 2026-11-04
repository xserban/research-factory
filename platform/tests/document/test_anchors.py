import json

import pytest

from factory.document.anchors import (
    ANCHOR_RE,
    AnchorKind,
    Manifest,
    ManifestError,
    parse_manifest,
)

MD = (
    '<a id="s1"></a>\n# 1 Intro\n\n<a id="s1.p1"></a>\nText.\n\n'
    '<a id="t1"></a>\n| a | b |\n|---|---|\n| 1 | 2 |\n'
)


def test_manifest_lists_sections_paragraphs_tables_and_cells() -> None:
    m = parse_manifest(MD)
    assert [a.id for a in m.anchors] == [
        "s1",
        "s1.p1",
        "t1",
        "t1.r1.c1",
        "t1.r1.c2",
        "t1.r2.c1",
        "t1.r2.c2",
    ]
    cell = m.get("t1.r2.c2")
    assert cell is not None
    assert cell.text == "2"
    assert cell.parent == "t1"
    assert cell.kind is AnchorKind.CELL


def test_anchor_text_is_element_source_without_anchor_line() -> None:
    m = parse_manifest(MD)
    heading = m.get("s1")
    paragraph = m.get("s1.p1")
    table = m.get("t1")
    assert heading is not None and heading.text == "# 1 Intro"
    assert paragraph is not None and paragraph.text == "Text."
    assert table is not None and table.text == "| a | b |\n|---|---|\n| 1 | 2 |"


def test_parents_follow_the_section_rules() -> None:
    md = (
        '<a id="t0"></a>\n| a |\n|---|\n| 1 |\n\n'
        '<a id="s3"></a>\n# 3\n\n'
        '<a id="s3.2"></a>\n## 3.2\n\n'
        '<a id="s3.2.p1"></a>\nBody.\n\n'
        '<a id="f1.cap"></a>\nFigure one.\n\n'
        '<a id="t1"></a>\n| a |\n|---|\n| 1 |\n'
    )
    m = parse_manifest(md)
    section = m.get("s3.2")
    assert section is not None and section.parent == "s3"
    top = m.get("s3")
    assert top is not None and top.parent is None
    paragraph = m.get("s3.2.p1")
    assert paragraph is not None and paragraph.parent == "s3.2"
    caption = m.get("f1.cap")
    assert caption is not None and caption.parent == "s3.2"
    assert caption.kind is AnchorKind.FIGURE_CAPTION
    tail_table = m.get("t1")
    assert tail_table is not None and tail_table.parent == "s3.2"
    # A table before any section has no enclosing section.
    preamble = m.get("t0")
    assert preamble is not None and preamble.parent is None


def test_duplicate_anchor_rejected() -> None:
    md = '<a id="s1"></a>\n# A\n\n<a id="s1"></a>\n# B\n'
    with pytest.raises(ManifestError, match="duplicate"):
        parse_manifest(md)


@pytest.mark.parametrize(
    "md",
    [
        '<a id="s1.p1"></a>\n\nText after a blank line.\n',
        '<a id="t1"></a>\n',
        '<a id="s1.p1"></a>\n<a id="s1.p2"></a>\nText.\n',
    ],
    ids=["blank-line-gap", "end-of-document", "two-anchors-in-a-row"],
)
def test_anchor_without_following_element_rejected(md: str) -> None:
    with pytest.raises(ManifestError, match="not directly followed"):
        parse_manifest(md)


def test_paragraph_under_unknown_section_rejected() -> None:
    with pytest.raises(ManifestError, match="under unknown section"):
        parse_manifest('<a id="s9.p1"></a>\nText.\n')


def test_s0_preamble_paragraphs_need_no_section_anchor() -> None:
    md = '<a id="s0.p1"></a>\nPreamble.\n\n<a id="s1"></a>\n# 1\n'
    m = parse_manifest(md)
    preamble = m.get("s0.p1")
    assert preamble is not None
    assert preamble.parent == "s0"
    assert preamble.text == "Preamble."
    assert m.get("s0") is None


def test_page_anchor_needs_no_following_element() -> None:
    md = '<a id="p1"></a>\n\n<a id="s1"></a>\n# 1\n'
    m = parse_manifest(md)
    page = m.get("p1")
    assert page is not None
    assert page.kind is AnchorKind.PAGE
    assert page.parent is None
    assert page.text == ""


def test_cell_ids_never_written_in_markdown() -> None:
    md = '<a id="t1.r1.c1"></a>\n| a |\n|---|\n| 1 |\n'
    with pytest.raises(ManifestError, match="not a valid anchor id"):
        parse_manifest(md)


def test_cell_text_is_unescaped_and_stripped() -> None:
    md = '<a id="t1"></a>\n| a |\n|---|\n|  x\\|y  |\n'
    m = parse_manifest(md)
    cell = m.get("t1.r2.c1")
    assert cell is not None and cell.text == "x|y"


def test_non_rectangular_table_rejected() -> None:
    md = '<a id="t1"></a>\n| a | b |\n|---|---|\n| 1 |\n'
    with pytest.raises(ManifestError, match="non-rectangular"):
        parse_manifest(md)


def test_section_anchor_must_precede_a_heading() -> None:
    with pytest.raises(ManifestError, match="must be followed by a heading"):
        parse_manifest('<a id="s1"></a>\nNot a heading.\n')


def test_anchor_must_be_on_its_own_line() -> None:
    with pytest.raises(ManifestError, match="own line"):
        parse_manifest('Text.\n<a id="s1.p1"></a>\nMore.\n')


@pytest.mark.parametrize("bad", ["x1", "s", "s1.p", "t1.r1.c1", "f1", "S1"])
def test_invalid_anchor_ids_rejected(bad: str) -> None:
    with pytest.raises(ManifestError, match="not a valid anchor id"):
        parse_manifest(f'<a id="{bad}"></a>\nText.\n')


def test_anchor_re_accepts_the_grammar_and_nothing_else() -> None:
    for good in ["s0", "s12.3", "s1.p1", "s1.2.p3", "p7", "t1", "f2.cap", "e4"]:
        assert ANCHOR_RE.match(good), good
    for bad in ["t1.r1.c1", "f2", "s1.", "p", "e", "s1.p"]:
        assert not ANCHOR_RE.match(bad), bad


def test_manifest_json_is_canonical_and_stable() -> None:
    md = '<a id="s1"></a>\n# 1\n\n<a id="p1"></a>\n\n<a id="s1.p1"></a>\né "q"\n'
    first = parse_manifest(md).to_json()
    assert first == parse_manifest(md).to_json()
    assert (
        first
        == (
            '[{"id":"s1","kind":"section","parent":null,"text":"# 1"},'
            '{"id":"p1","kind":"page","parent":null,"text":""},'
            '{"id":"s1.p1","kind":"paragraph","parent":"s1","text":"é \\"q\\""}]'
        ).encode()
    )


def test_manifest_json_round_trip() -> None:
    m = parse_manifest(MD)
    assert Manifest.from_json(m.to_json()) == m


def _entry(**changes: object) -> dict[str, object]:
    entry: dict[str, object] = {"id": "s1", "kind": "section", "parent": None, "text": "# 1"}
    entry.update(changes)
    return entry


def _data(*entries: object) -> bytes:
    return json.dumps(list(entries)).encode()


def test_from_json_rejects_unknown_kind() -> None:
    with pytest.raises(ManifestError, match="kind"):
        Manifest.from_json(_data(_entry(kind="bogus")))


def test_from_json_accepts_cell_ids() -> None:
    cell = _entry(id="t1.r2.c1", kind="cell", parent="t1", text="1")
    assert Manifest.from_json(_data(cell)).anchors[0].id == "t1.r2.c1"


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b'{"id": "s1"}',
        b'["not an object"]',
        _data({"id": "s1", "kind": "section", "parent": None}),
        _data(_entry(extra=1)),
        _data(_entry(id="x1")),
        _data(_entry(id="t1.r1.c1x")),
        _data(_entry(parent=3)),
        _data(_entry(text=None)),
    ],
    ids=[
        "not-json",
        "not-a-list",
        "not-an-object",
        "missing-key",
        "extra-key",
        "bad-id",
        "bad-cell-id",
        "bad-parent",
        "bad-text",
    ],
)
def test_from_json_rejects_malformed_input(data: bytes) -> None:
    with pytest.raises(ManifestError):
        Manifest.from_json(data)


def test_manifest_round_trip_covers_every_kind() -> None:
    md = (
        '<a id="p1"></a>\n\n<a id="s0.p1"></a>\nPreamble.\n\n'
        '<a id="s1"></a>\n# 1\n\n<a id="f1.cap"></a>\nFigure one.\n\n'
        '<a id="e1"></a>\n$x$\n\n<a id="t1"></a>\n| a |\n|---|\n| 1 |\n'
    )
    m = parse_manifest(md)
    assert {a.kind for a in m.anchors} == set(AnchorKind)
    assert Manifest.from_json(m.to_json()) == m


@pytest.mark.parametrize(
    ("anchor_id", "kind"),
    [
        ("s1", "table"),
        ("s1.p1", "section"),
        ("t1", "paragraph"),
        ("p1", "table"),
        ("t1", "cell"),
        ("f1.cap", "equation"),
        ("e1", "figure_caption"),
        ("s1", "page"),
        ("t1.r1.c1", "table"),
    ],
)
def test_from_json_rejects_id_form_that_contradicts_kind(anchor_id: str, kind: str) -> None:
    with pytest.raises(ManifestError, match="id"):
        Manifest.from_json(_data(_entry(id=anchor_id, kind=kind)))


def test_from_json_rejects_invalid_utf8() -> None:
    data = b'[{"id":"s1","kind":"section","parent":null,"text":"\xff"}]'
    with pytest.raises(ManifestError, match="not valid JSON"):
        Manifest.from_json(data)


def test_from_json_rejects_non_string_text() -> None:
    with pytest.raises(ManifestError, match="text"):
        Manifest.from_json(_data(_entry(text=3)))
