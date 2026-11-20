"""Precision of the spar and the ask, summarised from the researcher's ratings (plan spar-night N9).

Every number is computed from the index; nothing is typed. An agent's output is a proposal and the
researcher's rating decides (ruling 8): `sound`, `weak` or `wrong` on an argument
(`sheet.argument_rated`) or on an answer sentence (`chat.answer_rated`, sentence level).

Measures (conventions, stated here and in the hub's explanations):
- Precision of a group is sound / rated, where rated = sound + weak + wrong. Unrated arguments are
  counted (`unrated`) but never in the denominator. Below `MIN_N` (3) rated the figure is withheld
  and shown as "—"; a percentage is always shown with its n.
- Groups: stance, candidate source, strength, model, engine (v1 or v2) and v2 role. An argument is
  counted under every source that proposed its work on the sheet (`sheet_candidates.sources`), so
  the source rows add up to more than the total; one whose work has no candidate row counts under
  `unknown`. The role of a v2 argument is its stance (derived: arguments do not record their run);
  a v1 argument has no role.
- Critic against researcher (v2): the latest `sheet.argument_checked` verdict of an argument is
  compared with the researcher's rating on the mapping holds=sound, overreaches=weak, misread=wrong
  (a convention, not a finding). Raw agreement is the share on the diagonal; Cohen's kappa is
  shown only from `MIN_KAPPA_N` (10) compared arguments and is None when chance agreement is 1.
- `since` keeps ratings given on or after that date (ISO prefix); arguments rated earlier are left
  out (not counted as unrated); unrated arguments stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from factory.services.context import Project

MIN_N = 3
"""Rated arguments needed before a precision is shown."""
MIN_KAPPA_N = 10
"""Compared arguments needed before Cohen's kappa is shown."""
RATINGS = ("sound", "weak", "wrong")
VERDICT_TO_RATING = {"holds": "sound", "overreaches": "weak", "misread": "wrong"}
"""The convention that lines a critic verdict up with a researcher rating."""
DASH = "—"
DIMENSIONS = ("stance", "source", "strength", "model", "engine", "role")

MEASURES = {
    "precision": "The share of rated arguments you rated sound; shown only from 3 rated, always "
    "with the count behind it.",
    "unrated": "Arguments you have not rated yet; they are counted but not part of the share.",
    "source": "Which kind of search proposed the paper; an argument whose paper came from several "
    "sources counts under each, so these rows add up to more than the total.",
    "role": "In the agentic spar, a v2 role is the stance of the argument (against or for), "
    "derived because arguments do not record their run; the plain spar has no roles.",
    "since": "With a start date, arguments rated before it are left out (not counted as "
    "unrated); unrated arguments stay.",
    "agreement": "How often the critic's verdict matches your rating, counting holds as sound, "
    "overreaches as weak and misread as wrong; a raw share, with kappa from 10 comparisons.",
    "answers": "Your sentence ratings on answers, by the model that wrote them, with the same "
    "rules.",
}


@dataclass(frozen=True)
class Row:
    key: str
    sound: int
    weak: int
    wrong: int
    unrated: int
    rated: int
    precision: float | None
    """sound / rated, or None below `MIN_N` rated."""


@dataclass(frozen=True)
class Agreement:
    table: dict[str, dict[str, int]]
    """Critic verdict -> researcher rating -> count (latest check; rated arguments only)."""
    n: int
    agreed: int
    raw: float | None
    kappa: float | None


@dataclass(frozen=True)
class Precision:
    arguments: dict[str, tuple[Row, ...]]
    """`all` plus one table per dimension, rows sorted by key."""
    agreement: Agreement
    answers: dict[str, tuple[Row, ...]]
    """`all` and `model`: sentence ratings."""


def show_precision(row: Row) -> str:
    """`"67% (n=3)"`, or `"— (n=2)"` below the minimum."""
    if row.precision is None:
        return f"{DASH} (n={row.rated})"
    return f"{round(row.precision * 100)}% (n={row.rated})"


def _row(key: str, tally: dict[str, int]) -> Row:
    rated = sum(tally.get(r, 0) for r in RATINGS)
    sound = tally.get("sound", 0)
    return Row(
        key,
        sound,
        tally.get("weak", 0),
        tally.get("wrong", 0),
        tally.get("unrated", 0),
        rated,
        sound / rated if rated >= MIN_N else None,
    )


def _tables(groups: dict[str, dict[str, int]]) -> tuple[Row, ...]:
    return tuple(_row(k, groups[k]) for k in sorted(groups))


def agreement_of(table: dict[str, dict[str, int]]) -> Agreement:
    """Raw agreement and kappa of a verdict x rating table (the mapping is `VERDICT_TO_RATING`)."""
    n = sum(sum(r.values()) for r in table.values())
    agreed = sum(table.get(v, {}).get(r, 0) for v, r in VERDICT_TO_RATING.items())
    raw = agreed / n if n >= MIN_N else None
    kappa: float | None = None
    if n >= MIN_KAPPA_N:
        expected = sum(
            sum(table.get(v, {}).values()) * sum(t.get(r, 0) for t in table.values())
            for v, r in VERDICT_TO_RATING.items()
        ) / (n * n)
        if expected < 1:
            kappa = (agreed / n - expected) / (1 - expected)
    return Agreement(table, n, agreed, raw, kappa)


_ARGUMENTS = """
SELECT a.argument_id, a.stance, a.strength, a.model, r.rating, r.ts AS rated_ts,
       c.sources, q.engine,
       (SELECT k.verdict FROM argument_checks k WHERE k.argument_id = a.argument_id
        ORDER BY k.event_id DESC LIMIT 1) AS verdict
FROM sheet_arguments a
LEFT JOIN sheet_ratings r ON r.argument_id = a.argument_id
JOIN sheets s ON s.sheet_id = a.sheet_id
LEFT JOIN chat_requests q ON q.request_id = s.request_id
LEFT JOIN sheet_candidates c ON c.sheet_id = a.sheet_id AND c.work_id = a.work_id
"""
_SENTENCES = """
SELECT a.model, r.rating, r.ts AS rated_ts
FROM answer_sentences x
JOIN answers a ON a.answer_id = x.answer_id
LEFT JOIN answer_ratings r ON r.answer_id = x.answer_id AND r.sentence = x.idx
"""


def _bump(groups: dict[str, dict[str, int]], key: str, bucket: str) -> None:
    tally = groups.setdefault(key, {})
    tally[bucket] = tally.get(bucket, 0) + 1


def _kept(rating: Any, rated_ts: Any, since: str | None) -> str | None:
    """The bucket of a row (its rating, or `unrated`), or None when the rating is before `since`."""
    if rating is None:
        return "unrated"
    if since is not None and str(rated_ts) < since:
        return None
    return str(rating)


def precision(
    project: Project, *, sheet_ids: list[str] | None = None, since: str | None = None
) -> Precision:
    """The precision tables of the project (see the module docstring for every convention).
    `sheet_ids` limits the arguments to those sheets (answers are not filtered by it)."""
    project.index.sync()
    only = None if sheet_ids is None else set(sheet_ids)
    sql = _ARGUMENTS
    params: dict[str, Any] = {}
    if only is not None:
        names = {f"s{i}": s for i, s in enumerate(sorted(only))}
        sql += (
            " WHERE a.sheet_id IN (" + ", ".join(f":{n}" for n in names) + ")"
            if names
            else " WHERE 0"
        )
        params = names
    dims: dict[str, dict[str, dict[str, int]]] = {d: {} for d in ("all", *DIMENSIONS)}
    cross: dict[str, dict[str, int]] = {}
    sentences: dict[str, dict[str, int]] = {}
    answer_all: dict[str, dict[str, int]] = {}
    with project.index.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        sentence_rows = conn.execute(text(_SENTENCES)).mappings().all() if only is None else []
    for r in rows:
        bucket = _kept(r["rating"], r["rated_ts"], since)
        if bucket is None:
            continue
        engine = str(r["engine"] or "v1")
        _bump(dims["all"], "all", bucket)
        _bump(dims["stance"], str(r["stance"]), bucket)
        _bump(dims["strength"], str(r["strength"]), bucket)
        _bump(dims["model"], str(r["model"] or "unknown"), bucket)
        _bump(dims["engine"], engine, bucket)
        if engine == "v2":
            _bump(dims["role"], str(r["stance"]), bucket)
        for source in sorted({s for s in str(r["sources"] or "").split(",") if s}) or ["unknown"]:
            _bump(dims["source"], source, bucket)
        if bucket in RATINGS and r["verdict"] in VERDICT_TO_RATING:
            cell = cross.setdefault(str(r["verdict"]), {})
            cell[bucket] = cell.get(bucket, 0) + 1
    for r in sentence_rows:
        bucket = _kept(r["rating"], r["rated_ts"], since)
        if bucket is None:
            continue
        _bump(answer_all, "all", bucket)
        _bump(sentences, str(r["model"] or "unknown"), bucket)
    arguments = {d: _tables(g) for d, g in dims.items()}
    if not dims["all"]:
        arguments["all"] = (_row("all", {}),)
    return Precision(
        arguments,
        agreement_of(cross),
        {"all": _tables(answer_all) or (_row("all", {}),), "model": _tables(sentences)},
    )
