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

import json
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from factory.services import hub_graph, hub_lenses, hub_living, hub_screening, hub_ui
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

    def year_month(self, work_id: str) -> tuple[int | None, int | None]:
        date = self.publication.get(work_id, ("", ""))[1]
        year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None
        month = int(date[5:7]) if len(date) >= 7 and date[5:7].isdigit() else None
        return year, month


# ---------------------------------------------------------------- builders


def build_shell(ctx: HubContext) -> dict[str, Any]:
    """Slug, build time, PRISMA headline, included works (Ctrl-K, drawer), glossary and labels."""
    d = ctx.flow_data
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
            }
        )
    return {
        "slug": ctx.project.paths.slug,
        "generated": ctx.project.clock.now().isoformat(timespec="seconds"),
        "prisma": {
            "identified": sum(d.prisma.identified_databases.values())
            + sum(d.prisma.identified_other.values()),
            "screened": d.prisma.screened,
            "included": len(works),
            "read_in_full": len(d.sets.read_in_full),
        },
        "works": works,
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


def lens_works(ctx: HubContext) -> list[hub_lenses.LensWork]:
    """The included set as lens records, with the DNA dimensions the Explore wall uses."""
    fields = {k: ctx.field(k) for k in LENS_DIMS}
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


def build_lenses(ctx: HubContext) -> dict[str, Any]:
    return hub_lenses.lenses_payload(
        lens_works(ctx),
        matrix_dims=("technique", "architecture"),
        chain_dims=LENS_DIMS,
        trend_dim="technique",
        icicle_dims=("layer", "technique", "architecture"),
        assoc_dims=(*LENS_DIMS, "layer"),
        cites=lens_cites(ctx),
    )


def build_living(ctx: HubContext) -> dict[str, Any]:
    return hub_living.living_payload(ctx.project)


# Hook: `mining`, `findings` and `corpus` register here once their services exist, e.g.
# BUILDERS["mining"] = build_mining. A page lists the names it needs in hub_ui.PAGES.
BUILDERS: dict[str, Callable[[HubContext], dict[str, Any]]] = {
    "shell": build_shell,
    "overview": build_overview,
    "flow": build_flow,
    "screening": build_screening,
    "graph": build_graph,
    "lenses": build_lenses,
    "living": build_living,
}


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


def dumps(payload: object) -> str:
    """Deterministic JSON: sorted keys, UTF-8 text, NaN and infinity refused."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=None)


def build_static(
    project: Project, out_dir: Path, only: Collection[str] | None = None
) -> BuildReport:
    """Write ``data/<name>.json`` and ``.js``, ``assets/*`` and the pages whose payloads built.

    ``only`` limits the payload names (unknown names raise ValueError before anything is
    written); pages are written when every payload they need was built in this run."""
    if only is not None:
        unknown = sorted(set(only) - set(BUILDERS))
        if unknown:
            raise ValueError(
                f"unknown payload(s): {', '.join(unknown)}; known: {', '.join(BUILDERS)}"
            )
    names = [n for n in BUILDERS if only is None or n in only]
    ctx = HubContext(project)
    report = BuildReport()
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        started = time.perf_counter()
        try:
            text = dumps(BUILDERS[name](ctx))
        except Exception as exc:
            report.errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        (data_dir / f"{name}.json").write_text(text + "\n", encoding="utf-8")
        (data_dir / f"{name}.js").write_text(
            f"window.HUB_DATA=window.HUB_DATA||{{}};HUB_DATA[{json.dumps(name)}]={text};\n",
            encoding="utf-8",
        )
        report.payloads[name] = PayloadReport(
            round(time.perf_counter() - started, 2), len(text.encode("utf-8")) + 1
        )
    for asset in hub_ui.ASSETS:
        target = out_dir / "assets" / asset
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(hub_ui.asset_bytes(asset))
    version = hub_ui.asset_version()
    for spec in hub_ui.PAGES.values():
        missing = [n for n in spec.payloads if n not in report.payloads]
        if only is not None and not set(spec.payloads) <= set(names):
            continue
        if missing:
            report.skipped_pages[spec.id] = missing
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
    return lines
