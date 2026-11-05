"""The layer's own conditions for `check` (slice 3c, plan G3-C, task 3).

Each function reads the layer's tables by SQL and returns `(total, refs)`: the number of items in
the condition and up to `REF_CAP` of their identifiers, sorted. Nothing here reads a quote, a text
or a note, so a finding built from it carries counts and identifiers only. `services.check` owns
severities and messages; this module is one of the layer modules (`tests/intuition_separation.py`).

Concept cycles (`concept_cycles`) are found by one recursive query over the `uses` links between
concepts that are not rejected, with merged concepts read as the concept they were merged into, so
a cycle that only a merge closes is reported.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.services.context import Project
from factory.services.intuition_sources import stale_sources

__all__ = [
    "REF_CAP",
    "concept_cycles",
    "concepts_without_approved_source",
    "dropped_reviews",
    "inferred_links",
    "layer_present",
    "self_reviewed_items",
    "stale_items",
    "unreviewed_concepts",
    "unreviewed_interpretations",
]

REF_CAP = 500
Found = tuple[int, list[str]]


def _ids(project: Project, where: str, table: str, column: str) -> Found:
    project.index.sync()
    with project.index.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}")).scalar_one()
        found = conn.execute(
            text(f"SELECT {column} FROM {table} WHERE {where} ORDER BY {column} LIMIT :n"),
            {"n": REF_CAP},
        ).all()
    return int(total), [str(r[0]) for r in found]


def layer_present(project: Project) -> bool:
    """Whether the project has any interpretation or concept."""
    project.index.sync()
    with project.index.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM interpretations) "
                    "OR EXISTS (SELECT 1 FROM concepts)"
                )
            ).scalar_one()
        )


def unreviewed_interpretations(project: Project) -> Found:
    return _ids(project, "review_state = 'unreviewed'", "interpretations", "interpretation_id")


def unreviewed_concepts(project: Project) -> Found:
    """Approved, unmerged concepts whose live definition no human has reviewed."""
    return _ids(
        project,
        "source_state = 'approved' AND merged_into IS NULL AND review_state = 'unreviewed'",
        "concepts",
        "concept_id",
    )


def concepts_without_approved_source(project: Project) -> Found:
    """Concepts whose source is missing, proposed or rejected."""
    return _ids(project, "source_state != 'approved'", "concepts", "concept_id")


def inferred_links(project: Project) -> Found:
    """`uses` links awaiting a human decision."""
    return _ids(project, "status = 'inferred'", "concept_uses", "link_id")


def self_reviewed_items(project: Project) -> Found:
    """Live interpretations and concepts whose counting review is the author's own."""
    a, ia = _ids(
        project,
        "self_reviewed = 1 AND review_state IN ('reviewed', 'wrong')",
        "interpretations",
        "interpretation_id",
    )
    b, ib = _ids(
        project,
        "self_reviewed = 1 AND review_state IN ('reviewed', 'wrong')",
        "concepts",
        "concept_id",
    )
    return a + b, sorted([*ia, *ib])[:REF_CAP]


def dropped_reviews(project: Project) -> Found:
    """Reviews the fold did not count (not a human, or the writing session): their event ids."""
    a, ia = _ids(project, "folded = 0", "interpretation_reviews", "event_id")
    b, ib = _ids(project, "folded = 0", "concept_reviews", "event_id")
    return a + b, sorted([*ia, *ib])[:REF_CAP]


def stale_items(project: Project) -> Found:
    """Interpretations and concepts with a quote of a superseded document."""
    stale = sorted(stale_sources(project))
    return len(stale), stale[:REF_CAP]


_CYCLES = (
    "WITH RECURSIVE e AS (SELECT COALESCE(f.merged_into, u.from_node) AS a, "
    "COALESCE(c.merged_into, u.concept_id) AS b FROM concept_uses u "
    "LEFT JOIN concepts f ON f.concept_id = u.from_node "
    "LEFT JOIN concepts c ON c.concept_id = u.concept_id "
    "WHERE u.from_kind = 'concept' AND u.status != 'rejected'), "
    "reach(s, n) AS (SELECT a, b FROM e UNION SELECT r.s, e.b FROM reach r JOIN e ON e.a = r.n) "
    "SELECT DISTINCT s FROM reach WHERE s = n ORDER BY s"
)


def concept_cycles(project: Project) -> Found:
    """The concepts on a cycle of `uses` links between concepts."""
    project.index.sync()
    with project.index.connect() as conn:
        found = [str(r[0]) for r in conn.execute(text(_CYCLES)).all()]
    return len(found), found[:REF_CAP]
