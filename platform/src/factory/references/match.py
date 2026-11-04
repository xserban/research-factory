"""Title matching of a parsed reference entry against candidate works (spec ruling 16).

Pure and deterministic: the same fields, candidates and `MATCHER_VERSION` give the same `Match`,
whatever the order of the candidates. Similarity is the `difflib.SequenceMatcher` ratio of the
`normalize_title` strings.

Rules, in order:
- A candidate is *eligible* when the years are within `YEAR_TOLERANCE`; for an exact match the
  first-author surnames must also agree. Each check applies only when both sides carry the value.
- Exactly one eligible candidate with an equal normalised title: `resolved`, `title-exact`.
  Several: `ambiguous`.
- Otherwise the best eligible candidate with ratio >= `TITLE_FUZZY` and a margin >= `MARGIN` over
  the runner-up (any candidate): `unconfirmed`, `title-fuzzy`.
- Otherwise any candidate with ratio >= `TITLE_FLOOR`: `ambiguous`.
- Otherwise `unresolved` (reason `no-title`, `no-candidates` or `below-floor`).

`candidates` lists at most `MAX_CANDIDATES` candidates scoring at least `TITLE_FLOOR`, by score
descending, ties by work id. Scores are rounded to four decimals; comparisons use the raw ratio.
The thresholds are provisional (spec open question 1) and versioned with the matcher.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from factory.model.references import MAX_CANDIDATES, Confidence, LinkState
from factory.model.work_ids import normalize_title
from factory.references.parse import RefFields

MATCHER = "refmatch"
MATCHER_VERSION = "1"
TITLE_FUZZY = 0.92
TITLE_FLOOR = 0.85
MARGIN = 0.03
YEAR_TOLERANCE = 1


@dataclass(frozen=True)
class Candidate:
    """A work a title may match: its id, title, first author (display name) and year."""

    work_id: str
    title: str
    first_author: str | None
    year: int | None


@dataclass(frozen=True)
class Match:
    """The matcher's verdict. `work_id` is set only for `resolved` and `unconfirmed`."""

    state: LinkState
    confidence: Confidence | None
    score: float | None
    work_id: str | None
    candidates: tuple[tuple[str, float], ...]
    reason: str | None


def title_score(a: str, b: str) -> float:
    """The ratio of the normalised titles, 0 when either is empty after normalisation."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb, autojunk=False).ratio()


def surname_key(name: str) -> str:
    """The comparison form of a surname or a display name: its last normalised token."""
    tokens = normalize_title(name).split()
    return tokens[-1] if tokens else ""


def _year_ok(a: int | None, b: int | None) -> bool:
    return a is None or b is None or abs(a - b) <= YEAR_TOLERANCE


def _surname_ok(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return True
    ka, kb = surname_key(a), surname_key(b)
    return not ka or not kb or ka == kb


def _unresolved(reason: str) -> Match:
    return Match(LinkState.UNRESOLVED, None, None, None, (), reason)


def match_title(fields: RefFields, candidates: Sequence[Candidate]) -> Match:
    """Match an entry's title against `candidates` by the rules of the module docstring."""
    title = normalize_title(fields.title) if fields.title else ""
    if not title:
        return _unresolved("no-title")
    if not candidates:
        return _unresolved("no-candidates")
    floor_ratio = TITLE_FLOOR
    scored: list[tuple[float, Candidate]] = []
    for c in sorted(candidates, key=lambda c: c.work_id):
        other = normalize_title(c.title)
        if not other:
            continue
        matcher = SequenceMatcher(None, title, other, autojunk=False)
        # Cheap upper bounds first: most candidates of a corpus are far below the floor.
        if matcher.real_quick_ratio() < floor_ratio or matcher.quick_ratio() < floor_ratio:
            continue
        scored.append((1.0 if other == title else matcher.ratio(), c))
    scored = [s for s in scored if s[0] >= floor_ratio]
    if not scored:
        return _unresolved("below-floor")
    scored.sort(key=lambda s: (-s[0], s[1].work_id))
    listed = tuple((c.work_id, round(score, 4)) for score, c in scored[:MAX_CANDIDATES])

    exact = [
        c
        for score, c in scored
        if score == 1.0
        and _year_ok(fields.year, c.year)
        and _surname_ok(fields.first_author, c.first_author)
    ]
    if len(exact) == 1:
        return Match(
            LinkState.RESOLVED, Confidence.TITLE_EXACT, 1.0, exact[0].work_id, listed, None
        )
    if len(exact) > 1:
        return Match(LinkState.AMBIGUOUS, None, 1.0, None, listed, None)

    eligible = [(score, c) for score, c in scored if _year_ok(fields.year, c.year)]
    if eligible:
        best_score, best = eligible[0]
        runner = max((s for s, c in scored if c is not best), default=0.0)
        if best_score >= TITLE_FUZZY and best_score - runner >= MARGIN:
            return Match(
                LinkState.UNCONFIRMED,
                Confidence.TITLE_FUZZY,
                round(best_score, 4),
                best.work_id,
                listed,
                None,
            )
    return Match(LinkState.AMBIGUOUS, None, listed[0][1], None, listed, None)
