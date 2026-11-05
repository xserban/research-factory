"""Specification curve, ablations and controls from recorded runs (slice 6, plan XP-B). Pure."""

from __future__ import annotations

from collections.abc import Sequence

from factory.hypotheses.pairing import RunFact
from factory.hypotheses.tquantiles import Level
from factory.model.experiments import ExperimentDesign
from factory.model.hypotheses import HypothesisSpec


def design_flags(
    design: ExperimentDesign,
    spec: HypothesisSpec,
    facts: Sequence[RunFact],
    *,
    level: Level,
    min_seeds: int,
    outcome: str,
) -> set[str]:
    return set()
