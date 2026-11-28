"""Deterministic analytics for the hub's Lenses and Explore pages (plan hub-ui, step 6).

Pure functions over plain records (`LensWork`, adoption tuples). Nothing here calls a model, reads
the index or writes; assembling the corpus rows is the job of the payload builders. Every function
sorts by value or id before it counts, so the same data in any order gives the same output. A work
whose value for a field is None is counted as the category `NOT_CODED`, never dropped silently,
except where a method says otherwise (association uses only works coded on both fields).
`METHODS` holds the plain-English definitions shown to the researcher.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

NOT_CODED = "Not coded"
REST = "Rest"
DNA_DIMS = ("technique", "architecture", "span", "human")

METHODS: dict[str, str] = {
    "results": (
        "Result rows of the design approach miner (pass A) of the included works. The grid counts "
        "the rows that describe the paper's own system by lifecycle stage and approach; the bars "
        "count every row by who the result is about (system role), how strong the evidence is "
        "(evidence grade) and what kind of value it is. At most the first 30 rows of a work are "
        "read, and the count of rows left out is given. These are readings of the papers, not "
        "re-measured results."
    ),
    "citation_rate": (
        "The number of distinct works citing a paper, among works whose reference list was "
        "extracted, divided by the years since its publication (the publication year counts as "
        "one, the as-of year is the current year). The count is a lower bound: a paper nobody "
        "extracted a citer for shows none, which is not a known zero. The count stored in the "
        "work record (OpenAlex) is shown beside it and never merged with it."
    ),
    "design_matrix": (
        "Works are counted by the value of two fields. A work with no value for a field is counted "
        "under 'Not coded' for it (flagged). The expected count of a cell is its row total times "
        "its column total divided by the number of works, what the counts would be if the two "
        "fields were unrelated. The residual is (observed - expected) / sqrt(expected): above +2 "
        "the pair occurs clearly more often than chance, below -2 clearly less often. It is a "
        "guide to where to look, not a test."
    ),
    "chains": (
        "Works flow across the chosen fields in order. For each field the k most common values are "
        "kept (ties by name) and the rest pooled as 'Rest'. A link is the number of works with a "
        "given value in one field and a given value in the next. Every column sums to the number "
        "of works."
    ),
    "trends": (
        "Works counted by value of one field in each period (calendar year, or half-year: January "
        "to June is H1). The share is the count divided by all works of that period. Works with "
        "no year (or, for half-years, no month) are counted apart as undated."
    ),
    "icicle": (
        "Works nested by the chosen fields in order. Each block is the number of works with that "
        "value and the values above it; its children partition it exactly. A missing value is "
        "'Not coded'."
    ),
    "influence": (
        "A work's influence share is the number of distinct corpus works citing it divided by all "
        "in-corpus citations. The Gini coefficient is computed over those counts for every work "
        "(0 when all are equal, near 1 when a few works receive nearly all citations); it is "
        "empty when no work is cited."
    ),
    "association": (
        "For every pair of coded fields, Cramer's V with the bias correction of Bergsma (2013), "
        "computed over the works coded on both fields (n is given per pair). V runs from 0 (no "
        "association) to 1 (each value of one field fixes the value of the other); the correction "
        "can clip small values to 0. Pairs with fewer than two works or a single observed value "
        "in a field have no V. No p-values are given; read V with its n."
    ),
    "technique_adoption": (
        "Works counted by stage, technique code and half-year, from the technique records (one "
        "work can have several rows; a work counts once per cell). The first-seen period of a "
        "technique is the earliest half-year with a work using it. Only works with a record are "
        "covered; the coverage note says how many. Records without a date are counted apart."
    ),
    "similar": (
        "Similarity to a work is the number of identical values across six fields (technique, "
        "architecture, span, human, layer and half-year of publication; a missing value never "
        "matches) plus the number of in-corpus works that both cite. Works scoring 0 are left "
        "out; ties are ordered by work id. The matched fields and shared works are listed per "
        "result."
    ),
}


@dataclass(frozen=True)
class LensWork:
    """One corpus work as the lenses see it. `dims` maps a field name to its value or None."""

    id: str
    year: int | None = None
    month: int | None = None
    layer: str | None = None
    dims: Mapping[str, str | None] = field(default_factory=dict)
    cited_here: int = 0
    published: str = ""


def value_of(work: LensWork, dim: str) -> str | None:
    """Value of a field; `layer` and `year` are read from the record itself."""
    if dim == "layer":
        return work.layer
    if dim == "year":
        return None if work.year is None else str(work.year)
    if dim == "half":
        return half_of(work.year, work.month)
    return work.dims.get(dim)


def half_of(year: int | None, month: int | None) -> str | None:
    """Half-year label such as '2024H1', or None when year or month is missing."""
    if year is None or month is None:
        return None
    return f"{year}H{1 if month <= 6 else 2}"


def _cat(work: LensWork, dim: str) -> str:
    v = value_of(work, dim)
    return NOT_CODED if v is None else v


def _order(values: Iterable[str]) -> list[str]:
    """Sorted by name with NOT_CODED last."""
    return sorted(set(values), key=lambda v: (v == NOT_CODED, v))


# 1. design matrix -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DesignMatrix:
    """Invariants: rows and cols are sorted (Not coded last); sum(observed) == n."""

    row_dim: str
    col_dim: str
    rows: list[str]
    cols: list[str]
    observed: list[list[int]]
    expected: list[list[float]]
    residuals: list[list[float]]
    row_totals: list[int]
    col_totals: list[int]
    n: int
    row_not_coded: int
    col_not_coded: int


def design_matrix(works: Sequence[LensWork], row_dim: str, col_dim: str) -> DesignMatrix:
    """Observed counts, expected counts under independence and standardized residuals."""
    pairs = [(_cat(w, row_dim), _cat(w, col_dim)) for w in works]
    rows = _order(p[0] for p in pairs)
    cols = _order(p[1] for p in pairs)
    count = Counter(pairs)
    observed = [[count[(r, c)] for c in cols] for r in rows]
    n = len(pairs)
    rt = [sum(line) for line in observed]
    ct = [sum(observed[i][j] for i in range(len(rows))) for j in range(len(cols))]
    expected = [[rt[i] * ct[j] / n for j in range(len(cols))] for i in range(len(rows))]
    resid = [
        [(observed[i][j] - expected[i][j]) / math.sqrt(expected[i][j]) for j in range(len(cols))]
        for i in range(len(rows))
    ]
    return DesignMatrix(
        row_dim,
        col_dim,
        rows,
        cols,
        observed,
        expected,
        resid,
        rt,
        ct,
        n,
        sum(1 for p in pairs if p[0] == NOT_CODED),
        sum(1 for p in pairs if p[1] == NOT_CODED),
    )


# 2. chains ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Chains:
    """Invariant: every column sums to n and every link layer sums to n. A link is (value in one
    field, value in the next, count, sorted ids of those works); count == len(ids)."""

    dims: list[str]
    columns: list[list[tuple[str, int]]]
    links: list[list[tuple[str, str, int, list[str]]]]
    n: int


def chains(works: Sequence[LensWork], dims: Sequence[str], top_k: int) -> Chains:
    """Flows across ordered fields, top_k values per field and the rest pooled as 'Rest'."""
    vals = [[_cat(w, d) for d in dims] for w in works]
    maps: list[dict[str, str]] = []
    columns: list[list[tuple[str, int]]] = []
    for j in range(len(dims)):
        cnt = Counter(v[j] for v in vals)
        ranked = sorted(cnt, key=lambda v: (-cnt[v], v))
        keep = set(ranked[:top_k])
        maps.append({v: (v if v in keep else REST) for v in cnt})
        pooled = Counter({maps[j][v]: 0 for v in cnt})
        for v, c in cnt.items():
            pooled[maps[j][v]] += c
        columns.append(sorted(pooled.items(), key=lambda kv: (kv[0] == REST, -kv[1], kv[0])))
    links: list[list[tuple[str, str, int, list[str]]]] = []
    for j in range(len(dims) - 1):
        lw: dict[tuple[str, str], list[str]] = defaultdict(list)
        for work, vs in zip(works, vals, strict=True):
            lw[(maps[j][vs[j]], maps[j + 1][vs[j + 1]])].append(work.id)
        links.append([(a, b, len(ids), sorted(ids)) for (a, b), ids in sorted(lw.items())])
    return Chains(list(dims), columns, links, len(works))


# 3. trends ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Trends:
    dim: str
    by: str
    periods: list[str]
    values: list[str]
    counts: dict[str, dict[str, int]]
    shares: dict[str, dict[str, float]]
    totals: dict[str, int]
    undated: int


def trends(works: Sequence[LensWork], dim: str, by: str = "year") -> Trends:
    """Counts and shares of a field's values per period; `by` is 'year' or 'half'."""
    if by not in ("year", "half"):
        raise ValueError(f"by must be 'year' or 'half', got {by!r}")
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    undated = 0
    for w in works:
        p = value_of(w, by)
        if p is None:
            undated += 1
            continue
        counts[p][_cat(w, dim)] += 1
    periods = sorted(counts)
    values = _order(v for c in counts.values() for v in c)
    totals = {p: sum(counts[p].values()) for p in periods}
    return Trends(
        dim,
        by,
        periods,
        values,
        {p: {v: counts[p][v] for v in values if counts[p][v]} for p in periods},
        {p: {v: counts[p][v] / totals[p] for v in values if counts[p][v]} for p in periods},
        totals,
        undated,
    )


# 4. icicle ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IcicleNode:
    name: str
    count: int
    children: list[IcicleNode]


def icicle(works: Sequence[LensWork], dims: Sequence[str]) -> IcicleNode:
    """Hierarchy of counts by nested fields; children of a node partition its count."""

    def build(name: str, members: Sequence[LensWork], level: int) -> IcicleNode:
        if level == len(dims):
            return IcicleNode(name, len(members), [])
        groups: dict[str, list[LensWork]] = defaultdict(list)
        for w in members:
            groups[_cat(w, dims[level])].append(w)
        kids = [build(k, groups[k], level + 1) for k in groups]
        kids.sort(key=lambda x: (x.name == NOT_CODED, -x.count, x.name))
        return IcicleNode(name, len(members), kids)

    return build("All works", works, 0)


# 5. influence ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class InfluenceItem:
    id: str
    cited_here: int
    share: float
    year: int | None
    layer: str | None
    published: str = ""


@dataclass(frozen=True)
class Influence:
    items: list[InfluenceItem]
    total_citations: int
    gini: float | None


def influence(
    works: Sequence[LensWork], cites: Mapping[str, Collection[str]] | None = None
) -> Influence:
    """Share of in-corpus citations per work and the Gini of the counts.

    When `cites` (citing work id -> works it cites) is given, `cited_here` is the number of
    distinct citing corpus works computed from it; otherwise the record's own count is used.
    """
    ids = {w.id for w in works}
    if cites is not None:
        got: Counter[str] = Counter()
        for citing, cited in cites.items():
            if citing in ids:
                for c in set(cited) & ids:
                    if c != citing:
                        got[c] += 1
        counts = {w.id: got[w.id] for w in works}
    else:
        counts = {w.id: w.cited_here for w in works}
    total = sum(counts.values())
    items = [
        InfluenceItem(
            w.id, counts[w.id], counts[w.id] / total if total else 0.0, w.year, w.layer, w.published
        )
        for w in works
    ]
    items.sort(key=lambda i: (-i.cited_here, i.id))
    return Influence(items, total, _gini(sorted(counts.values())))


def _gini(asc: Sequence[int]) -> float | None:
    n, s = len(asc), sum(asc)
    if n == 0 or s == 0:
        return None
    return 2 * sum((i + 1) * x for i, x in enumerate(asc)) / (n * s) - (n + 1) / n


# 6. association -------------------------------------------------------------------------------


@dataclass(frozen=True)
class AssocPair:
    a: str
    b: str
    n: int
    v: float | None


def cramers_v_corrected(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Bias-corrected Cramer's V (Bergsma 2013) of a list of coded pairs; None if undefined."""
    n = len(pairs)
    rows = sorted({p[0] for p in pairs})
    cols = sorted({p[1] for p in pairs})
    r, k = len(rows), len(cols)
    if n < 2 or r < 2 or k < 2:
        return None
    cnt = Counter(pairs)
    rt = Counter(p[0] for p in pairs)
    ct = Counter(p[1] for p in pairs)
    chi2 = sum(
        (cnt[(a, b)] - rt[a] * ct[b] / n) ** 2 / (rt[a] * ct[b] / n) for a in rows for b in cols
    )
    phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))
    rc = r - (r - 1) ** 2 / (n - 1)
    kc = k - (k - 1) ** 2 / (n - 1)
    denom = min(kc - 1, rc - 1)
    if denom <= 0:
        return None
    return math.sqrt(phi2 / denom)


def association(works: Sequence[LensWork], dims: Sequence[str]) -> list[AssocPair]:
    """Cramer's V (bias-corrected) for every pair of fields, over works coded on both.

    Sorted by V descending (undefined last), then by field names.
    """
    out: list[AssocPair] = []
    ds = sorted(dims)
    for i, a in enumerate(ds):
        for b in ds[i + 1 :]:
            coded = [
                (x, y)
                for w in works
                if (x := value_of(w, a)) is not None and (y := value_of(w, b)) is not None
            ]
            out.append(AssocPair(a, b, len(coded), cramers_v_corrected(coded)))
    out.sort(key=lambda p: (p.v is None, -(p.v or 0.0), p.a, p.b))
    return out


# 7. technique adoption ------------------------------------------------------------------------

AdoptionRecord = tuple[str, str, str, int | None, int | None]


@dataclass(frozen=True)
class AdoptionCell:
    stage: str
    technique: str
    period: str
    works: int
    ids: list[str]


@dataclass(frozen=True)
class Adoption:
    cells: list[AdoptionCell]
    periods: list[str]
    stages: list[str]
    techniques: list[str]
    labels: dict[str, str]
    first_seen: dict[str, str]
    unlisted: list[str]
    works_with_records: int
    undated_records: int
    coverage_note: str


def technique_adoption(records: Iterable[AdoptionRecord], codebook: Mapping[str, str]) -> Adoption:
    """Stage x technique x half-year counts of distinct works, first-seen period per technique.

    `records` are (work_id, stage, technique_code, year, month); `codebook` maps code to label.
    """
    recs = list(records)
    cell_works: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    undated = 0
    for wid, stage, code, y, m in recs:
        p = half_of(y, m)
        if p is None:
            undated += 1
            continue
        cell_works[(stage, code, p)].add(wid)
    cells = [
        AdoptionCell(s, t, p, len(ws), sorted(ws)) for (s, t, p), ws in sorted(cell_works.items())
    ]
    first: dict[str, str] = {}
    for c in cells:
        if c.technique not in first or c.period < first[c.technique]:
            first[c.technique] = c.period
    n_works = len({r[0] for r in recs})
    techs = sorted({c.technique for c in cells})
    return Adoption(
        cells,
        sorted({c.period for c in cells}),
        sorted({c.stage for c in cells}),
        techs,
        {t: codebook.get(t, t) for t in techs},
        first,
        [t for t in techs if t not in codebook],
        n_works,
        undated,
        f"{n_works} works have technique records; works without records are not covered.",
    )


# 8. similar -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SimilarItem:
    id: str
    score: int
    matched_dims: list[str]
    shared_cites: list[str]


def dna(work: LensWork) -> dict[str, str | None]:
    """The six DNA segments of a work."""
    d: dict[str, str | None] = {k: work.dims.get(k) for k in DNA_DIMS}
    d["layer"] = work.layer
    d["half"] = half_of(work.year, work.month)
    return d


def similar(
    works: Sequence[LensWork],
    cited_by_work: Mapping[str, Collection[str]],
    target_id: str,
    k: int = 10,
) -> list[SimilarItem]:
    """The k works most like the target: identical non-None DNA values plus shared cited works.

    `cited_by_work` maps a work id to the in-corpus works it cites. Score 0 is omitted.
    """
    by_id = {w.id: w for w in works}
    t = by_id[target_id]
    td = dna(t)
    tc = set(cited_by_work.get(target_id, ()))
    out: list[SimilarItem] = []
    for w in works:
        if w.id == target_id:
            continue
        wd = dna(w)
        matched = [d for d, v in td.items() if v is not None and wd[d] == v]
        shared = sorted(tc & set(cited_by_work.get(w.id, ())))
        score = len(matched) + len(shared)
        if score:
            out.append(SimilarItem(w.id, score, matched, shared))
    out.sort(key=lambda s: (-s.score, s.id))
    return out[:k]


# payload --------------------------------------------------------------------------------------


def lenses_payload(
    works: Sequence[LensWork],
    *,
    matrix_dims: tuple[str, str],
    chain_dims: Sequence[str],
    trend_dim: str,
    icicle_dims: Sequence[str],
    assoc_dims: Sequence[str],
    cites: Mapping[str, Collection[str]] | None = None,
    adoption_records: Iterable[AdoptionRecord] = (),
    codebook: Mapping[str, str] | None = None,
    top_k: int = 8,
    matrix_pair_dims: Sequence[str] = (),
) -> dict[str, Any]:
    """JSON-safe payload for the Lenses page; every number is computed here.

    `matrices` holds the design matrix of every ordered pair of `matrix_pair_dims`, keyed
    "<row>|<col>"; `icicle.dims` names the field of each level below the root."""
    pairs = [(a, b) for a in matrix_pair_dims for b in matrix_pair_dims if a != b]
    icy = asdict(icicle(works, icicle_dims))
    icy["dims"] = list(icicle_dims)
    return {
        "n": len(works),
        "methods": dict(METHODS),
        "matrix": asdict(design_matrix(works, *matrix_dims)),
        "matrices": {f"{a}|{b}": asdict(design_matrix(works, a, b)) for a, b in pairs},
        "chains": asdict(chains(works, chain_dims, top_k)),
        "trends": {by: asdict(trends(works, trend_dim, by)) for by in ("year", "half")},
        "icicle": icy,
        "influence": asdict(influence(works, cites)),
        "association": [asdict(p) for p in association(works, assoc_dims)],
        "adoption": asdict(technique_adoption(adoption_records, codebook or {})),
    }


# ------------------------------------------------------------------ results grid, citation rate

RESULT_CAP_PER_WORK = 30
CITATION_RATE_TOP = 50
RESULT_BARS = ("system_role", "evidence_grade", "value_kind")


def results_grid(
    rows_by_work: Mapping[str, Sequence[Mapping[str, str]]],
    n_rows_by_work: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Heat grid and bars of the design-approach result rows (pass A) of the given works.

    `rows_by_work` holds at most `RESULT_CAP_PER_WORK` rows per work; `n_rows_by_work` the real
    row counts, so `left_out` can say how many rows the cap hides. `cells` lists, for every
    (stage, approach) with an own-system row, the row count and the work ids; `bars` counts every
    row by system role, evidence grade and value kind. Sorted by name; no value is typed."""
    rows = [(w, r) for w in sorted(rows_by_work) for r in rows_by_work[w]]
    own = [(w, r) for w, r in rows if r.get("system_role") == "own-system"]
    cells: dict[tuple[str, str], list[str]] = defaultdict(list)
    for w, r in own:
        if r.get("stage") and r.get("approach"):
            cells[(r["stage"], r["approach"])].append(w)
    n_real = n_rows_by_work or {}
    left_out = sum(max(0, n_real.get(w, len(rs)) - len(rs)) for w, rs in rows_by_work.items())
    return {
        "works_with_rows": sum(1 for rs in rows_by_work.values() if rs),
        "rows": len(rows),
        "own": len(own),
        "left_out": left_out,
        "cap_per_work": RESULT_CAP_PER_WORK,
        "stages": sorted({s for s, _a in cells}),
        "approaches": sorted({a for _s, a in cells}),
        "cells": [
            {"stage": s, "approach": a, "n": len(ws), "works": sorted(set(ws))}
            for (s, a), ws in sorted(cells.items())
        ],
        "bars": {
            f: sorted(
                ([v, n] for v, n in Counter(r[f] for _w, r in rows if r.get(f)).items()),
                key=lambda x: (-x[1], x[0]),
            )
            for f in RESULT_BARS
        },
        "methods": METHODS["results"],
    }


def citation_rate(
    works: Iterable[Any],
    included: Collection[str],
    *,
    extractions: int,
    entries: int,
    resolved_links: int,
    works_total: int,
    as_of_year: int,
    top: int = CITATION_RATE_TOP,
    published: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Citation rate per year of the included works (`citations.WorkCitations`), top `top`.

    `works` are the report's per-work records. A work with no rate (no reference list was
    extracted, or no year) is counted in `unknown`, never as zero. The head counts are the
    report's own. `as_of_year` is None when no reference list was extracted (no rate exists), so
    the payload of such a project does not depend on the date."""
    inc = set(included)
    mine = [w for w in works if w.work_id in inc]
    rated = sorted(
        (w for w in mine if w.per_year is not None),
        key=lambda w: (-w.per_year, w.work_id),
    )
    return {
        "as_of_year": as_of_year if extractions else None,
        "extractions": extractions,
        "entries": entries,
        "resolved_links": resolved_links,
        "works_total": works_total,
        "included": len(inc),
        "unknown": len(mine) - len(rated),
        "top": top,
        "rows": [
            {
                "id": w.work_id,
                "published": (published or {}).get(w.work_id, ""),
                "year": w.year,
                "cited_by": w.cited_by,
                "self_cited_by": w.self_cited_by,
                "per_year": round(w.per_year, 3),
                "external": w.external,
            }
            for w in rated[:top]
        ],
        "methods": METHODS["citation_rate"],
    }
