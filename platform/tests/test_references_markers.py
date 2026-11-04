import dataclasses

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.references.markers import completeness_flags, find_contexts
from factory.references.parse import parse_bibliography
from tests.references_helpers import manifest

NUMERIC = [f"[{i}] A. Auth{i}. Title {i}. Venue, {2000 + i}." for i in range(1, 11)]


def _ctx(body: list[str], entries: list[str] = NUMERIC):  # type: ignore[no-untyped-def]
    m = manifest(entries, body)
    bib = parse_bibliography(m)
    return bib, *find_contexts(m, bib)


def test_numeric_markers() -> None:
    _, ctx, distinct = _ctx(["see [3, 5], [7-9] and [2]"])
    assert [(c.entry, c.state) for c in ctx] == [
        (3, "matched"),
        (5, "matched"),
        (7, "matched"),
        (8, "matched"),
        (9, "matched"),
        (2, "matched"),
    ]
    assert {c.method for c in ctx} == {"numeric"} and {c.citing_anchor for c in ctx} == {"s1.p1"}
    assert distinct == 3


def test_numeric_markers_through_labels_when_present() -> None:
    entries = ["[10] A. A. T. 2001.", "[11] B. B. T. 2002."]
    _, ctx, _ = _ctx(["see [11]"], entries)
    assert [(c.entry, c.state) for c in ctx] == [(2, "matched")]


def test_linked_markers_use_link_method() -> None:
    _, ctx, distinct = _ctx(["as in [1](#b1) and [Auth2 (2002)](#b2), also [99](#b99)"])
    assert [(c.method, c.entry, c.state) for c in ctx] == [
        ("link", 1, "matched"),
        ("link", 2, "matched"),
        ("link", None, "unmatched"),
    ]
    assert ctx[0].marker == "[1]" and ctx[1].marker == "Auth2 (2002)"
    assert distinct == 3


def test_link_is_not_also_counted_as_numeric() -> None:
    _, ctx, _ = _ctx(["[[1]](#b1)"])
    assert len(ctx) == 1 or all(c.method != "numeric" or c.entry == 1 for c in ctx)


WANG = [
    "Wang, L. (2021). First paper. Venue A.",
    "Wang, L. (2021). Second paper. Venue B.",
    "Li, Q., and Chen, Z. (2019). Third paper. Venue C.",
    "Müller, K. (2018). Fourth paper. Venue D.",
]


def test_author_year_unique_and_ambiguous() -> None:
    _, ctx, _ = _ctx(
        ["(Li and Chen, 2019; Wang et al., 2021) and Müller (2018), Muller et al. (2018)."],
        WANG,
    )
    assert [(c.entry, c.state, c.method) for c in ctx] == [
        (3, "matched", "author-year"),
        (None, "ambiguous", "author-year"),
        (4, "matched", "author-year"),
        (4, "matched", "author-year"),
    ]
    assert ctx[0].marker == "Li and Chen, 2019" and ctx[1].marker == "Wang et al., 2021"


def test_author_year_unmatched_and_non_citation_parentheses() -> None:
    _, ctx, _ = _ctx(["(Zed, 2001) happened (in 2020) and (see Figure 3)."], WANG)
    assert [(c.entry, c.state) for c in ctx] == [(None, "unmatched")]


def test_marker_to_missing_entry_flags_gap() -> None:
    entries = [f"[{i}] A. Auth{i}. Title. {2000 + i}." for i in range(1, 31)]
    bib, ctx, _ = _ctx(["as shown in [40] and [28-32]"], entries)
    assert [c.state for c in ctx[:1]] == ["unmatched"]
    assert [c.entry for c in ctx[1:]] == [28, 29, 30, None, None]
    assert "parse-incomplete" in completeness_flags(bib, ctx)


def test_link_to_missing_entry_flags_marker_gap() -> None:
    bib, ctx, _ = _ctx(["see [5](#b5)"], NUMERIC[:2])
    assert completeness_flags(bib, ctx) == ("marker-gap",)


def test_clean_document_has_no_flags() -> None:
    bib, ctx, _ = _ctx(["see [1], [2]"], NUMERIC[:3])
    assert completeness_flags(bib, ctx) == ()


def test_label_gaps_flag_parse_incomplete() -> None:
    entries = ["[1] A. A. T. 2001.", "[3] B. B. T. 2002."]
    bib, ctx, _ = _ctx(["see [1]"], entries)
    assert completeness_flags(bib, ctx) == ("parse-incomplete",)


def test_marker_token_capped_at_80_chars() -> None:
    long_name = "Abcdefghij" * 12
    body = [f"(see {long_name} et al., 2001) and [{'1' * 5}, " + ", ".join(["2"] * 30) + "]"]
    _, ctx, _ = _ctx(body, WANG)
    assert ctx and all(len(c.marker) <= 80 for c in ctx)
    _, ctx2, _ = _ctx([f"[{long_name}](#b1)"])
    assert ctx2[0].marker == f"{long_name}"[:80]


def test_descending_range_is_unmatched() -> None:
    _, ctx, _ = _ctx(["[9-3]"])
    assert [(c.entry, c.state) for c in ctx] == [(None, "unmatched")]


def test_bibliography_entries_are_not_searched_for_markers() -> None:
    entries = ["[1] A. A. See also [2]. T. 2001.", "[2] B. B. T. 2002."]
    _, ctx, distinct = _ctx([], entries)
    assert ctx == [] and distinct == 0


def test_cells_and_captions_are_searched_in_document_order() -> None:
    m = manifest(NUMERIC[:5], ["first [1]"])
    extra = (
        Anchor("t1", AnchorKind.TABLE, "s1", "| a |\n| - |\n| [2] |"),
        Anchor("t1.r1.c1", AnchorKind.CELL, "t1", "[2]"),
        Anchor("f1.cap", AnchorKind.FIGURE_CAPTION, "s1", "Fig. [3]"),
    )
    full = Manifest(m.anchors[:2] + extra + m.anchors[2:])
    bib = parse_bibliography(full)
    ctx, _ = find_contexts(full, bib)
    assert [(c.citing_anchor, c.entry) for c in ctx] == [
        ("s1.p1", 1),
        ("t1.r1.c1", 2),
        ("f1.cap", 3),
    ]


def test_paragraph_fallback_ignores_bibliography_paragraphs() -> None:
    m = manifest(
        ["[1] A. A. See [2]. T. 2001.", "[2] B. B. T. 2002."], ["body [2]"], b_anchors=False
    )
    bib = parse_bibliography(m)
    ctx, _ = find_contexts(m, bib)
    assert [(c.citing_anchor, c.entry) for c in ctx] == [("s1.p1", 2)]


def _timed(fn):  # type: ignore[no-untyped-def]
    import time

    t0 = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - t0


def test_unclosed_paren_is_linear_time() -> None:
    body = "(" + "2020 " * 8000
    (_, ctx, _), elapsed = _timed(lambda: _ctx([body]))
    assert elapsed < 0.5 and ctx == []


def test_unicode_author_year_marker() -> None:
    entries = ["Łukasiewicz, J. (1920). On logic. Journal.", "Émile, A. (2001). T. V."]
    _, ctx, _ = _ctx(["see Łukasiewicz (1920) and (Émile, 2001)"], entries)
    assert [(c.entry, c.state) for c in ctx] == [(1, "matched"), (2, "matched")]


def test_stray_digit_label_keeps_ordinal_mapping() -> None:
    entries = ["2018. Foo bar.", "Baz. Qux.", "Quux. Corge."]
    bib, ctx, _ = _ctx(["see [2] and [3]"], entries)
    assert [(c.entry, c.state) for c in ctx] == [(2, "matched"), (3, "matched")]
    assert completeness_flags(bib, ctx) == ()


def test_link_maps_through_anchor_ids_not_ordinals() -> None:
    m = manifest(NUMERIC[:2], ["a [x](#b1) b [y](#b3) c [z](#b2)"])
    bib = parse_bibliography(m)
    renamed = dataclasses.replace(
        bib, entries=(bib.entries[0], dataclasses.replace(bib.entries[1], anchor="b3"))
    )
    ctx, _ = find_contexts(m, renamed)
    assert [(c.entry, c.state) for c in ctx] == [
        (1, "matched"),
        (2, "matched"),
        (None, "unmatched"),
    ]


def test_range_with_em_dash_and_semicolon_list() -> None:
    _, ctx, _ = _ctx(["see [2—4] and [1; 5]"])
    assert [c.entry for c in ctx] == [2, 3, 4, 1, 5]


def test_numeric_bracket_followed_by_url_is_not_a_marker() -> None:
    _, ctx, _ = _ctx(["see [1](http://example.org/x)"])
    assert ctx == []


def test_same_author_year_suffix_is_ambiguous() -> None:
    entries = ["Wang, L. (2021a). First. V.", "Wang, L. (2021b). Second. V."]
    _, ctx, _ = _ctx(["see Wang (2021b)"], entries)
    assert [(c.entry, c.state) for c in ctx] == [(None, "ambiguous")]


def test_duplicate_numeric_labels_are_ambiguous() -> None:
    bib, ctx, _ = _ctx(["see [1]"], ["[1] A. A. T. 2001.", "[1] B. B. T. 2002."])
    assert [(c.entry, c.state) for c in ctx] == [(None, "ambiguous")]
    assert completeness_flags(bib, ctx) == ("parse-incomplete",)


def test_labels_not_one_to_k_flag_incomplete_without_marker() -> None:
    bib, ctx, _ = _ctx([], ["[1] A. A. T. 2001.", "[1] B. B. T. 2002."])
    assert completeness_flags(bib, ctx) == ("parse-incomplete",)
