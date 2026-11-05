"""Protocol limits applied to the fields of an imported record (slice 3d ruling 25; plan
Import-C ruling 3).

A pure function: no I/O, no project. The protocol's limits are free-form (`field`, `value`); the
ones read here are

- `year` (also `years`, `publication_year`): `2015-2025`, `2015-` (from), `-2025` (up to) or
  `2015` (that year only);
- `type` (also `work_type`, `document_type`): a comma-, semicolon- or `|`-separated list of the
  permitted types, by record type (`article`, `preprint`, ...) or work type (`journal-article`,
  `conference-paper`, ...);
- `language`: accepted but never violated, since an export carries no language.

Invariants:
- A record lacking the field a limit constrains is not outside it (unknown counts as within).
- A limit this module does not understand is ignored, never read as violated.
- The result lists limit field names in the protocol's order, without repeats.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from factory.imports.model import ImportFields, RecordType
from factory.model.protocol import Limit

_YEAR_FIELDS = frozenset({"year", "years", "publication_year", "publication year"})
_TYPE_FIELDS = frozenset({"type", "work_type", "work type", "document_type", "document type"})
_RANGE = re.compile(r"^\s*(\d{4})?\s*-\s*(\d{4})?\s*$")
_YEAR = re.compile(r"^\s*(\d{4})\s*$")
_SEPARATORS = re.compile(r"[,;|]")

_TYPE_NAMES: dict[RecordType, frozenset[str]] = {
    "article": frozenset({"article", "journal-article", "journal article"}),
    "inproceedings": frozenset(
        {"inproceedings", "conference-paper", "conference paper", "proceedings"}
    ),
    "preprint": frozenset({"preprint"}),
    "book": frozenset({"book", "book-chapter", "book chapter"}),
    "thesis": frozenset({"thesis"}),
    "report": frozenset({"report", "tech-report", "technical report"}),
    "other": frozenset(),
}


def outside_limits(fields: ImportFields, limits: Sequence[Limit]) -> tuple[str, ...]:
    """Names of the limits `fields` violates, in protocol order; empty when within."""
    violated: list[str] = []
    for limit in limits:
        name = limit.field.strip().lower()
        if (name in _YEAR_FIELDS and _year_outside(fields.year, limit.value)) or (
            name in _TYPE_FIELDS and _type_outside(fields.type, limit.value)
        ):
            violated.append(limit.field)
    return tuple(dict.fromkeys(violated))


def _year_outside(year: int | None, value: str) -> bool:
    if year is None:
        return False
    if (single := _YEAR.match(value)) is not None:
        return year != int(single.group(1))
    if (span := _RANGE.match(value)) is not None:
        low, high = span.group(1), span.group(2)
        return (low is not None and year < int(low)) or (high is not None and year > int(high))
    return False


def _type_outside(record_type: RecordType, value: str) -> bool:
    names = _TYPE_NAMES[record_type]
    if not names:
        return False
    allowed = {part.strip().lower() for part in _SEPARATORS.split(value) if part.strip()}
    return bool(allowed) and not (allowed & names)
