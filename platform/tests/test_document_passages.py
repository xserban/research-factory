"""Tests for cutting anchored Markdown into search passages."""

import pytest

from factory.document.passages import (
    BOILERPLATE,
    Passage,
    SectionKind,
    cut_passages,
    embedding_windows,
    section_kind,
)


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
    md = _doc(_h("s1", "A"), *[_p(f"s1.p{i}", _words(30)) for i in range(1, 7)])
    for target in (30, 60, 95):
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
        _p("s1.p1", _words(30)),
        _p("s1.p2", _words(40)),
        _p("s1.p3", _words(30)),
    )
    result = cut_passages(md, target_words=35)
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
        _p("s1.p1", _words(30)),
        '<a id="t1"></a>\n| a | b |\n|---|---|\n| 1 | **2** |',
        _p("f1.cap", "Figure 1. A *caption* here " + _words(30)),
        _p("s1.p2", _words(30)),
    )
    result = cut_passages(md, target_words=40)
    assert [p.anchors for p in result] == [("s1.p1", "t1"), ("f1.cap",), ("s1.p2",)]
    assert result[0].text.endswith(" a | b | 1 | 2")  # 7 words: merged into the paragraph
    assert result[1].text == "Figure 1. A caption here " + _words(30)
    assert result[1].section_anchor == "s1"
    assert result[1].section_path == ("A",)


def test_long_table_is_own_passage() -> None:
    header = "| " + " | ".join(f"h{i}" for i in range(30)) + " |"
    sep = "|" + "---|" * 30
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", _words(30)),
        f'<a id="t1"></a>\n{header}\n{sep}',
        _p("s1.p2", _words(30)),
    )
    result = cut_passages(md, target_words=40)
    assert [p.anchors for p in result] == [("s1.p1",), ("t1",), ("s1.p2",)]


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


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ((), SectionKind.OTHER),
        (("References",), SectionKind.BACK),
        (("Acknowledgements",), SectionKind.BACK),
        (("Statement on AI use",), SectionKind.BACK),
        (("Appendix B",), SectionKind.APPENDIX),
        (("A.1 Prompts",), SectionKind.APPENDIX),
        (("B.2.3 Details",), SectionKind.APPENDIX),
        (("Prompt listings",), SectionKind.METHOD),
        (("2 Related Work",), SectionKind.RELATED),
        (("Background",), SectionKind.RELATED),
        (("1 Introduction",), SectionKind.FRONT),
        (("Abstract",), SectionKind.FRONT),
        (("3.1 Method",), SectionKind.METHOD),
        (("System architecture",), SectionKind.METHOD),
        (("4 Experiments",), SectionKind.RESULTS),
        (("Ablation study",), SectionKind.RESULTS),
        (("5 Discussion",), SectionKind.DISCUSSION),
        (("Conclusion",), SectionKind.DISCUSSION),
        (("Experiments and Discussion",), SectionKind.DISCUSSION),
        (("Method and results",), SectionKind.RESULTS),
        (("Something else",), SectionKind.OTHER),
        # innermost matching heading decides
        (("Method", "Evaluation"), SectionKind.RESULTS),
        (("Experiments", "Plain heading"), SectionKind.RESULTS),
        # the innermost heading naming a kind decides; ancestors do not taint
        (("Method", "Related work"), SectionKind.RELATED),
        (("Related work", "Method"), SectionKind.METHOD),
        (("Related work", "Plain heading"), SectionKind.RELATED),
        # an appendix ancestor wins
        (("Appendix", "Related work", "Results"), SectionKind.APPENDIX),
        (("References", "Appendix"), SectionKind.APPENDIX),
        # B1 table
        (("A Survey of X",), SectionKind.OTHER),
        (("Prompting strategies",), SectionKind.METHOD),
        (("Background and Motivation",), SectionKind.FRONT),
        (("Competing baselines",), SectionKind.OTHER),
        (("Competing interests",), SectionKind.BACK),
        (("Reference-based evaluation",), SectionKind.RESULTS),
        (("A.3 Code Execution Examples",), SectionKind.APPENDIX),
        (("G Baseline Implementation Details",), SectionKind.METHOD),
        (("Appendix A: Prompts",), SectionKind.APPENDIX),
        (("Results and Discussion",), SectionKind.DISCUSSION),
        (("IV. Related Work",), SectionKind.RELATED),
        (("Contents",), SectionKind.BACK),
        (("Broader Impact",), SectionKind.BACK),
        (("Background and related work",), SectionKind.RELATED),
        (("Supplementary Material",), SectionKind.APPENDIX),
        (("Ethics of annotation",), SectionKind.BACK),
    ],
)
def test_section_kind(path: tuple[str, ...], kind: SectionKind) -> None:
    assert section_kind(path) is kind


def test_bare_letter_is_appendix_only_after_back_matter() -> None:
    heading = "G Baseline Implementation Details"
    assert section_kind((heading,), (False,)) is SectionKind.METHOD
    assert section_kind((heading,), (True,)) is SectionKind.APPENDIX
    # a title-like heading with a bare letter, met after the references, is judged by its own flag
    assert section_kind(("A Survey of X", "Method"), (False, True)) is SectionKind.METHOD


def test_framework_title_is_not_appendix() -> None:
    assert section_kind(("A Framework for Agentic Science",)) is SectionKind.METHOD


def test_title_first_heading_uses_exact_forms_only() -> None:
    title = "Appendix Generation with Contents of Related Work"
    assert section_kind((title,), title_first=True) is SectionKind.OTHER
    assert section_kind((title,)) is SectionKind.APPENDIX
    assert section_kind(("References",), title_first=True) is SectionKind.BACK


def test_cut_title_heading_does_not_taint_sections() -> None:
    md = _doc(
        _h("s1", "A Survey of Agentic Science"),
        _h("s1.1", "Introduction"),
        _p("s1.1.p1", _words(40)),
        _h("s1.2", "Method"),
        _p("s1.2.p1", _words(40)),
        _h("s1.3", "Plain text"),
        _p("s1.3.p1", _words(40)),
        _h("s2", "References"),
        _p("s2.p1", _words(40)),
        _h("s3", "G Baseline Details"),
        _p("s3.p1", _words(40)),
    )
    kinds = {p.passage_id: p.section_kind for p in cut_passages(md)}
    assert kinds == {
        "s1.1.p1": SectionKind.FRONT,
        "s1.2.p1": SectionKind.METHOD,
        "s1.3.p1": SectionKind.OTHER,
        "s2.p1": SectionKind.BACK,
        "s3.p1": SectionKind.APPENDIX,
    }


def test_cut_bare_letter_before_references_is_not_appendix() -> None:
    md = _doc(
        _h("s1", "Introduction"),
        _p("s1.p1", _words(40)),
        _h("s2", "G Baseline Details"),
        _p("s2.p1", _words(40)),
        _h("s3", "References"),
        _p("s3.p1", _words(40)),
        _h("s4", "G Baseline Details"),
        _p("s4.p1", _words(40)),
    )
    kinds = {p.passage_id: p.section_kind for p in cut_passages(md)}
    assert kinds["s2.p1"] is not SectionKind.APPENDIX
    assert kinds["s4.p1"] is SectionKind.APPENDIX


def test_passage_carries_section_kind() -> None:
    md = _doc(_h("s1", "Method"), _p("s1.p1", _words(40)))
    assert cut_passages(md)[0].section_kind is SectionKind.METHOD


def test_short_passage_merges_into_previous_in_section() -> None:
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", _words(40)),
        _p("s1.p2", _words(5)),
    )
    result = cut_passages(md, target_words=40)
    assert [p.anchors for p in result] == [("s1.p1", "s1.p2")]
    assert result[0].passage_id == "s1.p1~s1.p2"
    assert result[0].text == _words(40) + " " + _words(5)


def test_short_first_passage_merges_into_next() -> None:
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", _words(5)),
        _p("s1.p2", _words(40)),
    )
    result = cut_passages(md, target_words=40)
    assert [p.anchors for p in result] == [("s1.p1", "s1.p2")]


def test_short_never_crosses_section_and_lone_short_stays() -> None:
    md = _doc(
        _h("s1", "One"),
        _p("s1.p1", _words(40)),
        _h("s2", "Two"),
        _p("s2.p1", _words(5)),
    )
    result = cut_passages(md)
    assert [p.anchors for p in result] == [("s1.p1",), ("s2.p1",)]


def test_short_table_merges_and_skipped_kept() -> None:
    md = _doc(
        _h("s1", "A"),
        _p("s1.p1", _words(40)),
        _p("s1.p2", "12345"),
        _p("s1.p3", _words(5)),
    )
    result = cut_passages(md, target_words=40)
    assert len(result) == 1
    assert result[0].skipped == ("s1.p2",)
    assert result[0].anchors == ("s1.p1", "s1.p3")


def test_embedding_windows_short_text_whole() -> None:
    assert embedding_windows("One. Two.") == ["One. Two."]
    assert embedding_windows("") == [""]


def test_embedding_windows_split_at_sentences() -> None:
    s = _words(4) + "."
    text = " ".join([s] * 6)
    windows = embedding_windows(text, max_words=10)
    assert windows == [" ".join([s, s]), " ".join([s, s]), " ".join([s, s])]
    assert embedding_windows(text, max_words=10) == windows


def test_embedding_windows_long_sentence_split_by_words() -> None:
    windows = embedding_windows(_words(25), max_words=10)
    assert [len(w.split()) for w in windows] == [10, 10, 5]
    short = "Hi there."
    mixed = embedding_windows(short + " " + _words(25) + ". " + short, max_words=10)
    assert mixed[0] == short
    assert mixed[-1] == short
    assert all(len(w.split()) <= 10 for w in mixed)
