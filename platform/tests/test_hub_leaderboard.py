"""Leaderboard payload (HS-50 to HS-55): vocabulary merging, own-model names, Part A and Part B
ranking, and the scope rule for baseline rows (HS-22). Pure over plain rows, plus one project test
for the approved-only rule."""

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.mining.spec import (
    EvidenceRule,
    MinerField,
    MinerRegime,
    MinerSpec,
    Population,
    QuoteKind,
    Selector,
)
from factory.model.cards import PropertyDef
from factory.services import hub_leaderboard as lb
from factory.services import hub_mining as hm
from factory.services.context import Project
from factory.services.properties import decide_property, propose_property
from tests.test_hub_mining import mk_row, mk_sets

RESULT_FIELDS = (
    "task",
    "model_name",
    "model_role",
    "dataset",
    "data_access",
    "setting",
    "metric",
    "value",
    "averaging",
    "result_quote",
)


def spec(name: str, fields: tuple[str, ...]) -> MinerSpec:
    return MinerSpec(
        name=name,
        version=1,
        selector=Selector(Population.INCLUDED_FINAL),
        fields=tuple(MinerField(f, "g", QuoteKind()) for f in fields),
        row_key_fields=(),
        row_anchor_fields=(),
        conditionals=(),
        evidence=EvidenceRule(1, True),
        procedure="rf-extract",
        regime=MinerRegime(2, 10, 0.8, 0.9),
        rationale="x",
    )


def res(eid: str, work: str, model: str, value: str, role: str = "own", **kv: str) -> hm.MRow:
    cells: dict[str, Any] = {
        "task": "classification",
        "model_name": model,
        "model_role": role,
        "dataset": "CT-RATE",
        "data_access": "public",
        "setting": "zero-shot",
        "metric": "auroc",
        "value": (value, "Table 2 says " + value, "t2"),
    }
    cells.update(kv)
    return mk_row(eid, work, "A", **cells)


def world(
    rows: list[hm.MRow],
    works: list[str],
    extra: dict[str, tuple[MinerSpec, list[hm.MRow]]] | None = None,
    published: dict[str, str] | None = None,
) -> hm.MiningData:
    specs = [spec("m-results", RESULT_FIELDS), *[s for s, _ in (extra or {}).values()]]
    rows_by = {"m-results": tuple(rows)} | {k: tuple(r) for k, (_s, r) in (extra or {}).items()}
    return hm.MiningData(
        miners=tuple(hm.miner_info(s, listed=True) for s in specs),
        rows=rows_by,
        models={},
        sets=mk_sets(works, [], {}),
        titles={w: f"Title {w}" for w in works},
        published=published or {},
    )


def vocab(dim: str, allowed: dict[str, tuple[str, ...]]) -> dict[str, PropertyDef]:
    return {
        dim: PropertyDef.model_validate(
            {
                "key": lb.DIMENSIONS[dim][1],
                "kind": "enum",
                "allowed": sorted(allowed),
                "match": "equal",
                "applies_to": "both",
                "value_aliases": allowed,
            }
        )
    }


def test_results_miner_is_found_by_its_fields() -> None:
    data = world([], ["w1"])
    found = lb.find_results_miner(data)
    assert found is not None and found.name == "m-results"
    other = hm.MiningData(
        miners=(hm.miner_info(spec("m-x", ("a", "b")), listed=True),),
        rows={},
        models={},
        sets=mk_sets(["w1"], [], {}),
        titles={},
    )
    assert lb.find_results_miner(other) is None
    assert lb.payload_from(other, {})["miner"] is None


def test_approved_aliases_merge_and_keep_both_spellings() -> None:
    rows = [
        res("e1", "w1", "A", "0.9", dataset="CT RATE (in-domain)"),
        res("e2", "w2", "B", "0.8", dataset="ctrate"),
        res("e3", "w3", "C", "0.7", dataset="Other"),
    ]
    v = vocab("dataset", {"ct-rate": ("CT RATE (in-domain)", "CT-Rate test")})
    out = lb.payload_from(world(rows, ["w1", "w2", "w3"]), v)
    by = {r["w"]: r["d"] for r in out["rows"]}
    assert by["w1"] == ["CT RATE (in-domain)", "ct-rate"]
    assert by["w2"] == ["ctrate", "ct-rate"]  # the allowed value itself merges by spelling key
    assert by["w3"] == ["Other", "Other"]  # no entry: as extracted
    assert out["vocabulary"]["dataset"]["approved"] is True
    assert out["vocabulary"]["metric"]["approved"] is False


def test_without_an_approved_property_values_stay_as_extracted() -> None:
    rows = [res("e1", "w1", "A", "0.9", dataset="CT RATE"), res("e2", "w2", "B", "0.8")]
    out = lb.payload_from(world(rows, ["w1", "w2"]), {})
    assert [r["d"] for r in out["rows"]] == [["CT RATE", "CT RATE"], ["CT-RATE", "CT-RATE"]]


def test_only_an_approved_property_reaches_the_page(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:
    definition = vocab("dataset", {"ct-rate": ("CT RATE",)})["dataset"]
    propose_property(project, agent, definition)
    assert lb.load_vocabulary(project) == {}  # a proposal does nothing
    decide_property(project, other_session_human, definition.key, "approve", "fits")
    assert lb.load_vocabulary(project) == {"dataset": definition}


def test_generic_own_names_follow_the_model_card_then_the_short_id() -> None:
    rows = [
        res("e1", "rf:alpha2025-x-aaaa1111", "Ours", "0.9"),
        res("e2", "rf:beta2025-x-bbbb2222", "Ours (7B)", "0.8"),
        res("e3", "rf:gamma2025-x-cccc3333", "Ours w/o pretraining", "0.7"),
        res("e4", "rf:delta2025-x-dddd4444", "our method", "0.6"),
        res("e5", "rf:alpha2025-x-aaaa1111", "Ours", "0.5", role="baseline"),
    ]
    works = [r.work for r in rows]
    card = spec("m-arch", ("model_name",))
    cards = [
        mk_row("c1", "rf:alpha2025-x-aaaa1111", "A", model_name="VoxForge"),
        mk_row("c2", "rf:beta2025-x-bbbb2222", "A", model_name="x" * 70),  # too long: unused
    ]
    out = lb.payload_from(world(rows, works, {"m-arch": (card, cards)}), {})
    by = {r["w"].split(":")[1].split("-")[0] + r["r"]: r for r in out["rows"]}
    assert by["alpha2025own"]["m"] == "VoxForge" and by["alpha2025own"]["mh"] == "card"
    assert by["alpha2025own"]["mr"] == "Ours"
    assert by["beta2025own"]["m"] == "beta2025-7B" and by["beta2025own"]["mh"] == "short-id"
    assert by["gamma2025own"]["m"] == "w/o pretraining"  # a qualifier is kept as given
    assert by["delta2025own"]["m"] == "delta2025"
    assert by["alpha2025baseline"]["m"] == "Ours"  # a baseline is never renamed
    assert out["name_sources"] == ["m-arch.model_name"]


def test_values_are_numbers_percent_is_scaled_and_junk_is_counted() -> None:
    rows = [
        res("e1", "w1", "A", "91.5%"),
        res("e2", "w2", "B", "0.5"),
        res("e3", "w3", "C", "n/a"),
        res("e4", "w4", "D", "250"),
    ]
    out = lb.payload_from(world(rows, ["w1", "w2", "w3", "w4"]), {})
    assert sorted(r["v"] for r in out["rows"]) == [0.5, 0.915]
    assert out["skipped"] == {"value": 2}


def test_part_a_best_per_model_and_paper_and_minimum_three_models() -> None:
    rows = [
        res("e1", "w1", "A", "0.70"),
        res("e2", "w1", "A", "0.90"),  # best of (A, w1)
        res("e3", "w2", "B", "0.80"),
        res("e4", "w3", "C", "0.60"),
        res("e5", "w4", "D", "0.99", dataset="Private-X", data_access="private"),
        res("e6", "w5", "E", "0.95", setting="fine-tuned"),
        res("e7", "w6", "F", "0.55", setting="fine-tuned"),
    ]
    out = lb.payload_from(world(rows, [f"w{i}" for i in range(1, 7)]), {})
    [table] = out["whole"]["tables"]  # fine-tuned has 2 models, the private table is not public
    assert (table["dataset"], table["setting"], table["models"]) == ("CT-RATE", "zero-shot", 3)
    assert [(e["model"], e["value"]) for e in table["top"]] == [("A", 0.9), ("B", 0.8), ("C", 0.6)]


def test_access_is_inherited_only_when_the_dataset_is_stated_public() -> None:
    rows = [
        res("e1", "w1", "A", "0.9", data_access="public", dataset="D1"),
        res("e2", "w2", "B", "0.8", data_access="not-stated", dataset="D1"),
        res("e3", "w3", "C", "0.7", data_access="not-stated", dataset="D2"),
        res("e4", "w4", "D", "0.6", data_access="public", dataset="D3"),
        res("e5", "w5", "E", "0.6", data_access="mixed", dataset="D3"),
        res("e6", "w6", "F", "0.6", data_access="not-stated", dataset="D3"),
    ]
    out = lb.payload_from(world(rows, [f"w{i}" for i in range(1, 7)]), {})
    assert {r["w"]: r["ap"] for r in out["rows"]} == {
        "w1": "public",
        "w2": "public",
        "w3": "not-stated",
        "w4": "public",
        "w5": "mixed",
        "w6": "not-stated",
    }


def baseline_world() -> hm.MiningData:
    rows = [
        res(f"b{i}", f"w{i}", "ResNet", str(0.5 + i / 100), role="baseline") for i in range(1, 7)
    ]
    rows += [res("o1", "w1", "Mine", "0.9"), res("o2", "w9", "Mine2", "0.8")]
    pub = {"w1": "2026-01", "w2": "2026-02", "w3": "2026-03", "w4": "2026-04", "w5": "2025-12"}
    pub |= {"w6": "2025-11", "w9": "2026-02"}
    return world(rows, ["w1", "w2", "w3", "w4", "w5", "w6", "w9"], published=pub)


def test_part_b_counts_papers_and_spread() -> None:
    out = lb.payload_from(baseline_world(), {})
    [b] = out["whole"]["baselines"]
    assert (b["model"], b["papers"], b["min"], b["max"]) == ("ResNet", 6, 0.51, 0.56)
    assert b["median"] == 0.535
    assert out["whole"]["hidden_baseline_rows"] == 0


def test_scope_hides_baseline_rows_of_out_of_scope_papers_and_counts_them() -> None:
    rows = lb.payload_from(baseline_world(), {})["rows"]
    in_scope = {"w1", "w2", "w3", "w4", "w9"}  # w5, w6 are out
    out = lb.rank(rows, in_scope)
    assert out["hidden_baseline_rows"] == 2
    assert out["hidden_own_rows"] == 0
    [b] = out["baselines"]
    assert b["papers"] == 4 and b["min"] == 0.51 and b["max"] == 0.54  # never re-attributed
    # one more paper out of scope: the baseline falls under the four-paper rule, 3 rows hidden
    out = lb.rank(rows, {"w1", "w2", "w3"})
    assert out["hidden_baseline_rows"] == 3 and out["baselines"] == []
    # the count equals a recount over the rows
    assert out["hidden_baseline_rows"] == sum(
        1 for r in rows if r["r"] == "baseline" and r["w"] not in {"w1", "w2", "w3"}
    )
    # an own row of an out-of-scope paper is counted apart, not as a baseline row
    assert lb.rank(rows, {"w2"})["hidden_own_rows"] == 2


def test_rows_carry_the_source_work_and_its_date_and_quote() -> None:
    out = lb.payload_from(baseline_world(), {})
    r = next(x for x in out["rows"] if x["w"] == "w1" and x["r"] == "own")
    assert (r["p"], r["q"], r["a"]) == ("2026-01", "Table 2 says 0.9", "t2")
    assert out["works"][0] == {"id": "w1", "published": "2026-01"}


def test_a_none_final_value_becomes_empty_text_never_the_word_none() -> None:
    from types import SimpleNamespace

    field = SimpleNamespace(value=None, quote=None, anchor=None)
    final = SimpleNamespace(work_id="w1", fields={"setting": field})
    data = SimpleNamespace(
        sets=SimpleNamespace(included=frozenset({"w1"}), duplicate_mapped=()), rows={}
    )
    recs = lb._records(data, SimpleNamespace(name="m"), [final])  # type: ignore[arg-type]
    assert [r.cells["setting"].value for r in recs] == [""]
