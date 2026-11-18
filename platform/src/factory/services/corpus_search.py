"""Keyword search over the passages of a selection (plan chat T3b).

Search ranks and never judges: there is no score threshold, and no work is dropped or hidden.

Invariants:
- Only the pinned conversions of the resolved selection are searched; the sidecar index
  (`passage_index`) is rebuildable, never authoritative, and is the only thing written.
- Each query is plain text: words become quoted FTS5 terms joined with OR, so punctuation cannot
  break the syntax; a double-quoted phrase stays a phrase. Per query, passages are ranked by bm25
  (title and section path weighted below the text); queries are fused by reciprocal rank fusion
  (k = 60). Ties break by work id, then passage id. Per query at most `CANDIDATES` passages are
  ranked.
- Returned titles and texts pass the same held-out scrub as other tools that name works
  (`held_out_tokens(include_work_ids=False)`); the scrub replaces identifiers, never a hit.
- An empty query, or more than `MAX_QUERIES` queries, is refused on field `queries`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.context import Project
from factory.services.passage_index import IndexReport, ensure_indexed, open_index
from factory.services.search import get_work
from factory.services.selection import SelectionSpec, resolve_selection
from factory.services.withholding import held_out_tokens, withhold

__all__ = ["CANDIDATES", "MAX_QUERIES", "RRF_K", "Hit", "SearchResult", "corpus_search"]

MAX_QUERIES = 10
RRF_K = 60
CANDIDATES = 1000
_TITLE_WEIGHT = 0.3
_PART = re.compile(r'"([^"]*)"|([^\s"]+)')


@dataclass(frozen=True)
class Hit:
    """One passage found; `ranks_per_query` holds the 1-based rank per query, None if no hit."""

    work_id: str
    title: str
    passage_id: str
    anchors: tuple[str, ...]
    section_path: tuple[str, ...]
    text: str
    rank: int
    ranks_per_query: tuple[int | None, ...]
    conversion_id: str


@dataclass(frozen=True)
class SearchResult:
    """The hits (fused order), the selection digest and the index report."""

    hits: tuple[Hit, ...]
    digest: str
    index: IndexReport


def _match(query: str) -> str | None:
    terms: list[str] = []
    for phrase, word in _PART.findall(query):
        part = phrase or word
        if any(ch.isalnum() for ch in part):
            terms.append('"' + part.replace('"', "") + '"')
    return " OR ".join(terms) if terms else None


def _validate(queries: Sequence[str]) -> list[str]:
    if not queries or len(queries) > MAX_QUERIES:
        raise FactoryValidationError(
            [ValidationIssue("queries", f"give between 1 and {MAX_QUERIES} queries")]
        )
    matches = [_match(q) for q in queries]
    if any(m is None for m in matches):
        raise FactoryValidationError([ValidationIssue("queries", "a query has no searchable word")])
    return [m for m in matches if m is not None]


def corpus_search(
    project: Project,
    queries: Sequence[str],
    spec: SelectionSpec,
    *,
    limit: int = 20,
    per_work_limit: int = 3,
) -> SearchResult:
    """Search the pinned conversions of `spec` (see the module invariants)."""
    matches = _validate(queries)
    selection = resolve_selection(project, spec)
    report = ensure_indexed(project, selection.works)
    pinned = [w.conversion_id for w in selection.works]
    ranked: list[dict[tuple[str, str], int]] = []
    rows: dict[tuple[str, str], tuple[str, str, str, str, str]] = {}
    with open_index(project) as conn:
        conn.execute("CREATE TEMP TABLE pinned(conversion_id TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO pinned VALUES (?)", [(c,) for c in pinned])
        for match in matches:
            found = conn.execute(
                "SELECT p.conversion_id, p.passage_id, p.work_id, p.anchors_json, "
                "p.section_path_json, p.text FROM passages_fts f "
                "JOIN passages p ON p.rowid = f.rowid "
                "WHERE passages_fts MATCH ? "
                "AND p.conversion_id IN (SELECT conversion_id FROM pinned) "
                "ORDER BY bm25(passages_fts, ?, 1.0), p.work_id, p.passage_id LIMIT ?",
                (match, _TITLE_WEIGHT, CANDIDATES),
            ).fetchall()
            ranks: dict[tuple[str, str], int] = {}
            for position, (conv, pid, work, anchors, path, text) in enumerate(found, start=1):
                key = (conv, pid)
                ranks[key] = position
                rows[key] = (work, anchors, path, text, conv)
            ranked.append(ranks)

    def score(key: tuple[str, str]) -> float:
        return sum(1.0 / (RRF_K + r[key]) for r in ranked if key in r)

    order = sorted(rows, key=lambda k: (-score(k), rows[k][0], k[1]))
    tokens = held_out_tokens(project, include_work_ids=False)
    hits: list[Hit] = []
    per_work: dict[str, int] = {}
    titles: dict[str, str] = {}
    for fused, key in enumerate(order, start=1):
        work, anchors, path, text, conv = rows[key]
        if per_work.get(work, 0) >= per_work_limit:
            continue
        per_work[work] = per_work.get(work, 0) + 1
        if work not in titles:
            record = get_work(project, work)
            titles[work] = "" if record is None else record.title
        hits.append(
            Hit(
                work_id=work,
                title=str(withhold(titles[work], tokens)),
                passage_id=key[1],
                anchors=tuple(json.loads(anchors)),
                section_path=tuple(json.loads(path)),
                text=str(withhold(text, tokens)),
                rank=fused,
                ranks_per_query=tuple(r.get(key) for r in ranked),
                conversion_id=conv,
            )
        )
        if len(hits) >= limit:
            break
    return SearchResult(tuple(hits), selection.digest, report)
