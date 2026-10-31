from enum import StrEnum

from factory.model.base import StrictModel


class RigorMode(StrEnum):
    EXPLORATORY = "exploratory"
    PILOT = "pilot"
    SYSTEMATIC = "systematic"


class ProjectCreated(StrictModel):
    slug: str
    rigor_mode: RigorMode
