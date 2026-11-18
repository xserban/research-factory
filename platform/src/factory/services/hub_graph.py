"""Deterministic analytics for the hub's Graph page (plan hub-ui, step 7).

Pure Python over plain data: a `CitationGraph` (papers with an optional date, live `cites` edges
from citing to cited work), a set of corpus work ids, and optional labels. Nothing here calls a
model, adds a dependency or writes; `load_citation_graph` and `load_reference_rows` read the index
read-only. Every function sorts by id before it computes, so the same data in any input order gives
the same output. `METHODS` holds the plain-English definitions shown to the researcher.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import text

from factory.services.context import Project

METHODS: dict[str, str] = {
    "landscape": (
        "Every work of the corpus, plus the outside works that at least two corpus works cite "
        "(the first ring). Only live citation links between works of the shown set are drawn. "
        "In-degree counts the distinct corpus works citing a work; out-degree counts the works it "
        "cites. Outside works cited by fewer corpus works are hidden and counted."
    ),
    "foundations": (
        "Works outside the corpus ranked by how many distinct corpus works cite them. The share "
        "is that number divided by the corpus size. Ties are ordered by work id. A corpus work "
        "never appears here."
    ),
    "coupling": (
        "Two corpus works are bibliographically coupled when they cite the same works. The weight "
        "is the number of shared references (pairs below the minimum are left out); the "
        "normalised weight is the shared count divided by the square root of the product of the "
        "two reference counts (Salton cosine)."
    ),
    "schools": (
        "Groups of corpus works that cite similar literature, found by weighted label propagation "
        "on the coupling graph with a fixed seed and id-ordered ties, so a rerun gives the same "
        "groups. Works with no coupling partner are grouped as unclustered. The dominant label "
        "is the most frequent value of the chosen label among members, with its share."
    ),
    "main_path": (
        "Search Path Count on the citation network inside the corpus, with knowledge flowing from "
        "cited to citing work: the weight of a link is the number of source-to-sink paths through "
        "it. The main path starts at the heaviest link leaving a source and follows the heaviest "
        "outgoing link at each step. Links inside a citation cycle that point backwards in time "
        "(by date, then id) are dropped and counted. A citation inside the corpus can point to a "
        "later-dated work (a preprint cited before its recorded publication date), so stops on "
        "the path are not always in date order."
    ),
    "river": (
        "One arc per citation between two corpus works, from the citing to the cited work, with "
        "the lag in months between their publication dates (month precision; missing months "
        "count as January). A citation can point to a later-dated work (a preprint cited before "
        "its recorded publication date); its lag is then negative, and the number of such "
        "citations is given."
    ),
    "reference_health": (
        "For each corpus work, the reference entries of its live extraction counted by link "
        "state: resolved, ambiguous, unconfirmed or unresolved. A work with no extraction has no "
        "counts and is flagged."
    ),
}

STATES = ("resolved", "ambiguous", "unconfirmed", "unresolved")
UNCLUSTERED = "unclustered"
LANDSCAPE_MAX_NODES = 3000


@dataclass(frozen=True)
class CitationGraph:
    """Papers (id -> publication date string or None) and live `cites` edges (citing, cited).

    Invariants (enforced by `make_graph`): edges are unique, have no self loops and every endpoint
    is a node."""

    nodes: Mapping[str, str | None]
    edges: tuple[tuple[str, str], ...]


def make_graph(
    nodes: Mapping[str, str | None] | Iterable[str], edges: Iterable[tuple[str, str]]
) -> CitationGraph:
    """Normalise plain data: dedupe edges, drop self loops, add edge endpoints as nodes."""
    ns: dict[str, str | None] = dict(nodes) if isinstance(nodes, Mapping) else dict.fromkeys(nodes)
    es = sorted({(a, b) for a, b in edges if a != b})
    for a, b in es:
        ns.setdefault(a, None)
        ns.setdefault(b, None)
    return CitationGraph(dict(sorted(ns.items())), tuple(es))


# ---------------------------------------------------------------- dates


def _ym(date: str | None) -> tuple[int, int] | None:
    """(year, month) of an ISO date string of any precision, or None."""
    if not date or len(date) < 4 or not date[:4].isdigit():
        return None
    month = int(date[5:7]) if len(date) >= 7 and date[5:7].isdigit() else 1
    return int(date[:4]), min(max(month, 1), 12)


def _sort_key(graph: CitationGraph, wid: str) -> tuple[str, str]:
    """Chronological key: padded date ('' when unknown, so earliest), then id."""
    d = graph.nodes.get(wid) or ""
    ym = _ym(d)
    if ym is None:
        return ("", wid)
    day = d[8:10] if len(d) >= 10 and d[8:10].isdigit() else "01"
    return (f"{ym[0]:04d}-{ym[1]:02d}-{day}", wid)


# ---------------------------------------------------------------- landscape


@dataclass(frozen=True)
class LandscapeNode:
    id: str
    in_corpus: bool
    in_degree: int
    out_degree: int
    year: int | None
    cluster: str | None
    label: str | None


@dataclass(frozen=True)
class Landscape:
    nodes: tuple[LandscapeNode, ...]
    edges: tuple[tuple[str, str], ...]
    ring_min: int
    hidden_nodes: int
    hidden_edges: int
    total_nodes: int
    total_edges: int
    full: bool


def landscape(
    graph: CitationGraph,
    corpus: Iterable[str],
    clusters: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    max_nodes: int = LANDSCAPE_MAX_NODES,
    full: bool = False,
) -> Landscape:
    """Corpus works plus the first ring (outside works cited by >= 2 corpus works).

    in_degree = distinct corpus works citing the node; out_degree = distinct works it cites.
    Edges are the live edges with both endpoints shown. If the view would exceed `max_nodes`, the
    ring threshold rises until it fits (corpus works are always shown); `ring_min` reports it.
    With `full` every graph node is shown. Nodes and edges are ordered by id; `hidden_*` count
    what the view leaves out."""
    cset = set(corpus)
    clusters = clusters or {}
    labels = labels or {}
    citers: dict[str, set[str]] = defaultdict(set)
    outs: dict[str, set[str]] = defaultdict(set)
    for a, b in graph.edges:
        outs[a].add(b)
        if a in cset:
            citers[b].add(a)
    all_ids = sorted(set(graph.nodes) | cset)
    ring_min = 2
    if full:
        shown = set(all_ids)
        ring_min = 0
    else:
        outside = sorted(
            (len(citers[w]) for w in all_ids if w not in cset and len(citers[w]) >= 2),
            reverse=True,
        )
        room = max(max_nodes - len(cset), 0)
        if len(outside) > room:
            ring_min = outside[room] + 1
        shown = {w for w in all_ids if w in cset or len(citers[w]) >= ring_min}
    nodes = tuple(
        LandscapeNode(
            id=w,
            in_corpus=w in cset,
            in_degree=len(citers[w]),
            out_degree=len(outs[w]),
            year=(_ym(graph.nodes.get(w)) or (None, 0))[0],
            cluster=clusters.get(w),
            label=labels.get(w),
        )
        for w in all_ids
        if w in shown
    )
    edges = tuple((a, b) for a, b in graph.edges if a in shown and b in shown)
    return Landscape(
        nodes,
        edges,
        ring_min,
        len(all_ids) - len(nodes),
        len(graph.edges) - len(edges),
        len(all_ids),
        len(graph.edges),
        full,
    )


# ---------------------------------------------------------------- foundations


@dataclass(frozen=True)
class Foundation:
    id: str
    citing: tuple[str, ...]
    count: int
    share: float


def foundations(graph: CitationGraph, corpus: Iterable[str], top: int = 50) -> list[Foundation]:
    """Outside-corpus works ranked by distinct corpus citers (descending), ties by id.

    Invariant: no corpus work is ever returned. `share` = count / corpus size (0.0 when the
    corpus is empty)."""
    cset = set(corpus)
    citers: dict[str, set[str]] = defaultdict(set)
    for a, b in graph.edges:
        if a in cset and b not in cset:
            citers[b].add(a)
    ranked = sorted(citers.items(), key=lambda kv: (-len(kv[1]), kv[0]))[: max(top, 0)]
    return [
        Foundation(w, tuple(sorted(c)), len(c), len(c) / len(cset) if cset else 0.0)
        for w, c in ranked
    ]


# ---------------------------------------------------------------- coupling


@dataclass(frozen=True)
class CouplingPair:
    a: str
    b: str
    shared: int
    cosine: float


@dataclass(frozen=True)
class Coupling:
    """Pairs (a < b) sharing >= min_shared references, plus each corpus work's reference set."""

    pairs: tuple[CouplingPair, ...]
    refs: Mapping[str, frozenset[str]]
    nodes: tuple[str, ...]


def coupling(graph: CitationGraph, corpus: Iterable[str], min_shared: int = 2) -> Coupling:
    """Bibliographic coupling among corpus works.

    refs(x) = the distinct works x cites (any work, self excluded). shared(a, b) = |refs(a) and
    refs(b)|; cosine = shared / sqrt(|refs(a)| * |refs(b)|), always in (0, 1]. Pairs are ordered
    by id with a < b; only pairs with shared >= min_shared (and at least 1) are kept."""
    cset = sorted(set(corpus))
    cs = set(cset)
    refs: dict[str, set[str]] = {w: set() for w in cset}
    for a, b in graph.edges:
        if a in cs:
            refs[a].add(b)
    citers: dict[str, list[str]] = defaultdict(list)
    for w in cset:
        for r in sorted(refs[w]):
            citers[r].append(w)
    shared: Counter[tuple[str, str]] = Counter()
    for members in citers.values():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                shared[(a, b)] += 1
    floor = max(min_shared, 1)
    pairs = tuple(
        CouplingPair(a, b, n, n / math.sqrt(len(refs[a]) * len(refs[b])))
        for (a, b), n in sorted(shared.items())
        if n >= floor
    )
    return Coupling(pairs, {w: frozenset(r) for w, r in refs.items()}, tuple(cset))


# ---------------------------------------------------------------- schools


@dataclass(frozen=True)
class School:
    id: str
    members: tuple[str, ...]
    size: int
    dominant_label: str | None
    dominant_share: float
    top_refs: tuple[tuple[str, int], ...]


MAX_LPA_PASSES = 100
TOP_SCHOOL_REFS = 5


def _propagate(nodes: list[str], adj: Mapping[str, Mapping[str, int]], seed: int) -> dict[str, str]:
    """Asynchronous weighted label propagation; update order is a seeded shuffle of sorted ids."""
    label = {w: w for w in nodes}
    order = list(nodes)
    random.Random(seed).shuffle(order)
    for _ in range(MAX_LPA_PASSES):
        changed = False
        for w in order:
            score: dict[str, int] = defaultdict(int)
            for nb, weight in adj[w].items():
                score[label[nb]] += weight
            if not score:
                continue
            best = min(score, key=lambda lab: (-score[lab], lab))
            if best != label[w] and score[best] > score.get(label[w], 0):
                label[w] = best
                changed = True
        if not changed:
            break
    return label


def schools(
    result: Coupling, labels: Mapping[str, str] | None = None, seed: int = 0
) -> list[School]:
    """Communities of the coupling graph by weighted label propagation (weight = shared count).

    Deterministic: nodes are sorted by id, the update order is a `random.Random(seed)` shuffle of
    that sorted list, ties go to the smallest label. Communities of one work, and works without a
    coupling partner, form the single school `unclustered` (listed last, no top references).
    Schools are ordered by size (descending) then first member id and named `s1`, `s2`, ...
    `dominant_label` is the most frequent value of `labels` among members (ties: smallest value),
    `dominant_share` its count over all members."""
    labels = labels or {}
    adj: dict[str, dict[str, int]] = {w: {} for w in result.nodes}
    for p in result.pairs:
        adj[p.a][p.b] = p.shared
        adj[p.b][p.a] = p.shared
    final = _propagate(sorted(result.nodes), adj, seed)
    groups: dict[str, list[str]] = defaultdict(list)
    for w in sorted(final):
        groups[final[w]].append(w)
    real = sorted((m for m in groups.values() if len(m) > 1), key=lambda m: (-len(m), m[0]))
    single = sorted(w for m in groups.values() if len(m) == 1 for w in m)

    def build(sid: str, members: list[str], with_refs: bool) -> School:
        counts = Counter(labels[w] for w in members if w in labels)
        dom = min(counts, key=lambda v: (-counts[v], v)) if counts else None
        refs: Counter[str] = Counter()
        if with_refs:
            for w in members:
                refs.update(result.refs.get(w, ()))
        top = sorted(((r, n) for r, n in refs.items() if n >= 2), key=lambda t: (-t[1], t[0]))
        return School(
            sid,
            tuple(members),
            len(members),
            dom,
            counts[dom] / len(members) if dom is not None else 0.0,
            tuple(top[:TOP_SCHOOL_REFS]),
        )

    out = [build(f"s{i}", m, True) for i, m in enumerate(real, 1)]
    if single:
        out.append(build(UNCLUSTERED, single, False))
    return out


# ---------------------------------------------------------------- main path


@dataclass(frozen=True)
class MainPath:
    """SPC weights per flow edge (cited, citing), the main path as work ids, and dropped edges."""

    spc: Mapping[tuple[str, str], int]
    path: tuple[str, ...]
    dropped: tuple[tuple[str, str], ...]


def _components(nodes: list[str], succ: Mapping[str, list[str]]) -> dict[str, int]:
    """Strongly connected components (iterative Tarjan); returns node -> component number."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    comp: dict[str, int] = {}
    counter = 0
    ncomp = 0
    for root in nodes:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on.add(v)
            nxt = succ.get(v, [])
            for j in range(i, len(nxt)):
                w = nxt[j]
                if w not in index:
                    work.append((v, j + 1))
                    work.append((w, 0))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                if low[v] == index[v]:
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp[w] = ncomp
                        if w == v:
                            break
                    ncomp += 1
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[v])
    return comp


def main_path(graph: CitationGraph, corpus: Iterable[str]) -> MainPath:
    """Search Path Count main path on the corpus-internal citation network.

    Flow edges run from cited to citing work. Cycles are broken deterministically: inside each
    strongly connected component an edge is dropped unless its citing work is strictly later than
    its cited work by (date, id); the rest of the network is untouched, so the result is acyclic
    and `dropped` lists exactly the removed (citing, cited) edges. For a flow edge u -> v,
    SPC = paths(source -> u) * paths(v -> sink), counted with Python integers, over all
    source-to-sink paths (a source cites nothing in the corpus, a sink is cited by nothing).
    The path starts at the highest-SPC edge leaving a source and repeatedly takes the
    highest-SPC outgoing edge; ties are broken by (cited id, citing id)."""
    cs = set(corpus)
    inner = [(a, b) for a, b in graph.edges if a in cs and b in cs]
    ids = sorted({w for e in inner for w in e})
    cites: dict[str, list[str]] = {w: [] for w in ids}
    for a, b in inner:
        cites[a].append(b)
    comp = _components(ids, cites)
    dropped: list[tuple[str, str]] = []
    kept: list[tuple[str, str]] = []
    for a, b in inner:
        if comp[a] == comp[b] and not _sort_key(graph, a) > _sort_key(graph, b):
            dropped.append((a, b))
        else:
            kept.append((a, b))
    # flow edges (cited u -> citing v)
    out: dict[str, list[str]] = {w: [] for w in ids}
    inc: dict[str, list[str]] = {w: [] for w in ids}
    for a, b in kept:
        out[b].append(a)
        inc[a].append(b)
    indeg = {w: len(inc[w]) for w in ids}
    ready = sorted(w for w in ids if indeg[w] == 0)
    topo: list[str] = []
    while ready:
        w = ready.pop(0)
        topo.append(w)
        for v in sorted(out[w]):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
                ready.sort()
    n_in: dict[str, int] = {}
    for w in topo:
        n_in[w] = sum(n_in[u] for u in inc[w]) if inc[w] else 1
    n_out: dict[str, int] = {}
    for w in reversed(topo):
        n_out[w] = sum(n_out[v] for v in out[w]) if out[w] else 1
    spc = {(u, v): n_in[u] * n_out[v] for u in topo for v in out[u]}
    path: list[str] = []
    starts = [(u, v) for (u, v) in spc if not inc[u]]
    if starts:
        u, v = min(starts, key=lambda e: (-spc[e], e))
        path = [u, v]
        while out[v]:
            nxt = min(out[v], key=lambda x: (-spc[(v, x)], v, x))
            path.append(nxt)
            v = nxt
    return MainPath(dict(sorted(spc.items())), tuple(path), tuple(sorted(dropped)))


# ---------------------------------------------------------------- river


@dataclass(frozen=True)
class Arc:
    citing: str
    cited: str
    citing_date: str | None
    cited_date: str | None
    lag_months: int | None


def river_stats(arcs: Sequence[Arc]) -> dict[str, int]:
    """Citations counted, those with both dates known, and those to a later-dated work."""
    lags = [a.lag_months for a in arcs if a.lag_months is not None]
    return {"arcs": len(arcs), "dated": len(lags), "negative_lag": sum(1 for x in lags if x < 0)}


def river(
    graph: CitationGraph, corpus: Iterable[str], dates: Mapping[str, str | None] | None = None
) -> list[Arc]:
    """One arc per corpus-internal citation, ordered by (citing, cited).

    `dates` overrides the graph's dates. lag_months = months(citing) - months(cited) at month
    precision (negative when the cited work is dated later); None when either date is unknown."""
    cs = set(corpus)
    dates = dates if dates is not None else graph.nodes
    arcs = []
    for a, b in graph.edges:
        if a in cs and b in cs:
            da, db = dates.get(a), dates.get(b)
            ya, yb = _ym(da), _ym(db)
            lag = (ya[0] * 12 + ya[1]) - (yb[0] * 12 + yb[1]) if ya and yb else None
            arcs.append(Arc(a, b, da, db, lag))
    return arcs


# ---------------------------------------------------------------- reference health


@dataclass(frozen=True)
class WorkHealth:
    work_id: str
    has_extraction: bool
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def reference_health(rows: Iterable[tuple[str, str]], corpus: Iterable[str]) -> list[WorkHealth]:
    """Per corpus work, counts of reference links by state from (work_id, state) rows.

    `rows` are the links of live extractions with their folded state (a decision already applied).
    Every state in STATES is present (0 when absent); `has_extraction` is False for a corpus work
    with no row. Unknown states are ignored. Ordered by work id."""
    per: dict[str, Counter[str]] = defaultdict(Counter)
    for wid, state in rows:
        per[wid][state] += 1
    return [WorkHealth(w, w in per, {s: per[w][s] for s in STATES}) for w in sorted(set(corpus))]


def health_totals(items: Iterable[WorkHealth]) -> dict[str, int]:
    """Sum of the state counts over `items`, plus `works_without_extraction`."""
    items = list(items)
    tot = {s: sum(i.counts.get(s, 0) for i in items) for s in STATES}
    tot["works_without_extraction"] = sum(1 for i in items if not i.has_extraction)
    return tot


# ---------------------------------------------------------------- loaders and payload


def load_citation_graph(project: Project) -> CitationGraph:
    """Paper nodes and live `cites` edges between papers, read from the index (no writes).

    Dates come from the stored work record (`dates.published`) when the work is known; outside
    works never fetched have None."""
    with project.index.connect() as conn:
        ids = [
            str(r[0])
            for r in conn.execute(text("SELECT node_id FROM graph_nodes WHERE node_type = 'paper'"))
        ]
        edges = [
            (str(a), str(b))
            for a, b in conn.execute(
                text(
                    "SELECT source, target FROM graph_edges WHERE edge_type = 'cites' AND live = 1"
                )
            )
        ]
        dates: dict[str, str | None] = {}
        for wid, pub in conn.execute(
            text("SELECT work_id, json_extract(data, '$.dates.published') FROM works")
        ):
            dates[str(wid)] = str(pub) if pub else None
    paper = set(ids)
    return make_graph(
        {w: dates.get(w) for w in ids},
        [(a, b) for a, b in edges if a in paper and b in paper],
    )


def load_reference_rows(project: Project) -> list[tuple[str, str]]:
    """(citing work id, folded link state) for every link of a live extraction."""
    with project.index.connect() as conn:
        return [
            (str(w), str(s))
            for w, s in conn.execute(
                text(
                    "SELECT e.work_id, l.state FROM reference_links l JOIN reference_extractions e "
                    "USING (extraction_id) WHERE e.live = 1"
                )
            )
        ]


def outside_info(project: Project, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Title, first author and year of each work in `ids` that has a stored work record."""
    wanted = set(ids)
    out: dict[str, dict[str, Any]] = {}
    with project.index.connect() as conn:
        for wid, data in conn.execute(text("SELECT work_id, data FROM works")):
            if str(wid) not in wanted:
                continue
            d = json.loads(str(data))
            title = str(d.get("title") or "").strip()
            if not title:
                continue
            authors = d.get("authors") or []
            pub = str((d.get("dates") or {}).get("published") or "")
            out[str(wid)] = {
                "title": title,
                "author": str(authors[0].get("name") or "") if authors else "",
                "year": int(pub[:4]) if pub[:4].isdigit() else None,
            }
    return dict(sorted(out.items()))


def graph_payload(
    project: Project,
    corpus_ids: Iterable[str],
    labels: Mapping[str, str] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """All Graph-page analytics as JSON-serialisable data, with `METHODS` for the info panels."""
    corpus = sorted(set(corpus_ids))
    graph = load_citation_graph(project)
    coup = coupling(graph, corpus)
    sch = schools(coup, labels, seed)
    cluster_of = {w: s.id for s in sch for w in s.members}
    land = landscape(graph, corpus, cluster_of, labels)
    mp = main_path(graph, corpus)
    arcs = river(graph, corpus)
    found = foundations(graph, corpus)
    health = reference_health(load_reference_rows(project), corpus)
    return {
        "methods": METHODS,
        "landscape": asdict(land),
        "foundations": [asdict(f) for f in found],
        "outside_info": outside_info(
            project,
            {n.id for n in land.nodes if not n.in_corpus} | {f.id for f in found},
        ),
        "coupling": {
            "pairs": [asdict(p) for p in coup.pairs],
            "refs_per_work": {w: len(r) for w, r in coup.refs.items()},
        },
        "schools": [asdict(s) for s in sch],
        "main_path": {
            "path": list(mp.path),
            "spc": [{"cited": u, "citing": v, "spc": n} for (u, v), n in mp.spc.items()],
            "dropped": [list(e) for e in mp.dropped],
        },
        "river": [asdict(a) for a in arcs],
        "river_stats": river_stats(arcs),
        "reference_health": {
            "works": [
                {"work_id": h.work_id, "has_extraction": h.has_extraction, **h.counts}
                for h in health
            ],
            "totals": health_totals(health),
        },
    }
