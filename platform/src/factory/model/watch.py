"""The watch plan (a protocol section) and, from plan living-A task 4, the watch-cycle events.

Pure value types. `WatchPlan` is hashed with the protocol but is outside `S@`: cadence and mode
change what is identified over time, not the search strategy a probe measured (slice 4b, ruling 4).
Sources and notice kinds are kept sorted so the order they are stated in never changes the hash.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from factory.model.base import StrictModel


class WatchSource(StrictModel):
    """How often one included source is re-run, and whether it is replayed in full or windowed."""

    source: str
    interval_days: int = Field(ge=1)
    mode: Literal["full", "window"] = "full"
    overlap_days: int = Field(default=7, ge=1)
    full_replay_every: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _window_needs_replay(self) -> Self:
        if self.mode == "window" and self.full_replay_every is None:
            raise ValueError("a window source must declare full_replay_every")
        return self


class WatchPlan(StrictModel):
    """The declared watch: one entry per source, plus notice, snapshot and digest settings."""

    sources: tuple[WatchSource, ...] = Field(min_length=1)
    notices: tuple[Literal["openalex", "crossref"], ...] = ("crossref", "openalex")
    notice_budget: int = Field(default=200, ge=0)
    track_versions: bool = True
    snapshot_every: int | None = Field(default=None, ge=1)
    max_consecutive_failures: int = Field(default=3, ge=1)
    digest_listing_cap: int = Field(default=50, ge=1)
    until: date | None = None

    @field_validator("sources")
    @classmethod
    def _unique_sorted(cls, value: tuple[WatchSource, ...]) -> tuple[WatchSource, ...]:
        names = [item.source for item in value]
        if len(set(names)) != len(names):
            raise ValueError("a source may appear once in a watch plan")
        return tuple(sorted(value, key=lambda item: item.source))

    @field_validator("notices")
    @classmethod
    def _sorted_notices(
        cls, value: tuple[Literal["openalex", "crossref"], ...]
    ) -> tuple[Literal["openalex", "crossref"], ...]:
        return tuple(sorted(set(value)))
