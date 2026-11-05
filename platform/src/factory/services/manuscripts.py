"""External manuscripts: adding, reading and reporting (slice 7b, plan W-C; spec ruling 17).

Declares: `add_manuscript`, `list_manuscripts`, `get_manuscript`, `require_manuscript`,
`manuscript_text`, `library_text`, `sentence_rows`, `citation_rows`, `closure_rows`, `units`. The
only module that writes `manuscript.added` and `manuscript.segmented`.

Invariants:
- A manuscript and its bibliography are copied into the git-ignored library by hash; the original
  file is only read. Events hold positions, hashes and keys, never text (R-47, decision 39).
- Adding is a human act; no MCP tool adds a manuscript.
- A refusal carries fixed reasons: never a sentence, a file's content or a decoder's message.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.manuscripts import (
    MAX_KEYS,
    MAX_LABEL,
    MAX_MANUSCRIPT_BYTES,
    MAX_SENTENCES,
    BibFormat,
    CitationRow,
    CitationState,
    ClosureRow,
    ManuscriptAdded,
    ManuscriptFormat,
    ManuscriptRow,
    ManuscriptSegmented,
    SentenceEntry,
    SentenceRow,
    UnitRow,
)
from factory.services.context import Project
from factory.writing.bibfile import BibFileError, BibRecord, read_bib, read_csl
from factory.writing.cites import cite_keys
from factory.writing.segment import SEGMENTER_VERSION, Format, mask, segment


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def format_of(fmt: ManuscriptFormat) -> Format:
    return fmt.value


def _read(path: Path, field: str) -> tuple[bytes, str]:
    """The bytes of a file and their text, or a refusal that quotes neither."""
    try:
        if path.stat().st_size > MAX_MANUSCRIPT_BYTES:
            raise _refuse(field, f"at most {MAX_MANUSCRIPT_BYTES} bytes")
        data = path.read_bytes()
    except OSError:
        raise _refuse(field, "cannot be read") from None
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(field, "not UTF-8 text") from None


def read_bibliography(body: str, fmt: BibFormat) -> list[BibRecord]:
    return read_csl(body) if fmt is BibFormat.CSL else read_bib(body)


def _bib_format(body: str) -> BibFormat:
    """CSL-JSON opens with `[` or `{`; anything else is read as BibTeX."""
    return BibFormat.CSL if body.lstrip()[:1] in ("[", "{") else BibFormat.BIBTEX


def _entries(body: str, fmt: Format) -> list[SentenceEntry]:
    masked = mask(body, fmt)
    entries: list[SentenceEntry] = []
    for s in segment(body, fmt):
        keys = cite_keys(masked[s.start : s.end], fmt)
        if len(keys) > MAX_KEYS:
            raise _refuse("path", f"a sentence holds more than {MAX_KEYS} citation keys")
        entries.append(
            SentenceEntry(
                ordinal=s.ordinal, start=s.start, end=s.end, sha256=s.sha256, keys=list(keys)
            )
        )
    return entries


def _same_bytes_added(project: Project, library_hash: str, bib_hash: str | None) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM manuscripts WHERE library_hash = :h "
                "AND ((bib_hash IS NULL AND :b IS NULL) OR bib_hash = :b)"
            ),
            {"h": library_hash, "b": bib_hash},
        ).first()
    return row is not None


def add_manuscript(
    project: Project,
    path: Path,
    *,
    fmt: ManuscriptFormat,
    bib: Path | None,
    label: str,
    actor: Actor,
) -> str:
    """Copy a manuscript (and its bibliography) into the library, segment it, and return its id.
    Refused, with nothing written: an agent (`actor`); a blank or long `label`; a file that cannot
    be read, is too large, is not UTF-8 or holds no sentence (`path`); a bibliography that cannot
    be read (`bib`); bytes already added with this bibliography (`path`). `label` is the
    researcher's own free text and is the one text of theirs an event holds."""
    if actor.kind != "human":
        raise _refuse("actor", "a manuscript is added by a human")
    if not label.strip() or len(label) > MAX_LABEL:
        raise _refuse("label", f"from 1 to {MAX_LABEL} characters")
    data, body = _read(path, "path")
    entries = _entries(body, format_of(fmt))
    if not entries:
        raise _refuse("path", "no sentence found")
    if len(entries) > MAX_SENTENCES:
        raise _refuse("path", f"at most {MAX_SENTENCES} sentences")
    bib_data: bytes | None = None
    bib_format: BibFormat | None = None
    if bib is not None:
        bib_data, bib_body = _read(bib, "bib")
        bib_format = _bib_format(bib_body)
        try:
            read_bibliography(bib_body, bib_format)
        except BibFileError:
            raise _refuse("bib", f"not a readable {bib_format.value} file") from None
    with project.index.exclusive():
        project.index.sync()
        try:
            library_hash = project.library.put(data)
            bib_hash = None if bib_data is None else project.library.put(bib_data)
        except OSError:
            raise _refuse("path", "the library cannot be written") from None
        if _same_bytes_added(project, library_hash, bib_hash):
            raise _refuse("path", "already added with this bibliography")
        manuscript_id = project.ids.new("msc")
        try:
            added = ManuscriptAdded(
                manuscript_id=manuscript_id,
                library_hash=library_hash,
                format=fmt,
                bib_hash=bib_hash,
                bib_format=bib_format,
                label=label,
                segmenter=SEGMENTER_VERSION,
            )
            segmented = ManuscriptSegmented(
                manuscript_id=manuscript_id, segmenter=SEGMENTER_VERSION, sentences=entries
            )
        except ValidationError:
            raise _refuse("path", "the segmentation does not validate") from None
        project.record(
            [
                project.events.make("manuscript.added", added, actor, refs=[manuscript_id]),
                project.events.make(
                    "manuscript.segmented",
                    segmented,
                    project.system_actor(),
                    refs=[manuscript_id],
                ),
            ]
        )
        return manuscript_id


_SELECT = (
    "SELECT m.manuscript_id, m.library_hash, m.format, m.bib_hash, m.bib_format, m.label, "
    "m.segmenter, (SELECT COUNT(*) FROM manuscript_sentences s "
    "WHERE s.manuscript_id = m.manuscript_id) AS sentences FROM manuscripts m"
)


def list_manuscripts(project: Project) -> list[ManuscriptRow]:
    """The manuscripts in the order they were added; empty on a fresh project."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text(f"{_SELECT} ORDER BY m.event_id")).mappings().all()
    return [ManuscriptRow.model_validate(dict(r)) for r in rows]


def get_manuscript(project: Project, manuscript_id: str) -> ManuscriptRow | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = (
            conn.execute(text(f"{_SELECT} WHERE m.manuscript_id = :m"), {"m": manuscript_id})
            .mappings()
            .first()
        )
    return None if row is None else ManuscriptRow.model_validate(dict(row))


def require_manuscript(project: Project, manuscript_id: str) -> ManuscriptRow:
    found = get_manuscript(project, manuscript_id)
    if found is None:
        raise _refuse("manuscript_id", "unknown manuscript")
    return found


def library_text(project: Project, ref: str) -> str:
    """The text stored under `ref`, which hashes to it or the store refuses it; else a refusal
    saying only that it is not there."""
    try:
        return project.library.get(ref).decode("utf-8")
    except (FactoryError, OSError, UnicodeDecodeError):
        raise _refuse("manuscript_id", "not in this library; add it again here") from None


def manuscript_text(project: Project, row: ManuscriptRow) -> str:
    return library_text(project, row.library_hash)


def sentence_rows(project: Project, manuscript_id: str) -> list[SentenceRow]:
    """The manuscript's sentences in order: positions, hashes and keys, no text."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ordinal, char_start, char_end, sha256, keys FROM manuscript_sentences "
                "WHERE manuscript_id = :m ORDER BY ordinal"
            ),
            {"m": manuscript_id},
        ).all()
    return [
        SentenceRow(ordinal=r[0], start=r[1], end=r[2], sha256=str(r[3]), keys=json.loads(r[4]))
        for r in rows
    ]


def citation_rows(project: Project, manuscript_id: str) -> dict[str, CitationRow]:
    """What each resolved key stands for, by key."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT key, work_id, method, score, state, decision "
                    "FROM manuscript_citations WHERE manuscript_id = :m ORDER BY key"
                ),
                {"m": manuscript_id},
            )
            .mappings()
            .all()
        )
    return {str(r["key"]): CitationRow.model_validate(dict(r)) for r in rows}


def closure_rows(project: Project, manuscript_id: str) -> dict[tuple[int, str], ClosureRow]:
    """The closures in force, by (ordinal, key)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT ordinal, key, work_id, reason FROM manuscript_closures "
                    "WHERE manuscript_id = :m ORDER BY ordinal, key"
                ),
                {"m": manuscript_id},
            )
            .mappings()
            .all()
        )
    return {(int(r["ordinal"]), str(r["key"])): ClosureRow.model_validate(dict(r)) for r in rows}


def units(project: Project, manuscript_id: str) -> list[UnitRow]:
    """The units of the manuscript by sentence and work: one per (sentence, resolved cited work),
    closed or open, and one per unresolved key closed. A key still proposed, or not yet resolved,
    makes none; keys of one sentence that resolve to one work make one."""
    citations = citation_rows(project, manuscript_id)
    closures = closure_rows(project, manuscript_id)
    found: dict[tuple[int, str], UnitRow] = {}
    for sentence in sentence_rows(project, manuscript_id):
        for key in sentence.keys:
            closure = closures.get((sentence.ordinal, key))
            citation = citations.get(key)
            if closure is not None:
                work, reason = closure.work_id, closure.reason
            elif citation is not None and citation.state is CitationState.RESOLVED:
                work, reason = citation.work_id, None
            else:
                continue
            slot = (sentence.ordinal, work or f"key:{key}")
            if slot in found:
                found[slot].keys.append(key)
            else:
                found[slot] = UnitRow(
                    ordinal=sentence.ordinal, work_id=work, keys=[key], reason=reason
                )
    return [found[slot] for slot in sorted(found)]
