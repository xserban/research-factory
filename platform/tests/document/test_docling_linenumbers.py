"""IDEA-48 wiring: the docling post-process, its version, the coverage rule and fixture figures."""

from factory.document import docling as docling_module
from factory.document.anchorise import anchorise
from factory.document.docling import postprocess
from factory.services.conversion_coverage import _TAG, content_words, overlap, words

BODY = [
    "We screen candidate papers against the protocol and record every verdict with a quote.",
    "Disagreements between the two passes are resolved by a human reviewer with a reason.",
    "The report states counts computed from events rather than typed by an agent today.",
    "Calibration draws a sample, the researcher labels it and the gate compares the result.",
]


def _source_text(numbered: bool) -> str:
    """The text layer: one line per sentence half, with the margin number first when numbered."""
    lines: list[str] = []
    n = 0
    for sentence in BODY:
        tokens = sentence.split()
        half = len(tokens) // 2
        for part in (" ".join(tokens[:half]), " ".join(tokens[half:])):
            n += 1
            lines.append(f"{n} {part}" if numbered else part)
    return "\n".join(lines)


def _docling_markdown() -> str:
    """What the layout model gave for the margin-numbered page: the margin column as one run of
    paragraphs and the body as paragraphs."""
    numbers = [str(n) for n in range(1, 2 * len(BODY) + 1)]
    return "\n\n".join(["# Title", *numbers, *BODY]) + "\n"


def test_version_is_bumped_and_names_the_filter() -> None:
    assert docling_module.CONVERTER_VERSION == "1.2"


def test_postprocess_drops_the_run_and_reports_counts_only() -> None:
    text, notes = postprocess(_docling_markdown())
    assert not any(line.strip().isdigit() for line in text.splitlines())
    assert notes == ("dropped 8 line-number paragraphs in 1 runs",)


def test_postprocess_leaves_a_clean_document_untouched() -> None:
    clean = "# Title\n\nA paragraph.\n\n12\n\nAnother one.\n"
    assert postprocess(clean) == (clean, ())


def test_filtering_before_anchoring_shrinks_the_paragraph_count() -> None:
    before = anchorise(_docling_markdown()).count("<a id=")
    after = anchorise(postprocess(_docling_markdown())[0]).count("<a id=")
    assert (before, after) == (13, 5)


def test_coverage_ignores_bare_number_tokens() -> None:
    assert content_words("In 2019 page 12 we ran 3 trials") == ["in", "page", "we", "ran", "trials"]
    assert words("page 12") == ["page", "12"]


def test_five_gram_recall_before_and_after() -> None:
    source = _source_text(numbered=True)
    before_md = anchorise(_docling_markdown())
    after_md = anchorise(postprocess(_docling_markdown())[0])
    recall_before, _ = overlap(words(source), words(_TAG.sub(" ", before_md)))
    recall_after, precision_after = overlap(
        content_words(source), content_words(_TAG.sub(" ", after_md))
    )
    assert recall_after > recall_before
    assert recall_after > 0.95 and precision_after > 0.95
