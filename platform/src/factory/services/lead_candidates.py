"""Lead candidates: observations from the technique landscape and the `m-claims` limitation rows,
each with the exact triggers a `lead_record` call accepts (job J2, task 1; hypothesis engine).

Invariants:
- Read-only and deterministic: nothing is written, no model is called, the same index gives the
  same candidates in the same order. A candidate is an observation, never a lead, and its wording
  never claims novelty ("not co-used in this corpus (exploratory, pass-A rows)").
- Every result is labelled exploratory (class interpretation, notice), as the technique models.
- Triggers are `item` (the `ext_` id of a LIVE, non-stale pass-A miner row) and `work`; never `row`
  (a miner row's `rk_` key does not resolve as a trigger: only an evidence cell does). At most 20
  per candidate: one best-quote row per cited work (not a `reused-cited` row when another exists,
  then an anchored one), at most ten works, the cut stated in `trigger_note`.
- Technique candidates call the pure `build_*` functions of `technique_graph` once, on one
  `read_inputs`. Claims candidates read the `m-claims` rows directly (`live_rows`) because the
  claims digest exposes only `rk_` keys: a `limitation`, `negative-result` or `failure-analysis`
  row is a candidate (order of `CLAIM_ORDER`); `no-limitation-stated` rows are only counted
  (`absence_only_works`), never a trigger; the researcher's gold rows have no `ext_` and are not
  read. Rows are those of the scope, whichever miner version, in the miner's production
  population, not stale.
- Held-out: nothing is masked in the service (decision 37 item 9), as the technique services; the
  MCP wrapper scrubs stated identifiers.
- The memo of the claims rows is keyed by the last folded event; no index lock is held across the
  scan, and concurrent misses share one scan.
"""

from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.extraction import MinerScope
from factory.model.lead_engine import (
    MAX_TRIGGERS_PER_CANDIDATE,
    SOURCES,
    BasisRow,
    Candidate,
    CandidateQuote,
    Candidates,
    CandidateTrigger,
    CandidateWork,
    Skipped,
)
from factory.model.screening import PassLabel
from factory.model.technique_graph import SUPPORTIVE, GapCandidate, Lens
from factory.services import lead_cache
from factory.services import technique_graph as tg
from factory.services.call_memo import entering
from factory.services.claims_digest import ABSENCE_TYPE, CLAIM_ORDER
from factory.services.context import Project
from factory.services.extraction import live_rows, stale_extractions
from factory.services.mining import miner_population
from factory.services.paper_profile import listed_miner_versions
from factory.services.search import works_by_ids
from factory.services.work_layers import layers_for

__all__ = ["CLAIMS_MINER", "LIMITATION_TYPES", "lead_candidates"]

CLAIMS_MINER = "m-claims"
LIMITATION_TYPES = ("limitation", "negative-result", "failure-analysis")
"""The claim types that state a limitation; the order of `CLAIM_ORDER` is kept."""
MAX_CITED_WORKS = 10
"""Works a candidate cites: one `item` and one `work` trigger each, so 20 triggers at most."""
OTHER_STAGE = "other"
"""The residual stage of the technique miners: never a gap's target (it fits no stage)."""
CHALLENGE_FLAG = "failure-quote-not-checked"
T = TypeVar("T")


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


# --- memo of the claims rows ----------------------------------------------------------------


@dataclass(frozen=True)
class _ClaimRow:
    extraction_id: str
    work_id: str
    row_key: str
    claim_type: str
    about: str
    quote: str | None
    anchor: str | None
    layer: str | None
    has_quote_field: bool = True


@dataclass(frozen=True)
class _Claims:
    version: int | None
    rows: tuple[_ClaimRow, ...]
    titles: dict[str, str]
    absence_only: dict[str, str | None]


_CACHE: dict[str, tuple[str | None, _Claims]] = {}
_GUARD = threading.Lock()
_KEY_LOCKS: dict[str, threading.Lock] = {}
_CACHE_MAX = 4


def _stable(project: Project, build: Callable[[], T]) -> tuple[T, str | None]:
    """`build` (short reads, no lock held across them) with the event id it is consistent with; if
    events arrive during the scan it is run once more, and if they still arrive the id before the
    last run is returned, so the memo entry is stale at once."""
    before = project.index.last_event_id()
    result = build()
    if project.index.last_event_id() != before:
        before = project.index.last_event_id()
        result = build()
    return result, before


def _field_text(fields: Mapping[str, Any], name: str) -> str:
    entry = fields.get(name)
    return "" if entry is None else str(getattr(entry, "value", "")).strip()


def _read_claims(project: Project) -> _Claims:
    scope = MinerScope(CLAIMS_MINER)
    version = dict(listed_miner_versions(project)).get(CLAIMS_MINER)
    if version is None:
        return _Claims(None, (), {}, {})
    with entering():  # short per-call reads: a snapshot would block writers for the scan
        keep = set(miner_population(project, CLAIMS_MINER))
        stale = stale_extractions(project, scope=scope)
        mined = [
            r
            for r in live_rows(project, PassLabel.A, scope=scope)
            if r.extraction_id not in stale and r.work_id in keep
        ]
        ids = sorted({r.work_id for r in mined})
        layers = layers_for(project, ids)
        titles = {w.id: w.title for w in works_by_ids(project, ids)}
    rows: list[_ClaimRow] = []
    types: dict[str, set[str]] = defaultdict(set)
    for r in mined:
        kind = _field_text(r.fields, "claim_type")
        types[r.work_id].add(kind)
        quote_field = r.fields.get("claim_quote")
        quote = None
        if quote_field is not None:  # the field `value` is never taken for a quote
            quote = (quote_field.quote or "").strip() or None
        rows.append(
            _ClaimRow(
                extraction_id=r.extraction_id,
                work_id=r.work_id,
                row_key=r.row_key,
                claim_type=kind,
                about=_field_text(r.fields, "about"),
                quote=quote,
                anchor=None if quote_field is None else quote_field.anchor,
                layer=layers[r.work_id].layer if r.work_id in layers else None,
                has_quote_field=quote_field is not None,
            )
        )
    absence = {
        w: (layers[w].layer if w in layers else None)
        for w, kinds in types.items()
        if kinds == {ABSENCE_TYPE}
    }
    rows.sort(key=lambda c: (c.work_id, c.row_key, c.extraction_id))
    return _Claims(version, tuple(rows), titles, absence)


def _claims_data(project: Project) -> _Claims:
    project.index.sync()
    key = str(project.paths.dir)
    with _GUARD:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == project.index.last_event_id():
            return hit[1]
        lock = _KEY_LOCKS.setdefault(key, threading.Lock())
    with lock:
        with _GUARD:
            hit = _CACHE.get(key)
            if hit is not None and hit[0] == project.index.last_event_id():
                return hit[1]
        data, built = _stable(project, lambda: _read_claims(project))
        with _GUARD:
            _CACHE.pop(key, None)
            while len(_CACHE) >= _CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)), None)
            _CACHE[key] = (built, data)
        return data


# --- picking the cited rows -----------------------------------------------------------------


def _quality(row: tg.RawRow) -> tuple[bool, bool, bool, str, str]:
    """Best first: not a `reused-cited` row, supportive evidence, an anchor, then ids."""
    return (
        row.status == tg.REUSED,
        row.evidence not in SUPPORTIVE,
        row.anchor is None,
        row.work_id,
        row.extraction_id,
    )


def _best_per_work(rows: Collection[tg.RawRow]) -> list[tg.RawRow]:
    """The best quoted row of each work, best first (a work with no quoted row has none)."""
    best: dict[str, tg.RawRow] = {}
    for row in sorted(rows, key=_quality):
        if row.quote and row.work_id not in best:
            best[row.work_id] = row
    return sorted(best.values(), key=_quality)


def _round_robin(
    sides: Sequence[tuple[str, Sequence[tg.RawRow]]], cap: int
) -> list[tuple[str, tg.RawRow]]:
    """Up to `cap` (role, row) picks, one work once, alternating between the sides so that each
    side with a quoted row is cited before any side cites a second."""
    pools = [(role, list(_best_per_work(rows))) for role, rows in sides]
    chosen: list[tuple[str, tg.RawRow]] = []
    seen: set[str] = set()
    while len(chosen) < cap and any(pool for _, pool in pools):
        for role, pool in pools:
            while pool and pool[0].work_id in seen:
                pool.pop(0)
            if pool and len(chosen) < cap:
                row = pool.pop(0)
                seen.add(row.work_id)
                chosen.append((role, row))
    return chosen


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _assemble(
    inputs: tg.Inputs,
    *,
    source: str,
    key: str,
    observation: str,
    approaches: tuple[str, ...],
    sides: Sequence[tuple[str, Sequence[tg.RawRow]]],
    works_total: int,
    miners: tuple[str, ...],
    overlap: int | None,
    score: float | None,
    flags: tuple[str, ...] = (),
    target_stages: tuple[str, ...] = (),
    side_of: Mapping[str, str] | None = None,
) -> Candidate | None:
    """The candidate citing the best quoted row of up to `MAX_CITED_WORKS` works; every cited row
    is quoted, with its side (`side_of[role]`, the approach it supports), what the row calls the
    approach and its evidence class."""
    picks = _round_robin(sides, MAX_CITED_WORKS)
    if not picks:
        return None
    total_cited_pool = {r.work_id for _, rows in sides for r in rows if r.quote}
    works = tuple(
        CandidateWork(work_id=r.work_id, title=inputs.works[r.work_id].title) for _, r in picks
    )
    triggers = tuple(CandidateTrigger(kind="item", ref=r.extraction_id) for _, r in picks) + tuple(
        CandidateTrigger(kind="work", ref=r.work_id) for _, r in picks
    )
    note = None
    if len(picks) < len(total_cited_pool):
        note = (
            f"triggers cover {len(picks)} of {len(total_cited_pool)} works with a quoted row "
            "(best quote per work, sides alternating); the others are counted in works_total"
        )
    return Candidate(
        candidate_id=f"{source}:{key}",
        source=source,
        observation=observation,
        approaches=approaches,
        works=works,
        works_total=works_total,
        quotes=tuple(
            CandidateQuote(
                role=role,
                work_id=r.work_id,
                extraction_id=r.extraction_id,
                quote=r.quote or "",
                anchor=r.anchor,
                side=None if side_of is None else side_of.get(role),
                described_as=r.described_as,
                evidence=r.evidence,
            )
            for role, r in picks
        ),
        triggers=triggers[:MAX_TRIGGERS_PER_CANDIDATE],
        basis=tuple(
            BasisRow(extraction_id=r.extraction_id, work_id=r.work_id, role=role)
            for role, r in picks
        ),
        trigger_note=note,
        target_stages=target_stages,
        miners=miners,
        overlap_works=overlap,
        score=score,
        flags=flags,
    )


# --- technique sources (pure over Inputs) ---------------------------------------------------


def technique_candidates(
    inputs: tg.Inputs,
    *,
    sources: Collection[str],
    per_source: int,
    layer: str,
    min_works: int,
    max_co_works: int,
) -> tuple[list[Candidate], dict[str, int]]:
    """The technique candidates of `sources` from one `Inputs` (see the module invariants) and the
    number each source produced before `per_source`. Pure."""
    lens = Lens(layer=layer)
    rows = [r for r in inputs.rows if layer == "all" or inputs.works[r.work_id].layer == layer]
    by_approach: dict[str, list[tg.RawRow]] = defaultdict(list)
    for r in rows:
        by_approach[r.approach].append(r)
    miners = tuple(f"{s.miner} v{s.version}" for s in inputs.stages)
    out: list[Candidate] = []
    totals: dict[str, int] = {}

    def name(approach: str) -> str:
        stage, label, _ = inputs.catalogue[approach]
        return f"{label} ({approach}, {stage})"

    if "technique-challenge" in sources:
        found = tg.build_challenges(inputs, lens, limit=per_source)
        totals["technique-challenge"] = found.total
        for c in found.challenges:
            fw = {u.work_id for u in c.failed}
            sw = {u.work_id for u in c.supported}
            mine = by_approach[c.approach.id]
            cand = _assemble(
                inputs,
                source="technique-challenge",
                key=c.approach.id,
                observation=(
                    f"{name(c.approach.id)}: reported as failing by {len(fw)} work(s) and "
                    f"supported by {len(sw)} work(s) in this corpus (exploratory, pass-A rows); "
                    "the settings may differ"
                ),
                approaches=(c.approach.id,),
                sides=(
                    ("failed", [r for r in mine if r.evidence == "reported-failure"]),
                    ("supported", [r for r in mine if r.evidence in SUPPORTIVE]),
                ),
                works_total=len(fw | sw),
                miners=miners,
                overlap=len(fw & sw),
                score=None,
                flags=(CHALLENGE_FLAG,),
                side_of={"failed": c.approach.id, "supported": c.approach.id},
            )
            if cand is not None:
                out.append(cand)
    if "technique-combination" in sources:
        combos = tg.build_combinations(
            inputs,
            lens,
            min_works=min_works,
            max_co_works=max_co_works,
            stage=None,
            limit=per_source,
            top=per_source,
        )
        totals["technique-combination"] = combos.total
        for k in combos.combinations:
            a, b = k.a.id, k.b.id
            cand = _assemble(
                inputs,
                source="technique-combination",
                key=f"{a}+{b}",
                observation=k.statement,
                approaches=(a, b),
                sides=(("a", by_approach[a]), ("b", by_approach[b])),
                works_total=k.works_a + k.works_b - len(k.co_works),
                miners=miners,
                overlap=len(k.co_works),
                score=None if k.score is None else k.score.composite,
                side_of={"a": a, "b": b},
            )
            if cand is not None:
                out.append(cand)
    if "technique-gap" in sources:
        stages = sorted({s.stage for s in inputs.stages})
        # one candidate per approach: every target stage no user of it has a row at (a target
        # stage is never `other`), the best composite over the targets
        found_by: dict[str, list[tuple[str, GapCandidate]]] = defaultdict(list)
        for from_stage in stages:
            for to_stage in stages:
                if from_stage == to_stage or to_stage == OTHER_STAGE:
                    continue
                gap_found = tg.build_gaps(
                    inputs,
                    lens,
                    from_stage=from_stage,
                    to_stage=to_stage,
                    min_works=min_works,
                    max_to_share=0.0,
                    limit=None,
                    top=None,
                )
                for g in gap_found.gaps:
                    found_by[g.approach.id].append((to_stage, g))
        gaps: list[tuple[float, str, Candidate]] = []
        for approach, targets in sorted(found_by.items()):
            first = targets[0][1]
            users = {w for _, g in targets for w in g.works}
            from_stage = first.from_stage
            mine = [
                r for r in by_approach[approach] if r.stage == from_stage and r.work_id in users
            ]
            to_stages = tuple(sorted({t for t, _ in targets}))
            scores = [g.score.composite for _, g in targets if g.score is not None]
            best = max(scores) if scores else None
            cand = _assemble(
                inputs,
                source="technique-gap",
                key=approach,
                observation=(
                    f"{name(approach)} is used by {len(users)} work(s) at {from_stage}; no user "
                    f"has a row at {', '.join(to_stages)} in this corpus (exploratory, pass-A "
                    f"rows); best composite {best:.3f}"
                    if best is not None
                    else f"{name(approach)} is used by {len(users)} work(s) at {from_stage}; "
                    f"no user has a row at {', '.join(to_stages)} in this corpus "
                    "(exploratory, pass-A rows)"
                ),
                approaches=(approach,),
                sides=(("from-stage", mine),),
                works_total=len(users),
                miners=miners,
                overlap=0,
                score=best,
                target_stages=to_stages,
                side_of={"from-stage": approach},
            )
            if cand is not None:
                gaps.append((-(cand.score or 0.0), approach, cand))
        totals["technique-gap"] = len(found_by)
        gaps.sort(key=lambda t: t[:2])
        out.extend(t[2] for t in gaps[:per_source])
    return out, totals


# --- claims source --------------------------------------------------------------------------


def claims_candidates(
    data: _Claims, *, per_source: int, layer: str
) -> tuple[list[Candidate], int, list[Skipped]]:
    """The limitation rows of `data` as candidates (see the module invariants), the number before
    `per_source`, and the rows left out with why. Pure."""
    chosen = [
        c
        for c in data.rows
        if c.claim_type in LIMITATION_TYPES and (layer == "all" or c.layer == layer)
    ]

    def order(c: _ClaimRow) -> tuple[int, str, str, str]:
        return (CLAIM_ORDER.index(c.claim_type), c.work_id, c.row_key, c.extraction_id)

    chosen.sort(key=order)
    out: list[Candidate] = []
    skipped: list[Skipped] = []
    for c in chosen[:per_source]:
        cid = f"claims-limitation:{c.extraction_id}"
        if not c.has_quote_field:
            skipped.append(Skipped(candidate_id=cid, reason="no-quote"))
            continue
        title = data.titles.get(c.work_id, c.work_id)
        about = f' about "{c.about}"' if c.about else ""
        out.append(
            Candidate(
                candidate_id=cid,
                source="claims-limitation",
                observation=(
                    f"{title}: an m-claims pass-A row states a {c.claim_type}{about} "
                    "(exploratory, pass-A row; one paper's statement, not a corpus finding)"
                ),
                works=(CandidateWork(work_id=c.work_id, title=title),),
                works_total=1,
                quotes=(
                    CandidateQuote(
                        role="limitation",
                        work_id=c.work_id,
                        extraction_id=c.extraction_id,
                        quote=c.quote,
                        anchor=c.anchor,
                    ),
                ),
                flags=() if c.quote is not None else ("no-stored-quote",),
                triggers=(
                    CandidateTrigger(kind="item", ref=c.extraction_id),
                    CandidateTrigger(kind="work", ref=c.work_id),
                ),
                basis=(
                    BasisRow(extraction_id=c.extraction_id, work_id=c.work_id, role="limitation"),
                ),
                miners=(f"{CLAIMS_MINER} v{data.version}",),
            )
        )
    return out, len(chosen), skipped


# --- public API -----------------------------------------------------------------------------


def lead_candidates(
    project: Project,
    *,
    sources: Sequence[str] = SOURCES,
    per_source: int = 20,
    layer: str = "core",
    technique_min_works: int = 3,
    max_co_works: int = 0,
    refresh: bool = False,
) -> Candidates:
    """Observations to check, with the exact triggers a `lead_record` call accepts (see the module
    invariants). Every parameter is a runtime knob: `sources` (any of `SOURCES`), `per_source` (a
    cap per source, at least 1), `layer` (a work layer id or `all`), `technique_min_works` (works
    each approach of a combination or gap needs) and `max_co_works` (works that may already use
    both approaches of a combination). Refused with nothing computed: an unknown source or a
    non-positive number (the field named). The result is cached on disk (`lead_cache`: derived,
    keyed by the last event, the code and these parameters); `refresh` drops the cache first."""
    unknown = sorted(set(sources) - set(SOURCES))
    if unknown or not sources:
        raise _refuse("sources", f"one or more of {', '.join(SOURCES)}: unknown {unknown}")
    if isinstance(per_source, bool) or per_source < 1:
        raise _refuse("per_source", "must be at least 1")
    if technique_min_works < 1:
        raise _refuse("technique_min_works", "must be at least 1")
    if max_co_works < 0:
        raise _refuse("max_co_works", "must not be negative")
    cache = lead_cache.slot(
        project,
        lead_cache.candidate_params(
            sources=sources,
            per_source=per_source,
            layer=layer,
            min_works=technique_min_works,
            max_co_works=max_co_works,
        ),
        refresh=refresh,
    )
    if (hit := cache.get()) is not None:
        return hit
    wanted = set(sources)
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    totals: dict[str, int] = {}
    miners: list[str] = []
    absence_only = 0
    if wanted & {"technique-challenge", "technique-combination", "technique-gap"}:
        inputs = tg.read_inputs(project)
        found, totals = technique_candidates(
            inputs,
            sources=wanted,
            per_source=per_source,
            layer=layer,
            min_works=technique_min_works,
            max_co_works=max_co_works,
        )
        candidates.extend(found)
        miners.extend(f"{s.miner} v{s.version}" for s in inputs.stages)
    if "claims-limitation" in wanted:
        data = _claims_data(project)
        if data.version is None:
            skipped.append(
                Skipped(candidate_id="claims-limitation", reason="m-claims is not listed")
            )
            totals["claims-limitation"] = 0
        else:
            found_claims, total, left = claims_candidates(data, per_source=per_source, layer=layer)
            candidates.extend(found_claims)
            skipped.extend(left)
            totals["claims-limitation"] = total
            miners.append(f"{CLAIMS_MINER} v{data.version}")
            absence_only = sum(
                1 for layer_of in data.absence_only.values() if layer in ("all", layer_of)
            )
    order = {s: i for i, s in enumerate(SOURCES)}
    candidates.sort(key=lambda c: order[c.source])  # stable: each source keeps its own order
    return cache.put(
        Candidates(
            parameters={
                "sources": tuple(sorted(wanted, key=order.__getitem__)),
                "per_source": per_source,
                "layer": layer,
                "technique_min_works": technique_min_works,
                "max_co_works": max_co_works,
            },
            totals={s: totals[s] for s in SOURCES if s in totals},
            candidates=tuple(candidates),
            skipped=tuple(skipped),
            miners=tuple(miners),
            absence_only_works=absence_only,
        )
    )
