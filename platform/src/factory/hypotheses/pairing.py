"""Seed-matched pairing of treatment and baseline runs (slice 6, plan XP-B, ruling 4; spec ruling
22). Pure: no I/O, no project state.

Invariants:
- A pair is a treatment run and a baseline run of one universe and one split with the same seed,
  both completed (exit status zero, a metric value) and not `environment-differs`.
- Of several completed runs of one cell the earliest reported is used and the others are listed in
  `extra_runs` (no best-of-n). A failed run is excluded with the reason `failed`, a run whose
  primary value is beyond the statistics' range with `out-of-range`, a run whose environment
  differs with `environment-differs`, a run with no completed partner of its seed with
  `missing-partner`; nothing is dropped silently.
- Two runs of one seed form a pair only if their configurations differ in exactly `differing_keys`
  (the factor keys, for the treatment and baseline arms); otherwise the pair is `confounded` and
  not used.
- The result lists pairs by seed, so the same facts always give the same pairing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from factory.hypotheses.stats import Direction, oriented
from factory.model.experiments import METRIC_OUT_OF_RANGE, Cell, SplitRole


@dataclass(frozen=True)
class RunFact:
    run_id: str
    cell: Cell
    config: Mapping[str, str]
    value: Decimal | None
    flags: frozenset[str]
    reported_order: int


@dataclass(frozen=True)
class Pairing:
    pairs: tuple[tuple[str, str, Decimal], ...]
    """(treatment-side run, baseline-side run, oriented difference), by seed."""
    confounded: tuple[tuple[str, str], ...]
    excluded: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Run id to the reasons it is not in a pair."""
    extra_runs: tuple[str, ...] = ()
    seeds: tuple[int, ...] = ()
    """The seeds of `pairs`, in the same order."""


def _differing(a: Mapping[str, str], b: Mapping[str, str]) -> frozenset[str]:
    return frozenset(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def pair_runs(
    facts: Sequence[RunFact],
    *,
    differing_keys: frozenset[str],
    universe: Mapping[str, str],
    split: SplitRole,
    direction: Direction,
    arms: tuple[str, str] = ("treatment", "baseline"),
) -> Pairing:
    """Pair the first completed run of each (arm, seed) cell of `universe` on `split`; the first
    arm of `arms` is the treatment side. See the module invariants."""
    coordinates = tuple(sorted(universe.items()))
    relevant = [
        f
        for f in sorted(facts, key=lambda f: (f.reported_order, f.run_id))
        if f.cell.universe == coordinates and f.cell.split == split and f.cell.arm in arms
    ]
    excluded: dict[str, tuple[str, ...]] = {}
    extra: list[str] = []
    chosen: dict[tuple[str, int], RunFact] = {}
    for f in relevant:
        reasons: list[str] = []
        if METRIC_OUT_OF_RANGE in f.flags:
            reasons.append("out-of-range")
        elif "failed" in f.flags or f.value is None:
            reasons.append("failed")
        if "environment-differs" in f.flags:
            reasons.append("environment-differs")
        if reasons:
            excluded[f.run_id] = tuple(reasons)
            continue
        key = (f.cell.arm, f.cell.seed)
        if key in chosen:
            extra.append(f.run_id)
        else:
            chosen[key] = f
    pairs: list[tuple[str, str, Decimal]] = []
    seeds: list[int] = []
    confounded: list[tuple[str, str]] = []
    for seed in sorted({s for _, s in chosen}):
        t = chosen.get((arms[0], seed))
        b = chosen.get((arms[1], seed))
        if t is None or b is None:
            lone = t or b
            assert lone is not None
            excluded[lone.run_id] = (*excluded.get(lone.run_id, ()), "missing-partner")
            continue
        if _differing(t.config, b.config) != differing_keys:
            confounded.append((t.run_id, b.run_id))
            continue
        assert t.value is not None and b.value is not None
        pairs.append((t.run_id, b.run_id, oriented(t.value, b.value, direction)))
        seeds.append(seed)
    return Pairing(
        pairs=tuple(pairs),
        confounded=tuple(confounded),
        excluded=excluded,
        extra_runs=tuple(extra),
        seeds=tuple(seeds),
    )
