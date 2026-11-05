"""The one region reader of the intuition layer's tables: nodes that use a background concept.

A `concept` rule selects the ideas and papers with a stated or confirmed `uses` link to a visible
(source-approved) concept, merges applied at read time. This module is the only place in
`factory.regions` that names a layer table, so the layer-separation scan lists it alone as a table
reader (`tests/intuition_separation.py`); it imports no layer module and writes nothing.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

USE_STATUSES = ("stated", "confirmed")
_SURVIVOR = (
    "WITH RECURSIVE up(concept_id, depth) AS ("
    "SELECT :c, 0 UNION ALL "
    "SELECT m.into_concept, up.depth + 1 FROM concept_merges m "
    "JOIN up ON m.from_concept = up.concept_id WHERE m.active = 1 AND up.depth < 50) "
    "SELECT concept_id FROM up ORDER BY depth DESC LIMIT 1"
)
_TREE = (
    "WITH RECURSIVE tree(concept_id) AS ("
    "SELECT :c UNION SELECT m.from_concept FROM concept_merges m "
    "JOIN tree ON m.into_concept = tree.concept_id WHERE m.active = 1) "
    "SELECT concept_id FROM tree"
)


def concept_exists(conn: Connection, concept_id: str) -> bool:
    """Whether a concept with this id was ever defined."""
    found = conn.execute(
        text("SELECT 1 FROM concepts WHERE concept_id = :c"), {"c": concept_id}
    ).first()
    return found is not None


def concept_live(conn: Connection, concept_id: str) -> str:
    """The concept `concept_id` stands for after active merges (itself when unmerged)."""
    return str(conn.execute(text(_SURVIVOR), {"c": concept_id}).scalar_one())


def concept_survivor(conn: Connection, concept_id: str) -> str | None:
    """The concept `concept_id` stands for after merges when it is visible, else None. Visible is
    the concept views' rule: source approved, not merged away, review not `wrong`."""
    survivor = concept_live(conn, concept_id)
    visible = conn.execute(
        text(
            "SELECT 1 FROM concepts WHERE concept_id = :c AND source_state = 'approved' "
            "AND merged_into IS NULL AND review_state IN ('unreviewed', 'reviewed')"
        ),
        {"c": survivor},
    ).first()
    return survivor if visible is not None else None


def concept_users(conn: Connection, concept_id: str) -> list[str]:
    """The sorted `from_node` ids with a stated or confirmed use of the concept or of any concept
    merged into it; a concept user must itself be visible (the concept views' endpoint rule).
    `concept_id` must be a survivor."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT u.from_node FROM concept_uses u "
            f"WHERE u.status IN ('stated', 'confirmed') AND u.concept_id IN ({_TREE}) "
            "AND (u.from_kind != 'concept' OR EXISTS (SELECT 1 FROM concepts cf WHERE "
            "cf.concept_id = COALESCE((SELECT m.merged_into FROM concepts m WHERE "
            "m.concept_id = u.from_node), u.from_node) AND cf.source_state = 'approved' "
            "AND cf.merged_into IS NULL AND cf.review_state IN ('unreviewed', 'reviewed'))) "
            "ORDER BY u.from_node"
        ),
        {"c": concept_id},
    ).all()
    return [str(row[0]) for row in rows]


def use_link(conn: Connection, link_id: str) -> tuple[str, str, str, str] | None:
    """`(from_node, from_kind, live concept id, status)` of a stated or confirmed concept use, or
    None for an unknown link or one not (yet) stated or confirmed."""
    row = conn.execute(
        text(
            "SELECT from_node, from_kind, concept_id, status FROM concept_uses "
            "WHERE link_id = :l AND status IN ('stated', 'confirmed')"
        ),
        {"l": link_id},
    ).first()
    if row is None:
        return None
    return str(row[0]), str(row[1]), concept_live(conn, str(row[2])), str(row[3])
