"""The `write` hub payload: synthesis pages, bibliography, PRISMA diagram and wiki vault pointer.

Invariants:
- `build` is pure over its `HubContext`, reads no network and calls no model; it only reads.
- Pages are shown as recorded (`pages.list_pages` / `read_page`); the body is cut into blocks on
  the server, so the page script never parses Markdown and every citation is resolved here.
- Every count (scope works, histogram, entries, coverage tallies) is computed here from the
  services' own rows; the page types none.
- BibTeX and the PRISMA SVG are strings built by `exports`; the browser saves them as files, so no
  route is needed. The wiki vault is too large for a payload: only its path and state are given.
- A section that fails to build is reported in `errors` and left empty; the others still render.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from factory.services.pages import PageInfo, list_pages, read_page, subset
from factory.services.site_bibliography import parse_entries
from factory.services.site_corpus import corpus_payload, slug_of
from factory.services.site_synthesis import scopes_of

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

_CITE = re.compile(r"\[\[works/([^\]|]+)(?:\|[^\]]*)?\]\]")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_BULLET = re.compile(r"^[-*]\s+")
KIND_ORDER = ("overview", "technique", "stage", "field")

METHODS: dict[str, str] = {
    "pages": (
        "Each page is shown as it was recorded, never regenerated. When it was recorded the "
        "platform checked it mechanically: cited works exist, quotations are verbatim in the "
        "quoted row, "
        "numbers come from the computed statistics. A flag is a sentence the check could not "
        "support. A page is stale when the rows of its scope changed after it was written."
    ),
    "scopes": (
        "The scopes are the whole corpus plus each technique, lifecycle stage and field of science "
        "that appears in the coded works. The number is how many papers the page would cover, "
        "counted from the same rows the page brief uses."
    ),
    "coverage": (
        "One cell per scope. Its state comes from the latest recorded page of that scope: checked "
        "(no flags, rows unchanged), flagged (the check left sentences unsupported), stale (rows "
        "changed since), or no page yet."
    ),
    "bibliography": (
        "The included works of the review, exported as BibTeX by the platform. Keys are stable "
        "names from the first author, year and title. The table is read from that same text, so "
        "both views hold the same entries."
    ),
    "prisma": (
        "The standard PRISMA 2020 flow diagram, drawn from the same recorded decisions as the "
        "Flow page. Every number is read from the flow and none is typed."
    ),
    "wiki": (
        "An Obsidian vault built from the coded corpus: one note per paper and per category, a "
        "timeline and an index, with the recorded synthesis pages marked as model-written. The "
        "vault is built on demand and is a projection, never edited by hand."
    ),
}


def markdown_blocks(body: str) -> list[dict[str, Any]]:
    """The page body as blocks: headings (level 1 to 3), paragraphs and bullet lists.

    A paragraph or heading carries `parts`: dicts `{"t": text}`, `{"b": bold text}` or
    `{"cite": slug}`; a list carries `items`, each a parts list. Nothing is rendered as HTML here.
    """

    def parts(text: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        pos = 0
        for m in _CITE.finditer(text):
            out.extend(_bold(text[pos : m.start()]))
            out.append({"cite": m.group(1)})
            pos = m.end()
        out.extend(_bold(text[pos:]))
        return out

    def _bold(text: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        pos = 0
        for m in _BOLD.finditer(text):
            if m.start() > pos:
                out.append({"t": text[pos : m.start()]})
            out.append({"b": m.group(1)})
            pos = m.end()
        if pos < len(text):
            out.append({"t": text[pos:]})
        return out

    blocks: list[dict[str, Any]] = []
    items: list[list[dict[str, str]]] = []

    def flush() -> None:
        if items:
            blocks.append({"k": "ul", "items": list(items)})
            items.clear()

    for line in body.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("#"):
            flush()
            level = min(len(s) - len(s.lstrip("#")), 3)
            blocks.append({"k": "h", "level": level, "parts": parts(s.lstrip("# "))})
        elif _BULLET.match(s):
            items.append(parts(_BULLET.sub("", s)))
        else:
            flush()
            blocks.append({"k": "p", "parts": parts(s)})
    flush()
    return blocks


def _cites_of(blocks: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for b in blocks:
        groups = b["items"] if b["k"] == "ul" else [b["parts"]]
        for g in groups:
            for p in g:
                if "cite" in p:
                    seen[p["cite"]] = None
    return list(seen)


def _state(info: PageInfo | None) -> str:
    if info is None:
        return "none"
    if info.stale:
        return "stale"
    return "flagged" if info.flags else "checked"


def _slug_ids(ctx: HubContext) -> dict[str, str]:
    """Slug of a work file name -> the id the shell (and its drawer) knows the work by."""
    out: dict[str, str] = {}
    source_of = ctx.source_of
    for wid in ctx.included:
        out[slug_of(source_of[wid])] = wid
    for wid in ctx.included:
        out[slug_of(wid)] = wid
    return out


def _pages_section(
    ctx: HubContext, infos: list[PageInfo], slug_ids: dict[str, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for info in infos:
        data = read_page(ctx.project, info.page_id)
        check = data["check"]
        blocks = markdown_blocks(str(data["body"]))
        out.append(
            {
                "page_id": info.page_id,
                "scope": info.scope,
                "title": info.title,
                "recorded_at": info.recorded_at,
                "who": info.model or info.actor_kind,
                "skill": info.skill,
                "words": info.words,
                "stale": info.stale,
                "state": _state(info),
                "supersedes": info.supersedes,
                "flags": [
                    {"sentence": f["sentence"], "detail": f["detail"], "kind": f["kind"]}
                    for f in check["flags"]
                ],
                "check": {
                    "cited_sentences": check["cited_sentences"],
                    "quotes_checked": check["quotes_checked"],
                    "numbers_checked": check["numbers_checked"],
                },
                "blocks": blocks,
                "cites": {s: slug_ids[s] for s in _cites_of(blocks) if s in slug_ids},
            }
        )
    return out


def _scopes_section(
    payload: dict[str, Any], infos: list[PageInfo]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The scope table rows and the coverage tallies by state."""
    have = {i.scope: i for i in infos}
    rows: list[dict[str, Any]] = []
    for scope in scopes_of(payload):
        try:
            n = len(subset(payload, scope)[0])
        except Exception:  # a scope with no works is left out, as in the classic table
            continue
        info = have.get(scope)
        kind, _, value = scope.partition("=")
        rows.append(
            {
                "scope": scope,
                "kind": kind if value else "overview",
                "value": value,
                "works": n,
                "page_id": info.page_id if info else None,
                "state": _state(info),
                "flags": info.flags if info else 0,
            }
        )
    tally = Counter(r["state"] for r in rows)
    coverage = {
        "tally": {s: tally.get(s, 0) for s in ("checked", "flagged", "stale", "none")},
        "total": len(rows),
        "kinds": [k for k in KIND_ORDER if any(r["kind"] == k for r in rows)],
    }
    return rows, coverage


def _bibliography_section(ctx: HubContext, slug_ids: dict[str, str]) -> dict[str, Any]:
    from factory.services.exports import export_bibliography

    bibtex = "".join(export_bibliography(ctx.project, "bibtex"))
    entries = parse_entries(bibtex)
    by_key = {slug.rsplit("-", 1)[0]: wid for slug, wid in slug_ids.items()}
    for e in entries:
        # a BibTeX key is a work's file-safe name without its hash suffix
        e["id"] = by_key.get(e["key"], "")
    years = Counter(e["year"] for e in entries if e["year"].isdigit())
    return {
        "entries": entries,
        "count": len(entries),
        "bibtex": bibtex,
        "filename": "references.bib",
        "years": [{"year": int(y), "n": years[y]} for y in sorted(years)],
        "undated": sum(1 for e in entries if not e["year"].isdigit()),
    }


def _prisma_section(ctx: HubContext) -> dict[str, Any]:
    from factory.exports.prisma_svg import prisma_svg

    file = prisma_svg(ctx.flow_data.prisma)
    # ``svg_file`` is the download (identical to the export); ``svg`` drops the XML
    # prolog, which is not valid inside an HTML element.
    inline = file.split("?>", 1)[1].lstrip() if file.lstrip().startswith("<?xml") else file
    return {"svg": inline, "svg_file": file, "filename": "prisma.svg"}


def _wiki_section(ctx: HubContext, works: int) -> dict[str, Any]:
    from factory.services.site import site_dir

    vault = site_dir(ctx.project) / "wiki"
    return {
        "path": str(vault),
        "built": (vault / "index.md").exists(),
        "works": works,
        "start": "index.md",
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The `write` payload: pages, scope coverage, bibliography, PRISMA SVG and the wiki pointer."""
    errors: dict[str, str] = {}
    out: dict[str, Any] = {
        "methods": dict(METHODS),
        "ready": True,
        "pages": [],
        "scopes": [],
        "coverage": {"tally": {}, "total": 0, "kinds": []},
        "bibliography": None,
        "prisma": None,
        "wiki": None,
    }
    slug_ids: dict[str, str] = {}
    try:
        slug_ids = _slug_ids(ctx)
    except Exception as exc:
        errors["links"] = str(exc)
    payload: dict[str, Any] = {"works": []}
    try:
        payload = corpus_payload(ctx.project)
        infos = list_pages(ctx.project)
        out["pages"] = _pages_section(ctx, infos, slug_ids)
        out["scopes"], out["coverage"] = _scopes_section(payload, infos)
    except Exception as exc:
        errors["pages"] = str(exc)
    sections: list[tuple[str, Callable[[], Any]]] = [
        ("bibliography", lambda: _bibliography_section(ctx, slug_ids)),
        ("prisma", lambda: _prisma_section(ctx)),
        ("wiki", lambda: _wiki_section(ctx, len(payload["works"]))),
    ]
    for key, fn in sections:
        try:
            out[key] = fn()
        except Exception as exc:
            errors[key] = str(exc)
    out["errors"] = errors
    return out
