"""Trace nodes and edges of regions (slice 3d, plan Regions-B, task 4).

Read-only SQL on the connection `services.trace` already holds. Three node kinds: `region`
(`reg_...`), `region_version` (`R@xxxxxxxx`) and `region_member` (`R@xxxxxxxx/<type>/<id>`, the
membership of one member in the latest version of a region, with its basis).

Invariants:
- Every label starts `"<kind> <id> · organisation · ..."`, so a region is never shown as evidence.
  Labels carry ids, rule text and member counts (agent-written, not literature), the writer of a
  definition (actor, model, skill, input blob) and the review history; a review note is never
  shown.
- A region leads down to its versions and a version up to its region; a member of a region leads
  up to its version. `attached` gives the memberships of a work, idea or concept, which
  `services.trace` adds only when asked for the layer (`layer = all`), so a trace of an evidence
  node is unchanged by default (spec ruling 7).
- Read in an agent trace, a region withheld from agents is removed whole by `services.trace`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.model.regions import REGION_ID_RE
from factory.regions.rules import REGION_VERSION_RE

__all__ = ["REGION_KINDS", "REGION_PATTERNS", "attached", "describe", "edges", "split_member"]

Key = tuple[str, str]
Described = tuple[str, str]
REGION_KINDS = ("region", "region_version", "region_member")
_MEMBER_RE = rf"^({REGION_VERSION_RE[1:-1]})/(work|idea|concept)/(\S+)$"
REGION_PATTERNS: tuple[tuple[str, str], ...] = (
    (REGION_ID_RE, "region"),
    (REGION_VERSION_RE, "region_version"),
    (_MEMBER_RE, "region_member"),
)


def _rows(conn: Connection, sql: str, **params: object) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(text(sql), params).all()]


def split_member(ident: str) -> tuple[str, str, str]:
    """`(version, member type, member)` of a `region_member` identifier."""
    match = re.fullmatch(_MEMBER_RE, ident)
    assert match is not None
    return match.group(1), match.group(2), match.group(3)


def _writer(actor_id: object, model: object, skill: object, blob: object) -> str:
    return (
        f"writer {actor_id}; model {model or '-'}; skill {skill or '-'}; input_blob {blob or '-'}"
    )


def describe(conn: Connection, kind: str, ident: str) -> Described | None:
    """The label and creating event of a region node, or None when no row names it."""
    if kind == "region":
        return _region(conn, ident)
    if kind == "region_version":
        return _version(conn, ident)
    return _member(conn, ident)


def _region(conn: Connection, region_id: str) -> Described | None:
    head = _rows(
        conn,
        "SELECT kind, facet_question, facet_slot, event_id FROM regions WHERE region_id = :r",
        r=region_id,
    )
    if not head:
        return None
    kind, question, slot, first = head[0]
    latest = _rows(
        conn,
        "SELECT d.name, d.author, d.rules, e.actor_id, e.model, e.skill, e.input_blob "
        "FROM region_definitions d JOIN events e ON e.id = d.event_id "
        "WHERE d.region_id = :r ORDER BY d.event_id DESC LIMIT 1",
        r=region_id,
    )
    name, author, rules, actor_id, model, skill, blob = latest[0]
    definitions = _rows(
        conn, "SELECT COUNT(*) FROM region_definitions WHERE region_id = :r", r=region_id
    )[0][0]
    decisions = _rows(
        conn,
        "SELECT decision, COUNT(*) FROM region_member_decisions WHERE region_id = :r "
        "GROUP BY decision ORDER BY decision",
        r=region_id,
    )
    proposals = _rows(
        conn, "SELECT COUNT(*) FROM region_member_proposals WHERE region_id = :r", r=region_id
    )[0][0]
    versions = [
        str(v[0])
        for v in _rows(
            conn,
            "SELECT version FROM region_snapshots WHERE region_id = :r ORDER BY event_id",
            r=region_id,
        )
    ]
    facet = f" {question}:{slot}" if question is not None else ""
    shown = ", ".join(f"{d} {n}" for d, n in decisions) or "none"
    label = (
        f"region {region_id} · organisation · {kind}{facet} · {name} · author {author} "
        f"({_writer(actor_id, model, skill, blob)}) · {definitions} definition(s) · "
        f"rules {rules} · member decisions: {shown} · {proposals} proposal(s) · "
        f"versions: {', '.join(versions) or 'none'}"
    )
    return label, str(first)


def _review_state(conn: Connection, version: str, region_id: str) -> str:
    latest = _rows(
        conn,
        "SELECT version FROM region_snapshots WHERE region_id = :r ORDER BY event_id DESC LIMIT 1",
        r=region_id,
    )
    if latest and latest[0][0] != version:
        return "superseded"
    state = _rows(
        conn,
        "SELECT state FROM region_reviews WHERE version = :v ORDER BY event_id DESC LIMIT 1",
        v=version,
    )
    return "unreviewed" if not state else str(state[0][0])


def _version(conn: Connection, version: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT event_id, region_id, definition_event, decisions, counts FROM region_snapshots "
        "WHERE version = :v ORDER BY event_id LIMIT 1",
        v=version,
    )
    if not found:
        return None
    event_id, region_id, definition, decisions, counts = found[0]
    reviews = _rows(
        conn,
        "SELECT state, reviewer_user, self_reviewed, event_id FROM region_reviews "
        "WHERE version = :v ORDER BY event_id",
        v=version,
    )
    history = (
        "; ".join(
            f"{state} by {user}{' (self)' if own else ''} ({ev})"
            for state, user, own, ev in reviews
        )
        or "none"
    )
    decided = len(json.loads(str(decisions)))
    label = (
        f"region_version {version} · organisation · {_review_state(conn, version, region_id)} · "
        f"region {region_id} · members {counts} · definition event {definition} · "
        f"{decided} member decision(s) in effect · reviews: {history}"
    )
    return label, str(event_id)


def _member(conn: Connection, ident: str) -> Described | None:
    version, member_type, member = split_member(ident)
    found = _rows(
        conn,
        "SELECT region_id, basis FROM region_members WHERE version = :v AND member_type = :t "
        "AND member = :m",
        v=version,
        t=member_type,
        m=member,
    )
    if not found:
        return None
    region_id, basis = found[0]
    parsed = json.loads(str(basis)) or {}
    rules = parsed.get("rules") or []
    decision = parsed.get("decision")
    via = []
    if rules:
        via.append("rules " + ", ".join(str(i) for i in rules))
    if decision:
        via.append(f"decision {decision}")
    snapshot = _rows(
        conn,
        "SELECT event_id FROM region_snapshots WHERE version = :v ORDER BY event_id LIMIT 1",
        v=version,
    )
    label = (
        f"region_member {ident} · organisation · {member_type} {member} is in {region_id} "
        f"{version} by {' and '.join(via) or 'no recorded basis'}"
    )
    return label, str(snapshot[0][0])


def edges(conn: Connection, kind: str, ident: str) -> tuple[list[Key], list[Key]]:
    """Upstream and downstream neighbours of a region node."""
    if kind == "region":
        versions = _rows(
            conn,
            "SELECT DISTINCT version FROM region_snapshots WHERE region_id = :r",
            r=ident,
        )
        return [], [("region_version", str(v[0])) for v in versions]
    if kind == "region_version":
        owner = _rows(
            conn,
            "SELECT region_id FROM region_snapshots WHERE version = :v LIMIT 1",
            v=ident,
        )
        return [("region", str(r[0])) for r in owner], []
    version = split_member(ident)[0]
    return [("region_version", version)], []


def attached(conn: Connection, kind: str, ident: str) -> list[Key]:
    """The `region_member` nodes of a work, idea or concept: one per region whose latest version
    holds it."""
    member_type = {"work": "work", "idea": "idea", "concept": "concept"}.get(kind)
    if member_type is None:
        return []
    return [
        ("region_member", f"{version}/{member_type}/{ident}")
        for (version,) in _rows(
            conn,
            "SELECT version FROM region_members WHERE member_type = :t AND member = :m "
            "ORDER BY region_id",
            t=member_type,
            m=ident,
        )
    ]
