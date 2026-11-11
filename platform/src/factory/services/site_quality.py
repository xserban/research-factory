# ruff: noqa: E501
"""The quality products: conversion coverage and full-text acquisition (plan site-hub, step 5).

- **Conversion coverage**: how much of each original document's text is found in its converted
  Markdown, and the reverse, by word 5-grams (`conversion_coverage`). A mechanical triage that
  ranks documents for a person to look at; it decides nothing.
- **Acquisition**: which promoted works have a full text, by route, which do not and why, and
  which of those a recorded protocol deviation declares not acquired.

Both are computed from the recorded events and the stored documents.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from factory.services.context import Project
from factory.services.fulltext_status import fulltext_status
from factory.services.protocol import list_deviations
from factory.services.site_corpus import slug_of
from factory.services.site_widgets import REPORT_CSS, bars, esc, note, section, table


def _works_info(project: Project, ids: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with project.index.connect() as conn:
        for wid in ids:
            row = conn.execute(
                text("SELECT data FROM works WHERE work_id = :w"), {"w": wid}
            ).first()
            if row is None:
                continue
            d = json.loads(row[0])
            out[wid] = {
                "title": str(d.get("title") or wid),
                "doi": str((d.get("identifiers") or {}).get("doi") or ""),
                "openalex": str((d.get("identifiers") or {}).get("openalex") or ""),
                "published": str((d.get("dates") or {}).get("published") or ""),
                "venue": str((d.get("venue") or {}).get("name") or ""),
                "authors": ", ".join(
                    str(a.get("name")) for a in (d.get("authors") or [])[:4] if a.get("name")
                ),
            }
    return out


def build_conversion(project: Project, out: Path) -> None:
    """The conversion product: the coverage list and one inspector page per document."""
    from factory.services.site_inspector import build_conversion_site

    build_conversion_site(project, out)


REASONS = {
    "no-arxiv-id": "the record has no arXiv id, so the arXiv routes could not run",
    "no-arxiv-html": "arXiv has no HTML rendering of this paper",
    "no-html-rendering": "arXiv has no HTML rendering of this paper",
    "no-latex-source": "arXiv offers no LaTeX source for this paper",
    "no-oa-pdf": "OpenAlex lists no open-access PDF for this work",
    "no-identifier": "the record has no DOI or other identifier to look up",
    "http-403": "the publisher refused the download (a paywall or a bot block)",
    "http-404": "the listed address no longer has the file",
    "not-a-pdf": "the address returned something that is not a PDF",
}
ROUTE_HELP = {
    "arxiv-html": "arXiv's HTML rendering of the paper",
    "arxiv-source": "arXiv's LaTeX source of the paper",
    "oa-pdf": "an open-access PDF listed by OpenAlex",
    "researcher-supplied": "a file the researcher supplies",
}
_ACQ_CSS = (
    REPORT_CSS
    + "tr.clk{cursor:pointer}tr.clk:hover{background:var(--sel)}.cmd{display:flex;gap:8px;"
    "align-items:center;margin:4px 0}.cmd code{background:var(--lt);border:1px solid var(--mut);"
    "border-radius:6px;padding:3px 8px;font-size:12px;flex:1;overflow-x:auto;white-space:nowrap}"
    ".cmd button{background:var(--lt);color:var(--fg);border:1px solid var(--mut);"
    "border-radius:6px;padding:2px 10px;cursor:pointer}pre.t{background:var(--lt);"
    "border:1px solid var(--mut);border-radius:8px;padding:10px;font-size:12px;overflow:auto}"
    ".pill{border:1px solid var(--mut);border-radius:10px;padding:0 8px;font-size:12px}"
    ".bad{color:var(--amber)}.ok{color:var(--ac)}"
)


def _cmd(c: str) -> str:
    return (
        f'<div class=cmd><code>{esc(c)}</code><button onclick="navigator.clipboard.writeText('
        f'this.dataset.c)" data-c="{esc(c)}">Copy</button></div>'
    )


def _work_page(project: Project, w: Any, meta: dict[str, str], declared: str | None) -> str:
    from urllib.parse import quote

    from factory.services.site import page

    slug = project.paths.slug
    title = meta.get("title", w.work_id)
    doi = meta.get("doi", "")
    attempts = "".join(
        f"<tr><td>{esc(route)}</td><td>{esc(ROUTE_HELP.get(str(route), ''))}</td><td>{esc(why)}</td>"
        f"<td>{esc(REASONS.get(str(why).split(' ')[0], ''))}</td></tr>"
        for route, why in sorted(w.reasons.items())
    )
    q = quote(title)
    where = [
        (f"https://doi.org/{doi}", "The publisher's page (DOI)") if doi else None,
        (f"https://openalex.org/{meta['openalex']}", "The OpenAlex record")
        if meta.get("openalex")
        else None,
        (f"https://scholar.google.com/scholar?q={q}", "Search the title on Google Scholar"),
        (f"https://arxiv.org/search/?query={q}&searchtype=title", "Search the title on arXiv"),
        (f"https://www.semanticscholar.org/search?q={q}", "Search the title on Semantic Scholar"),
    ]
    links = "".join(
        f"<li><a href='{esc(u)}' target=_blank>{esc(label)}</a></li>"
        for u, label in filter(None, where)
    )
    fname = (doi.replace("/", "_") + ".pdf") if doi else "<DOI with / replaced by _>.pdf"
    dev = (
        '{\n  "description": "'
        + esc(f"{title[:60].strip()} has no retrievable full text and is not acquired.")
        + '",\n  "reason": "No automatic route found a copy and none was supplied.",\n  "affects": ["'
        + esc(w.work_id)
        + '"]\n}'
    )
    state = (
        f"<span class='pill ok'>declared by {esc(declared)}</span>"
        if declared
        else "<span class='pill bad'>not declared by any deviation</span>"
    )
    body = (
        "<p class=dim><a href='../index.html'>← full-text acquisition</a></p>"
        f"<h1>{esc(title)}</h1><p class=dim>{esc(meta.get('authors', ''))} · {esc(meta.get('published', '')[:10])} · {esc(meta.get('venue', ''))}</p><p>{state}</p>"
        + note(
            "This work was promoted to full-text screening but no full text could be obtained. "
            "Below: what each automatic route tried, where you can look for a copy yourself, and "
            "what to do next."
        )
        + section(
            "What the automatic routes tried",
            "<table><tr><th>route</th><th>what it is</th><th>result</th><th>meaning</th></tr>"
            + attempts
            + "</table>",
        )
        + section("Look for a copy yourself", f"<ul>{links}</ul>")
        + section(
            "What you can do",
            "<ol><li><b>Retry the automatic routes</b> (if something changed, for example a new arXiv version):</li></ol>"
            + _cmd(f"factory --project {slug} fulltext fetch --work {w.work_id}")
            + "<ol start=2><li><b>Import a copy you found</b>: save the PDF in a folder under the name below, then import the folder (the platform matches it by the identifier in the name and checks the first page):</li></ol>"
            + _cmd(f"{fname}")
            + _cmd(f"factory --project {slug} fulltext import FOLDER")
            + (
                f"<ol start=3><li><b>Already declared not acquired</b> by {esc(declared)}; nothing more to record unless you find a copy (step 2).</li></ol>"
                if declared
                else "<ol start=3><li><b>Declare it not acquired</b> (your rule: no copy, so ignore it): record a deviation from a file with this content:</li></ol>"
                + f"<pre class=t>{dev}</pre>"
                + _cmd(f"factory --project {slug} protocol deviation --file deviation.json")
            ),
        )
    )
    return page(title[:80], body, _ACQ_CSS)


def build_acquisition(project: Project, out: Path) -> None:
    from factory.services.site import page

    status = fulltext_status(project)
    works = [w for w in status.works if w.state == "not-retrieved"]
    declared: dict[str, str] = {}
    deviations = list_deviations(project)
    for dev in deviations:
        for wid in dev.affects:
            declared.setdefault(wid, dev.deviation_id)
    info = _works_info(project, [w.work_id for w in works])
    (out / "work").mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    undeclared: list[str] = []
    for w in sorted(
        works, key=lambda x: (x.work_id in declared, info.get(x.work_id, {}).get("title", ""))
    ):
        meta = info.get(w.work_id, {})
        d = declared.get(w.work_id)
        if not d:
            undeclared.append(w.work_id)
        s = slug_of(w.work_id)
        (out / "work" / f"{s}.html").write_text(_work_page(project, w, meta, d), encoding="utf-8")
        why = "; ".join(f"{k}: {v}" for k, v in sorted(w.reasons.items()))
        rows.append(
            f"<tr class=clk onclick=\"location.href='work/{s}.html'\"><td><a href='work/{s}.html'>{esc(meta.get('title', w.work_id)[:100])}</a></td>"
            f"<td>{esc(meta.get('doi', ''))}</td><td>{esc(meta.get('published', '')[:10])}</td><td>{esc(why[:110])}</td>"
            f"<td>{esc(d) if d else '<span class=bad>not declared</span>'}</td></tr>"
        )
    head = table(
        ["promoted to full text", "unsought (later tranche)", "retrieved", "not retrieved"],
        [[status.promoted, status.unsought, status.retrieved, status.not_retrieved]],
    )
    routes = bars(collections.Counter({k: v for k, v in status.by_route.items() if v}))
    devs = table(
        ["deviation", "works", "description"],
        [[d.deviation_id, len(d.affects), d.description[:200]] for d in deviations],
    )
    slug = project.paths.slug
    batch = ""
    if undeclared:
        ids = json.dumps(undeclared)
        batch = section(
            f"Declare the {len(undeclared)} undeclared works at once",
            "<p class=dim>Save this as deviation.json and record it, or open a work above to declare it alone.</p>"
            f"<pre class=t>{esc(json.dumps({'description': 'Promoted works with no retrievable full text are not acquired.', 'reason': 'No automatic route found a copy and none was supplied.', 'affects': undeclared}, indent=2))}</pre>"
            + _cmd(f"factory --project {slug} protocol deviation --file deviation.json"),
        )
        del ids
    body = (
        "<h1>Full-text acquisition</h1>"
        + note(
            "After title/abstract screening, the works promoted to full text are fetched by "
            "several routes (arXiv HTML, arXiv source, open-access PDF, files you supply). This "
            "page shows how many were retrieved, by which route, and the works that could not be "
            "retrieved: each is excluded from full-text screening and extraction, and a protocol "
            "deviation records the decision. "
            + (
                f"{len(undeclared)} not-retrieved work(s) are not declared by any deviation yet."
                if undeclared
                else "Every not-retrieved work is declared by a deviation."
            )
            + " Click a work for what was tried and what to do."
        )
        + section(
            "How to read the counts",
            table(
                ["column", "meaning"],
                [
                    ["promoted to full text", "works that passed title/abstract screening"],
                    [
                        "unsought (later tranche)",
                        "promoted works not yet fetched (out of the current scope)",
                    ],
                    ["retrieved", "works with a stored document"],
                    ["not retrieved", "works that were tried and have no document"],
                ],
            ),
        )
        + head
        + section("Retrieved, by route", routes)
        + section(
            f"Not retrieved ({len(works)})",
            "<table><tr><th>title</th><th>DOI</th><th>published</th><th>reasons</th><th>declared by</th></tr>"
            + "".join(rows)
            + "</table>",
        )
        + batch
        + section(
            "Protocol deviations",
            note(
                "A deviation is a recorded departure from the protocol, with the reason and the works it affects."
            )
            + devs,
        )
    )
    (out / "index.html").write_text(page("Full-text acquisition", body, _ACQ_CSS), encoding="utf-8")
