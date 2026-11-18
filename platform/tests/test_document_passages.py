"""Tests for cutting anchored Markdown into search passages."""

from factory.document.passages import BOILERPLATE, Passage, cut_passages


def _doc(*parts: str) -> str:
    return "\n\n".join(parts) + "\n"


def _h(anchor: str, title: str, level: int = 2) -> str:
    return f'<a id="{anchor}"></a>\n{"#" * level} {title}'


def _p(anchor: str, text: str) -> str:
    return f'<a id="{anchor}"></a>\n{text}'


def _words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


def test_packs_paragraphs_up_to_target() -> None:
    md = _doc(
        _h("s1", "Intro"),
        _p("s1.p1", _words(40)),
        _p("s1.p2", _words(40)),
        _p("s1.p3", _words(40)),
    )
    result = cut_passages(md, target_words=100)
    assert [p.anchors for p in result] == [("s1.p1", "s1.p2"), ("s1.p3",)]
    assert result[0].passage_id == "s1.p1~s1.p2"
    assert result[1].passage_id == "s1.p3"
    assert result[0].text == _words(40) + " " + _words(40)
    assert all(isinstance(p, Passage) for p in result)


def test_target_words_respected() -> None:
    md = _doc(_h("s1", "A"), *[_p(f"s1.p{i}", _words(10)) for i in range(1, 7)])
    for target in (10, 20, 35):
        for p in cut_passages(md, target_words=target):
            assert len(p.text.split()) <= target


def test_no_passage_crosses_a_heading() -> None:
    md = _doc(
        _h("s1", "One"),
        _p("s1.p1", "short text here ok"),
        _h("s2", "Two"),
        _p("s2.p1", "other short text ok"),
    )
    result = cut_passages(md)
    assert [p.anchors for p in result] == [("s1.p1",), ("s2.p1",)]
    assert [p.section_anchor for p in result] == ["s1", "s2"]


def test_long_paragraph_alone() -> None:
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", _words(5)),
        _p("s1.p2", _words(30)),
        _p("s1.p3", _words(5)),
    )
    result = cut_passages(md, target_words=20)
    assert [p.anchors for p in result] == [("s1.p1",), ("s1.p2",), ("s1.p3",)]


def test_number_only_and_boilerplate_skipped() -> None:
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", "A real sentence about things."),
        _p("s1.p2", "12 345"),
        _p("s1.p3", "-- . ,"),
        _p("s1.p4", "Skip to main content"),
        _p("s1.p5", "More real text follows here."),
    )
    result = cut_passages(md)
    assert len(result) == 1
    assert result[0].anchors == ("s1.p1", "s1.p5")
    assert result[0].skipped == ("s1.p2", "s1.p3", "s1.p4")
    assert "12" not in result[0].text
    assert "skip to main content" in BOILERPLATE


def test_skipped_before_first_kept_goes_to_next_passage() -> None:
    md = _doc(_h("s1", "A"), _p("s1.p1", "123"), _p("s1.p2", "Real words here now."))
    result = cut_passages(md)
    assert result[0].anchors == ("s1.p2",)
    assert result[0].skipped == ("s1.p1",)


def test_boilerplate_only_whole_text() -> None:
    md = _doc(_h("s1", "A"), _p("s1.p1", "References"), _p("s1.p2", "References are listed."))
    result = cut_passages(md)
    assert result[0].anchors == ("s1.p2",)
    assert result[0].skipped == ("s1.p1",)


def test_short_paragraphs_are_packed_not_filtered() -> None:
    md = _doc(_h("s1", "A"), _p("s1.p1", "Yes."), _p("s1.p2", "No way."))
    result = cut_passages(md)
    assert result[0].anchors == ("s1.p1", "s1.p2")
    assert result[0].skipped == ()


def test_bibliography_pages_equations_never_passages() -> None:
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", "Body text of the paper."),
        '<a id="p2"></a>',
        _p("e1", "$$x = y$$"),
        _p("b1", "Smith, J. A reference entry."),
        _p("b2", "Jones, K. Another reference entry."),
    )
    result = cut_passages(md)
    assert [p.anchors for p in result] == [("s1.p1",)]


def test_table_and_caption_are_own_passages() -> None:
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", "Before the table text."),
        '<a id="t1"></a>\n| a | b |\n|---|---|\n| 1 | **2** |',
        _p("f1.cap", "Figure 1. A *caption* here."),
        _p("s1.p2", "After the table text."),
    )
    result = cut_passages(md)
    assert [p.anchors for p in result] == [("s1.p1",), ("t1",), ("f1.cap",), ("s1.p2",)]
    assert result[1].text == "a | b | 1 | 2"
    assert result[2].text == "Figure 1. A caption here."
    assert result[1].section_anchor == "s1"
    assert result[2].section_path == ("A",)


def test_section_path_nested_and_s0() -> None:
    md = _doc(
        _p("s0.p1", "Preamble text of the work."),
        _h("s1", "Methods"),
        _h("s1.1", "Data", 3),
        _p("s1.1.p1", "Data text goes here ok."),
        _h("s2", "Results"),
        _p("s2.p1", "Results text goes here."),
    )
    result = cut_passages(md)
    by_anchor = {p.anchors[0]: p for p in result}
    assert by_anchor["s0.p1"].section_anchor == "s0"
    assert by_anchor["s0.p1"].section_path == ()
    assert by_anchor["s1.1.p1"].section_anchor == "s1.1"
    assert by_anchor["s1.1.p1"].section_path == ("Methods", "Data")
    assert by_anchor["s2.p1"].section_path == ("Results",)


def test_deterministic() -> None:
    md = _doc(_h("s1", "A"), *[_p(f"s1.p{i}", _words(30)) for i in range(1, 12)])
    assert cut_passages(md) == cut_passages(md)


def test_empty_document() -> None:
    assert cut_passages("") == []
