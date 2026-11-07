"""Checks of the screener by a person: band checks, tuning batches and measurement batches.

A *draw* is a recorded random sample of records; a person later labels each record include or
exclude, blind to the agent's verdict. Three kinds share the two events:

- `band`: records of one pass, stratified by the relevance score the agent gave (H2 item 2). The
  band limits, the number per band and the seed are recorded, so the draw is reproducible.
- `tuning`: records the agent screens before main screening so that the person can turn its
  disagreements into criterion examples.
- `measurement`: a fresh batch, disjoint from every tuning batch and every example record, drawn
  after the last example change; the only draw on which agreement is reported.

Invariants:
- A band is a closed range of scores inside 1..10; bands do not overlap. `unscored` is the label
  of the band of decisions that carry no score.
- A draw's items are sorted by work id and listed once.
"""

from enum import StrEnum
from itertools import pairwise
from typing import Literal, Self

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel, RunStage

CHECK_ID_RE = rf"^chk_{ULID_RE}$"
UNSCORED = "unscored"
"""The label of the band of decisions without a score; its records are drawn like any band."""
ALL = "all"
"""The label of the single stratum of a tuning or measurement draw."""


class CheckKind(StrEnum):
    BAND = "band"
    TUNING = "tuning"
    MEASUREMENT = "measurement"


class ScoreBand(StrictModel):
    low: int = Field(ge=1, le=10)
    high: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.low > self.high:
            raise ValueError("a band's low limit must not exceed its high limit")
        return self

    @property
    def label(self) -> str:
        return f"{self.low}-{self.high}"

    def holds(self, score: int) -> bool:
        return self.low <= score <= self.high


DEFAULT_BANDS = (ScoreBand(low=1, high=3), ScoreBand(low=4, high=7), ScoreBand(low=8, high=10))
DEFAULT_PER_BAND = 10
DEFAULT_TUNING_SIZE = 20
DEFAULT_MEASUREMENT_SIZE = 30


class CheckItem(StrictModel):
    work_id: str = Field(min_length=1)
    band: str = ALL
    """The band label the record was drawn in (`1-3`, `unscored`, or `all`)."""


class CheckDrawn(StrictModel):
    draw_id: str = Field(pattern=CHECK_ID_RE)
    kind: CheckKind
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT
    pass_label: PassLabel = PassLabel.A
    random_seed: int = Field(ge=0, lt=2**32)
    items: tuple[CheckItem, ...]
    bands: tuple[ScoreBand, ...] = ()
    per_band: int | None = Field(default=None, ge=1)
    name: str | None = None
    last_example_change: str | None = None
    """The event of the latest change to the criterion examples when the draw was made (a
    tuning or measurement draw); a measurement is current only while this is still the latest."""

    @model_validator(mode="after")
    def _shape_fits_kind(self) -> Self:
        if self.kind is CheckKind.BAND:
            if not self.bands or self.per_band is None:
                raise ValueError("a band draw records its bands and the number per band")
            ordered = sorted(self.bands, key=lambda b: b.low)
            if any(a.high >= b.low for a, b in pairwise(ordered)):
                raise ValueError("bands must not overlap")
        elif self.bands or self.per_band is not None:
            raise ValueError("only a band draw has bands")
        works = [item.work_id for item in self.items]
        if works != sorted(set(works)):
            raise ValueError("items are sorted by work id and listed once")
        return self


class CheckLabelled(StrictModel):
    draw_id: str = Field(pattern=CHECK_ID_RE)
    work_id: str = Field(min_length=1)
    verdict: Literal["include", "exclude"]
    channel: Channel
    stage: RunStage = ScreeningStage.TITLE_ABSTRACT
