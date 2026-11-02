"""Citation chasing and late admission: chase rounds, pass-B sample extensions and seed admissions.

A chase round names its direction(s) and the works it chases from (the `promote` outcomes with an
OpenAlex id). Its queries are built by the platform and recorded with the round, so the round is
the only authority for a chase query text. A sample extension records one draw over the corpus
that arrived after pass B opened: `considered` is every candidate the draw saw, `added` the subset
it put into pass B. A seed admission records the ID lookup that tried to retrieve an explained
positive seed miss.

Invariants enforced here (validated at the boundary, before any event is written):
- A round has one or two distinct directions and at least one source work; source works are
  strictly sorted, so the same round is one canonical event.
- A sample extension is pass B only, and `added` is a subset of `considered`.
- The random seed is a 32-bit unsigned integer, as `open_pass` draws it.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.screening import NonBlank, PassLabel
from factory.model.seed import POSITIVE_SEED_ID_RE
from factory.model.work import RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE

CHASE_ROUND_ID_RE = rf"^chs_{ULID_RE}$"
CHASE_CHUNK: Final = 50
"""OpenAlex work ids per chase query. A chunk holds at most this many sorted ids."""

WorkId = Annotated[str, StringConstraints(pattern=WORK_ID_RE)]


class ChaseDirection(StrEnum):
    BACKWARD = "backward"
    FORWARD = "forward"


def _no_repeats(values: tuple[object, ...], field: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} must not repeat an entry")


# --- Event payloads (schema 1). Written by `factory.services.chase` and `factory.services.seeds`,
# folded by `factory.index.chase`.


class ChaseRoundStarted(StrictModel):
    round_id: str = Field(pattern=CHASE_ROUND_ID_RE)
    directions: tuple[ChaseDirection, ...] = Field(min_length=1, max_length=2)
    from_works: tuple[WorkId, ...] = Field(min_length=1)
    unchasable: tuple[WorkId, ...]
    queries: tuple[NonBlank, ...]

    @model_validator(mode="after")
    def _shape(self) -> Self:
        _no_repeats(self.directions, "directions")
        _no_repeats(self.unchasable, "unchasable")
        if list(self.from_works) != sorted(set(self.from_works)):
            raise ValueError("from_works must be sorted and unique")
        return self


class SampleExtended(StrictModel):
    pass_label: PassLabel
    random_seed: int = Field(ge=0, lt=2**32)
    considered: tuple[WorkId, ...]
    added: tuple[WorkId, ...]

    @model_validator(mode="after")
    def _pass_b_and_subset(self) -> Self:
        if self.pass_label is not PassLabel.B:
            raise ValueError("only pass B's sample is extended")
        _no_repeats(self.considered, "considered")
        _no_repeats(self.added, "added")
        if not set(self.added) <= set(self.considered):
            raise ValueError("added must be a subset of considered")
        return self


class SeedAdmitted(StrictModel):
    """The ID lookup that admitted an explained positive seed miss, and what it found."""

    seed_id: str = Field(pattern=POSITIVE_SEED_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)
    work_id: str | None = Field(default=None, pattern=WORK_ID_RE)
