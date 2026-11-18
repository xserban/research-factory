"""Payload of the hub Findings page: finding cards, research cycle, openness, claims (plan hub-ui,
step 5).

Pure functions over `hub_mining.MiningData` plus one thin loader. Nothing here calls a model,
writes an event or types a number: each card is a rule with a numerator, a denominator, the paper
ids behind it and evidence pointers (work, miner, field, quote, anchor), all read from the
recorded miner rows of the included works (the attribution rule of `hub_mining`).

Invariants:
- A card's sentence is a template with placeholders; the figures and words that fill it come
  from the counts. A rule whose miner did not run, or that has no value, is `available: False`
  with no sentence: an unknown share is never shown as zero.
- The denominator of a rule is the included works that carry a value for its field, never all
  included works; `population` says how many works the miner read, how many of them are
  included, and their layer when it is one (for example "94 core papers").
- A work's value for a field is the first non-empty value over its pass-A rows in row order.
- Ties between stages go to the earlier stage of the research cycle.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from factory.services import hub_mining as hm
from factory.services import site_corpus
from factory.services.context import Project
from factory.services.hub_mining import Attributed, Cell, MiningData
from factory.services.hub_payloads import Sets, cited_here
from factory.services.site_layers import LAYER_ORDER
from factory.services.work_layers import layers_of

EVIDENCE_LIMIT = 5
MIN_QUOTE = 40
TECH_FIELD = "category"
TECH_MINER = "m-tech-{stage}"

STAGES: tuple[tuple[str, str], ...] = (
    ("literature-review", "Literature review"),
    ("ideation-hypothesis", "Ideation and hypotheses"),
    ("experiment-design", "Experiment design"),
    ("implementation-execution", "Implementation and execution"),
    ("data-analysis", "Data analysis"),
    ("paper-writing", "Paper writing"),
    ("review-verification", "Review and verification"),
)
STAGE_LABEL = dict(STAGES)

DEFAULT_FIELDS: dict[str, tuple[str, str]] = {
    "human": ("m-mapping", "human_position"),
    "span": ("m-mapping", "automated_span"),
    "shape": ("m-mapping", "process_shape"),
    "compare": ("m-mapping", "human_vs_automated"),
    "validation": ("m-summary", "validation_level"),
    "contribution": ("m-summary", "contribution_type"),
    "data": ("m-release", "data_status"),
    "code": ("m-release", "code_status"),
    "stage": ("m-stages", "stage"),
    "mode": ("m-stages", "mode"),
}
PROFILE_DIM_KEYS = {"human": "human", "span": "span", "process": "shape"}

VALIDATION_LABELS: dict[str, str] = {
    "none": "None reported",
    "simulation-or-benchmark": "Benchmark or simulation",
    "expert-review": "Expert review",
    "real-experiment": "Real experiment",
    "deployment": "Deployment",
}
CONTRIBUTION_LABELS: dict[str, str] = {
    "new-system": "New system",
    "new-benchmark": "New benchmark",
    "empirical-study": "Empirical study",
    "framework-or-position": "Framework or position",
    "new-evaluation-method": "New evaluation method",
    "new-component": "New component",
    "other": "Other",
}
RELEASE_GROUPS: tuple[tuple[str, str], ...] = (
    ("released", "Released"),
    ("partial", "Partly released or on request"),
    ("promised", "Promised"),
    ("no", "Not released"),
    ("ns", "Not stated"),
    ("other", "Other"),
)
RELEASE_OF: dict[str, str] = {
    "released": "released",
    "partial": "partial",
    "available-on-request": "partial",
    "restricted-access": "partial",
    "promised": "promised",
    "not-released": "no",
    "not-stated": "ns",
}
COMPARES = ("comparable", "system-better", "humans-better")

METHODS: dict[str, str] = {
    "cards": (
        "Each card is one rule: the papers whose coded value matches, out of the included papers "
        "that carry a value for the field. Papers with no value are not in the denominator. The "
        "sentence is filled from the counts; the evidence is the quotations the readings were "
        "based on, from the papers cited most here."
    ),
    "cycle": (
        "For each stage of the research cycle, the papers whose stage record says the system "
        "does it automatically, out of the papers with stage records. Techniques come from the "
        "technique miners and are listed from the technique codebook; a technique counts a paper "
        "once. The technique miners ran on a subset of the papers, so the counts are lower "
        "bounds for the whole corpus."
    ),
    "openness": (
        "From the release miner: per layer and per artefact, the papers by release status. "
        "Partial, on request and restricted access are merged. Each bar counts the papers that "
        "have a status for that artefact."
    ),
    "claims": (
        "Counts of papers per pair of contribution type and strongest validation level, over "
        "the papers that have both."
    ),
}

FRACTIONS: tuple[tuple[float, str], ...] = (
    (0.1, "one in ten"),
    (1 / 6, "one in six"),
    (0.2, "one in five"),
    (0.25, "a quarter"),
    (1 / 3, "a third"),
    (0.4, "four in ten"),
    (0.5, "half"),
    (0.6, "six in ten"),
    (2 / 3, "two thirds"),
    (0.75, "three quarters"),
)


def share_words(p: float) -> str:
    """A share as plain words: the nearest common fraction within a point and a quarter of
    one, 'about' that within three points, else a percentage."""
    best = min(FRACTIONS, key=lambda f: abs(f[0] - p))
    d = abs(best[0] - p)
    if d < 0.012:
        return best[1]
    if d < 0.03:
        return "about " + best[1]
    return f"{round(p * 100)}%"


def percent(p: float) -> str:
    return f"{round(p * 100)}%"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


# ------------------------------------------------------------------ context


@dataclass(frozen=True)
class _Ctx:
    data: MiningData
    atts: Mapping[str, Attributed]
    layers: Mapping[str, str]
    rank: Mapping[str, int]
    fields: Mapping[str, tuple[str, str]]

    @property
    def included(self) -> int:
        return len(self.data.sets.included)

    def a(self, miner: str) -> Mapping[str, Sequence[hm.MRow]]:
        att = self.atts.get(miner)
        return att.by_pass.get("A", {}) if att is not None else {}

    def values(self, key: str) -> dict[str, Cell]:
        miner, name = self.fields[key]
        out: dict[str, Cell] = {}
        for w, rows in self.a(miner).items():
            c = hm.first_cell(rows, name)
            if c is not None:
                out[w] = c
        return out

    def order(self, ids: Iterable[str]) -> list[str]:
        return sorted(set(ids), key=lambda w: (-self.rank.get(w, 0), w))

    def population(self, miners: Sequence[str], with_value: int) -> dict[str, Any]:
        read = {w for m in miners for w in self.a(m)}
        layer_set = {self.layers.get(w) for w in read}
        only = next(iter(layer_set)) if len(layer_set) == 1 else None
        layer = only if read else None
        who = f"{layer} papers" if layer else "papers"
        txt = f"{len(read)} {who} read by {', '.join(miners)}"
        if len(read) < self.included:
            txt += f", of {self.included} included"
        return {
            "read": len(read),
            "of_included": self.included,
            "with_value": with_value,
            "layer": layer,
            "complete": len(read) == self.included,
            "miners": list(miners),
            "text": txt,
        }

    def evidence(
        self,
        ids: Iterable[str],
        pointer: Callable[[str], tuple[str, str, Cell] | None],
    ) -> list[dict[str, Any]]:
        quoted: list[tuple[str, str, str, Cell]] = []
        for w in self.order(ids):
            got = pointer(w)
            if got is not None and got[2].quote.strip():
                quoted.append((w, got[0], got[1], got[2]))
        long_ones = [q for q in quoted if len(q[3].quote.strip()) >= MIN_QUOTE]
        return [
            {
                "work": w,
                "title": self.data.titles.get(w, w),
                "miner": miner,
                "field": name,
                "value": c.value,
                "quote": c.quote,
                "anchor": c.anchor,
            }
            for w, miner, name, c in (long_ones or quoted)[:EVIDENCE_LIMIT]
        ]

    def field_pointer(self, key: str, cells: Mapping[str, Cell]) -> Callable[..., Any]:
        miner, name = self.fields[key]
        return lambda w: (miner, name, cells[w]) if w in cells else None


def _card(
    rule: str,
    template: str,
    how: str,
    *,
    numerator: int,
    denominator: int,
    ids: list[str],
    params: dict[str, str],
    evidence: list[dict[str, Any]],
    population: dict[str, Any],
    source: list[dict[str, str]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    available = denominator > 0
    return {
        "rule": rule,
        "template": template,
        "params": params if available else {},
        "say": template.format(**params) if available else None,
        "available": available,
        "numerator": numerator,
        "denominator": denominator,
        "share": numerator / denominator if denominator else None,
        "ids": ids if available else [],
        "evidence": evidence if available else [],
        "population": population,
        "source": source,
        "how": how,
        "extra": (extra or {}) if available else {},
    }


def _share_card(
    ctx: _Ctx,
    rule: str,
    template: str,
    how: str,
    key: str,
    match: Callable[[str], bool],
    words: Callable[[float], dict[str, str]],
) -> dict[str, Any]:
    cells = ctx.values(key)
    hit = [w for w, c in cells.items() if match(c.value)]
    n, d = len(hit), len(cells)
    miner, name = ctx.fields[key]
    return _card(
        rule,
        template,
        how,
        numerator=n,
        denominator=d,
        ids=ctx.order(hit),
        params=words(n / d) if d else {},
        evidence=ctx.evidence(hit, ctx.field_pointer(key, cells)),
        population=ctx.population([miner], d),
        source=[{"miner": miner, "field": name}],
    )


# ------------------------------------------------------------------ stages and techniques


@dataclass(frozen=True)
class _Stages:
    stage_works: int
    automated: Mapping[str, list[str]]
    quote: Mapping[tuple[str, str], Cell]


def _stages(ctx: _Ctx) -> _Stages:
    miner, _ = ctx.fields["stage"]
    _, mode_name = ctx.fields["mode"]
    stage_name = ctx.fields["stage"][1]
    auto: dict[str, list[str]] = {s: [] for s, _l in STAGES}
    quote: dict[tuple[str, str], Cell] = {}
    with_stage = 0
    for w, rows in ctx.a(miner).items():
        seen = False
        for stage, _label in STAGES:
            mine = [r for r in rows if (c := r.cells.get(stage_name)) and c.value == stage]
            if not mine:
                continue
            seen = True
            for r in mine:
                m = r.cells.get(mode_name)
                if m is not None and m.value == "automated":
                    auto[stage].append(w)
                    quote[(stage, w)] = m
                    break
        with_stage += int(seen)
    return _Stages(with_stage, {s: sorted(v) for s, v in auto.items()}, quote)


@dataclass(frozen=True)
class _Tech:
    stage: str
    miner: str
    read: int
    listed: list[dict[str, Any]]
    cells: Mapping[tuple[str, str], Cell]
    not_stated: int
    other: int
    unlisted: int


def _techniques(ctx: _Ctx, stage: str) -> _Tech:
    miner = TECH_MINER.format(stage=stage)
    rows_by_work = ctx.a(miner)
    entries: dict[str, dict[str, Any]] = {
        code: {"code": code, "label": v["label"], "ids": set(), "quotes": {}}
        for code, v in sorted(ctx.data.codebook.items())
        if v.get("stage") == stage
    }
    cells: dict[tuple[str, str], Cell] = {}
    not_stated = other = unlisted = 0
    for w, rows in rows_by_work.items():
        for r in rows:
            c = r.cells.get(TECH_FIELD)
            if c is None or not c.value:
                continue
            code = c.value.rsplit("/", 1)[-1]
            if code in entries:
                e = entries[code]
                e["ids"].add(w)
                if c.quote and w not in e["quotes"]:
                    e["quotes"][w] = c.quote
                cells.setdefault((code, w), c)
            elif code == "not-stated":
                not_stated += 1
            elif code == "other":
                other += 1
            else:
                unlisted += 1
    listed = [
        {
            "code": e["code"],
            "label": e["label"],
            "n": len(e["ids"]),
            "ids": sorted(e["ids"]),
            "quotes": dict(sorted(e["quotes"].items())),
        }
        for e in entries.values()
    ]
    listed.sort(key=lambda t: (-t["n"], t["label"]))
    return _Tech(stage, miner, len(rows_by_work), listed, cells, not_stated, other, unlisted)


def _cycle(ctx: _Ctx, st: _Stages, techs: Mapping[str, _Tech]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for stage, label in STAGES:
        t = techs[stage]
        n = len(st.automated[stage])
        out.append(
            {
                "stage": stage,
                "label": label,
                "automated": n,
                "of": st.stage_works,
                "share": n / st.stage_works if st.stage_works else None,
                "ids": st.automated[stage],
                "techniques_listed": len(t.listed),
                "techniques_used": sum(1 for x in t.listed if x["n"]),
                "techniques": t.listed,
                "not_stated": t.not_stated,
                "other": t.other,
                "unlisted": t.unlisted,
                "core": t.read,
            }
        )
    miners = [t.miner for t in techs.values() if t.read]
    return {
        "stages": out,
        "of": st.stage_works,
        "core": max((t.read for t in techs.values()), default=0),
        "population": ctx.population(miners, st.stage_works),
        "methods": METHODS["cycle"],
    }


def _stage_cards(ctx: _Ctx, st: _Stages, techs: Mapping[str, _Tech]) -> list[dict[str, Any]]:
    stage_miner = ctx.fields["stage"][0]
    mode_name = ctx.fields["mode"][1]
    nst = st.stage_works
    stats: list[tuple[str, int, float]] = [
        (s, len(st.automated[s]), len(st.automated[s]) / nst if nst else 0.0) for s, _l in STAGES
    ]
    lo = stats[0]
    hi = stats[0]
    for x in stats[1:]:
        lo = x if x[2] < lo[2] else lo
        hi = x if x[2] > hi[2] else hi
    s_lo = lo[0]
    least = _card(
        "least_automated_stage",
        "{stage_cap} is the least automated stage; {percent} of systems do it themselves.",
        "For each stage of the research cycle, counts the papers whose stage record says the "
        "system does it automatically, out of the papers with stage records. Papers where a "
        "person does the stage, or that only mention it, do not count. Ties go to the earlier "
        "stage.",
        numerator=lo[1],
        denominator=nst,
        ids=ctx.order(st.automated[s_lo]),
        params={"stage_cap": _cap(STAGE_LABEL[s_lo].lower()), "percent": percent(lo[2])},
        evidence=ctx.evidence(
            st.automated[s_lo],
            lambda w: (
                (stage_miner, mode_name, st.quote[(s_lo, w)]) if (s_lo, w) in st.quote else None
            ),
        ),
        population=ctx.population([stage_miner], nst),
        source=[{"miner": stage_miner, "field": mode_name}],
        extra={
            "stage": s_lo,
            "label": STAGE_LABEL[s_lo],
            "most_automated": {"stage": hi[0], "n": hi[1], "share": hi[2]},
        },
    )
    used: list[tuple[str, int]] = [
        (s, sum(1 for x in techs[s].listed if x["n"])) for s, _l in STAGES
    ]
    top = used[0]
    for y in used[1:]:
        top = y if y[1] > top[1] else top
    s_top = top[0]
    t_top = techs[s_top]
    ids_top = sorted({w for x in t_top.listed for w in x["ids"]})
    fewest = min(used, key=lambda x: x[1])
    varied = _card(
        "most_varied_stage",
        "{stage_cap} is the most varied stage: {n_techniques} different techniques in use.",
        "For each stage, counts the techniques of the stage's codebook that at least one paper "
        "read by the technique miners uses. The technique miners ran on a subset of the papers, "
        "so the counts are lower bounds for the whole corpus.",
        numerator=top[1],
        denominator=len(t_top.listed),
        ids=ctx.order(ids_top),
        params={"stage_cap": _cap(STAGE_LABEL[s_top].lower()), "n_techniques": str(top[1])},
        evidence=ctx.evidence(
            ids_top,
            lambda w: next(
                (
                    (t_top.miner, TECH_FIELD, t_top.cells[(x["code"], w)])
                    for x in t_top.listed
                    if (x["code"], w) in t_top.cells
                ),
                None,
            ),
        ),
        population=ctx.population([t.miner for t in techs.values() if t.read], t_top.read),
        source=[{"miner": t_top.miner, "field": TECH_FIELD}],
        extra={
            "stage": s_top,
            "label": STAGE_LABEL[s_top],
            "fewest": {"stage": fewest[0], "n": fewest[1]},
        },
    )
    if not any(t.listed for t in techs.values()):
        varied = {**varied, "available": False, "say": None, "ids": [], "evidence": [], "extra": {}}
    return [least, varied]


# ------------------------------------------------------------------ openness and claims


def _release_group(value: str) -> str:
    return RELEASE_OF.get(value, "other")


def _openness(ctx: _Ctx) -> dict[str, Any]:
    data, code = ctx.values("data"), ctx.values("code")
    covered = set(data) | set(code)
    present = {ctx.layers[w] for w in covered if w in ctx.layers}
    layers = [k for k in LAYER_ORDER if k in present] + sorted(present - set(LAYER_ORDER))

    def bar(cells: Mapping[str, Cell], works: set[str]) -> dict[str, Any]:
        by: dict[str, list[str]] = defaultdict(list)
        for w in sorted(works & set(cells)):
            by[_release_group(cells[w].value)].append(w)
        segs = [
            {"key": k, "label": lab, "n": len(by[k]), "ids": by[k]}
            for k, lab in RELEASE_GROUPS
            if by.get(k)
        ]
        return {"n": sum(s["n"] for s in segs), "segments": segs}

    groups = [("all", "All papers", covered)] + [
        (k, k, {w for w in covered if ctx.layers.get(w) == k}) for k in layers
    ]
    miner = ctx.fields["data"][0]
    return {
        "groups": [
            {"key": k, "label": lab, "n": len(ws), "data": bar(data, ws), "code": bar(code, ws)}
            for k, lab, ws in groups
        ],
        "n": len(covered),
        "population": ctx.population([miner], len(covered)),
        "methods": METHODS["openness"],
    }


def _claims(ctx: _Ctx) -> dict[str, Any]:
    contrib, valid = ctx.values("contribution"), ctx.values("validation")
    both = sorted(set(contrib) & set(valid))
    cols = list(VALIDATION_LABELS) + sorted({valid[w].value for w in both} - set(VALIDATION_LABELS))
    cell: dict[tuple[str, str], list[str]] = defaultdict(list)
    for w in both:
        cell[(contrib[w].value, valid[w].value)].append(w)
    keys = {contrib[w].value for w in both}
    rows: list[dict[str, Any]] = []
    for k in keys:
        n = sum(len(cell[(k, v)]) for v in cols)
        rows.append(
            {
                "key": k,
                "label": CONTRIBUTION_LABELS.get(k, k),
                "n": n,
                "cells": {v: {"n": len(cell[(k, v)]), "ids": cell[(k, v)]} for v in cols},
            }
        )
    rows.sort(key=lambda r: (-r["n"], r["key"]))
    return {
        "n": len(both),
        "columns": [{"key": v, "label": VALIDATION_LABELS.get(v, v)} for v in cols],
        "rows": rows,
        "column_totals": {v: sum(len(cell[(k, v)]) for k in keys) for v in cols},
        "population": ctx.population([ctx.fields["validation"][0]], len(both)),
        "methods": METHODS["claims"],
    }


# ------------------------------------------------------------------ payload


def findings_from(
    data: MiningData,
    layers: Mapping[str, str] | None = None,
    rank: Mapping[str, int] | None = None,
    fields: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """The Findings payload from prepared data. `layers` maps a work to its layer, `rank` to its
    cited-here count (evidence order), `fields` overrides the default miner field of a rule."""
    ctx = _Ctx(
        data, hm.attributions(data), layers or {}, rank or {}, {**DEFAULT_FIELDS, **(fields or {})}
    )
    st = _stages(ctx)
    techs = {s: _techniques(ctx, s) for s, _l in STAGES}
    stage_cards = _stage_cards(ctx, st, techs)

    def shares(p: float) -> dict[str, str]:
        return {"share": share_words(p), "share_cap": _cap(share_words(p))}

    no_human = _share_card(
        ctx,
        "no_human",
        "{share_cap} of the systems run with no human in the loop.",
        "Counts the papers whose coded human position is none, out of the papers that have a "
        "human position. Each value is backed by the sentence the first reading used.",
        "human",
        lambda v: v == "none",
        shares,
    )
    span = ctx.values("span")
    alt: Counter[str] = Counter(
        c.value for c in span.values() if c.value not in ("full-lifecycle", "not-determinable")
    )
    full = _share_card(
        ctx,
        "full_lifecycle",
        "Only {share} of systems automate the full research cycle.",
        "Counts the papers whose automated span is the full lifecycle, out of the papers with a "
        "span value. The alternative shown is the largest of the other values, not counting "
        "not determinable.",
        "span",
        lambda v: v == "full-lifecycle",
        shares,
    )
    if alt and full["available"]:
        top_v = sorted(alt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        top_ids = sorted(w for w, c in span.items() if c.value == top_v)
        full["extra"] = {
            "alternative": {"value": top_v, "n": len(top_ids), "ids": ctx.order(top_ids)}
        }
    loop = _share_card(
        ctx,
        "iterative_loop",
        "{share_cap} of systems are built as an iterative loop.",
        "Counts the papers whose process shape is an iterative loop (generate, test, revise), "
        "out of the papers that have a process shape.",
        "shape",
        lambda v: v == "iterative-loop",
        shares,
    )
    valid = ctx.values("validation")

    def real_words(p: float) -> dict[str, str]:
        n_real = sum(1 for c in valid.values() if c.value == "real-experiment")
        return {**shares(p), "real_percent": percent(n_real / len(valid))}

    bench = _share_card(
        ctx,
        "benchmark_validation",
        "{share_cap} of papers validate on benchmarks or simulation; {real_percent} test in a "
        "real experiment.",
        "Counts the papers whose strongest validation is a benchmark or simulation, out of the "
        "papers with a validation value. Real experiments and deployments are shown apart.",
        "validation",
        lambda v: v == "simulation-or-benchmark",
        real_words,
    )
    if bench["available"]:
        bench["extra"] = {
            k: {"n": len(ids), "ids": ctx.order(ids)}
            for k, ids in (
                ("real_experiment", [w for w, c in valid.items() if c.value == "real-experiment"]),
                ("deployment", [w for w, c in valid.items() if c.value == "deployment"]),
            )
        }
    compare = _share_card(
        ctx,
        "compare_with_humans",
        "Only {share} of papers compare the system with human performance.",
        "Counts the papers whose comparison with humans is comparable, system better or humans "
        "better, out of the papers with a value. Not compared is the rest.",
        "compare",
        lambda v: v in COMPARES,
        shares,
    )
    code = ctx.values("code")
    n_code = sum(1 for c in code.values() if c.value == "released")

    def release_words(p: float) -> dict[str, str]:
        return {
            "share": share_words(p),
            "code_share": share_words(n_code / len(code)) if code else "none",
        }

    release = _share_card(
        ctx,
        "data_release",
        "Only {share} of papers share their data; {code_share} release their code.",
        "From the release miner: counts the papers whose data status is released, out of the "
        "papers that have a data status; code status is counted the same way over the papers "
        "that have one. The release miner has not necessarily read every paper.",
        "data",
        lambda v: v == "released",
        release_words,
    )
    if release["available"]:
        ids = [w for w, c in code.items() if c.value == "released"]
        release["extra"] = {
            "code_released": {
                "n": len(ids),
                "denominator": len(code),
                "share": n_code / len(code) if code else None,
                "ids": ctx.order(ids),
            }
        }
    cards = [no_human, full, *stage_cards, loop, bench, compare, release]
    return {
        "population": {"included": ctx.included},
        "cards": cards,
        "cycle": _cycle(ctx, st, techs),
        "openness": _openness(ctx),
        "claims": _claims(ctx),
        "methods": METHODS,
    }


def profile_fields(project: Project) -> dict[str, tuple[str, str]]:
    """The human, span and process shape columns of the project's site profile as (miner, field)."""
    profile = site_corpus.load_profile(project)
    out: dict[str, tuple[str, str]] = {}
    for key, rule in PROFILE_DIM_KEYS.items():
        dim = next((d for d in profile.dims if d[0] == key), None)
        if dim is not None:
            out[rule] = (profile.roles.get(dim[2], dim[2]), dim[3])
    return out


def findings_payload(
    project: Project, sets: Sets | None = None, data: MiningData | None = None
) -> dict[str, Any]:
    """`findings_from` the project's data, with layers from `work_layers`, cited-here counts for
    evidence order and the site profile's columns."""
    data = data or hm.load_mining_data(project, sets=sets, with_platform=False)
    layers = {w: wl.layer for w, wl in layers_of(project).items() if wl.layer is not None}
    rank = {w: c.count for w, c in cited_here(project, data.sets.included).items()}
    return findings_from(data, layers=layers, rank=rank, fields=profile_fields(project))
