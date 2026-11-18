# ruff: noqa: E501
"""The project site: every product of the factory in one hub (plan 2026-11-10-site-hub, step 1).

A **product** is anything the factory produces for a person to read: the dashboard, the PRISMA flow,
the bibliography, and later the explorer, the results, the wiki and the synthesis pages. Each is a
rebuildable projection of the events and blobs, written to `<project>/site/<product>/`, never by
hand.

Invariants:

- A product's **fingerprint** is computed from the event log (the count and the last id of the event
  types it reads), its own version and the hub code its build reaches
  (`product_code_hash`). A product is stale when its recorded fingerprint differs.
- `site/manifest.json` is a cache. It is not an event, no event reads it, and deleting it only
  forces a rebuild.
- One product failing to build never stops the others: the error is recorded in the manifest, the
  previous output is kept, and the hub shows the failure.
- The platform never calls a model. A product that needs a model's judgement is a recorded document
  (a later step); the hub renders what was recorded and never regenerates it.
- Building writes no event.
"""

from __future__ import annotations

import ast
import hashlib
import html
import inspect
import json
import re
import shutil
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Final

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.site_chrome import CONTAINER_WIDTH
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
ItemRender = Callable[[Project, str, Path], bool]
"""Writes one item file of a product (`rel`, e.g. `doc/<slug>.html`) under the given directory, at
the same relative path; False when `rel` names no item (IDEA-96, lazy item pages)."""
ITEMS_DIR: Final = ".items"
"""Under `site/`: the item pages a served hub rendered on request, by product and fingerprint."""


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
    index_build: Build | None = None
    """A build without the item pages (lazy build, IDEA-96): the served hub renders each item on
    its first request with `item`. A full build (`factory site build`) writes them all."""
    item: ItemRender | None = None
    item_dirs: tuple[str, ...] = ()
    """The folders of the product that hold its item pages (rendered on request when lazy)."""


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


def _build_flow(project: Project, out: Path) -> None:
    from factory.services.site_flow import build_flow

    build_flow(project, out)


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


def _build_conversion_index(project: Project, out: Path) -> None:
    from factory.services.site_inspector import build_conversion_index

    build_conversion_index(project, out)


def _conversion_item(project: Project, rel: str, out: Path) -> bool:
    from factory.services.site_inspector import render_conversion_item

    return render_conversion_item(project, rel, out)


def _build_conversion(project: Project, out: Path) -> None:
    from factory.services.site_quality import build_conversion

    build_conversion(project, out)


def _build_search(project: Project, out: Path) -> None:
    from factory.services.site_search import build_search

    build_search(project, out)


def _build_acquisition(project: Project, out: Path) -> None:
    from factory.services.site_quality import build_acquisition

    build_acquisition(project, out)


def _build_updates(project: Project, out: Path) -> None:
    from factory.services.site_updates import build_updates

    build_updates(project, out)


def _build_costs(project: Project, out: Path) -> None:
    from factory.services.site_costs import build_costs

    build_costs(project, out)


LAYOUT: Final[dict[str, tuple[str, ...]]] = {
    "Overview": ("dashboard", "prisma", "flow", "documents", "costs"),
    "Sources": ("search", "feed", "acquisition", "conversion", "queue"),
    "Corpus": ("explorer", "bibliography", "citations", "layers", "wiki", "updates"),
    "Mining": ("miners", "agreement", "steps", "lifecycle", "runs"),
    "Findings": ("results", "synthesis", "taxonomy"),
}
"""The project hub's sidebar, in the order the work happens: each group and its products. (The factory-wide pages, the
backlog and the capabilities, are on the main hub, `site_chrome.HUB_NAV`.)"""
_GROUP: Final = {pid: g for g, ids in LAYOUT.items() for pid in ids}
_ORDER: Final = {pid: n for n, pid in enumerate(i for ids in LAYOUT.values() for i in ids)}


def _build_documents(project: Project, out: Path) -> None:
    from factory.services.site_documents import build_documents

    build_documents(project, out)


def _documents_stamp(project: Project) -> str:
    from factory.services.site_documents import documents_stamp

    return documents_stamp(project)


def _build_runs(project: Project, out: Path) -> None:
    from factory.services.site_runs import build_runs

    build_runs(project, out)


def _runs_stamp(project: Project) -> str:
    from factory.services.site_runs import runs_stamp

    return runs_stamp(project)


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
            id="updates",
            title="Updates",
            group="Corpus",
            description="What entered the corpus since the frozen review (v1) and how far each work "
            "got, the growth per snapshot, and the weekly watch with its settings.",
            entry="index.html",
            inputs=ALL_EVENTS,
            build=_build_updates,
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
            index_build=_build_conversion_index,
            item=_conversion_item,
            item_dirs=("doc", "files"),
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
            id="search",
            title="Search and deduplication",
            group="Sources",
            description="Each registered query with its runs and the gap between reported and "
            "retrieved, the records that never became works, every merge with its rule and "
            "status, and the merges whose absorbed work was screened differently.",
            entry="index.html",
            inputs=(*CORPUS_EVENTS, "calibration.%"),
            build=_build_search,
        ),
        Product(
            id="flow",
            title="Flow explorer",
            group="Overview",
            description="The PRISMA flow by source, every identified record with the step it "
            "reached, a trail of what happened to each work, and the records that never became "
            "works.",
            entry="index.html",
            inputs=(*CORPUS_EVENTS, "extraction.%", "reference.%"),
            build=_build_flow,
        ),
        Product(
            id="documents",
            title="Study documents",
            group="Overview",
            description="The study's own files registered with their hash (plan, protocol "
            "documents, validation reports), by kind, with versions and whether each changed "
            "since registration.",
            entry="index.html",
            inputs=("file.%",),
            build=_build_documents,
            stamp=_documents_stamp,
        ),
        Product(
            id="runs",
            title="Runs",
            group="Mining",
            description="The agent-run files under ops/ (prompts, screener scripts, logs) by "
            "folder and batch prefix, with counts, dates and sizes, and whether a run or task id "
            "an event names appears in a file name; the others are flagged unlinked.",
            entry="index.html",
            inputs=("runner.%", "task.%"),
            build=_build_runs,
            stamp=_runs_stamp,
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
    return sorted((replace(p, group=_GROUP[p.id]) for p in items), key=lambda p: _ORDER[p.id])


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


_SERVICES: Final = "factory.services"


def _code_files() -> dict[str, Path]:
    """The hub code set, by module name: what `code_hash` covers."""
    here = Path(__file__).parent
    names = [*here.glob("site*.py"), here / "miner_info.py", here / "pages.py"]
    return {path.stem: path for path in names if path.is_file()}


def _imports(tree: ast.AST, *, top_only: bool) -> set[str]:
    """The `factory.services` module names a tree imports (only its top level with `top_only`)."""
    nodes = getattr(tree, "body", []) if top_only else ast.walk(tree)
    out: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == _SERVICES:
                out.update(alias.name for alias in node.names)
            elif node.module.startswith(_SERVICES + "."):
                out.add(node.module[len(_SERVICES) + 1 :].split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_SERVICES + "."):
                    out.add(alias.name[len(_SERVICES) + 1 :].split(".")[0])
    return out


_PRODUCT_CODE: dict[tuple[object, ...], str] = {}


def product_code_hash(product: Product) -> str:
    """A hash of the hub code one product's build reaches (IDEA-96): `site.py` with its top-level
    imports, and every hub module imported, directly or through another hub module, by the
    product's `build` and `stamp` functions or by the module that defines them. Code outside the
    hub code set is not followed, as in `code_hash`. When a function's source cannot be read the
    whole set is used. Cached while the files keep their size and modification time, so a server
    sees an edited page as stale at once (its builds run the code on disk, `child_builder`)."""
    files = _code_files()
    stamp = tuple(sorted((n, f.stat().st_mtime_ns, f.stat().st_size) for n, f in files.items()))
    key = (product.build, product.stamp, stamp)
    cached = _PRODUCT_CODE.get(key)
    if cached is not None:
        return cached
    seen: set[str] = {"site"}
    todo = set(_imports(ast.parse(files["site"].read_text(encoding="utf-8")), top_only=True))
    for fn in (product.build, product.stamp):
        if fn is None:
            continue
        try:
            todo |= _imports(ast.parse(textwrap.dedent(inspect.getsource(fn))), top_only=False)
        except (OSError, TypeError, SyntaxError):
            todo |= set(files)
        home = getattr(fn, "__module__", "") or ""
        if home.startswith(_SERVICES + "."):
            todo.add(home[len(_SERVICES) + 1 :])
    while todo:
        name = todo.pop()
        if name in seen or name not in files:
            continue
        seen.add(name)
        todo |= _imports(ast.parse(files[name].read_text(encoding="utf-8")), top_only=False)
    digest = hashlib.sha256()
    for name in sorted(seen):
        digest.update(files[name].name.encode())
        digest.update(files[name].read_bytes())
    _PRODUCT_CODE[key] = found = digest.hexdigest()[:12]
    return found


TypeCounts = dict[str, tuple[int, str]]
"""Per event type: how many events and the greatest id."""


def type_counts(project: Project) -> TypeCounts:
    """One grouped read of the event log, shared by the fingerprints of one status pass."""
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT type, COUNT(*), MAX(id) FROM events GROUP BY type"))
        return {str(r[0]): (int(r[1]), str(r[2] or "")) for r in rows}


@lru_cache(maxsize=256)
def _like(pattern: str) -> re.Pattern[str]:
    """SQLite `LIKE` (no ESCAPE) as a regular expression: `%` any run, `_` one character, ASCII
    case-insensitive."""
    body = "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern)
    return re.compile(body, re.IGNORECASE | re.DOTALL)


def _match(counts: TypeCounts, pattern: str) -> tuple[int, str]:
    """`COUNT(*), COALESCE(MAX(id), '')` over the events whose type is `LIKE pattern`."""
    rx = _like(pattern)
    hits = [v for t, v in counts.items() if rx.fullmatch(t)]
    return sum(n for n, _ in hits), max((m for _, m in hits), default="")


def fingerprint(project: Project, product: Product, counts: TypeCounts | None = None) -> str:
    """The product's version, the code its build reaches (`product_code_hash`) and, per input
    pattern, the count and last id of matching events (from `counts` when given, read once per
    status pass; the same values as one `LIKE` query per pattern)."""
    parts: list[str] = [f"{product.id}@{product.version}", f"code:{product_code_hash(product)}"]
    seen = counts if counts is not None else type_counts(project)
    for pattern in product.inputs:
        n, last = _match(seen, pattern)
        parts.append(f"{pattern}:{n}:{last}")
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


def recorded_fingerprint(project: Project, pid: str) -> str | None:
    """The fingerprint the manifest records for product `pid`'s current build, or None."""
    entry = _read_manifest(project).get(pid)
    value = entry.get("fingerprint") if isinstance(entry, dict) else None
    return value if isinstance(value, str) else None


def built_count(project: Project) -> int:
    """How many products the manifest records as built, read without any lock: it never waits
    for a rebuild (a half-written manifest reads as empty)."""
    return sum(
        1 for v in _read_manifest(project).values() if isinstance(v, dict) and v.get("built_at")
    )


def _write_manifest(project: Project, manifest: dict[str, dict[str, str | None]]) -> None:
    root = site_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    # written aside and swapped in, so a reader never sees half a manifest (IDEA-96: the server
    # reads statuses while a product builds)
    tmp = root / f".{MANIFEST}.tmp"
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(root / MANIFEST)


def status(project: Project, registry: Sequence[Product] | None = None) -> list[ProductStatus]:
    """Every registered product with its build time, staleness and last error."""
    manifest = _read_manifest(project)
    counts = type_counts(project)
    out: list[ProductStatus] = []
    for product in registry if registry is not None else products():
        fp = fingerprint(project, product, counts)
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
    lazy: bool = False,
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
        partial = bool(entry.get("lazy")) and not lazy  # a full build must write the items
        if (
            built
            and entry.get("fingerprint") == fp
            and not entry.get("error")
            and not force
            and not partial
        ):
            results.append(BuildResult(id=product.id, built=False, skipped=True, error=None))
            continue
        scratch = root / f".build-{product.id}"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        try:
            # one memo scope per product (`call_memo`): the derivations its parts share (corpus,
            # outcomes, miner populations) are computed once. Events added meanwhile are not seen;
            # the fingerprint was taken before, so the product reads stale and is built again.
            as_lazy = lazy and product.index_build is not None
            with entering():
                (product.index_build if as_lazy and product.index_build else product.build)(
                    project, scratch
                )
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
        shutil.rmtree(root / ITEMS_DIR / product.id, ignore_errors=True)
        manifest[product.id] = {
            "built_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "fingerprint": fp,
            "error": None,
            "lazy": "1" if as_lazy else None,
        }
        results.append(BuildResult(id=product.id, built=True, skipped=False, error=None))
    # merge only the entries this build wrote into the manifest as it is now: another process (the
    # server's child build, a manual `site build`) may have recorded other products meanwhile
    touched = {r.id for r in results if not r.skipped}
    latest = _read_manifest(project)
    latest.update({pid: manifest[pid] for pid in touched if pid in manifest})
    _write_manifest(project, latest)
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


def page(title: str, body: str, css: str = "", *, head: str = "", body_class: str = "") -> str:
    """A themed standalone page for a product that has no page of its own."""
    return with_panel(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"{head}{THEME_SCRIPT}<title>{html.escape(title)}</title><style>{THEME_CSS}"
        f"body{{padding:20px 24px;max-width:{CONTAINER_WIDTH};margin:0 auto}}.theme-row{{display:flex;justify-content:flex-end;margin:0 0 6px}}"
        f"{css}{LIGHT_CSS}</style></head>"
        f"<body{f' class={body_class}' if body_class else ''}><div class=theme-row>{THEME_TOGGLE}</div>{body}</body></html>"
    )


def render_hub(
    project: Project,
    registry: Sequence[Product] | None = None,
    *,
    pending: Sequence[Planned] | None = None,
) -> Path:
    """Write `site/index.html` (the hub page; see `site_hub_page`)."""
    from factory.services.site_hub_page import render_hub as render

    return render(project, registry, pending=pending)
