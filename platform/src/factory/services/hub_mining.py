"""Payloads of the hub Miners and Data pages (plan hub-ui, step 5).

Pure functions over plain rows (`MRow`, `MinerInfo`, `MiningData`) plus thin read-only loaders over
the index and the existing services. Nothing here calls a model, writes an event or types a number:
every figure comes from the recorded miner rows. `METHODS` holds the plain-English definitions
shown in the info panels.

Invariants:
- The corpus is the PRISMA included set (hub_payloads `Sets`, rule 4.1). Per miner, rows recorded
  on an absorbed duplicate are shown on its canonical work when the canonical has no rows of its
  own (`Attributed.via`); duplicate rows that a read canonical makes redundant and rows on works
  that are not included are never in a count and are reported apart (`off_corpus`).
- Only live rows (not superseded) of the miner's chosen version are read: the listed version, else
  the latest registered. A value shown carries its quote and anchor as recorded, never invented.
- Three agreement measures are named and never mixed: `exact` (set equality, defined here, over
  included works), `fairer` (IDEA-53, `site_agreement.measure`, same rows) and `platform` (the
  recorded `mine_status` rates over all rows). None says which pass is right.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from factory.mining.spec import EnumKind, MinerSpec, kind_to_json
from factory.mining.taxonomy import TaxonomySpec
from factory.services import mining as mining_service
from factory.services import site_corpus
from factory.services.context import Project
from factory.services.hub_payloads import Sets, load_flow_data, reconcile_sets, sets_payload
from factory.services.site_agreement import (
    ANCHOR_SUFFIX,
    MULTI_ROW_RATIO,
    QUOTE_SUFFIX,
    measure,
)
from factory.services.taxonomies import list_taxonomies, registered_taxonomy

EXACT_LABEL = "set-equality (included works)"
FAIRER_LABEL = "IDEA-53 enum comparison (included works)"
PLATFORM_LABEL = "mine status (all read works)"
TECH_PREFIX = "t-tech-"
EXAMPLES = 4
HOLES_TOP = 25
DEFAULT_COLUMNS = 8
MAX_PAGE_SIZE = 200
NO_MODEL = "unknown"
# First values that say nothing: counted as "undetermined" next to the empty cells (Holes).
UNLAYERED = site_corpus.UNLAYERED
SCOPE_DOMINANT = 0.9  # share of a miner's works in one layer that names the layer
GAP_VALUES = frozenset({"not-determinable", "other", "not-stated", "none-stated", "unclear"})
GRID_PREFIX = "grid-"
HOLES_SKIP = frozenset({"m-release.artefact_scope"})

METHODS: dict[str, str] = {
    "miners": (
        "Each miner is shown at its listed version, else its latest registered version. Pass A "
        "and pass B are the two independent readings. Counts are over the included works: rows "
        "recorded under an absorbed duplicate are shown on the canonical work when that work has "
        "none of its own; duplicate rows made redundant by a read canonical, and rows on works "
        "that are not included, are counted apart and never in a figure."
    ),
    "exact": (
        "For each field except quotes, over the included works both passes read: the share of "
        "works where the two passes gave the same set of values (order and repeats do not "
        "matter). Works where neither pass gave a value for the field are left out. This is a "
        "strict match: a correct but differently worded value counts as a disagreement."
    ),
    "fairer": (
        "The IDEA-53 comparison of the site agreement report: rows align per work (or on the "
        "enum row key for miners with several rows per work), enum values compare as labels, a "
        "secondary label agrees when it equals the other pass's primary or secondary, and free "
        "text and quotes are not compared. It is computed on the same included works."
    ),
    "platform": (
        "The rates the platform records for the miner (`mine status`): all rows, where a row "
        "only one pass wrote counts against it, and aligned rows only. They cover every read "
        "work, not only the included ones."
    ),
    "by_model": (
        "Passes are grouped by the model that read them (the sessions that joined the pass). "
        "Each pair shows the exact agreement over all fields and miners that the pair read."
    ),
    "grid": (
        "One row per included work. A cell is the first value recorded for the field in pass A, "
        "with the quote and anchor it was based on; for miners with several rows per work `n` "
        "is the number of rows. An empty cell means no value was recorded."
    ),
    "coverage": (
        "For each miner, the included works each pass read. Works are listed once and the "
        "passes refer to them by position."
    ),
    "holes": (
        "Per field, the share of included works the miner read where no value was recorded, "
        "and the share of all included works that lack one (missing or not read). A value that "
        "says nothing (not determinable, not stated, unclear or other) is counted apart as "
        "undetermined. Works are ranked by how many primary coded fields (enumerated fields not "
        "ending in _secondary) are missing or undetermined."
    ),
    "codebook": (
        "Technique codes with their stage and label, from the registered technique taxonomies "
        "(names starting with t-tech-). A code is listed when its taxonomy lists it, whether or "
        "not a paper uses it."
    ),
}


# ------------------------------------------------------------------ plain data


@dataclass(frozen=True)
class Cell:
    """One recorded field value with its quote and anchor (empty when none was recorded)."""

    value: str
    quote: str = ""
    anchor: str = ""


@dataclass(frozen=True)
class MRow:
    """A live miner row: one work, one pass, its cells by field name."""

    eid: str
    work: str
    pass_label: str
    cells: Mapping[str, Cell]


@dataclass(frozen=True)
class FieldInfo:
    name: str
    type: str
    values: tuple[str, ...]
    required: bool
    group: str
    compared: bool
    desc: str = ""

    @property
    def is_quote(self) -> bool:
        return self.type == "quote"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "values": list(self.values),
            "required": self.required,
            "group": self.group,
            "compared": self.compared,
            "desc": self.desc,
        }


@dataclass(frozen=True)
class MinerInfo:
    name: str
    version: int
    listed: bool
    spec: MinerSpec
    fields: tuple[FieldInfo, ...]


def miner_info(spec: MinerSpec, listed: bool) -> MinerInfo:
    """Describe a registered spec for a page."""
    fields = tuple(
        FieldInfo(
            f.name,
            str(kind_to_json(f.kind)["type"]),
            f.kind.values if isinstance(f.kind, EnumKind) else (),
            f.required,
            f.group,
            f.compared,
            f.description,
        )
        for f in spec.fields
    )
    return MinerInfo(spec.name, spec.version, listed, spec, fields)


@dataclass(frozen=True)
class MiningData:
    """What the pages share, loaded once. `models` maps `"<miner>|<pass>"` to the models that
    read the pass; `platform` maps a miner to its recorded (all-rows, aligned) agreement;
    `codebook` maps a technique code to its stage and label; `layers` maps an included work to its
    layer, so a miner's scope can be named (for example "core papers, 94")."""

    miners: tuple[MinerInfo, ...]
    rows: Mapping[str, tuple[MRow, ...]]
    models: Mapping[str, tuple[str, ...]]
    sets: Sets
    titles: Mapping[str, str]
    platform: Mapping[str, tuple[float | None, float | None]] = field(default_factory=dict)
    codebook: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    layers: Mapping[str, str] = field(default_factory=dict)
    """Included work id -> its layer (absent or "unlayered" when none); gives a miner's scope."""

    def info(self, name: str) -> MinerInfo:
        for m in self.miners:
            if m.name == name:
                return m
        raise KeyError(name)


# ------------------------------------------------------------------ attribution (rule 4.1)


@dataclass(frozen=True)
class Attributed:
    """A miner's live rows attributed to included works. `by_pass[label][work]` lists the rows
    shown on `work`; `via[canonical]` is the duplicate whose rows stand in for it."""

    by_pass: Mapping[str, Mapping[str, tuple[MRow, ...]]]
    via: Mapping[str, str]
    mapped: tuple[tuple[str, str], ...]
    shadowed_rows: int
    excluded_rows: int
    excluded_works: tuple[str, ...]

    def works(self, label: str) -> tuple[str, ...]:
        return tuple(sorted(self.by_pass.get(label, {})))

    def n_rows(self, label: str) -> int:
        return sum(len(v) for v in self.by_pass.get(label, {}).values())


def attribute_rows(rows: Iterable[MRow], sets: Sets) -> Attributed:
    """Attribute one miner's rows to the included set by the 4.1 rule (see the module docstring)."""
    rows = sorted(rows, key=lambda r: r.eid)
    canonical_of = {d.mined_id: d.canonical_id for d in sets.duplicate_mapped}
    fates = {e.work_id: (e.stage, e.criterion) for e in sets.mined_but_excluded}
    local = reconcile_sets(sets.included, {r.work for r in rows}, canonical_of, fates)
    included = set(sets.included)
    standing_for = {dup: canon for canon, dup in local.sources.items()}
    by_pass: dict[str, dict[str, list[MRow]]] = defaultdict(lambda: defaultdict(list))
    shadowed = 0
    excluded_rows = 0
    excluded_works: set[str] = set()
    for r in rows:
        if r.work in included:
            by_pass[r.pass_label][r.work].append(r)
        elif r.work in standing_for:
            by_pass[r.pass_label][standing_for[r.work]].append(r)
        elif canonical_of.get(r.work) in included:
            shadowed += 1
        else:
            excluded_rows += 1
            excluded_works.add(r.work)
    frozen = {k: {w: tuple(v) for w, v in per.items()} for k, per in by_pass.items()}
    mapped = tuple(sorted((dup, canon) for dup, canon in standing_for.items()))
    return Attributed(
        frozen,
        dict(local.sources),
        mapped,
        shadowed,
        excluded_rows,
        tuple(sorted(excluded_works)),
    )


def value_cells(rows: Sequence[MRow], name: str) -> list[Cell]:
    """The non-empty cells of `name` over `rows`, in row order."""
    return [c for r in rows if (c := r.cells.get(name)) is not None and c.value != ""]


def first_cell(rows: Sequence[MRow], name: str) -> Cell | None:
    """The first non-empty cell of `name` over `rows` (rows in extraction-id order)."""
    cells = value_cells(rows, name)
    return cells[0] if cells else None


# ------------------------------------------------------------------ agreement


@dataclass(frozen=True)
class FieldAgreement:
    agreed: int
    total: int
    works_both: int

    @property
    def rate(self) -> float | None:
        return self.agreed / self.total if self.total else None


def _comparable(f: FieldInfo) -> bool:
    return f.compared and not f.is_quote


def exact_agreement(
    fields: Sequence[FieldInfo],
    a: Mapping[str, Sequence[MRow]],
    b: Mapping[str, Sequence[MRow]],
) -> dict[str, FieldAgreement]:
    """Per comparable field, over works both passes read: works where the two passes' value sets
    are equal, among works where at least one pass gave a value. Quote fields are left out."""
    both = sorted(set(a) & set(b))
    out: dict[str, FieldAgreement] = {}
    for f in fields:
        if not _comparable(f):
            continue
        agreed = total = 0
        for w in both:
            sa = {c.value for c in value_cells(a[w], f.name)}
            sb = {c.value for c in value_cells(b[w], f.name)}
            if not sa and not sb:
                continue
            total += 1
            agreed += int(sa == sb)
        out[f.name] = FieldAgreement(agreed, total, len(both))
    return out


def _rate(agreed: int, total: int) -> float | None:
    return agreed / total if total else None


def _as_site_rows(rows: Mapping[str, Sequence[MRow]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for w, rs in rows.items():
        out[w] = [
            {
                **{n: c.value for n, c in r.cells.items()},
                **{n + QUOTE_SUFFIX: c.quote for n, c in r.cells.items()},
                **{n + ANCHOR_SUFFIX: c.anchor for n, c in r.cells.items()},
            }
            for r in rs
        ]
    return out


def _fairer(info: MinerInfo, att: Attributed) -> dict[str, Any]:
    m = measure(
        info.spec,
        _as_site_rows(att.by_pass.get("A", {})),
        _as_site_rows(att.by_pass.get("B", {})),
    )
    agreed, total = m.overall()
    return {
        "measure": FAIRER_LABEL,
        "by_field": {
            n: {
                "agreed": m.agreed[n],
                "total": m.total[n],
                "rate": _rate(m.agreed[n], m.total[n]),
                "one_sided": m.one_sided[n],
            }
            for n in sorted(m.total)
        },
        "overall": {"agreed": agreed, "total": total, "rate": _rate(agreed, total)},
        "matched": m.matched,
        "works_both": m.works_both,
        "note": m.note,
    }


# ------------------------------------------------------------------ miners


def _distribution(info: MinerInfo, rows_by_work: Mapping[str, Sequence[MRow]]) -> dict[str, Any]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for f in info.fields:
        if f.type != "enum":
            continue
        n_rows: Counter[str] = Counter()
        ids: dict[str, list[str]] = defaultdict(list)
        for w in sorted(rows_by_work):
            seen: set[str] = set()
            for c in value_cells(rows_by_work[w], f.name):
                n_rows[c.value] += 1
                seen.add(c.value)
            for v in seen:
                ids[v].append(w)
        out[f.name] = {
            v: {"rows": n_rows[v], "works": len(ids[v]), "ids": ids[v]} for v in sorted(n_rows)
        }
    return out


def _examples(
    rows_by_work: Mapping[str, Sequence[MRow]], titles: Mapping[str, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in sorted(rows_by_work):
        row = next(
            (r for r in rows_by_work[w] if any(c.quote and c.value for c in r.cells.values())),
            None,
        )
        if row is None:
            continue
        out.append(
            {
                "work": w,
                "title": titles.get(w, w),
                "row": row.eid,
                "cells": {
                    n: {"value": c.value, "quote": c.quote, "anchor": c.anchor}
                    for n, c in row.cells.items()
                    if c.value
                },
            }
        )
        if len(out) >= EXAMPLES:
            break
    return out


def _pass_block(att: Attributed, label: str, models: tuple[str, ...]) -> dict[str, Any]:
    return {"rows": att.n_rows(label), "works": len(att.works(label)), "models": list(models)}


def attributions(data: MiningData) -> dict[str, Attributed]:
    """Each miner's rows attributed to the included set."""
    return {m.name: attribute_rows(data.rows.get(m.name, ()), data.sets) for m in data.miners}


def _models(data: MiningData, name: str, label: str) -> tuple[str, ...]:
    return data.models.get(f"{name}|{label}", ())


def _scope(data: MiningData, read: Mapping[str, Sequence[MRow]]) -> dict[str, Any]:
    """The works a miner's first pass actually read: their number, their layers and a short name.

    `layer` is the layer of all of them, or of at least `SCOPE_DOMINANT` of them (then the text
    says "mostly"); None when mixed or unknown. The registered population is a ceiling, not this."""
    by_layer = Counter(data.layers.get(w) or UNLAYERED for w in read)
    n = len(read)
    total = len(data.sets.included)
    top, top_n = max(by_layer.items(), key=lambda kv: (kv[1], kv[0]), default=(UNLAYERED, 0))
    layer = top if n and top != UNLAYERED and top_n >= SCOPE_DOMINANT * n else None
    lead = "" if layer is None or top_n == n else "mostly "
    return {
        "layer": layer,
        "works": n,
        "of_included": total,
        "complete": n == total,
        "by_layer": dict(sorted(by_layer.items())),
        "text": f"{lead}{layer} papers, {n}" if layer else f"papers, {n}",
    }


def miners(data: MiningData, atts: Mapping[str, Attributed] | None = None) -> dict[str, Any]:
    """The miner gallery and detail payload (see the module docstring for the measures)."""
    atts = atts or attributions(data)
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for info in data.miners:
        att = atts[info.name]
        a, b = att.by_pass.get("A", {}), att.by_pass.get("B", {})
        exact = exact_agreement(info.fields, a, b)
        e_agreed = sum(x.agreed for x in exact.values())
        e_total = sum(x.total for x in exact.values())
        n_a = att.n_rows("A")
        works_a = len(a)
        rpw = round(n_a / works_a, 3) if works_a else 0.0
        platform = data.platform.get(info.name, (None, None))
        both = len(set(a) & set(b))
        ma, mb = _models(data, info.name, "A"), _models(data, info.name, "B")
        if b:
            key = (" + ".join(ma) or NO_MODEL, " + ".join(mb) or NO_MODEL)
            p = pairs.setdefault(
                key,
                {"a": key[0], "b": key[1], "miners": [], "works_both": 0, "agreed": 0, "total": 0},
            )
            p["miners"].append(info.name)
            p["works_both"] += both
            p["agreed"] += e_agreed
            p["total"] += e_total
        regime = info.spec.regime
        by_model = (
            {
                "a": key[0],
                "b": key[1],
                "miners": [info.name],
                "works_both": both,
                "agreed": e_agreed,
                "total": e_total,
                "rate": _rate(e_agreed, e_total),
            }
            if b
            else None
        )
        out.append(
            {
                "name": info.name,
                "version": info.version,
                "listed": info.listed,
                "rationale": info.spec.rationale,
                "population": info.spec.selector.population.value,
                "scope": _scope(data, a),
                "regime": {
                    "passes": regime.passes,
                    "calibration_size": regime.calibration_size,
                    "recall_min": regime.recall_min,
                    "field_agreement_min": regime.field_agreement_min,
                },
                "row_key": list(info.spec.row_key_fields),
                "fields": [f.as_dict() for f in info.fields],
                "pass_a": _pass_block(att, "A", ma),
                "pass_b": _pass_block(att, "B", mb),
                "works_both": both,
                "off_corpus": {
                    "mapped_from_duplicates": [
                        {"duplicate": d, "canonical": c} for d, c in att.mapped
                    ],
                    "shadowed_duplicate_rows": att.shadowed_rows,
                    "excluded_works": list(att.excluded_works),
                    "excluded_rows": att.excluded_rows,
                },
                "agreement": {
                    "exact": {
                        "measure": EXACT_LABEL,
                        "by_field": {
                            n: {"agreed": x.agreed, "total": x.total, "rate": x.rate}
                            for n, x in exact.items()
                        },
                        "overall": {
                            "agreed": e_agreed,
                            "total": e_total,
                            "rate": _rate(e_agreed, e_total),
                        },
                    },
                    "fairer": _fairer(info, att),
                    "platform": {
                        "measure": PLATFORM_LABEL,
                        "all_rows": platform[0],
                        "aligned_rows": platform[1],
                    },
                    "by_model": by_model,
                },
                "multi_row": rpw > MULTI_ROW_RATIO,
                "rows_per_work": rpw,
                "distributions": _distribution(info, a),
                "examples": _examples(a, data.titles),
            }
        )
    by_pair = [
        {**p, "miners": sorted(p["miners"]), "rate": _rate(p["agreed"], p["total"])}
        for _, p in sorted(pairs.items())
    ]
    return {
        "corpus": {"included": len(data.sets.included)},
        "miners": out,
        "by_model_pair": by_pair,
    }


# ------------------------------------------------------------------ grid


def _catalogue(data: MiningData, atts: Mapping[str, Attributed]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for info in sorted(data.miners, key=lambda m: m.name):
        a = atts[info.name].by_pass.get("A", {})
        for f in info.fields:
            out.append(
                {
                    "key": f"{info.name}.{f.name}",
                    "miner": info.name,
                    "field": f.name,
                    "type": f.type,
                    "filled": sum(1 for rows in a.values() if first_cell(rows, f.name)),
                }
            )
    return out


def data_grid(
    data: MiningData,
    columns: Sequence[str] | None,
    page: int = 1,
    page_size: int = 50,
    atts: Mapping[str, Attributed] | None = None,
) -> dict[str, Any]:
    """One page of the paper-by-field grid over the included works, in work-id order. Raises
    ValueError for an unknown column or a page below 1."""
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    page_size = min(page_size, MAX_PAGE_SIZE)
    atts = atts or attributions(data)
    cat = _catalogue(data, atts)
    known = {c["key"]: c for c in cat}
    chosen = (
        list(columns)
        if columns is not None
        else [c["key"] for c in cat if c["filled"]][:DEFAULT_COLUMNS]
    )
    for key in chosen:
        if key not in known:
            raise ValueError(f"unknown column: {key}")
    works = list(data.sets.included)
    start = (page - 1) * page_size
    rows: list[dict[str, Any]] = []
    for w in works[start : start + page_size]:
        cells: dict[str, Any] = {}
        via: dict[str, str] = {}
        for key in chosen:
            c = known[key]
            att = atts[c["miner"]]
            got = att.by_pass.get("A", {}).get(w, ())
            if w in att.via:
                via[c["miner"]] = att.via[w]
            cell = first_cell(got, c["field"])
            cells[key] = (
                None
                if cell is None
                else {
                    "v": cell.value,
                    "q": cell.quote[: site_corpus.MAX_QUOTE],
                    "a": cell.anchor,
                    "n": len(got),
                }
            )
        rows.append({"id": w, "title": data.titles.get(w, w), "cells": cells, "via": via})
    return {
        "page": page,
        "page_size": page_size,
        "total": len(works),
        "pages": -(-len(works) // page_size),
        "columns": [
            {k: known[key][k] for k in ("key", "miner", "field", "type")} for key in chosen
        ],
        "catalogue": cat,
        "rows": rows,
        "methods": METHODS["grid"],
    }


# ------------------------------------------------------------------ coverage and holes


def coverage(data: MiningData, atts: Mapping[str, Attributed] | None = None) -> dict[str, Any]:
    """The miner by work matrix: per miner the positions (in `works`) each pass read."""
    atts = atts or attributions(data)
    works = list(data.sets.included)
    pos = {w: i for i, w in enumerate(works)}
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for info in data.miners:
        att = atts[info.name]
        a = sorted(pos[w] for w in att.by_pass.get("A", {}))
        b = sorted(pos[w] for w in att.by_pass.get("B", {}))
        union = set(a) | set(b)
        seen |= union
        out.append(
            {
                "name": info.name,
                "version": info.version,
                "a": a,
                "b": b,
                "both": len(set(a) & set(b)),
                "only_a": len(set(a) - set(b)),
                "only_b": len(set(b) - set(a)),
                "unread": len(works) - len(union),
            }
        )
    return {
        "works": works,
        "miners": out,
        "not_read_by_any": [i for i in range(len(works)) if i not in seen],
        "methods": METHODS["coverage"],
    }


def _is_primary(key: str, f: FieldInfo) -> bool:
    """A coded field that every read paper should have: enumerated, not a secondary, not skipped."""
    return f.type == "enum" and not f.name.endswith("_secondary") and key not in HOLES_SKIP


def holes(data: MiningData, atts: Mapping[str, Attributed] | None = None) -> dict[str, Any]:
    """Per field the works missing a value (and those whose first value says nothing), and the
    works with the most primary coded fields missing or undetermined."""
    atts = atts or attributions(data)
    n = len(data.sets.included)
    fields_out: list[dict[str, Any]] = []
    thin: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for info in sorted(data.miners, key=lambda m: m.name):
        a = atts[info.name].by_pass.get("A", {})
        for f in info.fields:
            key = f"{info.name}.{f.name}"
            missing_works: list[str] = []
            gap_works: list[str] = []
            for w, rows in sorted(a.items()):
                cell = first_cell(rows, f.name)
                if cell is None:
                    missing_works.append(w)
                elif f.type == "enum" and cell.value in GAP_VALUES:
                    gap_works.append(w)
            unread = n - len(a)
            primary = _is_primary(key, f)
            fields_out.append(
                {
                    "key": key,
                    "miner": info.name,
                    "field": f.name,
                    "required": f.required,
                    "primary": primary,
                    "read": len(a),
                    "missing": len(missing_works),
                    "undetermined": len(gap_works),
                    "unread": unread,
                    "share_of_read": len(missing_works) / len(a) if a else None,
                    "share_of_included": (len(missing_works) + unread) / n if n else None,
                }
            )
            if primary:
                thin_here = [(w, False) for w in missing_works] + [(w, True) for w in gap_works]
                for w, is_gap in thin_here:
                    thin[w].append((key, is_gap))
    ranked = sorted(thin.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:HOLES_TOP]
    return {
        "fields": fields_out,
        "works": [
            {
                "id": w,
                "title": data.titles.get(w, w),
                "missing": sorted(k for k, g in keys if not g),
                "undetermined": sorted(k for k, g in keys if g),
            }
            for w, keys in ranked
        ],
        "methods": METHODS["holes"],
    }


# ------------------------------------------------------------------ per-miner grids


def grid_name(miner: str) -> str:
    return f"{GRID_PREFIX}{miner}"


def _dumps(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=None)


def miner_grid(data: MiningData, info: MinerInfo, att: Attributed) -> dict[str, Any]:
    """One miner's grid: its fields as columns and a row for every included work its pass A
    read. A cell is null (no value) or [value, quote, anchor]; for a work with several values of
    a field the cell also carries `n` and the distinct values in order: [v, q, a, n, [values]].
    Quotes are as recorded, cut to `site_corpus.MAX_QUOTE`; `gap` counts first values that say
    nothing (`GAP_VALUES`), `empty` the read works with no value."""
    a = att.by_pass.get("A", {})
    works = [w for w in data.sets.included if w in a]
    columns: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = [{"id": w, "c": []} for w in works]
    for f in info.fields:
        empty = gap = 0
        for row, w in zip(rows, works, strict=True):
            cells = value_cells(a[w], f.name)
            if not cells:
                empty += 1
                row["c"].append(None)
                continue
            first = cells[0]
            if f.type == "enum" and first.value in GAP_VALUES:
                gap += 1
            out: list[Any] = [first.value, first.quote[: site_corpus.MAX_QUOTE], first.anchor]
            if len(cells) > 1:
                out += [len(cells), list(dict.fromkeys(c.value for c in cells))]
            row["c"].append(out)
        columns.append(
            {
                "key": f"{info.name}.{f.name}",
                "name": f.name,
                "type": f.type,
                "group": f.group,
                "required": f.required,
                "empty": empty,
                "gap": gap,
            }
        )
    return {
        "miner": info.name,
        "version": info.version,
        "columns": columns,
        "rows": rows,
        "works_read": len(works),
        "included": len(data.sets.included),
        "not_read": len(data.sets.included) - len(works),
        "multi_row": any(len(v) > 1 for v in a.values()),
        "gap_values": sorted(GAP_VALUES),
        "methods": METHODS["grid"],
    }


def grid_payloads(
    data: MiningData, atts: Mapping[str, Attributed] | None = None
) -> dict[str, dict[str, Any]]:
    """`grid-<miner>` name -> payload, for every miner in the mining data."""
    atts = atts or attributions(data)
    return {
        grid_name(i.name): miner_grid(data, i, atts[i.name])
        for i in sorted(data.miners, key=lambda m: m.name)
    }


def grid_manifest(grids: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Name, miner, works read, column count and JSON size in bytes of every grid payload."""
    return [
        {
            "name": name,
            "miner": g["miner"],
            "works_read": g["works_read"],
            "columns": len(g["columns"]),
            "bytes": len(_dumps(g).encode("utf-8")),
        }
        for name, g in sorted(grids.items())
    ]


# ------------------------------------------------------------------ labels

STAGE_NAMES: dict[str, str] = {
    "literature-review": "Literature review",
    "ideation-hypothesis": "Ideation and hypotheses",
    "experiment-design": "Experiment design",
    "implementation-execution": "Implementation and execution",
    "data-analysis": "Data analysis",
    "paper-writing": "Paper writing",
    "review-verification": "Review and verification",
    "other": "Other stages",
}
TECH_MINER_GROUP = "Technique per stage"
OTHER_GROUP = "Other miners"
# (title, group, blurb) of the miners the pilot registers; any other miner is titled from its name.
MINER_META: dict[str, tuple[str, str, str]] = {
    "m-descriptors": (
        "Descriptors",
        "Describe the paper",
        "The paper's own words for its domain, system, data and process.",
    ),
    "m-summary": (
        "Contribution summary",
        "Describe the paper",
        "What the paper contributes, how it innovates, what it builds on and where it stops.",
    ),
    "m-classification": (
        "Classification",
        "Describe the paper",
        "Sorts each paper into fixed categories: technique, field, data, architecture, evaluation.",
    ),
    "m-mapping": (
        "Human role and span",
        "Describe the paper",
        "Where a human sits in the loop and how much of the research cycle is automated.",
    ),
    "m-layer": (
        "Layer",
        "Describe the paper",
        "How central the paper is to the question: core, benchmark, applied, adjacent or "
        "background.",
    ),
    "m-release": (
        "Code and data release",
        "Describe the paper",
        "Whether code and data are released, and how freely.",
    ),
    "m-stages": (
        "Stages covered",
        "Trace the process",
        "Which research stages the system covers, and whether a machine or a person does each.",
    ),
    "m-stage-steps": (
        "Steps in each stage",
        "Trace the process",
        "The steps inside each stage, in the order the paper describes them.",
    ),
    "m-design-approach": (
        "Results by approach",
        "Trace the process",
        "One row per reported result: stage, approach, metric and the number as printed.",
    ),
    "m-lifecycle": (
        "Lifecycle links",
        "Trace the process",
        "How the stages hand work to one another across the research lifecycle.",
    ),
    "m-claims": (
        "Claims",
        "Claims",
        "The claims a paper makes, each tied to the sentence that makes it.",
    ),
}
# Enum values whose label is not the value with dashes turned into spaces.
VALUE_LABELS: dict[str, str] = {
    "ideation-to-experiment": "Ideation → experiment",
    "experiment-to-analysis": "Experiment → analysis",
    "computer-science-ml": "Computer science / ML",
    "biology-life-sciences": "Biology / life sciences",
    "medicine-health": "Medicine / health",
    "physics-astronomy": "Physics / astronomy",
    "earth-climate-energy": "Earth / climate / energy",
    "social-behavioural": "Social / behavioural",
    "llm-judge": "LLM judge",
    "baselines-ablation": "Baselines / ablation",
    "omics-biological": "Omics / biological",
    "simulation-synthetic": "Simulation / synthetic",
    "images-signals": "Images / signals",
    "knowledge-graphs-databases": "Knowledge graphs / databases",
    "multi-domain": "Multi-domain",
}


def _cap(name: str) -> str:
    words = name.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def miner_label(name: str, rationale: str) -> dict[str, str]:
    """Title, group and one-line blurb of a miner: the pilot's wording, the stage name for a
    technique miner (`m-tech-<stage>`), else the name itself and the first 100 characters of the
    rationale."""
    if name in MINER_META:
        title, group, blurb = MINER_META[name]
        return {"title": title, "group": group, "blurb": blurb}
    stage = name.removeprefix("m-tech-") if name.startswith("m-tech-") else None
    if stage is not None:
        label = STAGE_NAMES.get(stage, _cap(stage))
        where = (
            "stages outside the main seven"
            if stage == "other"
            else "its " + label.lower() + " stage"
        )
        return {
            "title": label,
            "group": TECH_MINER_GROUP,
            "blurb": f"Which techniques the system uses in {where}.",
        }
    return {
        "title": _cap(name.removeprefix("m-")),
        "group": OTHER_GROUP,
        "blurb": rationale[:100],
    }


def labels_payload(data: MiningData) -> dict[str, Any]:
    """Display labels generated from the registered specs: miners, fields and enum values."""
    fields: dict[str, str] = {}
    values: dict[str, str] = {}
    for info in data.miners:
        for f in info.fields:
            fields[f.name] = _cap(f.name)
            for v in f.values:
                values[v] = VALUE_LABELS.get(v) or _cap(v)
    return {
        "miners": {m.name: miner_label(m.name, m.spec.rationale) for m in data.miners},
        "fields": dict(sorted(fields.items())),
        "values": dict(sorted(values.items())),
    }


# ------------------------------------------------------------------ codebook


def codebook_from(specs: Mapping[str, TaxonomySpec]) -> dict[str, dict[str, str]]:
    """Technique code -> stage and label, from the technique taxonomies (`t-tech-<stage>`)."""
    out: dict[str, dict[str, str]] = {}
    for name in sorted(specs):
        if not name.startswith(TECH_PREFIX):
            continue
        stage = name[len(TECH_PREFIX) :]
        for dim in specs[name].dimensions:
            for cat in dim.categories:
                out.setdefault(cat.id, {"stage": stage, "label": cat.name})
    return out


def load_codebook(project: Project) -> dict[str, dict[str, str]]:
    """`codebook_from` the latest registered version of each technique taxonomy."""
    latest: dict[str, int] = {}
    for row in list_taxonomies(project):
        if row.name.startswith(TECH_PREFIX):
            latest[row.name] = max(latest.get(row.name, 0), row.version)
    specs = {
        n: s for n, v in latest.items() if (s := registered_taxonomy(project, n, v)) is not None
    }
    return codebook_from(specs)


# ------------------------------------------------------------------ loaders


def _chosen_versions(project: Project) -> list[tuple[MinerInfo, int]]:
    by_name: dict[str, list[Any]] = defaultdict(list)
    for entry in mining_service.miner_listing(project):
        by_name[entry.name].append(entry)
    out: list[tuple[MinerInfo, int]] = []
    for name in sorted(by_name):
        entries = by_name[name]
        listed = [e for e in entries if e.listed]
        pick = max(listed or entries, key=lambda e: e.version)
        spec = mining_service.registered_miner(project, name, pick.version)
        if spec is not None:
            out.append((miner_info(spec, pick.listed), pick.version))
    return out


def load_rows(project: Project, schemas: Mapping[str, str]) -> dict[str, tuple[MRow, ...]]:
    """Live rows of the given `schema_ref -> miner name`, with their cells."""
    grouped: dict[str, dict[str, tuple[str, str, dict[str, Cell]]]] = defaultdict(dict)
    with project.index.connect() as conn:
        for eid, work, label, schema in conn.execute(
            text(
                "SELECT extraction_id, work_id, pass_label, schema_ref FROM extraction_rows "
                "WHERE superseded_by IS NULL"
            )
        ):
            if str(schema) in schemas:
                grouped[schemas[str(schema)]][str(eid)] = (str(work), str(label), {})
        index = {e: cells for per in grouped.values() for e, (_w, _l, cells) in per.items()}
        for eid, name, value, quote, anchor in conn.execute(
            text("SELECT extraction_id, field, value, quote, anchor FROM extraction_fields")
        ):
            cells = index.get(str(eid))
            if cells is not None:
                cells[str(name)] = Cell(str(value or ""), str(quote or ""), str(anchor or ""))
    return {
        miner: tuple(MRow(e, w, label, cells) for e, (w, label, cells) in sorted(per.items()))
        for miner, per in grouped.items()
    }


def load_models(project: Project) -> dict[str, tuple[str, ...]]:
    """`"<miner>|<pass>"` -> the models of the sessions that joined that pass, sorted."""
    found: dict[str, set[str]] = defaultdict(set)
    with project.index.connect() as conn:
        for scope, label, model in conn.execute(
            text("SELECT scope, pass_label, model FROM extraction_sessions")
        ):
            found[f"{scope}|{label}"].add(str(model))
    return {k: tuple(sorted(v)) for k, v in found.items()}


def _load_titles(project: Project, ids: Iterable[str]) -> dict[str, str]:
    wanted = set(ids)
    out: dict[str, str] = {}
    with project.index.connect() as conn:
        for w, data in conn.execute(text("SELECT work_id, data FROM works")):
            if str(w) in wanted:
                out[str(w)] = str(json.loads(str(data)).get("title") or w)
    return out


def load_mining_data(
    project: Project, sets: Sets | None = None, with_platform: bool = True
) -> MiningData:
    """Read the miners, their live rows, session models, titles, codebook and (unless
    `with_platform` is False) the recorded platform agreement. `sets` defaults to the flow data's
    (which computes the ledger; pass it in when it is already at hand)."""
    project.index.sync()
    chosen = _chosen_versions(project)
    sets = sets or load_flow_data(project).sets
    schemas = {f"{i.name}@{v}": i.name for i, v in chosen}
    platform: dict[str, tuple[float | None, float | None]] = {}
    if with_platform:
        platform = {
            s.name: (s.agreement, s.agreement_aligned) for s in mining_service.mine_status(project)
        }
    return MiningData(
        miners=tuple(i for i, _v in chosen),
        rows=load_rows(project, schemas),
        models=load_models(project),
        sets=sets,
        titles=_load_titles(project, sets.included),
        platform=platform,
        codebook=load_codebook(project),
    )


# ------------------------------------------------------------------ payload


def mining_payload_from(
    data: MiningData, grids: Mapping[str, Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """The Miners and Data page payload. Its `grids` manifest lists the per-miner grid payloads
    (`grid_payloads`), which pages load on demand; pass them in when already computed."""
    atts = attributions(data)
    if grids is None:
        grids = grid_payloads(data, atts)
    return {
        "miners": miners(data, atts),
        "coverage": coverage(data, atts),
        "holes": holes(data, atts),
        "codebook": {k: dict(v) for k, v in sorted(data.codebook.items())},
        "columns": _catalogue(data, atts),
        "grids": grid_manifest(grids),
        "sets": sets_payload(data.sets),
        "labels": labels_payload(data),
        "methods": METHODS,
    }


def mining_payload(
    project: Project, sets: Sets | None = None, with_platform: bool = True
) -> dict[str, Any]:
    """`mining_payload_from` the project's data."""
    return mining_payload_from(load_mining_data(project, sets, with_platform))
