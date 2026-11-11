"""The explorer product: the corpus as list, timeline, chronology, lineage and graph views, each
work with its structured summary, quoted evidence and a link to the original (plan site-hub,
step 2).

Built from `site_corpus.corpus_payload`; writes `index.html` and `docs/` (links to the stored
originals under their own file names). A projection: rebuilt from the events, never edited.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from factory.services.context import Project
from factory.services.site_corpus import corpus_payload
from factory.services.site_explorer_page import DATA_MARKER, PAGE
from factory.services.site_widgets import FUTURE_CSS


def link_documents(payload: dict[str, object], out: Path) -> int:
    """Link each work's stored original into `out/docs/<name>` and give the work a relative path.

    The absolute library file is dropped from the payload. Returns the number of links."""
    docs = out / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    n = 0
    works = payload["works"]
    assert isinstance(works, list)
    for w in works:
        doc = w.get("doc")
        if not doc:
            continue
        source, name = Path(doc["file"]), doc["name"]
        if source.exists():
            target = docs / name
            if target.is_symlink() or target.exists():
                target.unlink()
            os.symlink(source, target)
            w["doc"] = {"kind": doc["kind"], "path": f"docs/{name}"}
            n += 1
        else:
            w["doc"] = None
    return n


def build_explorer(project: Project, out: Path) -> None:
    payload = corpus_payload(project)
    link_documents(payload, out)
    payload["project"] = project.paths.slug
    payload["generated"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    (out / "index.html").write_text(
        PAGE.replace("FUTURE_OVERLAY", FUTURE_CSS).replace(DATA_MARKER, data), encoding="utf-8"
    )
