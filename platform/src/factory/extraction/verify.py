"""Pure verification of one extracted field against its evidence in a manifest.

Invariants: a field is verified only against the anchored element it cites; a number is matched
as a whole token (``82.4`` is never found inside ``182.45``) and its suffix must agree with the
declared unit; a quote never spans two cells; reasons come from a fixed vocabulary and never carry
document text. Nothing here judges: the same input always gives the same verdict. False accepts
are worse than false rejects, so every doubtful case rejects.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.document.quotes import normalise_quote, quote_in_element
from factory.extraction.citations import citation_markers
from factory.extraction.numbers import (
    NumberToken,
    canonical,
    normalise_for,
    normalise_text,
    numbers_in,
    parse_printed,
)
from factory.packs import Check, FieldDef, FieldKind, Pack, UnitFamily

QUOTE_NOT_IN_ANCHOR = "quote-not-in-anchor"
ANCHOR_UNKNOWN = "anchor-unknown"
ANCHOR_REQUIRED = "anchor-required"
QUOTE_REQUIRED = "quote-required"
CELL_UNKNOWN = "cell-unknown"
CELL_NOT_IN_ANCHOR_TABLE = "cell-not-in-anchor-table"
NUMBER_NEEDS_CELL = "number-needs-cell"
NUMBER_NOT_IN_TEXT = "number-not-in-text"
NUMBER_NOT_IN_CELL = "number-not-in-cell"
UNIT_SUFFIX_MISMATCH = "unit-suffix-mismatch"
TEXT_NOT_IN_QUOTE = "text-not-in-quote"

_CELL_ID_RE = re.compile(r"^(t\d+)\.r(\d+)\.c\d+$")
_COUNT_SUFFIXES = frozenset("KMGTB")


@dataclass(frozen=True)
class FieldEntry:
    """What an agent declares for one field: a value and its evidence."""

    value: str | int | float | bool
    unit: str | None = None
    anchor: str | None = None
    cell: str | None = None
    quote: str | None = None
    reported_in: str = "own"
    reproduced: bool = False
    cited_work: str | None = None


@dataclass(frozen=True)
class StoredEntry(FieldEntry):
    """A verified entry plus the values the platform computed: canonical and copy marker."""

    canonical: str | None = None
    copy_marker: bool = False


@dataclass(frozen=True)
class VerifiedField:
    """A field that passed every check."""

    stored: StoredEntry


def cell_row(manifest: Manifest, cell_id: str) -> list[Anchor]:
    """The cells of the same table row as ``cell_id``, in column order; empty if unknown."""
    cell = manifest.get(cell_id)
    m = _CELL_ID_RE.match(cell_id)
    if cell is None or cell.kind is not AnchorKind.CELL or m is None:
        return []
    prefix = f"{m.group(1)}.r{m.group(2)}.c"
    return [a for a in manifest.anchors if a.kind is AnchorKind.CELL and a.id.startswith(prefix)]


def row_key(conversion_id: str, value: StoredEntry) -> str:
    """``rk_`` plus 12 hex of the hash of the conversion and the value field's location.

    The location is the value's cell (the anchor when that is itself a cell), else its anchor and
    canonical value. Equal for both passes when they cite the same place.
    """
    cell = value.cell
    if cell is None and value.anchor is not None and _CELL_ID_RE.match(value.anchor):
        cell = value.anchor
    location = cell if cell is not None else f"{value.anchor}\x1f{value.canonical}"
    digest = hashlib.sha256(f"{conversion_id}\x1f{location}".encode()).hexdigest()
    return f"rk_{digest[:12]}"


def verify_field(
    pack: Pack, field: FieldDef, entry: FieldEntry, manifest: Manifest
) -> VerifiedField | list[str]:
    """The stored field, or every reason it fails (fixed vocabulary, no document text).

    Preconditions: the value already has the field's kind (the caller checks kinds and units).
    """
    needs_evidence = field.check is not Check.NONE
    reasons: list[str] = []
    if entry.quote is None and needs_evidence:
        reasons.append(QUOTE_REQUIRED)
    if entry.anchor is None:
        if needs_evidence or entry.quote is not None or entry.cell is not None:
            return [ANCHOR_REQUIRED, *reasons]
        return _stored(entry, None, False)
    anchor = manifest.get(entry.anchor)
    if anchor is None:
        return [*reasons, ANCHOR_UNKNOWN]

    quote_ok = True
    if entry.quote is not None:
        quote_ok = quote_in_element(anchor.text, entry.quote)
        if not quote_ok:
            reasons.append(QUOTE_NOT_IN_ANCHOR)

    cell, cell_reasons = _resolve_cell(entry, anchor, manifest)
    reasons.extend(cell_reasons)

    if field.check is Check.NUMBER:
        reasons.extend(_number_reasons(field, entry, anchor, cell))
    elif field.check is Check.TEXT_IN_QUOTE and not _text_in(field, entry, cell):
        reasons.append(TEXT_NOT_IN_QUOTE)
    if reasons:
        return reasons

    canon: str | None = None
    if field.check is Check.NUMBER:
        printed = parse_printed(entry.value)
        assert printed is not None  # _number_reasons rejected an unparseable value
        try:
            canon = canonical(printed, entry.unit, field.unit_family)
        except ValueError:  # a unit outside the family's vocabulary
            return [UNIT_SUFFIX_MISMATCH]
    marker = field.check is Check.NUMBER and _copy_marker(pack, entry, cell, manifest)
    return _stored(entry, canon, marker)


def _stored(entry: FieldEntry, canon: str | None, marker: bool) -> VerifiedField:
    return VerifiedField(
        StoredEntry(
            value=entry.value,
            unit=entry.unit,
            anchor=entry.anchor,
            cell=entry.cell,
            quote=entry.quote,
            reported_in=entry.reported_in,
            reproduced=entry.reproduced,
            cited_work=entry.cited_work,
            canonical=canon,
            copy_marker=marker,
        )
    )


def _resolve_cell(
    entry: FieldEntry, anchor: Anchor, manifest: Manifest
) -> tuple[Anchor | None, list[str]]:
    """The one cell the evidence points at: ``cell``, or the anchor when it is itself a cell."""
    if entry.cell is None:
        return (anchor, []) if anchor.kind is AnchorKind.CELL else (None, [])
    cell = manifest.get(entry.cell)
    if cell is None or cell.kind is not AnchorKind.CELL:
        return None, [CELL_UNKNOWN]
    if anchor.kind is AnchorKind.CELL:
        return (cell, []) if cell.id == anchor.id else (None, [CELL_NOT_IN_ANCHOR_TABLE])
    if anchor.kind is not AnchorKind.TABLE or cell.parent != anchor.id:
        return None, [CELL_NOT_IN_ANCHOR_TABLE]
    return cell, []


def _number_reasons(
    field: FieldDef, entry: FieldEntry, anchor: Anchor, cell: Anchor | None
) -> list[str]:
    if anchor.kind is AnchorKind.TABLE and entry.cell is None:
        return [NUMBER_NEEDS_CELL]
    printed = parse_printed(entry.value)
    if printed is None:
        return [NUMBER_NOT_IN_TEXT]
    if entry.cell is not None and cell is None:
        return []  # the cell reason is already reported
    if cell is not None:
        return _match_reasons(field, entry.unit, printed, cell.text, NUMBER_NOT_IN_CELL)
    if entry.quote is None:
        return []  # quote-required is already reported
    return _match_reasons(field, entry.unit, printed, entry.quote, NUMBER_NOT_IN_TEXT)


def _match_reasons(
    field: FieldDef, unit: str | None, printed: Decimal, text: str, absent: str
) -> list[str]:
    same = [t for t in numbers_in(normalise_quote(text)) if t.value == printed]
    if any(_suffix_agrees(field.unit_family, unit, t) for t in same):
        return []
    return [UNIT_SUFFIX_MISMATCH] if same else [absent]


def _suffix_agrees(family: UnitFamily, unit: str | None, token: NumberToken) -> bool:
    """A bare token agrees with any unit; a suffix only with its own family and unit.

    ``%`` goes with a score field whose unit is ``%`` or unstated (never ``fraction``);
    ``K M G T B`` go with a count field whose unit is that suffix (``B`` and ``G`` are the same).
    """
    suffix = token.suffix
    if suffix is None:
        return True
    if suffix == "%":
        return family is UnitFamily.SCORE and (unit or "%") == "%"
    if suffix in _COUNT_SUFFIXES and family is UnitFamily.COUNT:
        want = unit or suffix
        return _alias(want) == _alias(suffix)
    return False


def _alias(unit: str) -> str:
    return "G" if unit == "B" else unit


def _text_in(field: FieldDef, entry: FieldEntry, cell: Anchor | None) -> bool:
    value = normalise_for(field, str(entry.value))
    if not value:
        return False
    sources = [s for s in (entry.quote, cell.text if cell else None) if s is not None]
    return any(value in normalise_text(s) for s in sources)


def _copy_marker(pack: Pack, entry: FieldEntry, cell: Anchor | None, manifest: Manifest) -> bool:
    """A citation marker in any cell of the value cell's row, else in the quote."""
    if cell is not None:
        texts = [a.text for a in cell_row(manifest, cell.id)]
    else:
        texts = [entry.quote] if entry.quote else []
    return any(citation_markers(t, pack.citation_patterns) for t in texts)


__all__ = [
    "FieldEntry",
    "FieldKind",
    "StoredEntry",
    "VerifiedField",
    "cell_row",
    "row_key",
    "verify_field",
]
