"""The marker rule and the item evidence rule (plan G2-B, task 1; pure)."""

from factory.lineage.cited import item_evidence, marker_check
from factory.lineage.refs import ContextView
from factory.model.extraction import StoredField


def _sf(value: str, anchor: str | None = None, quote: str | None = None) -> StoredField:
    return StoredField(value=value, anchor=anchor, quote=quote, copy_marker=False)


def test_marker_states() -> None:  # Review Focus 1
    ctx = [
        ContextView("s2.p1", 3, "[3, 5]", "matched"),
        ContextView("s2.p1", 5, "[3, 5]", "matched"),
    ]
    assert marker_check("as in [3, 5], we", "s2.p1", 5, ctx) == "matched"
    assert marker_check("as in [3, 5], we", "s2.p1", 4, ctx) == "mismatch"
    assert marker_check("we follow linear attention", "s2.p1", 5, ctx) == "absent"
    assert marker_check("as in [3, 5], we", "s4.p1", 5, ctx) == "absent"  # another anchor


def test_marker_token_compared_after_normalisation() -> None:
    ctx = [ContextView("s2.p1", 2, "(Wang et al., 2021)", "matched")]
    assert marker_check("as in (WANG   et al.,\n2021) we", "s2.p1", 2, ctx) == "matched"


def test_ambiguous_context_does_not_map() -> None:
    ctx = [
        ContextView("s2.p1", None, "[3]", "ambiguous"),
        ContextView("s2.p1", None, "[4]", "unmatched"),
    ]
    assert marker_check("see [3] and [4]", "s2.p1", 3, ctx) == "absent"


def test_one_marker_may_map_to_the_entry_among_others() -> None:
    ctx = [
        ContextView("s2.p1", 7, "[7]", "matched"),
        ContextView("s2.p1", 3, "[3]", "matched"),
    ]
    assert marker_check("[7] and [3]", "s2.p1", 3, ctx) == "matched"
    assert marker_check("only [7]", "s2.p1", 3, ctx) == "mismatch"


def test_item_evidence_order() -> None:
    fields = {
        "name": _sf("A", "s1.p2", "quote of a"),
        "statement": _sf("S", "s1.p1", "quote of s"),
    }
    assert item_evidence(fields) == ("s1.p2", "quote of a")
    assert item_evidence({"statement": fields["statement"]}) == ("s1.p1", "quote of s")
    compared = {"compared_to": _sf("C", "s3.p1", "quote of c")}
    assert item_evidence(compared) == ("s3.p1", "quote of c")


def test_item_evidence_skips_a_field_without_anchor_and_none_for_not_stated() -> None:
    fields = {"name": _sf("A"), "statement": _sf("S", "s1.p1", "q")}
    assert item_evidence(fields) == ("s1.p1", "q")
    assert item_evidence({"item_kind": _sf("not-stated"), "absent_kind": _sf("base-idea")}) is None
