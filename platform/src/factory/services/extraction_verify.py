"""Row verification: kinds, units, declared fields, corpus links and evidence (plan 2D, task 4).

Invariants: a row is accepted only if it has no issue; issues are located as ``fields.<name>`` or
``fields.<name>.<attr>`` and carry fixed reasons, never document text. The service reads the
conversion's manifest and the corpus and writes nothing. The row's identity is `pack_row_key`:
the field named ``value`` for unkeyed packs, the pack's key fields for keyed ones.

A value outside a field's ``allowed`` enumeration is ``value-not-allowed``. Conditionals are
evaluated on the normalised value of their ``when`` field only when that field passed its kind
and ``allowed`` checks, so a row failing ``allowed`` reports only that; a forbidden field present
is ``not-allowed-for-kind`` and is not verified further. A field with ``allowed`` is stored as
its normalised value, so stored values compare with ``==``; other fields are stored as given.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from factory.document.anchors import Manifest
from factory.errors import ValidationIssue
from factory.extraction.numbers import normalise_for, parse_printed
from factory.extraction.verify import (
    ANCHOR_REQUIRED,
    ANCHOR_UNKNOWN,
    CELL_NOT_IN_ANCHOR_TABLE,
    CELL_UNKNOWN,
    QUOTE_NOT_IN_ANCHOR,
    QUOTE_REQUIRED,
    VerifiedField,
    pack_row_key,
    verify_field,
)
from factory.model.extraction import ExtractedRowInput, FieldInput, StoredField
from factory.model.protocol import ExtractionSchema
from factory.packs import FieldDef, FieldKind, Pack
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.search import list_works

VALUE_FIELD = "value"
UNDECLARED = "not declared in the protocol's extraction schema"
VALUE_NOT_ALLOWED = "value-not-allowed"
REQUIRED = "required"
NOT_ALLOWED_FOR_KIND = "not-allowed-for-kind"

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

    fields: dict[str, StoredField] | None
    row_key: str | None
    issues: list[ValidationIssue]


def verify_row(
    project: Project,
    pack: Pack,
    schema: ExtractionSchema,
    row: ExtractedRowInput,
    conversion_id: str,
) -> RowVerdict:
    """Verify ``row`` against the pinned conversion and the corpus. Read-only.

    The declared fields are ``schema.fields``. Raises `FactoryValidationError` on field
    `conversion_id` when the conversion is unknown or damaged.
    """
    manifest = conversion_manifest(project, conversion_id)
    corpus = {w.id for w in list_works(project)}
    return verify_row_in(pack, schema.fields, row.fields, conversion_id, manifest, corpus)


def verify_row_in(
    pack: Pack,
    declared: Collection[str],
    row: Mapping[str, FieldInput],
    conversion_id: str,
    manifest: Manifest,
    corpus: Collection[str],
) -> RowVerdict:
    """As `verify_row`, with the manifest and the corpus work ids already loaded."""
    issues: list[ValidationIssue] = []
    stored: dict[str, StoredField] = {}
    required, forbidden = _conditional_rules(pack, declared, row)
    for name, entry in row.items():
        field = pack.field(name)
        if field is None or name not in declared:
            issues.append(ValidationIssue(f"fields.{name}", UNDECLARED))
            continue
        if name in forbidden:
            issues.append(ValidationIssue(f"fields.{name}", NOT_ALLOWED_FOR_KIND))
            continue
        before = len(issues)
        issues.extend(_kind_issues(name, field, entry))
        if entry.cited_work is not None and entry.cited_work not in corpus:
            issues.append(ValidationIssue(f"fields.{name}.cited_work", "not a work of the corpus"))
        if len(issues) != before:
            continue
        out = verify_field(pack, field, entry, manifest)
        if isinstance(out, VerifiedField):
            stored[name] = _canonical_allowed(field, out.stored)
        else:
            issues.extend(
                ValidationIssue(f"fields.{name}.{_ATTR.get(reason, 'value')}", reason)
                for reason in out
            )
    missing = [n for n in (*pack.required, *required) if n not in row]
    issues.extend(ValidationIssue(f"fields.{n}", REQUIRED) for n in dict.fromkeys(missing))
    if issues:
        return RowVerdict(None, None, issues)
    if not pack.row_key_fields and not pack.row_per_work and VALUE_FIELD not in stored:
        # the pack does not require `value`: the row has no identity
        return RowVerdict(None, None, [ValidationIssue(f"fields.{VALUE_FIELD}", REQUIRED)])
    return RowVerdict(stored, pack_row_key(pack, conversion_id, stored), [])


def _canonical_allowed(field: FieldDef, value: StoredField) -> StoredField:
    """A field with an ``allowed`` enumeration is stored as its normalised (allowed) value."""
    if not field.allowed:
        return value
    return value.model_copy(update={"value": normalise_for(field, str(value.value))})


def _conditional_rules(
    pack: Pack, declared: Collection[str], row: Mapping[str, FieldInput]
) -> tuple[set[str], set[str]]:
    """The fields the pack's conditionals make required and forbidden for ``row``.

    A conditional applies only when its ``when`` field is declared, present and valid (right kind,
    inside ``allowed``); its value is compared after ``normalise_for``.
    """
    required: set[str] = set()
    forbidden: set[str] = set()
    for cond in pack.conditionals:
        when, entry = pack.field(cond.when), row.get(cond.when)
        if when is None or entry is None or cond.when not in declared:
            continue
        if _kind_issues(cond.when, when, entry):
            continue
        if normalise_for(when, str(entry.value)) in cond.values:
            (required if cond.rule == "required" else forbidden).add(cond.field)
    return required, forbidden


def _kind_issues(name: str, field: FieldDef, entry: FieldInput) -> list[ValidationIssue]:
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
    elif field.allowed and normalise_for(field, str(value)) not in field.allowed:
        out.append(ValidationIssue(f"fields.{name}.value", VALUE_NOT_ALLOWED))
    if entry.unit is not None and field.units and entry.unit not in field.units:
        out.append(ValidationIssue(f"fields.{name}.unit", "unit not allowed for this field"))
    return out


__all__ = ["RowVerdict", "verify_row", "verify_row_in"]
