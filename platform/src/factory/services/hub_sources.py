"""The `sources` hub payload: searches and deduplication, full-text acquisition, conversion
coverage and the registered study documents (plan hub-ui port, step 3).

Invariants:
- `build` is pure over its `HubContext` and reads no network. It wraps `site_search.build_payload`,
  `dashboard._search/_dedup`, `fulltext_status`, `list_deviations`, `conversion_coverage`
  (cached report only: a missing cache is reported, never computed here), `site_inspector.documents`
  and `study_files`; no number those services compute is re-derived. The only figures computed
  here are aggregates of their rows: skipped records by reason, undeclared works, recall histograms
  and files by status.
- Writes nothing. A merge revert stays a read-only state (ruling P2); the CLI does it.
- Per-document inspector detail (gaps, extracted Markdown) is not in the payload; see
  `inspector_commands` for what the page can show without it.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from typing import TYPE_CHECKING, Any, cast

from factory.document.optional import converter_infos
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.work_ids import WORK_ID_RE
from factory.services import conversion_coverage as cov
from factory.services import dashboard, site_inspector, site_search
from factory.services.context import Project
from factory.services.flow_skipped import skipped_records
from factory.services.fulltext_status import fulltext_status
from factory.services.hub_tab_help import TAB_HELP
from factory.services.protocol import list_deviations
from factory.services.site_corpus import slug_of
from factory.services.site_documents import KIND_TITLES, _slug
from factory.services.site_inspector import documents as inspector_documents
from factory.services.site_quality import REASONS, ROUTE_HELP, _works_info
from factory.services.study_files import file_status, list_files

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

SKIPPED_SHOWN = 1000
"""Skipped records kept per query in the payload (the old page's cap); the count is complete."""
DEVIATION_TEXT = 200
BINS = 10
"""Recall histogram bins over 0 to 1."""

METHODS: dict[str, str] = {
    "tab_search": TAB_HELP["search"],
    "tab_conversion": TAB_HELP["conversion"],
    "search": (
        "<b>What it shows</b> Each registered query with what its source said it had and what was "
        "retrieved.<p><span class=k>How to read it.</span> The gap is the total the source "
        "reported less the records retrieved. Records of an archived page that did not become "
        "works are listed under their query.</p><p><span class=k>How it's computed.</span> "
        "From the search report and the run gaps in the event log.</p>"
    ),
    "yield": (
        "<b>What it shows</b> Reported against retrieved, per query.<p><span class=k>How to read "
        "it.</span> A bar that stops short of the reported mark means the source offered more than "
        "was fetched.</p><p><span class=k>How it's computed.</span> Reported is the last run's "
        "reported total; retrieved is the sum over the query's runs, which resume one another.</p>"
    ),
    "skipped": (
        "<b>What it shows</b> Raw records of an archived result page that never became works."
        "<p><span class=k>How it's computed.</span> The archived pages are parsed again and "
        "compared with the records the run kept. Reasons: untitled, duplicate within the run, "
        "unparsed.</p>"
    ),
    "dedup": (
        "<b>What it shows</b> Every merge of duplicate records, active or reverted, and the rule "
        "that matched them.<p><span class=k>How to read it.</span> The rule is an identifier "
        "match; no verdict is involved. A reverted merge keeps its recorded reason and time.</p>"
        "<p><span class=k>How it's computed.</span> From the merge projection; the revert time is "
        "read from the log. Reverting is done with the command line and is not offered here.</p>"
    ),
    "after": (
        "<b>What it shows</b> Merges whose absorbed record was screened differently from the "
        "primary.<p><span class=k>How it's computed.</span> The canonical work's outcome stands in "
        "every count (researcher ruling 2026-11-14); these pairs are listed for review.</p>"
    ),
    "identification": (
        "<b>What it shows</b> How many records each source gave, and the PRISMA split into "
        "databases and other sources.<p><span class=k>How it's computed.</span> From the PRISMA "
        "flow and the search report.</p>"
    ),
    "acquisition": (
        "<b>What it shows</b> Which papers promoted to full text have a document, by route, and "
        "which do not.<p><span class=k>How to read it.</span> Promoted: passed title and abstract "
        "screening. Unsought: promoted but not yet fetched (a later tranche). Retrieved: has a "
        "stored document. Not retrieved: tried, and has none; such a paper is excluded from "
        "full-text screening and extraction, and a protocol deviation records the decision.</p>"
        "<p><span class=k>How it's computed.</span> From the full-text projection; the three "
        "states add up to the promoted count.</p>"
    ),
    "funnel": (
        "<b>What it shows</b> The path from promoted papers to stored documents.<p><span class=k>"
        "How it's computed.</span> The same counts as the figures above; each route segment counts "
        "live documents of that route.</p>"
    ),
    "deviations": (
        "<b>What it shows</b> Recorded departures from the protocol, with the papers each affects."
        "<p><span class=k>How it's computed.</span> From the deviation events.</p>"
    ),
    "conversion": (
        "<b>What it shows</b> How much of each original's text survives conversion to Markdown."
        "<p><span class=k>How to read it.</span> Recall is the share of the original's word "
        "5-grams found in the Markdown (low: text may be lost). Precision is the share of the "
        "Markdown's found in the original (low: scrambled order or added text). Both are noisy "
        "(running headers, numbered lines). They rank documents for a person to check and decide "
        "nothing.</p><p><span class=k>How it's computed.</span> By a mechanical comparison stored "
        "as a cache; low is below the threshold in the payload.</p>"
    ),
    "survival": (
        "<b>What it shows</b> The spread of recall for each converter.<p><span class=k>How to read "
        "it.</span> Each bar counts documents in a tenth of the range; the left end is the "
        "documents to check first. Click a bar to list them.</p><p><span class=k>How it's "
        "computed.</span> Documents counted per bin of the cached recall.</p>"
    ),
    "documents": (
        "<b>What it shows</b> The files registered with the study, by kind.<p><span class=k>How to "
        "read it.</span> Each registration keeps the content it named, so an earlier version stays "
        "readable. Changed means the file on disk differs from the last registration.</p>"
        "<p><span class=k>How it's computed.</span> From the file registration events; the status "
        "compares the current file hash with the registered one.</p>"
    ),
}


def _search(project: Project) -> dict[str, Any]:
    """Queries, merges and the tiles and per-source totals of the old Search tab."""
    out = site_search.build_payload(project)
    out.pop("generated", None)  # the shell carries the build time
    skipped_all = skipped_records(project)
    out["skipped_by_reason"] = dict(sorted(Counter(s.reason for s in skipped_all).items()))
    out["skipped_total"] = len(skipped_all)
    for query in out["queries"]:
        query["skipped_n"] = len(query["skipped"])
        query["skipped"] = query["skipped"][:SKIPPED_SHOWN]
    tab = cast(dict[str, Any], dashboard._search(project))
    tab.pop("rows", None)  # `queries` already carries them
    out["per_source"] = tab["per_source"]
    out["runs_complete"] = tab["runs_complete"]
    out["runs_partial"] = tab["runs_partial"]
    out["identification"] = tab["identification"]
    out["merge_tiles"] = dashboard._dedup(project)
    return out


def _acquisition(project: Project) -> dict[str, Any]:
    """Full-text status, the not-retrieved works with their reasons and the deviations."""
    status = fulltext_status(project)
    deviations = list_deviations(project)
    declared: dict[str, str] = {}
    for dev in deviations:
        for work_id in dev.affects:
            declared.setdefault(work_id, dev.deviation_id)
    missing = [w for w in status.works if w.state == "not-retrieved"]
    info = _works_info(project, [w.work_id for w in missing])
    slug = project.paths.slug
    works: list[dict[str, Any]] = []
    for w in sorted(
        missing, key=lambda x: (x.work_id in declared, info.get(x.work_id, {}).get("title", ""))
    ):
        meta = info.get(w.work_id, {})
        title = meta.get("title", w.work_id)
        doi = meta.get("doi", "")
        works.append(
            {
                "id": w.work_id,
                "slug": slug_of(w.work_id),
                **meta,
                "title": title,
                "reasons": {str(k.value): v for k, v in sorted(w.reasons.items())},
                "declared_by": declared.get(w.work_id),
                "file_name": (doi.replace("/", "_") + ".pdf") if doi else None,
                "deviation": {
                    "description": f"{title[:60].strip()} has no retrievable full text "
                    "and is not acquired.",
                    "reason": "No automatic route found a copy and none was supplied.",
                    "affects": [w.work_id],
                },
                "fetch_command": f"factory --project {slug} fulltext fetch --work {w.work_id}",
            }
        )
    undeclared = [w["id"] for w in works if not w["declared_by"]]
    return {
        "promoted": status.promoted,
        "unsought": status.unsought,
        "retrieved": status.retrieved,
        "not_retrieved": status.not_retrieved,
        "by_route": {str(k.value): v for k, v in status.by_route.items()},
        "route_help": ROUTE_HELP,
        "reason_help": REASONS,
        "works": works,
        "undeclared": undeclared,
        "batch_deviation": {
            "description": "Promoted works with no retrievable full text are not acquired.",
            "reason": "No automatic route found a copy and none was supplied.",
            "affects": undeclared,
        },
        "commands": {
            "import": f"factory --project {slug} fulltext import FOLDER",
            "deviation": f"factory --project {slug} protocol deviation --file deviation.json",
        },
        "deviations": [
            {
                "id": d.deviation_id,
                "protocol_id": d.protocol_id,
                "works": len(d.affects),
                "description": d.description[:DEVIATION_TEXT],
                "reason": d.reason,
            }
            for d in deviations
        ],
    }


def _histogram(values: list[float]) -> list[int]:
    bins = [0] * BINS
    for v in values:
        bins[min(int(v * BINS), BINS - 1)] += 1
    return bins


def _conversion(project: Project) -> dict[str, Any]:
    """The cached coverage report with every converted document (None figures: not measured)."""
    report = cov.cached(project)
    panel = cov.panel(project, worst=0)
    docs = inspector_documents(
        project, report or cov.CoverageReport(computed_at="", rows=[], not_measured={})
    )
    rows = [
        {
            "id": d.document_id,
            "work_id": d.work_id,
            "slug": d.slug,
            "title": d.title,
            "converter": d.converter,
            "media": d.media_type,
            "recall": d.recall,
            "precision": d.precision,
            "words": d.source_words,
            "md_words": d.markdown_words,
        }
        for d in docs
    ]
    by_converter: dict[str, list[float]] = {}
    for d in docs:
        if d.recall is not None:
            by_converter.setdefault(d.converter, []).append(d.recall)
    return {
        "computed": bool(panel.get("computed")),
        "computed_at": panel.get("computed_at"),
        "low": cov.LOW,
        "summary": panel.get("summary", {}),
        "not_measured": panel.get("not_measured", {}),
        "documents": rows,
        "document_of_work": {r["work_id"]: r["id"] for r in reversed(rows)},
        "distribution": {
            "bins": BINS,
            "by_converter": {c: _histogram(v) for c, v in sorted(by_converter.items())},
        },
        "converters": [
            {"name": i.name, "accepts": list(i.accepts), "available": i.available}
            for i in converter_infos()
        ],
        "commands": {
            "coverage": f"factory --project {project.paths.slug} document coverage",
            "converters": f"factory --project {project.paths.slug} document converters",
            "slug": project.paths.slug,
        },
    }


def _documents(project: Project) -> dict[str, Any]:
    """Registered files by kind, each with its status and earlier versions."""
    files = list_files(project)
    status = {s.path: s for s in file_status(project)}
    base = project.paths.dir.resolve()
    kinds: list[dict[str, Any]] = []
    for kind, title in KIND_TITLES.items():
        entries = [f for f in files if f.latest.kind == kind]
        if not entries:
            continue
        rows: list[dict[str, Any]] = []
        for entry in entries:
            latest = entry.latest
            state = status[latest.path].state if latest.path in status else "unchanged"
            outside = not (base / latest.path).resolve().is_relative_to(base)
            name = _slug(latest.path)
            is_md = latest.path.lower().endswith((".md", ".markdown"))
            rows.append(
                {
                    "path": latest.path,
                    "title": latest.title,
                    "version": latest.version,
                    "registered": latest.registered_at[:10],
                    "sha": latest.sha256[:12],
                    "state": state,
                    "outside": outside,
                    "markdown": is_md,
                    "href": None
                    if outside
                    else (f"../documents/{name}.html" if is_md else f"../documents/files/{name}"),
                    "history": [
                        {"version": r.version, "at": r.registered_at[:10], "sha": r.sha256[:12]}
                        for r in entry.history
                    ],
                }
            )
        kinds.append(
            {
                "kind": kind,
                "title": title,
                "files": rows,
                "changed": sum(1 for r in rows if r["state"] == "changed"),
                "missing": sum(1 for r in rows if r["state"] == "missing"),
            }
        )
    return {
        "registered": len(files),
        "changed": sum(1 for s in status.values() if s.state == "changed"),
        "missing": sum(1 for s in status.values() if s.state == "missing"),
        "kinds": kinds,
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The `sources` payload: search, acquisition, conversion and documents, plus `methods`."""
    project = ctx.project
    payload = {
        "ready": True,
        "methods": METHODS,
        "search": _search(project),
        "acquisition": _acquisition(project),
        "conversion": _conversion(project),
        "documents": _documents(project),
    }
    json.dumps(payload)  # the payload must serialise as it stands
    return payload


# ---------------------------------------------------------------- one document (lazy routes)

DOC_TEXT_CAP = 400_000
"""Characters of the original's text and of the Markdown kept in a document payload."""
FILE_TYPES: dict[str, str] = {
    "application/pdf": "application/pdf",
    "text/html": "text/plain; charset=utf-8",  # never served as a page of this origin
    "application/x-eprint-tar": "application/x-tar",
}


def _find_document(project: Project, document_id: str) -> site_inspector.Doc | None:
    """The live converted document `document_id` (None for an unknown or malformed id): the id is
    matched against the index, so no value of the URL reaches the filesystem."""
    by_work = bool(re.match(WORK_ID_RE, document_id))
    if not by_work and not re.match(DOCUMENT_ID_RE, document_id):
        return None
    report = cov.cached(project) or cov.CoverageReport(computed_at="", rows=[], not_measured={})
    for doc in inspector_documents(project, report):  # ordered by work id; first live one wins
        if doc.document_id == document_id or (by_work and doc.work_id == document_id):
            return doc
    return None


_DETAILS: dict[tuple[str, str, str], dict[str, Any]] = {}
"""Content-addressed cache of built document payloads (keyed by the hashes of both texts)."""


def document_detail(project: Project, document_id: str) -> dict[str, Any] | None:
    """The `sources-doc-<id>` payload: the original's text (or a tar listing), the Markdown, the
    runs lost and added (`site_inspector.gaps`, six words or more) and the file routes. None when
    the id is not a converted document of the project. Reads only; cached by content hash."""
    doc = _find_document(project, document_id)
    if doc is None:
        return None
    key = (doc.document_id, doc.raw_hash, doc.markdown_hash)
    if key in _DETAILS:
        return _DETAILS[key]
    markdown = project.library.get(doc.markdown_hash).decode("utf-8", errors="replace")
    source: str | None = None
    listing = ""
    if doc.ext == "tar":
        listing = html.unescape(
            re.sub(r"<[^>]+>", " ", site_inspector._tar_listing(project.library.get(doc.raw_hash)))
        )
    else:
        source = cov._source_text(doc.media_type, project.library.get(doc.raw_hash))
    lost, added, n_src, n_md = site_inspector.gaps(doc, markdown, source)
    detail: dict[str, Any] = {
        "document_id": doc.document_id,
        "work_id": doc.work_id,
        "converter": doc.converter,
        "media": doc.media_type,
        "original_text": None if source is None else source[:DOC_TEXT_CAP],
        "tar_listing": " ".join(listing.split()),
        "markdown": markdown[:DOC_TEXT_CAP],
        "truncated": len(markdown) > DOC_TEXT_CAP or len(source or "") > DOC_TEXT_CAP,
        "lost": [[pos, run] for pos, run in lost[: site_inspector.MAX_RUNS * 8]],
        "added": [[pos, run] for pos, run in added[: site_inspector.MAX_RUNS * 8]],
        "source_tokens": n_src,
        "markdown_tokens": n_md,
        "files": {
            "original": f"file/original/{doc.document_id}",
            "markdown": f"file/markdown/{doc.document_id}",
        },
    }
    json.dumps(detail)
    if len(_DETAILS) >= 16:
        _DETAILS.pop(next(iter(_DETAILS)))
    _DETAILS[key] = detail
    return detail


def document_file(project: Project, document_id: str, kind: str) -> tuple[bytes, str] | None:
    """(bytes, content type) of a converted document's `original` or `markdown`; None when the
    kind or the id is unknown. HTML originals are served as text, never as a page."""
    if kind not in ("original", "markdown"):
        return None
    doc = _find_document(project, document_id)
    if doc is None:
        return None
    if kind == "markdown":
        return project.library.get(doc.markdown_hash), "text/markdown; charset=utf-8"
    return project.library.get(doc.raw_hash), FILE_TYPES.get(
        doc.media_type, "application/octet-stream"
    )
