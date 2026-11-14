"""IDEA-48: the line-number post-filter."""

from factory.document.linenumbers import MIN_RUN, drop_line_numbers


def _paras(*items: str) -> str:
    return "\n\n".join(items) + "\n"


def _margin_page(start: int, count: int) -> list[str]:
    out: list[str] = []
    for n in range(start, start + count):
        out.append(str(n))
        out.append(f"Sentence number {n} of the page body with enough words to read.")
    return out


def test_margin_numbers_clustered_are_dropped() -> None:
    text = _paras("# Title", *[str(n) for n in range(1, 31)], "Real text one.", "Real text two.")
    result = drop_line_numbers(text)
    assert result.dropped == 30 and result.runs == 1
    assert result.text == _paras("# Title", "Real text one.", "Real text two.")


def test_page_break_does_not_end_a_run() -> None:
    text = _paras("1", "2", "3", "\f", "4", "5", "Body.")
    result = drop_line_numbers(text)
    assert result.dropped == 5
    assert "\f" in result.text and "Body." in result.text


def test_each_page_restart_is_its_own_run() -> None:
    text = _paras(*[str(n) for n in range(1, 8)], "\f", *[str(n) for n in range(1, 8)], "End.")
    result = drop_line_numbers(text)
    assert result.dropped == 14 and result.runs == 2


def test_short_run_stays() -> None:
    items = [str(n) for n in range(1, MIN_RUN)]  # one short
    text = _paras("Table of ranks", *items, "after")
    assert drop_line_numbers(text).text == text


def test_page_number_and_table_value_stay() -> None:
    text = _paras("Intro paragraph.", "12", "Next paragraph.", "2019", "More text.")
    result = drop_line_numbers(text)
    assert result.text == text and result.dropped == 0


def test_run_broken_by_real_text_stays() -> None:
    text = _paras("1", "2", "3", "A real paragraph.", "4", "5", "6")
    assert drop_line_numbers(text).text == text


def test_run_not_counting_by_one_stays() -> None:
    text = _paras("1", "2", "4", "5", "6", "8")
    assert drop_line_numbers(text).dropped == 0


def test_five_digit_number_is_not_a_line_number() -> None:
    text = _paras("9998", "9999", "10000", "10001", "10002", "x")
    assert drop_line_numbers(text).dropped == 0


def test_number_alone_once_stays() -> None:
    text = _paras("Text.", "7", "Text again.")
    assert drop_line_numbers(text).text is text


def test_run_at_the_start_and_the_end_of_the_text() -> None:
    text = _paras(*[str(n) for n in range(40, 46)])
    assert drop_line_numbers(text).text == "\n"


def test_interleaved_numbers_are_kept() -> None:
    """Numbers that alternate with text lines never form an adjacent run (documented limit)."""
    text = _paras(*_margin_page(1, 10))
    assert drop_line_numbers(text).dropped == 0
