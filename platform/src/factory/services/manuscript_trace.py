"""Trace nodes and edges of manuscripts (slice 7b, plan W-C; spec Trace).

Read-only SQL on the connection `services.trace` already holds. A unit `msc_.../<ordinal>/<work_id>`
leads back to its verdict and the cited work; a verdict to the anchor of its quote, or to its
conversion when it quotes nothing, and from there along the existing chain to the document and the
work.

Invariants:
- No node holds the manuscript's text, a quote, a note or an audit label: only ids, the ordinal
  and the verdict.
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.model.identity import ULID_RE
from factory.model.manuscripts import MANUSCRIPT_VERDICT_ID_RE

Key = tuple[str, str]
Described = tuple[str, str]
MANUSCRIPT_KINDS = ("manuscript_unit", "manuscript_verdict")
_UNIT_RE = rf"^(msc_{ULID_RE})/([1-9][0-9]{{0,8}})/(rf:\S+)$"
MANUSCRIPT_PATTERNS: tuple[tuple[str, str], ...] = (
    (_UNIT_RE, "manuscript_unit"),
    (MANUSCRIPT_VERDICT_ID_RE, "manuscript_verdict"),
)


def _unit(ident: str) -> tuple[str, int, str] | None:
    m = re.fullmatch(_UNIT_RE, ident)
    return None if m is None else (m.group(1), int(m.group(2)), m.group(3))


def describe(conn: Connection, kind: str, ident: str) -> Described | None:
    """`(label, event_id)` of a manuscript node, or None when no row defines it."""
    if kind == "manuscript_verdict":
        row = conn.execute(
            text("SELECT verdict, event_id FROM manuscript_verdicts WHERE verdict_id = :i"),
            {"i": ident},
        ).first()
        return None if row is None else (f"manuscript verdict {row[0]}", str(row[1]))
    unit = _unit(ident)
    if unit is None:
        return None
    manuscript_id, ordinal, work_id = unit
    row = conn.execute(
        text(
            "SELECT c.event_id FROM manuscript_citations c, manuscript_sentences s, "
            "json_each(s.keys) j WHERE c.manuscript_id = :m AND s.manuscript_id = :m "
            "AND s.ordinal = :o AND j.value = c.key AND c.work_id = :w LIMIT 1"
        ),
        {"m": manuscript_id, "o": ordinal, "w": work_id},
    ).first()
    label = f"sentence {ordinal} of {manuscript_id} cites {work_id}"
    return None if row is None else (label, str(row[0]))


def edges(conn: Connection, kind: str, ident: str) -> tuple[list[Key], list[Key]]:
    """The upstream and downstream neighbours of a manuscript node."""
    if kind == "manuscript_verdict":
        row = conn.execute(
            text(
                "SELECT manuscript_id, ordinal, work_id, anchor, conversion_id "
                "FROM manuscript_verdicts WHERE verdict_id = :i"
            ),
            {"i": ident},
        ).first()
        if row is None:
            return [], []
        source: Key = (
            ("conversion", str(row[4])) if row[3] is None else ("anchor", f"{row[4]}/{row[3]}")
        )
        return [source], [("manuscript_unit", f"{row[0]}/{row[1]}/{row[2]}")]
    unit = _unit(ident)
    if unit is None:
        return [], []
    manuscript_id, ordinal, work_id = unit
    rows = conn.execute(
        text(
            "SELECT verdict_id FROM manuscript_verdicts "
            "WHERE manuscript_id = :m AND ordinal = :o AND work_id = :w"
        ),
        {"m": manuscript_id, "o": ordinal, "w": work_id},
    ).all()
    return [*(("manuscript_verdict", str(r[0])) for r in rows), ("work", work_id)], []
