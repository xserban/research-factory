"""Recording an imported library: parse, archive verbatim, split, record (slice 3d rulings 17-23).

`record_import` parses the export with the registry's parser, then, under the index lock, puts the
export (or, for a PDF folder, the manifest of its files) and every readable attachment into the
git-ignored library, the allow-listed records into `blobs/`, and writes `import.recorded` and
`import.split_drawn` in one append, as the researcher.

The split (plan Import-A ruling 5): when no search-purpose run has started yet, the records that
are not malformed are split into development and held-out parts by `draw_split` over
`(record key, year)`, from `random_seed` (default: the clock's microseconds), unless the
researcher declines (`split=False`). After the first search-purpose run there is no split
(`post-search`). Probe, chase and seed runs do not count.

Invariants:
- Invalid input (unreadable path, wrong format, bad collection or seed) raises
  `FactoryValidationError` and writes nothing, not even to the library.
- Nothing but allow-listed fields, hashes and ordinals reaches `blobs/` or the event log; notes,
  `annote` and attachment paths stay in the library copy of the export.
- The same file imported twice gives two imports with the same `file_hash` and `records_blob`.
- `development_ordinals` is the only part list meant for agents; held-out ordinals are read only
  through `import_part`, the researcher's view.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.reader import read_all
from factory.imports.model import (
    ImportFormat,
    ImportFormatError,
    ImportRecord,
    ParsedImport,
    ParseOutcome,
)
from factory.imports.registry import parse
from factory.model.base import StrictModel
from factory.model.imports import (
    MAX_COLLECTION,
    ImportRecorded,
    ImportRole,
    ImportSplitDrawn,
    SplitMode,
)
from factory.model.search import QueryPurpose
from factory.services.context import Project
from factory.services.seeds import draw_split

_RECORDED = "import.recorded"
_SPLIT = "import.split_drawn"
_SEED_LIMIT = 2**32

Part = Literal["development", "held-out", "unsplit"]


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
    """Parse, archive, split and record one export. Raises `FactoryValidationError`, writing
    nothing."""
    issues = _collection_issues(collection)
    if random_seed is not None and not 0 <= random_seed < _SEED_LIMIT:
        issues.append(ValidationIssue("random_seed", "must be an integer from 0 to 2**32 - 1"))
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
        drawn = _split(project, import_id, parsed.records, random_seed=random_seed, split=split)
        actor = project.human_actor()
        project.record(
            [
                project.events.make(_RECORDED, payload, actor, refs=(import_id,)),
                project.events.make(_SPLIT, drawn, actor, refs=(import_id,)),
            ]
        )
    return ImportSummary(
        import_id=import_id,
        counts=counts,
        attachments=payload.attachments,
        attachments_missing=payload.attachments_missing,
        split=drawn.mode,
    )


def import_records(project: Project, import_id: str) -> list[ImportRecord]:
    """Every record of an import, in ordinal order, read from its records blob."""
    payload = ImportRecorded.model_validate(_payload(project, _RECORDED, import_id))
    raw = project.blobs.get_json(payload.records_blob)
    assert isinstance(raw, list)
    return [ImportRecord.model_validate(item) for item in raw]


def import_part(project: Project, import_id: str, ordinal: int) -> Part:
    """The part of one record: `unsplit` when no split was drawn or the record is malformed."""
    parts = _parts(project, import_id)
    if parts is None:
        return "unsplit"
    development, held_out = parts
    if ordinal in development:
        return "development"
    return "held-out" if ordinal in held_out else "unsplit"


def development_ordinals(project: Project, import_id: str) -> list[int]:
    """The ordinals an agent may see: the development part, or every record that is not
    malformed when the import was not split."""
    parts = _parts(project, import_id)
    if parts is not None:
        return sorted(parts[0])
    return [r.ordinal for r in import_records(project, import_id) if _splittable(r)]


def _split(
    project: Project,
    import_id: str,
    records: tuple[ImportRecord, ...],
    *,
    random_seed: int | None,
    split: bool,
) -> ImportSplitDrawn:
    if _search_started(project):
        return ImportSplitDrawn(import_id=import_id, mode="post-search")
    if not split:
        return ImportSplitDrawn(import_id=import_id, mode="declined")
    seed = project.clock.now().microsecond if random_seed is None else random_seed
    keyed = {record_key(import_id, r.ordinal): r for r in records if _splittable(r)}
    development, held_out = draw_split(
        [(key, r.fields.year if r.fields else None) for key, r in keyed.items()], seed
    )
    dev: list[JsonValue] = [o for o in sorted(keyed[k].ordinal for k in development)]
    held: list[JsonValue] = [o for o in sorted(keyed[k].ordinal for k in held_out)]
    parts: JsonValue = {"development": dev, "held_out": held}
    return ImportSplitDrawn(
        import_id=import_id,
        mode="drawn",
        random_seed=seed,
        parts_blob=project.blobs.put_json(parts),
    )


def _splittable(record: ImportRecord) -> bool:
    return record.outcome is not ParseOutcome.MALFORMED


def _search_started(project: Project) -> bool:
    """Whether any run of a search-purpose query has started."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM runs JOIN queries ON queries.query_id = runs.query_id "
                "WHERE queries.purpose = :purpose LIMIT 1"
            ),
            {"purpose": QueryPurpose.SEARCH.value},
        ).first()
    return row is not None


def _parts(project: Project, import_id: str) -> tuple[set[int], set[int]] | None:
    payload = ImportSplitDrawn.model_validate(_payload(project, _SPLIT, import_id))
    if payload.parts_blob is None:
        return None
    raw = project.blobs.get_json(payload.parts_blob)
    assert isinstance(raw, dict)
    development, held_out = raw["development"], raw["held_out"]
    assert isinstance(development, list) and isinstance(held_out, list)
    return {int(str(o)) for o in development}, {int(str(o)) for o in held_out}


def _payload(project: Project, type_: str, import_id: str) -> dict[str, JsonValue]:
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type == type_ and event.refs == (import_id,):
            return dict(event.payload)
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
