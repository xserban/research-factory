"""In-text citation markers: finding them and mapping them to bibliography entries.

Pure and deterministic. Three methods, in this priority at any text position: Markdown links to
`#b<n>` (`link`, exact), numeric brackets `[3]`, `[3, 5]`, `[3-6]` (`numeric`, mapped through the
entry labels when any entry has a numeric label, else through the ordinals) and author-year
`(Wang et al., 2021)` / `Wang et al. (2021)` (`author-year`, mapped by folded first-author surname
and year). The parenthetical body is capped at 200 characters each side of the year; a longer
parenthetical is not matched. A marker that maps to no entry is `unmatched`, to several
`ambiguous`; both carry `entry=None`. Only the marker token (at most `MAX_TOKEN` characters) is
kept, never body text.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from factory.document.anchors import AnchorKind, Manifest
from factory.references.parse import UPPER, Bibliography

MAX_TOKEN = 80
_MAX_RANGE = 200

MarkerState = Literal["matched", "unmatched", "ambiguous"]
Method = Literal["link", "numeric", "author-year"]

_SN = rf"[{UPPER}][\w'\u2019\-]+"
_YEAR = r"((?:19|20)\d{2})[a-z]?"
_MARKER_RE = re.compile(
    r"(?P<link>\[(?P<ltext>[^\]\[]*)\]\(#b(?P<ln>\d+)\))"
    r"|(?P<num>\[(?P<nbody>\d+(?:\s*[-\u2013\u2014,;]\s*\d+)*)\](?!\())"
    rf"|(?P<narr>(?P<nname>{_SN})(?:\s+et\s+al\.?|\s+(?:and|&)\s+{_SN})?\s*\((?P<nyear>(?:19|20)\d{{2}})[a-z]?\))"
    rf"|(?P<paren>\((?P<pbody>[^()]{{0,200}}?(?:19|20)\d{{2}}[a-z]?[^()]{{0,200}})\))"
)
_PART_RE = re.compile(rf"({_SN})(?:\s+et\s+al\.?|\s+(?:and|&)\s+{_SN})?,?\s+{_YEAR}")
_INT_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class Context:
    """One marker occurrence: where it is, what it cites (ordinal or None) and how."""

    citing_anchor: str
    entry: int | None
    marker: str
    method: Method
    state: MarkerState


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _token(text: str) -> str:
    return " ".join(text.split())[:MAX_TOKEN]


def find_contexts(manifest: Manifest, bib: Bibliography) -> tuple[list[Context], int]:
    """Contexts in document order and the number of distinct marker tokens.

    Markers are sought in paragraphs, table cells and figure captions outside the bibliography.
    """
    entry_ids = {e.anchor for e in bib.entries}
    ordinals = {e.ordinal for e in bib.entries}
    by_anchor = {e.anchor: e.ordinal for e in bib.entries}
    digit_labels: dict[int, list[int]] = {}
    if _digit_label_mode(bib):
        for e in bib.entries:
            if e.label is not None and e.label.isdigit():
                digit_labels.setdefault(int(e.label), []).append(e.ordinal)
    author_year: dict[tuple[str, int], list[int]] = {}
    for e in bib.entries:
        if e.fields.first_author and e.fields.year:
            key = (_fold(e.fields.first_author), e.fields.year)
            author_year.setdefault(key, []).append(e.ordinal)

    def numeric(number: int) -> tuple[int | None, MarkerState]:
        found = (
            digit_labels.get(number, [])
            if digit_labels
            else ([number] if number in ordinals else [])
        )
        if len(found) == 1:
            return found[0], "matched"
        return None, ("ambiguous" if found else "unmatched")

    contexts: list[Context] = []
    kinds = (AnchorKind.PARAGRAPH, AnchorKind.CELL, AnchorKind.FIGURE_CAPTION)
    for anchor in manifest.anchors:
        # bibliography entries (`b<n>`, or section paragraphs in the fallback) are never searched
        if anchor.kind is AnchorKind.BIBLIOGRAPHY_ENTRY or anchor.kind not in kinds:
            continue
        if anchor.id in entry_ids:
            continue
        for m in _MARKER_RE.finditer(anchor.text):
            if m.group("link"):
                text = " ".join(m.group("ltext").split())
                token = _token(f"[{text}]" if text.isdigit() else text or f"[{m.group('ln')}]")
                entry: int | None = by_anchor.get(f"b{m.group('ln')}")
                state: MarkerState = "matched" if entry is not None else "unmatched"
                contexts.append(Context(anchor.id, entry, token, "link", state))
            elif m.group("num"):
                token = _token(m.group("num"))
                for number in bracket_numbers(m.group("nbody")):
                    entry, state = numeric(number) if number is not None else (None, "unmatched")
                    contexts.append(Context(anchor.id, entry, token, "numeric", state))
            elif m.group("narr"):
                token = _token(m.group("narr"))
                contexts.append(
                    _by_author_year(
                        anchor.id, token, m.group("nname"), int(m.group("nyear")), author_year
                    )
                )
            else:
                for part in m.group("pbody").split(";"):
                    pm = _PART_RE.search(part)
                    if pm:
                        contexts.append(
                            _by_author_year(
                                anchor.id,
                                _token(pm.group(0)),
                                pm.group(1),
                                int(pm.group(2)),
                                author_year,
                            )
                        )
    return contexts, len({c.marker for c in contexts})


def _digit_label_mode(bib: Bibliography) -> bool:
    """True when at least half of the entries carry a numeric label (else ordinals are used)."""
    digits = sum(1 for e in bib.entries if e.label is not None and e.label.isdigit())
    return digits > 0 and 2 * digits >= len(bib.entries)


def bracket_numbers(body: str) -> list[int | None]:
    """The numbers a bracket body stands for; a descending or oversized range is one `None`."""
    out: list[int | None] = []
    for piece in re.split(r"[,;]", body):
        bounds = [int(x) for x in _INT_RE.findall(piece)]
        if len(bounds) == 1:
            out.append(bounds[0])
        elif bounds[0] <= bounds[1] and bounds[1] - bounds[0] < _MAX_RANGE:
            out.extend(range(bounds[0], bounds[1] + 1))
        else:
            out.append(None)
    return out


def _by_author_year(
    anchor_id: str,
    token: str,
    surname: str,
    year: int,
    index: dict[tuple[str, int], list[int]],
) -> Context:
    found = index.get((_fold(surname), year), [])
    if len(found) == 1:
        return Context(anchor_id, found[0], token, "author-year", "matched")
    return Context(anchor_id, None, token, "author-year", "ambiguous" if found else "unmatched")


def completeness_flags(bib: Bibliography, contexts: Sequence[Context]) -> tuple[str, ...]:
    """`parse-incomplete` and `marker-gap`, computed.

    `parse-incomplete`: an unmatched numeric marker or a numeric label exceeds the entry count,
    or the numeric labels are not exactly 1..k. `marker-gap`: a linked marker targets no entry.
    """
    count = len(bib.entries)
    labels = sorted(
        int(e.label)
        for e in bib.entries
        if _digit_label_mode(bib) and e.label is not None and e.label.isdigit()
    )
    incomplete = bool(labels) and (labels[-1] > count or labels != list(range(1, len(labels) + 1)))
    for c in contexts:
        if c.method == "numeric" and c.state == "unmatched":
            nums = [int(x) for x in _INT_RE.findall(c.marker)]
            if nums and max(nums) > count:
                incomplete = True
    flags: list[str] = []
    if incomplete:
        flags.append("parse-incomplete")
    if any(c.method == "link" and c.state == "unmatched" for c in contexts):
        flags.append("marker-gap")
    return tuple(flags)
