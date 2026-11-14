# ruff: noqa: E501
"""The project site: every product of the factory in one hub (plan 2026-11-10-site-hub, step 1).

A **product** is anything the factory produces for a person to read: the dashboard, the PRISMA flow,
the bibliography, and later the explorer, the results, the wiki and the synthesis pages. Each is a
rebuildable projection of the events and blobs, written to `<project>/site/<product>/`, never by
hand.

Invariants:

- A product's **fingerprint** is computed from the event log (the count and the last id of the event
  types it reads, plus its own version). A product is stale when its recorded fingerprint differs.
- `site/manifest.json` is a cache. It is not an event, no event reads it, and deleting it only
  forces a rebuild.
- One product failing to build never stops the others: the error is recorded in the manifest, the
  previous output is kept, and the hub shows the failure.
- The platform never calls a model. A product that needs a model's judgement is a recorded document
  (a later step); the hub renders what was recorded and never regenerates it.
- Building writes no event.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Final

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.site_charts import CHART_CSS, activity
from factory.services.site_chrome import BAR_CSS, hub_bar
from factory.services.site_panel import with_panel
from factory.services.site_theme import LIGHT_CSS, THEME_SCRIPT, THEME_TOGGLE

SITE_DIR: Final = "site"
MANIFEST: Final = "manifest.json"
ALL_EVENTS: Final = ("%",)
# the event types the explorer and the wiki read (rows of the miners, documents, citations)
EXPLORER_EVENTS: Final = (
    "extraction.%",
    "fulltext.%",
    "document.%",
    "reference.%",
    "citation.%",
    "protocol.%",
    "miner.%",
    "dedup.%",
)
# the event types the corpus and screening products read (a mining event never changes them)
CORPUS_EVENTS: Final = (
    "search.%",
    "query.%",
    "dedup.%",
    "screening.%",
    "fulltext.%",
    "document.%",
    "protocol.%",
    "decision.%",
    "check.%",
    "audit.%",
)

Build = Callable[[Project, Path], None]


@dataclass(frozen=True)
class Product:
    """One product of the site. `inputs` are SQL `LIKE` patterns over event types (`%` = every
    event); `build` writes the files into the directory it is given, including `entry`."""

    id: str
    title: str
    group: str
    description: str
    entry: str
    inputs: tuple[str, ...]
    build: Build
    version: int = 1
    needs_model: bool = False
    stamp: Callable[[Project], str] | None = None
    """Extra fingerprint text for a product that reads files rather than events (the catalog
    reads SKILL.md files and the decision log)."""


@dataclass(frozen=True)
class Planned:
    """A product that exists today only as a pilot script and is to be ported (shown on the hub as
    not yet integrated, so nothing is hidden)."""

    title: str
    group: str
    description: str
    script: str


class ProductStatus(StrictModel):
    id: str
    title: str
    group: str
    description: str
    entry: str
    built: bool
    built_at: str | None
    stale: bool
    error: str | None
    fingerprint: str
    needs_model: bool


class BuildResult(StrictModel):
    id: str
    built: bool
    skipped: bool
    error: str | None


# --- the registry ---


def _build_dashboard(project: Project, out: Path) -> None:
    from factory.services.dashboard_server import export_snapshot

    export_snapshot(project, out / "index.html")


def _build_feed(project: Project, out: Path) -> None:
    from factory.services.site_feed import build_feed_pointer

    build_feed_pointer(project, out)


def _build_queue(project: Project, out: Path) -> None:
    from factory.services.site_queue import build_queue

    build_queue(project, out)


def _build_prisma(project: Project, out: Path) -> None:
    from factory.services.site_prisma import build_prisma

    build_prisma(project, out)


def _build_bibliography(project: Project, out: Path) -> None:
    from factory.services.site_bibliography import build_bibliography

    build_bibliography(project, out)


def _build_citations(project: Project, out: Path) -> None:
    from factory.services.site_citations import build_citations

    build_citations(project, out)


def _build_explorer(project: Project, out: Path) -> None:
    from factory.services.site_explorer import build_explorer

    build_explorer(project, out)


def _build_wiki(project: Project, out: Path) -> None:
    from factory.services.pages import list_pages, read_page
    from factory.services.site_wiki import build_wiki

    extra: dict[str, str] = {}
    for info in list_pages(project):
        body = str(read_page(project, info.page_id)["body"])
        extra[f"synthesis/{info.scope.replace('=', '-')}.md"] = (
            f"> Model-written page ({info.model or info.actor_kind}, {info.recorded_at[:10]}), "
            "checked when recorded. An interpretation, not evidence.\n\n" + body + "\n"
        )
    build_wiki(project, out, extra)
    (out / "index.html").write_text(
        page(
            "Wiki",
            "<h1>Wiki (Obsidian vault)</h1><p class=dim>One note per work, one per category, a "
            "chronology and an index, linked with <code>[[wikilinks]]</code>.</p>"
            "<div class=panel><b>Open it in Obsidian:</b> Open folder as vault, then choose "
            f"<code>{html.escape(str(out.parent / 'wiki'))}</code>. Start at <code>index.md</code> "
            "and use the graph view (Ctrl+G). Every placement in a note shows the quote behind "
            "it.</div><p><a href='index.md'>index.md</a> · "
            "<a href='timeline.md'>timeline.md</a></p>",
        ),
        encoding="utf-8",
    )


def _build_results(project: Project, out: Path) -> None:
    from factory.services.site_results import build_results

    build_results(project, out)


def _build_miners(project: Project, out: Path) -> None:
    from factory.services.site_miners import build_miners

    build_miners(project, out)


def _build_agreement(project: Project, out: Path) -> None:
    from factory.services.site_agreement import build_agreement

    build_agreement(project, out)


def _build_taxonomy(project: Project, out: Path) -> None:
    from factory.services.site_taxonomy import build_taxonomy

    build_taxonomy(project, out)


def _build_lifecycle(project: Project, out: Path) -> None:
    from factory.services.site_lifecycle import build_lifecycle

    build_lifecycle(project, out)


def _build_steps(project: Project, out: Path) -> None:
    from factory.services.site_steps import build_steps

    build_steps(project, out)


def _build_layers(project: Project, out: Path) -> None:
    from factory.services.site_layers import build_layers

    build_layers(project, out)


def _build_synthesis(project: Project, out: Path) -> None:
    from factory.services.site_synthesis import build_synthesis

    build_synthesis(project, out)


def _build_conversion(project: Project, out: Path) -> None:
    from factory.services.site_quality import build_conversion

    build_conversion(project, out)


def _build_acquisition(project: Project, out: Path) -> None:
    from factory.services.site_quality import build_acquisition

    build_acquisition(project, out)


def _build_costs(project: Project, out: Path) -> None:
    from factory.services.site_costs import build_costs

    build_costs(project, out)


LAYOUT: Final[dict[str, tuple[str, ...]]] = {
    "Overview": ("dashboard", "prisma", "costs"),
    "Corpus": ("explorer", "bibliography", "citations", "layers", "wiki", "feed"),
    "Findings": ("results", "synthesis", "lifecycle", "steps", "taxonomy"),
    "Mining": ("miners", "agreement"),
    "Data quality": ("conversion", "acquisition", "queue"),
}
"""The project hub's sidebar: each group and its products, in order. (The factory-wide pages, the
backlog and the capabilities, are on the main hub, `site_chrome.HUB_NAV`.)"""
_ORDER: Final = {pid: n for n, pid in enumerate(i for ids in LAYOUT.values() for i in ids)}


def products() -> list[Product]:
    """The registered products, in the sidebar order of `LAYOUT`."""
    items = [
        Product(
            id="dashboard",
            title="Dashboard (snapshot)",
            group="Overview",
            description="Protocol, decisions, search, screening, extraction, miners, conversion "
            "and cost, as of the build. `factory dashboard serve` shows it live.",
            entry="index.html",
            inputs=ALL_EVENTS,
            build=_build_dashboard,
        ),
        Product(
            id="explorer",
            title="Explorer",
            group="Corpus",
            description="List, timeline, chronology, lineage and graph of the corpus; each paper "
            "with its structured summary, quoted evidence and a link to the original.",
            entry="index.html",
            inputs=EXPLORER_EVENTS,
            build=_build_explorer,
        ),
        Product(
            id="wiki",
            title="Wiki (Obsidian vault)",
            group="Corpus",
            description="One note per work and per category, a chronology, an index and the "
            "recorded synthesis pages, linked for Obsidian's graph view.",
            entry="index.html",
            inputs=(*EXPLORER_EVENTS, "page.%"),
            build=_build_wiki,
        ),
        Product(
            id="results",
            title="Results",
            group="Findings",
            description="What the miners found: distributions, stages covered, stage by technique, "
            "result rows, the review flow and agent events per model.",
            entry="index.html",
            inputs=(*EXPLORER_EVENTS, *CORPUS_EVENTS),
            build=_build_results,
        ),
        Product(
            id="miners",
            title="Miners",
            group="Mining",
            description="Each miner explained: what it records, how it reads, its fields and "
            "checks, agreement, example rows with quotes, versions and what you can do.",
            entry="index.html",
            inputs=EXPLORER_EVENTS,
            build=_build_miners,
        ),
        Product(
            id="agreement",
            title="Miner agreement",
            group="Mining",
            description="How closely pass A and the second pass agree, by miner and field: the "
            "platform's measure beside the fairer per-work measure.",
            entry="index.html",
            inputs=EXPLORER_EVENTS,
            build=_build_agreement,
        ),
        Product(
            id="taxonomy",
            title="Taxonomy",
            group="Findings",
            description="The project's taxonomy by dimension and how the classification miner "
            "placed the works.",
            entry="index.html",
            inputs=EXPLORER_EVENTS,
            build=_build_taxonomy,
            version=1,
        ),
        Product(
            id="lifecycle",
            title="Lifecycle",
            group="Findings",
            description="The stages of AI research systems as a clickable flow: which stages the "
            "works automate, which they cover together, and each paper's own stages in its own "
            "order; every stage and paper links to its quotes.",
            entry="index.html",
            inputs=(*EXPLORER_EVENTS, "work.layer_set"),
            build=_build_lifecycle,
        ),
        Product(
            id="steps",
            title="Steps",
            group="Findings",
            description="Exploratory: the steps an AI research system takes in each lifecycle stage, "
            "per paper in its own order, with actor, check and limits and the quote behind each; "
            "the miner is not calibrated, so the rows are for reading only.",
            entry="index.html",
            inputs=EXPLORER_EVENTS,
            build=_build_steps,
        ),
        Product(
            id="layers",
            title="Layers",
            group="Corpus",
            description="The layer of each work (core, benchmark, applied, adjacent, background, "
            "off-topic): who set it, the miner or a researcher's move, with counts per layer.",
            entry="index.html",
            inputs=(*EXPLORER_EVENTS, "work.layer_set"),
            build=_build_layers,
        ),
        Product(
            id="synthesis",
            title="Synthesis pages",
            group="Findings",
            description="Model-written pages about a technique, stage, field or the whole corpus, "
            "recorded and checked against the quoted rows.",
            entry="index.html",
            inputs=(*EXPLORER_EVENTS, "page.%"),
            build=_build_synthesis,
            needs_model=True,
        ),
        Product(
            id="conversion",
            title="Conversion coverage",
            group="Data quality",
            description="How much of each original's text survives conversion, lowest first. "
            "Click a document to see the original beside the extracted text, where text was "
            "lost, and how to convert it again.",
            entry="index.html",
            inputs=("document.%", "fulltext.%"),
            build=_build_conversion,
        ),
        Product(
            id="acquisition",
            title="Full-text acquisition",
            group="Data quality",
            description="Which promoted works have a full text, by route; the works without one, "
            "why, and the deviations that declare them not acquired.",
            entry="index.html",
            inputs=("fulltext.%", "document.%", "protocol.%", "screening.%"),
            build=_build_acquisition,
        ),
        Product(
            id="costs",
            title="Run costs",
            group="Overview",
            description="What each headless run cost, per stage, model and miner: runs, units, "
            "reported cost, cost per unit, median turns and duration, tokens per unit, and how "
            "much each turn re-reads the transcript. The cost is the API-equivalent price.",
            entry="index.html",
            inputs=("runner.%",),
            build=_build_costs,
        ),
        Product(
            id="prisma",
            title="PRISMA 2020 flow",
            group="Overview",
            description="The flow diagram, computed from the recorded screening and full-text "
            "decisions.",
            entry="index.html",
            inputs=CORPUS_EVENTS,
            build=_build_prisma,
        ),
        Product(
            id="bibliography",
            title="Bibliography",
            group="Corpus",
            description="The included works as a sortable list (title, year) and as BibTeX.",
            entry="index.html",
            inputs=CORPUS_EVENTS,
            build=_build_bibliography,
        ),
        Product(
            id="citations",
            title="Citations in the corpus",
            group="Corpus",
            description="Which works the corpus cites most, per year since publication, and "
            "the works it cites that it does not hold (snowball candidates).",
            entry="index.html",
            inputs=("reference.%", "dedup.%", "search.%"),
            build=_build_citations,
        ),
        Product(
            id="feed",
            title="Daily updates",
            group="Corpus",
            description="The daily updates moved to one page of the main hub, with a tab per "
            "project: a link to it.",
            entry="index.html",
            inputs=(),
            build=_build_feed,
        ),
        Product(
            id="queue",
            title="Work queue",
            group="Data quality",
            description="The papers added from the feed, each with the stage it stands at "
            "(lookup, screening, full text, conversion, extraction), and the open units of work "
            "per task kind.",
            entry="index.html",
            inputs=(
                "feed.%",
                "inbox.%",
                "screening.%",
                "fulltext.%",
                "document.%",
                "extraction.%",
                "task.%",
            ),
            build=_build_queue,
        ),
    ]
    return sorted(items, key=lambda p: _ORDER[p.id])


def planned() -> list[Planned]:
    """Products that exist only as pilot scripts so far; each becomes a registered product. None
    remain: the conversion inspector replaced the hand-built side-by-side samples."""
    return []


# --- fingerprints, manifest ---


def site_dir(project: Project) -> Path:
    return project.paths.dir / SITE_DIR


@lru_cache(maxsize=1)
def code_hash() -> str:
    """A hash of the code that builds products (the site modules and what they render), so a
    product is rebuilt after an upgrade and not only after new events."""
    here = Path(__file__).parent
    names = sorted([*here.glob("site*.py"), here / "miner_info.py", here / "pages.py"])
    digest = hashlib.sha256()
    for path in names:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def fingerprint(project: Project, product: Product) -> str:
    """The product's version, the build code and, per input pattern, the count and last id of
    matching events."""
    parts: list[str] = [f"{product.id}@{product.version}", f"code:{code_hash()}"]
    with project.index.connect() as conn:
        for pattern in product.inputs:
            row = conn.execute(
                text("SELECT COUNT(*), COALESCE(MAX(id), '') FROM events WHERE type LIKE :p"),
                {"p": pattern},
            ).one()
            parts.append(f"{pattern}:{row[0]}:{row[1]}")
    if product.stamp is not None:
        parts.append(f"files:{product.stamp(project)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _read_manifest(project: Project) -> dict[str, dict[str, str | None]]:
    path = site_dir(project) / MANIFEST
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def built_count(project: Project) -> int:
    """How many products the manifest records as built, read without any lock: it never waits
    for a rebuild (a half-written manifest reads as empty)."""
    return sum(
        1 for v in _read_manifest(project).values() if isinstance(v, dict) and v.get("built_at")
    )


def _write_manifest(project: Project, manifest: dict[str, dict[str, str | None]]) -> None:
    root = site_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")


def status(project: Project, registry: Sequence[Product] | None = None) -> list[ProductStatus]:
    """Every registered product with its build time, staleness and last error."""
    manifest = _read_manifest(project)
    out: list[ProductStatus] = []
    for product in registry if registry is not None else products():
        fp = fingerprint(project, product)
        entry = manifest.get(product.id, {})
        built = (
            bool(entry.get("built_at"))
            and (site_dir(project) / product.id / product.entry).exists()
        )
        out.append(
            ProductStatus(
                id=product.id,
                title=product.title,
                group=product.group,
                description=product.description,
                entry=product.entry,
                built=built,
                built_at=entry.get("built_at"),
                stale=not built or entry.get("fingerprint") != fp,
                error=entry.get("error"),
                fingerprint=fp,
                needs_model=product.needs_model,
            )
        )
    return out


# --- building ---


def build(
    project: Project,
    *,
    only: Sequence[str] = (),
    force: bool = False,
    registry: Sequence[Product] | None = None,
) -> list[BuildResult]:
    """Build every stale product (or the named ones; all of them with `force`), then the hub.

    A product is built in a scratch directory and swapped in only when it succeeded; a failure is
    recorded and the previous output stays."""
    reg = list(registry if registry is not None else products())
    unknown = sorted(set(only) - {p.id for p in reg})
    if unknown:
        raise ValueError(f"unknown product(s): {', '.join(unknown)}")
    manifest = _read_manifest(project)
    root = site_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    results: list[BuildResult] = []
    for product in reg:
        if only and product.id not in only:
            continue
        fp = fingerprint(project, product)
        entry = manifest.get(product.id, {})
        built = bool(entry.get("built_at")) and (root / product.id / product.entry).exists()
        if built and entry.get("fingerprint") == fp and not entry.get("error") and not force:
            results.append(BuildResult(id=product.id, built=False, skipped=True, error=None))
            continue
        scratch = root / f".build-{product.id}"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        try:
            product.build(project, scratch)
            if not (scratch / product.entry).exists():
                raise RuntimeError(f"the build did not write {product.entry}")
        except Exception as exc:  # a product failure is recorded, never raised across products
            shutil.rmtree(scratch, ignore_errors=True)
            manifest[product.id] = {**entry, "error": f"{type(exc).__name__}: {exc}"[:500]}
            results.append(
                BuildResult(
                    id=product.id, built=False, skipped=False, error=manifest[product.id]["error"]
                )
            )
            continue
        target = root / product.id
        shutil.rmtree(target, ignore_errors=True)
        scratch.rename(target)
        manifest[product.id] = {
            "built_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "fingerprint": fp,
            "error": None,
        }
        results.append(BuildResult(id=product.id, built=True, skipped=False, error=None))
    _write_manifest(project, manifest)
    render_hub(project, reg)
    return results


# --- the hub page ---

THEME_CSS: Final = (
    # the dashboard's palette (services/dashboard_page.py); the look is a control room: square
    # panels with title bars, corner brackets, status lights, mono for data and sans for prose
    ":root{color-scheme:dark;--bg:#0B0C16;--dk:#080910;--lt:#151828;--sel:#1f253a;--mut:#2d3450;"
    "--fg:#ddf7ff;--dim:#6a6e95;--light:#b5c5db;--ac:#82FB9C;--green:#4fe88f;--cyan:#7cf8f7;"
    "--blue:#829dd4;--amber:#e8b45a;--red:#ff8a80;--card:rgba(21,24,40,.85);"
    "--navbg:rgba(8,9,16,.92);--hov:rgba(31,37,58,.55);--chart:rgba(8,9,16,.55);--heat:#829dd4;"
    "--mono:ui-monospace,'JetBrains Mono','Fira Code',SFMono-Regular,Menlo,Consolas,monospace}"
    "*{box-sizing:border-box;border-radius:0!important}html,body{height:100%}"
    "body{margin:0;color:var(--fg);font:14px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',"
    "Inter,system-ui,sans-serif;background-color:var(--bg);"
    "background-image:linear-gradient(rgba(130,251,156,.035) 1px,transparent 1px),"
    "linear-gradient(90deg,rgba(130,251,156,.035) 1px,transparent 1px);background-size:28px 28px}"
    "a{color:var(--blue);text-decoration:none}a:hover{color:var(--ac)}"
    "code,pre,.mono,h1,h2,h3,h4,table,button,input,select,label.mono,nav,header{font-family:var(--mono)}"
    "code,pre{font-size:.88em}.dim{color:var(--dim)}"
    "h1{font-size:19px;margin:0 0 8px;letter-spacing:.08em;text-transform:uppercase;font-weight:700}"
    "h1::before{content:'// ';color:var(--ac)}"
    "button,.btn{background:transparent;color:var(--ac);border:1px solid color-mix(in srgb,var(--ac) 45%,transparent);"
    "font:600 11px var(--mono);letter-spacing:.1em;text-transform:uppercase;padding:4px 12px;"
    "cursor:pointer;display:inline-block}button:hover,.btn:hover{background:var(--ac);"
    "color:var(--bg)}"
    "input,select{background:var(--dk);color:var(--fg);border:1px solid var(--mut);padding:5px 10px;"
    "font-size:12.5px}input:focus,select:focus{outline:none;border-color:var(--ac)}"
    ".br{position:relative}.br::before,.br::after{content:'';position:absolute;width:10px;"
    "height:10px;border:2px solid var(--ac);pointer-events:none}"
    ".br::before{top:-1px;left:-1px;border-right:0;border-bottom:0}"
    ".br::after{bottom:-1px;right:-1px;border-left:0;border-top:0}"
    ".panel{position:relative;background:var(--card);border:1px solid var(--mut);padding:12px}"
    "pre.panel{white-space:pre-wrap;overflow:auto}"
    ".tg{display:inline-block;font:600 10.5px var(--mono);letter-spacing:.12em;"
    "text-transform:uppercase;padding:1px 7px;border:1px solid currentColor;color:var(--dim)}"
    ".tg.ok{color:var(--ac)}.tg.warn{color:var(--amber)}.tg.bad{color:var(--red)}"
    ".led{display:inline-block;width:8px;height:8px;flex:none;background:var(--ac);"
    "box-shadow:0 0 8px var(--ac)}.led.stale{background:var(--amber);box-shadow:0 0 8px var(--amber)}"
    ".led.bad{background:var(--red);box-shadow:0 0 8px var(--red)}"
    ".led.off{background:none;border:1px solid var(--dim);box-shadow:none}"
    "::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:var(--mut)}"
    "::-webkit-scrollbar-track{background:var(--dk)}"
)


def page(title: str, body: str, css: str = "") -> str:
    """A themed standalone page for a product that has no page of its own."""
    return with_panel(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"{THEME_SCRIPT}<title>{html.escape(title)}</title><style>{THEME_CSS}"
        f"body{{padding:20px 24px;max-width:1100px;margin:0 auto}}.theme-row{{display:flex;justify-content:flex-end;margin:0 0 6px}}"
        f"{css}{LIGHT_CSS}</style></head>"
        f"<body><div class=theme-row>{THEME_TOGGLE}</div>{body}</body></html>"
    )


_HUB_CSS: Final = (
    "body{display:flex;flex-direction:column;height:100vh;overflow:hidden;max-width:none;padding:0}"
    ".shell{display:flex;flex:1;min-height:0}"
    "nav input{width:calc(100% - 28px);margin:10px 14px 0;box-sizing:border-box}"
    "nav{width:268px;flex:none;overflow:auto;border-right:1px solid var(--mut);"
    "background:var(--navbg);padding:6px 0 24px}"
    "nav h3{margin:16px 14px 4px;font-size:10.5px;font-weight:600;letter-spacing:.16em;"
    "text-transform:uppercase;color:var(--dim)}"
    "nav a.i{display:flex;align-items:center;gap:10px;padding:6px 14px;color:var(--light);"
    "cursor:pointer;border-left:2px solid transparent;font-size:12.5px}"
    "nav a.i:hover{background:var(--lt);color:var(--fg)}"
    "nav a.i.on{background:var(--sel);color:var(--fg);border-left-color:var(--ac)}"
    "nav a.i.plan{color:var(--dim)}nav .no{color:var(--dim);font-size:10.5px;width:18px}"
    "nav .n{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
    "main{flex:1;min-width:0;position:relative}main iframe{width:100%;height:100%;border:0;"
    "background:var(--bg)}"
    "#home{height:100%;overflow:auto;padding:22px 30px 60px}#home .wrap{max-width:1040px;margin:0 auto}"
    ".sec{font:600 11px var(--mono);letter-spacing:.18em;text-transform:uppercase;"
    "color:var(--ac);margin:26px 0 10px;display:flex;align-items:center;gap:10px}"
    ".sec::after{content:'';flex:1;height:1px;background:var(--mut)}"
    ".line{display:flex;align-items:stretch;overflow-x:auto;padding:4px 2px 8px}"
    ".st{position:relative;flex:1;min-width:104px;margin-right:16px;padding:8px 10px;"
    "background:var(--card);border:1px solid var(--mut);cursor:pointer}"
    ".st:last-child{margin-right:0}.st:not(:last-child)::after{content:'\\25B8';position:absolute;"
    "right:-15px;top:50%;margin-top:-9px;color:var(--ac);font-size:13px}"
    ".st:hover{border-color:var(--ac)}.st .k{display:flex;gap:6px;align-items:center;"
    "font:600 10px var(--mono);letter-spacing:.14em;color:var(--dim);text-transform:uppercase}"
    ".st .k .led{margin-left:auto}.st .v{font:700 21px var(--mono);color:var(--ac);"
    "letter-spacing:.02em;line-height:1.25}.st .s{font:11px var(--mono);color:var(--dim)}"
    ".mods{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}"
    ".pn{position:relative;display:flex;flex-direction:column;background:var(--card);"
    "border:1px solid var(--mut);cursor:pointer}.pn:hover{border-color:var(--ac)}"
    ".pn .pt{display:flex;align-items:center;gap:9px;padding:5px 10px;background:var(--sel);"
    "border-bottom:1px solid var(--mut);font:600 11px var(--mono);letter-spacing:.12em;"
    "text-transform:uppercase;color:var(--fg)}.pn .pt .id{color:var(--ac)}.pn .pt .sp{flex:1}"
    ".pn .pb{padding:10px 12px;color:var(--light);font-size:13px;flex:1}"
    ".pn .pf{display:flex;justify-content:space-between;gap:8px;padding:6px 12px;"
    "border-top:1px solid var(--mut);font:11px var(--mono);color:var(--dim)}"
    ".pn .pf .go{color:var(--ac);letter-spacing:.1em}"
    ".pn.plan{opacity:.55;cursor:default}.pn.plan:hover{border-color:var(--mut)}"
    ".guide{position:relative;border:1px solid var(--mut);border-left:3px solid var(--ac);"
    "background:var(--card);padding:10px 14px;margin:6px 0;color:var(--light);"
    "font-size:13.5px;line-height:1.6}.guide b{color:var(--fg)}"
    ".hint{color:var(--dim);font:12px var(--mono);margin:8px 0 0}.hint code{background:var(--dk);"
    "padding:1px 6px;border:1px solid var(--mut);color:var(--ac)}"
    "@media (max-width:760px){nav{width:190px}.st{min-width:110px}}"
)

_HUB_JS: Final = """
const items=[...document.querySelectorAll('nav a.i')];const frame=document.getElementById('frame');
const home=document.getElementById('home');
function show(){const id=(location.hash||'#home').slice(1);
 items.forEach(a=>a.classList.toggle('on',a.dataset.id===id));
 const a=items.find(x=>x.dataset.id===id);
 if(!a||a.dataset.id==='home'||!a.dataset.src){home.style.display='block';frame.style.display='none';return;}
 home.style.display='none';frame.style.display='block';
 if(frame.getAttribute('src')!==a.dataset.src)frame.setAttribute('src',a.dataset.src);}
window.addEventListener('hashchange',show);show();
document.querySelectorAll('[data-go]').forEach(r=>r.onclick=()=>{location.hash=r.dataset.go;});
const WORD={ok:'Nominal',stale:'Stale',bad:'Fault'};
async function live(){if(!location.protocol.startsWith('http'))return;
 try{const r=await fetch('api/status',{cache:'no-store'});const s=await r.json();
  s.products.forEach(p=>{const st=p.error?'bad':(p.stale||!p.built)?'stale':'ok';
   const a=items.find(x=>x.dataset.id===p.id);
   if(a){a.querySelector('.led').className='led '+(st==='ok'?'':st);if(p.built)a.dataset.src=p.id+'/'+p.entry;}
   document.querySelectorAll('[data-led="'+p.id+'"]').forEach(l=>l.className='led '+(st==='ok'?'':st));
   const pn=document.querySelector('.pn[data-go="'+p.id+'"]');
   if(pn){const b=pn.querySelector('.tg');if(b){b.className='tg '+(st==='ok'?'ok':st==='stale'?'warn':'bad');b.textContent=WORD[st];}
    const m=pn.querySelector('.when');if(m)m.textContent=p.built_at?'built '+p.built_at:'not built yet';}});
  document.getElementById('live').textContent=s.building?'REBUILDING':'LIVE';}catch(e){}}
setInterval(live,10000);live();
document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
 items.forEach(a=>{a.style.display=!q||a.textContent.toLowerCase().includes(q)?'':'none';});});
"""


def _led(s: ProductStatus) -> str:
    return "bad" if s.error else "stale" if s.stale or not s.built else ""


def _word(s: ProductStatus) -> tuple[str, str]:
    if s.error:
        return "bad", "Fault"
    if s.stale or not s.built:
        return "warn", "Stale"
    return "ok", "Nominal"


STATIONS: Final = (
    ("SEARCH", "identified", "records found", "prisma"),
    ("SCREEN", "screened", "records screened", "prisma"),
    ("FULL TEXT", "assessed", "works assessed", "acquisition"),
    ("CONVERT", "converted", "documents", "conversion"),
    ("MINE", "miner_rows", "rows recorded", "miners"),
    ("SYNTHESIZE", "pages", "pages recorded", "synthesis"),
    ("REPORT", "products", "products built", "results"),
)


def _line_numbers(project: Project, built: int) -> dict[str, int]:
    """The counts shown on the production line: the review flow from the Results product's
    `line.json`, the rest from cheap queries."""
    out: dict[str, int] = {"products": built}
    with contextlib.suppress(OSError, ValueError):
        out.update(json.loads((site_dir(project) / "results" / "line.json").read_text("utf-8")))
    with project.index.connect() as conn:
        out["miner_rows"] = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM extraction_rows WHERE superseded_by IS NULL "
                    "AND pass_label = 'A' AND schema_ref LIKE 'm-%'"
                )
            ).scalar()
            or 0
        )
        out["pages"] = int(
            conn.execute(text("SELECT COUNT(*) FROM events WHERE type = 'page.recorded'")).scalar()
            or 0
        )
        out["events"] = int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar() or 0)
    return out


def _activity_days(project: Project, days: int = 21) -> list[tuple[str, int]]:
    """Events per calendar day, the last `days` days that have events, oldest first."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT substr(ts, 1, 10) AS d, COUNT(*) FROM events GROUP BY d "
                "ORDER BY d DESC LIMIT :n"
            ),
            {"n": days},
        ).all()
    return [(str(d), int(n)) for d, n in reversed(rows)]


def render_hub(
    project: Project,
    registry: Sequence[Product] | None = None,
    *,
    pending: Sequence[Planned] | None = None,
) -> Path:
    """Write `site/index.html`: a control room. A sidebar of every product with a status light;
    the home view shows the production line (stations with counts that open their product) and a
    panel per product with its state; the selected product opens inside the hub."""
    reg = list(registry if registry is not None else products())
    stat = status(project, reg)
    plans = list(pending if pending is not None else planned())
    by_id = {s.id: s for s in stat}
    num = _line_numbers(project, sum(1 for s in stat if s.built))
    groups: list[str] = []
    for item in [*(s.group for s in stat), *(p.group for p in plans)]:
        if item not in groups:
            groups.append(item)
    e = html.escape
    nav: list[str] = [
        "<a class='i on' data-id='home' href='#home'><span class=no>00</span>"
        "<span class='n'>Control room</span></a>"
    ]
    panels: list[str] = []
    idx = 0
    for group in groups:
        nav.append(f"<h3>{e(group)}</h3>")
        panels.append(f"<div class=sec>{e(group)}</div><div class=mods>")
        for s in (x for x in stat if x.group == group):
            idx += 1
            src = f"{s.id}/{s.entry}" if s.built else ""
            nav.append(
                f"<a class='i' data-id='{e(s.id)}' data-src='{e(src)}' href='#{e(s.id)}'>"
                f"<span class=no>{idx:02d}</span><span class='led {_led(s)}'></span>"
                f"<span class='n'>{e(s.title)}</span></a>"
            )
            cls, word = _word(s)
            model = " <span class=tg>model-written</span>" if s.needs_model else ""
            when = f"built {e(s.built_at)}" if s.built_at else "not built yet"
            err = (
                f"<div class=tg style='color:var(--red);margin-top:6px'>{e(s.error)}</div>"
                if s.error
                else ""
            )
            panels.append(
                f"<div class='pn br' data-go='{e(s.id)}'><div class=pt><span class=id>{idx:02d}</span>"
                f"<span>{e(s.title)}</span><span class=sp></span><span class='tg {cls}'>{word}</span></div>"
                f"<div class=pb>{e(s.description)}{err}</div>"
                f"<div class=pf><span><span class=when>{when}</span>{model}</span>"
                "<span class=go>OPEN &rarr;</span></div></div>"
            )
        for p in (x for x in plans if x.group == group):
            idx += 1
            nav.append(
                f"<a class='i plan' data-id='plan-{e(p.title)}' data-src='' href='#home'>"
                f"<span class=no>{idx:02d}</span><span class='led off'></span>"
                f"<span class='n'>{e(p.title)}</span></a>"
            )
            panels.append(
                f"<div class='pn plan'><div class=pt><span class=id>{idx:02d}</span><span>{e(p.title)}</span>"
                "<span class=sp></span><span class=tg>Offline</span></div>"
                f"<div class=pb>{e(p.description)}</div>"
                f"<div class=pf><span>pilot script</span><span class=mono>{e(p.script)}</span></div></div>"
            )
        panels.append("</div>")
    stations = ""
    for name, key, sub, pid in STATIONS:
        prod = by_id.get(pid)
        led = _led(prod) if prod else "off"
        v = num.get(key)
        stations += (
            f"<div class=st data-go='{e(pid)}'><div class=k><span>{e(name)}</span>"
            f"<span class='led {led}' data-led='{e(pid)}'></span></div>"
            f"<div class=v>{'' if v is None else f'{v:,}'}{'' if v is not None else '&ndash;'}</div>"
            f"<div class=s>{e(sub)}</div></div>"
        )
    slug = e(project.paths.slug)
    n_stale = sum(1 for s in stat if s.stale or s.error)
    ready = "SYSTEM NOMINAL" if not n_stale else f"{n_stale} MODULE(S) NEED A REBUILD"
    doc = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"{THEME_SCRIPT}<title>{slug}</title><style>{THEME_CSS}{_HUB_CSS}{CHART_CSS}{LIGHT_CSS}{BAR_CSS}</style></head><body>"
        + hub_bar(
            "projects",
            context=f"<span class=crumb>// {slug}</span>"
            f"<span class=ro>{ready} &middot; EVENTS <b>{num.get('events', 0):,}</b>"
            " &middot; <b id=live>SNAPSHOT</b></span>",
            main_hub_only=True,
        )
        + f"<div class=shell><nav><input id=q placeholder='filter modules'>{''.join(nav)}</nav><main>"
        "<iframe id=frame style='display:none' title='product'></iframe>"
        "<div id=home><div class=wrap><h1>Control room</h1>"
        "<div class=guide><b>Where to start.</b> <b>Explorer</b> to browse the papers and open "
        "any one with its quotes; <b>Results</b> for what the miners found; <b>Miners</b> and "
        "<b>Miner agreement</b> for how each reading was made and how stable it is; "
        "<b>Full-text acquisition</b> for what is missing and what to do about it; "
        "<b>Conversion coverage</b> to check the text extraction against the originals; "
        "<b>Synthesis pages</b> for model-written summaries checked against the quotes. Click "
        "any station or module: each explains what its numbers mean and what you can do.</div>"
        f"<div class=sec>Production line</div><div class=line>{stations}</div>"
        "<div class=sec>Activity: events recorded per day</div>"
        f"{activity(_activity_days(project))}"
        "<p class=hint>Each bar is one day of recorded events (screening verdicts, rows, labels, "
        "decisions). Hover a bar for the count.</p>"
        "<p class=hint>The line runs left to right: records found, screened, read in full, "
        "converted to text, mined for typed quoted values, synthesised, reported. A light turns "
        "amber when a module's inputs changed since it was built.</p>"
        + "".join(panels)
        + "<p class=hint>REBUILD <code>factory site build</code> &nbsp; SERVE LIVE "
        "<code>factory site serve</code> &nbsp; DASHBOARD <code>factory dashboard serve</code></p>"
        + f"</div></div></main></div><script>{_HUB_JS}</script></body></html>"
    )
    path = site_dir(project) / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path
