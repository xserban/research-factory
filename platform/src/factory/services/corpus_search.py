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
- Returned titles, section path elements and texts pass the same held-out scrub as other tools
  that name works (`held_out_tokens(include_work_ids=False)`); the scrub replaces identifiers,
  never a hit.
- bm25 statistics (document frequencies, average length) are those of the whole sidecar, so a
  rank is relative to the sidecar's contents (which works have been indexed so far); for a given
  sidecar the order is deterministic. Rank values are not comparable across sidecars.
- `kinds` restricts hits to passages of those section kinds (None: every indexed kind; related,
  appendix and back passages are never indexed). Strings are accepted; an unknown kind is refused
  on field `kinds`.
- An empty query, or more than `MAX_QUERIES` queries, is refused on field `queries`.
- `method` is `keyword` (the default, as above), `vector` (exact cosine of the query vectors
  against the passage vectors of `passage_vectors`; queries fused by reciprocal rank like keyword
  queries) or `hybrid` (reciprocal rank fusion, k = 60, of the keyword order and the vector order
  of each passage). Each hit records its `keyword_rank` and `vector_rank` (None when absent from
  that order). Passages lacking vectors are embedded on demand when at most `ON_DEMAND_MAX` are
  missing; otherwise `vector` is refused on field `vectors` (the remedy names the CLI command)
  and `hybrid` returns the keyword results with a `note`. When the embedder is unavailable
  `vector` is refused (ranker_unavailable) and `hybrid` falls back to keyword with a `note`.
  `SearchResult.method` is the method actually used. Like keyword search, vector search ranks and
  never drops a work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from factory.document.passages import SectionKind
from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.context import Project
from factory.services.passage_index import IndexReport, ensure_indexed, open_index
from factory.services.passage_vectors import (
    count_missing,
    default_embedder,
    ensure_embedded,
    model_key,
    vector_ranking,
)
from factory.services.ranking_model import Embedder
from factory.services.search import get_work
from factory.services.selection import SelectionSpec, resolve_selection_cached
from factory.services.withholding import held_out_tokens, withhold

__all__ = [
    "CANDIDATES",
    "MAX_QUERIES",
    "ON_DEMAND_MAX",
    "RRF_K",
    "Hit",
    "Method",
    "SearchResult",
    "corpus_search",
]

Method = Literal["keyword", "vector", "hybrid"]
ON_DEMAND_MAX = 300
"""Most passages embedded during a search (about 2 to 3 minutes on a CPU)."""

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
    section_kind: SectionKind
    keyword_rank: int | None = None
    vector_rank: int | None = None


@dataclass(frozen=True)
class SearchResult:
    """The hits (fused order), the selection digest and the index report."""

    hits: tuple[Hit, ...]
    digest: str
    index: IndexReport
    method: str = "keyword"
    note: str | None = None


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


def _validate_kinds(kinds: Collection[SectionKind] | None) -> list[str] | None:
    if kinds is None:
        return None
    values = {str(k) for k in kinds}
    allowed = {k.value for k in SectionKind}
    bad = sorted(values - allowed)
    if bad:
        raise FactoryValidationError(
            [ValidationIssue("kinds", f"unknown section kind: {', '.join(bad)}")]
        )
    return sorted(values)


_Key = tuple[str, str]
_Row = tuple[str, str, str, str, str, str]  # work, anchors, path, text, conversion, kind


def _keyword_ranks(
    project: Project,
    matches: Sequence[str],
    pinned: Sequence[str],
    kind_values: list[str] | None,
) -> tuple[list[dict[_Key, int]], dict[_Key, _Row]]:
    ranked: list[dict[_Key, int]] = []
    rows: dict[_Key, _Row] = {}
    with open_index(project) as conn:
        conn.execute("CREATE TEMP TABLE pinned(conversion_id TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO pinned VALUES (?)", [(c,) for c in pinned])
        conn.execute("CREATE TEMP TABLE wanted(kind TEXT PRIMARY KEY)")
        if kind_values is not None:
            conn.executemany("INSERT INTO wanted VALUES (?)", [(k,) for k in kind_values])
        for match in matches:
            found = conn.execute(
                "SELECT p.conversion_id, p.passage_id, p.work_id, p.anchors_json, "
                "p.section_path_json, p.text, p.section_kind FROM passages_fts f "
                "JOIN passages p ON p.rowid = f.rowid "
                "WHERE passages_fts MATCH ? "
                "AND p.conversion_id IN (SELECT conversion_id FROM pinned) "
                "AND (? = 0 OR p.section_kind IN (SELECT kind FROM wanted)) "
                "ORDER BY bm25(passages_fts, ?, 1.0), p.work_id, p.passage_id LIMIT ?",
                (match, int(kind_values is not None), _TITLE_WEIGHT, CANDIDATES),
            ).fetchall()
            ranks: dict[_Key, int] = {}
            for position, (conv, pid, work, anchors, path, text, kind) in enumerate(found, start=1):
                key = (conv, pid)
                ranks[key] = position
                rows[key] = (work, anchors, path, text, conv, kind)
            ranked.append(ranks)
    return ranked, rows


def _fuse(ranked: Sequence[dict[_Key, int]], work_of: dict[_Key, str]) -> dict[_Key, int]:
    """Reciprocal rank fusion of ranked lists into one 1-based rank per passage."""
    keys = {k for r in ranked for k in r}
    scores = {k: sum(1.0 / (RRF_K + r[k]) for r in ranked if k in r) for k in keys}
    order = sorted(keys, key=lambda k: (-scores[k], work_of[k], k[1]))
    return {k: i for i, k in enumerate(order, start=1)}


def _fetch_rows(
    project: Project, keys: Collection[_Key], rows: dict[_Key, _Row]
) -> dict[_Key, _Row]:
    missing = [k for k in keys if k not in rows]
    if not missing:
        return rows
    with open_index(project) as conn:
        for conv, pid in missing:
            r = conn.execute(
                "SELECT work_id, anchors_json, section_path_json, text, section_kind "
                "FROM passages WHERE conversion_id = ? AND passage_id = ?",
                (conv, pid),
            ).fetchone()
            if r is not None:
                rows[(conv, pid)] = (r[0], r[1], r[2], r[3], conv, r[4])
    return rows


def _embed_command(spec: SelectionSpec) -> str:
    parts = ["factory passages embed"]
    if spec.layers:
        parts.append("--layers " + ",".join(spec.layers))
    for flag, values in (("--include", spec.include), ("--exclude", spec.exclude)):
        if values:
            parts.append(f"{flag} " + ",".join(values))
    return " ".join(parts)


def corpus_search(
    project: Project,
    queries: Sequence[str],
    spec: SelectionSpec,
    *,
    limit: int = 20,
    per_work_limit: int = 3,
    kinds: Collection[SectionKind] | None = None,
    method: Method = "keyword",
    embedder: Embedder | None = None,
) -> SearchResult:
    """Search the pinned conversions of `spec` (see the module invariants). `embedder` is used by
    `vector` and `hybrid`; when None, SPECTER2 from FACTORY_RANKER_MODEL."""
    if method not in ("keyword", "vector", "hybrid"):
        raise FactoryValidationError(
            [ValidationIssue("method", "method must be keyword, vector or hybrid")]
        )
    matches = _validate(queries)
    kind_values = _validate_kinds(kinds)
    selection = resolve_selection_cached(project, spec)
    report = ensure_indexed(project, selection.works)
    pinned = [w.conversion_id for w in selection.works]
    used: Method = method
    note: str | None = None
    emb: Embedder | None = None
    if method != "keyword":
        try:
            emb = embedder if embedder is not None else default_embedder()
            missing = count_missing(project, selection.works, model_key(emb))
            command = _embed_command(spec)
            if missing > ON_DEMAND_MAX:
                if method == "vector":
                    raise FactoryValidationError(
                        [
                            ValidationIssue(
                                "vectors",
                                f"vectors missing for {missing} passages; run `{command}`",
                            )
                        ]
                    )
                note = f"vectors missing for {missing} passages; run `{command}`"
                emb = None
            elif missing:
                ensure_embedded(project, selection.works, emb)
        except FactoryValidationError as exc:
            if method == "vector" or exc.issues[0].field != "ranker":
                raise
            note = f"meaning-based search unavailable ({exc.issues[0].reason}); keyword only"
            emb = None
        if emb is None:
            used = "keyword"
    keyword_ranked: list[dict[_Key, int]] = []
    rows: dict[_Key, _Row] = {}
    if used in ("keyword", "hybrid"):
        keyword_ranked, rows = _keyword_ranks(project, matches, pinned, kind_values)
    vector_ranked: list[dict[_Key, int]] = []
    if used in ("vector", "hybrid") and emb is not None:
        vector_ranked = [
            {
                k: i
                for i, k in enumerate(
                    vector_ranking(
                        project, selection.works, q, emb, kinds=kind_values, k=CANDIDATES
                    ),
                    start=1,
                )
            }
            for q in queries
        ]
        rows = _fetch_rows(project, {k for r in vector_ranked for k in r}, rows)
        vector_ranked = [{k: v for k, v in r.items() if k in rows} for r in vector_ranked]
    work_of = {k: v[0] for k, v in rows.items()}
    if used == "keyword":
        per_query = keyword_ranked
        final = _fuse(keyword_ranked, work_of)
        kw_rank: dict[_Key, int] = final
        vec_rank: dict[_Key, int] = {}
    elif used == "vector":
        per_query = vector_ranked
        final = _fuse(vector_ranked, work_of)
        kw_rank, vec_rank = {}, final
    else:
        kw_rank = _fuse(keyword_ranked, work_of)
        vec_rank = _fuse(vector_ranked, work_of)
        per_query = keyword_ranked
        final = _fuse([kw_rank, vec_rank], work_of)
    order = sorted(final, key=final.__getitem__)
    tokens = held_out_tokens(project, include_work_ids=False)
    hits: list[Hit] = []
    per_work: dict[str, int] = {}
    titles: dict[str, str] = {}
    for fused, key in enumerate(order, start=1):
        work, anchors, path, text, conv, kind = rows[key]
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
                section_path=tuple(str(withhold(h, tokens)) for h in json.loads(path)),
                text=str(withhold(text, tokens)),
                rank=fused,
                ranks_per_query=tuple(r.get(key) for r in per_query),
                conversion_id=conv,
                section_kind=SectionKind(kind),
                keyword_rank=kw_rank.get(key),
                vector_rank=vec_rank.get(key),
            )
        )
        if len(hits) >= limit:
            break
    return SearchResult(tuple(hits), selection.digest, report, used, note)
