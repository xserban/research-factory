"""How far each work has been processed (slice 7b, plan V-A, ruling 5).

Depth, highest reached: `indexed` (a recorded or cited work) < `screened` (a decided outcome at
either screening stage) < `extracted` (a current extraction unit, evidence or contribution scope)
< `verified` (a final row `agreed` or `resolved`, or, for the researcher, a labelled audit item).

Invariants:
- Read-only; every depth is derived from the log, never typed (R-05).
- A stale unit is not a current unit: an amendment that stales extraction lowers the work to
  `screened`.
- The agent variant (`agent=True`) leaves out the labelled-audit path: whether an item was
  audited and labelled is a label-derived fact that agents do not read (decision 37.14), so a
  count of `verified` works must not depend on it. The agreed or resolved path is unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.extraction import Scope
from factory.model.protocol import ScreeningStage
from factory.model.views import ProcessingDepth
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.extraction import unit_states
from factory.services.extraction_agreement import final_rows

DEPTH_RANK: Mapping[ProcessingDepth, int] = {
    "indexed": 0,
    "screened": 1,
    "extracted": 2,
    "verified": 3,
}

BATCH = 900
"""The most ids one `IN` read names."""

_SCOPES = (Scope.EVIDENCE, Scope.CONTRIBUTION)


@dataclass(frozen=True)
class DepthIndex:
    """The works at each depth above `indexed`, read once; `of` is a set lookup."""

    screened: frozenset[str]
    extracted: frozenset[str]
    verified: frozenset[str]

    def of(self, work_id: str) -> ProcessingDepth:
        if work_id in self.verified:
            return "verified"
        if work_id in self.extracted:
            return "extracted"
        if work_id in self.screened:
            return "screened"
        return "indexed"


def depth_index(project: Project, *, agent: bool = False) -> DepthIndex:
    """The sets behind every depth of the project, from the screening outcomes, the extraction
    units and the final rows of both scopes (and, unless `agent`, the labelled audit items)."""
    project.index.sync()
    screened = {
        work
        for stage in (ScreeningStage.TITLE_ABSTRACT, ScreeningStage.FULL_TEXT)
        for work, outcome in final_outcomes(project, stage=stage).items()
        if outcome is not Outcome.PENDING
    }
    extracted: set[str] = set()
    verified: set[str] = set()
    for scope in _SCOPES:
        extracted.update(
            s.work_id for s in unit_states(project, scope=scope) if s.state == "current"
        )
        verified.update(
            r.work_id
            for r in final_rows(project, scope=scope)
            if r.status in ("agreed", "resolved")
        )
    if not agent:
        with project.index.connect() as conn:
            verified.update(
                str(r[0])
                for r in conn.execute(
                    text(
                        "SELECT DISTINCT work_id FROM extraction_audit_items "
                        "WHERE correct IS NOT NULL"
                    )
                )
            )
    return DepthIndex(
        screened=frozenset(screened),
        extracted=frozenset(extracted),
        verified=frozenset(verified),
    )


def _known(conn: Connection, ids: Sequence[str]) -> set[str]:
    """The ids that are recorded works or papers of the graph, read in batches."""
    found: set[str] = set()
    for start in range(0, len(ids), BATCH):
        chunk = json.dumps(list(ids[start : start + BATCH]))
        rows = conn.execute(
            text(
                "SELECT work_id FROM works WHERE work_id IN (SELECT value FROM json_each(:ids)) "
                "UNION SELECT node_id FROM graph_nodes WHERE node_type = 'paper' "
                "AND node_id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": chunk},
        )
        found.update(str(r[0]) for r in rows)
    return found


def processing_depths(
    project: Project, work_ids: Sequence[str], *, agent: bool = False
) -> dict[str, ProcessingDepth]:
    """The depth of each of `work_ids`. An id that is neither a recorded work nor a paper of the
    graph is refused (field `work_ids`); an external work of the graph reads as `indexed`."""
    project.index.sync()
    ids = sorted(set(work_ids))
    with project.index.connect() as conn:
        unknown = [w for w in ids if w not in _known(conn, ids)] if ids else []
    if unknown:
        raise FactoryValidationError(
            [ValidationIssue("work_ids", f"unknown work: {w}") for w in unknown]
        )
    index = depth_index(project, agent=agent)
    return {w: index.of(w) for w in ids}


def depth_counts(
    project: Project,
    work_ids_sql: str,
    params: Mapping[str, object],
    *,
    conn: Connection | None = None,
    agent: bool = False,
    index: DepthIndex | None = None,
) -> dict[ProcessingDepth, int]:
    """Works per depth over the ids `work_ids_sql` selects (one `work_id` column). Every depth
    is present. `conn` is the connection holding a connection-local table the SQL may name;
    without it a fresh read connection is used."""
    depths = index if index is not None else depth_index(project, agent=agent)
    counts: dict[ProcessingDepth, int] = {
        "indexed": 0,
        "screened": 0,
        "extracted": 0,
        "verified": 0,
    }
    if conn is not None:
        for (work,) in conn.execute(text(work_ids_sql), dict(params)):
            counts[depths.of(str(work))] += 1
        return counts
    project.index.sync()
    with project.index.connect() as own:
        for (work,) in own.execute(text(work_ids_sql), dict(params)):
            counts[depths.of(str(work))] += 1
    return counts
