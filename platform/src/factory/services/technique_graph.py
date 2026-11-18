"""The technique landscape: a derived, read-only, exploratory view of the technique miners' rows
(IDEA-78; plan 2026-11-18-technique-graph; decision "to be assigned at merge").

Nodes are approaches (categories of the `t-tech-<stage>` taxonomies; one node per stage and
category, so a technique two stage taxonomies both hold is two nodes), works and rows. Edges are
derived by rule from the pass-A rows of the latest non-retired derived miner of each such
taxonomy, joined to the resolved reference links and the work layers:

- `uses` work -> approach, one per current row; `co-used-with` between two approaches that rows
  of the same work name, weighted by the number of works;
- `derives-from` (candidate) work W -> work W2 for approach T when W's row for T has status
  `reused-cited`, a live, unrejected resolved G1 reference link runs W -> W2, and W2 has a row for
  T; the reverse direction is never derived;
- `earliest-in-corpus` approach -> work with the earliest publication date among its users (ties
  by work id): a date rule, not an origin claim; undated works are skipped and listed.

Invariants. Nothing is written, no event or table is added, no model is called. The same index
gives the same result in the same order. Every node, edge and result is labelled exploratory
(`factory.model.technique_graph`). No figure here enters a report. A held-out seed's work is a
corpus work here (decision 37 item 9): nothing is masked in the service; the MCP wrapper scrubs
stated identifiers as for other read tools. Gap, combination and challenge lists are hypotheses to
check, never findings.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations as _pairs
from typing import Any

from sqlalchemy import bindparam, text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.model.technique_graph import (
    EVIDENCE_LEVELS,
    NOT_STATED,
    SUPPORTIVE,
    Approach,
    ApproachView,
    Candidates,
    ChallengeCandidate,
    CombinationCandidate,
    CoUse,
    Edge,
    GapCandidate,
    Landscape,
    Lens,
    Neighbors,
    StageReach,
    StageSummary,
    UseRow,
    WorkNode,
)
from factory.services import mining as mining_service
from factory.services import taxonomies as tax_service
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.extraction import live_rows, stale_extractions
from factory.services.search import works_by_ids
from factory.services.work_layers import layers_for

__all__ = [
    "TECHNIQUE_TAXONOMY_PREFIX",
    "Inputs",
    "RawRow",
    "read_inputs",
    "technique_challenges",
    "technique_combinations",
    "technique_gaps",
    "technique_landscape",
    "technique_neighbors",
    "technique_view",
]

TECHNIQUE_TAXONOMY_PREFIX = "t-tech-"
REUSED = "reused-cited"
_CATEGORY = "category"
_CACHE_MAX = 4


@dataclass(frozen=True)
class RawRow:
    approach: str
    stage: str
    work_id: str
    extraction_id: str
    status: str | None
    evidence: str | None
    described_as: str | None
    quote: str | None
    anchor: str | None
    parameters: str | None


@dataclass(frozen=True)
class StageInfo:
    stage: str
    miner: str
    version: int
    residual_rows: int
    agreement: float | None
    agreement_aligned: float | None


@dataclass(frozen=True)
class WorkMeta:
    title: str
    date: str | None
    year: int | None
    layer: str | None


@dataclass(frozen=True)
class Inputs:
    """Everything the pure builders read: plain data, so tests can supply it directly."""

    catalogue: dict[str, tuple[str, str, str]]  # approach id -> (stage, name, definition)
    rows: tuple[RawRow, ...]
    stages: tuple[StageInfo, ...]
    works: dict[str, WorkMeta]
    cites: tuple[tuple[str, str, str], ...]  # (source work, target work, link id)
    extra: dict[str, Any] = field(default_factory=dict)


# --- reading -----------------------------------------------------------------------------------

_CACHE: dict[str, tuple[str | None, Inputs]] = {}
"""Project directory -> (last folded event id, inputs): a read-time memo per index snapshot."""


def _refuse(field_: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, reason)])


def _text(stored: Any) -> str | None:
    if stored is None:
        return None
    value = str(stored.value).strip()
    return value or None


def read_inputs(project: Project) -> Inputs:
    """The inputs of the landscape from the index, memoised per last folded event. Read-only."""
    project.index.sync()
    key = str(project.paths.dir)
    head = project.index.last_event_id()
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == head:
        return hit[1]
    inputs = _read(project)
    _CACHE.pop(key, None)
    while len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (head, inputs)
    return inputs


def _technique_miners(project: Project) -> list[tuple[str, int, str, int]]:
    """`(miner, version, taxonomy, taxonomy version)` of the latest non-retired derived miner of
    each technique taxonomy, by stage name."""
    best: dict[str, tuple[str, int, str, int]] = {}
    for row in mining_service.registered_miners(project):
        if row.retired:
            continue
        spec = mining_service.registered_miner(project, row.name, row.version)
        if spec is None or spec.taxonomy is None:
            continue
        if not spec.taxonomy.name.startswith(TECHNIQUE_TAXONOMY_PREFIX):
            continue
        current = best.get(row.name)
        if current is None or row.version > current[1]:
            best[row.name] = (row.name, row.version, spec.taxonomy.name, spec.taxonomy.version)
    return sorted(best.values(), key=lambda b: b[2])


def _read(project: Project) -> Inputs:
    catalogue: dict[str, tuple[str, str, str]] = {}
    rows: list[RawRow] = []
    stages: list[StageInfo] = []
    with project.index.snapshot(), entering():
        status = {s.name: s for s in mining_service.mine_status(project)}
        for miner, version, tname, tversion in _technique_miners(project):
            spec = tax_service.registered_taxonomy(project, tname, tversion)
            if spec is None or not spec.dimensions:
                continue
            stage = tname[len(TECHNIQUE_TAXONOMY_PREFIX) :]
            dimension = spec.dimensions[0]
            for c in dimension.categories:
                catalogue.setdefault(c.id, (stage, c.name, c.definition))
            keep: set[str] | None = None
            if miner in status:
                keep = set(mining_service.miner_population(project, miner))
            stale = stale_extractions(project, scope=MinerScope(miner))
            residual = 0
            for r in live_rows(project, PassLabel.A, scope=MinerScope(miner)):
                if r.extraction_id in stale or (keep is not None and r.work_id not in keep):
                    continue
                cat = r.fields.get(_CATEGORY)
                if cat is None:
                    continue
                cid = str(cat.value).split("/", 1)[-1]
                if catalogue.get(cid, ("",))[0] != stage:
                    residual += 1  # other, not-stated or outside the taxonomy: never counted
                    continue
                q = r.fields.get("quote")
                rows.append(
                    RawRow(
                        approach=cid,
                        stage=stage,
                        work_id=r.work_id,
                        extraction_id=r.extraction_id,
                        status=_text(r.fields.get("status")),
                        evidence=_text(r.fields.get("evidence")),
                        described_as=_text(r.fields.get("described_as")),
                        quote=(q.quote or _text(q)) if q is not None else cat.quote,
                        anchor=(q.anchor if q is not None and q.anchor else cat.anchor),
                        parameters=_text(r.fields.get("parameters")),
                    )
                )
            st = status.get(miner)
            stages.append(
                StageInfo(
                    stage,
                    miner,
                    version,
                    residual,
                    None if st is None else st.agreement,
                    None if st is None else st.agreement_aligned,
                )
            )
        ids = sorted({r.work_id for r in rows})
        layers = layers_for(project, ids)
        works: dict[str, WorkMeta] = {}
        for w in works_by_ids(project, ids):
            published = w.dates.published
            works[w.id] = WorkMeta(
                w.title,
                published.isoformat() if published else None,
                published.year if published else None,
                layers[w.id].layer if w.id in layers else None,
            )
        for i in ids:
            if i not in works:
                works[i] = WorkMeta(i, None, None, layers[i].layer if i in layers else None)
        cites = _read_cites(project, ids)
    rows.sort(key=lambda r: (r.approach, r.work_id, r.extraction_id))
    return Inputs(catalogue, tuple(rows), tuple(stages), works, cites)


def _read_cites(project: Project, sources: Sequence[str]) -> tuple[tuple[str, str, str], ...]:
    """Live, unrejected resolved `cites` links from `sources` (a link of a replaced extraction is
    not live, so a stale link is hidden as in the lineage views)."""
    if not sources:
        return ()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT source, target, edge_id FROM graph_edges WHERE edge_type = 'cites' "
                "AND live = 1 AND (decision IS NULL OR decision != 'reject') "
                "AND source IN :s ORDER BY source, target, edge_id"
            ).bindparams(bindparam("s", expanding=True)),
            {"s": list(sources)},
        ).all()
    return tuple((str(a), str(b), str(c)) for a, b, c in found)


# --- pure builders -----------------------------------------------------------------------------


def _evidence(row: RawRow) -> str:
    return row.evidence or NOT_STATED


def _status(row: RawRow) -> str:
    return row.status or NOT_STATED


def _in_layer(inputs: Inputs, rows: Iterable[RawRow], layer: str) -> list[RawRow]:
    if layer == "all":
        return list(rows)
    return [r for r in rows if inputs.works[r.work_id].layer == layer]


def _lens_rows(inputs: Inputs, lens: Lens, *, with_stage: bool = True) -> list[RawRow]:
    rows = _in_layer(inputs, inputs.rows, lens.layer)
    return [
        r
        for r in rows
        if (not with_stage or lens.stage is None or r.stage == lens.stage)
        and (lens.evidence is None or _evidence(r) == lens.evidence)
        and (lens.status is None or _status(r) == lens.status)
    ]


def _node(inputs: Inputs, approach: str, rows: Sequence[RawRow]) -> Approach:
    stage, name, definition = inputs.catalogue[approach]
    mine = [r for r in rows if r.approach == approach]
    ev: dict[str, int] = defaultdict(int)
    st: dict[str, int] = defaultdict(int)
    for r in mine:
        ev[_evidence(r)] += 1
        st[_status(r)] += 1
    return Approach(
        id=approach,
        stage=stage,
        name=name,
        definition=definition,
        works=len({r.work_id for r in mine}),
        rows=len(mine),
        by_evidence=dict(sorted(ev.items())),
        by_status=dict(sorted(st.items())),
    )


def _by_approach(rows: Iterable[RawRow]) -> dict[str, list[RawRow]]:
    out: dict[str, list[RawRow]] = defaultdict(list)
    for r in rows:
        out[r.approach].append(r)
    return out


def _co_use(rows: Iterable[RawRow]) -> dict[tuple[str, str], tuple[str, ...]]:
    per_work: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        per_work[r.work_id].add(r.approach)
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for work in sorted(per_work):
        for a, b in _pairs(sorted(per_work[work]), 2):
            pairs[(a, b)].append(work)
    return {k: tuple(v) for k, v in pairs.items()}


def derives_from(inputs: Inputs, rows: Sequence[RawRow]) -> list[Edge]:
    """Candidate `derives-from` edges (see the module docstring), sorted. Pure."""
    have = {(r.work_id, r.approach) for r in rows}
    links: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for source, target, link in inputs.cites:
        links[source].append((target, link))
    out: dict[tuple[str, str, str], Edge] = {}
    for r in rows:
        if r.status != REUSED:
            continue
        for target, link in links.get(r.work_id, ()):
            if target == r.work_id or (target, r.approach) not in have:
                continue
            out.setdefault(
                (r.work_id, target, r.approach),
                Edge(
                    kind="derives-from",
                    source=r.work_id,
                    target=target,
                    approach=r.approach,
                    works=(r.work_id, target),
                    basis=link,
                    note="candidate: a reused-cited row and a resolved reference to a work that "
                    "uses the same approach; not an origin claim",
                ),
            )
    return [out[k] for k in sorted(out)]


def _earliest(
    inputs: Inputs, approach: str, rows: Sequence[RawRow]
) -> tuple[Edge | None, list[str]]:
    users = sorted({r.work_id for r in rows if r.approach == approach})
    dated = [(inputs.works[w].date, w) for w in users if inputs.works[w].date]
    skipped = [w for w in users if not inputs.works[w].date]
    if not dated:
        return None, skipped
    date, work = min(dated)
    return (
        Edge(
            kind="earliest-in-corpus",
            source=approach,
            target=work,
            approach=approach,
            works=(work,),
            basis=date,
            note="date rule: the earliest publication date among the users in this corpus; "
            "not an origin claim",
        ),
        skipped,
    )


def _check_lens(
    inputs: Inputs, stage: str | None, evidence: str | None, status: str | None
) -> None:
    stages = {s.stage for s in inputs.stages}
    if stage is not None and stage not in stages:
        raise _refuse("stage", f"unknown stage; known: {', '.join(sorted(stages)) or 'none'}")
    if evidence is not None and evidence not in (*EVIDENCE_LEVELS, NOT_STATED):
        raise _refuse("evidence", f"must be one of {', '.join((*EVIDENCE_LEVELS, NOT_STATED))}")
    if status is not None and not status.strip():
        raise _refuse("status", "must not be blank")


def _positive(name: str, value: int) -> None:
    if value < 1:
        raise _refuse(name, "must be at least 1")


def build_landscape(
    inputs: Inputs,
    lens: Lens,
    *,
    max_edges: int | None = None,
    include_uses: bool = False,
) -> Landscape:
    """The landscape of `inputs` under `lens`. Pure and deterministic."""
    rows = _lens_rows(inputs, lens)
    by = _by_approach(rows)
    nodes = {a: _node(inputs, a, rows) for a in sorted(by)}
    co_rows = _lens_rows(inputs, lens, with_stage=False)
    edges: list[Edge] = []
    co = [
        (k, w)
        for k, w in _co_use(co_rows).items()
        if len(w) >= lens.min_co_works
        and (lens.stage is None or any(inputs.catalogue[x][0] == lens.stage for x in k))
    ]
    co.sort(key=lambda kw: (-len(kw[1]), kw[0]))
    co_edges = [
        Edge(kind="co-used-with", source=k[0], target=k[1], weight=len(w), works=w) for k, w in co
    ]
    omitted = 0
    if max_edges is not None and len(co_edges) > max_edges:
        omitted = len(co_edges) - max_edges
        co_edges = co_edges[:max_edges]
    needed = {x for e in co_edges for x in (e.source, e.target)} - nodes.keys()
    for a in sorted(needed):
        nodes[a] = _node(inputs, a, _lens_rows(inputs, lens, with_stage=False))
    edges.extend(co_edges)
    layer_rows = _in_layer(inputs, inputs.rows, lens.layer)
    derived = [
        e
        for e in derives_from(inputs, layer_rows)
        if lens.stage is None or inputs.catalogue[e.approach or ""][0] == lens.stage
    ]
    edges.extend(derived)
    undated: set[str] = set()
    for a in sorted(by):
        edge, skipped = _earliest(inputs, a, rows)
        undated.update(skipped)
        if edge is not None:
            edges.append(edge)
    if include_uses:
        edges.extend(
            Edge(kind="uses", source=r.work_id, target=r.approach, basis=r.extraction_id)
            for r in sorted(rows, key=lambda r: (r.work_id, r.approach, r.extraction_id))
        )
    summaries: list[StageSummary] = []
    for info in inputs.stages:
        if lens.stage is not None and info.stage != lens.stage:
            continue
        mine = [r for r in rows if r.stage == info.stage]
        summaries.append(
            StageSummary(
                stage=info.stage,
                miner=info.miner,
                version=info.version,
                approaches=len({r.approach for r in mine}),
                works=len({r.work_id for r in mine}),
                rows=len(mine),
                residual_rows=info.residual_rows,
                no_evidence_share=(
                    round(sum(1 for r in mine if not r.evidence) / len(mine), 4) if mine else None
                ),
                agreement=info.agreement,
                agreement_aligned=info.agreement_aligned,
                agreement_note=(
                    "exploratory, not calibrated"
                    if info.agreement is not None
                    else "no second pass"
                ),
            )
        )
    return Landscape(
        lens=lens,
        stages=tuple(summaries),
        approaches=tuple(sorted(nodes.values(), key=lambda n: (n.stage, n.id))),
        edges=tuple(edges),
        edges_omitted=omitted,
        undated_works=tuple(sorted(undated)),
    )


def _work_node(inputs: Inputs, work: str) -> WorkNode:
    m = inputs.works[work]
    return WorkNode(id=work, title=m.title, year=m.year, date=m.date, layer=m.layer)


def _use(row: RawRow) -> UseRow:
    return UseRow(
        approach=row.approach,
        stage=row.stage,
        work_id=row.work_id,
        extraction_id=row.extraction_id,
        status=_status(row),
        evidence=_evidence(row),
        described_as=row.described_as,
        quote=row.quote,
        anchor=row.anchor,
        parameters=row.parameters,
    )


def _known(inputs: Inputs, approach_id: str) -> None:
    if approach_id not in inputs.catalogue:
        raise _refuse("approach", "unknown approach")


def build_view(inputs: Inputs, approach_id: str, lens: Lens) -> ApproachView:
    _known(inputs, approach_id)
    rows = _lens_rows(inputs, lens, with_stage=False)
    mine = sorted(
        (r for r in rows if r.approach == approach_id),
        key=lambda r: (r.work_id, r.extraction_id),
    )
    earliest, skipped = _earliest(inputs, approach_id, mine)
    layer_rows = _in_layer(inputs, inputs.rows, lens.layer)
    candidates = [e for e in derives_from(inputs, layer_rows) if e.approach == approach_id]
    users = sorted({r.work_id for r in mine})
    return ApproachView(
        lens=lens,
        approach=_node(inputs, approach_id, rows),
        works=tuple(_work_node(inputs, w) for w in users),
        uses=tuple(_use(r) for r in mine),
        derives_from=tuple(candidates),
        earliest=earliest,
        undated_works=tuple(skipped),
        not_stated_share=(
            round(sum(1 for r in mine if not r.evidence) / len(mine), 4) if mine else None
        ),
    )


def build_neighbors(
    inputs: Inputs, approach_id: str, lens: Lens, *, min_works: int = 1, limit: int | None = None
) -> Neighbors:
    _known(inputs, approach_id)
    rows = _lens_rows(inputs, lens, with_stage=False)
    users = sorted({r.work_id for r in rows if r.approach == approach_id})
    uset = set(users)
    reach: dict[str, set[str]] = defaultdict(set)
    other: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r.work_id in uset:
            reach[r.stage].add(r.work_id)
            if r.approach != approach_id:
                other[r.approach].add(r.work_id)
    co = sorted(
        ((a, tuple(sorted(w))) for a, w in other.items() if len(w) >= min_works),
        key=lambda aw: (-len(aw[1]), aw[0]),
    )
    if limit is not None:
        co = co[:limit]
    layer_rows = _in_layer(inputs, inputs.rows, lens.layer)
    return Neighbors(
        lens=lens,
        approach=_node(inputs, approach_id, rows),
        co_used=tuple(
            CoUse(approach=_node(inputs, a, rows), weight=len(w), works=w) for a, w in co
        ),
        stages=tuple(
            StageReach(stage=s, works=len(w))
            for s, w in sorted(reach.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ),
        works=tuple(users),
        derives_from=tuple(
            e for e in derives_from(inputs, layer_rows) if e.approach == approach_id
        ),
    )


def build_gaps(
    inputs: Inputs,
    lens: Lens,
    *,
    from_stage: str,
    to_stage: str,
    min_works: int,
    max_to_share: float,
    limit: int | None,
) -> Candidates:
    """Approaches of `from_stage` used by at least `min_works` works, of which at most
    `max_to_share` (a share of those works, 0.0 for none) have any row of an approach of
    `to_stage`. Ordered by fewest such works, then most users, then id."""
    rows = _lens_rows(inputs, lens, with_stage=False)
    to_works = {r.work_id for r in rows if r.stage == to_stage}
    found: list[GapCandidate] = []
    for approach, mine in sorted(_by_approach(r for r in rows if r.stage == from_stage).items()):
        users = tuple(sorted({r.work_id for r in mine}))
        if len(users) < min_works:
            continue
        covered = tuple(w for w in users if w in to_works)
        if len(covered) / len(users) > max_to_share:
            continue
        node = _node(inputs, approach, rows)
        found.append(
            GapCandidate(
                approach=node,
                from_stage=from_stage,
                to_stage=to_stage,
                works=users,
                works_with_to_stage=covered,
                statement=(
                    f"{node.name} ({approach}) is used by {len(users)} work(s) at {from_stage}; "
                    f"{len(covered)} of them have a row at {to_stage}"
                ),
            )
        )
    found.sort(key=lambda g: (len(g.works_with_to_stage), -len(g.works), g.approach.id))
    return Candidates(
        kind="gaps",
        lens=lens,
        parameters={
            "from_stage": from_stage,
            "to_stage": to_stage,
            "min_works": min_works,
            "max_to_share": max_to_share,
            "limit": limit,
        },
        total=len(found),
        gaps=tuple(found if limit is None else found[:limit]),
    )


def build_combinations(
    inputs: Inputs,
    lens: Lens,
    *,
    min_works: int,
    max_co_works: int,
    stage: str | None,
    limit: int | None,
) -> Candidates:
    """Pairs of approaches each used by at least `min_works` works and used together by at most
    `max_co_works`. Ordered by the smaller user count, then the sum, then ids."""
    rows = _lens_rows(inputs, lens, with_stage=False)
    users = {a: {r.work_id for r in mine} for a, mine in _by_approach(rows).items()}
    big = sorted(a for a, w in users.items() if len(w) >= min_works)
    found: list[tuple[str, str, tuple[str, ...]]] = []
    for a, b in _pairs(big, 2):
        if stage is not None and stage not in (inputs.catalogue[a][0], inputs.catalogue[b][0]):
            continue
        both = tuple(sorted(users[a] & users[b]))
        if len(both) <= max_co_works:
            found.append((a, b, both))
    found.sort(
        key=lambda t: (
            -min(len(users[t[0]]), len(users[t[1]])),
            -(len(users[t[0]]) + len(users[t[1]])),
            t[0],
            t[1],
        )
    )
    shown = found if limit is None else found[:limit]
    return Candidates(
        kind="combinations",
        lens=lens,
        parameters={
            "min_works": min_works,
            "max_co_works": max_co_works,
            "stage": stage,
            "limit": limit,
        },
        total=len(found),
        combinations=tuple(
            CombinationCandidate(
                a=_node(inputs, a, rows),
                b=_node(inputs, b, rows),
                co_works=both,
                works_a=len(users[a]),
                works_b=len(users[b]),
                statement=(
                    f"{a} ({len(users[a])} works) and {b} ({len(users[b])} works) are used "
                    f"together by {len(both)} work(s) in this corpus"
                ),
            )
            for a, b, both in shown
        ),
    )


def build_challenges(inputs: Inputs, lens: Lens, *, limit: int | None) -> Candidates:
    """Approaches with a `reported-failure` row in one work and a supportive row (independent-test,
    own-ablation or own-comparison) in another. The settings may differ: a prompt to read the
    quotes, not a contradiction."""
    rows = _lens_rows(inputs, lens, with_stage=False)
    found: list[ChallengeCandidate] = []
    for approach, mine in sorted(_by_approach(rows).items()):
        failed = [r for r in mine if r.evidence == "reported-failure"]
        supported = [r for r in mine if r.evidence in SUPPORTIVE]
        fw = {r.work_id for r in failed}
        sw = {r.work_id for r in supported}
        if not fw or not sw or (fw == sw and len(fw) == 1):
            continue
        found.append(
            ChallengeCandidate(
                approach=_node(inputs, approach, rows),
                failed=tuple(_use(r) for r in sorted(failed, key=lambda r: r.extraction_id)),
                supported=tuple(_use(r) for r in sorted(supported, key=lambda r: r.extraction_id)),
                statement=(
                    f"{approach}: reported as failing by {len(fw)} work(s) and supported by "
                    f"{len(sw)} work(s); the settings may differ"
                ),
            )
        )
    found.sort(key=lambda c: (-min(len(c.failed), len(c.supported)), c.approach.id))
    return Candidates(
        kind="challenges",
        lens=lens,
        parameters={"limit": limit},
        total=len(found),
        challenges=tuple(found if limit is None else found[:limit]),
    )


# --- public API ---------------------------------------------------------------------------------


def technique_landscape(
    project: Project,
    *,
    layer: str = "core",
    stage: str | None = None,
    evidence: str | None = None,
    status: str | None = None,
    min_co_works: int = 2,
    max_edges: int | None = None,
    include_uses: bool = False,
) -> Landscape:
    """The landscape under the lens (default: the core layer, every stage). Read-only."""
    _positive("min_co_works", min_co_works)
    inputs = read_inputs(project)
    _check_lens(inputs, stage, evidence, status)
    lens = Lens(
        layer=layer, stage=stage, evidence=evidence, status=status, min_co_works=min_co_works
    )
    return build_landscape(inputs, lens, max_edges=max_edges, include_uses=include_uses)


def technique_view(
    project: Project,
    approach_id: str,
    *,
    layer: str = "core",
    evidence: str | None = None,
    status: str | None = None,
) -> ApproachView:
    """One approach: its works, one row per use with quote and anchor, candidate `derives-from`
    edges and the earliest-in-corpus date rule. Refused for an unknown approach."""
    inputs = read_inputs(project)
    _check_lens(inputs, None, evidence, status)
    return build_view(inputs, approach_id, Lens(layer=layer, evidence=evidence, status=status))


def technique_neighbors(
    project: Project,
    approach_id: str,
    *,
    layer: str = "core",
    min_works: int = 1,
    limit: int | None = None,
) -> Neighbors:
    """Co-used approaches (by weight), the stages the approach's users have rows in, its works and
    candidate `derives-from` edges."""
    _positive("min_works", min_works)
    return build_neighbors(
        read_inputs(project), approach_id, Lens(layer=layer), min_works=min_works, limit=limit
    )


def _check_stage(inputs: Inputs, name: str, stage: str) -> None:
    if stage not in {s.stage for s in inputs.stages}:
        raise _refuse(name, "unknown stage")


def technique_gaps(
    project: Project,
    *,
    from_stage: str,
    to_stage: str,
    min_works: int = 3,
    max_to_share: float = 0.0,
    layer: str = "core",
    limit: int | None = 100,
) -> Candidates:
    """Hypotheses to check: approaches well used at `from_stage` whose users show none (at most
    `max_to_share`) at `to_stage`. Cross-stage duplicates stay two nodes."""
    _positive("min_works", min_works)
    if not 0.0 <= max_to_share <= 1.0:
        raise _refuse("max_to_share", "must be between 0 and 1")
    inputs = read_inputs(project)
    _check_stage(inputs, "from_stage", from_stage)
    _check_stage(inputs, "to_stage", to_stage)
    return build_gaps(
        inputs,
        Lens(layer=layer),
        from_stage=from_stage,
        to_stage=to_stage,
        min_works=min_works,
        max_to_share=max_to_share,
        limit=limit,
    )


def technique_combinations(
    project: Project,
    *,
    min_works: int = 3,
    max_co_works: int = 0,
    stage: str | None = None,
    layer: str = "core",
    limit: int | None = 100,
) -> Candidates:
    """Hypotheses to check: pairs of approaches each used by at least `min_works` works and used
    together by at most `max_co_works`."""
    _positive("min_works", min_works)
    if max_co_works < 0:
        raise _refuse("max_co_works", "must not be negative")
    inputs = read_inputs(project)
    if stage is not None:
        _check_stage(inputs, "stage", stage)
    return build_combinations(
        inputs,
        Lens(layer=layer),
        min_works=min_works,
        max_co_works=max_co_works,
        stage=stage,
        limit=limit,
    )


def technique_challenges(
    project: Project, *, layer: str = "core", limit: int | None = 100
) -> Candidates:
    """Hypotheses to check: approaches reported as failing in one work and supported in another."""
    return build_challenges(read_inputs(project), Lens(layer=layer), limit=limit)
