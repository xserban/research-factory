"""Cited items: reference entries of all live extractions grouped by normalised title.

Invariants: read-only (writes no event, only syncs the index); deterministic for a given index;
ordering (by citing count, then key) never judges relevance. A cited item is computed on read,
never stored.

An entry with any clean-up flag (see `flags_for`) is not grouped: it is reported as unassessable
with its reasons. Entries that carry a DOI or arXiv id but no usable title are later given a title
by resolution, after which they can be grouped.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import text

from factory.services.context import Project

ITEM_RULES_VERSION: Final = "1"

_MIN_WORDS: Final = 3
_MIN_CHARS: Final = 12
_NOISE_START: Final = "[](){}.,;:-"
_NAME_SPLIT: Final = re.compile(r"\s*(?:,|;|&|\band\b)\s*", re.IGNORECASE)
_NAME_TOKEN: Final = re.compile(r"^(?:[A-Z]\.?|[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*\.?)$")
_INITIAL: Final = re.compile(r"^[A-Z]\.?$")


def normalise_title(title: str) -> str:
    """NFKC, case-folded, punctuation removed (letters and digits kept), spaces collapsed."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    kept = "".join(c if (c.isalnum() or c.isspace()) else " " for c in folded)
    return " ".join(kept.split())


def item_key(normalised: str) -> str:
    """`ci-` plus the first 16 hex characters of the SHA-256 of the normalised title."""
    return "ci-" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _looks_like_author_list(raw: str) -> bool:
    """Conservative: the raw title splits on `,` `;` `&` or `and` into at least two parts,
    every part is a personal name (2 to 4 capitalised tokens, initials allowed), and the list is
    either three or more names or contains an initial ("M. Smith, J. Doe"; "Dylan M Anstine and
    Olexandr Isayev"). Two plain full names ("Machine Learning, Deep Learning") are not flagged."""
    parts = [p for p in _NAME_SPLIT.split(raw.strip()) if p]
    if len(parts) < 2:
        return False
    has_initial = False
    for part in parts:
        tokens = part.split()
        if not 2 <= len(tokens) <= 4:
            return False
        if not all(_NAME_TOKEN.match(t) for t in tokens):
            return False
        has_initial = has_initial or any(_INITIAL.match(t) for t in tokens)
    return has_initial or len(parts) >= 3


def flags_for(title: str | None) -> tuple[str, ...]:
    """Computed clean-up flags, sorted: author-list, leading-noise, no-title, too-short."""
    if title is None or not title.strip():
        return ("no-title",)
    flags: set[str] = set()
    norm = normalise_title(title)
    if len(norm.split()) < _MIN_WORDS or len(norm) < _MIN_CHARS:
        flags.add("too-short")
    raw = title.strip()
    if raw[0] in _NOISE_START:
        flags.add("leading-noise")
    if _looks_like_author_list(raw):
        flags.add("author-list")
    return tuple(sorted(flags))


@dataclass(frozen=True)
class ItemEntry:
    extraction_id: str
    ordinal: int
    work_id: str


@dataclass(frozen=True)
class CitedItem:
    key: str
    title: str
    normalised: str
    citing_works: tuple[str, ...]
    entries: tuple[ItemEntry, ...]
    year: int | None
    dois: tuple[str, ...]
    arxivs: tuple[str, ...]

    @property
    def citing_count(self) -> int:
        return len(self.citing_works)


@dataclass
class Unassessable:
    extraction_id: str
    ordinal: int
    work_id: str
    reasons: tuple[str, ...]
    doi: str | None
    arxiv: str | None


@dataclass
class ItemsReport:
    items: list[CitedItem] = field(default_factory=list)
    unassessable: list[Unassessable] = field(default_factory=list)
    entries_total: int = 0
    rules_version: str = ITEM_RULES_VERSION


def cited_items(project: Project) -> ItemsReport:
    """Group live entries into cited items; flagged entries are unassessable."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT e.extraction_id, e.ordinal, x.work_id, e.title, e.year, e.doi, e.arxiv "
                "FROM reference_entries e JOIN reference_extractions x "
                "ON x.extraction_id = e.extraction_id WHERE x.live = 1 "
                "ORDER BY e.extraction_id, e.ordinal"
            )
        ).all()
    report = ItemsReport(entries_total=len(rows))
    groups: dict[str, list[tuple[ItemEntry, str, int | None, str | None, str | None]]] = (
        defaultdict(list)
    )
    norms: dict[str, str] = {}
    for eid, ordinal, wid, title, year, doi, arxiv in rows:
        flags = flags_for(title)
        if flags:
            report.unassessable.append(Unassessable(eid, ordinal, wid, flags, doi, arxiv))
            continue
        norm = normalise_title(title)
        key = item_key(norm)
        norms[key] = norm
        groups[key].append((ItemEntry(eid, ordinal, wid), title.strip(), year, doi, arxiv))
    for key, members in groups.items():
        counts = Counter(m[1] for m in members)
        best = min(counts, key=lambda t: (-counts[t], len(t), t))
        years = [m[2] for m in members if m[2] is not None]
        report.items.append(
            CitedItem(
                key=key,
                title=best,
                normalised=norms[key],
                citing_works=tuple(sorted({m[0].work_id for m in members})),
                entries=tuple(
                    sorted((m[0] for m in members), key=lambda e: (e.extraction_id, e.ordinal))
                ),
                year=min(years) if years else None,
                dois=tuple(sorted({m[3] for m in members if m[3]})),
                arxivs=tuple(sorted({m[4] for m in members if m[4]})),
            )
        )
    report.items.sort(key=lambda i: (-i.citing_count, i.key))
    return report
