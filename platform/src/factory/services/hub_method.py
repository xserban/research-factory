# ruff: noqa: E501
"""The `method` hub payload: Lifecycle, Steps and Taxonomy (plan hub-ui-port-all, step 4).

It wraps existing services and re-derives no number they compute:
- Lifecycle: `site_lifecycle.lifecycle_data` (works per stage, layer and mode, from `m-stages`) and
  `own_stage_sequences` (each paper's own stages, from pass A of `m-lifecycle`). New here is the
  overall stage-sequence analysis (ruling P4): the free-text stage names of the papers are grouped
  onto the nine `m-stages` stages by the deterministic rules in `STAGE_RULES`, then transitions,
  loops, most common orders and entry/exit counts are counted over each paper's ordered sequence.
- Steps: `site_steps.step_rows` / `steps_view` (exploratory miner `m-stage-steps`).
- Taxonomy: registered versions (`taxonomies`, `site_taxonomy_registered`) with the computed diff
  between consecutive versions, plus the earlier unregistered `taxonomy.json` kept as it was.

Invariants:
- `build` is pure over its `HubContext` and reads no network; the same project gives the same
  payload (every list is sorted, every tie broken by a fixed key).
- The name map is a constant. A stage name that no rule matches goes to `other` and is listed as
  unmapped, never dropped.
- Every count is computed from rows; no sentence in `methods` carries a digit.
"""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from factory.mining.taxonomy import Category, Dimension, TaxonomyDiff, TaxonomySpec, diff, full_id
from factory.services import taxonomies as tax_service
from factory.services.site_lifecycle import (
    LAYER_ORDER,
    MODES,
    STAGES,
    lifecycle_data,
    own_stage_sequences,
)
from factory.services.site_steps import ACTORS, MINER, OPTIONAL, step_rows, steps_view
from factory.services.site_taxonomy_registered import DerivedMiner, _dates, derived_miner

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.context import Project
    from factory.services.hub_build import HubContext

OTHER = "other"
TOP_ORDERS = 10
LEGACY_FILE = "taxonomy.json"
_STAGE_IDS: tuple[str, ...] = tuple(i for i, _ in STAGES)

# Name map (ruling P4). A paper's stage name is lower-cased, its punctuation turned into spaces, and
# tested against these rules in order; the first rule with a keyword that occurs in the name wins.
# The order settles overlaps: "literature review" is a literature stage before it is a review
# stage; "experiment design" is a design stage before it is an execution stage. A name that no rule
# matches maps to `other` and is shown as unmapped. Keywords are word stems, matched as substrings.
STAGE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lab-automation", ("lab ", "robot", "wet lab", "physical", "instrument")),
    (
        "literature-review",
        ("literature", "related work", "prior work", "survey", "background", "paper search"),
    ),
    ("paper-writing", ("writing", "write", "manuscript", "draft", "report", "paper generation")),
    (
        "review-verification",
        (
            "review",
            "verif",
            "validat",
            "critique",
            "critic",
            "peer",
            "check",
            "feedback",
            "evaluat",
        ),
    ),
    ("ideation-hypothesis", ("idea", "ideation", "hypothes", "brainstorm", "novelty", "proposal")),
    ("experiment-design", ("design", "plan", "protocol")),
    ("data-analysis", ("analy", "interpret", "statistic", "visuali", "insight", "result")),
    (
        "implementation-execution",
        (
            "implement",
            "execut",
            "experiment",
            "coding",
            "code",
            "simulat",
            "train",
            "build",
            "develop",
            "collect",
        ),
    ),
)

METHODS: dict[str, str] = {
    "lifecycle_flow": (
        "<b>What it shows</b>: how often papers cover each stage of an AI research system and which "
        "stages the same papers cover together."
        "<p><span class=k>How to read it.</span> Each node is one of the nine stages of the stages "
        "miner; its size is the number of papers that cover it. An arc joins two stages that the same "
        "papers cover; thicker means more papers. The left-to-right order is a layout convention, not a "
        "finding. Click a node or an arc to list its papers with the quote behind each row.</p>"
        "<p><span class=k>How it's computed.</span> Papers are counted from the live pass-A rows of the "
        "stages miner under the chosen layer and mode. The layer pass is not calibrated. The view "
        "is in the address, so it can be linked.</p>"
    ),
    "stage_matrix": (
        "<b>What it shows</b>: papers per stage and layer."
        "<p><span class=k>How it's computed.</span> A paper counts once in a cell when it has a row for "
        "that stage and sits in that layer. Each count opens the list for that stage and layer.</p>"
    ),
    "stage_mode": (
        "<b>What it shows</b>: how each stage is covered: automated, human-assisted or only mentioned."
        "<p><span class=k>How it's computed.</span> Papers with at least one row for the stage in that "
        "mode. A paper can count in several modes of one stage.</p>"
    ),
    "stage_count": (
        "<b>What it shows</b>: how many different stages a single paper covers."
        "<p><span class=k>How it's computed.</span> Distinct stages with at least one row, per paper, "
        "over papers with any stage row.</p>"
    ),
    "stage_technique": (
        "<b>What it shows</b>: which technique goes with which automated stage."
        "<p><span class=k>How it's computed.</span> Papers per stage and primary technique, counting only "
        "rows whose mode is automated or human-assisted; mentioned-only rows are left out.</p>"
    ),
    "sequences": (
        "<b>What it shows</b>: the order in which papers run the stages, across all papers."
        "<p><span class=k>How to read it.</span> Arcs above the line go forward in the usual research "
        "cycle, arcs below go back. Thickness is the number of papers. Click an arc to see the papers "
        "that take that step.</p>"
        "<p><span class=k>How it's computed.</span> Every paper's stages come from pass A of the "
        "lifecycle miner, in the paper's own order. Each stage name is grouped onto one of the nine "
        "stages by a fixed name map, shown below; names the map does not know go to other and are listed "
        "as unmapped. Steps that stay in one stage are merged. A transition counts each paper once; a "
        "loop back is read from the paper's own statement of where it returns, and is counted apart from "
        "forward transitions. Until the production run these rows are the calibration sample only and "
        "are not yet checked against the gold labels.</p>"
    ),
    "stage_map": (
        "<b>What it shows</b>: how each stage name that papers use was grouped onto the nine stages."
        "<p><span class=k>How it's computed.</span> A fixed list of keyword rules, tried in order, on the "
        "lower-cased name. The first rule that matches decides; no match means other. The rules are "
        "listed with the table, so any grouping can be checked and the rules corrected.</p>"
    ),
    "steps": (
        "<b>What it shows</b>: the steps an AI research system takes in each stage, paper by paper, in "
        "the paper's own order, with who does each one."
        "<p><span class=k>How it's computed.</span> Closed pass-A rows of the latest version of the steps "
        "miner. The miner has no calibration: the rows are for reading, not evidence. A field that the "
        "paper does not state is shown as not stated, never as a value.</p>"
    ),
    "taxonomy": (
        "<b>What it shows</b>: the project's registered taxonomies, one entry per version, with the "
        "categories, their definitions and how many papers sit in each."
        "<p><span class=k>How it's computed.</span> Counts are papers with a current pass-A row in the "
        "category, taken from the miner that projects the version. The changes from the previous version "
        "are computed by comparing the two versions, never typed.</p>"
        "<p><span class=k>What you can do.</span> Split a broad category, record a revised taxonomy as a "
        "new version, then run the classification miner again; its old rows stay.</p>"
    ),
}


# ---------------------------------------------------------------- the stage-name map


def normalise(name: str) -> str:
    """The name lower-cased, punctuation turned into spaces, whitespace collapsed."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.lower()).split())


def map_stage(name: str) -> str | None:
    """The `m-stages` stage id the name is grouped onto, or None when no rule matches. Pure."""
    padded = normalise(name) + " "
    for stage, keywords in STAGE_RULES:
        if any(k in padded for k in keywords):
            return stage
    return None


def _stage_of(name: str) -> tuple[str, bool]:
    stage = map_stage(name)
    return (OTHER, False) if stage is None else (stage, True)


def _collapse(stages: Sequence[str]) -> list[str]:
    out: list[str] = []
    for s in stages:
        if not out or out[-1] != s:
            out.append(s)
    return out


def _no_loop(value: str) -> bool:
    """True when a `loops_back_to` value is empty or says there is no loop."""
    return normalise(value) in ("", "none", "no", "na", "n a", "null", "nil")


def _resolve_loop(
    loops: str, entries: Sequence[Mapping[str, Any]], stages: Sequence[str]
) -> str | None:
    """The stage a `loops_back_to` value points at: an order number or a stage name of the same
    paper, else a name the map knows; None when the value is empty, says none, or cannot be read."""
    value = loops.strip()
    if _no_loop(value):
        return None
    if value.isdigit():
        for e, s in zip(entries, stages, strict=True):
            if str(e["order"]).strip() == value:
                return s
        return None
    key = normalise(value)
    for e, s in zip(entries, stages, strict=True):
        if normalise(str(e["name"])) == key:
            return s
    return map_stage(value)


def sequence_analysis(seqs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Group the papers' own stage names and count the overall structure (LC-8, LC-10).

    `seqs` is `own_stage_sequences`. Returns `papers` (each with its mapped `path`, merged over
    repeats), `stage_map`, `unmapped`, `transitions` and `loops` (papers per edge, `times` its
    occurrences), `orders` (top ten full orders), `entry` and `exit` (papers per stage). Pure and
    order-independent: the same sequences in any order give the same result."""
    names: dict[str, dict[str, Any]] = {}
    papers: list[dict[str, Any]] = []
    transitions: Counter[tuple[str, str]] = Counter()
    trans_times: Counter[tuple[str, str]] = Counter()
    loops: Counter[tuple[str, str]] = Counter()
    loop_times: Counter[tuple[str, str]] = Counter()
    orders: Counter[tuple[str, ...]] = Counter()
    entry: Counter[str] = Counter()
    exit_: Counter[str] = Counter()
    unresolved_loops = 0
    repeats = 0
    for seq in sorted(seqs, key=lambda s: str(s["id"])):
        entries = list(seq["stages"])
        mapped = [_stage_of(str(e["name"])) for e in entries]
        stage_ids = [m[0] for m in mapped]
        seen_here: set[str] = set()
        for e, (stage_id, ok) in zip(entries, mapped, strict=True):
            key = normalise(str(e["name"]))
            row = names.setdefault(
                key, {"name": key, "rows": 0, "papers": 0, "stage": stage_id, "mapped": ok}
            )
            row["rows"] += 1
            if key not in seen_here:
                seen_here.add(key)
                row["papers"] += 1
        path = _collapse(stage_ids)
        repeats += len(stage_ids) - len(path)
        if path:
            orders[tuple(path)] += 1
            entry[path[0]] += 1
            exit_[path[-1]] += 1
        edges = list(itertools.pairwise(path))
        for edge in edges:
            trans_times[edge] += 1
        for edge in set(edges):
            transitions[edge] += 1
        paper_loops: list[tuple[str, str]] = []
        stages_out: list[dict[str, Any]] = []
        for e, (s_id, ok) in zip(entries, mapped, strict=True):
            raw = str(e.get("loops") or "")
            target = _resolve_loop(raw, entries, stage_ids)
            if not _no_loop(raw):
                if target is None:
                    unresolved_loops += 1
                else:
                    paper_loops.append((s_id, target))
                    loop_times[(s_id, target)] += 1
            stages_out.append(
                {
                    "order": str(e["order"]),
                    "name": str(e["name"]),
                    "stage": s_id,
                    "mapped": ok,
                    "actor": str(e.get("actor") or ""),
                    "how": str(e.get("how") or ""),
                    "next": str(e.get("next") or ""),
                    "loops": raw,
                    "loops_to": target,
                }
            )
        for edge in set(paper_loops):
            loops[edge] += 1
        papers.append(
            {
                "id": str(seq["id"]),
                "title": str(seq.get("title") or seq["id"]),
                "year": str(seq.get("year") or ""),
                "path": path,
                "stages": stages_out,
            }
        )
    order_index = {s: i for i, s in enumerate(_STAGE_IDS)}

    def edge_rows(
        papers_of: Counter[tuple[str, str]], times_of: Counter[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        return [
            {"from": a, "to": b, "n": n, "times": times_of[(a, b)]}
            for (a, b), n in sorted(
                papers_of.items(),
                key=lambda kv: (order_index[kv[0][0]], order_index[kv[0][1]]),
            )
        ]

    stage_map = sorted(
        (
            {
                "name": r["name"],
                "stage": r["stage"],
                "mapped": r["mapped"],
                "papers": r["papers"],
                "rows": r["rows"],
            }
            for r in names.values()
        ),
        key=lambda r: (order_index[str(r["stage"])], -int(r["papers"]), str(r["name"])),
    )
    return {
        "n_papers": len(papers),
        "n_rows": sum(len(p["stages"]) for p in papers),
        "repeats_merged": repeats,
        "unresolved_loops": unresolved_loops,
        "papers": papers,
        "stage_map": stage_map,
        "unmapped": sorted(
            (r for r in stage_map if not r["mapped"]),
            key=lambda r: (-int(r["papers"]), str(r["name"])),
        ),
        "transitions": edge_rows(transitions, trans_times),
        "loops": edge_rows(loops, loop_times),
        "orders": [
            {"path": list(p), "n": n}
            for p, n in sorted(orders.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_ORDERS]
        ],
        "entry": {s: entry.get(s, 0) for s in _STAGE_IDS},
        "exit": {s: exit_.get(s, 0) for s in _STAGE_IDS},
    }


# ---------------------------------------------------------------- lifecycle (m-stages)


def _technique(work: Mapping[str, Any]) -> str:
    cell = (work.get("cls") or {}).get("technique_primary")
    return str(cell["v"]) if cell and cell.get("v") else "not coded"


def lifecycle_view(
    works: Sequence[Mapping[str, Any]], layers: Mapping[str, str | None]
) -> dict[str, Any]:
    """`lifecycle_data` plus the work ids, the stage-by-layer matrix, the unfiltered co-occurrence
    arcs, stage by mode (RS-8), distinct stages per paper (RS-9) and stage by primary technique
    (RS-10). Pure: sorted by stage order, then by key."""
    data = lifecycle_data(works, layers)
    id_of = {str(w["slug"]): str(w["id"]) for w in works}
    for w in data["works"]:
        w["id"] = id_of.get(str(w["slug"]), str(w["slug"]))
    kept = {str(w["id"]) for w in data["works"]}
    raw = [w for w in sorted(works, key=lambda w: str(w["id"])) if str(w["id"]) in kept]
    by_stage = {s: [w for w in data["works"] if s in w["stages"]] for s in _STAGE_IDS}
    layer_ids = [str(lay["id"]) for lay in data["layers"]]
    matrix = [
        {
            "stage": s,
            "n": len(by_stage[s]),
            "layers": {lay: sum(1 for w in by_stage[s] if w["layer"] == lay) for lay in layer_ids},
        }
        for s in _STAGE_IDS
    ]
    arcs = [
        {"a": a, "b": b, "n": n}
        for i, a in enumerate(_STAGE_IDS)
        for b in _STAGE_IDS[i + 1 :]
        if (n := sum(1 for w in by_stage[a] if b in w["stages"]))
    ]
    stage_mode = [
        {
            "stage": s,
            "modes": {
                m: sum(1 for w in by_stage[s] if any(r["mode"] == m for r in w["stages"][s]))
                for m in MODES
            },
        }
        for s in _STAGE_IDS
    ]
    distinct = Counter(len(w["stages"]) for w in data["works"])
    techniques: dict[str, dict[str, int]] = {s: {} for s in _STAGE_IDS}
    for w in raw:
        tech = _technique(w)
        done: set[tuple[str, str]] = set()
        for r in w.get("stages") or ():
            if r.get("mode") in ("automated", "human-assisted") and str(r["stage"]) in techniques:
                key = (str(r["stage"]), tech)
                if key not in done:
                    done.add(key)
                    techniques[key[0]][tech] = techniques[key[0]].get(tech, 0) + 1
    tech_names = sorted({t for row in techniques.values() for t in row})
    data.update(
        {
            "layer_order": list(LAYER_ORDER),
            "matrix": matrix,
            "arcs": arcs,
            "stage_mode": stage_mode,
            "distinct_stages": [{"k": k, "n": distinct[k]} for k in sorted(distinct)],
            "stage_technique": {
                "techniques": tech_names,
                "rows": [
                    {"stage": s, "n": {t: techniques[s].get(t, 0) for t in tech_names}}
                    for s in _STAGE_IDS
                ],
            },
        }
    )
    return data


# ---------------------------------------------------------------- steps


def steps_payload(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`steps_view` plus the filter vocabularies and the totals; the page's ST-1 banner is static."""
    view = steps_view(rows)
    works = {str(w["id"]) for s in view["stages"] for w in s["works"]}
    return {
        "miner": MINER,
        "stages": view["stages"],
        "actors": list(ACTORS),
        "fields": [name for name, _ in OPTIONAL],
        "n_rows": len(rows),
        "n_works": len(works),
    }


# ---------------------------------------------------------------- taxonomy


def diff_rows(change: TaxonomyDiff) -> list[dict[str, str]]:
    """The computed changes as label and text rows, empty entries kept as `none` (TX-4)."""
    return [
        {"label": "added", "text": ", ".join(change.added)},
        {"label": "removed", "text": ", ".join(change.removed)},
        {"label": "redefined", "text": ", ".join(change.redefined)},
        {"label": "renamed", "text": ", ".join(change.renamed)},
        {
            "label": "split",
            "text": "; ".join(f"{p} into {', '.join(k)}" for p, k in change.split),
        },
        {
            "label": "merged",
            "text": "; ".join(f"{', '.join(p)} into {c}" for p, c in change.merged),
        },
        {
            "label": "dimensions",
            "text": "; ".join(f"{d}: {w}" for d, w in change.dimension_changes),
        },
    ]


def _category(dim: Dimension, cat: Category, miner: DerivedMiner | None) -> dict[str, Any]:
    fid = full_id(dim.id, cat.id)
    mined = miner is not None and dim.id in miner.dimensions
    return {
        "id": cat.id,
        "full_id": fid,
        "name": cat.name,
        "definition": cat.definition,
        "count": miner.counts.get(fid, 0) if miner is not None and mined else None,
        "mined": mined,
        "include": list(cat.include_cues),
        "exclude": list(cat.exclude_cues),
        "examples": [
            {"quote": e.quote, "work": e.work_id, "anchor": e.anchor} for e in cat.examples
        ],
    }


def _dimension(dim: Dimension, miner: DerivedMiner | None) -> dict[str, Any]:
    mined = miner is not None and dim.id in miner.dimensions
    return {
        "id": dim.id,
        "title": dim.title,
        "question": dim.question,
        "cardinality": dim.cardinality,
        "read_scope": "whole text"
        if dim.read_scope.whole_text
        else ", ".join(dim.read_scope.headings),
        "layer_scheme": dim.layer_scheme,
        "residuals": [
            {
                "id": r,
                "full_id": full_id(dim.id, r),
                "count": miner.counts.get(full_id(dim.id, r), 0)
                if miner is not None and mined
                else None,
            }
            for r in dim.residuals
        ],
        "categories": [_category(dim, c, miner) for c in dim.categories],
    }


def _version(
    spec: TaxonomySpec,
    previous: TaxonomySpec | None,
    miner: DerivedMiner | None,
    digest: str,
    date: str,
) -> dict[str, Any]:
    return {
        "version": spec.version,
        "digest": digest,
        "date": date,
        "rationale": spec.rationale,
        "n_dimensions": len(spec.dimensions),
        "n_categories": sum(len(d.categories) for d in spec.dimensions),
        "miner": None
        if miner is None
        else {"name": miner.name, "version": miner.version, "page": miner.page},
        "against": None if previous is None else previous.version,
        "diff": None if previous is None else diff_rows(diff(previous, spec)),
        "dimensions": [_dimension(d, miner) for d in spec.dimensions],
    }


def registered_payload(project: Project) -> list[dict[str, Any]]:
    """Each registered taxonomy name with its versions (latest first), open proposals, and per
    version the dimensions, categories with counts, derived miner and the diff from the previous
    version. Names sorted; counts from `derived_counts` through `derived_miner`."""
    rows = tax_service.list_taxonomies(project)
    dates = _dates(project, [r.event_id for r in rows])
    by_name: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_name[r.name].append(r)
    out: list[dict[str, Any]] = []
    for name in sorted(by_name):
        entries = sorted(by_name[name], key=lambda r: r.version)
        specs = {
            r.version: tax_service.registered_taxonomy(project, name, r.version) for r in entries
        }
        versions: list[dict[str, Any]] = []
        previous: TaxonomySpec | None = None
        for r in entries:
            spec = specs[r.version]
            if spec is None:
                continue
            versions.append(
                _version(
                    spec,
                    previous,
                    derived_miner(project, name, r.version),
                    r.digest,
                    dates.get(r.event_id, ""),
                )
            )
            previous = spec
        open_n = sum(1 for p in tax_service.list_proposals(project, name) if p.status == "open")
        out.append(
            {
                "name": name,
                "latest": entries[-1].version,
                "open_proposals": open_n,
                "versions": list(reversed(versions)),
            }
        )
    return out


def legacy_taxonomy(project: Project) -> dict[str, Any] | None:
    """The earlier unregistered `taxonomy.json`, kept as it was (TX-8); None when absent."""
    try:
        tax = json.loads((project.paths.dir / LEGACY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(tax, dict):
        return None
    return {
        "name": str(tax.get("taxonomy", "")),
        "status": str(tax.get("status", "")),
        "source": str(tax.get("source", "")),
        "dimensions": [
            {
                "id": str(d.get("dimension", "")),
                "title": str(d.get("title") or d.get("dimension", "")),
                "categories": [
                    {"name": str(c.get("name", "")), "pattern": str(c.get("pattern") or "")}
                    for c in d.get("categories", [])
                ],
            }
            for d in tax.get("dimensions", [])
        ],
    }


# ---------------------------------------------------------------- build


def _layer_map(project: Project) -> dict[str, str | None]:
    try:
        from factory.services.work_layers import layers_of

        return {wid: wl.layer for wid, wl in layers_of(project).items()}
    except Exception:  # layers are an aid: a project without them still gets the page
        return {}


def build(ctx: HubContext) -> dict[str, Any]:
    """The `method` payload: `lifecycle` (m-stages view and the overall sequences), `steps`,
    `taxonomy` (registered versions and the legacy list) and `methods`."""
    project = ctx.project
    works: list[dict[str, Any]] = ctx.corpus_raw["works"]
    lifecycle = lifecycle_view(works, _layer_map(project))
    lifecycle["sequences"] = sequence_analysis(own_stage_sequences(project))
    lifecycle["stage_rules"] = [{"stage": s, "keywords": list(k)} for s, k in STAGE_RULES]
    return {
        "ready": True,
        "methods": dict(METHODS),
        "lifecycle": lifecycle,
        "steps": steps_payload(step_rows(project)),
        "taxonomy": {
            "registered": registered_payload(project),
            "legacy": legacy_taxonomy(project),
        },
    }
