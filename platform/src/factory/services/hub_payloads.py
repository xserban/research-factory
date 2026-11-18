"""Payloads of the hub Overview and Flow pages and their named sets (plan hub-ui, step 3).

Pure functions over plain rows, plus thin read-only loaders over the index and the existing
services. Nothing here calls a model, writes an event or types a number: every figure comes from
`prisma_flow`, `flow_ledger`, the miner rows or the citation graph. `METHODS` holds the
plain-English definitions shown in the info panels.

Invariants:
- The hub's corpus is the PRISMA included set: the ledger rows whose final outcome is included
  (`ft_outcome` after a full-text stage, else `ta_outcome`). `load_flow_data` checks that this
  count equals `prisma_flow`'s and raises otherwise, so a drift cannot reach a page.
- "Read in full" is the set of works with a live pass-A row of a listed miner (the explorer's
  selection, see `site_corpus.corpus_payload`). Its differences from the included set are returned
  by id with a reason (`Sets`); nothing is hidden, held-out seeds' works included (decision 37.9).
- The ledger is computed once per `FlowData`; payload functions accept a prepared `FlowData` so a
  page build never repeats it.
- "Cited here" counts distinct included works citing a work through a live link of the citation
  graph (`hub_graph.load_citation_graph`); self-loops and non-included citers are ignored.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import text

from factory.services import site_corpus
from factory.services.agreement import Outcome
from factory.services.citations import _meta
from factory.services.context import Project
from factory.services.flow_ledger import LedgerRow, flow_ledger
from factory.services.hub_graph import CitationGraph, load_citation_graph
from factory.services.human_queue import human_queue
from factory.services.prisma import PrismaFlow, prisma_flow
from factory.services.work_layers import layers_of

METHODS: dict[str, str] = {
    "sets": (
        "Included is the PRISMA final set: the works included at full text (at title and abstract "
        "when the protocol has no full-text stage). Read in full is the set of works with a live "
        "first-pass row of a listed miner. Where they differ, every work is listed by id: a "
        "duplicate record that was read under its own id is shown on the canonical record; a work "
        "that was read but excluded is listed with its exclusion criterion and not shown in "
        "corpus views; a work read under a duplicate record whose canonical record is not "
        "included is listed apart as 'duplicate of an excluded work' and not shown in corpus "
        "views; an "
        "included work with no rows of its own or of a merged duplicate is "
        "'not read yet'."
    ),
    "fates": (
        "Every identified record has one final fate: removed as a duplicate, excluded at title "
        "and abstract (by criterion), not sought, not retrieved, excluded at full text (by "
        "criterion), still pending, or included. The groups are exclusive and their sizes sum to "
        "the number of identified records; the PRISMA figures beside them come from the same "
        "events and are checked against the groups."
    ),
    "cited_here": (
        "The number of distinct included works that cite a work through a live reference link "
        "(resolved, or confirmed by the researcher) between two works. A work citing itself is "
        "not counted, and neither is a citer outside the included set. Author self-citation, a "
        "citer sharing a normalised author name with the cited work, is counted and shown "
        "separately. The count is a lower bound: it depends on how many reference lists were "
        "extracted and matched. The citation report counts resolved links only and reports a "
        "different set; the two are never mixed on one page."
    ),
    "human_role": (
        "The share of included works whose human position, as read by the mapping miner, is "
        "'none', among the included works that carry a value. Works not yet read are not in "
        "the denominator and are counted apart."
    ),
    "papers_per_month": (
        "Included works counted by the month of their publication date; months with none are "
        "shown as zero between the first and the last. Works dated to a year only, and works "
        "with no usable date, are not placed in a month and are counted apart."
    ),
    "composition": (
        "Included works grouped by layer (the researcher's move, else the layer miner's final "
        "row) and by human position. A work with no layer is 'unlayered'; one with no human "
        "position is 'not coded'."
    ),
}

UNLAYERED = site_corpus.UNLAYERED
NOT_CODED = "null"
MINED_ON_DUPLICATE = "duplicate"

FATE_LABELS: dict[str, str] = {
    "duplicate": "Removed as duplicate",
    "ta_excluded": "Excluded at title and abstract",
    "ta_pending": "Awaiting title and abstract",
    "not_sought": "Full text not sought",
    "not_retrieved": "Full text not retrieved",
    "ft_excluded": "Excluded at full text",
    "ft_pending": "Awaiting full-text decision",
    "included": "Included",
}
FATE_ORDER = tuple(FATE_LABELS)


# ------------------------------------------------------------------ sets


@dataclass(frozen=True)
class DuplicateMapped:
    """A work read under the id of an absorbed duplicate; its rows show on `canonical_id`."""

    mined_id: str
    canonical_id: str
    canonical_also_mined: bool


@dataclass(frozen=True)
class MinedButExcluded:
    """A work with miner rows that is not in the included set. `stage` is where it left."""

    work_id: str
    stage: str
    criterion: str | None


@dataclass(frozen=True)
class Sets:
    """The included and read-in-full sets and their differences, each by id with its reason."""

    included: tuple[str, ...]
    read_in_full: tuple[str, ...]
    duplicate_mapped: tuple[DuplicateMapped, ...]
    mined_but_excluded: tuple[MinedButExcluded, ...]
    not_read_yet: tuple[str, ...]
    sources: Mapping[str, str] = field(default_factory=dict)
    """Included work id -> the work id whose miner rows it shows, where that is not its own."""
    duplicate_of_excluded: tuple[DuplicateMapped, ...] = ()
    """Works read under an absorbed duplicate whose canonical record is not in the included set;
    not shown in corpus views, listed here by id."""

    def miner_source(self, work_id: str) -> str:
        """The work id whose miner rows to show for `work_id` (itself unless a duplicate holds
        the only rows)."""
        return self.sources.get(work_id, work_id)


def reconcile_sets(
    included: Iterable[str],
    mined: Iterable[str],
    canonical_of: Mapping[str, str],
    fate_of: Mapping[str, tuple[str, str | None]] | None = None,
) -> Sets:
    """Apply the 4.1 rule to plain data.

    `canonical_of` maps an absorbed duplicate to its canonical id; `fate_of` maps a work id to
    `(stage, criterion)` for the excluded list (unknown ids get stage `unknown`)."""
    inc = sorted(set(included))
    inc_set = set(inc)
    mined_set = set(mined)
    fates = fate_of or {}
    all_dup = [
        DuplicateMapped(m, canonical_of[m], canonical_of[m] in mined_set)
        for m in sorted(mined_set)
        if m in canonical_of
    ]
    dup = [d for d in all_dup if d.canonical_id in inc_set]
    dup_excluded = [d for d in all_dup if d.canonical_id not in inc_set]
    excluded = []
    for m in sorted(mined_set):
        if m in inc_set or m in canonical_of:
            continue
        stage, criterion = fates.get(m, ("unknown", None))
        excluded.append(MinedButExcluded(m, stage, criterion))
    held_by_dup: dict[str, str] = {}
    for d in dup:
        if d.canonical_id in inc_set:
            held_by_dup.setdefault(d.canonical_id, d.mined_id)
    sources = {c: m for c, m in held_by_dup.items() if c not in mined_set}
    unread = [w for w in inc if w not in mined_set and w not in held_by_dup]
    return Sets(
        included=tuple(inc),
        read_in_full=tuple(sorted(mined_set)),
        duplicate_mapped=tuple(dup),
        mined_but_excluded=tuple(excluded),
        not_read_yet=tuple(unread),
        sources=sources,
        duplicate_of_excluded=tuple(dup_excluded),
    )


def included_ids(rows: Iterable[LedgerRow], stage_run: bool) -> list[str]:
    """The PRISMA final included set from ledger rows (canonical works only)."""
    out = []
    for r in rows:
        if r.canonical_id is not None:
            continue
        if stage_run:
            if r.ft_outcome == "included":
                out.append(r.work_id)
        elif r.ta_outcome is Outcome.INCLUDED:
            out.append(r.work_id)
    return sorted(out)


def load_read_in_full(project: Project) -> set[str]:
    """Works with a live pass-A row of a listed miner and a stored record: the selection of
    `site_corpus.corpus_payload`, re-queried the same way (read-only)."""
    profile = site_corpus.load_profile(project)
    listed = site_corpus._listed_schemas(project)
    schemas = sorted({listed[m] for m in profile.roles.values() if m in listed})
    found: set[str] = set()
    with project.index.connect() as conn:
        for schema in schemas:
            for (wid,) in conn.execute(
                text(
                    "SELECT work_id FROM extraction_rows WHERE pass_label = 'A' "
                    "AND superseded_by IS NULL AND schema_ref = :s"
                ),
                {"s": schema},
            ):
                found.add(str(wid))
        known = {str(w) for (w,) in conn.execute(text("SELECT work_id FROM works"))}
    return found & known


# ------------------------------------------------------------------ flow data


@dataclass(frozen=True)
class FlowData:
    """What `flow_payload` and `overview_payload` share, loaded once."""

    prisma: PrismaFlow
    rows: tuple[LedgerRow, ...]
    sets: Sets


def load_flow_data(project: Project) -> FlowData:
    """Compute `prisma_flow`, the ledger (about a minute on the pilot) and the sets once.

    Raises ValueError when the ledger's included count differs from PRISMA's."""
    project.index.sync()
    flow = prisma_flow(project)
    rows = flow_ledger(project)
    stage_run = flow.full_text.stage_run
    inc = included_ids(rows, stage_run)
    expected = flow.included_in_review if stage_run else flow.included
    if len(inc) != expected:
        raise ValueError(f"ledger includes {len(inc)} works, prisma_flow {expected}")
    canonical_of = {r.work_id: r.canonical_id for r in rows if r.canonical_id is not None}
    fates = {r.work_id: _stage_criterion(r) for r in rows}
    sets = reconcile_sets(inc, load_read_in_full(project), canonical_of, fates)
    return FlowData(flow, tuple(rows), sets)


def _stage_criterion(row: LedgerRow) -> tuple[str, str | None]:
    if row.ft_outcome == "excluded":
        return "full_text", row.ft_criterion
    if row.ta_outcome is Outcome.EXCLUDED:
        return "title_abstract", row.ta_criterion
    return "not_excluded", None


def fate_of(row: LedgerRow, stage_run: bool) -> tuple[str, str | None]:
    """The final fate group of one ledger row and its criterion (excluded groups only)."""
    if row.canonical_id is not None:
        return "duplicate", None
    if row.ta_outcome is Outcome.EXCLUDED:
        return "ta_excluded", row.ta_criterion
    if row.ta_outcome is not Outcome.INCLUDED:
        return "ta_pending", None
    if not stage_run or row.ft_state is None:
        return "included", None
    if row.ft_state == "not-sought":
        return "not_sought", None
    if row.ft_state == "attempted-failed":
        return "not_retrieved", None
    if row.ft_outcome == "included":
        return "included", None
    if row.ft_outcome == "excluded":
        return "ft_excluded", row.ft_criterion
    return "ft_pending", None


def sets_payload(sets: Sets) -> dict[str, Any]:
    """The sets as JSON-safe data."""
    return {
        "included": list(sets.included),
        "read_in_full": list(sets.read_in_full),
        "duplicate_mapped": [asdict(d) for d in sets.duplicate_mapped],
        "mined_but_excluded": [asdict(e) for e in sets.mined_but_excluded],
        "not_read_yet": list(sets.not_read_yet),
        "duplicate_of_excluded": [asdict(d) for d in sets.duplicate_of_excluded],
        "sources": dict(sorted(sets.sources.items())),
        "methods": METHODS["sets"],
    }


def flow_payload(project: Project, data: FlowData | None = None) -> dict[str, Any]:
    """PRISMA figures, per-record fates grouped with work ids, and the sets reconciliation."""
    d = data or load_flow_data(project)
    stage_run = d.prisma.full_text.stage_run
    groups: dict[str, list[str]] = {k: [] for k in FATE_ORDER}
    by_criterion: dict[str, dict[str, list[str]]] = {k: {} for k in FATE_ORDER}
    records = []
    for r in d.rows:
        key, crit = fate_of(r, stage_run)
        groups[key].append(r.work_id)
        if crit is not None:
            by_criterion[key].setdefault(crit, []).append(r.work_id)
        records.append(
            {
                "id": r.work_id,
                "title": r.title,
                "year": r.year,
                "fate": key,
                "criterion": crit,
                "source": r.source_group,
            }
        )
    identified = sum(d.prisma.identified_databases.values()) + sum(
        d.prisma.identified_other.values()
    )
    out_groups = [
        {
            "key": k,
            "label": FATE_LABELS[k],
            "n": len(groups[k]),
            "works": groups[k],
            "by_criterion": {
                c: {"n": len(ids), "works": ids} for c, ids in sorted(by_criterion[k].items())
            },
        }
        for k in FATE_ORDER
    ]
    return {
        "prisma": d.prisma.model_dump(mode="json"),
        "identified": identified,
        "records_total": len(d.rows),
        "groups": out_groups,
        "groups_sum": sum(len(v) for v in groups.values()),
        "reconciles": sum(len(v) for v in groups.values()) == identified,
        "records": records,
        "sets": sets_payload(d.sets),
        "methods": {"fates": METHODS["fates"], "sets": METHODS["sets"]},
    }


# ------------------------------------------------------------------ cited here


@dataclass(frozen=True)
class CitedHere:
    """Distinct included citers of one work and how many of them share an author with it."""

    count: int
    self_count: int
    citers: tuple[str, ...]


def cited_here_from(
    graph: CitationGraph,
    included: Iterable[str],
    names: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, CitedHere]:
    """Per included work, its distinct included citers (self-loops dropped). `names` maps a
    work id to its normalised author names for the self-citation share."""
    inc = set(included)
    who: dict[str, set[str]] = defaultdict(set)
    for citing, cited in graph.edges:
        if citing != cited and citing in inc and cited in inc:
            who[cited].add(citing)
    nm = names or {}
    out: dict[str, CitedHere] = {}
    for w in sorted(inc):
        cs = sorted(who.get(w, ()))
        own = sum(1 for c in cs if nm.get(c, frozenset()) & nm.get(w, frozenset()))
        out[w] = CitedHere(len(cs), own, tuple(cs))
    return out


def load_author_names(project: Project, ids: Iterable[str]) -> dict[str, frozenset[str]]:
    """Normalised author names per work, by the rule of `citations` (read-only)."""
    wanted = set(ids)
    with project.index.connect() as conn:
        return {
            str(w): _meta(str(data))[2]
            for w, data in conn.execute(text("SELECT work_id, data FROM works"))
            if str(w) in wanted
        }


def cited_here(
    project: Project, included: Iterable[str], graph: CitationGraph | None = None
) -> dict[str, CitedHere]:
    """`cited_here_from` over the live citation graph of the project (the source `hub_graph`
    uses for its pages, so the figures agree)."""
    inc = sorted(set(included))
    return cited_here_from(
        graph or load_citation_graph(project), inc, load_author_names(project, inc)
    )


# ------------------------------------------------------------------ overview


def human_share(values: Mapping[str, str | None]) -> dict[str, Any]:
    """The human-position composition of works: `values` maps work id to its value or None."""
    coded = {w: v for w, v in values.items() if v}
    n_none = sum(1 for v in coded.values() if v == "none")
    return {
        "coded": len(coded),
        "none": n_none,
        "share_none": (n_none / len(coded)) if coded else None,
        "not_coded": len(values) - len(coded),
        "by_value": dict(sorted(Counter(coded.values()).items())),
    }


def month_counts(months: Iterable[str]) -> dict[str, Any]:
    """Counts per `YYYY-MM`, continuous from the first to the last month, plus the busiest.

    Every input is accounted for: dated to the month (in `counts`), `year_only` (`YYYY`) or
    `unknown_date` (empty or unparseable)."""
    given = list(months)
    ms = sorted(m for m in given if len(m) == 7 and m[4] == "-" and m[:4].isdigit())
    year_only = sum(1 for m in given if len(m) == 4 and m.isdigit())
    unknown = len(given) - len(ms) - year_only
    if not ms:
        return {
            "months": [],
            "counts": [],
            "busiest": None,
            "unknown_date": unknown,
            "year_only": year_only,
        }
    c = Counter(ms)
    y, m = int(ms[0][:4]), int(ms[0][5:])
    ye, me = int(ms[-1][:4]), int(ms[-1][5:])
    labels: list[str] = []
    while (y, m) <= (ye, me):
        labels.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    counts = [c.get(k, 0) for k in labels]
    top = max(range(len(counts)), key=lambda i: (counts[i], -i))
    return {
        "months": labels,
        "counts": counts,
        "busiest": {"month": labels[top], "n": counts[top]},
        "unknown_date": unknown,
        "year_only": year_only,
    }


def _load_publication(project: Project, ids: Iterable[str]) -> dict[str, tuple[str, str]]:
    """work id -> (title, published date string) for `ids`."""
    wanted = set(ids)
    out: dict[str, tuple[str, str]] = {}
    with project.index.connect() as conn:
        for w, data in conn.execute(text("SELECT work_id, data FROM works")):
            if str(w) in wanted:
                d = json.loads(str(data))
                out[str(w)] = (
                    str(d.get("title") or w),
                    str((d.get("dates") or {}).get("published") or ""),
                )
    return out


def _load_role_cells(
    project: Project, source_of: Mapping[str, str], dim_key: str
) -> dict[str, tuple[str, str] | None]:
    """The first pass-A (value, quote) of a profile dimension of each work's source, or None."""
    profile = site_corpus.load_profile(project)
    dim = next((d for d in profile.dims if d[0] == dim_key), None)
    out: dict[str, tuple[str, str] | None] = dict.fromkeys(source_of)
    if dim is None:
        return out
    listed = site_corpus._listed_schemas(project)
    schema = listed.get(profile.roles.get(dim[2], ""))
    if schema is None:
        return out
    sources = set(source_of.values())
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.work_id, f.value, f.quote FROM extraction_rows r "
                "JOIN extraction_fields f "
                "USING (extraction_id) WHERE r.pass_label = 'A' AND r.superseded_by IS NULL "
                "AND r.schema_ref = :s AND f.field = :f ORDER BY r.extraction_id"
            ),
            {"s": schema, "f": dim[3]},
        ).all()
    first: dict[str, tuple[str, str]] = {}
    for w, v, q in rows:
        if str(w) in sources and v:
            first.setdefault(str(w), (str(v), str(q or "")))
    return {w: first.get(src) for w, src in source_of.items()}


def _load_role_field(
    project: Project, source_of: Mapping[str, str], dim_key: str
) -> dict[str, str | None]:
    """The first pass-A value of a profile dimension (role + field) of each work's source."""
    cells = _load_role_cells(project, source_of, dim_key)
    return {w: (c[0] if c else None) for w, c in cells.items()}


def pipeline_strip(d: FlowData) -> list[dict[str, Any]]:
    """The five-step strip of the Overview from the PRISMA figures; each step has its losses."""
    p = d.prisma
    ft = p.full_text
    identified = sum(p.identified_databases.values()) + sum(p.identified_other.values())
    included = len(d.sets.included)
    head: list[dict[str, Any]] = [
        {"key": "identified", "n": identified, "of": None, "loss": {}},
        {
            "key": "screened",
            "n": p.screened,
            "of": identified,
            "loss": {"duplicates": p.duplicates_removed},
        },
    ]
    if not ft.stage_run:
        # No full-text stage has run: the included set is the title-and-abstract one, and the
        # steps between are stated as not run rather than shown as zero.
        return [
            *head,
            {"key": "sought", "n": None, "of": None, "loss": {}, "not_run": True},
            {"key": "assessed", "n": None, "of": None, "loss": {}, "not_run": True},
            {"key": "included", "n": included, "of": p.screened, "loss": {}},
        ]
    return [
        *head,
        {
            "key": "sought",
            "n": ft.sought,
            "of": p.included,
            "loss": {"not_sought": ft.not_sought},
        },
        {
            "key": "assessed",
            "n": ft.assessed,
            "of": ft.sought,
            "loss": {"not_retrieved": ft.not_retrieved, "pending": ft.pending},
        },
        {
            "key": "included",
            "n": included,
            "of": ft.assessed,
            "loss": {"excluded_full_text": ft.excluded_total},
        },
    ]


def overview_payload(project: Project, data: FlowData | None = None) -> dict[str, Any]:
    """Lead facts, pipeline strip, papers per month, composition, most cited and next actions."""
    d = data or load_flow_data(project)
    inc = list(d.sets.included)
    source_of = {w: d.sets.miner_source(w) for w in inc}
    human_values = _load_role_field(project, source_of, "human")
    humans = human_share(human_values)
    cites = cited_here(project, inc)
    pub = _load_publication(project, inc)
    layers = layers_of(project)

    def layer_of(w: str) -> str:
        wl = layers.get(w) or layers.get(source_of[w])
        return wl.layer if wl is not None and wl.layer else UNLAYERED

    by_layer = Counter(layer_of(w) for w in inc)
    by_human = Counter(v or NOT_CODED for v in human_values.values())
    top = sorted(inc, key=lambda w: (-cites[w].count, w))[:8]
    return {
        "lead": {
            "included": len(inc),
            "screened": d.prisma.screened,
            "identified": sum(d.prisma.identified_databases.values())
            + sum(d.prisma.identified_other.values()),
            "read_in_full": len(d.sets.read_in_full),
            "human": humans,
        },
        "pipeline": pipeline_strip(d),
        "papers_per_month": month_counts(pub[w][1][:7] if w in pub else "" for w in inc),
        "composition": {
            "layer": dict(sorted(by_layer.items())),
            "human": dict(sorted(by_human.items())),
        },
        "most_cited": [
            {
                "id": w,
                "title": pub.get(w, (w, ""))[0],
                "cited_here": cites[w].count,
                "self_cited": cites[w].self_count,
                "layer": layer_of(w),
            }
            for w in top
        ],
        "cited_here": {w: [c.count, c.self_count] for w, c in cites.items()},
        "sets": sets_payload(d.sets),
        "next_actions": [i.model_dump(mode="json") for i in human_queue(project).items],
        "methods": {
            k: METHODS[k]
            for k in ("sets", "cited_here", "human_role", "papers_per_month", "composition")
        },
    }
