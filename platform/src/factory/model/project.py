from typing import Any, Literal

from pydantic import SerializerFunctionWrapHandler, model_serializer

from factory.model.base import StrictModel
from factory.model.levels import AutonomyLevel, Tier
from factory.model.rigor import RigorMode

Visibility = Literal["lab", "private"]


class ProjectCreated(StrictModel):
    slug: str
    rigor_mode: RigorMode
    tier: Tier | None = None
    """The tier the study declared at init; None for a legacy project. Left out of the event
    while None, so no old log changes."""
    autonomy_level: AutonomyLevel = AutonomyLevel.ATTENDED
    """Who closes the decision gates. Left out of the event while `attended` (the default)."""

    @model_serializer(mode="wrap")
    def _omit_defaults(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.tier is None:
            data.pop("tier", None)
        if self.autonomy_level is AutonomyLevel.ATTENDED:
            data.pop("autonomy_level", None)
        return data


class ProjectVisibilitySet(StrictModel):
    """`lab`: every lab member reads. `private`: members only (slice 5 ruling 13)."""

    visibility: Visibility


__all__ = ["ProjectCreated", "ProjectVisibilitySet", "RigorMode", "Visibility"]
