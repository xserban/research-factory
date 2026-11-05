"""Platform floors of miner calibration (slice M ruling 16; M-D rulings 2 and 4).

Pure data and comparisons: no index, log or clock is read here.

Invariants:
- A miner may declare thresholds and a sample size above these floors, never below.
- In exploratory mode there is no floor: a declared value stands (and is the only gate).
- The floors never reach an agent: refusals and views name counts only (decision 43).
"""

from __future__ import annotations

from factory.mining.spec import MinerRegime
from factory.model.project import RigorMode

SAMPLE_FLOOR: dict[RigorMode, int] = {
    RigorMode.EXPLORATORY: 0,
    RigorMode.PILOT: 5,
    RigorMode.SYSTEMATIC: 10,
}
"""The fewest units a calibration sample holds, when the population allows."""

THRESHOLD_FLOOR: dict[RigorMode, tuple[float, float]] = {
    RigorMode.EXPLORATORY: (0.0, 0.0),
    RigorMode.PILOT: (0.8, 0.9),
    RigorMode.SYSTEMATIC: (0.9, 0.95),
}
"""`(recall, field agreement)` floors."""


def sample_size(mode: RigorMode, regime: MinerRegime, population: int) -> int:
    """Units to draw: the declared size or the mode's floor, whichever is larger, capped at the
    population."""
    return min(population, max(regime.calibration_size, SAMPLE_FLOOR[mode]))


def thresholds(mode: RigorMode, regime: MinerRegime) -> tuple[float, float]:
    """`(recall_min, field_agreement_min)` in force: each declared value, raised to the floor."""
    recall_floor, agreement_floor = THRESHOLD_FLOOR[mode]
    return max(regime.recall_min, recall_floor), max(regime.field_agreement_min, agreement_floor)
