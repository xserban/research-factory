"""Attach the files an export names to the promoted works its records resolved to (ruling 24).

`attach_import` goes through the records of an import that carry an attachment, in ordinal order.
The file's bytes were copied into the library when the import was recorded; here a record whose
work is promoted (included at the last declared stage) gets a researcher-route document through
`record_supplied_document`, with an `import.attachment_linked` event in the same append.

Each record with an attachment lands in exactly one list of the report:
- `already_attached`: a link for the record exists; nothing is written. (A record whose bytes
  already back a document of its work gets its link and is listed here too.)
- `attachment_missing`: the export named a file that could not be read at import time, or its
  bytes are no longer in the library.
- `unresolved`: the record has no resolved work (unresolved, unconfirmed or ambiguous).
- `not_promoted`: its work has not passed screening. No document is ever recorded for it.
- `identity_unchecked`: a PDF-folder record whose resolved title does not occur, normalised, in
  the first page's text, until a human confirms the record (`decide_import`).
- `attached`: a document was recorded, as `(ordinal, work, document)`.

Invariants:
- Only promoted works get documents. The actor is the researcher and the document route is
  `researcher`, as for the folder import.
- First-page text is read in memory for the identity check and never stored or returned.
- The report lists ordinals: it is the researcher's, and no agent surface may return it.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from pydantic import Field
from pypdf import PdfReader
from sqlalchemy import text

from factory.events.envelope import Event
from factory.imports.model import ImportFormat
from factory.model.base import StrictModel
from factory.model.imports import ImportAttachmentLinked
from factory.model.references import LinkState
from factory.model.work_ids import normalize_title
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.fulltext import record_supplied_document
from factory.services.imports import import_row
from factory.services.search import get_work

_MEDIA_TYPE = "application/pdf"
_SOURCE_PREFIX = "file:"
_SOURCE_DIGITS = 12
_LINKED = "import.attachment_linked"


class AttachReport(StrictModel):
    """Where each attachment of one import landed (see the module docstring)."""

    attached: list[tuple[int, str, str]] = Field(default_factory=list)
    not_promoted: list[int] = Field(default_factory=list)
    unresolved: list[int] = Field(default_factory=list)
    attachment_missing: list[int] = Field(default_factory=list)
    identity_unchecked: list[int] = Field(default_factory=list)
    already_attached: list[int] = Field(default_factory=list)


def attach_import(project: Project, import_id: str) -> AttachReport:
    """Attach every file the import names to its record's promoted work; see the module docstring.

    Raises `FactoryValidationError` for an unknown import, writing nothing.
    """
    report = AttachReport()
    with project.index.exclusive():
        project.index.sync()
        row = import_row(project, import_id)
        promoted = _promoted(project)
        linked = _linked(project, import_id)
        for record in _records(project, import_id):
            ordinal = record.ordinal
            content = record.content_sha256
            if ordinal in linked:
                report.already_attached.append(ordinal)
                continue
            if content is None:
                report.attachment_missing.append(ordinal)
                continue
            work_id = record.work_id
            if record.link_state != LinkState.RESOLVED.value or work_id is None:
                report.unresolved.append(ordinal)
                continue
            if work_id not in promoted:
                report.not_promoted.append(ordinal)
                continue
            ref = f"sha256:{content}"
            if not project.library.exists(ref):
                report.attachment_missing.append(ordinal)
                continue
            data = project.library.get(ref)
            confirmed = record.decision == "confirm"
            if (
                row.format is ImportFormat.PDFS
                and not confirmed
                and not _title_on_first_page(project, work_id, data)
            ):
                report.identity_unchecked.append(ordinal)
                continue
            _attach(project, import_id, ordinal, work_id, data, report)
    return report


def _attach(
    project: Project, import_id: str, ordinal: int, work_id: str, data: bytes, report: AttachReport
) -> None:
    actor = project.human_actor()

    def link(document_id: str) -> Event:
        payload = ImportAttachmentLinked(
            import_id=import_id, ordinal=ordinal, work_id=work_id, document_id=document_id
        )
        return project.events.make(_LINKED, payload, actor, refs=(import_id, document_id))

    digest = hashlib.sha256(data).hexdigest()
    document_id = record_supplied_document(
        project,
        work_id,
        content=data,
        source_version=f"{_SOURCE_PREFIX}{digest[:_SOURCE_DIGITS]}",
        media_type=_MEDIA_TYPE,
        actor=actor,
        link=link,
    )
    if document_id is not None:
        report.attached.append((ordinal, work_id, document_id))
        return
    # The bytes already back a document of this work: link the record to it.
    existing = _document_of(project, work_id, f"sha256:{digest}")
    if existing is not None:
        project.record([link(existing)])
    report.already_attached.append(ordinal)


def _promoted(project: Project) -> set[str]:
    """Works included at the last declared stage, with the ids merged into them."""
    included = {w for w, o in final_outcomes(project).items() if o is Outcome.INCLUDED}
    absorbed = {a for m in active_merges(project) if m.primary in included for a in m.absorbed}
    return included | absorbed


@dataclass(frozen=True)
class _Record:
    ordinal: int
    link_state: str | None
    work_id: str | None
    decision: str | None
    content_sha256: str | None


def _records(project: Project, import_id: str) -> list[_Record]:
    """The records that name a file (readable or not), in ordinal order."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ordinal, link_state, work_id, decision, attachment_content_sha256 "
                "FROM import_records WHERE import_id = :i "
                "AND attachment_path_sha256 IS NOT NULL ORDER BY ordinal"
            ),
            {"i": import_id},
        ).all()
    return [
        _Record(
            int(o),
            None if s is None else str(s),
            None if w is None else str(w),
            None if d is None else str(d),
            None if c is None else str(c),
        )
        for o, s, w, d, c in rows
    ]


def _linked(project: Project, import_id: str) -> set[int]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT ordinal FROM import_attachments WHERE import_id = :i"), {"i": import_id}
        ).all()
    return {int(o) for (o,) in rows}


def _document_of(project: Project, work_id: str, raw_hash: str) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT document_id FROM fulltext_documents WHERE work_id = :w "
                "AND raw_hash = :h ORDER BY event_id LIMIT 1"
            ),
            {"w": work_id, "h": raw_hash},
        ).first()
    return None if row is None else str(row[0])


def _title_on_first_page(project: Project, work_id: str, data: bytes) -> bool:
    """Whether the work's normalised title occurs in the normalised text of the PDF's first page.
    The text is read in memory and dropped; a reader failure is a failed check."""
    work = get_work(project, work_id)
    wanted = normalize_title(work.title) if work is not None else ""
    if not wanted:
        return False
    try:
        page = PdfReader(io.BytesIO(data)).pages[0].extract_text() or ""
    # pypdf raises many exception types on damaged input, and none of them is fatal here.
    except Exception:
        return False
    return wanted in normalize_title(page)
