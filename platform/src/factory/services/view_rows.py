"""The evidence rows a view counts (slice 7b, plan V-B; review I2, I3).

Declares: `canonical_ids`, `visible_groups`, `visible_rows`. Read-only.

Invariants:
- The evidence report keeps the rows of a work an active dedup merge absorbs (it ignores merges).
  The views keep those rows too, so their row counts equal the report's, but read the work as
  its primary: an absorbed record and its primary are one paper, so `works` counts papers (the
  report counts records), and dates, idea membership and lineage edges follow the primary.
- A row is shown when its canonical work is a corpus work (`view_corpus.corpus_among`: PRISMA's
  corpus, role-blind) and neither the record nor its primary is excluded by a retraction notice.
  Groups are filtered before they are ranked or cut, so totals equal what is listed.
- A work with a correction pending (the record or its primary) is returned in `pending`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.services.context import Project
from factory.services.extraction_agreement import FinalRow, GroupKey
from factory.services.notices import work_states
from factory.services.view_corpus import BATCH, corpus_among


def canonical_ids(conn: Connection, ids: Sequence[str]) -> dict[str, str]:
    """For each id absorbed by an active merge, its primary; other ids are omitted."""
    out: dict[str, str] = {}
    for start in range(0, len(ids), BATCH):
        rows = conn.execute(
            text(
                'SELECT mm.work_id, m."primary" FROM merge_members mm '
                "JOIN merges m ON m.merge_id = mm.merge_id "
                "WHERE m.status = 'active' AND mm.work_id != m.\"primary\" "
                "AND mm.work_id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": json.dumps(list(ids[start : start + BATCH]))},
        )
        out.update({str(a): str(p) for a, p in rows})
    return out


def visible_groups(
    project: Project, groups: Sequence[tuple[GroupKey, list[FinalRow]]]
) -> tuple[list[tuple[GroupKey, list[FinalRow]]], frozenset[str]]:
    """The groups restricted to visible rows (rows read under their canonical work), empty groups
    dropped, and the canonical works among them with a correction pending."""
    works = sorted({r.work_id for _, rows in groups for r in rows})
    if not works:
        return [], frozenset()
    with project.index.connect() as conn:
        canon = canonical_ids(conn, works)
        corpus = corpus_among(conn, sorted({canon.get(w, w) for w in works}))
    states = work_states(project)
    excluded = {w for w, s in states.items() if s.synthesis == "excluded"}
    pending = {w for w, s in states.items() if s.flag == "correction-pending"}
    out: list[tuple[GroupKey, list[FinalRow]]] = []
    pending_out: set[str] = set()
    for key, rows in groups:
        kept: list[FinalRow] = []
        for row in rows:
            own = row.work_id
            main = canon.get(own, own)
            if main not in corpus or own in excluded or main in excluded:
                continue
            if own in pending or main in pending:
                pending_out.add(main)
            kept.append(row if main == own else row.model_copy(update={"work_id": main}))
        if kept:
            out.append((key, kept))
    return out, frozenset(pending_out)


def visible_rows(
    project: Project, rows: Sequence[FinalRow]
) -> tuple[list[FinalRow], frozenset[str]]:
    """`visible_groups` for the rows of one group."""
    groups, pending = visible_groups(project, [((), list(rows))])
    return (groups[0][1] if groups else []), pending
