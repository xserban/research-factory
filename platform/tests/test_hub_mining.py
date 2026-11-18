"""Hub mining payloads (plan hub-ui, step 5): miners, agreement, grid, coverage, holes, codebook."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.mining.spec import (
    EnumKind,
    EvidenceRule,
    MinerField,
    MinerRegime,
    MinerSpec,
    Population,
    QuoteKind,
    Selector,
    spec_to_json,
)
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec
from factory.services import hub_mining as hm
from factory.services import site_corpus
from factory.services.context import Project
from factory.services.hub_payloads import Sets, reconcile_sets
from factory.services.mining import register_miner

# ---------------------------------------------------------------- builders


def mk_spec(
    name: str = "m-test",
    version: int = 1,
    row_key: tuple[str, ...] = (),
    extra: tuple[MinerField, ...] = (),
) -> MinerSpec:
    fields = (
        MinerField("stance", "g1", EnumKind(("pro", "con", "none")), required=True),
        MinerField("shape", "g1", EnumKind(("loop", "line"))),
        MinerField("evidence", "g2", QuoteKind(), compared=False),
        *extra,
    )
    return MinerSpec(
        name=name,
        version=version,
        selector=Selector(Population.INCLUDED_FINAL),
        fields=fields,
        row_key_fields=row_key,
        row_anchor_fields=(),
        conditionals=(),
        evidence=EvidenceRule(1, True),
        procedure="rf-extract",
        regime=MinerRegime(2, 10, 0.8, 0.9),
        rationale="Reads the stance.",
    )


def mk_row(eid: str, work: str, label: str, **kv: Any) -> hm.MRow:
    cells: dict[str, hm.Cell] = {}
    for k, v in kv.items():
        value, quote, anchor = (v, "", "") if isinstance(v, str) else v
        cells[k] = hm.Cell(value, quote, anchor)
    return hm.MRow(eid, work, label, cells)


def mk_sets(included: list[str], mined: list[str], canonical_of: dict[str, str]) -> Sets:
    return reconcile_sets(
        included, mined, canonical_of, {"x9": ("full_text", "EX01"), "x8": ("full_text", "EX06")}
    )


def mk_data(
    rows: list[hm.MRow],
    sets: Sets,
    spec: MinerSpec | None = None,
    models: dict[str, tuple[str, ...]] | None = None,
    platform: dict[str, tuple[float | None, float | None]] | None = None,
) -> hm.MiningData:
    s = spec or mk_spec()
    return hm.MiningData(
        miners=(hm.miner_info(s, listed=True),),
        rows={s.name: tuple(rows)},
        models=models or {},
        sets=sets,
        titles={w: f"Title {w}" for w in sets.included},
        platform=platform or {},
        codebook={},
    )


# ---------------------------------------------------------------- agreement


def test_exact_agreement_is_set_equality_on_hand_case() -> None:
    info = hm.miner_info(mk_spec(), listed=True)
    a = {
        "w1": [mk_row("a1", "w1", "A", stance="pro")],
        "w2": [mk_row("a2", "w2", "A", stance="pro")],
        "w3": [
            mk_row("a3", "w3", "A", stance="pro"),
            mk_row("a4", "w3", "A", stance="con"),
        ],
        "w4": [mk_row("a5", "w4", "A", shape="loop")],  # stance empty in both
        "w5": [mk_row("a6", "w5", "A", stance="pro")],
        "w6": [mk_row("a7", "w6", "A", stance="pro")],  # not read by B
    }
    b = {
        "w1": [mk_row("b1", "w1", "B", stance="pro")],
        "w2": [mk_row("b2", "w2", "B", stance="con")],
        "w3": [
            mk_row("b3", "w3", "B", stance="con"),
            mk_row("b4", "w3", "B", stance="pro"),
        ],
        "w4": [mk_row("b5", "w4", "B", shape="loop")],
        "w5": [mk_row("b6", "w5", "B", shape="line")],  # B has no stance
    }
    got = hm.exact_agreement(info.fields, a, b)
    # stance: w1 agree, w2 differ, w3 equal sets, w5 one-sided -> 2 of 4; w4 has no value at all
    assert (got["stance"].agreed, got["stance"].total) == (2, 4)
    assert got["stance"].rate == 0.5
    assert (got["shape"].agreed, got["shape"].total) == (1, 2)  # w4 agree, w5 only B
    assert "evidence" not in got  # quote fields are never compared
    assert got["shape"].works_both == 5


def test_exact_agreement_rate_is_none_without_comparisons() -> None:
    info = hm.miner_info(mk_spec(), listed=True)
    got = hm.exact_agreement(info.fields, {}, {})
    assert got["stance"].total == 0 and got["stance"].rate is None


# ---------------------------------------------------------------- attribution (rule 4.1)


def test_duplicate_rows_attributed_to_canonical_and_excluded_counted_apart() -> None:
    sets = mk_sets(
        ["c1", "c2", "c3", "c4"],
        ["c1", "d2", "c3", "d3", "x9", "x8"],
        {"d2": "c2", "d3": "c3"},
    )
    rows = [
        mk_row("r1", "c1", "A", stance="pro"),
        mk_row("r2", "d2", "A", stance="con"),  # duplicate of c2, c2 unmined -> shown on c2
        mk_row("r3", "c3", "A", stance="pro"),
        mk_row("r4", "d3", "A", stance="con"),  # duplicate of c3, c3 read itself -> shadowed
        mk_row("r5", "x9", "A", stance="pro"),  # excluded at full text
        mk_row("r6", "x8", "A", stance="pro"),
        mk_row("r7", "x8", "B", stance="pro"),
    ]
    att = hm.attribute_rows(rows, sets)
    assert sorted(att.by_pass["A"]) == ["c1", "c2", "c3"]  # c4 not read
    assert [r.eid for r in att.by_pass["A"]["c2"]] == ["r2"]
    assert [r.eid for r in att.by_pass["A"]["c3"]] == ["r3"]  # own rows only
    assert att.mapped == (("d2", "c2"),)
    assert att.shadowed_rows == 1
    assert att.excluded_rows == 3 and att.excluded_works == ("x8", "x9")
    out = hm.miners(mk_data(rows, sets))["miners"][0]
    assert out["pass_a"]["works"] == 3  # corpus counts exclude x9 and x8
    assert out["pass_a"]["rows"] == 3
    assert out["off_corpus"] == {
        "mapped_from_duplicates": [{"duplicate": "d2", "canonical": "c2"}],
        "shadowed_duplicate_rows": 1,
        "excluded_works": ["x8", "x9"],
        "excluded_rows": 3,
    }
    assert out["distributions"]["stance"]["pro"] == {"rows": 2, "works": 2}
    assert "con" in out["distributions"]["stance"]  # c2's row via its duplicate
    assert out["distributions"]["stance"]["con"] == {"rows": 1, "works": 1}


# ---------------------------------------------------------------- miners


def two_pass_data(
    platform: dict[str, tuple[float | None, float | None]] | None = None,
) -> hm.MiningData:
    sets = mk_sets(["w1", "w2", "w3"], ["w1", "w2", "w3"], {})
    rows = [
        mk_row("a1", "w1", "A", stance=("pro", "we are pro", "s1.p1"), shape="loop"),
        mk_row("a2", "w2", "A", stance="con", shape="line"),
        mk_row("a3", "w3", "A", stance="pro"),
        mk_row("b1", "w1", "B", stance="pro", shape="loop"),
        mk_row("b2", "w2", "B", stance="pro", shape="line"),
    ]
    return mk_data(
        rows,
        sets,
        models={"m-test|A": ("claude-sonnet-5-5",), "m-test|B": ("claude-haiku-5",)},
        platform=platform if platform is not None else {"m-test": (0.5, 0.75)},
    )


def test_miners_names_exact_fairer_and_platform_measures() -> None:
    out = hm.miners(two_pass_data())
    m = out["miners"][0]
    assert m["name"] == "m-test" and m["version"] == 1 and m["rationale"] == "Reads the stance."
    assert m["works_both"] == 2
    assert m["pass_a"] == {"rows": 3, "works": 3, "models": ["claude-sonnet-5-5"]}
    assert m["pass_b"]["works"] == 2 and m["pass_b"]["models"] == ["claude-haiku-5"]
    ag = m["agreement"]
    assert set(ag) == {"exact", "fairer", "platform"}
    assert ag["exact"]["measure"] == "set-equality (included works)"
    assert ag["exact"]["by_field"]["stance"] == {"agreed": 1, "total": 2, "rate": 0.5}
    assert ag["exact"]["overall"] == {"agreed": 3, "total": 4, "rate": 0.75}
    assert ag["fairer"]["by_field"]["stance"]["agreed"] == 1
    assert ag["fairer"]["by_field"]["stance"]["total"] == 2
    assert (ag["platform"]["all_rows"], ag["platform"]["aligned_rows"]) == (0.5, 0.75)
    assert ag["platform"]["measure"] != ag["exact"]["measure"] != ag["fairer"]["measure"]
    fld = {f["name"]: f for f in m["fields"]}
    assert fld["stance"] == {
        "name": "stance",
        "type": "enum",
        "values": ["pro", "con", "none"],
        "required": True,
        "group": "g1",
        "compared": True,
    }
    assert fld["evidence"]["type"] == "quote"
    assert out["by_model_pair"] == [
        {
            "a": "claude-sonnet-5-5",
            "b": "claude-haiku-5",
            "miners": ["m-test"],
            "works_both": 2,
            "agreed": 3,
            "total": 4,
            "rate": 0.75,
        }
    ]
    assert m["multi_row"] is False
    assert out["corpus"]["included"] == 3
    json.dumps(out)


def test_examples_carry_quotes_and_are_capped_at_four() -> None:
    sets = mk_sets([f"w{i}" for i in range(7)], [f"w{i}" for i in range(7)], {})
    rows = [
        mk_row(f"a{i}", f"w{i}", "A", stance=("pro", f"quote {i}", f"s{i}")) for i in range(7)
    ] + [mk_row("a9", "w0", "A", stance="con")]  # second row of w0, no quote
    m = hm.miners(mk_data(rows, sets))["miners"][0]
    assert len(m["examples"]) == 4
    first = m["examples"][0]
    assert first["work"] == "w0" and first["title"] == "Title w0"
    assert first["cells"]["stance"] == {"value": "pro", "quote": "quote 0", "anchor": "s0"}
    assert m["multi_row"] is False  # 8 rows over 7 works is below the ratio
    assert m["rows_per_work"] == round(8 / 7, 3)


def test_multi_row_flag_uses_the_platform_ratio() -> None:
    sets = mk_sets(["w1", "w2"], ["w1", "w2"], {})
    rows = [mk_row(f"a{i}", w, "A", stance="pro") for i, w in enumerate(["w1"] * 3 + ["w2"] * 2)]
    assert hm.miners(mk_data(rows, sets))["miners"][0]["multi_row"] is True


# ---------------------------------------------------------------- grid


def test_grid_pages_and_quotes_are_present_iff_recorded() -> None:
    d = two_pass_data()
    cols = ["m-test.stance", "m-test.shape"]
    page1 = hm.data_grid(d, cols, page=1, page_size=2)
    assert page1["total"] == 3 and page1["pages"] == 2 and page1["page"] == 1
    assert [r["id"] for r in page1["rows"]] == ["w1", "w2"]
    w1 = page1["rows"][0]
    assert w1["title"] == "Title w1"
    assert w1["cells"]["m-test.stance"] == {
        "v": "pro",
        "q": "we are pro",
        "a": "s1.p1",
        "n": 1,
    }
    assert w1["cells"]["m-test.shape"]["q"] == ""  # no quote recorded: empty, never invented
    page2 = hm.data_grid(d, cols, page=2, page_size=2)
    assert [r["id"] for r in page2["rows"]] == ["w3"]
    assert page2["rows"][0]["cells"]["m-test.shape"] is None  # read, no value
    assert page1["columns"] == [
        {"key": "m-test.stance", "miner": "m-test", "field": "stance", "type": "enum"},
        {"key": "m-test.shape", "miner": "m-test", "field": "shape", "type": "enum"},
    ]


def test_grid_default_columns_catalogue_and_errors() -> None:
    d = two_pass_data()
    g = hm.data_grid(d, None, page=1, page_size=50)
    keys = [c["key"] for c in g["catalogue"]]
    assert keys == ["m-test.stance", "m-test.shape", "m-test.evidence"]
    assert g["catalogue"][0]["filled"] == 3  # works with a value
    assert g["catalogue"][2]["filled"] == 0
    assert [c["key"] for c in g["columns"]] == keys[:2]  # only columns with values by default
    with pytest.raises(ValueError, match="unknown column"):
        hm.data_grid(d, ["m-test.nope"], page=1, page_size=10)
    # out-of-range page is empty, never an error
    assert hm.data_grid(d, keys, page=9, page_size=2)["rows"] == []
    with pytest.raises(ValueError, match="page"):
        hm.data_grid(d, keys, page=0, page_size=2)


def test_grid_cell_for_a_work_read_through_its_duplicate() -> None:
    sets = mk_sets(["c2"], ["d2"], {"d2": "c2"})
    rows = [mk_row("r", "d2", "A", stance=("con", "q", "a"))]
    g = hm.data_grid(mk_data(rows, sets), ["m-test.stance"], page=1, page_size=5)
    assert g["rows"][0]["id"] == "c2"
    assert g["rows"][0]["cells"]["m-test.stance"]["v"] == "con"
    assert g["rows"][0]["via"] == {"m-test": "d2"}


# ---------------------------------------------------------------- coverage and holes


def test_coverage_encodes_passes_as_indexes_into_the_work_list() -> None:
    d = two_pass_data()
    c = hm.coverage(d)
    assert c["works"] == ["w1", "w2", "w3"]
    m = c["miners"][0]
    assert m["name"] == "m-test" and m["a"] == [0, 1, 2] and m["b"] == [0, 1]
    assert m["both"] == 2 and m["only_a"] == 1 and m["unread"] == 0
    assert c["not_read_by_any"] == []


def test_coverage_lists_works_no_miner_read() -> None:
    sets = mk_sets(["w1", "w2"], ["w1"], {})
    c = hm.coverage(mk_data([mk_row("a", "w1", "A", stance="pro")], sets))
    assert c["not_read_by_any"] == [1]
    assert c["miners"][0]["unread"] == 1


def test_holes_per_field_and_works_with_most_missing_required_fields() -> None:
    sets = mk_sets(["w1", "w2", "w3", "w4"], ["w1", "w2", "w3"], {})
    rows = [
        mk_row("a1", "w1", "A", stance="pro", shape="loop"),
        mk_row("a2", "w2", "A", shape="line"),  # stance (required) missing
        mk_row("a3", "w3", "A"),  # stance and shape missing
    ]
    h = hm.holes(mk_data(rows, sets))
    f = {x["key"]: x for x in h["fields"]}
    assert f["m-test.stance"]["read"] == 3 and f["m-test.stance"]["missing"] == 2
    assert f["m-test.stance"]["share_of_read"] == pytest.approx(2 / 3)
    assert f["m-test.stance"]["unread"] == 1
    assert f["m-test.stance"]["share_of_included"] == pytest.approx(3 / 4)  # missing + unread
    assert f["m-test.shape"]["missing"] == 1
    assert f["m-test.stance"]["required"] is True
    assert h["works"][0] == {"id": "w2", "title": "Title w2", "missing": ["m-test.stance"]}
    assert [w["id"] for w in h["works"]] == ["w2", "w3"]  # required fields only; ties by id


# ---------------------------------------------------------------- codebook


def test_codebook_maps_technique_codes_to_stage_and_label() -> None:
    def tax(name: str, cats: list[tuple[str, str]]) -> TaxonomySpec:
        return TaxonomySpec(
            name=name,
            version=1,
            dimensions=(
                Dimension(
                    id="technique",
                    title="t",
                    question="q",
                    cardinality="multi",
                    categories=tuple(Category(i, n, "def") for i, n in cats),
                ),
            ),
        )

    cb = hm.codebook_from(
        {
            "t-tech-literature-review": tax("t-tech-literature-review", [("lr-01", "API search")]),
            "t-tech-paper-writing": tax("t-tech-paper-writing", [("pw-01", "Draft with LLM")]),
            "t-agentic-layer": tax("t-agentic-layer", [("core", "Core")]),
        }
    )
    assert cb == {
        "lr-01": {"stage": "literature-review", "label": "API search"},
        "pw-01": {"stage": "paper-writing", "label": "Draft with LLM"},
    }


# ---------------------------------------------------------------- payload and loader


def test_payload_is_json_safe_and_carries_methods() -> None:
    p = hm.mining_payload_from(two_pass_data())
    json.dumps(p)
    assert set(p) >= {"miners", "coverage", "holes", "codebook", "columns", "methods", "sets"}
    assert "exact" in p["methods"] and "fairer" in p["methods"] and "platform" in p["methods"]
    assert len(p["sets"]["included"]) == 3


def _insert_row(project: Project, eid: str, work: str, label: str, schema: str) -> None:
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO extraction_rows (extraction_id, scope, pack, cited_extraction_id, "
                "cited_ordinal, cited_marker, work_id, pass_label, task_id, protocol_id, "
                "schema_ref, document_id, conversion_id, row_key, supersedes, superseded_by, "
                "event_id) VALUES (:e, 'm-test', NULL, NULL, NULL, NULL, :w, :p, 't', 'p', "
                ":s, 'd', 'c', :e, NULL, NULL, 'e')"
            ),
            {"e": eid, "w": work, "p": label, "s": schema},
        )


def _insert_field(project: Project, eid: str, name: str, value: str, quote: str = "") -> None:
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO extraction_fields (extraction_id, field, value, quote, anchor, "
                "reported_in, copy_marker, reproduced) VALUES (:e, :f, :v, :q, 'an', 'r', 0, 0)"
            ),
            {"e": eid, "f": name, "v": value, "q": quote},
        )


def test_loader_reads_latest_version_rows_models_and_applies_the_sets(
    project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_miner(project, agent, spec_to_json(mk_spec("m-test", 1, ("stance",))))
    register_miner(project, agent, spec_to_json(mk_spec("m-test", 2, ("stance",))))
    monkeypatch.setattr(site_corpus, "_listed_schemas", lambda _p: {})
    with project.index._engine.begin() as conn:
        for w in ("w1", "d2"):
            conn.execute(
                text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, :d, 'e')"),
                {"w": w, "d": json.dumps({"title": f"T {w}"})},
            )
        for label, model in (("A", "claude-sonnet-5-5"), ("B", "claude-haiku-5")):
            conn.execute(
                text(
                    "INSERT INTO extraction_sessions (session, scope, pass_label, model, "
                    "calibration) VALUES (:s, 'm-test', :p, :m, 0)"
                ),
                {"s": f"s{label}", "p": label, "m": model},
            )
    _insert_row(project, "old", "w1", "A", "m-test@1")  # an older version's row: not read
    _insert_field(project, "old", "stance", "con")
    _insert_row(project, "e1", "w1", "A", "m-test@2")
    _insert_field(project, "e1", "stance", "pro", "the quote")
    _insert_row(project, "e2", "d2", "A", "m-test@2")
    _insert_field(project, "e2", "stance", "con")
    _insert_row(project, "e3", "w1", "B", "m-test@2")
    _insert_field(project, "e3", "stance", "pro")
    sets = mk_sets(["w1", "c2"], ["w1", "d2"], {"d2": "c2"})
    d = hm.load_mining_data(project, sets=sets, with_platform=False)
    assert [(m.name, m.version) for m in d.miners] == [("m-test", 2)]
    assert d.models == {"m-test|A": ("claude-sonnet-5-5",), "m-test|B": ("claude-haiku-5",)}
    assert {r.eid for r in d.rows["m-test"]} == {"e1", "e2", "e3"}
    out = hm.miners(d)["miners"][0]
    assert out["version"] == 2 and out["pass_a"]["works"] == 2  # w1, and c2 through d2
    g = hm.data_grid(d, ["m-test.stance"], page=1, page_size=10)
    by_id = {r["id"]: r for r in g["rows"]}
    assert by_id["w1"]["cells"]["m-test.stance"]["q"] == "the quote"
    assert by_id["w1"]["title"] == "T w1"
    assert by_id["c2"]["via"] == {"m-test": "d2"}
    assert hm.mining_payload(project, sets=sets)["miners"]["miners"][0]["name"] == "m-test"
