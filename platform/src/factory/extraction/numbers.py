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
from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal

from factory.packs import FieldDef, UnitFamily

# ASCII digits only; exponents are capped at three digits so values stay finite.
_NUM = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?:[eE][-+−]?[0-9]{1,3})?"
_TIMES = r"(?:[ \t]*(?:×|x|\\times)[ \t]*10[ \t]*\^[ \t]*\{?(?P<texp>[-+−]?[0-9]{1,3})\}?)?"
_TOKEN_RE = re.compile(
    r"(?<![\w.,])(?<![A-Za-z][-−])"
    r"(?<!\^)(?<!\^\{)(?<!\^[-−+])(?<!\^\{[-−+])"
    rf"(?P<sign>[-+−])?(?P<num>{_NUM}){_TIMES}"
    r"(?![0-9]|[.,][0-9]|_|[eE][-+−]?[0-9])"
    r"(?:[ \t]*(?P<suffix>%|GFLOPs|GMACs|MB|[KMGTB])(?![A-Za-z0-9_]))?"
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
_WORD_UNITS = {"GFLOPs": "G", "GMACs": "G", "MB": "M"}
_FAMILY_UNITS: dict[UnitFamily, frozenset[str]] = {
    UnitFamily.COUNT: frozenset(_MULTIPLIER),
    UnitFamily.SCORE: frozenset({"", "%", "fraction"}),
}


@dataclass(frozen=True)
class NumberToken:
    """A whole number found in text, with its attached suffix, if any.

    ``suffix`` is one of ``%``, ``K M G T B``; the words ``GFLOPs``/``GMACs``/``MB``
    map to ``G``/``G``/``M``. Known limitation: in ``2^8`` the base ``2`` is a
    token and the exponent is not.
    """

    value: Decimal
    suffix: str | None


def _ctx(*parts: Decimal | int) -> Context:
    """A context wide enough that arithmetic on ``parts`` never rounds."""
    digits = sum(len(p.as_tuple().digits) if isinstance(p, Decimal) else len(str(p)) for p in parts)
    return Context(prec=max(60, digits + 20), Emax=MAX_EMAX, Emin=MIN_EMIN)


def _to_decimal(sign: str | None, num: str, texp: str | None = None) -> Decimal:
    d = Decimal(num.replace(",", ""))
    if texp is not None:
        d = d.scaleb(int(texp.replace("−", "-")), _ctx(d))
    return -d if sign in ("-", "−") else d


def numbers_in(text: str) -> list[NumberToken]:
    """Return the whole number tokens of ``text`` in order."""
    out: list[NumberToken] = []
    for m in _TOKEN_RE.finditer(text):
        suffix = m.group("suffix")
        out.append(
            NumberToken(
                _to_decimal(m.group("sign"), m.group("num").replace("−", "-"), m.group("texp")),
                _WORD_UNITS.get(suffix, suffix) if suffix else None,
            )
        )
    return out


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
        return _to_decimal(sign, (s[1:] if sign else s).replace("−", "-"))
    except ArithmeticError:
        return None


def canonical(printed: Decimal, unit: str | None, family: UnitFamily) -> str:
    """Exact canonical plain-decimal string: count fields are scaled by their unit.

    Arithmetic never rounds. Raises ValueError for a unit outside the COUNT
    (``K M G T B``) or SCORE (``%``, ``fraction``) vocabulary; other families
    take the value unchanged.
    """
    u = unit or ""
    vocab = _FAMILY_UNITS.get(family)
    if vocab is not None and u not in vocab:
        raise ValueError(f"unit {unit!r} is not in the {family.value} vocabulary")
    d = printed
    ctx = _ctx(d, _MULTIPLIER["T"])
    if family is UnitFamily.COUNT:
        d = ctx.multiply(d, Decimal(_MULTIPLIER[u]))
    if d == 0:
        return "0"
    return format(d.normalize(ctx), "f")


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
