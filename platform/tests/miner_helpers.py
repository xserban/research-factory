"""Shared builders of the miner tests: a `VISION_RESULT_V1` spec and its JSON form."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from factory.document.anchors import AnchorKind
from factory.mining.spec import (
    EnumKind,
    EvidenceRule,
    MinerField,
    MinerRegime,
    MinerSpec,
    NumberKind,
    Population,
    QuoteKind,
    Selector,
)
from factory.packs.model import UnitFamily

VISION_NAME = "m-vision-result"


def vision_result(**over: Any) -> MinerSpec:
    """A small registered miner: a metric, its number and an evidence quote, per result."""
    spec = MinerSpec(
        name=VISION_NAME,
        version=1,
        selector=Selector(
            Population.INCLUDED_FT,
            elements=(AnchorKind.PARAGRAPH, AnchorKind.TABLE),
            heading_patterns=("results",),
            max_units=20,
        ),
        fields=(
            MinerField("metric", "result", QuoteKind(), required=True),
            MinerField(
                "value",
                "result",
                NumberKind(UnitFamily.SCORE, ("%", "fraction", "")),
                required=True,
            ),
            MinerField("direction", "result", EnumKind(("higher", "lower"))),
            MinerField("evidence", "evidence", QuoteKind(), compared=False),
        ),
        row_key_fields=("metric",),
        row_anchor_fields=("metric",),
        conditionals=(),
        evidence=EvidenceRule(1, True),
        procedure="rf-extract",
        regime=MinerRegime(2, 10, 0.8, 0.9),
        rationale="Report the headline metric of each result.",
    )
    return replace(spec, **over) if over else spec
