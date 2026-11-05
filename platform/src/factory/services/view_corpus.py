"""The corpus a view counts: the corpus of PRISMA (slice 7b, plan V-A ruling 7, used by V-B).

Declares: `corpus_among`, `years_of`, `CORPUS_SQL`, `CORPUS_PARAMS`, `search_horizon`,
`horizon_notice`. Read-only.

Invariant: a work is in the corpus of a view when it has a non-probe provenance row and no active
merge absorbs it (it is not a merge member other than the primary). The test is role-blind: a
seed's work is an ordinary corpus work (decision 37.9). Ids are read in batches of `BATCH`; no
work record is parsed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.model.search import QueryPurpose
from factory.model.views import ViewNotice
from factory.services.context import Project

BATCH = 900
_PROBE = QueryPurpose.PROBE.value


def corpus_among(conn: Connection, ids: Sequence[str]) -> set[str]:
    """The ids that are corpus works as `list_works` defines the corpus and that no active merge
    absorbs."""
    found: set[str] = set()
    for start in range(0, len(ids), BATCH):
        rows = conn.execute(
            text(
                "SELECT DISTINCT p.work_id FROM provenance p "
                "WHERE p.work_id IN (SELECT value FROM json_each(:ids)) "
                "AND p.query_id NOT IN (SELECT query_id FROM queries WHERE purpose = :probe) "
                "AND p.work_id NOT IN (SELECT mm.work_id FROM merge_members mm JOIN merges m "
                "ON m.merge_id = mm.merge_id WHERE m.status = 'active' "
                'AND mm.work_id != m."primary")'
            ),
            {"ids": json.dumps(list(ids[start : start + BATCH])), "probe": _PROBE},
        )
        found.update(str(r[0]) for r in rows)
    return found


def years_of(conn: Connection, ids: Sequence[str]) -> dict[str, int]:
    """The publication year of each work in `ids` that has a dated record (`dates.published`
    starting with four digits); undated works are omitted, never guessed."""
    out: dict[str, int] = {}
    for start in range(0, len(ids), BATCH):
        rows = conn.execute(
            text(
                "SELECT work_id, substr(json_extract(data, '$.dates.published'), 1, 4) "
                "FROM works WHERE work_id IN (SELECT value FROM json_each(:w))"
            ),
            {"w": json.dumps(list(ids[start : start + BATCH]))},
        )
        out.update({str(w): int(y) for w, y in rows if y is not None and str(y).isdigit()})
    return out


CORPUS_SQL = (
    "(SELECT DISTINCT p.work_id FROM provenance p WHERE p.query_id NOT IN "
    "(SELECT query_id FROM queries WHERE purpose = :view_probe) AND p.work_id NOT IN "
    "(SELECT mm.work_id FROM merge_members mm JOIN merges m ON m.merge_id = mm.merge_id "
    "WHERE m.status = 'active' AND mm.work_id != m.\"primary\"))"
)
"""The corpus as a SQL subquery of work ids, for a query that joins it (parameters `CORPUS_PARAMS`);
the same set as `corpus_among`."""

CORPUS_PARAMS = {"view_probe": _PROBE}


def search_horizon(project: Project) -> dict[str, str]:
    """The latest finished search or chase run (complete or partial) per source, as a date.
    Probe, seed, supplied, import and status runs are not the search of the corpus and are left
    out (role-blind: no seed or held-out information enters)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.source, MAX(substr(r.finished_at, 1, 10)) FROM runs r "
                "JOIN queries q ON q.query_id = r.query_id "
                "WHERE r.finished_at IS NOT NULL AND r.status IN ('complete', 'partial') "
                "AND q.purpose IN ('search', 'chase') GROUP BY r.source ORDER BY r.source"
            )
        ).all()
    return {str(s): str(d) for s, d in rows}


def horizon_notice(horizon: dict[str, str]) -> ViewNotice:
    if not horizon:
        return ViewNotice(
            code="corpus-horizon",
            text="No finished search run is recorded, so the corpus horizon is unknown; works "
            "published after the last search are not in the corpus.",
        )
    latest = "; ".join(f"{source}: {date}" for source, date in horizon.items())
    return ViewNotice(
        code="corpus-horizon",
        text=f"Latest search or watch run per source: {latest}. Works published after these "
        "dates are not in the corpus.",
    )
