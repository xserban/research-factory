"""Value checks of property assertions (slice 6, plan H-A, rulings 3 and 4). Pure.

Invariants:
- `check_value` decides only whether a value is well formed for its property: an `enum` value is
  allowed; a `set` is a non-empty subset of the allowed values, stored sorted and unique; a `bool`
  is a bool; a `number` is a decimal string with a unit valid for the property's unit family,
  canonicalised by the extraction rules (`extraction.numbers.canonical`).
- `value_in_quote` decides only whether a quote can carry the value. Text values (and aliases) are
  found as whole words after quote normalisation and case folding. A `bool` is carried by an alias
  of the property itself, and `false` is never carried: the platform cannot verify a negation, so
  `false` needs an `inferred` or `researcher` basis. A number is carried by a whole number token
  that equals the printed value with an agreeing suffix, as in the extraction number check.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from factory.document.quotes import normalise_quote
from factory.extraction.numbers import canonical, numbers_in, parse_printed
from factory.extraction.verify import suffix_agrees
from factory.model.cards import PropertyDef, PropertyKind
from factory.packs import UnitFamily

Value = str | Sequence[str] | bool

VALUE_NOT_ALLOWED = "value-not-allowed"
EMPTY_SET = "empty-set"
UNIT_INVALID = "unit-invalid"
NOT_A_NUMBER = "not-a-number"


@dataclass(frozen=True)
class ValueVerdict:
    ok: bool
    reason: str | None
    canonical: str | None
    value_norm: tuple[str, ...]


def _bad(reason: str) -> ValueVerdict:
    return ValueVerdict(ok=False, reason=reason, canonical=None, value_norm=())


def check_value(defn: PropertyDef, value: Value, unit: str | None) -> ValueVerdict:
    """Whether `value` (with `unit`, for a number) is well formed for `defn`; see the module
    docstring. Reasons: `value-not-allowed`, `empty-set`, `unit-invalid`, `not-a-number`."""
    if defn.kind is PropertyKind.ENUM:
        if isinstance(value, str) and value in defn.allowed:
            return ValueVerdict(ok=True, reason=None, canonical=None, value_norm=(value,))
        return _bad(VALUE_NOT_ALLOWED)
    if defn.kind is PropertyKind.SET:
        if isinstance(value, str | bool):
            return _bad(VALUE_NOT_ALLOWED)
        members = sorted(set(value))
        if not members:
            return _bad(EMPTY_SET)
        if any(m not in defn.allowed for m in members):
            return _bad(VALUE_NOT_ALLOWED)
        return ValueVerdict(ok=True, reason=None, canonical=None, value_norm=tuple(members))
    if defn.kind is PropertyKind.BOOL:
        if isinstance(value, bool):
            return ValueVerdict(
                ok=True, reason=None, canonical=None, value_norm=("true" if value else "false",)
            )
        return _bad(VALUE_NOT_ALLOWED)
    return _check_number(defn, value, unit)


def _check_number(defn: PropertyDef, value: Value, unit: str | None) -> ValueVerdict:
    printed = parse_printed(value) if isinstance(value, str) else None
    if printed is None or defn.unit_family is None:
        return _bad(NOT_A_NUMBER)
    if defn.unit_family is UnitFamily.NONE and unit:
        return _bad(UNIT_INVALID)
    try:
        canon = canonical(printed, unit, defn.unit_family)
    except ValueError:
        return _bad(UNIT_INVALID)
    return ValueVerdict(ok=True, reason=None, canonical=canon, value_norm=(canon,))


def _words(text: str) -> str:
    return normalise_quote(text).casefold()


def _has_word(haystack: str, needle: str) -> bool:
    """Whether the case-folded `needle` occurs in `haystack` delimited by non-word characters."""
    pattern = r"(?<!\w)" + re.escape(_words(needle)) + r"(?!\w)"
    return re.search(pattern, haystack) is not None


def _carried(text: str, token: str, aliases: Sequence[str]) -> bool:
    return any(_has_word(text, candidate) for candidate in (token, *aliases))


def value_in_quote(defn: PropertyDef, value: Value, quote: str, *, unit: str | None = None) -> bool:
    """Whether `quote` can carry `value` for `defn` (module docstring). `unit` is the number's."""
    text = _words(quote)
    if defn.kind in (PropertyKind.ENUM, PropertyKind.SET):
        if isinstance(value, bool):
            return False
        members = [value] if isinstance(value, str) else list(value)
        return bool(members) and all(
            _carried(text, m, defn.value_aliases.get(m, ())) for m in members
        )
    if defn.kind is PropertyKind.BOOL:
        return value is True and any(_has_word(text, alias) for alias in defn.aliases)
    return _number_in(defn, value, normalise_quote(quote), unit)


def _number_in(defn: PropertyDef, value: Value, text: str, unit: str | None) -> bool:
    printed: Decimal | None = parse_printed(value) if isinstance(value, str) else None
    if printed is None or defn.unit_family is None:
        return False
    return any(
        t.value == printed and suffix_agrees(defn.unit_family, unit, t) for t in numbers_in(text)
    )
