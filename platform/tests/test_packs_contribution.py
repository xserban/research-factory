"""Pack attributes, the generic `contribution` pack v1 and generic verification (G2-A, task 1).

The document is converted from hand-written Markdown, so each test fixes the anchored text.
"""

import hashlib
import re
from typing import Any

import pytest

from factory.document.anchorise import anchorise
from factory.document.anchors import Manifest, parse_manifest
from factory.extraction.numbers import normalise_text
from factory.extraction.verify import pack_row_key, row_key
from factory.model.extraction import ROW_KEY_RE, FieldInput, StoredField
from factory.packs import ML_BENCHMARK_V1, Check, Conditional, get_pack
from factory.packs.contribution import (
    ABSENT_KINDS,
    CONTRIBUTION_PACK,
    CONTRIBUTION_V1,
    ITEM_KINDS,
)
from factory.packs.ml_benchmark import CITATION_PATTERNS
from factory.services.extraction_verify import RowVerdict, verify_row_in

MD = """# Study

We build on Linear Attention and improve over Linformer by a wide margin.

## Results

Top-1 accuracy reaches 82.4% on ImageNet.

## Limits

Our method fails on long sequences.
"""
P1, RES, LIM = "s0.p1", "s0.1.p1", "s0.2.p1"
CNV = "cnv_1"
DECLARED = {f.name for f in CONTRIBUTION_V1.fields}


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return parse_manifest(anchorise(MD))


def Q(value: str, anchor: str = P1, quote: str | None = None) -> FieldInput:
    """A text field quoted from ``anchor`` (the quote defaults to the value itself)."""
    return FieldInput(value=value, anchor=anchor, quote=quote if quote is not None else value)


def plain(value: Any) -> FieldInput:
    return FieldInput(value=value)


def as_input(**kw: Any) -> dict[str, FieldInput]:
    return {k: v if isinstance(v, FieldInput) else plain(v) for k, v in kw.items()}


def run(manifest: Manifest, **kw: Any) -> RowVerdict:
    return verify_row_in(CONTRIBUTION_V1, DECLARED, as_input(**kw), CNV, manifest, set())


def reasons_in(manifest: Manifest, **kw: Any) -> dict[str, str]:
    return {i.field: i.reason for i in run(manifest, **kw).issues}


def stored(**kw: Any) -> dict[str, StoredField]:
    out: dict[str, StoredField] = {}
    for k, v in kw.items():
        if isinstance(v, tuple):
            value, anchor = v
            out[k] = StoredField(value=value, anchor=anchor, quote=value, copy_marker=False)
        else:
            out[k] = StoredField(value=v, copy_marker=False)
    return out


# --- pack shape -------------------------------------------------------------------------------


def test_ml_benchmark_unchanged() -> None:
    p = ML_BENCHMARK_V1
    assert p.row_key_fields == p.row_anchor_fields == () and p.compared_fields is None
    assert p.conditionals == () and all(f.allowed == () for f in p.fields)


def test_contribution_pack_shape() -> None:
    p = get_pack("contribution", 1)
    assert p is CONTRIBUTION_V1 and p.name == CONTRIBUTION_PACK
    assert [f.name for f in p.fields] == [
        "item_kind",
        "absent_kind",
        "name",
        "statement",
        "compared_to",
        "cited_entry",
        "metric",
        "value",
        "result_row",
    ]
    item_kind, absent_kind = p.field("item_kind"), p.field("absent_kind")
    value, name = p.field("value"), p.field("name")
    assert item_kind is not None and absent_kind is not None
    assert value is not None and name is not None
    assert p.required == ("item_kind",) and item_kind.allowed == ITEM_KINDS
    assert absent_kind.allowed == ABSENT_KINDS == ("base-idea", "limitation")
    assert ITEM_KINDS == ("base-idea", "addition", "result", "limitation", "not-stated")
    assert value.check is Check.NUMBER and name.check is Check.TEXT_IN_QUOTE
    assert value.units == ("%", "fraction", "")
    assert p.compared_fields is not None
    assert set(p.compared_fields) <= {f.name for f in p.fields}
    assert "statement" not in p.compared_fields
    assert p.compared_fields == ("item_kind", "absent_kind", "name", "cited_entry", "value")
    assert p.row_key_fields == ("item_kind", "absent_kind", "name", "metric")
    assert p.row_anchor_fields == ("name", "statement", "compared_to")
    assert p.default_comparability_keys == () and p.citation_patterns == CITATION_PATTERNS


def test_conditional_fields_name_existing_fields() -> None:
    names = {f.name for f in CONTRIBUTION_V1.fields}
    assert CONTRIBUTION_V1.conditionals
    for c in CONTRIBUTION_V1.conditionals:
        assert isinstance(c, Conditional)
        assert c.field in names and c.when in names and c.rule in ("required", "forbidden")
        when = CONTRIBUTION_V1.field(c.when)
        assert when is not None and set(c.values) <= set(when.allowed)
    keyed = set(CONTRIBUTION_V1.row_key_fields) | set(CONTRIBUTION_V1.row_anchor_fields)
    assert keyed <= names


def test_contribution_digest_is_pinned() -> None:
    digest = hashlib.sha256(repr(CONTRIBUTION_V1).encode()).hexdigest()
    assert digest == "5e8eb3706e962766be1e71acec6322879b36dd06628c4fbc45f3bb9e5a56f7cd", (
        "packs are versioned: add a new version"
    )


# --- allowed values and conditionals -----------------------------------------------------------


def test_value_not_allowed(manifest: Manifest) -> None:
    assert reasons_in(manifest, item_kind="improvement") == {
        "fields.item_kind.value": "value-not-allowed"
    }


def test_allowed_compares_normalised_value(manifest: Manifest) -> None:
    v = run(manifest, item_kind=" Not-Stated ", absent_kind="base-idea")
    assert v.issues == [] and v.fields is not None


def test_allowed_value_stored_normalised(manifest: Manifest) -> None:
    """Review F3: a field with ``allowed`` stores the canonical allowed value."""
    v = run(manifest, item_kind="Not-Stated ", absent_kind=" Base-Idea")
    assert v.fields is not None
    assert v.fields["item_kind"].value == "not-stated"
    assert v.fields["absent_kind"].value == "base-idea"
    same = run(manifest, item_kind="not-stated", absent_kind="base-idea")
    assert same.fields == v.fields and same.row_key == v.row_key


def test_free_text_field_stored_raw(manifest: Manifest) -> None:
    v = run(manifest, item_kind="limitation", statement=Q("Our method fails", LIM))
    assert v.fields is not None and v.fields["statement"].value == "Our method fails"


def test_not_stated_needs_absent_kind_and_forbids_content(manifest: Manifest) -> None:
    assert "fields.absent_kind" in reasons_in(manifest, item_kind="not-stated")
    assert reasons_in(
        manifest, item_kind="not-stated", absent_kind="base-idea", name=Q("Linformer")
    ) == {"fields.name": "not-allowed-for-kind"}
    ok = run(manifest, item_kind="not-stated", absent_kind="limitation")
    assert ok.issues == [] and ok.row_key is not None


def test_absent_kind_forbidden_unless_not_stated(manifest: Manifest) -> None:
    r = reasons_in(
        manifest,
        item_kind="base-idea",
        absent_kind="base-idea",
        name=Q("Linear Attention"),
        statement=Q("We build on Linear Attention"),
    )
    assert r == {"fields.absent_kind": "not-allowed-for-kind"}


def test_absent_kind_refuses_addition_and_result(manifest: Manifest) -> None:
    """Acceptance 4."""
    for kind in ("addition", "result"):
        r = reasons_in(manifest, item_kind="not-stated", absent_kind=kind)
        assert r["fields.absent_kind.value"] == "value-not-allowed"


def test_result_needs_metric_and_value(manifest: Manifest) -> None:
    r = reasons_in(manifest, item_kind="result", statement=Q("reaches 82.4%", RES))
    assert r == {"fields.metric": "required", "fields.value": "required"}
    full = run(
        manifest,
        item_kind="result",
        statement=Q("reaches 82.4%", RES),
        metric=Q("Top-1 accuracy", RES),
        value=FieldInput(value="82.4", unit="%", anchor=RES, quote="reaches 82.4%"),
    )
    assert full.issues == [] and full.fields is not None
    assert full.fields["value"].canonical == "82.4"


def test_result_fields_forbidden_for_other_kinds(manifest: Manifest) -> None:
    r = reasons_in(
        manifest,
        item_kind="limitation",
        statement=Q("fails on long sequences", LIM),
        metric=Q("Top-1 accuracy", RES),
        compared_to=Q("Linformer"),
        cited_entry=3,
    )
    assert r == {
        "fields.metric": "not-allowed-for-kind",
        "fields.compared_to": "not-allowed-for-kind",
        "fields.cited_entry": "not-allowed-for-kind",
    }


def test_base_idea_needs_name_and_statement(manifest: Manifest) -> None:
    r = reasons_in(manifest, item_kind="base-idea")
    assert r == {"fields.name": "required", "fields.statement": "required"}
    ok = run(
        manifest,
        item_kind="base-idea",
        name=Q("linear attention", quote="We build on Linear Attention"),
        statement=Q("We build on Linear Attention"),
        cited_entry=12,
    )
    assert ok.issues == [] and ok.fields is not None and ok.row_key is not None


def test_addition_may_name_compared_to(manifest: Manifest) -> None:
    v = run(
        manifest,
        item_kind="addition",
        name=Q("Linear Attention"),
        statement=Q("improve over Linformer"),
        compared_to=Q("Linformer"),
    )
    assert v.issues == []


def test_text_in_quote_still_checked(manifest: Manifest) -> None:
    r = reasons_in(
        manifest,
        item_kind="addition",
        name=FieldInput(value="Performer", anchor=P1, quote="Linear Attention"),
        statement=Q("improve over Linformer"),
    )
    assert r == {"fields.name.value": "text-not-in-quote"}


def test_conditionals_skipped_when_item_kind_invalid(manifest: Manifest) -> None:
    r = reasons_in(manifest, item_kind="improvement", absent_kind="base-idea", name=Q("Linformer"))
    assert r == {"fields.item_kind.value": "value-not-allowed"}


def test_conditionals_skipped_when_item_kind_missing(manifest: Manifest) -> None:
    assert reasons_in(manifest, name=Q("Linformer")) == {"fields.item_kind": "required"}


def test_keyed_pack_does_not_need_value_field(manifest: Manifest) -> None:
    v = run(manifest, item_kind="limitation", statement=Q("fails on long sequences", LIM))
    assert v.issues == [] and v.fields is not None and v.row_key is not None
    assert v.row_key == pack_row_key(CONTRIBUTION_V1, CNV, v.fields)


# --- row key -----------------------------------------------------------------------------------


def test_row_key_normalises_name_and_uses_anchor() -> None:
    """Review Focus 4."""
    k1 = pack_row_key(
        CONTRIBUTION_V1, CNV, stored(item_kind="base-idea", name=("Linear Attention", "s2.p1"))
    )
    k2 = pack_row_key(
        CONTRIBUTION_V1, CNV, stored(item_kind="base-idea", name=("linear  attention", "s2.p1"))
    )
    k3 = pack_row_key(
        CONTRIBUTION_V1, CNV, stored(item_kind="base-idea", name=("Linear Attention", "s3.p2"))
    )
    assert k1 == k2 != k3 and re.fullmatch(ROW_KEY_RE, k1)
    k4 = pack_row_key(
        CONTRIBUTION_V1, "cnv_2", stored(item_kind="base-idea", name=("Linear Attention", "s2.p1"))
    )
    assert k4 != k1


def test_row_key_formula() -> None:
    fields = stored(
        item_kind="addition",
        statement=("improve", "s2.p4"),
        compared_to=("Linformer", "s2.p5"),
    )
    material = "\x1f".join([CNV, "s2.p4", "addition", "", "", ""])
    expected = "rk_" + hashlib.sha256(material.encode()).hexdigest()[:12]
    assert pack_row_key(CONTRIBUTION_V1, CNV, fields) == expected


def test_results_at_same_anchor_keyed_by_metric() -> None:
    """Review F1: several results quoted from one paragraph do not collide."""

    def result(metric: str, value: str) -> dict[str, StoredField]:
        return stored(
            item_kind="result",
            statement=("reaches 82.4%", "s0.1.p1"),
            metric=(metric, "s0.1.p1"),
            value=(value, "s0.1.p1"),
        )

    top1 = pack_row_key(CONTRIBUTION_V1, CNV, result("Top-1 accuracy", "82.4"))
    top5 = pack_row_key(CONTRIBUTION_V1, CNV, result("Top-5 accuracy", "82.4"))
    again = pack_row_key(CONTRIBUTION_V1, CNV, result("top-1  Accuracy", "82.4"))
    assert top1 != top5 and top1 == again


def test_row_key_anchor_follows_anchor_field_order() -> None:
    a = stored(item_kind="addition", name=("X", "s1.p1"), statement=("X does", "s2.p2"))
    b = stored(item_kind="addition", name=("X", "s1.p1"), statement=("X does", "s9.p9"))
    assert pack_row_key(CONTRIBUTION_V1, CNV, a) == pack_row_key(CONTRIBUTION_V1, CNV, b)


def test_not_stated_row_key_has_no_anchor() -> None:
    base = stored(item_kind="not-stated", absent_kind="base-idea")
    lim = stored(item_kind="not-stated", absent_kind="limitation")
    kb = pack_row_key(CONTRIBUTION_V1, CNV, base)
    material = "\x1f".join([CNV, "-", normalise_text("not-stated"), "base-idea", "", ""])
    assert kb == "rk_" + hashlib.sha256(material.encode()).hexdigest()[:12]
    assert kb != pack_row_key(CONTRIBUTION_V1, CNV, lim)


def test_ml_benchmark_row_key_unchanged() -> None:
    value = StoredField(
        value="82.4", unit="%", anchor="t1", cell="t1.r3.c2", quote="82.40", copy_marker=False
    )
    fields = {"value": value, "metric": StoredField(value="top-1", copy_marker=False)}
    assert pack_row_key(ML_BENCHMARK_V1, CNV, fields) == row_key(CNV, value)
    with pytest.raises(ValueError):
        pack_row_key(ML_BENCHMARK_V1, CNV, {"metric": fields["metric"]})
