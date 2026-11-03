"""Tests for canonical normalisation and table cell escaping."""

from factory.document.anchorise import anchorise
from factory.document.anchors import AnchorKind, parse_manifest
from factory.document.normalise import escape_cell, normalise


def test_normalise_rules() -> None:
    assert normalise("é\n") == "é\n"  # NFC
    assert normalise("a\r\nb\rc") == "a\nb\nc\n"  # LF line endings
    assert normalise("a  \t\n") == "a\n"  # no trailing whitespace
    assert normalise("a\n\n\n\nb\n") == "a\n\nb\n"  # at most one blank line between blocks
    assert normalise("\n\na\n\n") == "a\n"  # no leading or trailing blank lines
    assert normalise("a") == "a\n"  # file ends with exactly one newline
    assert normalise("a\n\n\n") == "a\n"
    assert normalise("| a\tb | c |\n|---|---|\n| x\ty | 1 |\n") == (
        "| a b | c |\n|---|---|\n| x y | 1 |\n"
    )  # tabs inside table cells become single spaces
    assert normalise("a\tb\n") == "a\tb\n"  # tabs outside tables are kept
    assert normalise("\ufb01ne \u2013 dash\n") == "\ufb01ne \u2013 dash\n"  # ligatures, dashes
    assert normalise("```\na\n\n\nb\n```\n") == "```\na\n\n\nb\n```\n"  # code is not collapsed
    assert normalise("") == ""


def test_normalise_is_idempotent() -> None:
    for sample in ["é \r\n\n\n\t| a\t|\n|-|\n| b\t|\n\n\n", "x  \n", "", "\f\n\n\n"]:
        once = normalise(sample)
        assert normalise(once) == once


def test_cell_pipe_and_newline() -> None:
    assert escape_cell("x|y") == "x\\|y"
    assert escape_cell("a\nb") == "a b"
    assert escape_cell("  pad \n") == "pad"
    left, right = escape_cell("|x|"), escape_cell("two\nlines")
    m = parse_manifest(anchorise(f"| a | b |\n|---|---|\n| {left} | {right} |\n"))
    cell = m.get("t1.r2.c1")
    assert cell is not None and cell.text == "|x|" and cell.kind is AnchorKind.CELL
    other = m.get("t1.r2.c2")
    assert other is not None and other.text == "two lines"
    assert m.get("t1.r2.c3") is None  # the column count is unchanged
