"""The `leaderboard` hub payload (spec slice-7-hub-scope HS-50 to HS-55): one entry per final row of
the project's results miner, plus the whole-corpus ranking computed from them.

Invariants:
- `build` is pure over its `HubContext`: it reads the index, the vocabulary and (only when a second
  pass exists) the final rows service; it writes nothing and calls no model or network.
- The source is the results miner, found by its fields (`find_results_miner`): the registered miner
  with `model_role`, `metric` and `value` among its fields, listed ones first. Rows are the final
  rows of pass A: with no pass B recorded, every live pass-A row (a single reading); once pass B
  exists, the final rows of the extraction service (`agreed`, `resolved`, `single`), so a row with
  an unresolved disagreement never appears.
- Spellings of dataset, metric and setting are merged only through the approved vocabulary
  (`PropertyDef.value_aliases` of the properties named in `DIMENSIONS`). Nothing is hard-coded; an
  unapproved proposal is invisible here. Each row keeps `[as extracted, as merged]`.
- A generic own-model name ("Ours", "our model", ...) is replaced by a name from a model-card miner
  field (`NAME_FIELDS`), else by the paper's short id; the rule is `NAME_RULE`. A baseline row is
  never renamed.
- Values are read as numbers: a trailing `%` is dropped; above 1 they are divided by 100; a value
  still above 1 or not a number is skipped and counted (`skipped`). Nothing is typed by hand.
- `rank` is the one definition of Part A (own models) and Part B (re-reported baselines); the page
  runs the same steps over the rows whose source work is in scope (HS-22), and a test compares them.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from factory.model.cards import PropertyDef
from factory.model.extraction import MinerScope
from factory.services import site_corpus
from factory.services.extraction_agreement import FinalRow, final_rows
from factory.services.hub_mining import Cell, MinerInfo, MiningData, attribute_rows
from factory.services.properties import resolve_property

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

# Payload name and the event type prefixes it reads (`hub_build.PAYLOAD_INPUTS`).
NAME: Final = "leaderboard"
EVENT_PREFIXES: Final[tuple[str, ...]] = (
    "extraction.",
    "mine.",
    "miner.",
    "taxonomy.",
    "vocabulary.",
    "protocol.",
    "work.",
    "reference.",
    "screening.",
    "fulltext.",
    "search.",
    "import.",
    "dedup.",
    "decision.",
    "document.",
    "gate.",
)

# Result-row dimension -> (miner field, key of the approved property that merges its spellings).
DIMENSIONS: Final[dict[str, tuple[str, str]]] = {
    "dataset": ("dataset", "pr:leaderboard-dataset"),
    "metric": ("metric", "pr:leaderboard-metric"),
    "setting": ("setting", "pr:leaderboard-setting"),
}
REQUIRED_FIELDS: Final = frozenset({"model_role", "metric", "value"})
NAME_FIELDS: Final = ("model_name", "model_name_quote")  # in order of preference
MAX_NAME: Final = 60
MIN_MODELS: Final = 3  # Part A: a table needs this many models
MIN_PAPERS: Final = 4  # Part B: a baseline needs this many source papers
TOP: Final = 15  # Part A rows shown per table
QUOTE_CUT: Final = site_corpus.MAX_QUOTE
OVER_ONE: Final = 1.0001  # a share above this is read as a percentage

GENERIC = re.compile(
    r"\s*[\(\[]?\b(ours|our model|our method|our approach|proposed( method| model)?)\b[\)\]]?\s*",
    re.I,
)
SIZE_ONLY = re.compile(r"-?\d+[A-Za-z]*")

NAME_RULE: Final = (
    "An own-model row whose name is generic (it contains ours, our model, our method, our approach "
    "or proposed method/model) is named after the paper's own model: the first non-empty pass-A "
    "value of the field model_name, else model_name_quote, in the first miner (by name) that has "
    "it, kept when at most 60 characters; otherwise the paper's short id (the first word of its "
    "work id). A name that is only a size (for example 7B) is joined to it (VoxForge-7B). A "
    "generic name with a qualifier (Ours w/o pretraining) keeps the qualifier. Baselines keep "
    "their names."
)
VOCAB_RULE: Final = (
    "Spellings of dataset, metric and setting are merged through the approved properties "
    "pr:leaderboard-dataset, pr:leaderboard-metric and pr:leaderboard-setting: a value (compared "
    "without case, spaces, hyphens and punctuation) that equals an allowed value or one of its "
    "value aliases becomes that allowed value. A property that is not approved changes nothing."
)
ACCESS_RULE: Final = (
    "A row is public when its data_access says public. A row that says not-stated (or nothing) "
    "counts as public when its merged dataset has at least one row that says public and none that "
    "says private or mixed. Part A uses public rows only."
)
METHODS: Final[dict[str, str]] = {
    "source": (
        "Rows of the project's results miner (the registered miner with the fields model_role, "
        "metric and value). With no second pass these are the live pass-A rows; once pass B "
        "exists, only the final rows (agreed, resolved or single), never a row with an open "
        "disagreement. Unaudited unless an audit says otherwise."
    ),
    "names": NAME_RULE,
    "vocabulary": VOCAB_RULE,
    "access": ACCESS_RULE,
    "values": (
        "A value is read as a number; a trailing % is dropped and a value above 1 is divided by "
        "100. A value that is still above 1 or not a number is left out and counted."
    ),
    "part_a": (
        "Own models only. Per table (task, dataset, setting, metric) the best value of each "
        f"(model, paper); public datasets only; a table needs at least {MIN_MODELS} models; "
        f"ranked by value, the top {TOP} shown."
    ),
    "part_b": (
        "Baselines only: per baseline name, task, dataset, setting and metric, the best value each "
        f"source paper reported; listed when at least {MIN_PAPERS} papers reported it. A wide "
        "spread means the papers do not reproduce the same number."
    ),
    "scope": (
        "A row is in scope when the paper that reports it is in scope. A baseline row whose "
        "source paper is out of scope is hidden and counted; it is never kept as a reference or "
        "attributed to another paper."
    ),
}


# ------------------------------------------------------------------ vocabulary


def load_vocabulary(project: Any) -> dict[str, PropertyDef]:
    """Dimension -> its approved definition (merges followed); a dimension with none is absent."""
    out: dict[str, PropertyDef] = {}
    for dim, (_field, key) in DIMENSIONS.items():
        definition = resolve_property(project, key)
        if definition is not None:
            out[dim] = definition
    return out


def spelling_key(text: str) -> str:
    """The comparison key of a spelling: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def merge_table(definition: PropertyDef | None) -> dict[str, str]:
    """Spelling key -> allowed value, from the allowed values and their aliases (the first
    allowed value in sorted order wins a key two of them share)."""
    if definition is None:
        return {}
    table: dict[str, str] = {}
    for token in sorted(definition.allowed):
        for spelling in (token, *definition.value_aliases.get(token, ())):
            k = spelling_key(spelling)
            if k:
                table.setdefault(k, token)
    return table


def merged(table: Mapping[str, str], raw: str) -> str:
    """`raw` after the merge table; unchanged when the table has no entry for it."""
    return table.get(spelling_key(raw), raw)


# ------------------------------------------------------------------ source


def find_results_miner(data: MiningData) -> MinerInfo | None:
    """The miner whose fields include `REQUIRED_FIELDS`: listed ones first, then by name."""
    found = [m for m in data.miners if {f.name for f in m.fields} >= REQUIRED_FIELDS]
    found.sort(key=lambda m: (not m.listed, m.name))
    return found[0] if found else None


def short_id(work: str) -> str:
    """The first word of a work id's slug (`rf:abaid2025-3d-ct-...-a93fed12` -> `abaid2025`)."""
    return work.split(":", 1)[-1].split("-", 1)[0]


def model_card_names(data: MiningData, results: str) -> tuple[dict[str, str], dict[str, str]]:
    """Work id -> the model name its model-card field gives, and work id -> `<miner>.<field>`.

    Only pass-A rows of included works are read, `NAME_FIELDS` in order of preference, miners in
    name order, the first non-empty value of at most `MAX_NAME` characters."""
    names: dict[str, str] = {}
    origin: dict[str, str] = {}
    for fname in NAME_FIELDS:
        for info in sorted(data.miners, key=lambda m: m.name):
            if info.name == results or fname not in {f.name for f in info.fields}:
                continue
            att = attribute_rows(data.rows.get(info.name, ()), data.sets)
            for work, rows in att.by_pass.get("A", {}).items():
                if work in names:
                    continue
                for r in rows:
                    cell = r.cells.get(fname)
                    value = " ".join(cell.value.split()) if cell else ""
                    if value and len(value) <= MAX_NAME:
                        names[work] = value
                        origin[work] = f"{info.name}.{fname}"
                        break
    return names, origin


def own_name(raw: str, work: str, names: Mapping[str, str]) -> tuple[str, str]:
    """(name, how) for an own-model row: `how` is `""` (unchanged), `card` or `short-id`."""
    if not GENERIC.search(raw):
        return raw, ""
    rest = GENERIC.sub(" ", raw).strip(" -\u2013\u2014:()[]")
    card = names.get(work)
    how = "card" if card else "short-id"
    base = card or short_id(work)
    if not rest:
        return base, how
    if SIZE_ONLY.fullmatch(rest):
        return f"{base}-{rest.strip('-')}", how
    return rest, ""


@dataclass(frozen=True)
class _Rec:
    work: str
    cells: Mapping[str, Cell]


def _records(data: MiningData, info: MinerInfo, finals: Sequence[FinalRow] | None) -> list[_Rec]:
    """The rows read: pass A as recorded, or the final rows when a second pass exists."""
    if finals is None:
        att = attribute_rows(data.rows.get(info.name, ()), data.sets)
        out = [_Rec(w, r.cells) for w, rows in att.by_pass.get("A", {}).items() for r in rows]
        return sorted(out, key=lambda r: r.work)
    included = set(data.sets.included)
    canon = {d.mined_id: d.canonical_id for d in data.sets.duplicate_mapped}
    recs: list[_Rec] = []
    for fr in finals:
        work = fr.work_id if fr.work_id in included else canon.get(fr.work_id, "")
        if work not in included:
            continue
        cells = {n: Cell(str(f.value), f.quote or "", f.anchor or "") for n, f in fr.fields.items()}
        recs.append(_Rec(work, cells))
    return sorted(recs, key=lambda r: r.work)


def _number(text: str) -> float | None:
    try:
        v = float(text.replace("%", "").strip())
    except ValueError:
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    if v > OVER_ONE:
        v /= 100
    return v if 0 <= v <= OVER_ONE else None


def _val(rec: _Rec, name: str) -> str:
    c = rec.cells.get(name)
    return c.value.strip() if c else ""


def build_rows(
    data: MiningData,
    info: MinerInfo,
    vocab: Mapping[str, PropertyDef],
    finals: Sequence[FinalRow] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The leaderboard rows and the counts of what was skipped (`value`: no usable number)."""
    tables = {dim: merge_table(vocab.get(dim)) for dim in DIMENSIONS}
    names, _origin = model_card_names(data, info.name)
    skipped = {"value": 0}
    rows: list[dict[str, Any]] = []
    for rec in _records(data, info, finals):
        number = _number(_val(rec, "value"))
        if number is None:
            skipped["value"] += 1
            continue
        role = _val(rec, "model_role")
        raw_model = _val(rec, "model_name")
        model, how = own_name(raw_model, rec.work, names) if role == "own" else (raw_model, "")
        vcell = rec.cells.get("value") or Cell("")
        dims: dict[str, list[str]] = {}
        for dim, (field, _key) in DIMENSIONS.items():
            raw = _val(rec, field)
            dims[dim] = [raw, merged(tables[dim], raw)]
        rows.append(
            {
                "w": rec.work,
                "p": data.published.get(rec.work, ""),
                "t": _val(rec, "task"),
                "m": model,
                "mr": raw_model,
                "mh": how,
                "r": role,
                "d": dims["dataset"],
                "s": dims["setting"],
                "x": dims["metric"],
                "v": round(number, 6),
                "vr": _val(rec, "value"),
                "g": _val(rec, "averaging"),
                "ac": _val(rec, "data_access"),
                "q": (vcell.quote or _val(rec, "result_quote"))[:QUOTE_CUT],
                "a": vcell.anchor,
            }
        )
    _effective_access(rows)
    return rows, skipped


def _effective_access(rows: list[dict[str, Any]]) -> None:
    """Set `ap` (public, or the stated value) on every row; see `ACCESS_RULE`."""
    stated: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        stated[r["d"][1]].add(r["ac"])
    for r in rows:
        said = stated[r["d"][1]]
        inherited = (
            r["ac"] in ("", "not-stated") and "public" in said and not said & {"private", "mixed"}
        )
        r["ap"] = "public" if r["ac"] == "public" or inherited else (r["ac"] or "not-stated")


# ------------------------------------------------------------------ ranking (Part A, Part B)


def rank(rows: Iterable[Mapping[str, Any]], works: Collection[str] | None = None) -> dict[str, Any]:
    """Part A tables, Part B baselines and the rows hidden by a scope.

    `works` is the set of works in scope (None: every work). A baseline row of a work outside it
    counts in `hidden_baseline_rows`; an own row of such a work counts in `hidden_own_rows`.
    Tables are by (task, metric, dataset, setting), most models first."""
    best_own: dict[tuple[str, str, str, str], dict[tuple[str, str], Mapping[str, Any]]] = (
        defaultdict(dict)
    )
    best_base: dict[tuple[str, str, str, str, str], dict[str, Mapping[str, Any]]] = defaultdict(
        dict
    )
    hidden_base = hidden_own = 0
    for r in rows:
        if works is not None and r["w"] not in works:
            if r["r"] == "baseline":
                hidden_base += 1
            elif r["r"] == "own":
                hidden_own += 1
            continue
        if r["ap"] != "public":
            continue
        if r["r"] == "own":
            key = (r["t"], r["x"][1], r["d"][1], r["s"][1])
            slot = best_own[key]
            who = (r["m"], r["w"])
            if who not in slot or r["v"] > slot[who]["v"]:
                slot[who] = r
        elif r["r"] == "baseline":
            name = re.sub(r"\s+", " ", r["m"]).strip()
            bkey = (name, r["t"], r["x"][1], r["d"][1], r["s"][1])
            bslot = best_base[bkey]
            if r["w"] not in bslot or r["v"] > bslot[r["w"]]["v"]:
                bslot[r["w"]] = r
    tables: list[dict[str, Any]] = []
    for (task, metric, dataset, setting), slot in best_own.items():
        if len(slot) < MIN_MODELS:
            continue
        ranked = sorted(slot.values(), key=lambda r: (-r["v"], r["m"], r["w"]))
        tables.append(
            {
                "task": task,
                "metric": metric,
                "dataset": dataset,
                "setting": setting,
                "models": len(slot),
                "top": [_entry(r) for r in ranked[:TOP]],
            }
        )
    tables.sort(key=lambda t: (t["task"], t["metric"], -t["models"], t["dataset"], t["setting"]))
    baselines: list[dict[str, Any]] = []
    for (name, task, metric, dataset, setting), bslot in best_base.items():
        if len(bslot) < MIN_PAPERS:
            continue
        vs = [r["v"] for r in bslot.values()]
        baselines.append(
            {
                "model": name,
                "task": task,
                "metric": metric,
                "dataset": dataset,
                "setting": setting,
                "papers": len(vs),
                "median": round(statistics.median(vs), 6),
                "min": min(vs),
                "max": max(vs),
            }
        )
    baselines.sort(
        key=lambda b: (-b["papers"], b["model"], b["task"], b["metric"], b["dataset"], b["setting"])
    )
    return {
        "tables": tables,
        "baselines": baselines,
        "hidden_baseline_rows": hidden_base,
        "hidden_own_rows": hidden_own,
    }


def _entry(r: Mapping[str, Any]) -> dict[str, Any]:
    return {"model": r["m"], "work": r["w"], "value": r["v"], "averaging": r["g"]}


# ------------------------------------------------------------------ payload


def payload_from(
    data: MiningData,
    vocab: Mapping[str, PropertyDef],
    finals: Sequence[FinalRow] | None = None,
) -> dict[str, Any]:
    """The `leaderboard` payload (module docstring); an empty one when no results miner exists."""
    info = find_results_miner(data)
    base: dict[str, Any] = {
        "miner": None,
        "version": None,
        "second_pass": finals is not None,
        "rows": [],
        "works": [],
        "skipped": {"value": 0},
        "whole": rank([]),
        "vocabulary": {
            dim: {"key": key, "approved": dim in vocab, "allowed": len(vocab[dim].allowed)}
            if dim in vocab
            else {"key": key, "approved": False, "allowed": 0}
            for dim, (_f, key) in DIMENSIONS.items()
        },
        "name_sources": [],
        "constants": {"min_models": MIN_MODELS, "min_papers": MIN_PAPERS, "top": TOP},
        "methods": dict(METHODS),
    }
    if info is None:
        return base
    rows, skipped = build_rows(data, info, vocab, finals)
    works = sorted({r["w"] for r in rows})
    names, origin = model_card_names(data, info.name)
    base.update(
        miner=info.name,
        version=info.version,
        rows=rows,
        works=[{"id": w, "published": data.published.get(w, "")} for w in works],
        skipped=skipped,
        whole=rank(rows),
        name_sources=sorted({o for o in origin.values()}),
        titles={w: data.titles.get(w, "") for w in works},
    )
    base["constants"]["names_from_cards"] = len(names)
    return base


def build(ctx: HubContext) -> dict[str, Any]:
    """The `leaderboard` payload of the project (see `payload_from`)."""
    data = ctx.mining_data
    info = find_results_miner(data)
    finals: list[FinalRow] | None = None
    if info is not None and any(r.pass_label == "B" for r in data.rows.get(info.name, ())):
        finals = final_rows(ctx.project, scope=MinerScope(info.name))
    return payload_from(data, load_vocabulary(ctx.project), finals)
