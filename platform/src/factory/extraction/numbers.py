# ruff: noqa: RUF001, RUF002
"""Number tokens, canonical values and text normalisers.

Invariants: number tokens are matched whole (``82.4`` is never found inside
``182.45``); units are compared, never converted (a fraction is not rescaled
to a percentage); ``canonical`` yields a plain decimal string without
exponent or trailing zeros.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from factory.packs import FieldDef, UnitFamily

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+−]?\d+)?"
_TOKEN_RE = re.compile(
    r"(?<![\w.,])(?<![A-Za-z][-−])"
    rf"(?P<sign>[-+−])?(?P<num>{_NUM})"
    r"(?:(?P<suffix>%|[KMGTB](?![A-Za-z])))?"
)
_PRINTED_RE = re.compile(rf"[-+−]?{_NUM}")
_MULTIPLIER = {
    "": 1,
    "K": 10**3,
    "M": 10**6,
    "G": 10**9,
    "B": 10**9,
    "T": 10**12,
}


@dataclass(frozen=True)
class NumberToken:
    """A whole number found in text, with its attached suffix, if any."""

    value: Decimal
    suffix: str | None


def _to_decimal(sign: str | None, num: str) -> Decimal:
    d = Decimal(num.replace(",", "").replace("−", "-"))
    return -d if sign in ("-", "−") else d


def numbers_in(text: str) -> list[NumberToken]:
    """Return the whole number tokens of ``text`` in order."""
    return [
        NumberToken(_to_decimal(m.group("sign"), m.group("num")), m.group("suffix"))
        for m in _TOKEN_RE.finditer(text)
    ]


def parse_printed(value: str | int | float) -> Decimal | None:
    """Parse a bare printed number; None for suffixes, percent signs, text, bool, nan."""
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(repr(value)) if math.isfinite(value) else None
        s = value.strip()
        if not _PRINTED_RE.fullmatch(s):
            return None
        sign = s[0] if s[0] in "-+−" else None
        return _to_decimal(sign, s[1:] if sign else s)
    except InvalidOperation:
        return None


def canonical(printed: Decimal, unit: str | None, family: UnitFamily) -> str:
    """Canonical plain-decimal string: count fields are scaled by their unit; others unchanged."""
    d = printed
    if family is UnitFamily.COUNT:
        d = d * _MULTIPLIER.get(unit or "", 1)
    if d == 0:
        return "0"
    s = format(d.normalize(), "f")
    return s


def normalise_text(s: str) -> str:
    """NFKC, casefold, collapse whitespace."""
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


_RES_SQUARE = re.compile(r"(\d+)(?:\^2|²)?")
_RES_RECT = re.compile(r"(\d+)\s*[x×]\s*(\d+)")


def normalise_resolution(s: str) -> str:
    """Map ``224``, ``224²``, ``224^2``, ``224 × 224`` to ``224x224``; else normalise_text."""
    t = normalise_text(s.replace("\u00b2", "^2"))  # NFKC would turn ² into a digit
    m = _RES_SQUARE.fullmatch(t)
    if m:
        return f"{m.group(1)}x{m.group(1)}"
    m = _RES_RECT.fullmatch(t)
    if m:
        return f"{m.group(1)}x{m.group(2)}"
    return t


def normalise_for(field: FieldDef, s: str) -> str:
    """Normalise ``s`` with the field's normaliser, else as plain text."""
    if field.normaliser == "resolution":
        return normalise_resolution(s)
    return normalise_text(s)
