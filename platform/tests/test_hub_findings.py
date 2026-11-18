"""Hub findings (plan hub-ui, step 5): the eight finding cards, the research cycle, openness,
claims by validation. Every figure is pinned to the rows of a hand-built fixture."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from factory.mining.spec import (
    EnumKind,
    EvidenceRule,
    MinerField,
    MinerRegime,
    MinerSpec,
    Population,
    Selector,
)
from factory.services import hub_findings as hf
from factory.services import hub_mining as hm
from factory.services.context import Project
from factory.services.hub_payloads import reconcile_sets
from tests.test_hub_mining import mk_row

LONG = "This is a sentence of forty or more characters used as evidence."


def spec_of(name: str, fields: list[str]) -> MinerSpec:
    return MinerSpec(
        name=name,
        version=1,
        selector=Selector(Population.INCLUDED_FINAL),
        fields=tuple(MinerField(f, "g", EnumKind(("x",))) for f in fields),
        row_key_fields=(fields[0],),
        row_anchor_fields=(),
        conditionals=(),
        evidence=EvidenceRule(1, True),
        procedure="rf-extract",
        regime=MinerRegime(2, 10, 0.8, 0.9),
    )


W = [f"w{i:02d}" for i in range(1, 11)]
TECH = {
    "lr-01": {"stage": "literature-review", "label": "API search"},
    "lr-02": {"stage": "literature-review", "label": "Snowballing"},
    "lr-03": {"stage": "literature-review", "label": "Unused technique"},
    "pw-01": {"stage": "paper-writing", "label": "Draft with LLM"},
    "pw-02": {"stage": "paper-writing", "label": "Unused writing"},
}


def table(prefix: str, spec: str, per_work: dict[str, list[dict[str, Any]]]) -> list[hm.MRow]:
    out: list[hm.MRow] = []
    n = 0
    for w, rows in per_work.items():
        for kv in rows:
            n += 1
            out.append(mk_row(f"{prefix}{n:03d}", w, "A", **kv))
    return out


def fixture_data() -> hm.MiningData:
    sets = reconcile_sets(W, W, {})
    mapping = table(
        "m",
        "m-mapping",
        {
            "w01": [
                {
                    "human_position": ("none", LONG, "s1"),
                    "automated_span": ("full-lifecycle", LONG, "s2"),
                    "process_shape": ("iterative-loop", LONG, "s3"),
                    "human_vs_automated": ("comparable", LONG, "s4"),
                }
            ],
            "w02": [
                {
                    "human_position": "none",
                    "automated_span": "full-lifecycle",
                    "process_shape": "iterative-loop",
                    "human_vs_automated": "system-better",
                }
            ],
            "w03": [
                {
                    "human_position": "none",
                    "automated_span": "literature-only",
                    "process_shape": "iterative-loop",
                    "human_vs_automated": "humans-better",
                }
            ],
            "w04": [
                {
                    "human_position": "feedback",
                    "automated_span": "literature-only",
                    "process_shape": "iterative-loop",
                    "human_vs_automated": "not-compared",
                }
            ],
            "w05": [
                {
                    "human_position": "feedback",
                    "automated_span": "literature-only",
                    "process_shape": "linear-pipeline",
                    "human_vs_automated": "not-compared",
                }
            ],
            "w06": [
                {
                    "human_position": "feedback",
                    "automated_span": "ideation-only",
                    "human_vs_automated": "not-compared",
                }
            ],
            "w07": [{"human_position": "feedback", "automated_span": "not-determinable"}],
            "w08": [{"human_position": "feedback"}],
            "w09": [{}],  # read, nothing recorded
        },
    )
    summary = table(
        "s",
        "m-summary",
        {
            "w01": [
                {
                    "validation_level": ("simulation-or-benchmark", LONG, "v1"),
                    "contribution_type": "new-system",
                }
            ],
            "w02": [
                {"validation_level": "simulation-or-benchmark", "contribution_type": "new-system"}
            ],
            "w03": [
                {
                    "validation_level": "simulation-or-benchmark",
                    "contribution_type": "new-benchmark",
                }
            ],
            "w04": [
                {"validation_level": "real-experiment", "contribution_type": "empirical-study"}
            ],
            "w05": [{"validation_level": "deployment", "contribution_type": "new-system"}],
            "w06": [{"validation_level": "none", "contribution_type": "new-system"}],
            "w07": [{"contribution_type": "new-system"}],  # no validation: not in the matrix
        },
    )
    release = table(
        "r",
        "m-release",
        {
            "w01": [
                {"release_statement": "see appendix"},  # first row has no status
                {"data_status": ("released", LONG, "r1"), "code_status": "released"},
            ],
            "w02": [{"data_status": "released", "code_status": "promised"}],
            "w03": [{"data_status": "available-on-request", "code_status": "not-released"}],
            "w04": [{"data_status": "not-released"}],
        },
    )
    all_stages = [
        "literature-review",
        "ideation-hypothesis",
        "experiment-design",
        "implementation-execution",
        "data-analysis",
        "paper-writing",
        "review-verification",
    ]

    def srow(stage: str, mode: str, quote: str = "") -> dict[str, Any]:
        return {"stage": stage, "mode": (mode, quote, "a1")}

    stages = table(
        "t",
        "m-stages",
        {
            "w01": [srow("literature-review", "automated", LONG), srow("paper-writing", "human")],
            "w02": [
                srow("literature-review", "automated"),
                srow("paper-writing", "automated", LONG),
            ],
            "w03": [srow("literature-review", "automated"), srow("paper-writing", "mentioned")],
            "w04": [srow("literature-review", "human")],
            "w05": [srow(s, "automated") for s in all_stages if s != "paper-writing"],
            "w06": [srow(s, "automated") for s in all_stages if s != "paper-writing"],
        },
    )
    lit = table(
        "l",
        "m-tech-literature-review",
        {
            "w01": [{"category": ("technique/lr-01", LONG, "l1")}],
            "w02": [{"category": "technique/lr-01"}],
            "w03": [{"category": "technique/lr-02"}],
            "w04": [{"category": "technique/not-stated"}],
        },
    )
    writing = table(
        "p", "m-tech-paper-writing", {"w01": [{"category": ("technique/pw-01", LONG, "p1")}]}
    )
    specs = [
        spec_of(
            "m-mapping", ["human_position", "automated_span", "process_shape", "human_vs_automated"]
        ),
        spec_of("m-summary", ["validation_level", "contribution_type"]),
        spec_of("m-release", ["data_status", "code_status", "release_statement"]),
        spec_of("m-stages", ["stage", "mode"]),
        spec_of("m-tech-literature-review", ["category"]),
        spec_of("m-tech-paper-writing", ["category"]),
    ]
    return hm.MiningData(
        miners=tuple(hm.miner_info(s, listed=True) for s in specs),
        rows={
            "m-mapping": tuple(mapping),
            "m-summary": tuple(summary),
            "m-release": tuple(release),
            "m-stages": tuple(stages),
            "m-tech-literature-review": tuple(lit),
            "m-tech-paper-writing": tuple(writing),
        },
        models={},
        sets=sets,
        titles={w: f"Title {w}" for w in W},
        codebook=TECH,
    )


LAYERS = {w: "core" for w in W[:4]} | {w: "applied" for w in W[4:]}
RANK = {"w03": 5, "w02": 3}


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    return hf.findings_from(fixture_data(), layers=LAYERS, rank=RANK)


def card(p: dict[str, Any], rule: str) -> dict[str, Any]:
    (c,) = [c for c in p["cards"] if c["rule"] == rule]
    return dict(c)


def test_eight_cards_in_order_with_no_digits_in_templates(payload: dict[str, Any]) -> None:
    assert [c["rule"] for c in payload["cards"]] == [
        "no_human",
        "full_lifecycle",
        "least_automated_stage",
        "most_varied_stage",
        "iterative_loop",
        "benchmark_validation",
        "compare_with_humans",
        "data_release",
    ]
    for c in payload["cards"]:
        assert not re.search(r"\d", c["template"]), c["rule"]
        assert not re.search(r"\d", c["how"]), c["rule"]
        assert c["available"] is True
        assert c["say"] and "{" not in c["say"]
    json.dumps(payload)


def test_no_human_card(payload: dict[str, Any]) -> None:
    c = card(payload, "no_human")
    # 3 of the 8 works with a human position say none; w09 has no value and is not counted
    assert (c["numerator"], c["denominator"]) == (3, 8)
    assert c["ids"] == ["w03", "w02", "w01"]  # ranked by cited-here, then id
    assert c["source"] == [{"miner": "m-mapping", "field": "human_position"}]
    ev = c["evidence"]
    assert [e["work"] for e in ev] == ["w01"]  # only w01 has a quote of 40+ characters
    assert ev[0] == {
        "work": "w01",
        "title": "Title w01",
        "miner": "m-mapping",
        "field": "human_position",
        "value": "none",
        "quote": LONG,
        "anchor": "s1",
    }
    assert c["say"] == "About four in ten of the systems run with no human in the loop."
    assert "{share_cap}" in c["template"]
    assert c["population"]["of_included"] == 10 and c["population"]["read"] == 9
    assert c["population"]["with_value"] == 8


def test_full_lifecycle_card_names_the_largest_alternative(payload: dict[str, Any]) -> None:
    c = card(payload, "full_lifecycle")
    assert (c["numerator"], c["denominator"]) == (2, 7)  # w01..w07 carry a span
    assert c["ids"] == ["w02", "w01"]
    assert c["extra"]["alternative"] == {
        "value": "literature-only",
        "n": 3,
        "ids": ["w03", "w04", "w05"],
    }  # not-determinable is never the alternative


def test_least_automated_stage_card_and_cycle(payload: dict[str, Any]) -> None:
    c = card(payload, "least_automated_stage")
    # six works have stage records; paper-writing is automated by w02 only
    assert c["extra"]["stage"] == "paper-writing"
    assert (c["numerator"], c["denominator"]) == (1, 6)
    assert c["ids"] == ["w02"]
    assert c["extra"]["most_automated"] == {"stage": "literature-review", "n": 5, "share": 5 / 6}
    assert c["evidence"][0]["quote"] == LONG and c["evidence"][0]["field"] == "mode"
    cyc = {s["stage"]: s for s in payload["cycle"]["stages"]}
    assert [s["stage"] for s in payload["cycle"]["stages"]][:2] == [
        "literature-review",
        "ideation-hypothesis",
    ]
    assert cyc["literature-review"]["automated"] == 5 and cyc["literature-review"]["of"] == 6
    assert cyc["literature-review"]["share"] == 5 / 6
    assert sorted(cyc["ideation-hypothesis"]["ids"]) == ["w05", "w06"]
    assert cyc["paper-writing"]["ids"] == ["w02"]


def test_most_varied_stage_counts_used_techniques_of_the_codebook(
    payload: dict[str, Any],
) -> None:
    c = card(payload, "most_varied_stage")
    assert c["extra"]["stage"] == "literature-review"
    assert (c["numerator"], c["denominator"]) == (2, 3)  # two of three listed are used
    assert sorted(c["ids"]) == ["w01", "w02", "w03"]  # w04 said not-stated
    assert c["population"]["read"] == 4 and c["population"]["layer"] == "core"
    assert "4 core papers" in c["population"]["text"]
    lit = {s["stage"]: s for s in payload["cycle"]["stages"]}["literature-review"]
    assert lit["techniques_listed"] == 3 and lit["techniques_used"] == 2
    assert lit["not_stated"] == 1 and lit["other"] == 0 and lit["core"] == 4
    assert [(t["code"], t["label"], t["n"]) for t in lit["techniques"]] == [
        ("lr-01", "API search", 2),
        ("lr-02", "Snowballing", 1),
        ("lr-03", "Unused technique", 0),
    ]
    assert lit["techniques"][0]["ids"] == ["w01", "w02"]
    assert lit["techniques"][0]["quotes"] == {"w01": LONG}  # only quotes that were recorded


def test_iterative_loop_card(payload: dict[str, Any]) -> None:
    c = card(payload, "iterative_loop")
    assert (c["numerator"], c["denominator"]) == (4, 5)
    assert sorted(c["ids"]) == ["w01", "w02", "w03", "w04"]


def test_benchmark_validation_card_with_real_and_deployment(payload: dict[str, Any]) -> None:
    c = card(payload, "benchmark_validation")
    assert (c["numerator"], c["denominator"]) == (3, 6)  # w07 has no validation
    assert c["extra"]["real_experiment"] == {"n": 1, "ids": ["w04"]}
    assert c["extra"]["deployment"] == {"n": 1, "ids": ["w05"]}
    assert "{real_percent}" in c["template"]


def test_compare_with_humans_card(payload: dict[str, Any]) -> None:
    c = card(payload, "compare_with_humans")
    assert (c["numerator"], c["denominator"]) == (3, 6)  # comparable, system-better, humans-better
    assert sorted(c["ids"]) == ["w01", "w02", "w03"]


def test_data_release_card_uses_the_first_value_over_all_rows(payload: dict[str, Any]) -> None:
    c = card(payload, "data_release")
    # four works carry a data status (w01's status is on its second row); two released it
    assert (c["numerator"], c["denominator"]) == (2, 4)
    assert sorted(c["ids"]) == ["w01", "w02"]
    code = c["extra"]["code_released"]
    assert (code["n"], code["denominator"], code["ids"]) == (1, 3, ["w01"])
    assert c["population"]["read"] == 4 and c["population"]["of_included"] == 10
    assert c["population"]["complete"] is False
    assert c["evidence"][0]["work"] == "w01" and c["evidence"][0]["field"] == "data_status"


def test_openness_groups_by_layer_with_merged_partial_status(payload: dict[str, Any]) -> None:
    o = payload["openness"]
    groups = {g["key"]: g for g in o["groups"]}
    assert list(groups) == ["all", "core"]  # only layers with a release record
    seg = {s["key"]: s for s in groups["all"]["data"]["segments"]}
    assert seg["released"]["n"] == 2 and seg["partial"]["ids"] == ["w03"]
    assert seg["no"]["n"] == 1 and groups["all"]["data"]["n"] == 4
    assert groups["all"]["code"]["n"] == 3
    assert {s["key"]: s["n"] for s in groups["all"]["code"]["segments"]} == {
        "released": 1,
        "promised": 1,
        "no": 1,
    }
    assert groups["core"]["n"] == 4


def test_claims_by_validation_matrix(payload: dict[str, Any]) -> None:
    m = payload["claims"]
    assert m["n"] == 6  # works with both a contribution type and a validation level
    assert m["columns"][0]["key"] == "none" and m["columns"][-1]["key"] == "deployment"
    rows = {r["key"]: r for r in m["rows"]}
    assert m["rows"][0]["key"] == "new-system"  # largest first
    assert rows["new-system"]["n"] == 4
    assert rows["new-system"]["cells"]["simulation-or-benchmark"] == {
        "n": 2,
        "ids": ["w01", "w02"],
    }
    assert rows["new-system"]["cells"]["deployment"]["ids"] == ["w05"]
    assert m["column_totals"]["simulation-or-benchmark"] == 3
    assert "w07" not in {w for r in m["rows"] for c in r["cells"].values() for w in c["ids"]}


def test_a_miner_that_did_not_run_gives_an_unavailable_card_not_a_zero() -> None:
    d = fixture_data()
    d = hm.MiningData(
        miners=tuple(i for i in d.miners if i.name != "m-summary"),
        rows={k: v for k, v in d.rows.items() if k != "m-summary"},
        models=d.models,
        sets=d.sets,
        titles=d.titles,
        codebook=d.codebook,
    )
    c = card(hf.findings_from(d), "benchmark_validation")
    assert c["available"] is False and c["say"] is None and c["denominator"] == 0
    assert c["numerator"] == 0 and c["ids"] == []


def test_share_words_follow_the_demo_rule() -> None:
    assert hf.share_words(1 / 3) == "a third"
    assert hf.share_words(0.34) == "a third"
    assert hf.share_words(0.45) == "45%"
    assert hf.share_words(0.52) == "about half"
    assert hf.share_words(0.0) == "0%"


def test_profile_fields_override_the_default_human_and_span_columns() -> None:
    d = fixture_data()
    p = hf.findings_from(
        d, fields={"human": ("m-mapping", "process_shape"), "span": ("m-mapping", "automated_span")}
    )
    c = card(p, "no_human")
    assert c["source"] == [{"miner": "m-mapping", "field": "process_shape"}]
    assert c["denominator"] == 5  # works with a process shape; none has the value 'none'
    assert c["numerator"] == 0


def test_profile_fields_default_and_custom_profile(project: Project) -> None:
    assert hf.profile_fields(project) == {
        "human": ("m-mapping", "human_position"),
        "span": ("m-mapping", "automated_span"),
        "shape": ("m-mapping", "process_shape"),
    }
    (project.paths.dir / "site-profile.json").write_text(
        json.dumps({"roles": {"map": "m-map2"}, "dims": [["human", "Human", "map", "role"]]}),
        encoding="utf-8",
    )
    assert hf.profile_fields(project) == {"human": ("m-map2", "role")}


def test_findings_payload_uses_layers_cited_here_and_profile(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    @dataclass
    class WL:
        layer: str | None

    monkeypatch.setattr(
        hf, "layers_of", lambda _p: {"w01": WL("core"), "w02": WL(None), "w03": WL("core")}
    )
    monkeypatch.setattr(
        hf,
        "cited_here",
        lambda _p, _ids: {"w03": SimpleNamespace(count=9), "w01": SimpleNamespace(count=1)},
    )
    p = hf.findings_payload(project, data=fixture_data())
    c = card(p, "no_human")
    assert c["ids"] == ["w03", "w01", "w02"]  # w03 is cited most here
    assert c["population"]["layer"] is None  # layers are mixed or missing
