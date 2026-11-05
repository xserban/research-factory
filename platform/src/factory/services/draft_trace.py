"""Trace nodes and edges of drafts (slice 7b, plan W-B, task 6; spec Trace). This closes R-01's
chain "claim -> synthesis sentence".

Read-only SQL on the connection `services.trace` already holds. Upstream of a sentence are its
supports and the sentence it superseded; downstream its draft, its verdicts and the sentence that
superseded it, so a back trace from a sentence reaches the question through each support kind and a
forward trace from a claim, cell, item or edge reaches the sentences citing it and their drafts.

Invariants:
- A `stat` is a leaf: the platform computes it from the log and it has no upstream node. A `group`
  leads to the value cells of its visible rows.
- A support that names nothing still appears, as a missing node, so a broken link is visible.
- No audit label, verdict note or input is shown in any node.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.model.drafts import (
    DRAFT_ID_RE,
    GROUP_ID_RE,
    SENTENCE_ID_RE,
    VERDICT_ID_RE,
    SupportKind,
)
from factory.services.context import Project

Key = tuple[str, str]
Described = tuple[str, str]
DRAFT_KINDS = ("group", "stat", "sentence", "verdict", "draft")
DRAFT_PATTERNS: tuple[tuple[str, str], ...] = (
    (DRAFT_ID_RE, "draft"),
    (SENTENCE_ID_RE, "sentence"),
    (VERDICT_ID_RE, "verdict"),
    (GROUP_ID_RE, "group"),
    (r"^stat:\S+$", "stat"),
)
CITABLE_KINDS = ("claim", "cell", "extraction", "relation", "cites", "interpretation", "concept")


def _support_key(kind: str, ref: str) -> Key:
    """The trace node of a support."""
    support = SupportKind(kind)
    if support is SupportKind.STAT:
        return ("stat", f"stat:{ref}")
    if support is SupportKind.GROUP:
        return ("group", ref)
    if support is SupportKind.ITEM:
        return ("extraction", ref)
    if support is SupportKind.EDGE:
        return ("cites" if ref.startswith("cit:") else "relation", ref)
    if support is SupportKind.INTERP:
        return ("interpretation" if ref.startswith("int_") else "concept", ref)
    return (support.value, ref)


def _cited(conn: Connection, kind: str, ref: str) -> str | None:
    """The first event of a sentence citing the support, or None."""
    row = conn.execute(
        text(
            "SELECT MIN(s.event_id) FROM sentence_supports u JOIN draft_sentences s "
            "ON s.sentence_id = u.sentence_id WHERE u.kind = :k AND u.ref = :r"
        ),
        {"k": kind, "r": ref},
    ).first()
    return None if row is None or row[0] is None else str(row[0])


def describe(conn: Connection, kind: str, ident: str) -> Described | None:
    """`(label, event_id)` of a draft node, or None when no row defines it."""
    if kind == "draft":
        row = conn.execute(
            text("SELECT title, event_id FROM drafts WHERE draft_id = :i"), {"i": ident}
        ).first()
        return None if row is None else (f"draft {row[0]}", str(row[1]))
    if kind == "sentence":
        row = conn.execute(
            text("SELECT cls, text, event_id FROM draft_sentences WHERE sentence_id = :i"),
            {"i": ident},
        ).first()
        return None if row is None else (f"{row[0]} sentence: {row[1]}", str(row[2]))
    if kind == "verdict":
        row = conn.execute(
            text("SELECT verdict, event_id FROM sentence_verdicts WHERE verdict_id = :i"),
            {"i": ident},
        ).first()
        return None if row is None else (f"verdict {row[0]}", str(row[1]))
    if kind == "group":
        event = _cited(conn, "group", ident)
        return None if event is None else (f"group {ident}", event)
    event = _cited(conn, "stat", ident.removeprefix("stat:"))
    return None if event is None else (f"computed figure {ident}", event)


def _sentence_edges(conn: Connection, ident: str) -> tuple[list[Key], list[Key]]:
    up = [
        _support_key(str(kind), str(ref))
        for kind, ref in conn.execute(
            text("SELECT kind, ref FROM sentence_supports WHERE sentence_id = :i"), {"i": ident}
        )
    ]
    down: list[Key] = [
        ("verdict", str(r[0]))
        for r in conn.execute(
            text("SELECT verdict_id FROM sentence_verdicts WHERE sentence_id = :i"), {"i": ident}
        )
    ]
    row = conn.execute(
        text(
            "SELECT draft_id, supersedes, superseded_by FROM draft_sentences WHERE sentence_id = :i"
        ),
        {"i": ident},
    ).first()
    if row is not None:
        down.append(("draft", str(row[0])))
        if row[1] is not None:
            up.append(("sentence", str(row[1])))
        if row[2] is not None:
            down.append(("sentence", str(row[2])))
    return up, down


def edges(project: Project, conn: Connection, kind: str, ident: str) -> tuple[list[Key], list[Key]]:
    """The upstream and downstream neighbours of a draft node."""
    if kind == "sentence":
        return _sentence_edges(conn, ident)
    if kind == "verdict":
        rows = conn.execute(
            text("SELECT sentence_id FROM sentence_verdicts WHERE verdict_id = :i"), {"i": ident}
        ).all()
        return [("sentence", str(r[0])) for r in rows], []
    if kind == "draft":
        rows = conn.execute(
            text("SELECT sentence_id FROM draft_sentences WHERE draft_id = :i"), {"i": ident}
        ).all()
        return [("sentence", str(r[0])) for r in rows], []
    down = citing(conn, kind, ident)
    if kind == "group":
        from factory.services.write_rows import visible_rows_by_group  # it reads the evidence

        found = visible_rows_by_group(project).groups.get(ident)
        rows_of = [] if found is None else found[1]
        return [("cell", f"{r.row_key}/value") for r in rows_of], down
    return [], down


def citing(conn: Connection, kind: str, ident: str) -> list[Key]:
    """The sentences that cite this node as a support."""
    support = {
        "claim": "claim",
        "cell": "cell",
        "extraction": "item",
        "relation": "edge",
        "cites": "edge",
        "interpretation": "interp",
        "concept": "interp",
        "group": "group",
        "stat": "stat",
    }[kind]
    ref = ident.removeprefix("stat:")
    if kind == "cell" and "/" not in ref:
        ref = f"{ref}/value"
    rows = conn.execute(
        text("SELECT DISTINCT sentence_id FROM sentence_supports WHERE kind = :k AND ref = :r"),
        {"k": support, "r": ref},
    ).all()
    return [("sentence", str(r[0])) for r in rows]
