"""Row verification: kinds, units, declared fields, corpus links and evidence (plan 2D, task 4).

Invariants: a row is accepted only if it has no issue; issues are located as ``fields.<name>`` or
``fields.<name>.<attr>`` and carry fixed reasons, never document text. The service reads the
conversion's manifest and the corpus and writes nothing. The row's identity comes from the field
named ``value``.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from factory.document.anchors import Manifest
from factory.errors import ValidationIssue
from factory.extraction.numbers import parse_printed
from factory.extraction.verify import (
    ANCHOR_REQUIRED,
    ANCHOR_UNKNOWN,
    CELL_NOT_IN_ANCHOR_TABLE,
    CELL_UNKNOWN,
    QUOTE_NOT_IN_ANCHOR,
    QUOTE_REQUIRED,
    FieldEntry,
    StoredEntry,
    VerifiedField,
    row_key,
    verify_field,
)
from factory.packs import FieldDef, FieldKind, Pack
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.search import list_works

VALUE_FIELD = "value"
UNDECLARED = "not declared in the protocol's extraction schema"

_ATTR = {
    ANCHOR_UNKNOWN: "anchor",
    ANCHOR_REQUIRED: "anchor",
    QUOTE_NOT_IN_ANCHOR: "quote",
    QUOTE_REQUIRED: "quote",
    CELL_UNKNOWN: "cell",
    CELL_NOT_IN_ANCHOR_TABLE: "cell",
    "number-needs-cell": "cell",
}


@dataclass(frozen=True)
class RowVerdict:
    """``fields`` and ``row_key`` are set only when ``issues`` is empty."""

    fields: dict[str, StoredEntry] | None
    row_key: str | None
    issues: list[ValidationIssue]


def verify_row(
    project: Project,
    pack: Pack,
    declared: Collection[str],
    row: Mapping[str, FieldEntry],
    conversion_id: str,
) -> RowVerdict:
    """Verify ``row`` against the pinned conversion and the corpus. Read-only.

    ``declared`` are the schema's field names. Raises `FactoryValidationError` on field
    `conversion_id` when the conversion is unknown or damaged.
    """
    manifest = conversion_manifest(project, conversion_id)
    corpus = {w.id for w in list_works(project)}
    return verify_row_in(pack, declared, row, conversion_id, manifest, corpus)


def verify_row_in(
    pack: Pack,
    declared: Collection[str],
    row: Mapping[str, FieldEntry],
    conversion_id: str,
    manifest: Manifest,
    corpus: Collection[str],
) -> RowVerdict:
    """As `verify_row`, with the manifest and the corpus work ids already loaded."""
    issues: list[ValidationIssue] = []
    stored: dict[str, StoredEntry] = {}
    for name, entry in row.items():
        field = pack.field(name)
        if field is None or name not in declared:
            issues.append(ValidationIssue(f"fields.{name}", UNDECLARED))
            continue
        before = len(issues)
        issues.extend(_kind_issues(name, field, entry))
        if entry.cited_work is not None and entry.cited_work not in corpus:
            issues.append(ValidationIssue(f"fields.{name}.cited_work", "not a work of the corpus"))
        if len(issues) != before:
            continue
        out = verify_field(pack, field, entry, manifest)
        if isinstance(out, VerifiedField):
            stored[name] = out.stored
        else:
            issues.extend(
                ValidationIssue(f"fields.{name}.{_ATTR.get(reason, 'value')}", reason)
                for reason in out
            )
    issues.extend(
        ValidationIssue(f"fields.{name}", "required") for name in pack.required if name not in row
    )
    if issues:
        return RowVerdict(None, None, issues)
    return RowVerdict(stored, row_key(conversion_id, stored[VALUE_FIELD]), [])


def _kind_issues(name: str, field: FieldDef, entry: FieldEntry) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []
    value = entry.value
    problem: str | None = None
    if field.kind is FieldKind.BOOL:
        problem = None if isinstance(value, bool) else "not a boolean"
    elif field.kind in (FieldKind.NUMBER, FieldKind.INTEGER):
        number = parse_printed(value)
        if number is None:
            problem = "not a number"
        elif field.kind is FieldKind.INTEGER and number != number.to_integral_value():
            problem = "not an integer"
    elif not isinstance(value, str) or not value.strip():
        problem = "not text"
    if problem is not None:
        out.append(ValidationIssue(f"fields.{name}.value", problem))
    if entry.unit is not None and field.units and entry.unit not in field.units:
        out.append(ValidationIssue(f"fields.{name}.unit", "unit not allowed for this field"))
    return out


__all__ = ["RowVerdict", "verify_row", "verify_row_in"]
