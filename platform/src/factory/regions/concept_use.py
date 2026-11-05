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


def concept_survivor(conn: Connection, concept_id: str) -> str | None:
    """The concept `concept_id` stands for after merges when it is source-approved, else None."""
    survivor = conn.execute(text(_SURVIVOR), {"c": concept_id}).scalar_one()
    approved = conn.execute(
        text("SELECT 1 FROM concepts WHERE concept_id = :c AND source_state = 'approved'"),
        {"c": survivor},
    ).first()
    return str(survivor) if approved is not None else None


def concept_users(conn: Connection, concept_id: str) -> list[str]:
    """The sorted `from_node` ids with a stated or confirmed use of the concept or of any concept
    merged into it. `concept_id` must be a survivor."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT from_node FROM concept_uses "
            f"WHERE status IN ('stated', 'confirmed') AND concept_id IN ({_TREE}) "
            "ORDER BY from_node"
        ),
        {"c": concept_id},
    ).all()
    return [str(row[0]) for row in rows]
