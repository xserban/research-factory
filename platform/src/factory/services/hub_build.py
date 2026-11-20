"""Static build of the hub v2 pages (plan hub-ui): payload registry, pages and a build report.

Invariants:
- ``BUILDERS`` maps a payload name to a function of a shared ``HubContext``. Mining, findings and
  corpus payloads register here later by adding one entry; nothing else changes.
- ``HubContext`` computes each shared input once: the flow data (the ledger takes about 80 s on
  the pilot), the citation graph, the layers and the coded fields. A failure is memoised too, so
  a broken input is attempted once and reported by every payload that needs it.
- One failing payload never stops the others; its error is in ``BuildReport.errors`` and none of
  its files is written. Pages whose payloads did not all build are not written.
- Output is deterministic for a given project state and clock reading: sorted keys, no NaN.
- The project is only read. Files are written under ``out_dir`` and nowhere else.
- No function here calls a model or the network.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import re
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, TypeVar

from sqlalchemy import text as sql_text

from factory.services import (
    call_memo,
    citations,
    hub_chat,
    hub_contradictions,
    hub_costs,
    hub_findings,
    hub_graph,
    hub_landscape,
    hub_learn,
    hub_lenses,
    hub_levels,
    hub_living,
    hub_method,
    hub_mining,
    hub_pipeline,
    hub_platform,
    hub_protocol,
    hub_screening,
    hub_sources,
    hub_ui,
    hub_write,
    protocol,
    question,
    site_corpus,
)
from factory.services import hub_payloads as hp
from factory.services.context import Project
from factory.services.work_layers import layers_of

T = TypeVar("T")

# Fields every lens and the graph labels read, as the profile's dimension keys.
LENS_DIMS = hub_lenses.DNA_DIMS
GRAPH_LABEL_DIM = "technique"


class HubContext:
    """A project and its lazily computed, memoised shared inputs."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self._memo: dict[str, tuple[bool, Any]] = {}

    def _once(self, key: str, fn: Callable[[], T]) -> T:
        if key not in self._memo:
            try:
                self._memo[key] = (True, fn())
            except Exception as exc:
                self._memo[key] = (False, exc)
        ok, value = self._memo[key]
        if not ok:
            raise value
        return value  # type: ignore[no-any-return]

    @property
    def flow_data(self) -> hp.FlowData:
        # Looked up on the module at call time so a test can count or replace it.
        return self._once("flow", lambda: hp.load_flow_data(self.project))

    @property
    def included(self) -> list[str]:
        return list(self.flow_data.sets.included)

    @property
    def source_of(self) -> dict[str, str]:
        """Included work id -> the id its miner rows are recorded under."""
        sets = self.flow_data.sets
        return {w: sets.miner_source(w) for w in self.included}

    @property
    def graph(self) -> hub_graph.CitationGraph:
        return self._once("graph", lambda: hub_graph.load_citation_graph(self.project))

    @property
    def publication(self) -> dict[str, tuple[str, str]]:
        """Included work id -> (title, published date string)."""
        return self._once("pub", lambda: hp._load_publication(self.project, self.included))

    @property
    def layer_of(self) -> dict[str, str]:
        def build() -> dict[str, str]:
            layers = layers_of(self.project)
            src = self.source_of
            out: dict[str, str] = {}
            for w in self.included:
                wl = layers.get(w) or layers.get(src[w])
                out[w] = wl.layer if wl is not None and wl.layer else hp.UNLAYERED
            return out

        return self._once("layers", build)

    def field(self, dim_key: str) -> dict[str, str | None]:
        """The first pass-A value of a profile dimension for every included work."""
        return self._once(
            f"field:{dim_key}",
            lambda: hp._load_role_field(self.project, self.source_of, dim_key),
        )

    @property
    def cited_here(self) -> dict[str, hp.CitedHere]:
        return self._once(
            "cited",
            lambda: hp.cited_here(self.project, self.included, self.graph),
        )

    @property
    def mining_data(self) -> hub_mining.MiningData:
        """Miner rows, models, titles and codebook, loaded once with the flow data's sets (the
        ledger is not recomputed)."""
        return self._once(
            "mining",
            lambda: dataclasses.replace(
                hub_mining.load_mining_data(self.project, sets=self.flow_data.sets),
                layers=self.layer_of,
            ),
        )

    @property
    def grids(self) -> dict[str, dict[str, Any]]:
        """`grid-<miner>` payloads from the loaded mining data, computed once."""
        return self._once("grids", lambda: hub_mining.grid_payloads(self.mining_data))

    def role_cells(self, dim_key: str) -> dict[str, tuple[str, str] | None]:
        """The first pass-A (value, quote) of a profile dimension for every included work."""
        return self._once(
            f"cells:{dim_key}",
            lambda: hp._load_role_cells(self.project, self.source_of, dim_key),
        )

    @property
    def dna(self) -> dict[str, dict[str, dict[str, str] | None]]:
        """Included work id -> EXPLORE_DIMS -> {"v", "q"} or None; computed once, shared by the
        shell and explore payloads."""

        def build() -> dict[str, dict[str, dict[str, str] | None]]:
            cells = {k: self.role_cells(k) for k in EXPLORE_DIMS}
            out: dict[str, dict[str, dict[str, str] | None]] = {}
            for w in self.included:
                out[w] = {}
                for k in EXPLORE_DIMS:
                    c = cells[k].get(w)
                    out[w][k] = {"v": c[0], "q": c[1]} if c else None
            return out

        return self._once("dna", build)

    @property
    def landscape_parts(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """The `landscape` and `landscape_uses` payloads, built once from one read of the technique
        service's inputs (a cold read takes 26 to 60 s; the service memoises it per last event)."""
        return self._once(
            "landscape",
            lambda: hub_landscape.landscape_payloads(hub_landscape.load_inputs(self.project)),
        )

    @property
    def corpus_raw(self) -> dict[str, Any]:
        """`site_corpus.corpus_payload` for the whole project, read once and shared (the method,
        write and corpus payloads each used to read it again). Callers must not mutate it."""
        return self._once("corpus_payload", lambda: site_corpus.corpus_payload(self.project))

    def year_month(self, work_id: str) -> tuple[int | None, int | None]:
        date = self.publication.get(work_id, ("", ""))[1]
        year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None
        month = int(date[5:7]) if len(date) >= 7 and date[5:7].isdigit() else None
        return year, month


# ---------------------------------------------------------------- builders


SHELL_ABSTRACT_CHARS = 600  # the drawer's abstract is cut to this many characters, then "…"
SHELL_AUTHORS = 8


def _cut(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def work_meta(project: Project, ids: Collection[str]) -> dict[str, dict[str, Any]]:
    """work id -> authors (first 8 names), venue, abstract, doi and arxiv, one index read."""
    wanted = set(ids)
    out: dict[str, dict[str, Any]] = {}
    with project.index.connect() as conn:
        for w, data in conn.execute(sql_text("SELECT work_id, data FROM works")):
            if str(w) not in wanted:
                continue
            d = json.loads(str(data))
            ident = d.get("identifiers") or {}
            out[str(w)] = {
                "authors": [str(a.get("name")) for a in (d.get("authors") or []) if a.get("name")][
                    :SHELL_AUTHORS
                ],
                "venue": (d.get("venue") or {}).get("name") or "",
                "abstract": str(d.get("abstract") or ""),
                "doi": ident.get("doi"),
                "arxiv": ident.get("arxiv"),
            }
    return out


def readable_title(slug: str) -> str:
    """A project title from its slug: separators become spaces, first letter capital."""
    words = re.sub(r"[-_]+", " ", slug).strip()
    return words[:1].upper() + words[1:]


def project_head(project: Project) -> dict[str, Any]:
    """Title (the slug made readable; the question record has no short title), protocol id and
    the review question's primary question."""
    q = question.question_view(project)
    pv = protocol.protocol_view(project)
    return {
        "title": readable_title(project.paths.slug),
        "question": q.spec.primary_question if q.spec is not None else None,
        "protocol_id": pv.protocol_id,
    }


def build_shell(ctx: HubContext, *, with_abstracts: bool = True) -> dict[str, Any]:
    """Slug, build time, PRISMA headline, included works with what the drawer and Ctrl-K show
    (authors, venue, abstract cut to SHELL_ABSTRACT_CHARS, ids, cited-here, DNA values with quotes,
    layer, mapped_from), included-to-included citation pairs as indexes into `works`, the
    project head, the sets summary, glossary and labels."""
    d = ctx.flow_data
    ids = sorted(ctx.included)
    meta = work_meta(ctx.project, ids)
    cited = ctx.cited_here
    dna = ctx.dna
    src = ctx.source_of
    works = []
    for w in ids:
        year, month = ctx.year_month(w)
        m = meta.get(w, {})
        entry: dict[str, Any] = {
            "id": w,
            "title": ctx.publication.get(w, (w, ""))[0],
            "year": year,
            "month": month,
            "layer": ctx.layer_of[w],
            "authors": m.get("authors", []),
            "venue": m.get("venue", ""),
            "doi": m.get("doi"),
            "arxiv": m.get("arxiv"),
            "cited_here": cited[w].count,
            **{k: dna[w][k] for k in EXPLORE_DIMS},
        }
        if with_abstracts:
            entry["abstract"] = _cut(m.get("abstract", ""), SHELL_ABSTRACT_CHARS)
        if src[w] != w:
            entry["mapped_from"] = src[w]
        works.append(entry)
    index = {w["id"]: i for i, w in enumerate(works)}
    cites = sorted(
        [index[a], index[b]] for a, b in ctx.graph.edges if a in index and b in index and a != b
    )
    sets = d.sets
    return {
        "slug": ctx.project.paths.slug,
        "generated": ctx.project.clock.now().isoformat(timespec="seconds"),
        "project": project_head(ctx.project),
        "prisma": {
            "identified": sum(d.prisma.identified_databases.values())
            + sum(d.prisma.identified_other.values()),
            "screened": d.prisma.screened,
            "included": len(works),
            "read_in_full": len(sets.read_in_full),
        },
        "sets": {
            "included": len(sets.included),
            "read_in_full": len(sets.read_in_full),
            "duplicate_mapped": len(sets.duplicate_mapped),
            "mined_but_excluded": len(sets.mined_but_excluded),
            "not_read_yet": len(sets.not_read_yet),
        },
        "works": works,
        "cites": cites,
        "dna_dims": list(EXPLORE_DIMS),
        "abstract_chars": SHELL_ABSTRACT_CHARS,
        "glossary": {k: list(v) for k, v in sorted(hub_ui.GLOSSARY.items())},
        "labels": dict(sorted(hub_ui.LABELS.items())),
    }


def build_overview(ctx: HubContext) -> dict[str, Any]:
    return hp.overview_payload(ctx.project, ctx.flow_data)


def build_flow(ctx: HubContext) -> dict[str, Any]:
    return hp.flow_payload(ctx.project, ctx.flow_data)


def build_screening(ctx: HubContext) -> dict[str, Any]:
    return hub_screening.screening_payload(ctx.project)


def graph_labels(ctx: HubContext) -> dict[str, str]:
    """Included work id -> technique code, as the overview reads the field. Uncoded works absent."""
    return {w: v for w, v in ctx.field(GRAPH_LABEL_DIM).items() if v}


def build_graph(ctx: HubContext) -> dict[str, Any]:
    return hub_graph.graph_payload(ctx.project, ctx.included, graph_labels(ctx))


def lens_works(
    ctx: HubContext, fields: Mapping[str, Mapping[str, str | None]] | None = None
) -> list[hub_lenses.LensWork]:
    """The included set as lens records, with the DNA dimensions the Explore wall uses.

    `fields` (dimension -> work -> value) defaults to the context's fields; the explore builder
    passes the values of the DNA cells it already holds so the index is read once."""
    fields = fields or {k: ctx.field(k) for k in LENS_DIMS}
    cited = ctx.cited_here
    out = []
    for w in sorted(ctx.included):
        year, month = ctx.year_month(w)
        out.append(
            hub_lenses.LensWork(
                id=w,
                year=year,
                month=month,
                layer=ctx.layer_of[w],
                dims={k: fields[k].get(w) for k in LENS_DIMS},
                cited_here=cited[w].count,
            )
        )
    return out


def lens_cites(ctx: HubContext) -> dict[str, Collection[str]]:
    """Citing included work -> the works it cites, from the live citation graph."""
    inc = set(ctx.included)
    out: dict[str, set[str]] = {}
    for a, b in ctx.graph.edges:
        if a in inc:
            out.setdefault(a, set()).add(b)
    return {a: sorted(b) for a, b in sorted(out.items())}


def adoption_records(ctx: HubContext) -> list[hub_lenses.AdoptionRecord]:
    """Technique miner rows as (work, stage, technique code, year, month), pass A, included works.

    The stage is the codebook's stage of the code; a code outside the codebook (not-stated,
    other) is not a technique and is left out."""
    data = ctx.mining_data
    codebook = data.codebook
    atts = hub_mining.attributions(data)
    out: list[hub_lenses.AdoptionRecord] = []
    for miner, att in sorted(atts.items()):
        if not miner.startswith(hub_findings.TECH_MINER_PREFIX):
            continue
        for w, rows in sorted(att.by_pass.get("A", {}).items()):
            year, month = ctx.year_month(w)
            codes = {
                c.value.rsplit("/", 1)[-1]
                for r in rows
                if (c := r.cells.get(hub_findings.TECH_FIELD)) is not None and c.value
            }
            for code in sorted(codes):
                if code in codebook:
                    out.append((w, codebook[code]["stage"], code, year, month))
    return out


def build_lenses(ctx: HubContext) -> dict[str, Any]:
    return hub_lenses.lenses_payload(
        lens_works(ctx),
        matrix_dims=("technique", "architecture"),
        chain_dims=LENS_DIMS,
        trend_dim="technique",
        icicle_dims=("layer", "technique", "architecture"),
        assoc_dims=(*LENS_DIMS, "layer"),
        matrix_pair_dims=(*LENS_DIMS, "layer"),
        cites=lens_cites(ctx),
        adoption_records=adoption_records(ctx),
        codebook={k: v["label"] for k, v in sorted(ctx.mining_data.codebook.items())},
    )


def build_landscape(ctx: HubContext) -> dict[str, Any]:
    return ctx.landscape_parts[0]


def build_landscape_uses(ctx: HubContext) -> dict[str, Any]:
    return ctx.landscape_parts[1]


def build_living(ctx: HubContext) -> dict[str, Any]:
    return hub_living.living_payload(ctx.project)


def build_mining(ctx: HubContext) -> dict[str, Any]:
    return hub_mining.mining_payload_from(ctx.mining_data, ctx.grids)


def build_findings(ctx: HubContext) -> dict[str, Any]:
    layers = dict(ctx.layer_of)
    rank = {w: c.count for w, c in ctx.cited_here.items()}
    return hub_findings.findings_from(
        ctx.mining_data,
        layers=layers,
        rank=rank,
        fields=hub_findings.profile_fields(ctx.project),
    )


EXPLORE_DIMS = ("technique", "architecture", "span", "human")
EXPLORE_SIMILAR_K = 8  # similar papers listed per work

EXPLORE_METHODS: dict[str, str] = {
    "filter": (
        "Filtering runs on the fields the miners recorded. Counts and percentages are "
        "calculated from the papers that match; no model is involved."
    ),
    "rings": (
        "Sector widths, ring counts and sizes are counted from the recorded fields. Positions "
        "inside a ring are spread to avoid overlap, so distance within a ring means nothing."
    ),
    "wall": (
        "Colours come from the recorded values; a grey square means the field was not coded. "
        "Sorting is by the value order shown in the key."
    ),
    "tray": (
        "Differences are plain comparisons of recorded values. Shared citations count papers in "
        "this review that two or more pinned papers cite, or that cite them."
    ),
}


def build_explore(ctx: HubContext) -> dict[str, Any]:
    """Per included work: id, title, date, layer, cited-here count, the DNA dimensions, each
    as {"v": value, "q": quote} (null when the work has no value), and its top
    `EXPLORE_SIMILAR_K` similar works from `hub_lenses.similar` (id, score, matched fields,
    shared cited works). `methods` carries the texts of the page's information panels."""
    all_dna = ctx.dna
    cited = ctx.cited_here
    lw = lens_works(
        ctx,
        {k: {w: (c["v"] if (c := all_dna[w][k]) else None) for w in all_dna} for k in LENS_DIMS},
    )
    inc = set(ctx.included)
    cites = {a: sorted(set(b) & inc) for a, b in lens_cites(ctx).items()}
    works = []
    for w in sorted(ctx.included):
        year, month = ctx.year_month(w)
        works.append(
            {
                "id": w,
                "title": ctx.publication.get(w, (w, ""))[0],
                "year": year,
                "month": month,
                "layer": ctx.layer_of[w],
                "cited_here": cited[w].count,
                "dna": all_dna[w],
                "similar": [
                    {
                        "id": r.id,
                        "score": r.score,
                        "matched_dims": r.matched_dims,
                        "shared_cites": r.shared_cites,
                    }
                    for r in hub_lenses.similar(lw, cites, w, EXPLORE_SIMILAR_K)
                ],
            }
        )
    return {
        "works": works,
        "dims": list(EXPLORE_DIMS),
        "layer_order": _layer_order(),
        "methods": {**EXPLORE_METHODS, "similar": hub_lenses.METHODS["similar"]},
    }


def _layer_order() -> list[str]:
    from factory.services.site_layers import LAYER_ORDER  # imports site_corpus

    return [*LAYER_ORDER, hp.UNLAYERED]


def _unread_entry(ctx: HubContext, work_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    """A corpus entry for an included work no miner has read: its record only, no coded values,
    marked `not_read_yet` so the Corpus lists every included work (plan 4.1)."""
    title, published = ctx.publication.get(work_id, (work_id, ""))
    return {
        "id": work_id,
        "slug": site_corpus.slug_of(work_id),
        "title": title or work_id,
        "authors": meta.get("authors", []),
        "published": published,
        "year": published[:4],
        "month": published[:7],
        "venue": meta.get("venue", ""),
        "doi": meta.get("doi"),
        "arxiv": meta.get("arxiv"),
        "cited_by": None,
        "cited_in_corpus": c.count if (c := ctx.cited_here.get(work_id)) else None,
        "abstract": meta.get("abstract", ""),
        "cls": {},
        "map": {},
        "sum": {},
        "desc": {},
        "stages": [],
        "design": [],
        "n_design": 0,
        "doc": None,
        "layer": ctx.layer_of[work_id],
        "not_read_yet": True,
    }


def _doc_link(doc: Mapping[str, str] | None, slug: str) -> dict[str, str] | None:
    """The stored original of a work as the page may show it: its kind and name and the path of the
    conversion inspector page. The absolute library path is dropped (the payload is published)."""
    if not doc:
        return None
    return {
        "kind": doc["kind"],
        "name": doc["name"],
        "inspector": f"../conversion/doc/{slug}.html",
    }


def build_corpus(ctx: HubContext) -> dict[str, Any]:
    """`site_corpus.corpus_payload` restricted to the included set (plan 4.1).

    corpus_payload reads the index for works with live miner rows (excluded ones too), so it is
    called and post-filtered: a work stays only if included; a canonical work with no rows of its
    own takes the rows of the duplicate that holds them (marked `mapped_from`); citation pairs are
    mapped to included ids, self-links and repeats dropped. An included work no miner has read is
    listed from its record, marked `not_read_yet`, so every included work appears. `sets` lists the
    differences."""
    raw = ctx.corpus_raw
    by_id = {w["id"]: w for w in raw["works"]}
    source_of = ctx.source_of
    layer_of = ctx.layer_of
    works: list[dict[str, Any]] = []
    to_included: dict[str, str] = {}
    unread = [w for w in sorted(ctx.included) if by_id.get(source_of[w]) is None]
    meta = work_meta(ctx.project, unread)
    for w in sorted(ctx.included):
        entry = by_id.get(source_of[w])
        if entry is None:
            works.append(_unread_entry(ctx, w, meta.get(w, {})))
            continue
        to_included[entry["id"]] = w
        item = dict(entry)
        item["id"] = w
        item["slug"] = site_corpus.slug_of(w)
        item["layer"] = layer_of[w]
        item["doc"] = _doc_link(entry.get("doc"), item["slug"])
        if source_of[w] != w:
            item["mapped_from"] = source_of[w]
        works.append(item)
    slug_to_id = {e["slug"]: e["id"] for e in raw["works"]}
    slug_of_included = {w["id"]: w["slug"] for w in works}
    pairs: set[tuple[str, str]] = set()
    for a, b in raw["cites"]:
        ia, ib = to_included.get(slug_to_id[a]), to_included.get(slug_to_id[b])
        if ia and ib and ia != ib:
            pairs.add((slug_of_included[ia], slug_of_included[ib]))
    report = citations.citation_report(ctx.project, as_of_year=datetime.now(UTC).year)
    design = {
        w["id"]: [{k: str(r.get(k) or "") for k in site_corpus.DESIGN_FIELDS} for r in w["design"]]
        for w in works
        if w.get("design")
    }
    n_design = {w["id"]: int(w.get("n_design") or 0) for w in works if w.get("design")}
    return {
        "dims": raw["dims"],
        "works": works,
        "layer_order": raw["layer_order"],
        "cites": sorted([a, b] for a, b in pairs),
        "refs_done": raw["refs_done"],
        "sets": hp.sets_payload(ctx.flow_data.sets),
        "citation": hub_lenses.citation_rate(
            report.works,
            ctx.included,
            extractions=report.extractions,
            entries=report.entries,
            resolved_links=report.resolved_links,
            works_total=report.works_total,
            as_of_year=report.as_of_year,
        ),
        "results": hub_lenses.results_grid(design, n_design),
    }


def build_journeys(ctx: HubContext) -> dict[str, Any]:
    """Per-work journeys and replay frames; the module is delivered separately, so it is imported
    when the payload is built and its absence is reported as this payload's error."""
    import importlib

    try:
        mod = importlib.import_module("factory.services.hub_journeys")
        fn = mod.journeys_payload
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(f"hub_journeys.journeys_payload is not available: {exc}") from exc
    payload: dict[str, Any] = fn(ctx.project, ctx.flow_data)
    return payload


def _grid_builder(name: str) -> Callable[[HubContext], dict[str, Any]]:
    return lambda ctx: ctx.grids[name]


GRID_FAMILY = "grid"  # `--only grid` builds every `grid-<miner>` payload

BUILDERS: dict[str, Callable[[HubContext], dict[str, Any]]] = {
    "shell": build_shell,
    "overview": build_overview,
    "flow": build_flow,
    "screening": build_screening,
    "graph": build_graph,
    "lenses": build_lenses,
    "living": build_living,
    "mining": build_mining,
    "findings": build_findings,
    "contradictions": hub_contradictions.build,
    "chat": hub_chat.build,
    "explore": build_explore,
    "corpus": build_corpus,
    "journeys": build_journeys,
    hub_landscape.LANDSCAPE: build_landscape,
    hub_landscape.USES: build_landscape_uses,
    # stubs of the seven ported pages (step 0); each module's `build` replaces its stub later
    "protocol": hub_protocol.build,
    "levels": hub_levels.build,
    "pipeline": hub_pipeline.build,
    "sources": hub_sources.build,
    "method": hub_method.build,
    "costs": hub_costs.build,
    "write": hub_write.build,
    "platform": hub_platform.build,
    "learn": hub_learn.build,
}

# Payloads whose cache key is narrower than the whole event log: name -> the event type prefixes
# they read. Every other payload is keyed on `PAYLOAD_INPUTS` (see `hub_serve.fingerprint`).
PAYLOAD_EVENTS: dict[str, tuple[str, ...]] = {
    hub_landscape.LANDSCAPE: hub_landscape.EVENT_PREFIXES,
    hub_landscape.USES: hub_landscape.EVENT_PREFIXES,
}

# What a payload reads, for its cache key (`hub_serve.fingerprint`). A spec is a tuple of event type
# prefixes ("extraction." matches `extraction.recorded`); a spec that starts with "*" means every
# event type except those named with a leading "-". A payload with no entry reads every event.
# Conservative: a family is left out only where no builder of the payload reads it (the live pilot's
# constant runner, task, feed and watch events must not restale the corpus pages).
_QUIET: Final = ("-runner.", "-task.", "-feed.", "-watch.", "-xrun.", "-file.", "-notice.")
PAYLOAD_INPUTS: dict[str, tuple[str, ...]] = {
    **{
        name: ("*", *_QUIET)
        for name in (
            "shell",
            "overview",
            "flow",
            "screening",
            "graph",
            "lenses",
            "mining",
            "findings",
            "explore",
            "corpus",
            "journeys",
        )
    },
    # the call ledger and the budget: agent-written work and its runs, not inbox, feed or pages
    "costs": (
        "runner.",
        "task.",
        "budget.",
        "ledger.",
        "xrun.",
        "member.",
        "review.",
        "extraction.",
        "screening.",
        "mine.",
        "miner.",
        "decision.",
        "calibration.",
        "audit.",
        "check.",
        "document.",
        "fulltext.",
        "reference.",
        "search.",
        "probe.",
        "interpretation.",
        "contribution.",
        "relation.",
        "idea.",
        "concept.",
        "hypothesis.",
        "draft.",
        "manuscript.",
        "experiment.",
        "lead.",
        "label.",
        "appraisal.",
        "consolidation.",
        "taxonomy.",
        "vocabulary.",
    ),
}


def reads(name: str, event_type: str) -> bool:
    """Whether the cache key of payload `name` follows events of `event_type` (landscape payloads
    follow `PAYLOAD_EVENTS`; a grid follows the mining payload)."""
    if name in PAYLOAD_EVENTS:
        return event_type.startswith(PAYLOAD_EVENTS[name])
    if name.startswith(hub_mining.GRID_PREFIX):
        name = "mining"
    spec = PAYLOAD_INPUTS.get(name, ("*",))
    if spec[0] == "*":
        return not any(event_type.startswith(p[1:]) for p in spec[1:])
    return event_type.startswith(spec)


# ---------------------------------------------------------------- build


@dataclass(frozen=True)
class PayloadReport:
    seconds: float
    bytes: int


@dataclass
class BuildReport:
    """Per payload name: seconds and bytes written; per failed name: the error text."""

    payloads: dict[str, PayloadReport] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    pages: list[str] = field(default_factory=list)
    skipped_pages: dict[str, list[str]] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)


def dumps(payload: object) -> str:
    """Deterministic JSON: sorted keys, UTF-8 text, NaN and infinity refused."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=None)


def _write_payload(data_dir: Path, name: str, text: str) -> None:
    """`<name>.json.gz` then `<name>.json`, each renamed into place from a temporary file."""
    raw = (text + "\n").encode("utf-8")
    for suffix, body in ((".json.gz", gzip.compress(raw, 6, mtime=0)), (".json", raw)):
        tmp = data_dir / f"{name}{suffix}.tmp"
        tmp.write_bytes(body)
        tmp.replace(data_dir / f"{name}{suffix}")


def build_static(
    project: Project,
    out_dir: Path,
    only: Collection[str] | None = None,
    *,
    payloads_only: bool = False,
) -> BuildReport:
    """Write ``data/<name>.json`` and ``.js``, ``assets/*`` and the pages whose payloads built.

    ``only`` limits the payload names (unknown names raise ValueError before anything is
    written); pages are written when every payload they need was built in this run. A failed
    payload's stale ``data/<name>.json|js`` and the stale ``.html`` of pages skipped because of
    it are deleted and listed in ``report.removed``.

    ``payloads_only`` is the served hub's child build: only ``data/<name>.json`` and its
    ``.json.gz`` (compressed once, here) are written, each through a temporary file so a file
    that exists is complete (the gzip first); no ``.js``, assets or pages. A list ``only`` fixes
    the build order (the payload a request waits for comes first)."""
    only_set = None if only is None else set(only)
    if only_set is not None:
        unknown = sorted(
            n
            for n in only_set
            if n not in BUILDERS and n != GRID_FAMILY and not n.startswith(hub_mining.GRID_PREFIX)
        )
        if unknown:
            raise ValueError(
                f"unknown payload(s): {', '.join(unknown)}; known: {', '.join(BUILDERS)}, "
                f"{GRID_FAMILY}, {hub_mining.GRID_PREFIX}<miner>"
            )
    names = [n for n in BUILDERS if only_set is None or n in only_set]
    if isinstance(only, list | tuple):
        rank = {n: i for i, n in enumerate(only)}
        names.sort(key=lambda n: rank[n])
    ctx = HubContext(project)
    report = BuildReport()
    builders: dict[str, Callable[[HubContext], dict[str, Any]]] = {n: BUILDERS[n] for n in names}
    wanted_grids = only_set is None or GRID_FAMILY in only_set
    specific = sorted(n for n in (only_set or ()) if n.startswith(hub_mining.GRID_PREFIX))
    if wanted_grids or specific:
        try:
            grids = ctx.grids
        except Exception as exc:
            report.errors[GRID_FAMILY] = f"{type(exc).__name__}: {exc}"
            grids = {}
        missing_grids = [n for n in specific if n not in grids]
        if missing_grids and not report.errors:
            raise ValueError(f"unknown grid payload(s): {', '.join(missing_grids)}")
        for gname in grids:
            if wanted_grids or gname in specific:
                builders[gname] = _grid_builder(gname)
                names.append(gname)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        started = time.perf_counter()
        try:
            # one reading of each shared derivation per payload, and one index sync
            with ctx.project.index.frozen_sync(), call_memo.entering():
                text = dumps(builders[name](ctx))
        except Exception as exc:
            report.errors[name] = f"{type(exc).__name__}: {exc}"
            for stale in (data_dir / f"{name}.json", data_dir / f"{name}.js"):
                if stale.is_file():  # an old file must not outlive a failed rebuild
                    stale.unlink()
                    report.removed.append(f"data/{stale.name}")
            continue
        if payloads_only:
            _write_payload(data_dir, name, text)
            report.payloads[name] = PayloadReport(
                round(time.perf_counter() - started, 2), len(text.encode("utf-8")) + 1
            )
            continue
        (data_dir / f"{name}.json").write_text(text + "\n", encoding="utf-8")
        (data_dir / f"{name}.js").write_text(
            f"window.HUB_DATA=window.HUB_DATA||{{}};HUB_DATA[{json.dumps(name)}]={text};\n",
            encoding="utf-8",
        )
        report.payloads[name] = PayloadReport(
            round(time.perf_counter() - started, 2), len(text.encode("utf-8")) + 1
        )
    if payloads_only:
        return report
    for asset in hub_ui.ASSETS:
        target = out_dir / "assets" / asset
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(hub_ui.asset_bytes(asset))
    version = hub_ui.asset_version()
    for spec in hub_ui.PAGES.values():
        missing = [n for n in spec.payloads if n not in report.payloads]
        if only_set is not None and not set(spec.payloads) <= set(names):
            continue
        if missing:
            report.skipped_pages[spec.id] = missing
            stale_page = out_dir / f"{spec.id}.html"
            if stale_page.is_file():
                stale_page.unlink()
                report.removed.append(stale_page.name)
            continue
        (out_dir / f"{spec.id}.html").write_text(
            hub_ui.page_html(spec.id, spec.title, [spec.script], spec.payloads, version),
            encoding="utf-8",
        )
        report.pages.append(spec.id)
    return report


def format_report(report: BuildReport) -> list[str]:
    """One line per payload, page and error, for the CLI."""
    lines = [f"{n}: {r.seconds:.2f} s, {r.bytes} bytes" for n, r in report.payloads.items()]
    lines += [f"{n}: FAILED {e}" for n, e in report.errors.items()]
    lines += [f"page {p}" for p in report.pages]
    lines += [
        f"page {p}: not written, missing {', '.join(m)}" for p, m in report.skipped_pages.items()
    ]
    lines += [f"removed stale {r}" for r in report.removed]
    return lines
