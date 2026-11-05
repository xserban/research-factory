"""Trace nodes and edges of the organisation class (slice 3d, plan Regions-C, task 5).

Read-only SQL on the connection `services.trace` already holds. Four node kinds: `label`
(`lbl_...`, an application), `term` (`trm_...`), `consolidation` (`cns_...`, a pass) and
`proposal` (`cnp_...`).

Invariants:
- Every label starts `"<kind> <id> · organisation · <state>"`, so a trace never shows an
  organisation item unlabelled.
- A node shows its actor, model, skill and input blob, the stored quote of a label, the merges and
  decisions that touch it, and counts; never a review note or document text beyond the stored
  quote.
- Upstream edges lead to what the item rests on (the target, the quote's anchor, the pass);
  downstream edges to what rests on it (proposals of a pass).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.model.labels import LABEL_ID_RE, PASS_ID_RE, PROPOSAL_ID_RE, TERM_ID_RE

__all__ = ["ORGANISATION_KINDS", "ORGANISATION_PATTERNS", "describe", "edges"]

Key = tuple[str, str]
Described = tuple[str, str]
ORGANISATION_KINDS = ("label", "term", "consolidation", "proposal")
ORGANISATION_PATTERNS: tuple[tuple[str, str], ...] = (
    (LABEL_ID_RE, "label"),
    (TERM_ID_RE, "term"),
    (PASS_ID_RE, "consolidation"),
    (PROPOSAL_ID_RE, "proposal"),
)
_CAP = 25


def _rows(conn: Connection, sql: str, **params: object) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(text(sql), params).all()]


def _writer(conn: Connection, event_id: object) -> str:
    found = _rows(
        conn, "SELECT actor_id, model, skill, input_blob FROM events WHERE id = :e", e=event_id
    )
    if not found:
        return "writer -"
    actor, model, skill, blob = found[0]
    return f"writer {actor}; model {model or '-'}; skill {skill or '-'}; input_blob {blob or '-'}"


def describe(conn: Connection, kind: str, ident: str) -> Described | None:
    """`(label, event_id)` of an organisation node, or None when no row defines it."""
    if kind == "label":
        return _label(conn, ident)
    if kind == "term":
        return _term(conn, ident)
    if kind == "consolidation":
        return _pass(conn, ident)
    return _proposal(conn, ident)


def _label(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT target_type, target, text, key, live_key, status, origin, quote, quote_text, "
        "decision, withdrawn, import_ref, event_id FROM labels WHERE application_id = :a",
        a=ident,
    )
    if not found:
        return None
    ttype, target, label, key, live, status, origin, quote, qtext, decision, gone, ref, event = (
        found[0]
    )
    state = (
        "withdrawn"
        if gone
        else "rejected"
        if decision == "reject"
        else ("confirmed" if decision == "confirm" else status)
    )
    merged = "" if live == key else f", read as {live}"
    anchor = ""
    if quote is not None:
        basis = json.loads(str(quote))
        anchor = f' quote "{qtext}" at {basis["conversion_id"]}/{basis["anchor"]};'
    source = "" if ref is None else f"; from record {ref}"
    return (
        f'label {ident} · organisation · {state}: "{label}" on {ttype} {target} '
        f"({origin}{source}{merged};{anchor} {_writer(conn, event)})",
        str(event),
    )


def _term(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT name, aliases, definition, applies_to, refers_to, retired, version, event_id "
        "FROM terms WHERE term_id = :t",
        t=ident,
    )
    if not found:
        return None
    name, aliases, definition, applies, refers, retired, version, event = found[0]
    state = "retired" if retired else "live"
    return (
        f"term {ident} · organisation · {state}: {name} (aliases {json.loads(str(aliases))}; "
        f"applies to {json.loads(str(applies))}; version {version}"
        f"{'' if refers is None else '; refers to ' + str(refers)}): {definition} "
        f"({_writer(conn, event)})",
        str(event),
    )


def _pass(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT event_id, counts, completed_event FROM consolidation_passes WHERE pass_id = :p",
        p=ident,
    )
    if not found:
        return None
    event, counts, completed = found[0]
    decided = _rows(
        conn,
        "SELECT decision, merge_events FROM consolidation_decisions WHERE pass_id = :p",
        p=ident,
    )
    merges = sum(len(json.loads(str(m))) for _, m in decided)
    state = "completed" if completed else "open"
    return (
        f"consolidation {ident} · organisation · {state}: clusters {json.loads(str(counts))}, "
        f"{len(decided)} decided, {merges} merge(s) ({_writer(conn, event)})",
        str(event),
    )


def _proposal(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT pass_id, cluster_index, action, into, members, reason, event_id "
        "FROM consolidation_proposals WHERE proposal_id = :p",
        p=ident,
    )
    if not found:
        return None
    pass_id, index, action, into, members, reason, event = found[0]
    decided = _rows(
        conn,
        "SELECT decision, merge_events FROM consolidation_decisions "
        "WHERE proposal_id = :p ORDER BY event_id",
        p=ident,
    )
    outcome = (
        "undecided"
        if not decided
        else f"decided {decided[-1][0]} ({len(json.loads(str(decided[-1][1])))} merge(s))"
    )
    target = "" if into is None else f" into {into}"
    return (
        f"proposal {ident} · organisation · {outcome}: {action}{target} of "
        f"{json.loads(str(members))} for cluster {index} of {pass_id}: {reason} "
        f"({_writer(conn, event)})",
        str(event),
    )


def edges(conn: Connection, kind: str, ident: str) -> tuple[list[Key], list[Key]]:
    """Upstream and downstream neighbours of an organisation node."""
    up: list[Key] = []
    down: list[Key] = []
    if kind == "label":
        found = _rows(
            conn,
            "SELECT target_type, target, quote FROM labels WHERE application_id = :a",
            a=ident,
        )
        if found:
            ttype, target, quote = found[0]
            up.append(({"work": "work", "idea": "idea", "concept": "concept"}[ttype], str(target)))
            if quote is not None:
                basis = json.loads(str(quote))
                up.append(("anchor", f"{basis['conversion_id']}/{basis['anchor']}"))
    elif kind == "term":
        up += [
            ("label", str(r[0]))
            for r in _rows(
                conn,
                "SELECT application_id FROM labels WHERE withdrawn = 0 AND (key IN "
                "(SELECT key FROM term_aliases WHERE term_id = :t) OR live_key IN "
                "(SELECT key FROM term_aliases WHERE term_id = :t)) "
                "ORDER BY application_id LIMIT :n",
                t=ident,
                n=_CAP,
            )
        ]
    elif kind == "consolidation":
        down += [
            ("proposal", str(r[0]))
            for r in _rows(
                conn,
                "SELECT proposal_id FROM consolidation_proposals WHERE pass_id = :p "
                "ORDER BY proposal_id",
                p=ident,
            )
        ]
    else:
        found = _rows(
            conn, "SELECT pass_id FROM consolidation_proposals WHERE proposal_id = :p", p=ident
        )
        up += [("consolidation", str(r[0])) for r in found]
    return up, down
