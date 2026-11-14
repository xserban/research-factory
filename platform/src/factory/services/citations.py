"""In-corpus citation counts per work, computed from resolved reference links (IDEA-57).

Invariants:
- Read-only: syncs the index, writes no event. Counts are computed from `reference_links` of live
  extractions, never typed.
- A citation is one citing work, counted once however many of its entries resolve to the cited
  work; a work citing itself is not counted.
- The count is a lower bound: it depends on how many reference lists were extracted and how many
  entries resolved. `CitationReport` carries both denominators. When no live extraction exists the
  count of every work is `None` (unknown), never 0.
- Self-citation is a separate figure: a citing work sharing a normalised author name with the
  cited work. `cited_by` includes those citations; `self_cited_by` says how many of them.
- `candidates` are cited items (rules of `reference_items`) none of whose entries resolved to a
  work and that carry a year or an identifier: cited by the corpus, not in it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import text

from factory.model.references import LinkState
from factory.services.context import Project
from factory.services.reference_items import cited_items


@dataclass(frozen=True)
class WorkCitations:
    work_id: str
    title: str
    year: int | None
    cited_by: int | None
    """Distinct live-extracted works citing this one; None when no reference list was extracted."""
    self_cited_by: int | None
    citers: tuple[str, ...]
    per_year: float | None
    """`cited_by` over the years since publication (the publication year counts as one)."""
    external: int | None = None
    """The count stored in the work record (`cited_by_count`, read from OpenAlex when the work was
    enriched); None when absent. A different measure from `cited_by`, never merged with it."""

    @property
    def cited_by_excluding_self(self) -> int | None:
        if self.cited_by is None or self.self_cited_by is None:
            return None
        return self.cited_by - self.self_cited_by


@dataclass(frozen=True)
class Candidate:
    """A cited item that no entry resolved to a work."""

    key: str
    title: str
    year: int | None
    citing_count: int
    dois: tuple[str, ...]
    arxivs: tuple[str, ...]


@dataclass
class CitationReport:
    works: list[WorkCitations] = field(default_factory=list)
    works_total: int = 0
    extractions: int = 0
    """Works with a live reference extraction: the first denominator."""
    entries: int = 0
    """Reference entries of the live extractions."""
    resolved_links: int = 0
    """Entries resolved to a work: the second denominator."""
    candidates: list[Candidate] = field(default_factory=list)
    as_of_year: int = 0


_NON_WORD = re.compile(r"[^a-z0-9]+")


def _name_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return _NON_WORD.sub(" ", folded).strip()


def _meta(data: str) -> tuple[str, int | None, frozenset[str], int | None]:
    d = json.loads(data)
    published = (d.get("dates") or {}).get("published") or ""
    year = int(published[:4]) if published[:4].isdigit() else None
    names = frozenset(
        k for a in (d.get("authors") or []) if (k := _name_key(str(a.get("name") or "")))
    )
    ext = d.get("cited_by_count")
    return str(d.get("title") or ""), year, names, ext if isinstance(ext, int) else None


def citation_report(project: Project, *, as_of_year: int) -> CitationReport:
    """Per-work in-corpus citation counts, denominators and snowball candidates."""
    project.index.sync()
    with project.index.connect() as conn:
        works = {
            str(wid): _meta(str(data))
            for wid, data in conn.execute(text("SELECT work_id, data FROM works"))
        }
        extractions = int(
            conn.execute(
                text("SELECT COUNT(DISTINCT work_id) FROM reference_extractions WHERE live = 1")
            ).scalar()
            or 0
        )
        entries = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM reference_entries n JOIN reference_extractions x "
                    "USING (extraction_id) WHERE x.live = 1"
                )
            ).scalar()
            or 0
        )
        links = conn.execute(
            text(
                "SELECT x.work_id, l.work_id, l.extraction_id, l.ordinal FROM reference_links l "
                "JOIN reference_extractions x USING (extraction_id) WHERE x.live = 1 "
                "AND l.state = :resolved AND l.work_id IS NOT NULL"
            ),
            {"resolved": LinkState.RESOLVED.value},
        ).all()
    resolved_keys = {(str(r[2]), int(r[3])) for r in links}
    citers: dict[str, set[str]] = {}
    for citing, cited, _x, _o in links:
        if citing != cited:
            citers.setdefault(str(cited), set()).add(str(citing))
    report = CitationReport(
        works_total=len(works),
        extractions=extractions,
        entries=entries,
        resolved_links=len(resolved_keys),
        as_of_year=as_of_year,
    )
    for wid in sorted(works):
        title, year, names, ext = works[wid]
        if extractions == 0:
            report.works.append(WorkCitations(wid, title, year, None, None, (), None, ext))
            continue
        who = sorted(citers.get(wid, ()))
        own = sum(1 for c in who if c in works and names & works[c][2])
        n = len(who)
        rate = n / max(1, as_of_year - year + 1) if year is not None else None
        report.works.append(WorkCitations(wid, title, year, n, own, tuple(who), rate, ext))
    for item in cited_items(project).items:
        if any((e.extraction_id, e.ordinal) in resolved_keys for e in item.entries):
            continue
        if item.year is None and not item.dois and not item.arxivs:
            continue  # nothing identifies it as a work (converter boilerplate lands here)
        report.candidates.append(
            Candidate(item.key, item.title, item.year, item.citing_count, item.dois, item.arxivs)
        )
    report.candidates.sort(key=lambda c: (-c.citing_count, c.key))
    return report
