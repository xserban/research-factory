"""Experiment-design rules, cell enumeration, run configurations and `E@` (slice 6, plan XP-A,
rulings 1 to 4). Pure: no I/O, no project state.

Invariants:
- A design is valid only if every rule of `design_issues` holds: one primary metric, enough unique
  seeds, at most `MAX_UNIVERSES` universes, a primary universe inside the product, a factor that
  is not an axis and is present in the base configuration with a baseline value equal to the base
  value, ablations that each change one existing key of the full configuration, controls that
  leave the factor alone, and datasets with exactly one confirmatory dataset per name at most and
  at least one in all.
- A run's configuration is computed, never stated: the base configuration, overlaid by the
  universe coordinates, then the arm's change, then the seed. `config_hash` does not depend on key
  order.
- Planned cells: the primary cells (primary universe, every seed, treatment and baseline, on the
  confirmatory split), the reproduction cells of each baseline (its split), and the ablation and
  control cells (primary universe, every seed, the `dev` split, so that the confirmatory split is
  read by the primary cells only). Any other cell is exploratory.
- `E@` hashes every field except `notes`; list-valued fields that are sets in meaning (seeds,
  datasets, metrics, ablations, controls, baselines, axis values) are sorted first, so the order
  the author wrote them in does not change it.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.errors import ValidationIssue
from factory.model.experiments import MAX_UNIVERSES, Cell, DesignMetric, ExperimentDesign

__all__ = [
    "MAX_UNIVERSES",
    "ablation_cells",
    "access_hash",
    "cell_hash",
    "cell_in_design",
    "config_hash",
    "control_cells",
    "design_issues",
    "design_version",
    "full_config",
    "planned_cells",
    "primary_cells",
    "primary_metric",
    "primary_universe_pairs",
    "reproduction_cells",
    "run_config",
    "universes",
]


def _universe_count(d: ExperimentDesign) -> int:
    count = 1
    for values in d.axes.values():
        count *= len(values)
    return count


def universes(d: ExperimentDesign) -> Iterator[dict[str, str]]:
    """Every point of the multiverse, in a fixed order (sorted keys, sorted values); one empty
    universe when there are no axes."""
    keys = sorted(d.axes)
    for combo in itertools.product(*(sorted(set(d.axes[k])) for k in keys)):
        yield dict(zip(keys, combo, strict=True))


def primary_universe_pairs(d: ExperimentDesign) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(d.primary_universe.items()))


def primary_metric(d: ExperimentDesign) -> DesignMetric:
    return next(m for m in d.metrics if m.primary)


def full_config(d: ExperimentDesign) -> dict[str, str]:
    """The treatment configuration at the primary universe: what an ablation removes a part of."""
    return run_config(
        d, Cell(universe=primary_universe_pairs(d), seed=0, arm="treatment", split="dev")
    )


def design_issues(d: ExperimentDesign, *, min_seeds: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    primaries = [i for i, m in enumerate(d.metrics) if m.primary]
    if len(primaries) != 1:
        issues.append(ValidationIssue("metrics", "exactly-one-primary"))
    if len({m.name for m in d.metrics}) != len(d.metrics):
        issues.append(ValidationIssue("metrics", "duplicate-name"))
    if len(set(d.seeds)) != len(d.seeds):
        issues.append(ValidationIssue("seeds", "duplicate"))
    if len(set(d.seeds)) < min_seeds:
        issues.append(ValidationIssue("seeds", f"at-least-{min_seeds}"))
    if _universe_count(d) > MAX_UNIVERSES:
        issues.append(ValidationIssue("axes", "too-many-universes"))
    if set(d.primary_universe) != set(d.axes):
        issues.append(ValidationIssue("primary_universe", "keys-differ-from-axes"))
    else:
        issues.extend(
            ValidationIssue(f"primary_universe.{k}", "not-in-axis")
            for k in sorted(d.primary_universe)
            if d.primary_universe[k] not in d.axes[k]
        )
    issues.extend(_factor_issues(d))
    issues.extend(_ablation_issues(d))
    issues.extend(_control_issues(d))
    issues.extend(_dataset_issues(d))
    if len({b.row_key for b in d.baselines}) != len(d.baselines):
        issues.append(ValidationIssue("baselines", "duplicate-row-key"))
    if Decimal(d.budget.per_run_gpu_hours) > Decimal(d.budget.gpu_hours):
        issues.append(ValidationIssue("budget.per_run_gpu_hours", "above-total"))
    return issues


def _factor_issues(d: ExperimentDesign) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in sorted(d.factor):
        baseline_value, treatment_value = d.factor[key]
        if key in d.axes:
            issues.append(ValidationIssue(f"factor.{key}", "is-an-axis"))
        if key not in d.base_config:
            issues.append(ValidationIssue(f"factor.{key}", "not-in-base-config"))
        elif d.base_config[key] != baseline_value:
            issues.append(ValidationIssue(f"factor.{key}", "baseline-value-not-base"))
        if baseline_value == treatment_value:
            issues.append(ValidationIssue(f"factor.{key}", "no-change"))
    return issues


def _ablation_issues(d: ExperimentDesign) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len({a.name for a in d.ablations}) != len(d.ablations):
        issues.append(ValidationIssue("ablations", "duplicate-name"))
    if set(d.primary_universe) != set(d.axes):
        return issues  # the full configuration is not defined yet
    full = full_config(d)
    for i, a in enumerate(d.ablations):
        if a.key not in d.base_config or a.key in d.axes or full.get(a.key) == a.value:
            issues.append(ValidationIssue(f"ablations.{i}", "not-one-key"))
    return issues


def _control_issues(d: ExperimentDesign) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len({c.name for c in d.controls}) != len(d.controls):
        issues.append(ValidationIssue("controls", "duplicate-name"))
    for i, c in enumerate(d.controls):
        if set(c.overrides) & set(d.factor):
            issues.append(ValidationIssue(f"controls.{i}.overrides", "touches-factor"))
        if set(c.overrides) & set(d.axes):
            issues.append(ValidationIssue(f"controls.{i}.overrides", "touches-axis"))
    return issues


def _dataset_issues(d: ExperimentDesign) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not any(x.role == "confirmatory" for x in d.datasets):
        issues.append(ValidationIssue("datasets", "no-confirmatory-dataset"))
    seen: set[str] = set()
    dev_hashes = {x.sha256 for x in d.datasets if x.role == "dev"}
    for i, x in enumerate(d.datasets):
        if x.role == "confirmatory" and x.sha256 in dev_hashes:
            issues.append(ValidationIssue(f"datasets.{i}", "shared-hash"))
        if x.role == "confirmatory":
            if x.name in seen:
                issues.append(ValidationIssue(f"datasets.{i}", "second-confirmatory-dataset"))
            seen.add(x.name)
    return issues


# --- Cells and configurations --------------------------------------------------------------------


def run_config(d: ExperimentDesign, cell: Cell) -> dict[str, str]:
    """The run's configuration (ruling 1): base, then universe, then the arm's change, then
    `seed`. Treatment sets the factor to its treatment values; baseline and reproduction set it to
    its baseline values; an ablation is the treatment with one key changed; a control is the
    treatment with its overrides."""
    config = dict(d.base_config)
    config.update(dict(cell.universe))
    kind, _, name = cell.arm.partition(":")
    if kind in ("treatment", "ablation", "control"):
        config.update({k: v[1] for k, v in d.factor.items()})
    else:
        config.update({k: v[0] for k, v in d.factor.items()})
    if kind == "ablation":
        for a in d.ablations:
            if a.name == name:
                config[a.key] = a.value
    elif kind == "control":
        for c in d.controls:
            if c.name == name:
                config.update(c.overrides)
    config["seed"] = str(cell.seed)
    return config


def config_hash(config: dict[str, str]) -> str:
    return hashlib.sha256(canonical_json(dict(config))).hexdigest()[:16]


def cell_hash(cell: Cell) -> str:
    body: JsonValue = {
        "arm": cell.arm,
        "seed": cell.seed,
        "split": cell.split,
        "universe": [[k, v] for k, v in cell.universe],
    }
    return hashlib.sha256(canonical_json(body)).hexdigest()[:16]


def access_hash(cell: Cell) -> str | None:
    """The hash of the primary cell a run reads on the confirmatory split, None for a run that
    reads another split. A baseline reproduction on the confirmatory split reads the primary
    baseline cell of its universe and seed (same data, same configuration)."""
    if cell.split != "confirmatory":
        return None
    if cell.is_reproduction:
        return cell_hash(cell.model_copy(update={"arm": "baseline"}))
    return cell_hash(cell)


def primary_cells(d: ExperimentDesign) -> list[Cell]:
    """Primary universe x seeds x {treatment, baseline} on the confirmatory split."""
    universe = primary_universe_pairs(d)
    return [
        Cell(universe=universe, seed=seed, arm=arm, split="confirmatory")
        for arm in ("treatment", "baseline")
        for seed in sorted(set(d.seeds))
    ]


def reproduction_cells(d: ExperimentDesign) -> list[Cell]:
    universe = primary_universe_pairs(d)
    return [
        Cell(universe=universe, seed=seed, arm=f"reproduction:{b.row_key}", split=b.split)
        for b in d.baselines
        for seed in sorted(set(d.seeds))
    ]


def ablation_cells(d: ExperimentDesign) -> list[Cell]:
    universe = primary_universe_pairs(d)
    return [
        Cell(universe=universe, seed=seed, arm=f"ablation:{a.name}", split="dev")
        for a in d.ablations
        for seed in sorted(set(d.seeds))
    ]


def control_cells(d: ExperimentDesign) -> list[Cell]:
    universe = primary_universe_pairs(d)
    return [
        Cell(universe=universe, seed=seed, arm=f"control:{c.name}", split="dev")
        for c in d.controls
        for seed in sorted(set(d.seeds))
    ]


def cell_in_design(d: ExperimentDesign, cell: Cell) -> bool:
    """Whether a cell is a point the design can run at all: its universe is a point of the
    multiverse and its arm names the factor or something the design declares. A post hoc run
    (exploratory) must still be one."""
    coordinates = dict(cell.universe)
    if set(coordinates) != set(d.axes) or any(coordinates[k] not in d.axes[k] for k in coordinates):
        return False
    kind, _, name = cell.arm.partition(":")
    if kind == "ablation":
        return any(a.name == name for a in d.ablations)
    if kind == "control":
        return any(c.name == name for c in d.controls)
    if kind == "reproduction":
        return any(b.row_key == name for b in d.baselines)
    return True


def planned_cells(d: ExperimentDesign) -> list[Cell]:
    return [
        *primary_cells(d),
        *reproduction_cells(d),
        *ablation_cells(d),
        *control_cells(d),
    ]


# --- E@ -----------------------------------------------------------------------------------------


def _sorted_by_json(items: list[Any]) -> list[Any]:
    return sorted(items, key=lambda x: canonical_json(x))


def design_version(d: ExperimentDesign) -> str:
    """`E@` and the first eight hex digits of the hash over every field but `notes`."""
    body = d.model_dump(mode="json")
    del body["notes"]
    body["seeds"] = sorted(body["seeds"])
    body["axes"] = {k: sorted(v) for k, v in body["axes"].items()}
    for name in ("datasets", "metrics", "ablations", "controls", "baselines"):
        body[name] = _sorted_by_json(body[name])
    return "E@" + hashlib.sha256(canonical_json(body)).hexdigest()[:8]
