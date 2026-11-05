"""When consolidation is due (slice 3d ruling 14, plan Regions-C).

Kept apart from `services/consolidation.py` so that the region service can ask without importing
the consolidation service (which imports it).

Invariants:
- Counts are derived from the index; nothing is typed. New label keys are keys whose first
  application is after the last completed pass; new nodes are ideas and concepts first recorded
  after it. Completing a pass restarts both counts.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.regions.concept_use import concepts_defined_after
from factory.services.context import Project

CONSOLIDATION_DUE_LABELS = 50
CONSOLIDATION_DUE_NODES = 10


class DueState(StrictModel):
    new_label_keys: int
    new_nodes: int
    due: bool


def _baseline(project: Project) -> str:
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT MAX(completed_event) FROM consolidation_passes")
        ).scalar_one()
    return "" if found is None else str(found)


def consolidation_due(project: Project) -> DueState:
    """New label keys, ideas and concepts since the last completed pass, and whether either
    exceeds its constant (`CONSOLIDATION_DUE_LABELS`, `CONSOLIDATION_DUE_NODES`)."""
    project.index.sync()
    since = _baseline(project)
    with project.index.connect() as conn:
        keys = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM (SELECT key FROM labels GROUP BY key "
                    "HAVING MIN(event_id) > :b)"
                ),
                {"b": since},
            ).scalar_one()
        )
        ideas = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM ideas WHERE event_id > :b AND merged_into IS NULL "
                    "AND superseded_by IS NULL AND COALESCE(decision, '') != 'reject'"
                ),
                {"b": since},
            ).scalar_one()
        )
        concepts = concepts_defined_after(conn, since)
    nodes = ideas + concepts
    return DueState(
        new_label_keys=keys,
        new_nodes=nodes,
        due=keys > CONSOLIDATION_DUE_LABELS or nodes > CONSOLIDATION_DUE_NODES,
    )
