"""The lead queue: candidates and open leads ordered by computed measures (job J2, task 2).

The platform computes measures from recorded rows and orders by a fixed, printed rule; it never
decides which observation is better. Invariants:
- Read-only and deterministic: nothing is written, no model is called; the same index and the
  same parameters give the same queue. Every result is labelled exploratory.
- The order is lexicographic over `order_by` (any sequence of `MEASURES`; the default is
  `DEFAULT_ORDER`), each measure with its printed direction, after one fixed rule: an entry whose
  rows are not all live is flagged and sorted last, never dropped. Ties break by entry id. A
  measure is comparable only with the others of the same call.
- M1 support: works the observation counts (a lead: works behind its triggers). M2 independence:
  distinct works cited by the triggers (distinct works only; no venue or citation reading).
  M3 verification: cited `item` rows whose quote is verbatim in the row's pinned conversion
  (`chat_verify`), over all cited `item` rows. M4 supportive share: cited technique rows with
  supportive evidence over cited technique rows (None without one). M5 overlap: works whose rows
  already state the observation (None for claims and leads). M6 diversity against the promoted
  leads: 1 minus the largest Jaccard of item ids and approaches, shared works never counting.
  M7 prior hits: parked or discarded leads, hypotheses (through their lead) and directions that
  share a trigger key, every collision reported with the shared items and works. M8 score: the
  technique rank composite, 0 with a flag where none exists. M9 basis: every cited row recomputed
  live now (`live`, `stale`, `superseded`, `unknown`).
- Reads are SQL on the lead, key, direction and extraction tables, once per call; no `prior_for`
  per candidate, no index lock held across a scan.
- Held-out: nothing is masked in the service (decision 37 item 9); the tool layer scrubs.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.extraction import MinerScope, Scope, ScopeKey
from factory.model.lead_engine import (
    DEFAULT_ORDER,
    MEASURES,
    SOURCES,
    Candidate,
    Candidates,
    Measures,
    PriorHit,
    Queue,
    QueueItem,
    Skipped,
    Verification,
)
from factory.model.technique_graph import SUPPORTIVE
from factory.services.chat_read import VerifyItem, chat_verify
from factory.services.context import Project
from factory.services.extraction import stale_extractions
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_stats import scope_source

__all__ = ["DEFAULT_ORDER", "lead_queue"]

_DIRECTION = {
    "support": "descending",
    "independence": "descending",
    "verification": "descending",
    "supportive_share": "descending",
    "overlap": "ascending",
    "diversity": "descending",
    "prior_hits": "ascending",
    "score": "descending",
    "basis": "live first",
}
_QUOTE_FIELDS = ("quote", "claim_quote")
_COMPARABILITY = (
    "measures and their order are comparable only within this call: they are computed from this "
    "corpus, these sources and these parameters, and say nothing across runs or projects"
)
_BATCH = 5000
_VERIFIED: dict[tuple[str, str], bool] = {}
_VERIFIED_MAX = 50000
_GUARD = threading.Lock()
"""Verification of one row's quote never changes (the row and its pinned conversion are
immutable), so it is memoised per project and extraction id."""


def _refuse(field_: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, reason)])


@dataclass(frozen=True)
class _Item:
    scope: str
    work_id: str
    conversion_id: str
    superseded: bool
    category: str | None
    evidence: str | None
    quote: str | None
    anchor: str | None


@dataclass
class _Subject:
    """What is measured: a candidate or a lead, reduced to its cited rows and works."""

    entry_id: str
    kind: str
    source: str
    items: tuple[str, ...]
    works: tuple[str, ...]
    works_total: int | None = None
    overlap: int | None = None
    score: float | None = None
    candidate: Candidate | None = None
    flags: list[str] = field(default_factory=list)


def _json_ids(values: Iterable[str]) -> list[str]:
    return [json.dumps(chunk) for chunk in _chunks(sorted(set(values)))]


def _chunks(values: Sequence[str]) -> list[list[str]]:
    return [list(values[i : i + _BATCH]) for i in range(0, len(values), _BATCH)]


# --- reads ----------------------------------------------------------------------------------


def _items(project: Project, ids: Collection[str]) -> dict[str, _Item]:
    """The rows named by `ids` with what the measures read of them; an id of no row is absent."""
    found: dict[str, _Item] = {}
    with project.index.connect() as conn:
        for blob in _json_ids(ids):
            heads = conn.execute(
                text(
                    "SELECT extraction_id, scope, work_id, conversion_id, superseded_by "
                    "FROM extraction_rows WHERE extraction_id IN "
                    "(SELECT value FROM json_each(:ids))"
                ),
                {"ids": blob},
            ).all()
            cells = conn.execute(
                text(
                    "SELECT extraction_id, field, value, quote, anchor FROM extraction_fields "
                    "WHERE extraction_id IN (SELECT value FROM json_each(:ids)) "
                    "ORDER BY extraction_id, field"
                ),
                {"ids": blob},
            ).all()
            by_row: dict[str, list[tuple[str, str, str | None, str | None]]] = defaultdict(list)
            for ext, name, value, quote, anchor in cells:
                by_row[str(ext)].append((str(name), str(value), quote, anchor))
            for ext, scope, work, conversion, superseded in heads:
                fields = by_row[str(ext)]
                by_name = {n: (v, q, a) for n, v, q, a in fields}
                chosen = next((by_name[n] for n in _QUOTE_FIELDS if n in by_name), None)
                if chosen is None:
                    chosen = next(((v, q, a) for _, v, q, a in fields if q), None)
                quote = None if chosen is None else (chosen[1] or chosen[0]).strip() or None
                category = by_name.get("category")
                evidence = by_name.get("evidence")
                found[str(ext)] = _Item(
                    scope=str(scope),
                    work_id=str(work),
                    conversion_id=str(conversion),
                    superseded=superseded is not None,
                    category=None if category is None else category[0].split("/", 1)[-1],
                    evidence=None if evidence is None else evidence[0].strip(),
                    quote=quote,
                    anchor=None if chosen is None or chosen[2] is None else str(chosen[2]),
                )
    return found


def _scope_key(name: str) -> ScopeKey:
    return Scope(name) if name in {s.value for s in Scope} else MinerScope(name)


_STALE: dict[tuple[str, str], tuple[str | None, frozenset[str]]] = {}
_STALE_MAX = 64
"""Stale rows per project and scope, keyed by the last folded event: the ledger is the slowest
read of a call (seconds per scope on the pilot)."""


def _stale(project: Project, scope: str) -> frozenset[str]:
    key = (str(project.paths.dir), scope)
    head = project.index.last_event_id()
    with _GUARD:
        hit = _STALE.get(key)
        if hit is not None and hit[0] == head:
            return hit[1]
    found = frozenset(stale_extractions(project, scope=_scope_key(scope)))
    with _GUARD:
        if len(_STALE) >= _STALE_MAX:
            _STALE.clear()
        _STALE[key] = (head, found)
    return found


def _basis(project: Project, items: dict[str, _Item]) -> dict[str, str]:
    """`ext id -> live | stale | superseded` for the known rows, from the tables and the stale
    ledger of each scope involved (one ledger per scope, memoised per last folded event)."""
    stale = {scope: _stale(project, scope) for scope in sorted({i.scope for i in items.values()})}
    return {
        ext: "superseded" if i.superseded else "stale" if ext in stale[i.scope] else "live"
        for ext, i in items.items()
    }


def _verify(project: Project, items: dict[str, _Item]) -> dict[str, bool]:
    key = str(project.paths.dir)
    out: dict[str, bool] = {}
    todo: list[tuple[str, _Item]] = []
    with _GUARD:
        for ext, item in items.items():
            if item.quote is None or item.anchor is None:
                out[ext] = False
            elif (key, ext) in _VERIFIED:
                out[ext] = _VERIFIED[(key, ext)]
            else:
                todo.append((ext, item))
    if todo:
        results = chat_verify(
            project,
            [
                VerifyItem(i.work_id, i.anchor or "", i.quote or "", i.conversion_id)
                for _, i in todo
            ],
        )
        with _GUARD:
            for (ext, _), res in zip(todo, results, strict=True):
                out[ext] = res.status == "accepted"
                if len(_VERIFIED) >= _VERIFIED_MAX:
                    _VERIFIED.clear()
                _VERIFIED[(key, ext)] = out[ext]
    return out


def _lead_rows(project: Project, state: str) -> list[tuple[str, str | None, str]]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT lead_id, framework, event_id FROM leads WHERE state = :s ORDER BY lead_id"
            ),
            {"s": state},
        ).all()
    return [(str(a), None if b is None else str(b), str(c)) for a, b, c in rows]


def _lead_triggers(project: Project, lead_ids: Collection[str]) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with project.index.connect() as conn:
        for blob in _json_ids(lead_ids):
            rows = conn.execute(
                text(
                    "SELECT lead_id, kind, ref FROM lead_triggers WHERE lead_id IN "
                    "(SELECT value FROM json_each(:ids)) ORDER BY lead_id, kind, ref"
                ),
                {"ids": blob},
            ).all()
            for lead, kind, ref in rows:
                out[str(lead)].append((str(kind), str(ref)))
    return out


def _prior_rows(
    project: Project, keys: Collection[str]
) -> tuple[
    list[tuple[str, str, str, str | None]],
    list[tuple[str, str, str]],
    list[tuple[str, str, str, str]],
]:
    """`(key, lead id, state, reason)` of parked and discarded leads; `(key, hypothesis id, lead)`
    of hypotheses through their lead's keys; `(key, direction id, source kind, reason)` of the
    directions, for the given trigger keys."""
    leads: list[tuple[str, str, str, str | None]] = []
    hyps: list[tuple[str, str, str]] = []
    dirs: list[tuple[str, str, str, str]] = []
    with project.index.connect() as conn:
        for blob in _json_ids(keys):
            for key, lead, state, reason in conn.execute(
                text(
                    "SELECT k.key, l.lead_id, l.state, l.reason FROM lead_keys k JOIN leads l "
                    "ON l.lead_id = k.lead_id WHERE l.state IN ('parked', 'discarded') "
                    "AND k.key IN (SELECT value FROM json_each(:ids))"
                ),
                {"ids": blob},
            ):
                leads.append(
                    (str(key), str(lead), str(state), None if reason is None else str(reason))
                )
            for key, hyp, lead in conn.execute(
                text(
                    "SELECT k.key, h.hypothesis_id, h.lead FROM hypotheses h JOIN lead_keys k "
                    "ON k.lead_id = h.lead WHERE k.key IN (SELECT value FROM json_each(:ids))"
                ),
                {"ids": blob},
            ):
                hyps.append((str(key), str(hyp), str(lead)))
            for key, direction, kind, reason in conn.execute(
                text(
                    "SELECT k.key, d.direction_id, d.source_kind, d.reason FROM direction_keys k "
                    "JOIN directions d ON d.direction_id = k.direction_id "
                    "WHERE k.key IN (SELECT value FROM json_each(:ids))"
                ),
                {"ids": blob},
            ):
                dirs.append((str(key), str(direction), str(kind), str(reason)))
    return leads, hyps, dirs


# --- measures -------------------------------------------------------------------------------


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _hits(
    subject: _Subject,
    leads: list[tuple[str, str, str, str | None]],
    hyps: list[tuple[str, str, str]],
    dirs: list[tuple[str, str, str, str]],
) -> tuple[tuple[PriorHit, ...], bool]:
    mine = set(subject.items) | set(subject.works)
    shared: dict[tuple[str, str], set[str]] = defaultdict(set)
    detail: dict[tuple[str, str], str | None] = {}
    closed = False
    for key, lead, state, reason in leads:
        if key in mine and lead != subject.entry_id:
            shared[("lead", lead)].add(key)
            detail[("lead", lead)] = state if reason is None else f"{state}: {reason}"
    for key, hyp, lead in hyps:
        if key in mine and lead != subject.entry_id:
            shared[("hypothesis", hyp)].add(key)
            detail[("hypothesis", hyp)] = f"drafted from lead {lead}"
    for key, direction, kind, reason in dirs:
        if key in mine:
            shared[("direction", direction)].add(key)
            detail[("direction", direction)] = f"{kind}: {reason}"
            closed = closed or kind == "closed"
    hits = tuple(
        PriorHit(
            kind=kind,
            id=ident,
            detail=detail[(kind, ident)],
            shared_items=tuple(sorted(k for k in keys if k.startswith("ext_"))),
            shared_works=tuple(sorted(k for k in keys if not k.startswith("ext_"))),
        )
        for (kind, ident), keys in sorted(shared.items())
    )
    return hits, closed


def _sort_key(item: QueueItem, order_by: Sequence[str]) -> tuple[object, ...]:
    m = item.measures
    parts: dict[str, tuple[object, ...]] = {
        "support": (-m.support,),
        "independence": (-m.independence,),
        "verification": (-(m.verification.share or 0.0),),
        "supportive_share": (-(m.supportive_share or 0.0),),
        "overlap": (m.overlap or 0,),
        "diversity": (-m.diversity,),
        "prior_hits": (m.closed_direction_hit, m.narrow_prior_hits, m.prior_hits),
        "score": (-m.score,),
        "basis": (),
    }
    key: list[object] = [m.basis != "live"]
    for name in order_by:
        key.extend(parts[name])
    key.append(item.entry_id)
    return tuple(key)


def _rule(order_by: Sequence[str]) -> str:
    steps = ", ".join(f"{n} ({_DIRECTION[n]})" for n in order_by)
    return (
        "an entry with a row that is not live sorts last, whatever the order; then, in turn: "
        f"{steps}; ties by entry id"
    )


def _balanced(ordered: list[QueueItem], quota: int, top: int) -> list[QueueItem]:
    """The first `quota` of each source in `ordered`, in `ordered`'s order, cut to `top` by
    dropping from the global tail the entries that are not their source's first."""
    seen: dict[str, int] = defaultdict(int)
    kept: list[tuple[QueueItem, int]] = []
    for m in ordered:
        seen[m.source] += 1
        if seen[m.source] <= quota:
            kept.append((m, seen[m.source]))
    while len(kept) > top:
        drop = next((i for i in range(len(kept) - 1, -1, -1) if kept[i][1] > 1), len(kept) - 1)
        del kept[drop]
    return [m for m, _ in kept]


def _check(
    order_by: Sequence[str],
    top: int,
    per_source: int,
    per_source_top: int | None = None,
    balance: bool = True,
) -> None:
    unknown = [n for n in order_by if n not in MEASURES]
    if not order_by or unknown:
        raise _refuse("order_by", f"measures: {', '.join(MEASURES)}; unknown {unknown}")
    if isinstance(top, bool) or top < 1:
        raise _refuse("top", "must be at least 1")
    if per_source < 1:
        raise _refuse("per_source", "must be at least 1")
    if per_source_top is not None and (isinstance(per_source_top, bool) or per_source_top < 1):
        raise _refuse("per_source_top", "must be at least 1")
    if per_source_top is not None and not balance:
        raise _refuse("per_source_top", "applies only with balance=True")


def _sources_of(found: Candidates) -> tuple[str, ...]:
    named = found.parameters.get("sources", ())
    return tuple(named) if isinstance(named, tuple) else ()


def _subject_of(candidate: Candidate) -> _Subject:
    return _Subject(
        entry_id=candidate.candidate_id,
        kind="candidate",
        source=candidate.source,
        items=tuple(t.ref for t in candidate.triggers if t.kind == "item"),
        works=tuple(t.ref for t in candidate.triggers if t.kind == "work"),
        works_total=candidate.works_total,
        overlap=candidate.overlap_works,
        score=candidate.score,
        candidate=candidate,
    )


def lead_queue(
    project: Project,
    *,
    candidates: Candidates | None = None,
    order_by: Sequence[str] = DEFAULT_ORDER,
    sources: Sequence[str] = SOURCES,
    top: int = 50,
    exclude_prior: bool = False,
    per_source: int = 20,
    layer: str = "core",
    technique_min_works: int = 3,
    max_co_works: int = 0,
    include_leads: bool = True,
    balance: bool = True,
    per_source_top: int | None = None,
) -> Queue:
    """Candidates (`candidates`, else `lead_candidates` with the same `sources`, `per_source`,
    `layer`, `technique_min_works` and `max_co_works`) and, with `include_leads`, the open
    leads, each with its measures, ordered by `order_by` (see the module invariants); at most
    `top` of each are returned, `total_candidates` is before that. With `exclude_prior` a
    candidate with any prior hit is left out and listed in `excluded`. Refused with nothing
    computed: an unknown measure, `top` or `per_source` below 1, `per_source_top` below 1 or given
    with `balance=False` (the field named).

    Balance (default): when more than one source is in play, the best `per_source_top` of each
    source (in the queue's order within the source; default `ceil(top / sources)`) are kept and
    merged by the global order, so no source is crowded out of the top; the total never exceeds
    `top` (surplus entries beyond each source's first are dropped from the global tail).
    `balance=False` returns the plain global order. `parameters` shows `balance` (1 or 0) and the
    `per_source_top` applied (None when not balanced)."""
    _check(order_by, top, per_source, per_source_top, balance)
    fresh = candidates or lead_candidates(
        project,
        sources=sources,
        per_source=per_source,
        layer=layer,
        technique_min_works=technique_min_works,
        max_co_works=max_co_works,
    )
    project.index.sync()
    subjects = [_subject_of(c) for c in fresh.candidates]
    promoted = _lead_rows(project, "promoted")
    open_leads = _lead_rows(project, "open") if include_leads else []
    by_lead = _lead_triggers(project, [r[0] for r in (*promoted, *open_leads)])

    def lead_subject(lead_id: str) -> _Subject:
        trig = by_lead.get(lead_id, [])
        return _Subject(
            entry_id=lead_id,
            kind="lead",
            source="lead",
            items=tuple(r for k, r in trig if k == "item"),
            works=tuple(r for k, r in trig if k == "work"),
        )

    lead_subjects = [lead_subject(r[0]) for r in open_leads]
    promoted_subjects = [lead_subject(r[0]) for r in promoted]
    everyone = [*subjects, *lead_subjects]
    items = _items(project, {i for s in (*everyone, *promoted_subjects) for i in s.items})
    state = _basis(project, items)
    cited_ids = {i for s in everyone for i in s.items}
    verified = _verify(project, {i: v for i, v in items.items() if i in cited_ids})
    keys = {k for s in everyone for k in (*s.items, *s.works)}
    leads_p, hyps_p, dirs_p = _prior_rows(project, keys)

    def approach_set(subject: _Subject) -> set[str]:
        found = {
            f"approach:{items[i].category}"
            for i in subject.items
            if i in items and items[i].category
        }
        return set(subject.items) | found

    promoted_sets = {s.entry_id: approach_set(s) for s in promoted_subjects}

    def measure(subject: _Subject) -> QueueItem:
        known = {i: items[i] for i in subject.items if i in items}
        cited = set(subject.works) | {i.work_id for i in known.values()}
        bad = {i: ("unknown" if i not in items else state[i]) for i in subject.items}
        bad = {i: s for i, s in bad.items() if s != "live"}
        kinds = set(bad.values())
        basis = next((k for k in ("unknown", "superseded", "stale") if k in kinds), "live")
        ok = sum(1 for i in subject.items if verified.get(i, False))
        tech = [i for i in known.values() if i.category is not None]
        share = None if not tech else sum(1 for i in tech if i.evidence in SUPPORTIVE) / len(tech)
        mine = approach_set(subject)
        similar = sorted(
            (
                (_jaccard(mine, other), lead)
                for lead, other in promoted_sets.items()
                if lead != subject.entry_id
            ),
            key=lambda t: (-t[0], t[1]),
        )
        best = similar[0] if similar else (0.0, None)
        hits, closed = _hits(subject, leads_p, hyps_p, dirs_p)
        narrow = sum(1 for h in hits if h.shared_items)
        flags = list(subject.flags)
        if basis != "live":
            flags.append(f"basis-{basis}")
        if closed:
            flags.append("closed-direction-hit")
        if subject.score is None:
            flags.append("no-score")
        m = Measures(
            support=subject.works_total if subject.works_total is not None else len(cited),
            independence=len(cited),
            verification=Verification(
                verified=ok,
                total=len(subject.items),
                share=None if not subject.items else ok / len(subject.items),
            ),
            supportive_share=share,
            overlap=subject.overlap,
            diversity=1.0 - best[0] if mine else 1.0,
            diversity_vs=best[1] if best[0] > 0 else None,
            prior_hits=len(hits),
            narrow_prior_hits=narrow,
            closed_direction_hit=closed,
            score=subject.score or 0.0,
            score_flag=None if subject.score is not None else "no score for this source",
            basis=basis,
        )
        source = subject.source
        if subject.kind == "lead":
            source = scope_source({items[i].scope for i in subject.items if i in items})
        return QueueItem(
            kind=subject.kind,
            entry_id=subject.entry_id,
            source=source,
            rank=0,
            measures=m,
            prior=hits,
            flags=tuple(flags),
            stale_refs=tuple(sorted(bad)),
            candidate=subject.candidate,
        )

    measured = [measure(s) for s in subjects]
    excluded: list[Skipped] = []
    if exclude_prior:
        excluded = [
            Skipped(candidate_id=m.entry_id, reason=f"prior-hits: {m.measures.prior_hits}")
            for m in measured
            if m.measures.prior_hits
        ]
        measured = [m for m in measured if not m.measures.prior_hits]
    ordered = sorted(measured, key=lambda m: _sort_key(m, order_by))
    lead_items = sorted((measure(s) for s in lead_subjects), key=lambda m: _sort_key(m, order_by))
    applied: int | None = None
    chosen = ordered
    if balance and len({m.source for m in ordered}) > 1:
        n_sources = len({m.source for m in ordered})
        applied = per_source_top or -(-top // n_sources)
        chosen = _balanced(ordered, applied, top)
    else:
        chosen = ordered[:top]
    return Queue(
        order_by=tuple(order_by),
        order_rule=_rule(order_by),
        comparability=_COMPARABILITY,
        parameters={
            "sources": _sources_of(fresh),
            "per_source": per_source,
            "layer": layer,
            "top": top,
            "exclude_prior": int(exclude_prior),
            "include_leads": int(include_leads),
            "technique_min_works": technique_min_works,
            "max_co_works": max_co_works,
            "balance": int(balance),
            "per_source_top": applied,
        },
        items=tuple(m.model_copy(update={"rank": r}) for r, m in enumerate(chosen, 1)),
        leads=tuple(m.model_copy(update={"rank": r}) for r, m in enumerate(lead_items[:top], 1)),
        total_candidates=len(ordered),
        excluded=tuple(excluded),
    )
