"""The generic `contribution` pack, version 1 (pure data; slice 3b ruling 7, G2-A ruling 5).

Invariants: ``item_kind`` is the only pack-required field; every other requirement and
prohibition is a `Conditional` on ``item_kind``. ``not-stated`` items carry only
``absent_kind`` (``base-idea`` or ``limitation``) and no quote. ``statement``, quotes and anchors
are never compared between passes. ``metric`` is a key field so that several results quoted
from one element keep distinct row keys (it is absent, hence ``""``, for other kinds).
The unit of ``value`` is its `FieldInput.unit`, not a field.
"""

from __future__ import annotations

from factory.packs.ml_benchmark import CITATION_PATTERNS
from factory.packs.model import Check, Conditional, FieldDef, FieldKind, Pack, UnitFamily

CONTRIBUTION_PACK = "contribution"
ITEM_KINDS = ("base-idea", "addition", "result", "limitation", "not-stated")
ABSENT_KINDS = ("base-idea", "limitation")

_T, _N, _I = FieldKind.TEXT, FieldKind.NUMBER, FieldKind.INTEGER
_NONE_U = UnitFamily.NONE
_TQ, _NUM, _NOCHK = Check.TEXT_IN_QUOTE, Check.NUMBER, Check.NONE

_STATED = ("base-idea", "addition", "result", "limitation")
_NOT_STATED = ("not-stated",)
_CONTENT = ("name", "statement", "compared_to", "cited_entry", "metric", "value", "result_row")


def _req(field: str, values: tuple[str, ...]) -> Conditional:
    return Conditional(field, "item_kind", values, "required")


def _forbid(field: str, values: tuple[str, ...]) -> Conditional:
    return Conditional(field, "item_kind", values, "forbidden")


CONTRIBUTION_V1 = Pack(
    name=CONTRIBUTION_PACK,
    version=1,
    fields=(
        FieldDef("item_kind", "item", _T, _NONE_U, _NOCHK, allowed=ITEM_KINDS),
        FieldDef("absent_kind", "item", _T, _NONE_U, _NOCHK, allowed=ABSENT_KINDS),
        FieldDef("name", "content", _T, _NONE_U, _TQ),
        FieldDef("statement", "content", _T, _NONE_U, _TQ),
        FieldDef("compared_to", "content", _T, _NONE_U, _TQ),
        FieldDef("cited_entry", "link", _I, _NONE_U, _NOCHK, unitless=True),
        FieldDef("metric", "result", _T, _NONE_U, _TQ),
        FieldDef("value", "result", _N, UnitFamily.SCORE, _NUM, ("%", "fraction", "")),
        FieldDef("result_row", "link", _T, _NONE_U, _NOCHK),
    ),
    required=("item_kind",),
    default_comparability_keys=(),
    citation_patterns=CITATION_PATTERNS,
    conditionals=(
        _req("absent_kind", _NOT_STATED),
        _forbid("absent_kind", _STATED),
        *(_forbid(f, _NOT_STATED) for f in _CONTENT),
        _req("statement", _STATED),
        _req("name", ("base-idea", "addition")),
        _req("metric", ("result",)),
        _req("value", ("result",)),
        *(_forbid(f, ("base-idea", "addition", "limitation")) for f in ("metric", "value")),
        _forbid("result_row", ("base-idea", "addition", "limitation")),
        _forbid("compared_to", ("base-idea", "limitation")),
        _forbid("cited_entry", ("limitation",)),
    ),
    row_key_fields=("item_kind", "absent_kind", "name", "metric"),
    row_anchor_fields=("name", "statement", "compared_to"),
    compared_fields=("item_kind", "absent_kind", "name", "cited_entry", "value"),
)

__all__ = ["ABSENT_KINDS", "CONTRIBUTION_PACK", "CONTRIBUTION_V1", "ITEM_KINDS"]
