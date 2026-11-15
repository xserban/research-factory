"""The registered taxonomies on the taxonomy product (decision 127 item 5, decision 120).

Read-only over the index and blobs. The index page lists each `t-...` name with its versions;
every version has a page with its dimensions and categories; a taxonomy with more than one version
shows the computed `diff` between consecutive versions. When a derived miner projects the version
(`MinerSpec.taxonomy`), each category shows the number of works with a current pass-A row for it
and the page links the miner page; otherwise the page says so. Counts are computed, never typed.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import bindparam, text

from factory.mining.spec import MinerSpec
from factory.mining.taxonomy import (
    Category,
    Dimension,
    TaxonomyDiff,
    TaxonomySpec,
    diff,
    full_id,
)
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.services import mining as mining_service
from factory.services import taxonomies as tax_service
from factory.services.context import Project
from factory.services.extraction import live_rows, stale_extractions
from factory.services.site_corpus import slug_of
from factory.services.site_widgets import Html, esc, note, section, table

CATEGORY_FIELD = "category"


@dataclass(frozen=True)
class DerivedMiner:
    """A registered miner that projects one taxonomy version, with the per-category counts of
    works holding a current row."""

    name: str
    version: int
    counts: dict[str, int]
    page: bool  # the Miners product has a page for it
    dimensions: tuple[str, ...]  # the dimensions the miner projects; other dimensions are not mined


def category_counts(rows: Iterable[tuple[str, str]]) -> dict[str, int]:
    """Distinct works per category value from `(work_id, category)` pairs."""
    seen: dict[str, set[str]] = {}
    for work_id, value in rows:
        seen.setdefault(value, set()).add(work_id)
    return {value: len(works) for value, works in seen.items()}


def derived_counts(project: Project, miner: str, version: int | None = None) -> dict[str, int]:
    """Category counts from the live, non-stale pass-A rows of `miner` (calibration rows apart).
    When the miner is listed in the protocol, only works in its current population count, so rows
    of works no longer in it are left out."""
    stale = stale_extractions(project, scope=MinerScope(miner))
    keep: set[str] | None = None
    if version is not None and miner in {s.name for s in mining_service.mine_status(project)}:
        keep = set(mining_service.miner_population(project, miner))
    pairs = [
        (row.work_id, str(row.fields[CATEGORY_FIELD].value))
        for row in live_rows(project, PassLabel.A, scope=MinerScope(miner))
        if row.extraction_id not in stale
        and CATEGORY_FIELD in row.fields
        and (keep is None or row.work_id in keep)
    ]
    return category_counts(pairs)


def _registration_order(project: Project, event_ids: list[str]) -> dict[str, tuple[str, str]]:
    """`(ts, id)` of each registration event, the key that orders registrations."""
    if not event_ids:
        return {}
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT id, ts FROM events WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": event_ids},
        ).all()
    return {str(i): (str(t), str(i)) for i, t in found}


def derived_miner(project: Project, name: str, version: int) -> DerivedMiner | None:
    """The latest registered non-retired miner version whose spec references taxonomy
    `(name, version)`: latest by registration event order, not by name."""
    candidates: list[tuple[MinerSpec, str]] = []
    for row in mining_service.registered_miners(project):
        if row.retired:
            continue
        spec = mining_service.registered_miner(project, row.name, row.version)
        if spec is None or spec.taxonomy is None:
            continue
        if (spec.taxonomy.name, spec.taxonomy.version) != (name, version):
            continue
        candidates.append((spec, row.event_id))
    if not candidates:
        return None
    order = _registration_order(project, [e for _, e in candidates])
    best = max(candidates, key=lambda c: order.get(c[1], ("", c[1])))[0]
    assert best.taxonomy is not None
    listed = {s.name for s in mining_service.mine_status(project)}
    return DerivedMiner(
        best.name,
        best.version,
        derived_counts(project, best.name, best.version),
        best.name in listed,
        tuple(best.taxonomy.dimensions),
    )


def _dates(project: Project, event_ids: list[str]) -> dict[str, str]:
    if not event_ids:
        return {}
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT id, substr(ts, 1, 10) FROM events WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": event_ids},
        ).all()
    return {str(i): str(d) for i, d in found}


def _work_link(work_id: str) -> Html:
    slug = urllib.parse.quote(slug_of(work_id), safe="")
    return Html(f"<a href='../explorer/index.html#open={esc(slug)}'>{esc(work_id)}</a>")


def _page_name(name: str, version: int, latest: int) -> str:
    return f"{name}.html" if version == latest else f"{name}-v{version}.html"


def _list(items: Iterable[str]) -> str:
    items = list(items)
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else "none"


def _category_block(
    dim: Dimension, cat: Category, counts: dict[str, int] | None, mined: bool = True
) -> str:
    head = f"<h4 id='{esc(full_id(dim.id, cat.id))}'>{esc(cat.id)} — {esc(cat.name)}</h4>"
    rows: list[list[object]] = [["definition", cat.definition]]
    if counts is not None:
        rows.append(
            [
                "works with a current row",
                counts.get(full_id(dim.id, cat.id), 0) if mined else "not mined",
            ]
        )
    rows.append(["include cues", Html(_list(cat.include_cues))])
    rows.append(["exclude cues", Html(_list(cat.exclude_cues))])
    if cat.examples:
        shown = (
            "<ul>"
            + "".join(
                f"<li>“{esc(e.quote)}” ({_work_link(e.work_id)}, {esc(e.anchor)})</li>"
                for e in cat.examples
            )
            + "</ul>"
        )
        rows.append(["examples", Html(shown)])
    return head + table(["", ""], rows)


def render_diff(change: TaxonomyDiff, old: int, new: int) -> str:
    """The computed difference from version `old` to `new`."""
    rows: list[list[object]] = [
        ["added", ", ".join(change.added) or "none"],
        ["removed", ", ".join(change.removed) or "none"],
        ["redefined", ", ".join(change.redefined) or "none"],
        ["renamed", ", ".join(change.renamed) or "none"],
        ["split", "; ".join(f"{p} into {', '.join(k)}" for p, k in change.split) or "none"],
        [
            "merged",
            "; ".join(f"{', '.join(p)} into {c}" for p, c in change.merged) or "none",
        ],
        ["dimensions", "; ".join(f"{d}: {w}" for d, w in change.dimension_changes) or "none"],
    ]
    return f"<h3>Changes from version {old} to {new}</h3>" + table(["", ""], rows)


def render_version(
    spec: TaxonomySpec,
    *,
    versions: list[int],
    latest: int,
    miner: DerivedMiner | None,
    previous: TaxonomySpec | None,
    open_proposals: int,
) -> str:
    """The body of one version's page."""
    body = f"<h1>{esc(spec.name)} version {spec.version}</h1>"
    body += (
        "<p class=dim>Versions: "
        + ", ".join(
            f"<a href='{esc(_page_name(spec.name, v, latest))}'>{v}</a>"
            for v in sorted(versions, reverse=True)
        )
        + f". Open proposals: {open_proposals}.</p>"
    )
    if spec.rationale:
        body += note(spec.rationale)
    if miner is None:
        body += note("No derived miner yet.")
    else:
        link = (
            f"<a href='../miners/{esc(miner.name)}.html'>{esc(miner.name)}</a>"
            if miner.page
            else esc(miner.name)
        )
        body += (
            f"<p>Derived miner: {link} version {miner.version}. "
            "Counts are works with a current row.</p>"
        )
    if previous is not None:
        body += render_diff(diff(previous, spec), previous.version, spec.version)
    for dim in spec.dimensions:
        info = table(
            ["", ""],
            [
                ["question", dim.question],
                ["cardinality", dim.cardinality],
                [
                    "read scope",
                    "whole text"
                    if dim.read_scope.whole_text
                    else ", ".join(dim.read_scope.headings) or "none",
                ],
                ["residuals", ", ".join(dim.residuals) or "none"],
            ],
        )
        mined = miner is not None and dim.id in miner.dimensions
        cats = "".join(
            _category_block(dim, c, None if miner is None else miner.counts, mined)
            for c in dim.categories
        )
        if miner is not None and mined:
            residual = ", ".join(
                f"{r} {miner.counts.get(full_id(dim.id, r), 0)}" for r in dim.residuals
            )
            if residual:
                cats += f"<p class=dim>Residuals (works): {esc(residual)}.</p>"
        if not dim.categories and dim.layer_scheme is not None:
            cats = note(f"Categories come from layer scheme version {dim.layer_scheme}.")
        body += section(f"{dim.title} ({dim.id})", info + cats)
    return body


def render_index(project: Project) -> str:
    """The 'Registered taxonomies' section of the index page; writes nothing."""
    summaries = _summaries(project)
    if not summaries:
        return section(
            "Registered taxonomies",
            note("No taxonomy is registered yet (decision 120: the researcher registers them)."),
        )
    rows: list[list[object]] = []
    for name, entries, open_n in summaries:
        latest = entries[-1][0]
        lines = []
        for v, row_digest, date, dims, cats in reversed(entries):
            lines.append(
                f"<a href='{esc(_page_name(name, v, latest))}'>v{v}</a> "
                f"<code>{esc(row_digest[:12])}</code> {esc(date)}, "
                f"{dims} dimensions, {cats} categories"
            )
        rows.append([Html(esc(name)), Html("<br>".join(lines)), open_n])
    return section(
        "Registered taxonomies", table(["name", "versions (latest first)", "open proposals"], rows)
    )


def _summaries(project: Project) -> list[tuple[str, list[tuple[int, str, str, int, int]], int]]:
    rows = tax_service.list_taxonomies(project)
    dates = _dates(project, [r.event_id for r in rows])
    by_name: dict[str, list[tuple[int, str, str, int, int]]] = {}
    for r in rows:
        spec = tax_service.registered_taxonomy(project, r.name, r.version)
        dims = 0 if spec is None else len(spec.dimensions)
        cats = 0 if spec is None else sum(len(d.categories) for d in spec.dimensions)
        by_name.setdefault(r.name, []).append(
            (r.version, r.digest, dates.get(r.event_id, ""), dims, cats)
        )
    result = []
    for name, entries in by_name.items():
        open_n = sum(1 for p in tax_service.list_proposals(project, name) if p.status == "open")
        result.append((name, sorted(entries), open_n))
    return result


def write_registered(project: Project, out: Path, page: Callable[..., str]) -> None:
    """One page per registered version; the latest is `<name>.html`."""
    from factory.services.site_widgets import REPORT_CSS

    rows = tax_service.list_taxonomies(project)
    versions: dict[str, list[int]] = {}
    for r in rows:
        versions.setdefault(r.name, []).append(r.version)
    for name, vs in versions.items():
        vs.sort()
        latest = vs[-1]
        open_n = sum(1 for p in tax_service.list_proposals(project, name) if p.status == "open")
        specs = {v: tax_service.registered_taxonomy(project, name, v) for v in vs}
        for i, v in enumerate(vs):
            spec = specs[v]
            if spec is None:
                continue
            body = render_version(
                spec,
                versions=vs,
                latest=latest,
                miner=derived_miner(project, name, v),
                previous=specs[vs[i - 1]] if i else None,
                open_proposals=open_n,
            )
            (out / _page_name(name, v, latest)).write_text(
                page(f"{name} v{v}", body, REPORT_CSS), encoding="utf-8"
            )
