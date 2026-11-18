"""Paper flow for the hub: the path of each work through the factory (plan hub-ui, step 8b).

Pure functions over plain data (ledger rows and the trails of `flow_trails`), plus thin read-only
loaders. Nothing here calls a model, writes an event or types a number. The ledger is computed
once (`FlowData`) and the events are read once (`flow_trails`, one pass for all works), so no
function loops over works with a query.

Invariants:
- A work's final fate is the ledger's (`hub_payloads.fate_of`); stops never decide it.
  `fate_consistent` checks that the stops do not contradict it, and the tests run it on every row.
- Stops are ordered by time, ties by stage order, then by event order (the sort is stable).
- An absorbed duplicate is shown with its canonical work: its own stops, then the canonical's
  stops from the merge onwards, marked `of`. Own stops alone feed fates, replay and divergence.
- Stages without a source in `flow_trails` (references extracted, cited by corpus) take stops
  from the optional `extra` argument; none are invented.
- Output is a function of the data, not of input order: ids, stops and dict keys are sorted.
- Stops carry no `event_id` yet: `TrailStep` does not hold it, so the field is None.

Cost: `flow_trails` is one pass over the events (the dominant cost, reads every event once);
`replay_frames` and `journey_index` are linear in the number of trail steps.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.context import Project
from factory.services.flow_ledger import LedgerRow
from factory.services.flow_trails import TrailStep, flow_trails
from factory.services.hub_payloads import (
    FATE_ORDER,
    FlowData,
    fate_of,
    included_ids,
    load_flow_data,
)

MAX_LANES = 20
TEXT_LIMIT = 240
DAY = 86400

STAGES: tuple[str, ...] = (
    "found",
    "deduplicated",
    "title-abstract",
    "retrieval",
    "conversion",
    "full-text",
    "read-in-full",
    "references-extracted",
    "cited-by-corpus",
)
"""The canonical stages, in the order a work meets them."""

METHODS: dict[str, str] = {
    "stages": (
        "Found (a search run, a supplied record or a snowball round), deduplicated (merged into "
        "a canonical record, or kept as it), title and abstract (each screener's pass and the "
        "resolution), retrieval (each attempt to get the full text), conversion, full text (each "
        "screener's pass and the resolution), read in full (each miner pass), references "
        "extracted, and cited by the corpus. A work only has stops for the stages it reached."
    ),
    "fate": (
        "The final fate is the one the flow ledger gives the record; the stops are what the "
        "events say happened on the way. The two are checked against each other."
    ),
    "replay": (
        "Each record is a dot. It enters a stage at the time of the first event of that stage "
        "for it, and stays there until it enters the next. Time is event time, in seconds since "
        "the first event; the histogram counts, per day, the records entering each stage."
    ),
    "swimlanes": (
        "One lane per chosen paper on a shared time axis, one stop per event with its stage, "
        "date, who acted (and which model), the outcome and the quote. A paper diverges at the "
        "first stage where its outcome differs from the strict majority of the lanes that reached "
        "that stage; where no outcome has a strict majority there is no divergence. A duplicate "
        "is shown with its canonical record. A stage's duration is the time from its first stop "
        "to the first stop of the next stage the paper reached."
    ),
}

_VERDICT_OUTCOME = {"include": "included", "exclude": "excluded"}
_STAGE_OF_SCREEN = {"title-abstract": "title-abstract", "full-text": "full-text"}


# ------------------------------------------------------------------ stops


@dataclass(frozen=True)
class Stop:
    """One event of a work's path. `of` is set when the stop belongs to the canonical record of
    a duplicate; `figure_id` links the stop to a `hub_trace` figure when one applies."""

    stage: str
    stage_index: int
    ts: str
    actor_kind: str
    actor: str | None
    model: str | None
    outcome: str
    criterion: str | None
    text: str | None
    quote: str | None
    label: str | None
    event_id: str | None
    figure_id: str | None
    of: str | None = None

    @classmethod
    def make(
        cls,
        stage: str,
        ts: str,
        outcome: str,
        *,
        actor_kind: str = "system",
        actor: str | None = None,
        model: str | None = None,
        criterion: str | None = None,
        text: str | None = None,
        quote: str | None = None,
        label: str | None = None,
        figure_id: str | None = None,
    ) -> Stop:
        return cls(
            stage, STAGES.index(stage), ts, actor_kind, actor, model, outcome, criterion,
            text, quote, label, None, figure_id,
        )  # fmt: skip


def _cut(text: str | None, limit: int = TEXT_LIMIT) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _kind(by: str | None, model: str | None) -> str:
    if model:
        return "agent"
    if by is None or by == "factory":
        return "system"
    return "human"


def _stop(work_id: str, s: TrailStep) -> Stop | None:
    d = s.d
    by = str(d["by"]) if "by" in d else None
    model = str(d["model"]) if "model" in d else None
    kind = _kind(by, model)
    crit = str(d["criterion"]) if "criterion" in d else None

    def make(stage: str, outcome: str, **kw: Any) -> Stop:
        return Stop.make(stage, s.at, outcome, **kw)

    if s.kind == "found":
        method = str(d.get("method", ""))
        where = ", ".join(str(d[k]) for k in ("source", "query", "run") if k in d)
        return make("found", "found", label=method or None, text=_cut(where))
    if s.kind == "merged":
        absorbed = [a.strip() for a in str(d.get("absorbed", "")).split(",") if a.strip()]
        primary = str(d.get("primary", ""))
        mine = work_id in absorbed
        return make(
            "deduplicated",
            "merged" if mine else "kept",
            text=_cut(f"into {primary}" if mine else f"absorbed {', '.join(absorbed)}"),
            label=str(d["rule"]) if "rule" in d else None,
        )
    if s.kind == "merge reverted":
        return make("deduplicated", "reverted", text=_cut(str(d.get("reason", ""))))
    if s.kind in ("decision", "resolved"):
        stage = _STAGE_OF_SCREEN.get(str(d.get("stage", "")))
        if stage is None:
            return None
        verdict = str(d.get("verdict", ""))
        label = (
            "resolution"
            if s.kind == "resolved"
            else f"pass {d['pass_label']}"
            + (" calibration" if d.get("phase") == "calibration" else "")
            if "pass_label" in d
            else None
        )
        return make(
            stage,
            _VERDICT_OUTCOME.get(verdict, verdict or "decided"),
            actor_kind=kind,
            actor=by,
            model=model,
            criterion=crit,
            text=_cut(str(d.get("rationale") or d.get("reason") or "")),
            quote=_cut(str(d["quote"])) if "quote" in d else None,
            label=label,
            figure_id=f"work.{work_id}.screening",
        )
    if s.kind == "attempt":
        return make(
            "retrieval",
            str(d.get("outcome", "attempted")),
            actor_kind=kind,
            actor=by,
            model=model,
            label=str(d["route"]) if "route" in d else None,
            text=_cut(str(d.get("reason", ""))),
        )
    if s.kind == "document added":
        return make(
            "retrieval", "retrieved", label=str(d.get("route", "")) or None, text="document added"
        )
    if s.kind == "converted":
        return make("conversion", "converted", label=str(d.get("converter", "")) or None)
    if s.kind == "conversion failed":
        return make(
            "conversion",
            "failed",
            label=str(d.get("converter", "")) or None,
            text=_cut(str(d.get("reason", ""))),
        )
    if s.kind in ("extracted", "claims"):
        schema = str(d.get("schema", "")) or s.kind
        label = f"{schema} pass {d['pass_label']}" if "pass_label" in d else schema
        return make("read-in-full", "read", label=label, text=f"{d.get('rows', 0)} rows")
    return None


def build_stops(work_id: str, steps: Iterable[TrailStep], extra: Iterable[Stop] = ()) -> list[Stop]:
    """The stops of one work, ordered by time then stage (stable, so event order breaks ties)."""
    out = [x for x in (_stop(work_id, s) for s in steps) if x is not None]
    out.extend(extra)
    return sorted(out, key=lambda x: (x.ts, x.stage_index))


# ------------------------------------------------------------------ journeys


@dataclass(frozen=True)
class Journey:
    """One work's path. `fate` and `criterion` are the ledger's."""

    work_id: str
    title: str
    fate: str
    criterion: str | None
    canonical_id: str | None
    stops: tuple[Stop, ...]

    def own(self) -> tuple[Stop, ...]:
        return tuple(s for s in self.stops if s.of is None)


def _by_id(rows: Iterable[LedgerRow]) -> dict[str, LedgerRow]:
    return {r.work_id: r for r in rows}


def _journey(
    row: LedgerRow,
    by_id: Mapping[str, LedgerRow],
    trails: Mapping[str, Sequence[TrailStep]],
    stage_run: bool,
    extra: Mapping[str, Sequence[Stop]],
) -> Journey:
    fate, criterion = fate_of(row, stage_run)
    stops = build_stops(row.work_id, trails.get(row.work_id, ()), extra.get(row.work_id, ()))
    canon = row.canonical_id
    if canon is not None and canon in by_id:
        merged = [s.ts for s in stops if s.stage == "deduplicated" and s.outcome == "merged"]
        since = merged[-1] if merged else ""
        shown = build_stops(canon, trails.get(canon, ()), extra.get(canon, ()))
        stops += [replace_of(s, canon) for s in shown if s.ts >= since]
    return Journey(row.work_id, row.title, fate, criterion, canon, tuple(stops))


def replace_of(stop: Stop, canonical: str) -> Stop:
    d = asdict(stop)
    d["of"] = canonical
    return Stop(**d)


def journey(
    work_id: str,
    rows: Sequence[LedgerRow],
    trails: Mapping[str, Sequence[TrailStep]],
    stage_run: bool,
    extra: Mapping[str, Sequence[Stop]] | None = None,
) -> Journey:
    """The journey of one ledger row; `work_id` unknown to the ledger is refused."""
    by_id = _by_id(rows)
    if work_id not in by_id:
        raise _refuse(f"unknown work {work_id}")
    return _journey(by_id[work_id], by_id, trails, stage_run, extra or {})


def fate_consistent(j: Journey) -> bool:
    """Whether the own stops do not contradict the ledger fate (see the module invariants)."""
    own = j.own()

    def at(stage: str) -> list[Stop]:
        return [s for s in own if s.stage == stage]

    dedup = at("deduplicated")
    if j.fate == "duplicate":
        return bool(dedup) and dedup[-1].outcome == "merged"
    if dedup and dedup[-1].outcome == "merged":
        return False
    for stage, fates in (("title-abstract", ("ta_excluded",)), ("full-text", ("ft_excluded",))):
        stops = at(stage)
        if j.fate in fates:
            hits = [s for s in stops if s.outcome == "excluded"]
            if not hits or (j.criterion and j.criterion not in {s.criterion for s in hits}):
                return False
        elif j.fate == "included":
            resolutions = [s for s in stops if s.label == "resolution"]
            if resolutions and resolutions[-1].outcome == "excluded":
                return False
    got = {s.outcome for s in at("retrieval")}
    if j.fate == "not_sought" and got:
        return False
    return not (j.fate == "not_retrieved" and (not got or "retrieved" in got or "restored" in got))


# ------------------------------------------------------------------ swimlanes


@dataclass(frozen=True)
class Lane:
    """One swimlane: the journey, its last outcome per stage reached, where it diverged and how
    long each stage lasted."""

    work_id: str
    title: str
    fate: str
    criterion: str | None
    canonical_id: str | None
    stops: tuple[Stop, ...]
    outcomes: dict[str, str]
    divergence: str | None
    durations: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SwimlaneSet:
    lanes: tuple[Lane, ...]
    domain: tuple[str, str] | None
    stages: tuple[str, ...] = STAGES
    methods: dict[str, str] = field(default_factory=lambda: {"swimlanes": METHODS["swimlanes"]})

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("work_ids", reason)])


def epoch(ts: str) -> int:
    """Whole seconds since the Unix epoch of a stored timestamp."""
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC).timestamp())


def _outcomes(j: Journey) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in j.own():
        out[s.stage] = s.outcome
    return out


def _durations(j: Journey) -> tuple[dict[str, Any], ...]:
    firsts: list[Stop] = []
    seen: set[str] = set()
    for s in j.own():
        if s.stage not in seen:
            seen.add(s.stage)
            firsts.append(s)
    out = []
    for i, s in enumerate(firsts):
        nxt = firsts[i + 1].ts if i + 1 < len(firsts) else None
        out.append(
            {"stage": s.stage, "start": s.ts, "seconds": epoch(nxt) - epoch(s.ts) if nxt else None}
        )
    return tuple(out)


def _divergence(outcomes: Sequence[Mapping[str, str]]) -> list[str | None]:
    """Per lane, the first stage where it is off the strict majority among lanes that reached
    the stage (None when no stage differs or no outcome has a strict majority)."""
    result: list[str | None] = [None] * len(outcomes)
    if len(outcomes) < 2:
        return result
    majority: dict[str, str] = {}
    for stage in STAGES:
        counts = Counter(o[stage] for o in outcomes if stage in o)
        ranked = counts.most_common(2)
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            majority[stage] = ranked[0][0]
    for i, o in enumerate(outcomes):
        for stage in STAGES:
            if stage in o and stage in majority and o[stage] != majority[stage]:
                result[i] = stage
                break
    return result


def swimlanes(
    rows: Sequence[LedgerRow],
    trails: Mapping[str, Sequence[TrailStep]],
    work_ids: Sequence[str],
    stage_run: bool,
    extra: Mapping[str, Sequence[Stop]] | None = None,
) -> SwimlaneSet:
    """Lanes for 1 to `MAX_LANES` works on a shared time domain, in the order given (repeated ids
    once). Refuses (`work_ids`) none, too many, or an id the ledger does not hold."""
    ids = list(dict.fromkeys(work_ids))
    if not ids:
        raise _refuse("choose at least one work")
    if len(ids) > MAX_LANES:
        raise _refuse(f"at most {MAX_LANES} works, got {len(ids)}")
    by_id = _by_id(rows)
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise _refuse("unknown work " + ", ".join(sorted(unknown)))
    js = [_journey(by_id[i], by_id, trails, stage_run, extra or {}) for i in ids]
    outs = [_outcomes(j) for j in js]
    div = _divergence(outs)
    times = [s.ts for j in js for s in j.stops]
    lanes = tuple(
        Lane(j.work_id, j.title, j.fate, j.criterion, j.canonical_id, j.stops, o, d, _durations(j))
        for j, o, d in zip(js, outs, div, strict=True)
    )
    return SwimlaneSet(lanes, (min(times), max(times)) if times else None)


# ------------------------------------------------------------------ replay


def replay_frames(
    rows: Sequence[LedgerRow],
    trails: Mapping[str, Sequence[TrailStep]],
    stage_run: bool,
    extra: Mapping[str, Sequence[Stop]] | None = None,
) -> dict[str, Any]:
    """Compact frames for the browser, for every ledger record (own stops only).

    `stages`: stage names; `fates`: fate keys; `ids`: sorted work ids; `records`: per id
    `[id index, fate index, [[stage index, seconds since t0], ...]]` with the first entry into
    each stage, in time order; `t0`: epoch seconds of the first event's UTC midnight; `days`:
    length of the time domain; `hist`: stage name -> records entering it per day since t0."""
    extra = extra or {}
    ordered = sorted(rows, key=lambda r: r.work_id)
    entered: list[list[tuple[int, int]]] = []
    for r in ordered:
        seen: dict[int, int] = {}
        for s in build_stops(r.work_id, trails.get(r.work_id, ()), extra.get(r.work_id, ())):
            seen.setdefault(s.stage_index, epoch(s.ts))
        entered.append(sorted(seen.items(), key=lambda kv: (kv[1], kv[0])))
    all_t = [t for e in entered for _, t in e]
    t0 = min(all_t) // DAY * DAY if all_t else 0
    days = (max(all_t) - t0) // DAY + 1 if all_t else 0
    hist = {name: [0] * days for name in STAGES}
    records = []
    for i, (r, e) in enumerate(zip(ordered, entered, strict=True)):
        fate = fate_of(r, stage_run)[0]
        records.append([i, FATE_ORDER.index(fate), [[si, t - t0] for si, t in e]])
        for si, t in e:
            hist[STAGES[si]][(t - t0) // DAY] += 1
    return {
        "stages": list(STAGES),
        "fates": list(FATE_ORDER),
        "ids": [r.work_id for r in ordered],
        "records": records,
        "t0": t0,
        "days": days,
        "hist": hist,
    }


def journey_index(
    rows: Sequence[LedgerRow],
    trails: Mapping[str, Sequence[TrailStep]],
    stage_run: bool,
    scope: str = "included",
    text_limit: int = 120,
    extra: Mapping[str, Sequence[Stop]] | None = None,
) -> dict[str, Any]:
    """Stop lists to embed in a static page: per work (the included works, or `all`) a list of
    `[stage index, ts, actor kind, model, outcome, criterion, text]` over own stops, texts cut to
    `text_limit`. `bytes` is the compact JSON size of `works`."""
    if scope not in ("included", "all"):
        raise FactoryValidationError([ValidationIssue("scope", "must be 'included' or 'all'")])
    extra = extra or {}
    ids = included_ids(rows, stage_run) if scope == "included" else sorted(r.work_id for r in rows)
    works = {
        i: [
            [
                s.stage_index,
                s.ts,
                s.actor_kind,
                s.model,
                s.outcome,
                s.criterion,
                _cut(s.text, text_limit),
            ]
            for s in build_stops(i, trails.get(i, ()), extra.get(i, ()))
        ]
        for i in ids
    }
    size = len(json.dumps(works, separators=(",", ":")))
    return {"scope": scope, "text_limit": text_limit, "works": works, "bytes": size}


# ------------------------------------------------------------------ loaders


def journeys_payload(
    project: Project,
    flow_data: FlowData | None = None,
    trails: Mapping[str, Sequence[TrailStep]] | None = None,
) -> dict[str, Any]:
    """The replay frames and their methods; swimlanes are fetched on demand."""
    data = flow_data or load_flow_data(project)
    got = trails if trails is not None else flow_trails(project)
    stage_run = data.prisma.full_text.stage_run
    return {"methods": METHODS, "replay": replay_frames(data.rows, got, stage_run)}


def swimlanes_payload(
    project: Project,
    work_ids: Sequence[str],
    flow_data: FlowData | None = None,
    trails: Mapping[str, Sequence[TrailStep]] | None = None,
) -> dict[str, Any]:
    """Swimlanes for the chosen works as JSON-safe data."""
    data = flow_data or load_flow_data(project)
    got = trails if trails is not None else flow_trails(project)
    return swimlanes(data.rows, got, work_ids, data.prisma.full_text.stage_run).to_payload()
