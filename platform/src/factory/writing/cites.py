"""Citation keys of one manuscript sentence (slice 7b, plan W-C ruling 2). Pure.

Declares: `cite_keys`.

Forms: LaTeX `\\cite`, `\\citep`, `\\citet`, `\\parencite`, `\\textcite`, `\\autocite` with their
capitalised and starred forms, keys split on `,`, in every format; pandoc `[@key]` and `@key`, and
numeric markers `[n]`, `[n-m]`, `[n, m]`, outside LaTeX. A number is a key; `bibfile` maps it to
the reference list through G1's `references/markers.py`.

Invariants:
- A key reaches an event, so it is never a run of the manuscript's text: anything that is not one
  token of at most `MAX_KEY` characters is replaced by a digest. The sentence stays cited, and the
  key resolves to nothing.
- Keys are NFC, in order of first appearance, without duplicates.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from factory.model.manuscripts import MAX_KEY
from factory.references.markers import bracket_numbers
from factory.writing.segment import Format

_LATEX = re.compile(
    r"\\(?:[Cc]ite[pt]?|[Pp]arencite|[Tt]extcite|[Aa]utocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{(?P<keys>[^{}]*)\}"
)
_PANDOC = re.compile(r"(?<![\w.@/\\])@(?P<key>\w(?:[\w:.#$%&+?<>~/-]*\w)?)")
_NUMERIC = re.compile(r"\[(?P<body>\d+(?:\s*[-\u2013\u2014,;]\s*\d+)*)\](?!\()")
_TOKEN = re.compile(rf"\S{{1,{MAX_KEY}}}")


def _safe(key: str) -> str:
    folded = unicodedata.normalize("NFC", key.strip())
    if _TOKEN.fullmatch(folded):
        return folded
    return "key:" + hashlib.sha256(folded.encode()).hexdigest()[:16]


def _numbers(body: str) -> list[str]:
    numbers = bracket_numbers(body)
    if None in numbers:  # a descending or oversized range names no entry
        return ["".join(body.split())]
    return [str(n) for n in numbers]


def cite_keys(sentence: str, fmt: Format) -> tuple[str, ...]:
    """The citation keys of a sentence (see the module docstring)."""
    found: list[tuple[int, str]] = []
    for m in _LATEX.finditer(sentence):
        found.extend((m.start(), k) for k in m.group("keys").split(",") if k.strip())
    if fmt != "latex":
        found.extend((m.start(), m.group("key")) for m in _PANDOC.finditer(sentence))
        for m in _NUMERIC.finditer(sentence):
            found.extend((m.start(), n) for n in _numbers(m.group("body")))
    found.sort(key=lambda item: item[0])  # stable: the keys of one marker keep their order
    return tuple(dict.fromkeys(_safe(key) for _, key in found))
