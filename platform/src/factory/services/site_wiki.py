"""The wiki product: an Obsidian vault of the corpus (plan site-hub, step 2).

One note per work (frontmatter, abstract, placement links, the structured summary, the
classification with its quotes, lifecycle stages, citations inside the corpus), one note per
category listing its works, a chronological `timeline.md` and an `index.md`. Open the folder as a
vault, then use the graph view. Built from `site_corpus.corpus_payload`; a projection, never edited
by hand. Model-written pages (synthesis) are added from recorded documents in a later step.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from factory.services.context import Project
from factory.services.site_corpus import SUMMARY_ORDER, corpus_payload
from factory.services.site_explorer import link_documents

CATEGORY_DIMS = ("technique", "field", "data", "architecture", "evaluation", "human", "stage")


def _name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._-]+", "-", value)[:80]


def _val(w: dict[str, Any], role: str, field: str) -> str:
    return str((w[role].get(field) or {}).get("v", ""))


def _quote(o: dict[str, str], n: int) -> str:
    return f' — "{o["q"][:n]}" ({o["a"]})' if o["q"] and o["q"] != o["v"] else ""


def build_wiki(project: Project, out: Path, extra_pages: dict[str, str] | None = None) -> None:
    """Write the vault into `out`. `extra_pages` maps a `folder/name.md` path to its text."""
    payload = corpus_payload(project)
    works: list[dict[str, Any]] = payload["works"]
    link_documents(payload, out)
    for sub in ("works", *CATEGORY_DIMS):
        (out / sub).mkdir(parents=True, exist_ok=True)
    cites: list[list[str]] = payload["cites"]
    cat: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for w in works:
        links: list[str] = []

        def add(dim: str, value: str, w: dict[str, Any] = w, links: list[str] = links) -> None:
            if value:
                cat[(dim, value)].append(w)
                links.append(f"[[{dim}/{_name(value)}]]")

        add("technique", _val(w, "cls", "technique_primary"))
        add("technique", _val(w, "cls", "technique_secondary"))
        add("field", _val(w, "cls", "field_primary"))
        add("data", _val(w, "cls", "data_primary"))
        add("architecture", _val(w, "cls", "architecture_primary"))
        add("evaluation", _val(w, "cls", "evaluation_primary"))
        add("human", _val(w, "map", "human_position"))
        for s in w["stages"]:
            add("stage", s["stage"])
        title = w["title"].replace('"', "'")
        front = [
            "---",
            f'title: "{title}"',
            f"published: {w['published']}",
            f'venue: "{w["venue"]}"',
            f"doi: {w['doi'] or ''}",
            f"arxiv: {w['arxiv'] or ''}",
            f"technique: {_val(w, 'cls', 'technique_primary')}",
            f"field: {_val(w, 'cls', 'field_primary')}",
            f"human_position: {_val(w, 'map', 'human_position')}",
            "stages: [" + ", ".join(sorted({s["stage"] for s in w["stages"]})) + "]",
            f"work_id: {w['id']}",
            "---",
        ]
        body = [
            f"# {w['title']}",
            "",
            f"{', '.join(a for a in w['authors'] if a)} · {w['published']}",
        ]
        if w["venue"]:
            body[-1] += f" · {w['venue']}"
        if w["doc"]:
            body += ["", f"Original: [{w['doc']['kind'].upper()}](../{w['doc']['path']})"]
        if w["sum"]:
            body += ["", "## Structured summary (sentences quoted from the paper)"]
            for key, label in SUMMARY_ORDER:
                o = w["sum"].get(key)
                if o:
                    body.append(f"- **{label}**: {o['v']}" + (_quote(o, 260) or f" ({o['a']})"))
        body += ["", "## Abstract", w["abstract"] or "(none)", "", "## Placed in"]
        body.append(" · ".join(links) or "(no classification)")
        body += ["", "## Classification (evidence quoted from the paper)"]
        for key, o in [*w["cls"].items(), *w["map"].items()]:
            body.append(f"- **{key}**: {o['v']}{_quote(o, 240)}")
        if w["stages"]:
            body += ["", "## Lifecycle stages"]
            for s in w["stages"]:
                ref = f"[[stage/{_name(s['stage'])}]] ({s['mode']})"
                body.append(f'- {ref} — "{s["quote"][:240]}" ({s["anchor"]})')
        out_ = [b for a, b in cites if a == w["slug"]]
        in_ = [a for a, b in cites if b == w["slug"]]
        if out_ or in_:
            body += ["", "## Citations within the corpus"]
            body += [f"- cites [[works/{x}]]" for x in out_]
            body += [f"- cited by [[works/{x}]]" for x in in_]
        (out / "works" / f"{w['slug']}.md").write_text(
            "\n".join([*front, "", *body]) + "\n", "utf-8"
        )
    for (dim, value), members in cat.items():
        lines = [
            f"# {dim}: {value}",
            "",
            f"{len(members)} works (pass A; each note shows the quote behind its placement).",
            "",
        ]
        lines += [
            f"- [[works/{m['slug']}|{m['title'][:110]}]] ({m['published'][:7]})"
            for m in sorted(members, key=lambda x: x["published"])
        ]
        (out / dim / f"{_name(value)}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    timeline = ["# Chronology", "", "All works by month of publication, newest first.", ""]
    for month in sorted({w["month"] for w in works if w["month"]}, reverse=True):
        timeline.append(f"## {month}")
        for w in sorted(
            (x for x in works if x["month"] == month), key=lambda x: x["published"], reverse=True
        ):
            tech, hum = _val(w, "cls", "technique_primary"), _val(w, "map", "human_position")
            timeline.append(
                f"- {w['published']} [[works/{w['slug']}|{w['title'][:120]}]] — {tech}, {hum}"
            )
        timeline.append("")
    (out / "timeline.md").write_text("\n".join(timeline) + "\n", encoding="utf-8")
    pages = extra_pages or {}
    for rel, content in pages.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    index = [
        "# Map of the corpus",
        "",
        f"{len(works)} works. Open the graph view (Ctrl+G) to see works linked to techniques, "
        "fields, stages and human positions.",
        "",
        "See [[timeline]] for the chronological list.",
        "",
    ]
    synth = sorted(p[:-3] for p in pages if p.endswith(".md") and p.startswith("synthesis/"))
    if synth:
        index += ["## synthesis (model-written, quote-checked)", *[f"- [[{p}]]" for p in synth], ""]
    for dim in CATEGORY_DIMS:
        index.append(f"## {dim}")
        for (d2, value), members in sorted(cat.items(), key=lambda x: -len(x[1])):
            if d2 == dim:
                index.append(f"- [[{dim}/{_name(value)}]] ({len(members)})")
        index.append("")
    (out / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
