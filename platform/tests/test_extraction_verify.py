"""Deterministic verification of extraction fields and rows (plan 2D, task 4).

The document is converted from hand-written Markdown, so each test fixes the anchored text.
Issue reasons are compared by their fixed vocabulary; they never carry document text.
"""

from typing import Any

import pytest

from factory.document.anchorise import anchorise
from factory.document.anchors import Manifest, parse_manifest
from factory.document.registry import ConverterRegistry
from factory.errors import ValidationIssue
from factory.extraction.verify import (
    FieldEntry,
    VerifiedField,
    cell_row,
    row_key,
    verify_field,
)
from factory.packs import ML_BENCHMARK_V1 as PACK
from factory.packs import FieldDef
from factory.services.context import Project
from factory.services.document_convert import convert_documents
from factory.services.extraction_verify import RowVerdict, verify_row, verify_row_in
from factory.services.search import list_works
from tests.document_helpers import fetched_document, promoted_works
from tests.test_document_read import PassThroughConverter

DOC_TEXT = "SECRETDOCWORD"
MD = f"""# Study

Our model reaches 82.4% top-1 accuracy on ImageNet-1K. {DOC_TEXT}

Plain count of 22,100,000 parameters and DeiT-S [41] reaches 79.8% in prior work.

| Method | Top-1 | Params |
| --- | --- | --- |
| DeiT-S [41] | 79.8 | 22.1M |
| Ours | 82.40 | 25M |

| Other | Val |
| --- | --- |
| x | 1 |
"""
DECLARED = {f.name for f in PACK.fields}


def fdef(name: str) -> FieldDef:
    found = PACK.field(name)
    assert found is not None
    return found


@pytest.fixture
def manifest() -> Manifest:
    return parse_manifest(anchorise(MD))


def entry(
    value: Any,
    unit: str | None,
    anchor: str | None,
    cell: str | None,
    quote: str | None,
    **kw: Any,
) -> FieldEntry:
    return FieldEntry(value=value, unit=unit, anchor=anchor, cell=cell, quote=quote, **kw)


def base_row(**override: FieldEntry) -> dict[str, FieldEntry]:
    row = {
        "method_name": entry("Ours", None, "t1", "t1.r3.c1", "Ours"),
        "task": entry("classification", None, None, None, None),
        "dataset": entry("ImageNet-1K", None, "s1.p1", None, "ImageNet-1K"),
        "metric": entry("top-1", None, "s1.p1", None, "top-1 accuracy"),
        "value": entry("82.4", "%", "t1", "t1.r3.c2", "82.40"),
    }
    row.update(override)
    return row


def run(manifest: Manifest, row: dict[str, FieldEntry], cnv: str = "cnv_1") -> RowVerdict:
    return verify_row_in(PACK, DECLARED, row, cnv, manifest, set())


def reasons(manifest: Manifest, **override: FieldEntry) -> dict[str, str]:
    return {i.field: i.reason for i in run(manifest, base_row(**override)).issues}


def field_reasons(manifest: Manifest, name: str, e: FieldEntry) -> list[str]:
    out = verify_field(PACK, fdef(name), e, manifest)
    return [] if isinstance(out, VerifiedField) else out


def test_number_in_cell_accepted_and_canonical(manifest: Manifest) -> None:
    v = run(manifest, base_row())
    assert v.issues == [] and v.fields is not None
    assert v.fields["value"].canonical == "82.4"
    assert v.row_key is not None and v.row_key.startswith("rk_")


def test_number_absent_from_quote_and_cell_rejected(manifest: Manifest) -> None:
    """Acceptance 6."""
    r = reasons(manifest, value=entry("82.5", "%", "t1", "t1.r3.c2", "82.40"))
    assert r == {"fields.value.value": "number-not-in-cell"}


def test_number_matched_as_whole_token(manifest: Manifest) -> None:
    e = entry("82.4", "%", "s1.p1", None, "reaches 182.45 top-1")
    out = field_reasons(manifest, "value", e)
    assert "number-not-in-text" in out and "quote-not-in-anchor" in out
    # a verbatim quote that only has the longer number is still rejected
    m = parse_manifest(anchorise("# 1 S\n\nScore 182.45 here.\n"))
    assert field_reasons(m, "value", entry("82.4", "%", "s1.p1", None, "182.45")) == [
        "number-not-in-text"
    ]


def test_quote_in_paragraph_without_cell_ok(manifest: Manifest) -> None:
    e = entry("82.4", "%", "s1.p1", None, "82.4% top-1")
    assert field_reasons(manifest, "value", e) == []


def test_table_anchor_without_cell_rejected(manifest: Manifest) -> None:
    """Review Focus 2."""
    assert "number-needs-cell" in field_reasons(
        manifest, "value", entry("82.4", "%", "t1", None, "82.40")
    )


def test_cell_resolves_to_exactly_one_cell_and_text_checked(manifest: Manifest) -> None:
    """Acceptance 7."""
    assert "cell-unknown" in field_reasons(
        manifest, "value", entry("82.4", "%", "t1", "t1.r9.c9", "82.40")
    )
    assert "cell-not-in-anchor-table" in field_reasons(
        manifest, "value", entry("1", None, "t1", "t2.r2.c2", "1")
    )
    assert "cell-unknown" in field_reasons(  # a non-cell id is not a cell
        manifest, "value", entry("82.4", "%", "t1", "s1.p1", "82.40")
    )
    # the quote has no 79.8; the cell shows 82.40
    assert "number-not-in-cell" in field_reasons(
        manifest, "value", entry("79.8", "%", "t1", "t1.r3.c2", "Ours | 82.40")
    )


def test_cell_as_anchor_itself(manifest: Manifest) -> None:
    assert field_reasons(manifest, "value", entry("82.4", "%", "t1.r3.c2", None, "82.40")) == []
    bad = entry("82.4", "%", "t1.r3.c2", "t1.r2.c2", "82.40")
    assert "cell-not-in-anchor-table" in field_reasons(manifest, "value", bad)


def test_quote_spanning_two_cells_rejected(manifest: Manifest) -> None:
    assert "quote-not-in-anchor" in field_reasons(
        manifest, "value", entry("82.4", "%", "t1", "t1.r3.c2", "Ours 82.40")
    )


def test_unknown_anchor_and_missing_evidence(manifest: Manifest) -> None:
    assert "anchor-unknown" in field_reasons(manifest, "value", entry("1", None, "t9", None, "1"))
    assert "anchor-required" in field_reasons(manifest, "value", entry("1", None, None, None, "1"))
    assert "quote-required" in field_reasons(
        manifest, "value", entry("1", None, "s1.p1", None, None)
    )


def test_unit_suffix_mismatch(manifest: Manifest) -> None:
    bad = entry("22.1", "G", "t1", "t1.r2.c3", "22.1M")
    assert "unit-suffix-mismatch" in field_reasons(manifest, "params", bad)
    good = verify_field(
        PACK, fdef("params"), entry("22.1", "M", "t1", "t1.r2.c3", "22.1M"), manifest
    )
    assert isinstance(good, VerifiedField) and good.stored.canonical == "22100000"


def test_percent_token_does_not_match_count_field(manifest: Manifest) -> None:
    out = field_reasons(manifest, "params", entry("82.4", "M", "s1.p1", None, "82.4% top-1"))
    assert out == ["unit-suffix-mismatch"]
    # a fraction is not a percentage
    assert "unit-suffix-mismatch" in field_reasons(
        manifest, "value", entry("82.4", "fraction", "s1.p1", None, "82.4% top-1")
    )


def test_thousands_separator_and_count(manifest: Manifest) -> None:
    e = entry("22,100,000", None, "s1.p2", None, "22,100,000 parameters")
    good = verify_field(PACK, fdef("params"), e, manifest)
    assert isinstance(good, VerifiedField) and good.stored.canonical == "22100000"


def test_text_in_quote(manifest: Manifest) -> None:
    assert "text-not-in-quote" in field_reasons(
        manifest, "dataset", entry("CIFAR", None, "s1.p1", None, "top-1 accuracy")
    )
    assert reasons(manifest) == {}


def test_undeclared_field_rejected_valid_fields_reported(manifest: Manifest) -> None:
    """Acceptance 5."""
    r = reasons(manifest, depth=entry(3, None, None, None, None))
    assert r == {"fields.depth": "not declared in the protocol's extraction schema"}
    row = base_row(depth=entry(3, None, None, None, None))
    row["value"] = entry("82.5", "%", "t1", "t1.r3.c2", "82.40")
    verdict = run(manifest, row)
    assert {i.field for i in verdict.issues} == {"fields.depth", "fields.value.value"}
    assert verdict.fields is None and verdict.row_key is None


def test_missing_required_field_rejected(manifest: Manifest) -> None:
    row = base_row()
    del row["metric"]
    assert run(manifest, row).issues == [ValidationIssue("fields.metric", "required")]


def test_kind_errors(manifest: Manifest) -> None:
    r = reasons(manifest, value=entry("82.4%", "%", "t1", "t1.r3.c2", "82.40"))
    assert list(r) == ["fields.value.value"]
    r = reasons(manifest, value=entry("82.4", "mm", "t1", "t1.r3.c2", "82.40"))
    assert list(r) == ["fields.value.unit"]
    r = reasons(manifest, is_proposed=entry("yes", None, None, None, None))
    assert list(r) == ["fields.is_proposed.value"]
    r = reasons(manifest, batch_size=entry(1.5, None, "s1.p1", None, "1"))
    assert list(r) == ["fields.batch_size.value"]
    assert reasons(manifest, is_proposed=entry(True, None, None, None, None)) == {}


def test_copy_marker_from_row_cells(manifest: Manifest) -> None:
    """Review Focus 5: DeiT-S's row carries [41] although declared own."""
    own = entry("79.8", "%", "t1", "t1.r2.c2", "79.8", reported_in="own")
    v = run(manifest, base_row(value=own))
    assert v.fields is not None
    f = v.fields["value"]
    assert f.copy_marker is True and f.reported_in == "own"
    v2 = run(manifest, base_row())
    assert v2.fields is not None and v2.fields["value"].copy_marker is False


def test_copy_marker_from_quote_when_no_cell(manifest: Manifest) -> None:
    e = entry("79.8", "%", "s1.p2", None, "DeiT-S [41] reaches 79.8%")
    out = verify_field(PACK, fdef("value"), e, manifest)
    assert isinstance(out, VerifiedField) and out.stored.copy_marker is True
    e2 = entry("82.4", "%", "s1.p1", None, "82.4% top-1")
    out2 = verify_field(PACK, fdef("value"), e2, manifest)
    assert isinstance(out2, VerifiedField) and out2.stored.copy_marker is False


def test_cell_row(manifest: Manifest) -> None:
    assert [a.id for a in cell_row(manifest, "t1.r2.c2")] == ["t1.r2.c1", "t1.r2.c2", "t1.r2.c3"]
    assert cell_row(manifest, "t1.r9.c1") == []


def test_cited_work_must_exist_in_corpus(manifest: Manifest) -> None:
    e = entry("82.4", "%", "t1", "t1.r3.c2", "82.40", cited_work="w_known")
    ok = verify_row_in(PACK, DECLARED, base_row(value=e), "cnv_1", manifest, {"w_known"})
    assert ok.issues == []
    bad = run(manifest, base_row(value=e))
    assert [i.field for i in bad.issues] == ["fields.value.cited_work"]


def test_ligature_and_nbsp_quote_accepted() -> None:
    m = parse_manifest(anchorise("# 1 S\n\nThe e\ufb03cient model reaches 82.4%\u00a0top-1.\n"))
    e = entry("82.4", "%", "s1.p1", None, "efficient model reaches 82.4% top-1")
    assert field_reasons(m, "value", e) == []


def test_reasons_never_contain_document_text(manifest: Manifest) -> None:
    row = base_row(
        value=entry("82.5", "%", "t1", "t1.r3.c2", f"{DOC_TEXT} 82.40"),
        dataset=entry("x", None, "s1.p1", None, DOC_TEXT),
        depth=entry(3, None, None, None, DOC_TEXT),
    )
    verdict = run(manifest, row)
    assert verdict.issues
    assert all(DOC_TEXT not in str(i) for i in verdict.issues)


def test_row_key_equal_across_passes_and_depends_on_conversion(manifest: Manifest) -> None:
    a = run(manifest, base_row())
    b = run(manifest, dict(reversed(list(base_row().items()))))
    c = run(manifest, base_row(), "cnv_2")
    assert a.row_key == b.row_key and a.row_key != c.row_key
    # without a cell the key rests on the anchor and the canonical value
    nocell = entry("82.4", "%", "s1.p1", None, "82.4% top-1")
    d = run(manifest, base_row(value=nocell))
    assert d.fields is not None and d.row_key is not None and d.row_key != a.row_key
    assert row_key("cnv_1", d.fields["value"]) == d.row_key


@pytest.mark.usefixtures("corpus")
def test_verify_row_against_a_converted_document(project: Project) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, MD.encode())
    summary = convert_documents(project, ConverterRegistry([PassThroughConverter()]))
    cnv = next(o.conversion_id for o in summary.outcomes if o.conversion_id)
    ok = verify_row(project, PACK, DECLARED, base_row(), cnv)
    assert ok.issues == [] and ok.fields is not None
    cited = list_works(project)[0].id
    row = base_row(value=entry("82.4", "%", "t1", "t1.r3.c2", "82.40", cited_work=cited))
    assert verify_row(project, PACK, DECLARED, row, cnv).issues == []
    row = base_row(value=entry("82.4", "%", "t1", "t1.r3.c2", "82.40", cited_work="w_nope"))
    assert [i.field for i in verify_row(project, PACK, DECLARED, row, cnv).issues] == [
        "fields.value.cited_work"
    ]
