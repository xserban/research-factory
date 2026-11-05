"""The one read of G1 reference data the lineage code uses (slice 3b, plan G2-B).

Invariants:
- Reads the index only. Entry text is not in the index (G1 ruling 14), and no function here reads
  a conversion or an entry's text; an entry is described by its parsed fields and ordinal.
- `state`, `work_id` and `confidence` of a link already fold the latest binding decision, so
  `EntryView.link_*` are the decided values.
- `reference_view` is the work's live extraction; whether it is also the work's current one (pinned
  to its default conversion, this parser version) is `references.current_extraction`'s question.
- Briefs served to an agent are metadata only; an entry linked to, or identified as, a held-out
  seed's work is masked like an unresolved entry (R-20).
"""

from __future__ import annotations

import json

from sqlalchemy import text

from factory.lineage.refs import ContextView, EntryView, ReferenceView
from factory.model.extraction import EntryBrief
from factory.model.references import Confidence, LinkState
from factory.model.seed import HeldOut
from factory.services.context import Project
from factory.services.references import link_touches_held_out

__all__ = [
    "briefs",
    "is_live_reference_extraction",
    "reference_view",
    "reference_view_of",
]


def reference_view(project: Project, work_id: str) -> ReferenceView | None:
    """The live reference extraction of `work_id` with its entries and contexts; None when the
    work has none."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT extraction_id FROM reference_extractions WHERE work_id = :w AND live = 1"),
            {"w": work_id},
        ).first()
    return None if row is None else reference_view_of(project, str(row[0]))


def reference_view_of(project: Project, extraction_id: str) -> ReferenceView | None:
    """Any reference extraction, live or superseded; None when it is unknown."""
    project.index.sync()
    with project.index.connect() as conn:
        head = conn.execute(
            text(
                "SELECT work_id, conversion_id FROM reference_extractions WHERE extraction_id = :x"
            ),
            {"x": extraction_id},
        ).first()
        if head is None:
            return None
        entries = (
            conn.execute(
                text(
                    "SELECT n.ordinal, n.anchor, n.label, n.title, n.first_author, n.year, "
                    "n.doi, n.arxiv, l.state, l.work_id, l.confidence, l.base_work_id, l.candidates "
                    "FROM reference_entries n LEFT JOIN reference_links l "
                    "ON l.extraction_id = n.extraction_id AND l.ordinal = n.ordinal "
                    "WHERE n.extraction_id = :x ORDER BY n.ordinal"
                ),
                {"x": extraction_id},
            )
            .mappings()
            .all()
        )
        contexts = (
            conn.execute(
                text(
                    "SELECT citing_anchor, entry, marker, state FROM citation_contexts "
                    "WHERE extraction_id = :x ORDER BY position"
                ),
                {"x": extraction_id},
            )
            .mappings()
            .all()
        )
    return ReferenceView(
        extraction_id=extraction_id,
        work_id=str(head[0]),
        conversion_id=str(head[1]),
        entries=tuple(
            EntryView(
                ordinal=int(r["ordinal"]),
                anchor=str(r["anchor"]),
                label=r["label"],
                title=r["title"],
                first_author=r["first_author"],
                year=r["year"],
                doi=r["doi"],
                arxiv=r["arxiv"],
                link_state=LinkState(str(r["state"])) if r["state"] else LinkState.UNRESOLVED,
                link_work=r["work_id"],
                confidence=Confidence(str(r["confidence"])) if r["confidence"] else None,
                base_work=r["base_work_id"],
                candidate_works=tuple(
                    str(c["work_id"]) for c in json.loads(r["candidates"] or "[]")
                ),
            )
            for r in entries
        ),
        contexts=tuple(
            ContextView(
                citing_anchor=str(r["citing_anchor"]),
                entry=None if r["entry"] is None else int(r["entry"]),
                marker=str(r["marker"]),
                state=r["state"],
            )
            for r in contexts
        ),
    )


def is_live_reference_extraction(project: Project, extraction_id: str) -> bool:
    """Whether `extraction_id` is the live extraction of its work."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT live FROM reference_extractions WHERE extraction_id = :x"),
            {"x": extraction_id},
        ).first()
    return row is not None and bool(row[0])


def briefs(view: ReferenceView, held_out: HeldOut | None = None) -> list[EntryBrief]:
    """The entries of `view` as an agent sees them: ordinal, anchor, label and parsed fields. With
    `held_out`, an entry whose link touches a held-out work (linked, base or candidate), or that
    states a held-out identifier, loses its title, DOI and arXiv id, as G1's `_masked` does; its
    author and year stay, so it looks like a genuine entry without identifier or title."""
    out: list[EntryBrief] = []
    for entry in view.entries:
        works = (entry.link_work, entry.base_work, *entry.candidate_works)
        hidden = held_out is not None and link_touches_held_out(
            held_out, works, entry.doi, entry.arxiv
        )
        out.append(
            EntryBrief(
                ordinal=entry.ordinal,
                anchor=entry.anchor,
                label=entry.label,
                title=None if hidden else entry.title,
                first_author=entry.first_author,
                year=entry.year,
                doi=None if hidden else entry.doi,
                arxiv=None if hidden else entry.arxiv,
            )
        )
    return out
