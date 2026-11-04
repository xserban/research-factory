"""The watch plan (a protocol section) and, from plan living-A task 4, the watch-cycle events.

Pure value types. `WatchPlan` is hashed with the protocol but is outside `S@`: cadence and mode
change what is identified over time, not the search strategy a probe measured (slice 4b, ruling 4).
Sources and notice kinds are kept sorted so the order they are stated in never changes the hash.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

WCY_ID_RE = rf"^wcy_{ULID_RE}$"
_PROTOCOL_ID_RE = r"^P@[0-9a-f]{8}$"  # as model.protocol; that module imports this one

CycleTrigger = Literal["scheduler", "human", "agent"]


class CycleStatus(StrEnum):
    """`OPEN` is a cycle started and not finished; the other three are terminal."""

    OPEN = "open"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


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


# --- Event payloads (schema 1). Written by `factory.services.watch`, folded by `index.watch`.


class SourceCounts(StrictModel):
    """What one source contributed to one cycle. Always computed from run events and index rows
    (`factory.living.counts`), never supplied.

    `runs` and `complete_runs` count planned queries run in the cycle and those whose latest run
    in the cycle completed; `retrieved` sums the records those latest runs retrieved. `new_works`
    counts works first seen in the cycle by this source; `duplicates_in_cycle` works this source
    returned that an earlier source of the same cycle had found first. `window_missed` and
    `disappeared` exist only for a full replay (None otherwise, and `disappeared` None when a
    run of the source did not complete).
    """

    source: str
    runs: int = Field(ge=0)
    complete_runs: int = Field(ge=0)
    retrieved: int = Field(ge=0)
    new_works: int = Field(ge=0)
    duplicates_in_cycle: int = Field(ge=0)
    window_missed: int | None = Field(default=None, ge=0)
    disappeared: int | None = Field(default=None, ge=0)

    @property
    def complete(self) -> bool:
        return self.runs > 0 and self.runs == self.complete_runs


class CycleSource(StrictModel):
    """One source of a cycle: how it runs, and the window it lists from."""

    source: str
    mode: Literal["full", "window"]
    window_start: date | None = None
    full_replay: bool


class WatchCycleStarted(StrictModel):
    cycle_id: str = Field(pattern=WCY_ID_RE)
    protocol_id: str = Field(pattern=_PROTOCOL_ID_RE)
    sources: tuple[CycleSource, ...] = Field(min_length=1)
    skipped: tuple[str, ...] = ()
    trigger: CycleTrigger


class WatchCycleFinished(StrictModel):
    cycle_id: str = Field(pattern=WCY_ID_RE)
    status: CycleStatus
    run_ids: tuple[str, ...] = ()
    status_run_ids: tuple[str, ...] = ()
    counts: tuple[SourceCounts, ...] = ()
    note: str | None = None

    @model_validator(mode="after")
    def _terminal(self) -> Self:
        if self.status is CycleStatus.OPEN:
            raise ValueError("a finished cycle is complete, partial or failed")
        return self
