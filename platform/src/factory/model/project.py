from enum import StrEnum
from typing import Literal

from factory.model.base import StrictModel

Visibility = Literal["lab", "private"]


class RigorMode(StrEnum):
    EXPLORATORY = "exploratory"
    PILOT = "pilot"
    SYSTEMATIC = "systematic"


class ProjectCreated(StrictModel):
    slug: str
    rigor_mode: RigorMode


class ProjectVisibilitySet(StrictModel):
    """`lab`: every lab member reads. `private`: members only (slice 5 ruling 13)."""

    visibility: Visibility
