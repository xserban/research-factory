"""Registered conclusions of a living review (slice 4b, plan living-D).

A conclusion is a statement written by the researcher (`conclusion.registered`, a human act) with
a non-empty basis of references that resolve through `trace` and, optionally, one fact predicate
from a fixed menu. The platform never writes or judges the statement; it computes the predicate's
value and the basis state from the events (R-105).

Invariants:
- A basis reference has the shape of its kind; a predicate carries exactly the fields of its kind.
- `ConclusionDiff` and `ConclusionSnapshot` hold ids and computed values only, never a statement.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from factory.living.facts import FactsDiff
from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.work_ids import WORK_ID_RE

CCL_ID_RE = rf"^ccl_{ULID_RE}$"
GROUP_ID_RE = r"^grp_[0-9a-f]{12}$"
ROW_KEY_RE = r"^rk_[0-9a-f]{12}$"
_CELL_RE = r"^rk_[0-9a-f]{12}/\S+$"
_RELATION_RE = rf"^rel_{ULID_RE}$"

_BASIS_SHAPES = {
    "cell": _CELL_RE,
    "row": ROW_KEY_RE,
    "group": GROUP_ID_RE,
    "work": WORK_ID_RE,
    "relation": _RELATION_RE,
}


class BasisRef(StrictModel):
    """One thing a conclusion rests on: a cell (`rk_<12hex>/field`), a row (`rk_<12hex>`), a
    comparability group (`grp_<12hex>`), a work (`rf:` id) or a relation (`rel_`, slice 3b)."""

    kind: Literal["cell", "row", "group", "work", "relation"]
    ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def _shape(self) -> BasisRef:
        if re.fullmatch(_BASIS_SHAPES[self.kind], self.ref) is None:
            raise ValueError(f"{self.ref!r} is not a {self.kind} reference")
        return self


PredicateKind = Literal[
    "frontier-member", "best-in-group", "group-row-count-at-least", "path-exists"
]

_REQUIRED: dict[str, frozenset[str]] = {
    "frontier-member": frozenset({"group_id", "axis_key", "row_key"}),
    "best-in-group": frozenset({"group_id", "row_key"}),
    "group-row-count-at-least": frozenset({"group_id", "count"}),
    "path-exists": frozenset({"source", "target"}),
}
_ARGUMENTS = ("group_id", "axis_key", "row_key", "count", "source", "target")


class Predicate(StrictModel):
    """A fact predicate over the conclusion facts; its value is computed, `None` when undefined."""

    kind: PredicateKind
    group_id: str | None = Field(default=None, pattern=GROUP_ID_RE)
    axis_key: str | None = Field(default=None, min_length=1)
    row_key: str | None = Field(default=None, pattern=ROW_KEY_RE)
    count: int | None = Field(default=None, ge=1)
    source: str | None = Field(default=None, min_length=1)
    target: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _fields_per_kind(self) -> Predicate:
        given = frozenset(a for a in _ARGUMENTS if getattr(self, a) is not None)
        needed = _REQUIRED[self.kind]
        if given != needed:
            raise ValueError(
                f"{self.kind} takes exactly {', '.join(sorted(needed))}; got "
                f"{', '.join(sorted(given)) or 'none'}"
            )
        return self


class ConclusionRegistered(StrictModel):
    """A researcher's conclusion with its basis (human; gate living.conclusion_register)."""

    conclusion_id: str = Field(pattern=CCL_ID_RE)
    statement: str = Field(min_length=1, max_length=2000)
    basis: tuple[BasisRef, ...] = Field(min_length=1)
    predicate: Predicate | None = None


class ConclusionRetired(StrictModel):
    """A researcher withdraws a conclusion from evaluation; the registration stays in the log."""

    conclusion_id: str = Field(pattern=CCL_ID_RE)
    reason: str = Field(min_length=1)


class ConclusionRecord(StrictModel):
    """A registered conclusion as the projection holds it (the researcher's view: it has the
    statement)."""

    conclusion_id: str
    statement: str
    basis: tuple[BasisRef, ...]
    predicate: Predicate | None
    registered_event: str
    retired: bool = False
    retire_reason: str | None = None


class ConclusionSnapshot(StrictModel):
    """A conclusion's computed state inside a snapshot blob: ids and values, no statement."""

    conclusion_id: str
    predicate_value: bool | None
    affected: tuple[str, ...]


class ConclusionDiff(StrictModel):
    """How one conclusion stands against a snapshot, computed (R-105)."""

    conclusion_id: str
    state: Literal["unchanged", "changed", "basis-affected", "new"]
    predicate_before: bool | None
    predicate_now: bool | None
    affected: tuple[str, ...]
    facts: FactsDiff | None
