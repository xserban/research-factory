"""Recording an imported library: parse, archive verbatim, record (slice 3d rulings 17-20).

`record_import` parses the export with the registry's parser, then, under the index lock, puts the
export (or, for a PDF folder, the manifest of its files) and every readable attachment into the
git-ignored library, the allow-listed records into `blobs/`, and writes one `import.recorded`
event as the researcher.

Invariants:
- Invalid input (unreadable path, wrong format, bad collection) raises `FactoryValidationError`
  and writes nothing, not even to the library.
- Nothing but allow-listed fields and hashes reaches `blobs/` or the event log; notes, `annote`
  and attachment paths stay in the library copy of the export.
- The same file imported twice gives two imports with the same `file_hash` and `records_blob`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import JsonValue

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.reader import read_all
from factory.imports.model import ImportFormat, ImportFormatError, ImportRecord, ParsedImport
from factory.imports.model import ParseOutcome as ParseOutcome
from factory.imports.registry import parse
from factory.model.base import StrictModel
from factory.model.imports import MAX_COLLECTION, ImportRecorded, ImportRole, SplitMode
from factory.services.context import Project

_RECORDED = "import.recorded"


class ImportSummary(StrictModel):
    import_id: str
    counts: dict[ParseOutcome, int]
    attachments: int
    attachments_missing: int
    split: SplitMode


def record_key(import_id: str, ordinal: int) -> str:
    """The key of one record of an import: `imp_<ULID>:<ordinal>`."""
    return f"{import_id}:{ordinal}"


def record_import(
    project: Project,
    path: Path,
    *,
    format: ImportFormat,
    role: ImportRole,
    collection: str | None = None,
    random_seed: int | None = None,
    split: bool = True,
) -> ImportSummary:
    """Parse, archive and record one export. Raises `FactoryValidationError`, writing nothing."""
    issues = _collection_issues(collection)
    parsed = _parse(format, path, issues)
    if issues or parsed is None:
        raise FactoryValidationError(issues)

    with project.index.exclusive():
        project.index.sync()
        file_hash = _archive(project, path, parsed)
        for content in parsed.attachment_bytes.values():
            project.library.put(content)
        records: list[JsonValue] = [r.model_dump(mode="json") for r in parsed.records]
        records_blob = project.blobs.put_json(records)
        counts = {outcome: 0 for outcome in ParseOutcome}
        for record in parsed.records:
            counts[record.outcome] += 1
        attached = [r.attachment for r in parsed.records if r.attachment is not None]
        import_id = project.ids.new("imp")
        payload = ImportRecorded(
            import_id=import_id,
            format=format,
            role=role,
            collection=collection,
            parser=parsed.parser,
            parser_version=parsed.parser_version,
            file_hash=file_hash,
            records_blob=records_blob,
            counts=counts,
            attachments=len(attached),
            attachments_missing=sum(1 for a in attached if a.content_sha256 is None),
        )
        project.record(
            [project.events.make(_RECORDED, payload, project.human_actor(), refs=(import_id,))]
        )
    return ImportSummary(
        import_id=import_id,
        counts=counts,
        attachments=payload.attachments,
        attachments_missing=payload.attachments_missing,
        split="declined",
    )


def import_records(project: Project, import_id: str) -> list[ImportRecord]:
    """Every record of an import, in ordinal order, read from its records blob."""
    payload = _recorded(project, import_id)
    raw = project.blobs.get_json(payload.records_blob)
    assert isinstance(raw, list)
    return [ImportRecord.model_validate(item) for item in raw]


def _recorded(project: Project, import_id: str) -> ImportRecorded:
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type == _RECORDED and event.refs == (import_id,):
            return ImportRecorded.model_validate(event.payload)
    raise FactoryValidationError([ValidationIssue("import_id", "no such import")])


def _collection_issues(collection: str | None) -> list[ValidationIssue]:
    if collection is None:
        return []
    if not collection.strip():
        return [ValidationIssue("collection", "must not be blank")]
    if len(collection) > MAX_COLLECTION:
        return [ValidationIssue("collection", f"must be at most {MAX_COLLECTION} characters")]
    return []


def _parse(format: ImportFormat, path: Path, issues: list[ValidationIssue]) -> ParsedImport | None:
    exists = path.is_dir() if format is ImportFormat.PDFS else path.is_file()
    if not exists:
        kind = "a directory" if format is ImportFormat.PDFS else "a readable file"
        issues.append(ValidationIssue("path", f"not {kind}"))
        return None
    try:
        return parse(format, path)
    except ImportFormatError as exc:
        issues.append(ValidationIssue("path", f"not {format.value}: {exc}"))
    except OSError as exc:
        issues.append(ValidationIssue("path", f"unreadable: {exc.strerror or exc}"))
    return None


def _archive(project: Project, path: Path, parsed: ParsedImport) -> str:
    """Put the export into the library verbatim; for a PDF folder, the manifest of its files.

    The manifest is the canonical JSON list of `[path_sha256, record_sha256]` per record, in
    ordinal order (`path_sha256` is null for a file that is not a PDF).
    """
    if parsed.format is not ImportFormat.PDFS:
        return project.library.put(path.read_bytes())
    manifest: list[JsonValue] = [
        [r.attachment.path_sha256 if r.attachment else None, r.record_sha256]
        for r in parsed.records
    ]
    return project.library.put_json(manifest)
