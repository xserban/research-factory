"""The rigour mode of a project (decision 24). Kept apart from `model.project` so that
`model.levels` can map tiers to modes without an import cycle."""

from enum import StrEnum


class RigorMode(StrEnum):
    EXPLORATORY = "exploratory"
    PILOT = "pilot"
    SYSTEMATIC = "systematic"
