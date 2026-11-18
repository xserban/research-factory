"""The Landscape payloads of the hub v2 (IDEA-78 in the hub-ui architecture): a derived, exploratory
reading of the technique miners' pass-A rows, as two JSON payloads.

- `landscape`: the stage summaries and the stage-by-approach counts (default lens), compact rows
  from which the page recomputes any lens (layer, evidence, status) in the browser, co-used,
  derives-from and earliest-in-corpus edges, and the ranked candidates (default lens only).
- `landscape_uses`: per approach, the evidence rows with the verbatim quote and anchor, loaded by
  the page only when an approach is opened.

Invariants:
- Both are pure functions of one `technique_graph.Inputs` (`landscape_payloads`); the project is
  read once by `load_inputs` (the service's memoised read, no index lock held across the scan).
  Same inputs, same payloads: no clock, no randomness.
- Every figure counts works with a current pass-A row of a technique miner (a named set, stated in
  `sets`), never a figure for a report. The notice, the corpus sentence and the candidate sentence
  travel in the payload; every node, edge and candidate keeps its `class` and `state` labels.
- Nothing is written and no model is called. A held-out seed's work is a corpus work (decision 37
  item 9): nothing is masked here.
- `EVENT_PREFIXES` names the event types the payloads depend on; `hub_serve` keys the cache on
  them, so a feed, runner or page event never rebuilds the Landscape.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from factory.model import technique_graph as tg_model
from factory.model.technique_graph import (
    CANDIDATE_SENTENCE,
    CORPUS_SENTENCE,
    DERIVES_LENS_NOTE,
    EVIDENCE_LEVELS,
    NOT_STATED,
    NOTICE,
    Lens,
)
from factory.services import technique_graph as tg
from factory.services import technique_rank as rank
from factory.services.context import Project
from factory.services.hub_payloads import UNLAYERED

__all__ = [
    "EVENT_PREFIXES",
    "LANDSCAPE",
    "USES",
    "code_stamp",
    "landscape_payloads",
    "load_inputs",
]

LANDSCAPE: Final = "landscape"
USES: Final = "landscape_uses"
DEFAULT_LAYER: Final = "core"
MAX_EDGES: Final = 200
MAX_CANDIDATES: Final = 10
MIN_WORKS: Final = 3
MAX_USES: Final = 300
"""Evidence rows listed per approach in `landscape_uses` (core layer first); the total is stated."""
LAYER_ORDER: Final = ("core", "benchmark", "applied", "adjacent", "background", "off-topic")
EVIDENCE_ALL: Final = (*EVIDENCE_LEVELS, NOT_STATED)

EVENT_PREFIXES: Final = (
    "extraction.",  # the miners' rows, passes and agreement
    "miner.",
    "taxonomy.",
    "protocol.",  # the listed miners and their populations
    "dedup.",
    "reference.",  # resolved reference links (derives-from candidates, bridge scores)
    "citation.",
    "search.",  # corpus membership and the works' titles and dates
    "query.",
    "screening.",
    "decision.",
    "work.",  # layers and core marks
)
"""Event type prefixes the Landscape reads. Feed, runner, page, inbox and task events are absent."""

_STAMP_MODULES: Final = (
    "technique_graph",
    "technique_rank",
    "mining",
    "taxonomies",
    "search",
    "extraction",
    "extraction_agreement",
    "protocol",
    "work_layers",
)

METHODS: Final[dict[str, str]] = {
    "page": (
        "<b>What it shows</b> The techniques (here called approaches) the AI-science systems of "
        "this review use, stage by stage of the research cycle, how well each is evidenced and "
        "which approaches meet.<p><span class=k>How to read it.</span> A row is one approach. "
        "The number is how many papers use it; the bar splits those uses by the evidence level "
        "the paper gives. Open an approach for its papers and the sentences behind it.</p>"
        "<p><span class=k>How it's computed.</span> Counts are papers with a current first-reading "
        "(pass A) row of a technique miner in the chosen layer, evidence level and status. The "
        "miners are not calibrated. Nothing here enters a report.</p>"
    ),
    "matrix": (
        "<b>What it shows</b> One row per approach, grouped by stage.<p><span class=k>How to read "
        "it.</span> Papers: distinct papers using the approach in the lens. Uses: rows the "
        "miner recorded (a paper can use an approach more than once). The coloured bar is the "
        "evidence mix of those uses.</p><p><span class=k>How it's computed.</span> Counted in "
        "your browser from the rows in the data file; with the default lens it equals the "
        "figure the server computed.</p>"
    ),
    "agreement": (
        "<b>What it shows</b> How often a second, independent reading (pass B) of a sample "
        "recorded the same category as the first.<p><span class=k>How to read it.</span> Shown "
        "beside the pass-A counts as a reminder that the miners are not calibrated. It is not "
        "used to correct any count.</p>"
    ),
    "candidates": (
        "<b>What it shows</b> Ideas to check, ranked.<p><span class=k>How to read it.</span> "
        "A candidate is a hypothesis to check against the quotes, never a finding: not found in "
        "this corpus is not absent from the field. A score orders one list only, so scores are "
        "comparable within a list and never across lists. Flags name pairs to judge by hand.</p>"
        "<p><span class=k>How it's computed.</span> Default lens only: core layer, first "
        "reading. Score components are each between 0 and 1; the weights are a first heuristic, "
        "not fitted to any outcome.</p>"
    ),
    "derives": (
        "<b>What it shows</b> Candidate lines of descent between two papers.<p><span class=k>How "
        "to read it.</span> A line is drawn when a paper reports reusing an approach it cites "
        "and the cited paper also uses that approach. It is a candidate, not an origin claim.</p>"
        "<p><span class=k>How it's computed.</span> From the reused-and-cited status of the "
        "row and a resolved reference link. It follows the layer, not the evidence level or "
        "status.</p>"
    ),
    "earliest": (
        "<b>What it shows</b> The earliest-published paper that uses the approach in this "
        "corpus.<p><span class=k>How to read it.</span> A date rule, not a claim of origin: "
        "the approach may be older and outside the corpus.</p>"
        "<p><span class=k>How it's computed.</span> Earliest publication date among the papers "
        "using it, ties by id. A year-only date is ordered by year; undated papers are "
        "skipped and listed.</p>"
    ),
}


# ---------------------------------------------------------------- code stamp and event key


@lru_cache(maxsize=1)
def code_stamp() -> str:
    """Hash of the code the payloads read besides the hub services (the technique graph, its
    ranking and model and `_STAMP_MODULES`), so a payload goes stale when they change. Read once
    per process. Only these direct imports are hashed, not what they import in turn."""
    here = Path(str(tg.__file__)).parent
    paths = [Path(str(tg_model.__file__)), Path(str(rank.__file__)), Path(str(tg.__file__))]
    paths += [here / f"{m}.py" for m in _STAMP_MODULES if (here / f"{m}.py").is_file()]
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda p: p.name):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:12]


def event_key(counts: Mapping[str, tuple[int, str]]) -> str:
    """The count and greatest id of the event types the payloads depend on, as text; `counts` is
    `site.type_counts` (event type -> (count, greatest id))."""
    hits = [v for t, v in sorted(counts.items()) if t.startswith(EVENT_PREFIXES)]
    return f"{sum(n for n, _ in hits)}:{max((m for _, m in hits), default='')}"


# ---------------------------------------------------------------- reading


def load_inputs(project: Project) -> tg.Inputs:
    """The service's inputs with each stage miner's agreement filled in (both memoised per last
    folded event; a cold read takes 26 to 60 s on the pilot). No index lock is held."""
    return tg.with_agreement(project, tg.read_inputs(project))


# ---------------------------------------------------------------- building


def _dump(model: Any) -> dict[str, Any]:
    out: dict[str, Any] = model.model_dump(by_alias=True, mode="json")
    return out


def _layer_key(layer: str | None) -> str:
    return layer or UNLAYERED


def _layers_present(inputs: tg.Inputs) -> list[str]:
    seen = {m.layer for m in inputs.works.values() if m.layer}
    return sorted(seen, key=lambda x: (LAYER_ORDER.index(x) if x in LAYER_ORDER else 99, x))


def _lens_view(inputs: tg.Inputs, lens: Lens) -> Any:
    return tg.build_landscape(inputs, lens, max_edges=MAX_EDGES)


def _candidate(item: Any, kind: str) -> dict[str, Any]:
    """One ranked candidate as a plain dict (the model's own dump, by alias)."""
    out = _dump(item)
    out["kind"] = kind
    return out


def _candidates(inputs: tg.Inputs) -> dict[str, Any]:
    """Ranked lists under the default lens: one gap list per ordered stage pair (a score is
    relative to its own list, so lists are never merged), the combinations and the challenges.
    Each ranked list holds the top `MAX_CANDIDATES` by the composite score."""
    lens = Lens(layer=DEFAULT_LAYER)
    stages = [s.stage for s in inputs.stages]
    gap_lists: list[dict[str, Any]] = []
    for a in stages:
        for b in stages:
            if a == b:
                continue
            found = tg.build_gaps(
                inputs,
                lens,
                from_stage=a,
                to_stage=b,
                min_works=MIN_WORKS,
                max_to_share=0.0,
                limit=MAX_CANDIDATES,
                rank_by="composite",
                top=MAX_CANDIDATES,
            )
            if found.gaps:
                gap_lists.append(
                    {
                        "from_stage": a,
                        "to_stage": b,
                        "total": found.total,
                        "shown": len(found.gaps),
                        "items": [_candidate(g, "gap") for g in found.gaps],
                    }
                )
    combos = tg.build_combinations(
        inputs,
        lens,
        min_works=MIN_WORKS,
        max_co_works=0,
        stage=None,
        limit=MAX_CANDIDATES,
        rank_by="composite",
        top=MAX_CANDIDATES,
    )
    chal = tg.build_challenges(inputs, lens, limit=MAX_CANDIDATES)
    return {
        "lens": _dump(lens),
        "label": CANDIDATE_SENTENCE,
        "min_works": MIN_WORKS,
        "max_per_list": MAX_CANDIDATES,
        "quotes_on_first": rank.QUOTE_TOP,
        "gaps": gap_lists,
        "combinations": {
            "total": combos.total,
            "shown": len(combos.combinations),
            "items": [_candidate(c, "combination") for c in combos.combinations],
        },
        "challenges": {
            "total": chal.total,
            "shown": len(chal.challenges),
            "items": [_candidate(c, "challenge") for c in chal.challenges],
        },
    }


def _earliest(inputs: tg.Inputs, layers: Sequence[str]) -> dict[str, Any]:
    """Per layer (and `all`): approach -> earliest work edge, plus the undated works skipped. The
    layer lens only; the evidence and status lenses do not apply (the page says so)."""
    out: dict[str, Any] = {}
    for layer in ("all", *layers):
        land = tg.build_landscape(inputs, Lens(layer=layer, min_co_works=10**9))
        out[layer] = {
            "by_approach": {
                e.source: {"work": e.target, "note": e.note}
                for e in land.edges
                if e.kind == "earliest-in-corpus"
            },
            "undated_works": list(land.undated_works),
        }
    return out


def _uses(inputs: tg.Inputs) -> dict[str, Any]:
    """`landscape_uses`: per approach, the evidence rows (verbatim quote and anchor) of every layer,
    core first, at most `MAX_USES` each; the total is stated so a cut is never silent."""

    def order(r: tg.RawRow) -> tuple[int, str, str]:
        layer = inputs.works[r.work_id].layer
        rankno = LAYER_ORDER.index(layer) if layer in LAYER_ORDER else len(LAYER_ORDER)
        return (rankno, r.work_id, r.extraction_id)

    by: dict[str, list[tg.RawRow]] = {}
    for r in inputs.rows:
        by.setdefault(r.approach, []).append(r)
    approaches: dict[str, Any] = {}
    for a in sorted(by):
        rows = sorted(by[a], key=order)
        approaches[a] = {
            "rows_total": len(rows),
            "rows_shown": min(len(rows), MAX_USES),
            "uses": [
                {
                    "work": r.work_id,
                    "extraction": r.extraction_id,
                    "layer": _layer_key(inputs.works[r.work_id].layer),
                    "status": r.status or NOT_STATED,
                    "evidence": r.evidence or NOT_STATED,
                    "described_as": r.described_as,
                    "quote": r.quote,
                    "anchor": r.anchor,
                    "parameters": r.parameters,
                }
                for r in rows[:MAX_USES]
            ],
        }
    return {
        "class": "interpretation",
        "state": "exploratory",
        "exploratory": True,
        "notice": NOTICE,
        "max_uses": MAX_USES,
        "approaches": approaches,
    }


def landscape_payloads(inputs: tg.Inputs) -> tuple[dict[str, Any], dict[str, Any]]:
    """The `landscape` and `landscape_uses` payloads of `inputs`. Pure and deterministic."""
    default = Lens(layer=DEFAULT_LAYER)
    land = _lens_view(inputs, default)
    layers = _layers_present(inputs)
    catalogue = sorted(inputs.catalogue.items(), key=lambda kv: (kv[1][0], kv[0]))
    aidx = {a: i for i, (a, _) in enumerate(catalogue)}
    work_ids = sorted({r.work_id for r in inputs.rows})
    widx = {w: i for i, w in enumerate(work_ids)}
    statuses = sorted({r.status or NOT_STATED for r in inputs.rows})
    sidx = {s: i for i, s in enumerate(statuses)}
    eidx = {e: i for i, e in enumerate(EVIDENCE_ALL)}
    ev_present = [
        e for e in EVIDENCE_ALL if any((r.evidence or NOT_STATED) == e for r in inputs.rows)
    ]
    users_by_layer: dict[str, set[str]] = {}
    for r in inputs.rows:
        users_by_layer.setdefault(_layer_key(inputs.works[r.work_id].layer), set()).add(r.work_id)
    stage_order = [s.stage for s in inputs.stages]
    derived = [
        {
            **_dump(e),
            "source_layer": _layer_key(inputs.works[e.source].layer),
            "target_layer": _layer_key(inputs.works[e.target].layer),
        }
        for e in tg.derives_from(inputs, inputs.rows)
    ]
    payload: dict[str, Any] = {
        "class": "interpretation",
        "state": "exploratory",
        "exploratory": True,
        "notice": NOTICE,
        "corpus": CORPUS_SENTENCE,
        "candidate_sentence": CANDIDATE_SENTENCE,
        "derives_lens_note": DERIVES_LENS_NOTE,
        "cross_stage_note": land.cross_stage_note,
        "lens": _dump(default),
        "layers": layers,
        "layer_unset": UNLAYERED,
        "evidence_levels": ev_present,
        "evidence_all": list(EVIDENCE_ALL),
        "statuses": statuses,
        "stage_order": stage_order,
        "sets": {
            "what": "works with a current pass-A row of a technique miner",
            "works": len(work_ids),
            "rows": len(inputs.rows),
            "by_layer": {k: len(v) for k, v in sorted(users_by_layer.items())},
        },
        "stages": [_dump(s) for s in land.stages],
        "catalogue": [
            {"id": a, "stage": s, "name": n, "definition": d} for a, (s, n, d) in catalogue
        ],
        "works": [
            {
                "id": w,
                "title": inputs.works[w].title,
                "year": inputs.works[w].year,
                "date": inputs.works[w].date,
                "layer": _layer_key(inputs.works[w].layer),
            }
            for w in work_ids
        ],
        "rows": [
            [
                aidx[r.approach],
                widx[r.work_id],
                eidx[r.evidence or NOT_STATED],
                sidx[r.status or NOT_STATED],
            ]
            for r in inputs.rows
        ],
        "default": {
            "approaches": [_dump(a) for a in land.approaches],
            "co_used": [_dump(e) for e in land.edges if e.kind == "co-used-with"],
            "co_used_omitted": land.edges_omitted,
            "max_edges": MAX_EDGES,
            "min_co_works": default.min_co_works,
        },
        "derives_from": derived,
        "earliest": _earliest(inputs, layers),
        "candidates": _candidates(inputs),
        "methods": dict(METHODS),
    }
    return payload, _uses(inputs)
