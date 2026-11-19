"""The `method` payload: the stage-name map, the overall stage sequences, lifecycle views, steps and
taxonomy (plan hub-ui-port-all, step 4; ruling P4). Pure functions are tested on hand-made rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from factory.services import hub_build as hb
from factory.services import hub_method as hm
from factory.services.context import Project
from factory.services.site_lifecycle import STAGES
from tests.test_hub_build import world  # noqa: F401  (fixture)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)


def entry(order: int, name: str, loops: str = "", actor: str = "automated") -> dict[str, str]:
    return {
        "order": str(order),
        "name": name,
        "actor": actor,
        "how": "",
        "next": "",
        "loops": loops,
        "anchor": "",
    }


def paper(wid: str, *entries: dict[str, str]) -> dict[str, Any]:
    return {"id": wid, "title": wid, "year": "2025", "stages": list(entries)}


# ---------------------------------------------------------------- name map


def test_map_stage_groups_known_names_onto_the_nine_stages() -> None:
    assert hm.map_stage("Literature review") == "literature-review"
    assert hm.map_stage("  literature   search ") == "literature-review"
    assert hm.map_stage("Hypothesis generation") == "ideation-hypothesis"
    assert hm.map_stage("Experiment design") == "experiment-design"
    assert hm.map_stage("Experiment execution") == "implementation-execution"
    assert hm.map_stage("Data analysis") == "data-analysis"
    assert hm.map_stage("Manuscript writing") == "paper-writing"
    assert hm.map_stage("Peer review") == "review-verification"
    assert hm.map_stage("Wet lab robot control") == "lab-automation"


def test_map_stage_rule_order_settles_overlaps() -> None:
    # "literature review" contains the review keyword but is a literature stage
    assert hm.map_stage("literature review") == "literature-review"
    # "experiment design" contains the experiment keyword but is a design stage
    assert hm.map_stage("experiment design") == "experiment-design"


def test_every_rule_targets_one_of_the_nine_stages_once() -> None:
    ids = [s for s, _ in hm.STAGE_RULES]
    assert len(ids) == len(set(ids))
    assert set(ids) <= {i for i, _ in STAGES}


def test_unmapped_names_go_to_other_and_are_listed() -> None:
    assert hm.map_stage("zzz quux") is None
    out = hm.sequence_analysis([paper("w1", entry(1, "Literature review"), entry(2, "Zzz quux"))])
    assert out["papers"][0]["path"] == ["literature-review", "other"]
    assert [r["name"] for r in out["unmapped"]] == ["zzz quux"]
    row = next(r for r in out["stage_map"] if r["name"] == "zzz quux")
    assert (row["stage"], row["mapped"], row["papers"], row["rows"]) == ("other", False, 1, 1)
    assert out["papers"][0]["stages"][1]["mapped"] is False


def test_stage_map_counts_papers_and_rows_per_name() -> None:
    out = hm.sequence_analysis(
        [
            paper("w1", entry(1, "Literature Review"), entry(2, "literature review")),
            paper("w2", entry(1, "literature review")),
        ]
    )
    (row,) = out["stage_map"]
    assert row == {
        "name": "literature review",
        "stage": "literature-review",
        "mapped": True,
        "papers": 2,
        "rows": 3,
    }


# ---------------------------------------------------------------- transitions, orders, loops


def test_transitions_count_papers_once_and_merge_repeats() -> None:
    seqs = [
        paper(
            "w1",
            entry(1, "Literature review"),
            entry(2, "Related work survey"),  # same stage: merged
            entry(3, "Hypothesis generation"),
            entry(4, "Experiment execution"),
            entry(5, "Hypothesis refinement"),  # back to ideation
        ),
        paper("w2", entry(1, "Literature review"), entry(2, "Hypothesis generation")),
    ]
    out = hm.sequence_analysis(seqs)
    t = {(r["from"], r["to"]): (r["n"], r["times"]) for r in out["transitions"]}
    assert t[("literature-review", "ideation-hypothesis")] == (2, 2)
    assert t[("ideation-hypothesis", "implementation-execution")] == (1, 1)
    assert t[("implementation-execution", "ideation-hypothesis")] == (1, 1)
    assert out["repeats_merged"] == 1
    assert out["papers"][0]["path"] == [
        "literature-review",
        "ideation-hypothesis",
        "implementation-execution",
        "ideation-hypothesis",
    ]


def test_a_repeated_transition_in_one_paper_counts_one_paper_two_times() -> None:
    seq = paper(
        "w1",
        entry(1, "Hypothesis generation"),
        entry(2, "Experiment execution"),
        entry(3, "Hypothesis generation"),
        entry(4, "Experiment execution"),
    )
    (row,) = [
        r
        for r in hm.sequence_analysis([seq])["transitions"]
        if (r["from"], r["to"]) == ("ideation-hypothesis", "implementation-execution")
    ]
    assert (row["n"], row["times"]) == (1, 2)


def test_loops_are_counted_apart_from_transitions() -> None:
    seqs = [
        paper(
            "w1",
            entry(1, "Hypothesis generation"),
            entry(2, "Experiment execution"),
            entry(3, "Data analysis", loops="2"),  # by order number
        ),
        paper(
            "w2",
            entry(1, "Hypothesis generation"),
            entry(2, "Data analysis", loops="Hypothesis generation"),  # by name
        ),
        paper("w3", entry(1, "Data analysis", loops="none")),
        paper("w4", entry(1, "Data analysis", loops="nowhere in this paper")),
    ]
    out = hm.sequence_analysis(seqs)
    loops = {(r["from"], r["to"]): r["n"] for r in out["loops"]}
    assert loops == {
        ("data-analysis", "implementation-execution"): 1,
        ("data-analysis", "ideation-hypothesis"): 1,
    }
    assert out["unresolved_loops"] == 1


def test_orders_are_the_most_common_full_paths_with_a_fixed_tie_break() -> None:
    a = (entry(1, "Literature review"), entry(2, "Data analysis"))
    b = (entry(1, "Hypothesis generation"), entry(2, "Data analysis"))
    seqs = [paper("w1", *a), paper("w2", *a), paper("w3", *b), paper("w4", *b), paper("w5")]
    out = hm.sequence_analysis(seqs)
    assert out["orders"] == [
        {"path": ["ideation-hypothesis", "data-analysis"], "n": 2},  # equal counts: path order
        {"path": ["literature-review", "data-analysis"], "n": 2},
    ]


def test_orders_are_cut_to_ten() -> None:
    names = [
        "Literature review",
        "Hypothesis generation",
        "Experiment design",
        "Experiment execution",
        "Data analysis",
        "Manuscript writing",
        "Peer review",
        "Wet lab robot",
    ]
    seqs = [paper(f"w{i}", entry(1, names[i % 8]), entry(2, names[(i + 3) % 8])) for i in range(12)]
    assert len(hm.sequence_analysis(seqs)["orders"]) == hm.TOP_ORDERS


def test_entry_and_exit_counts() -> None:
    seqs = [
        paper("w1", entry(1, "Literature review"), entry(2, "Manuscript writing")),
        paper("w2", entry(1, "Literature review"), entry(2, "Data analysis")),
        paper("w3", entry(1, "Data analysis")),
    ]
    out = hm.sequence_analysis(seqs)
    assert out["entry"]["literature-review"] == 2 and out["entry"]["data-analysis"] == 1
    assert out["exit"]["paper-writing"] == 1 and out["exit"]["data-analysis"] == 2
    assert sum(out["entry"].values()) == sum(out["exit"].values()) == out["n_papers"] == 3
    assert set(out["entry"]) == {s for s, _ in STAGES}


def test_sequence_analysis_is_deterministic_and_order_independent() -> None:
    seqs = [
        paper("w2", entry(1, "Data analysis"), entry(2, "Zzz", loops="1")),
        paper("w1", entry(1, "Literature review"), entry(2, "Manuscript writing")),
        paper("w3", entry(1, "Literature review"), entry(2, "Manuscript writing")),
    ]
    first = hm.sequence_analysis(seqs)
    assert json.dumps(first, sort_keys=True) == json.dumps(
        hm.sequence_analysis(list(reversed(seqs))), sort_keys=True
    )
    assert first == hm.sequence_analysis(seqs)


def test_empty_input_gives_an_empty_analysis() -> None:
    out = hm.sequence_analysis([])
    assert out["n_papers"] == 0 and out["papers"] == [] and out["orders"] == []
    assert out["transitions"] == [] and out["loops"] == [] and out["unmapped"] == []


# ---------------------------------------------------------------- lifecycle (m-stages)


def _work(wid: str, stages: list[tuple[str, str]], technique: str | None = None) -> dict[str, Any]:
    return {
        "id": wid,
        "slug": f"s-{wid}",
        "title": wid,
        "year": "2025",
        "stages": [{"stage": s, "mode": m, "quote": "q", "anchor": "a"} for s, m in stages],
        "cls": {"technique_primary": {"v": technique, "q": "", "a": ""}} if technique else {},
    }


def test_lifecycle_view_matrix_arcs_modes_and_distinct_stages() -> None:
    works = [
        _work(
            "w1", [("data-analysis", "automated"), ("paper-writing", "mentioned-only")], "agents"
        ),
        _work("w2", [("data-analysis", "human-assisted")], "agents"),
        _work("w3", [("data-analysis", "automated"), ("paper-writing", "automated")], "rl"),
        _work("w4", []),
    ]
    layers = {"w1": "core", "w2": "core", "w3": "applied", "w4": "core"}
    v = hm.lifecycle_view(works, layers)
    assert [w["id"] for w in v["works"]] == ["w1", "w2", "w3"]
    row = next(r for r in v["matrix"] if r["stage"] == "data-analysis")
    assert row["n"] == 3 and row["layers"] == {"core": 2, "applied": 1}
    assert v["arcs"] == [{"a": "data-analysis", "b": "paper-writing", "n": 2}]
    mode = next(r for r in v["stage_mode"] if r["stage"] == "paper-writing")
    assert mode["modes"] == {"automated": 1, "human-assisted": 0, "mentioned-only": 1}
    assert v["distinct_stages"] == [{"k": 1, "n": 1}, {"k": 2, "n": 2}]
    tech = v["stage_technique"]
    assert tech["techniques"] == ["agents", "rl"]
    da = next(r for r in tech["rows"] if r["stage"] == "data-analysis")
    assert da["n"] == {"agents": 2, "rl": 1}
    pw = next(r for r in tech["rows"] if r["stage"] == "paper-writing")
    assert pw["n"] == {"agents": 0, "rl": 1}  # the mentioned-only row is left out


# ---------------------------------------------------------------- steps and taxonomy


def test_steps_payload_counts_rows_and_works() -> None:
    rows = [
        {
            "work": "w1",
            "title": "T",
            "year": "2025",
            "stage": "data-analysis",
            "order": "1",
            "actor": "",
            "step": {"text": "run it", "anchor": "a1"},
            "check": {"text": "checked", "anchor": "a2"},
        },
        {
            "work": "w1",
            "title": "T",
            "year": "2025",
            "stage": "paper-writing",
            "order": "2",
            "actor": "human",
            "step": {"text": "write", "anchor": "a3"},
        },
    ]
    p = hm.steps_payload(rows)
    assert (p["n_rows"], p["n_works"], p["miner"]) == (2, 1, "m-stage-steps")
    assert len(p["stages"]) == 9
    assert p["actors"] == ["automated", "human-assisted", "human", "not-stated"]
    da = next(s for s in p["stages"] if s["id"] == "data-analysis")
    assert da["works"][0]["steps"][0]["actor"] == "not-stated"  # absence is not a value


def test_diff_rows_are_computed_from_the_two_versions() -> None:
    from factory.mining.taxonomy import TaxonomyDiff

    rows = hm.diff_rows(TaxonomyDiff(added=("d/new",), split=(("d/a", ("d/a1", "d/a2")),)))
    by = {r["label"]: r["text"] for r in rows}
    assert by["added"] == "d/new" and by["split"] == "d/a into d/a1, d/a2" and by["removed"] == ""
    assert [r["label"] for r in rows] == [
        "added",
        "removed",
        "redefined",
        "renamed",
        "split",
        "merged",
        "dimensions",
    ]


def test_legacy_taxonomy_is_read_as_it_was(world: Project) -> None:  # noqa: F811
    assert hm.legacy_taxonomy(world) is None
    (world.paths.dir / hm.LEGACY_FILE).write_text(
        json.dumps(
            {
                "taxonomy": "old",
                "status": "accepted",
                "source": "s",
                "dimensions": [
                    {"dimension": "d", "title": "D", "categories": [{"name": "c", "pattern": None}]}
                ],
            }
        ),
        encoding="utf-8",
    )
    legacy = hm.legacy_taxonomy(world)
    assert legacy is not None and legacy["name"] == "old" and legacy["status"] == "accepted"
    assert legacy["dimensions"] == [
        {"id": "d", "title": "D", "categories": [{"name": "c", "pattern": ""}]}
    ]


def test_registered_payload_is_empty_without_registrations(world: Project) -> None:  # noqa: F811
    assert hm.registered_payload(world) == []


# ---------------------------------------------------------------- the payload


def test_method_payload_is_ready_and_has_its_methods(world: Project, tmp_path: Path) -> None:  # noqa: F811
    hb.build_static(world, tmp_path / "ui", only={"method"})
    data = json.loads((tmp_path / "ui/data/method.json").read_text(encoding="utf-8"))
    assert data["ready"] is True
    assert set(data) >= {"methods", "lifecycle", "steps", "taxonomy"}
    assert set(data["methods"]) >= {"sequences", "stage_map", "steps", "taxonomy", "lifecycle_flow"}
    seq = data["lifecycle"]["sequences"]
    assert seq["n_papers"] == len(seq["papers"])
    assert data["lifecycle"]["stage_rules"][0]["stage"] == hm.STAGE_RULES[0][0]
    assert not any(ch.isdigit() for ch in "".join(data["methods"].values()))


def test_method_payload_is_deterministic(world: Project) -> None:  # noqa: F811
    first = hm.build(hb.HubContext(world))
    second = hm.build(hb.HubContext(world))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
