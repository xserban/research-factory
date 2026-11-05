"""Calibration events of registered miners (slice M, M-D): the drawn sample and the gold labels.

Invariants:
- A calibration is drawn once per miner version; its units are `(work_id, conversion_id)` pairs of
  the selector's population, sorted and distinct.
- A gold label is a human's answer for one unit: verified rows, or `empty` (and then no rows).
  Rows are stored as `extraction.recorded` stores them, so the same verifier admitted them.
- Nothing here holds a score: scores are computed on read from the labels and the calibration
  pass's rows (R-05).

Written by `factory.services.miners`, folded by `factory.index.miner_calibration`.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.model.extraction import ROW_KEY_RE, FieldName, StoredField
from factory.model.identity import CONVERSION_ID_RE, ULID_RE
from factory.model.miners import DIGEST_RE, MINER_NAME_RE
from factory.model.protocol import PROTOCOL_ID_RE
from factory.model.screening import Channel

CALIBRATION_ID_RE = rf"^mcl_{ULID_RE}$"


class CalibrationUnit(StrictModel):
    work_id: str = Field(min_length=1)
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)


class MinerCalibrationDrawn(StrictModel):
    calibration_id: str = Field(pattern=CALIBRATION_ID_RE)
    name: str = Field(pattern=MINER_NAME_RE)
    version: int = Field(ge=1)
    digest: str = Field(pattern=DIGEST_RE)
    units: tuple[CalibrationUnit, ...] = Field(min_length=1)
    random_seed: int = Field(ge=0, lt=2**32)
    population: int = Field(ge=1)
    population_digest: str = Field(min_length=1)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)

    @model_validator(mode="after")
    def _units_sorted_distinct(self) -> Self:
        works = [u.work_id for u in self.units]
        if works != sorted(set(works)):
            raise ValueError("units must be sorted by work and distinct")
        if len(works) > self.population:
            raise ValueError("more units than the population")
        return self


class GoldRow(StrictModel):
    """One gold record: its key and verified fields."""

    row_key: str = Field(pattern=ROW_KEY_RE)
    fields: dict[FieldName, StoredField] = Field(min_length=1)


class MinerCalibrationLabelled(StrictModel):
    calibration_id: str = Field(pattern=CALIBRATION_ID_RE)
    work_id: str = Field(min_length=1)
    rows: tuple[GoldRow, ...] = ()
    empty: bool = False
    channel: Channel

    @model_validator(mode="after")
    def _empty_iff_no_rows(self) -> Self:
        if self.empty != (not self.rows):
            raise ValueError("a unit is empty if and only if it has no gold rows")
        return self
