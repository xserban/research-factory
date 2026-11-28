"""The corpus payload the explorer and the wiki products are built from (plan site-hub, step 2).

One read-only join of what the project recorded: each work's metadata, the rows of the listed miners
(pass A, live), the stored documents and the resolved citation links between works of the corpus.
Nothing here judges, and nothing is written.

A **profile** says which miner plays which role in the explorer (classification, mapping, summary,
descriptors, stages, results) and which fields are filter dimensions. The default profile fits the
AI-research-system miners of the pilot; a project overrides it with `<project>/site-profile.json`
(`{"roles": {...}, "dims": [[key, label, role, field], ...]}`), so project-specific choices live in
the project, not in code. A role whose miner has no rows is simply empty.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text

from factory.services import hub_facets
from factory.services.capture_hints import WorkOrigin, origins_of
from factory.services.citations import cited_by_counts
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.work_layers import WorkLayer, layers_of

PROFILE_FILE = "site-profile.json"
DEFAULT_ROLES: dict[str, str] = dict(hub_facets.LEGACY_ROLE_MINERS)
META_ROLE = "meta"
SUMMARY_ORDER: tuple[tuple[str, str], ...] = (
    ("problem_gap", "Problem and gap"),
    ("core_innovation", "Core innovation"),
    ("contribution_type", "Contribution type"),
    ("innovation_axis", "Novelty is about"),
    ("builds_on", "Builds on"),
    ("builds_on_relation", "Relation"),
    ("improves_over", "Improves over"),
    ("improvement_aspect", "Improves"),
    ("benchmark_role", "Benchmark"),
    ("benchmark_named", "Benchmark named"),
    ("headline_result", "Headline result"),
    ("validation_level", "Validation"),
    ("claimed_discovery", "Claimed discovery"),
    ("failure_modes", "Failure modes"),
    ("limitations", "Limitations"),
    ("future_work", "Future work"),
    ("availability", "Availability"),
    ("cost_compute", "Cost and compute"),
)
MAX_QUOTE = 400
MAX_ABSTRACT = 1800
DESIGN_FIELDS = (
    "system",
    "stage",
    "approach",
    "system_role",
    "evidence_grade",
    "value_kind",
    "metric",
)


UNLAYERED = "unlayered"
"""The layer value of a work with no layer row (pending included): the explorer never says
`pending`."""


def layer_fields(wl: WorkLayer | None) -> dict[str, str]:
    """The layer keys of one work in the payload: `layer`, and `layer_source` (`miner` or `moved`,
    empty when unlayered) and `layer_miner` (what the miner said, empty without one)."""
    if wl is None or wl.layer is None:
        return {"layer": UNLAYERED, "layer_source": "", "layer_miner": ""}
    return {
        "layer": wl.layer,
        "layer_source": wl.source,
        "layer_miner": wl.miner_layer or "",
    }


def origin_fields(origin: WorkOrigin | None) -> dict[str, str]:
    """The origin keys of one work in the payload (IDEA-81): `origin` is `inbox` or `feed` and
    `origin_channel` the capturing channel, both empty for a work that came by search or seed.
    Computed from events (`capture_hints.origins_of`); the explorer filters on `origin`."""
    if origin is None:
        return {"origin": "", "origin_channel": ""}
    return {"origin": origin.kind, "origin_channel": origin.channel}


@dataclass(frozen=True)
class Profile:
    """Roles (role -> miner name) and the dimensions `(key, label, role, field)` of the explorer.
    `role` is a key of `roles`, `meta` (the work's own metadata) or, for a facet of a project's own
    miner, the miner name. `extra` holds the facets' descriptions and value labels by key."""

    roles: dict[str, str]
    dims: tuple[tuple[str, str, str, str], ...]
    extra: dict[str, hub_facets.Facet] = field(default_factory=dict)

    def miner_of(self, role: str) -> str:
        """The miner a role or a miner name stands for (empty for `meta`)."""
        return "" if role == META_ROLE else self.roles.get(role, role)

    def miners(self) -> list[str]:
        """Every miner the profile reads: the role miners and the miners of the dimensions."""
        names = set(self.roles.values()) | {self.miner_of(d[2]) for d in self.dims}
        return sorted(names - {""})

    def dim(self, key: str) -> tuple[str, str, str, str] | None:
        """The dimension `key`; for a project with none of the pilot's four DNA keys, a DNA key
        (technique, architecture, span, human) stands for the facet at its position."""
        found = next((d for d in self.dims if d[0] == key), None)
        if found is not None:
            return found
        keys = [d[0] for d in self.dims if d[2] != META_ROLE]
        alias = hub_facets.slot_aliases(keys).get(key)
        return next((d for d in self.dims if d[0] == alias), None) if alias else None


def load_profile(project: Project) -> Profile:
    """The project's profile. Dimensions: the researcher's facet setting, else `dims` of
    `<project>/site-profile.json` when it has them, else the default facets (`services.hub_facets`).
    Roles: the default roles with the file's overrides."""
    path = project.paths.dir / PROFILE_FILE
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        loaded = {}
    roles = {**DEFAULT_ROLES, **{str(k): str(v) for k, v in loaded.get("roles", {}).items()}}
    facets = hub_facets.facets_of(project)
    extra = {f.key: f for f in facets}
    if hub_facets.facet_setting(project) is None and "dims" in loaded:
        dims = tuple((str(a), str(b), str(c), str(d)) for a, b, c, d in loaded["dims"])
    else:
        dims = (*(f.dim for f in facets), hub_facets.MONTH)
    return Profile(roles, dims, extra)


def slug_of(work_id: str) -> str:
    """A file-safe name of a work id."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", work_id.replace("rf:", ""))[:90]


def library_file(project: Project, raw_hash: str) -> Path:
    """The stored original of a document, by its content hash."""
    digest = raw_hash.split(":")[-1]
    return project.paths.library_dir / "sha256" / digest[:2] / digest[2:]


def _listed_schemas(project: Project) -> dict[str, str]:
    """`name@version` of each listed miner, by miner name."""
    protocol = current_protocol(project)
    if protocol is None:
        return {}
    return {u.name: f"{u.name}@{u.version}" for u in protocol.spec.miners or ()}


def _facet_values(
    profile: Profile,
    work_id: str,
    merged: Callable[[str, str], dict[str, tuple[str, str, str]]],
) -> dict[str, dict[str, str]]:
    """The values of the dimensions that read a miner outside the legacy roles, by dimension key."""
    out: dict[str, tuple[str, str, str]] = {}
    for key, _label, role, name in profile.dims:
        if role == META_ROLE or role in profile.roles:
            continue
        found = merged(work_id, role).get(name)
        if found is not None:
            out[key] = found
    return _pack(out)


def _dim_payload(profile: Profile) -> list[dict[str, Any]]:
    """The `dims` of the corpus payload: key, label, where a work holds the value (`src`, `field`),
    and from the facet the field's description and the value labels the spec names."""
    out: list[dict[str, Any]] = []
    for key, label, role, name in profile.dims:
        facet = profile.extra.get(key)
        generic = role != META_ROLE and role not in profile.roles
        out.append(
            {
                "key": key,
                "label": label,
                "src": "facets" if generic else role,
                "field": key if generic else name,
                "description": facet.description if facet else "",
                "values": dict(sorted(facet.values.items())) if facet else {},
            }
        )
    return out


def _pack(fields: dict[str, tuple[str, str, str]]) -> dict[str, dict[str, str]]:
    return {k: {"v": v[0], "q": v[1][:MAX_QUOTE], "a": v[2]} for k, v in fields.items()}


def corpus_payload(project: Project) -> dict[str, Any]:
    """Works, miner rows, documents and citation links as one JSON-ready dict.

    A work is in scope when a listed miner has a live pass-A row for it. Documents carry the media
    type and the stored file, so a product can link to the original. `cited_in_corpus` is the
    in-corpus citation count of `cited_by_counts` (computed once per payload); None when no
    reference list was extracted, so an unknown count is never shown as 0."""
    profile = load_profile(project)
    listed = _listed_schemas(project)
    schemas = sorted({listed[m] for m in profile.miners() if m in listed})
    rows_by_work: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    fields: dict[str, dict[str, tuple[str, str, str]]] = defaultdict(dict)
    docs: dict[str, tuple[str, str]] = {}
    works_data: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str]] = []
    n_ext = 0
    in_corpus = cited_by_counts(project)
    with project.index.connect() as conn:
        for schema in schemas:
            for eid, wid in conn.execute(
                text(
                    "SELECT extraction_id, work_id FROM extraction_rows WHERE pass_label = 'A' "
                    "AND superseded_by IS NULL AND schema_ref = :s"
                ),
                {"s": schema},
            ):
                rows_by_work[wid][schema].append(eid)
        wanted = {e for per in rows_by_work.values() for ids in per.values() for e in ids}
        for eid, name, value, quote, anchor in conn.execute(
            text("SELECT extraction_id, field, value, quote, anchor FROM extraction_fields")
        ):
            if eid in wanted:
                fields[eid].setdefault(name, (value or "", quote or "", anchor or ""))
        for wid, media, raw in conn.execute(
            text(
                "SELECT work_id, media_type, raw_hash FROM fulltext_documents "
                "WHERE superseded_by IS NULL"
            )
        ):
            if wid in rows_by_work:
                docs[wid] = (media, raw)
        for wid in rows_by_work:
            row = conn.execute(
                text("SELECT data FROM works WHERE work_id = :w"), {"w": wid}
            ).first()
            if row is not None:
                works_data[wid] = json.loads(row[0])
        edges = sorted(
            {
                (a, b)
                for a, b in conn.execute(
                    text(
                        "SELECT e.work_id, l.work_id FROM reference_links l JOIN "
                        "reference_extractions e USING (extraction_id) WHERE e.live = 1 "
                        "AND l.state = 'resolved' AND l.work_id IS NOT NULL"
                    )
                )
                if a in rows_by_work and b in rows_by_work and a != b
            }
        )
        n_ext = int(
            conn.execute(
                text("SELECT COUNT(DISTINCT work_id) FROM reference_extractions WHERE live = 1")
            ).scalar()
            or 0
        )

    def merged(wid: str, role: str) -> dict[str, tuple[str, str, str]]:
        schema = listed.get(profile.miner_of(role))
        out: dict[str, tuple[str, str, str]] = {}
        for eid in rows_by_work[wid].get(schema or "", []):
            for name, tup in fields[eid].items():
                out.setdefault(name, tup)
        return out

    layers = layers_of(project)
    origins = origins_of(project)
    works: list[dict[str, Any]] = []
    for wid in sorted(works_data):
        d = works_data[wid]
        ids = d.get("identifiers") or {}
        pub = (d.get("dates") or {}).get("published") or ""
        stage_rows: list[dict[str, str]] = []
        design: list[dict[str, str]] = []
        for role, sink in (("stages", stage_rows), ("design", design)):
            sref = listed.get(profile.roles.get(role, ""))
            for eid in rows_by_work[wid].get(sref or "", []):
                f = fields[eid]
                if role == "stages" and "stage" in f:
                    sink.append(
                        {
                            "stage": f["stage"][0],
                            "mode": (f.get("mode") or ("",))[0],
                            "quote": f["stage"][1],
                            "anchor": f["stage"][2],
                        }
                    )
                elif role == "design":
                    entry = {k: (f[k][0] if k in f else "") for k in DESIGN_FIELDS}
                    first = f.get("system") or f.get("approach") or ("", "", "")
                    entry["quote"] = first[1]
                    sink.append(entry)
        doc: dict[str, str] | None = None
        if wid in docs:
            media, raw = docs[wid]
            kind = {"application/pdf": "pdf", "text/html": "html"}.get(media, "tar")
            doc = {
                "kind": kind,
                "file": str(library_file(project, raw)),
                "name": f"{slug_of(wid)}.{kind}",
            }
        works.append(
            {
                "id": wid,
                "slug": slug_of(wid),
                "title": d.get("title") or wid,
                "authors": [a.get("name") for a in (d.get("authors") or [])][:8],
                "published": pub,
                "year": pub[:4],
                "month": pub[:7],
                "venue": (d.get("venue") or {}).get("name") or "",
                "doi": ids.get("doi"),
                "arxiv": ids.get("arxiv"),
                "cited_by": d.get("cited_by_count"),
                "cited_in_corpus": in_corpus.get(wid),
                "abstract": (d.get("abstract") or "")[:MAX_ABSTRACT],
                "cls": _pack(merged(wid, "cls")),
                "map": _pack(merged(wid, "map")),
                "sum": _pack(merged(wid, "sum")),
                "desc": _pack(merged(wid, "desc")),
                "facets": _facet_values(profile, wid, merged),
                "stages": stage_rows,
                "design": design[:30],
                "n_design": len(design),
                "doc": doc,
                **layer_fields(layers.get(wid)),
                **origin_fields(origins.get(wid)),
            }
        )
    from factory.services.site_layers import LAYER_ORDER  # site_layers imports this module

    by_slug = {w["id"]: w["slug"] for w in works}
    return {
        "dims": _dim_payload(profile),
        "works": works,
        "layer_order": list(LAYER_ORDER),
        "cites": [[by_slug[a], by_slug[b]] for a, b in edges],
        "refs_done": n_ext,
    }
