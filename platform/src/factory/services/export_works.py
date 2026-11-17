"""Export chosen works as files for a notebook tool (IDEA-87): the current converted Markdown of
each work, with a header that names the work and its conversion, optionally the stored PDF, and a
manifest of exactly what was written.

Read-only: no event is written, no model is called, the library is only read. Like the other file
exports (`exports`), the CLI and the hub call it as the researcher; the CLI leaves its usual access
log line.

Invariants:
- Every refusal is a FactoryValidationError raised before the output exists; files are built in a
  staging directory beside the output and reach it by one rename, so a refusal or a failure leaves
  nothing behind. An existing output is refused, never overwritten.
- The Markdown of a work is the document `document_read` would serve by default (the default
  conversion), read from the library and checked by its hash; the header carries the work id, the
  conversion id and the Markdown hash so an answer read elsewhere can be traced back by hand.
- A work without a converted document, an unknown id and a work whose blob is missing are listed in
  the manifest as skipped with a reason; none is dropped silently.
- A held-out seed's work is never exported (R-20). It is counted as `withheld` and named nowhere:
  neither its id nor any identifier is written to the manifest or the files.
- The selection is capped in works and in total bytes (defaults `MAX_WORKS`, `MAX_BYTES`).
- The manifest states that answers produced in the other tool are not records.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.services import document_read, withholding, work_layers
from factory.services.context import Project
from factory.services.conversions import conversion_of

MAX_WORKS = 200
MAX_BYTES = 500 * 1024 * 1024
UNLAYERED = "unlayered"

CAVEAT = (
    "Answers produced in the other tool are not records of this project. Their citations point to "
    "that tool's copy of each file, not to the factory's anchors; trace one back by the work id "
    "and conversion id in the header of the file it cites."
)


@dataclass(frozen=True)
class Selection:
    """The work ids to export and how they were chosen (a phrase for the manifest)."""

    ids: tuple[str, ...]
    how: str


@dataclass(frozen=True)
class ExportSummary:
    out: Path
    exported: int
    skipped: int
    withheld: int
    bytes: int
    without_pdf: int = 0
    works: tuple[str, ...] = field(default=())


def slug_of_id(work_id: str) -> str:
    """A filename-safe form of a work id."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", work_id.replace("rf:", "")).strip("-")[:80]


def _title_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]


def read_ids_file(path: Path) -> tuple[str, ...]:
    """Work ids one per line; blank lines and `#` comments are skipped, repeats dropped."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FactoryValidationError([ValidationIssue("from_file", f"cannot read: {exc}")]) from exc
    seen: dict[str, None] = {}
    for line in lines:
        item = line.strip()
        if item and not item.startswith("#"):
            seen.setdefault(item)
    return tuple(seen)


def select_by_layer(project: Project, layer: str) -> Selection:
    """The works whose layer is `layer`, sorted by id (read-only)."""
    found = work_layers.layers_of(project)
    ids = sorted(w for w, v in found.items() if (v.layer or UNLAYERED) == layer)
    return Selection(tuple(ids), f"layer {layer}")


def _refuse(field_: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, reason)])


def _withheld(project: Project, work_id: str, data: dict[str, Any] | None) -> bool:
    tokens = {t.lower() for t in withholding.held_out_tokens(project, include_work_ids=True)}
    if not tokens:
        return False
    if work_id.lower() in tokens:
        return True
    ident = (data or {}).get("identifiers") or {}
    if not isinstance(ident, dict):
        return False
    for key, value in ident.items():
        if not value:
            continue
        stated = f"pmid:{value}" if key == "pmid" else str(value)
        if stated.lower() in tokens:
            return True
    return False


def _work_data(project: Project, work_id: str) -> dict[str, Any] | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT data FROM works WHERE work_id = :w"), {"w": work_id}
        ).first()
    if row is None:
        return None
    loaded = json.loads(str(row[0]))
    return loaded if isinstance(loaded, dict) else None


def _pdf_of(project: Project, work_id: str, document_id: str) -> tuple[str, str] | None:
    """(library ref, document id) of a live PDF original: the converted document's own, else the
    work's earliest live PDF document; None when there is none."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT document_id, raw_hash FROM fulltext_documents WHERE work_id = :w "
                "AND superseded_by IS NULL AND media_type = 'application/pdf' ORDER BY event_id"
            ),
            {"w": work_id},
        ).all()
    ordered = sorted(rows, key=lambda r: str(r[0]) != document_id)
    return (str(ordered[0][1]), str(ordered[0][0])) if ordered else None


def _quote(value: object) -> str:
    return json.dumps("" if value is None else value, ensure_ascii=False)


def _header(fields: list[tuple[str, str]]) -> str:
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in fields) + "---\n\n"


def export_works(
    project: Project,
    selection: Selection,
    out: Path,
    *,
    pdfs: bool = False,
    max_works: int = MAX_WORKS,
    max_bytes: int = MAX_BYTES,
    now: str | None = None,
) -> ExportSummary:
    """Write the export of `selection` to `out`: a directory that does not exist, or a path ending
    `.zip` that does not exist. Raises FactoryValidationError (nothing left behind) for an empty or
    over-cap selection, an existing output, or a total over `max_bytes`."""
    ids = tuple(dict.fromkeys(selection.ids))
    if not ids:
        raise _refuse("selection", "no works selected")
    if len(ids) > max_works:
        raise _refuse("selection", f"{len(ids)} works selected; the cap is {max_works}")
    if out.exists():
        raise _refuse("out", "already exists; name a new path")
    zipped = out.suffix == ".zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    project.index.sync()
    layers = work_layers.layers_of(project)
    refs = document_read.default_conversions(project, ids)
    stamp = now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    stage = Path(tempfile.mkdtemp(prefix=".export-", dir=out.parent))
    try:
        summary = _build(
            project, ids, selection.how, stage, layers, refs, pdfs, max_bytes, stamp, out
        )
        if zipped:
            _zip(stage, out)
            shutil.rmtree(stage)
        else:
            stage.rename(out)
        return summary
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _zip(stage: Path, out: Path) -> None:
    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(str(path.relative_to(stage)), (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, path.read_bytes())
    tmp.rename(out)


def _build(
    project: Project,
    ids: tuple[str, ...],
    how: str,
    stage: Path,
    layers: dict[str, work_layers.WorkLayer],
    refs: dict[str, document_read.ConversionRef | None],
    pdfs: bool,
    max_bytes: int,
    stamp: str,
    out: Path,
) -> ExportSummary:
    (stage / "markdown").mkdir()
    if pdfs:
        (stage / "pdf").mkdir()
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    withheld = 0
    total = 0
    used: set[str] = set()
    for work_id in ids:
        data = _work_data(project, work_id)
        if _withheld(project, work_id, data):
            withheld += 1
            continue
        if data is None:
            skipped.append({"work_id": work_id, "reason": "unknown work"})
            continue
        ref = refs.get(work_id)
        conv = None if ref is None else conversion_of(project, ref.conversion_id)
        if ref is None or conv is None:
            skipped.append({"work_id": work_id, "reason": "no converted document"})
            continue
        try:
            markdown = project.library.get(conv.markdown_hash).decode("utf-8")
        except (BlobNotFoundError, BlobIntegrityError, OSError, UnicodeDecodeError):
            skipped.append(
                {
                    "work_id": work_id,
                    "reason": "stored Markdown missing or damaged; run "
                    "`factory document convert --restore`",
                }
            )
            continue
        authors = [str(a.get("name")) for a in data.get("authors") or [] if a.get("name")]
        published = str((data.get("dates") or {}).get("published") or "")
        ident = data.get("identifiers") or {}
        layer = layers.get(work_id)
        title = str(data.get("title") or work_id)
        fields = [
            ("work_id", _quote(work_id)),
            ("title", _quote(title)),
            ("authors", _quote(authors)),
            ("year", _quote(published[:4])),
            ("doi", _quote(ident.get("doi"))),
            ("identifiers", _quote({k: v for k, v in sorted(ident.items()) if v})),
            ("conversion_id", _quote(conv.conversion_id)),
            ("markdown_hash", _quote(conv.markdown_hash)),
            ("layer", _quote(layer.layer if layer and layer.layer else UNLAYERED)),
        ]
        body = _header(fields) + markdown
        stem = f"{_title_slug(title)}--{slug_of_id(work_id)}"
        while stem in used:
            stem += "-x"
        used.add(stem)
        raw = body.encode("utf-8")
        total += len(raw)
        pdf_entry: dict[str, Any] | None = None
        pdf_src: Path | None = None
        if pdfs:
            found = _pdf_of(project, work_id, ref.document_id)
            if found is not None:
                path = project.library.path(found[0])
                if path.is_file():
                    pdf_src = path
                    total += path.stat().st_size
                    pdf_entry = {
                        "file": f"pdf/{stem}.pdf",
                        "sha256": found[0].split(":")[-1],
                        "document_id": found[1],
                    }
        if total > max_bytes:
            raise _refuse("bytes", f"the export exceeds {max_bytes} bytes (at work {work_id})")
        (stage / "markdown" / f"{stem}.md").write_bytes(raw)
        if pdf_src is not None and pdf_entry is not None:
            shutil.copyfile(pdf_src, stage / pdf_entry["file"])
        entries.append(
            {
                "work_id": work_id,
                "title": title,
                "file": f"markdown/{stem}.md",
                "file_sha256": hashlib.sha256(raw).hexdigest(),
                "conversion_id": conv.conversion_id,
                "markdown_hash": conv.markdown_hash,
                "pdf": pdf_entry,
            }
        )
    without = [e["work_id"] for e in entries if pdfs and e["pdf"] is None]
    manifest: dict[str, Any] = {
        "project": project.paths.slug,
        "exported_at": stamp,
        "selection": how,
        "selected": len(ids),
        "pdfs": "included where stored" if pdfs else "not requested",
        "works": entries,
        "skipped": skipped,
        "withheld": withheld,
        "works_without_pdf": without,
        "note": CAVEAT,
    }
    (stage / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "MANIFEST.md").write_text(_manifest_md(manifest), encoding="utf-8")
    return ExportSummary(
        out=out,
        exported=len(entries),
        skipped=len(skipped),
        withheld=withheld,
        bytes=total,
        without_pdf=len(without),
        works=tuple(e["work_id"] for e in entries),
    )


def _manifest_md(m: dict[str, Any]) -> str:
    lines = [
        "# Export manifest",
        "",
        f"- Project: {m['project']}",
        f"- Exported at: {m['exported_at']}",
        f"- Selection: {m['selection']} ({m['selected']} works)",
        f"- PDFs: {m['pdfs']}",
        f"- Exported: {len(m['works'])}; skipped: {len(m['skipped'])}; "
        f"withheld (held-out, not named): {m['withheld']}",
        "",
        f"**Note.** {m['note']}",
        "",
        "## Exported works",
        "",
    ]
    for e in m["works"]:
        pdf = (
            ""
            if m["pdfs"] == "not requested"
            else (f"; PDF {e['pdf']['file']}" if e["pdf"] else "; no PDF in the store")
        )
        lines.append(
            f"- {e['work_id']}: {e['title']} -> {e['file']} (conversion {e['conversion_id']}, "
            f"Markdown {e['markdown_hash']}){pdf}"
        )
    lines += ["", "## Skipped works", ""]
    lines += [f"- {s['work_id']}: {s['reason']}" for s in m["skipped"]] or ["- none"]
    if m["pdfs"] != "not requested":
        lines += ["", "## Works without a PDF", ""]
        lines += [f"- {w}: no PDF in the store" for w in m["works_without_pdf"]] or ["- none"]
    return "\n".join(lines) + "\n"


def work_ids_of(values: Sequence[str]) -> tuple[str, ...]:
    """Ids from a list given on a command line or in a request: trimmed, blanks and repeats out."""
    return tuple(dict.fromkeys(v.strip() for v in values if v and v.strip()))
