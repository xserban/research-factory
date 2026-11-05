"""Trace nodes and edges of the interpretation layer (slice 3c, plan G3-C, task 4).

Read-only SQL on the connection `services.trace` already holds; nothing here syncs the index or
opens another connection. Three node kinds: `interpretation` (`int_…`), `concept` (`cpt_…`) and
`concept_link` (`cul_…`). Review history is shown as child nodes whose id is the item's id, `#`
and the event id of the step (kind of the item; they have no edges of their own).

Invariants:
- Every layer node's label starts `"<kind> <id> · interpretation · <state>"`, so a trace never
  shows layer content unlabelled. Labels carry ids, flags, the stored text (agent-written, not
  literature), the writer (actor, model, skill, input blob) and, for history nodes, the review
  state and reviewer. A review note is never shown.
- Upstream edges lead to what the item rests on (target, quote anchors, cited extraction or work,
  approved source, prior item, the concept merged into); downstream edges to what rests on it.
  `attached` gives the layer items an evidence node (anchor, work, idea) carries; `services.trace`
  adds them only when asked for the layer, so a trace of an evidence node is unchanged by default.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.intuition.labels import layer_label
from factory.model.identity import ULID_RE
from factory.model.intuition import CONCEPT_ID_RE, CONCEPT_LINK_ID_RE, INTERPRETATION_ID_RE

__all__ = [
    "LAYER_KINDS",
    "LAYER_PATTERNS",
    "attached",
    "describe",
    "edges",
]

Key = tuple[str, str]
Described = tuple[str, str]
LAYER_KINDS = ("interpretation", "concept", "concept_link")
LAYER_PATTERNS: tuple[tuple[str, str], ...] = (
    (INTERPRETATION_ID_RE, "interpretation"),
    (rf"^int_{ULID_RE}#ev_{ULID_RE}$", "interpretation"),
    (CONCEPT_ID_RE, "concept"),
    (rf"^cpt_{ULID_RE}#ev_{ULID_RE}$", "concept"),
    (CONCEPT_LINK_ID_RE, "concept_link"),
    (rf"^cul_{ULID_RE}#ev_{ULID_RE}$", "concept_link"),
)

_HISTORY = re.compile(r"^(?P<item>[a-z]{3}_[0-9A-Z]+)#(?P<event>ev_[0-9A-Z]+)$")


def _rows(conn: Connection, sql: str, **params: object) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(text(sql), params).all()]


def _writer(actor_id: object, model: object, skill: object, blob: object) -> str:
    return (
        f"writer {actor_id}; model {model or '-'}; skill {skill or '-'}; input_blob {blob or '-'}"
    )


def _flags(*flags: tuple[bool, str]) -> str:
    named = [name for on, name in flags if on]
    return f" [{', '.join(named)}]" if named else ""


def describe(conn: Connection, kind: str, ident: str) -> Described | None:
    """`(label, event_id)` of a layer node, or None when no row defines it."""
    history = _HISTORY.match(ident)
    if history is not None:
        return _describe_history(conn, kind, history["item"], history["event"])
    if kind == "interpretation":
        return _describe_interpretation(conn, ident)
    if kind == "concept":
        return _describe_concept(conn, ident)
    return _describe_link(conn, ident)


def _describe_interpretation(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT i.review_state, i.self_reviewed, i.text, i.event_id, i.superseded_by, "
        "e.actor_id, e.model, e.skill, e.input_blob, "
        "EXISTS (SELECT 1 FROM interpretation_sources s JOIN fulltext_documents d "
        "ON d.document_id = s.document_id WHERE s.interpretation_id = i.interpretation_id "
        "AND d.superseded_by IS NOT NULL AND i.superseded_by IS NULL) "
        "FROM interpretations i JOIN events e ON e.id = i.event_id "
        "WHERE i.interpretation_id = :i",
        i=ident,
    )
    if not found:
        return None
    state, self_reviewed, body, event_id, _sup, actor, model, skill, blob, stale = found[0]
    quotes = "".join(
        f' source "{r[0]}" at {r[1]}/{r[2]};'
        for r in _rows(
            conn,
            "SELECT quote, conversion_id, anchor FROM interpretation_sources "
            "WHERE interpretation_id = :i AND kind = 'quote' ORDER BY position",
            i=ident,
        )
    )
    label = (
        f"interpretation {ident} · {layer_label(str(state))}"
        f"{_flags((bool(stale), 'source-stale'), (bool(self_reviewed), 'self-reviewed'))}: "
        f"{body} ({quotes.strip() + ' ' if quotes else ''}{_writer(actor, model, skill, blob)})"
    )
    return label, str(event_id)


def _describe_concept(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT c.review_state, c.self_reviewed, c.name, c.text, c.source_state, c.merged_into, "
        "c.source_verifiable, c.definition_event, e.actor_id, e.model, e.skill, e.input_blob, "
        "EXISTS (SELECT 1 FROM concept_quotes q JOIN fulltext_documents d "
        "ON d.document_id = q.document_id WHERE q.concept_id = c.concept_id "
        "AND d.superseded_by IS NOT NULL) "
        "FROM concepts c JOIN events e ON e.id = c.definition_event WHERE c.concept_id = :c",
        c=ident,
    )
    if not found:
        return None
    state, self_reviewed, name, body, source, merged, verifiable, event_id = found[0][:8]
    actor, model, skill, blob, stale = found[0][8:]
    flags = _flags(
        (bool(stale), "source-stale"),
        (bool(self_reviewed), "self-reviewed"),
        (verifiable is not None and not verifiable, "unverifiable-source"),
    )
    label = (
        f"concept {ident} · {layer_label(str(state))}{flags}"
        f" (source {source}{'' if merged is None else f', merged into {merged}'}): {name}"
        f"{'' if body is None else ': ' + str(body)} ({_writer(actor, model, skill, blob)})"
    )
    return label, str(event_id)


def _describe_link(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT status, status_reason, from_kind, from_node, concept_id, decided_by, event_id, "
        "basis_quote FROM concept_uses WHERE link_id = :l",
        l=ident,
    )
    if not found:
        return None
    status, reason, from_kind, from_node, concept_id, decided_by, event_id, quote = found[0]
    decided = "" if decided_by is None else f"; decided by {decided_by}"
    basis = "" if quote is None else f'; basis "{quote}"'
    label = (
        f"concept_link {ident} · {layer_label(str(status))}: {from_kind} {from_node} uses "
        f"{concept_id} ({reason}{decided}{basis})"
    )
    return label, str(event_id)


def _describe_history(conn: Connection, kind: str, item: str, event: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT e.type, e.actor_id, e.model FROM events e WHERE e.id = :e",
        e=event,
    )
    if not found:
        return None
    type_, actor, _model = found[0]
    state = _history_state(conn, kind, event)
    shown = f" {state[0]}" if state else ""
    counted = "" if state is None or state[1] else " (did not count)"
    return (
        f"{kind} {item} · {type_}{shown} by {actor}{counted} · interpretation · history",
        event,
    )


def _history_state(conn: Connection, kind: str, event: str) -> tuple[str, bool] | None:
    table = {
        "interpretation": ("interpretation_reviews", "state", "folded"),
        "concept": ("concept_reviews", "state", "folded"),
    }.get(kind)
    if table is None:
        return None
    found = _rows(
        conn, f"SELECT {table[1]}, {table[2]} FROM {table[0]} WHERE event_id = :e", e=event
    )
    if found:
        return str(found[0][0]), bool(found[0][1])
    if kind == "concept":
        decision = _rows(
            conn, "SELECT decision FROM concept_source_decisions WHERE event_id = :e", e=event
        )
        if decision:
            return f"source {decision[0][0]}", True
    return None


def _anchor_key(conversion: object, anchor: object) -> Key | None:
    if conversion is None or anchor is None:
        return None
    return ("anchor", f"{conversion}/{anchor}")


def _citation_keys(reference: object, work: object) -> list[Key]:
    keys: list[Key] = []
    if reference is not None:
        keys.append(("reference_extraction", str(reference).rsplit(":", 1)[0]))
    if work is not None:
        keys.append(("work", str(work)))
    return keys


def _history_keys(conn: Connection, kind: str, item: str) -> list[Key]:
    if kind == "interpretation":
        events = _rows(
            conn,
            "SELECT event_id FROM interpretation_reviews WHERE interpretation_id = :i "
            "ORDER BY event_id",
            i=item,
        )
    elif kind == "concept":
        events = _rows(
            conn,
            "SELECT event_id FROM concept_reviews WHERE concept_id = :c "
            "UNION SELECT event_id FROM concept_source_decisions WHERE concept_id = :c "
            "ORDER BY event_id",
            c=item,
        )
    else:
        events = _rows(
            conn,
            "SELECT decision_event FROM concept_uses WHERE link_id = :l "
            "AND decision_event IS NOT NULL",
            l=item,
        )
    return [(kind, f"{item}#{r[0]}") for r in events]


def edges(conn: Connection, kind: str, ident: str) -> tuple[list[Key], list[Key]]:
    """Upstream and downstream neighbours of a layer node."""
    if _HISTORY.match(ident):
        return [], []
    if kind == "interpretation":
        return _interpretation_edges(conn, ident)
    if kind == "concept":
        return _concept_edges(conn, ident)
    return _link_edges(conn, ident)


def _interpretation_edges(conn: Connection, ident: str) -> tuple[list[Key], list[Key]]:
    head = _rows(
        conn,
        "SELECT target, target_kind, supersedes, superseded_by FROM interpretations "
        "WHERE interpretation_id = :i",
        i=ident,
    )
    up: list[Key] = []
    down: list[Key] = []
    if head:
        target, target_kind, supersedes, superseded_by = head[0]
        up.append(("idea" if target_kind == "idea" else "work", str(target)))
        if supersedes is not None:
            up.append(("interpretation", str(supersedes)))
        if superseded_by is not None:
            down.append(("interpretation", str(superseded_by)))
    for kind_, conversion, anchor, reference, work in _rows(
        conn,
        "SELECT kind, conversion_id, anchor, reference, work_id FROM interpretation_sources "
        "WHERE interpretation_id = :i ORDER BY position",
        i=ident,
    ):
        if kind_ == "quote":
            key = _anchor_key(conversion, anchor)
            if key is not None:
                up.append(key)
        else:
            up += _citation_keys(reference, work)
    history = _history_keys(conn, "interpretation", ident)
    return up + history, down + history


def _concept_edges(conn: Connection, ident: str) -> tuple[list[Key], list[Key]]:
    head = _rows(
        conn, "SELECT source_work, merged_into FROM concepts WHERE concept_id = :c", c=ident
    )
    up: list[Key] = []
    down: list[Key] = []
    if head:
        source_work, merged_into = head[0]
        if source_work is not None:
            up.append(("work", str(source_work)))
        if merged_into is not None:
            up.append(("concept", str(merged_into)))
    for conversion, anchor in _rows(
        conn,
        "SELECT conversion_id, anchor FROM concept_quotes WHERE concept_id = :c ORDER BY position",
        c=ident,
    ):
        key = _anchor_key(conversion, anchor)
        if key is not None:
            up.append(key)
    down += [
        ("concept", str(r[0]))
        for r in _rows(conn, "SELECT concept_id FROM concepts WHERE merged_into = :c", c=ident)
    ]
    down += [
        ("concept_link", str(r[0]))
        for r in _rows(
            conn,
            "SELECT link_id FROM concept_uses WHERE concept_id = :c "
            "OR (from_kind = 'concept' AND from_node = :c)",
            c=ident,
        )
    ]
    history = _history_keys(conn, "concept", ident)
    return up + history, down + history


def _link_edges(conn: Connection, ident: str) -> tuple[list[Key], list[Key]]:
    head = _rows(
        conn,
        "SELECT from_node, from_kind, concept_id, basis_conversion, basis_anchor, reference "
        "FROM concept_uses WHERE link_id = :l",
        l=ident,
    )
    up: list[Key] = []
    if head:
        from_node, from_kind, concept_id, conversion, anchor, reference = head[0]
        kind = {"paper": "work", "idea": "idea", "concept": "concept"}[str(from_kind)]
        up += [(kind, str(from_node)), ("concept", str(concept_id))]
        key = _anchor_key(conversion, anchor)
        if key is not None:
            up.append(key)
        up += _citation_keys(reference, None)
    history = _history_keys(conn, "concept_link", ident)
    return up + history, history


def attached(conn: Connection, kind: str, ident: str) -> list[Key]:
    """The layer items an evidence node carries, all states (the labels say which): the
    interpretations that target it or cite it as a source, the concepts it is the approved source
    of or that quote it, and the `uses` links from it or based on it."""
    out: list[Key] = []
    if kind == "anchor":
        conversion, anchor = ident.split("/", 1)
        out += [
            ("interpretation", str(r[0]))
            for r in _rows(
                conn,
                "SELECT DISTINCT interpretation_id FROM interpretation_sources "
                "WHERE conversion_id = :c AND anchor = :a",
                c=conversion,
                a=anchor,
            )
        ]
        out += [
            ("concept", str(r[0]))
            for r in _rows(
                conn,
                "SELECT DISTINCT concept_id FROM concept_quotes "
                "WHERE conversion_id = :c AND anchor = :a",
                c=conversion,
                a=anchor,
            )
        ]
        out += [
            ("concept_link", str(r[0]))
            for r in _rows(
                conn,
                "SELECT link_id FROM concept_uses "
                "WHERE basis_conversion = :c AND basis_anchor = :a",
                c=conversion,
                a=anchor,
            )
        ]
    elif kind in ("work", "idea"):
        out += [
            ("interpretation", str(r[0]))
            for r in _rows(
                conn,
                "SELECT interpretation_id FROM interpretations WHERE target = :t "
                "UNION SELECT interpretation_id FROM interpretation_sources "
                "WHERE work_id = :t OR resolved_work = :t",
                t=ident,
            )
        ]
        out += [
            ("concept", str(r[0]))
            for r in _rows(conn, "SELECT concept_id FROM concepts WHERE source_work = :t", t=ident)
        ]
        out += [
            ("concept_link", str(r[0]))
            for r in _rows(conn, "SELECT link_id FROM concept_uses WHERE from_node = :t", t=ident)
        ]
    return out
