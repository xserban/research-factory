"""The corpus a view counts: the corpus of PRISMA (slice 7b, plan V-A ruling 7, used by V-B).

Declares: `corpus_among`. Read-only.

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
