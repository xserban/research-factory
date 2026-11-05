"""Design validation, cell enumeration, run configurations and `E@` (slice 6, plan XP-A task 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.hypotheses.design import (
    cell_hash,
    config_hash,
    design_issues,
    design_version,
    planned_cells,
    primary_cells,
    reproduction_cells,
    run_config,
    universes,
)
from factory.model.experiments import Cell, ExperimentDesign
from tests.experiment_helpers import ROW, design, design_body


def _issues(**over: object) -> list[tuple[str, str]]:
    d = design(**over)
    return [(i.field, i.reason) for i in design_issues(d, min_seeds=3)]


def test_valid_design_has_no_issues() -> None:
    assert _issues() == []


def test_too_many_universes_rejected() -> None:  # acceptance 13
    axes = {f"a{i}": [str(v) for v in range(4)] for i in range(5)}  # 4**5 = 1024
    issues = _issues(axes=axes, primary_universe={k: "0" for k in axes})
    assert ("axes", "too-many-universes") in issues
    at_limit = {f"a{i}": ["0", "1"] for i in range(8)}  # 256
    assert ("axes", "too-many-universes") not in _issues(
        axes=at_limit, primary_universe={k: "0" for k in at_limit}
    )


def test_ablation_must_change_one_key() -> None:  # acceptance 13
    unchanged = {"name": "same", "key": "use_norm", "value": True}
    assert ("ablations.0", "not-one-key") in _issues(ablations=[unchanged])
    unknown = {"name": "ghost", "key": "no_such_key", "value": "x"}
    assert ("ablations.0", "not-one-key") in _issues(ablations=[unknown])
    axis_key = {"name": "res", "key": "resolution", "value": "384"}
    assert ("ablations.0", "not-one-key") in _issues(ablations=[axis_key])
    on_factor = {"name": "soft", "key": "attention", "value": "softmax"}
    assert _issues(ablations=[on_factor]) == []  # removing the treatment from the full config


def test_min_seeds_by_plan() -> None:
    d = design(seeds=[1, 2])
    assert [(i.field, i.reason) for i in design_issues(d, min_seeds=3)] == [("seeds", "at-least-3")]
    assert design_issues(d, min_seeds=2) == []
    dup = design(seeds=[1, 1, 2])
    assert ("seeds", "duplicate") in [(i.field, i.reason) for i in design_issues(dup, min_seeds=2)]


def test_primary_universe_in_product() -> None:
    assert ("primary_universe.resolution", "not-in-axis") in _issues(
        primary_universe={"resolution": "512"}
    )
    assert ("primary_universe", "keys-differ-from-axes") in _issues(primary_universe={})


def test_factor_not_axis() -> None:
    issues = _issues(
        axes={"attention": ["softmax", "linear"]}, primary_universe={"attention": "softmax"}
    )
    assert ("factor.attention", "is-an-axis") in issues
    assert ("factor.speed", "not-in-base-config") in _issues(factor={"speed": ["a", "b"]})
    assert ("factor.attention", "baseline-value-not-base") in _issues(
        factor={"attention": ["other", "linear"]}
    )
    assert ("factor.attention", "no-change") in _issues(
        factor={"attention": ["softmax", "softmax"]}
    )


def test_exactly_one_primary_metric_and_confirmatory_dataset() -> None:
    two = [
        {"name": "a", "direction": "higher", "unit_family": "score", "primary": True},
        {"name": "b", "direction": "higher", "unit_family": "score", "primary": True},
    ]
    assert ("metrics", "exactly-one-primary") in _issues(metrics=two)
    dev_only = [{"name": "d", "version": "1", "sha256": "a" * 64, "role": "dev"}]
    assert ("datasets", "no-confirmatory-dataset") in _issues(datasets=dev_only)
    twice = [
        {"name": "t", "version": "1", "sha256": "a" * 64, "role": "confirmatory"},
        {"name": "t", "version": "2", "sha256": "b" * 64, "role": "confirmatory"},
    ]
    assert ("datasets.1", "second-confirmatory-dataset") in _issues(datasets=twice)


def test_controls_leave_the_factor_alone() -> None:
    bad = [
        {
            "name": "c",
            "kind": "negative",
            "overrides": {"attention": "x"},
            "expect": "no-effect",
        }
    ]
    assert ("controls.0.overrides", "touches-factor") in _issues(controls=bad)
    with pytest.raises(ValidationError):  # a positive control expects an effect
        design(
            controls=[
                {"name": "c", "kind": "positive", "overrides": {"a": "b"}, "expect": "no-effect"}
            ]
        )


def test_budget_per_run_cap_not_above_total() -> None:
    assert ("budget.per_run_gpu_hours", "above-total") in _issues(
        budget={"gpu_hours": "5", "per_run_gpu_hours": "6", "max_runs": 3}
    )


def test_float_config_value_refused_and_scalars_spelled() -> None:
    with pytest.raises(ValidationError):
        design(base_config={"attention": "softmax", "lr": 0.001})
    d = design()
    assert d.base_config["depth"] == "12" and d.base_config["use_norm"] == "true"


def test_run_config_overlay_order() -> None:
    d = design(base_config={"attention": "softmax", "depth": 12, "resolution": "32", "x": "1"})
    universe = (("resolution", "224"),)
    treat = run_config(d, Cell(universe=universe, seed=7, arm="treatment", split="confirmatory"))
    assert treat == {
        "attention": "linear",
        "depth": "12",
        "resolution": "224",
        "x": "1",
        "seed": "7",
    }
    base = run_config(d, Cell(universe=universe, seed=7, arm="baseline", split="confirmatory"))
    assert base["attention"] == "softmax" and base["resolution"] == "224"
    ablation = run_config(d, Cell(universe=universe, seed=1, arm="ablation:no-norm", split="dev"))
    assert ablation["use_norm"] == "false" and ablation["attention"] == "linear"
    control = run_config(d, Cell(universe=universe, seed=1, arm="control:shuffled", split="dev"))
    assert control["labels"] == "shuffled" and control["attention"] == "linear"
    repro = run_config(
        d, Cell(universe=universe, seed=1, arm=f"reproduction:{ROW}", split="confirmatory")
    )
    assert repro["attention"] == "softmax"
    # the seed is last: a base_config "seed" cannot survive
    seeded = design(base_config={"attention": "softmax", "seed": "999"})
    assert run_config(seeded, Cell(universe=(), seed=5, arm="baseline", split="dev"))["seed"] == "5"


def test_primary_cells_count() -> None:
    d = design()
    cells = primary_cells(d)
    assert len(cells) == len(d.seeds) * 2
    assert {c.arm for c in cells} == {"treatment", "baseline"}
    assert {c.split for c in cells} == {"confirmatory"}
    assert {c.universe for c in cells} == {(("resolution", "224"),)}


def test_other_planned_cells_and_universes() -> None:
    d = design()
    assert len(reproduction_cells(d)) == 3
    assert {c.split for c in reproduction_cells(d)} == {"dev"}  # the default (review C1)
    cells = planned_cells(d)
    assert len(cells) == 6 + 3 + 3 + 6
    assert len({cell_hash(c) for c in cells}) == len(cells)
    assert list(universes(d)) == [{"resolution": "224"}, {"resolution": "384"}]
    assert list(universes(design(axes={}, primary_universe={}))) == [{}]


def test_e_version_ignores_notes_and_changes_with_seed_list() -> None:  # acceptance 13
    base = design()
    assert design_version(base).startswith("E@") and len(design_version(base)) == 10
    assert design_version(design(notes="a note")) == design_version(base)
    assert design_version(design(seeds=[1, 2, 3, 4])) != design_version(base)
    assert design_version(design(seeds=[3, 1, 2])) == design_version(base)
    reordered = design_body()
    reordered["datasets"] = list(reversed(reordered["datasets"]))
    assert design_version(ExperimentDesign.model_validate(reordered)) == design_version(base)
    assert design_version(design(code={"uri": "u", "commit": "other"})) != design_version(base)


def test_config_hash_independent_of_key_order() -> None:
    assert config_hash({"a": "1", "b": "2"}) == config_hash({"b": "2", "a": "1"})
    assert config_hash({"a": "1"}) != config_hash({"a": "2"})
    assert len(config_hash({"a": "1"})) == 16


def test_cell_hash_distinguishes_split_and_seed() -> None:
    a = Cell(universe=(), seed=1, arm="treatment", split="dev")
    assert cell_hash(a) != cell_hash(a.model_copy(update={"split": "confirmatory"}))
    assert cell_hash(a) != cell_hash(a.model_copy(update={"seed": 2}))
    with pytest.raises(ValidationError):  # coordinates must be sorted
        Cell(universe=(("b", "1"), ("a", "1")), seed=1, arm="treatment", split="dev")


def test_dev_and_confirmatory_cannot_be_the_same_data() -> None:
    # review I6 (R-50): a shared content hash makes the split a label only
    same = [
        {"name": "d", "version": "1", "sha256": "b" * 64, "role": "dev"},
        {"name": "t", "version": "1", "sha256": "b" * 64, "role": "confirmatory"},
    ]
    assert ("datasets.1", "shared-hash") in _issues(datasets=same)
    apart = [
        {"name": "d", "version": "1", "sha256": "a" * 64, "role": "dev"},
        {"name": "t", "version": "1", "sha256": "b" * 64, "role": "confirmatory"},
    ]
    assert ("datasets.1", "shared-hash") not in _issues(datasets=apart)
