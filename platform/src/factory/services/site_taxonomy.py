"""The taxonomy product: the project's taxonomy and how the works fell into it (plan site-hub,
step 3).

The taxonomy is project data, read from `<project>/taxonomy.json` (dimensions, each with named
categories and the keyword pattern that proposed them; IDEA-50 will make it a versioned object).
Keyword patterns only propose and count: the classification miner assigns every work to a category
with a quote. For each dimension that the explorer profile also uses as a filter, the page shows how
many works the miner placed in each category.
"""

from __future__ import annotations

import collections
import json
from functools import partial
from pathlib import Path
from typing import Any

from factory.services.context import Project
from factory.services.site_corpus import corpus_payload, load_profile
from factory.services.site_results import explorer_link
from factory.services.site_widgets import REPORT_CSS, bars, esc, note, section, table

TAXONOMY_FILE = "taxonomy.json"


def _link(role: str, field: str, value: str) -> str | None:
    return explorer_link(role, field, value)


def build_taxonomy(project: Project, out: Path) -> None:
    from factory.services.site import page

    path = project.paths.dir / TAXONOMY_FILE
    try:
        tax: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tax = {}
    payload = corpus_payload(project)
    works: list[dict[str, Any]] = payload["works"]
    dims = {d[0]: d for d in load_profile(project).dims}
    from factory.services.site_taxonomy_registered import render_index, write_registered

    write_registered(project, out, page)
    body = "<h1>Taxonomy</h1>" + render_index(project)
    body += f"<h2>Earlier unregistered list: {esc(tax.get('taxonomy', ''))}</h2>"
    body += note(
        "The list below is the earlier, unregistered taxonomy file, kept as it was. "
        "A taxonomy is the project's own list of categories for describing the systems, by "
        "dimension (technique, field, data, architecture, autonomy, human role, evaluation, "
        "stages). The researcher accepted this one; keyword patterns only proposed and counted "
        "the categories. The classification miner then placed every paper in a category with a "
        "quote."
    )
    if not tax:
        body += note(f"No taxonomy recorded for this project (expected `{TAXONOMY_FILE}`).")
    else:
        body += note(
            f"Status: {tax.get('status', '')}. {tax.get('source', '')} Keyword patterns propose "
            "categories and count matches; the classification miner assigns every work to a "
            "category with a quoted sentence."
        )
    for dim in tax.get("dimensions", []):
        key = dim["dimension"]
        rows = [[c["name"], c.get("pattern") or "(matches none)"] for c in dim["categories"]]
        block = table(["category", "keyword pattern"], rows)
        if key in dims:
            _, _, role, fname = dims[key]
            counter: collections.Counter[str] = collections.Counter(
                w[role][fname]["v"] for w in works if fname in w[role]
            )
            if counter:
                block += (
                    f"<h3>Works placed by the classification miner ({fname})</h3>"
                    "<p class=dim>Click a category to open its works in the explorer, each with "
                    "the quote behind the placement.</p>"
                    + bars(counter, link=partial(_link, role, fname))
                )
        body += section(dim.get("title", key), block)
    body += section(
        "What you can do",
        "<p class=dim>Read a dimension's categories above and open any category to see its works "
        "and their quotes. If a category is too broad or an 'other' bucket is large, open its "
        "works, decide a split, and record the revised taxonomy as a new version; then run the "
        "classification miner again (its old rows stay). Commands: "
        f"<code>factory --project {esc(project.paths.slug)} mine status</code> and the Miners "
        "product's page for m-classification. A taxonomy as a versioned object is backlog "
        "IDEA-50.</p>",
    )
    (out / "index.html").write_text(page("Taxonomy", body, REPORT_CSS), encoding="utf-8")
