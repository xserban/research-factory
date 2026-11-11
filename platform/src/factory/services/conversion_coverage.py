"""Automatic coverage check of converted documents (a mechanical triage, never a judgement).

For each converted document the words of the original (the text layer of a PDF, the visible text
of an HTML page) are compared with the words of the stored Markdown, by word 5-grams:

- recall: the share of the original's 5-grams found in the Markdown (low: text may be lost);
- precision: the share of the Markdown's 5-grams found in the original (low: reading order
  scrambled, or text added).

Both are noisy: a PDF text layer carries running headers and interleaved columns, an HTML page
carries alt text and hidden maths. The figures rank documents for a human to look at; they decide
nothing. LaTeX-source conversions (pandoc) have no comparable plain text and are not measured.

The result is a derived cache (`<project>/.cache/conversion-coverage.json`), rebuilt on demand by
`factory document coverage`. It is not an event and no event reads it; the dashboard shows it.
PDF text needs the `pdftotext` tool; without it the PDF documents are listed as not measured.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import Field
from sqlalchemy import text

from factory.errors import FactoryError
from factory.model.base import StrictModel
from factory.services.context import Project

_WORD = re.compile(r"[^\W_]+")
_HIDDEN = re.compile(r"(?is)<(script|style|annotation[^>]*|math)[^>]*>.*?</\1>")
_TAG = re.compile(r"<[^>]+>")
GRAM = 5
LOW = 0.8
"""Recall or precision below this is listed as low (a triage threshold, not a quality bar)."""


class CoverageRow(StrictModel):
    document_id: str
    work_id: str
    converter: str
    source_words: int = Field(ge=0)
    markdown_words: int = Field(ge=0)
    recall: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)


class CoverageReport(StrictModel):
    computed_at: str
    rows: list[CoverageRow]
    not_measured: dict[str, int]
    """Documents without a comparable plain text, by reason."""


def words(value: str) -> list[str]:
    return _WORD.findall(value.lower())


def grams(tokens: Sequence[str]) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + GRAM]) for i in range(len(tokens) - GRAM + 1)}


def overlap(source: Sequence[str], markdown: Sequence[str]) -> tuple[float, float]:
    """(recall, precision) of the 5-grams; 0.0 where a side has none."""
    a, b = grams(source), grams(markdown)
    common = len(a & b)
    return (common / len(a) if a else 0.0, common / len(b) if b else 0.0)


def html_text(raw: bytes) -> str:
    page = _HIDDEN.sub("", raw.decode("utf-8", errors="replace"))
    return html.unescape(_TAG.sub(" ", page))


def pdf_text(raw: bytes) -> str | None:
    """The text layer of a PDF, or None when `pdftotext` is missing or fails."""
    tool = shutil.which("pdftotext")
    if tool is None:
        return None
    done = subprocess.run(
        [tool, "-q", "-", "-"], input=raw, capture_output=True, check=False, timeout=120
    )
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None


def _source_text(media_type: str, raw: bytes) -> str | None:
    if media_type == "application/pdf":
        return pdf_text(raw)
    if media_type == "text/html":
        return html_text(raw)
    return None


def compute(project: Project) -> CoverageReport:
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT c.document_id, d.work_id, c.converter, d.media_type, d.raw_hash, "
                "c.markdown_hash FROM document_conversions c "
                "JOIN fulltext_documents d ON d.document_id = c.document_id"
            )
        ).all()
    rows: list[CoverageRow] = []
    skipped: Counter[str] = Counter()
    for document_id, work_id, converter, media_type, raw_hash, markdown_hash in found:
        try:
            source = _source_text(str(media_type), project.library.get(str(raw_hash)))
            markdown = project.library.get(str(markdown_hash)).decode("utf-8", errors="replace")
        except (OSError, ValueError, FactoryError, subprocess.SubprocessError):
            skipped["raw or Markdown unreadable"] += 1
            continue
        if source is None:
            skipped[f"no comparable text ({media_type})"] += 1
            continue
        a, b = words(source), words(_TAG.sub(" ", markdown))
        recall, precision = overlap(a, b)
        rows.append(
            CoverageRow(
                document_id=str(document_id),
                work_id=str(work_id),
                converter=str(converter),
                source_words=len(a),
                markdown_words=len(b),
                recall=round(recall, 3),
                precision=round(precision, 3),
            )
        )
    return CoverageReport(
        computed_at=project.clock.now().isoformat(), rows=rows, not_measured=dict(skipped)
    )


def cache_path(project: Project) -> Path:
    return project.paths.dir / ".cache" / "conversion-coverage.json"


def refresh(project: Project) -> CoverageReport:
    """Compute the report and store it as the derived cache."""
    report = compute(project)
    path = cache_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(), encoding="utf-8")
    return report


def cached(project: Project) -> CoverageReport | None:
    path = cache_path(project)
    if not path.exists():
        return None
    return CoverageReport.model_validate(json.loads(path.read_text(encoding="utf-8")))


def panel(project: Project, worst: int = 15) -> dict[str, object]:
    """The dashboard panel: per-converter summary and the lowest-recall documents, with titles."""
    report = cached(project)
    if report is None:
        return {"computed": False}
    by: dict[str, list[CoverageRow]] = {}
    for row in report.rows:
        by.setdefault(row.converter, []).append(row)
    summary = {}
    for converter, rows in sorted(by.items()):
        recalls = sorted(r.recall for r in rows)
        precisions = sorted(r.precision for r in rows)
        summary[converter] = {
            "documents": len(rows),
            "median_recall": recalls[len(recalls) // 2],
            "median_precision": precisions[len(precisions) // 2],
            "low_recall": sum(1 for r in rows if r.recall < LOW),
            "low_precision": sum(1 for r in rows if r.precision < LOW),
        }
    lowest = sorted(report.rows, key=lambda r: r.recall)[:worst]
    titles: dict[str, str] = {}
    with project.index.connect() as conn:
        for row in lowest:
            data = conn.execute(
                text("SELECT data FROM works WHERE work_id = :w"), {"w": row.work_id}
            ).scalar_one_or_none()
            titles[row.work_id] = str(json.loads(data).get("title", ""))[:90] if data else ""
    return cast(
        dict[str, object],
        {
            "computed": True,
            "computed_at": report.computed_at,
            "low_below": LOW,
            "summary": summary,
            "not_measured": report.not_measured,
            "lowest": [{**r.model_dump(), "title": titles.get(r.work_id, "")} for r in lowest],
        },
    )
