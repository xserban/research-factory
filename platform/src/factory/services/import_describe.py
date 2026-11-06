"""The researcher's description of an import record (PD-2, decision 120 provisional).

A PDF with no usable metadata has nothing a resolver can read, and only the researcher can say what
it is: a script guessing a title from the first page would be an identity claim nobody made.
`describe_record` writes `import.record_described`, an overlay of allow-listed fields over the
stored record. The record, its hash, its outcome and its part never change (R-03, ruling 23);
`effective_records` is what the resolver and the admission read. After a description the record
waits for `import resolve --described`, and admission refuses until it has run.

Invariants:
- A human act: an agent actor is refused here and the fold ignores its event.
- Refused, writing nothing: a malformed record, a record an admission plan already names, and a
  description that changes nothing. The fold repeats the guards it can see.
- Each event holds the whole overlay: a later description merges the earlier one, then the latest
  event wins, so no field is lost by describing another.
- `describe_records` reads the CSV and never archives it; each row is applied or reported alone.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import ValidationError

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.imports.model import ImportFields, ImportRecord, ParseOutcome
from factory.model.base import StrictModel
from factory.model.imports import (
    DESCRIBED_FIELDS,
    ImportRecordDescribed,
    RecordDescription,
)
from factory.model.references import MAX_RATIONALE
from factory.model.work_ids import normalize_arxiv, normalize_doi
from factory.services.context import Project
from factory.services.imports import (
    admission_names,
    effective_records,
    import_row,
    record_key,
    stored_description,
)

_DESCRIBED = "import.record_described"
_CSV_COLUMNS = frozenset({"ordinal", "title", "authors", "year", "doi", "arxiv", "venue"})
_AUTHOR_SEPARATOR = ";"


class RowProblem(StrictModel):
    """A CSV row that was not applied: its line number and why."""

    line: int
    reasons: list[str]


class DescribeSummary(StrictModel):
    """What a CSV did: how many rows were applied, and each row that was not."""

    described: int
    rejected: list[RowProblem]


def parse_description(raw: Mapping[str, object]) -> RecordDescription:
    """A description from raw fields, identifiers normalised. Blank values are absent. Raises
    `FactoryValidationError` naming each field out of bounds."""
    values = {k: v for k, v in raw.items() if v not in (None, "", [], ())}
    if isinstance(values.get("doi"), str):
        values["doi"] = normalize_doi(str(values["doi"]))
    if isinstance(values.get("arxiv"), str):
        values["arxiv"] = normalize_arxiv(str(values["arxiv"]))
    try:
        return RecordDescription.model_validate(values)
    except ValidationError as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(".".join(str(p) for p in error["loc"]) or "fields", error["msg"])
                for error in exc.errors()
            ]
        ) from exc


def describe_record(
    project: Project,
    actor: Actor,
    import_id: str,
    ordinal: int,
    description: RecordDescription,
    *,
    rationale: str,
) -> None:
    """Record the researcher's description of one record; see the module invariants. Raises
    `FactoryValidationError` with every issue at once, writing nothing."""
    with project.index.exclusive():
        project.index.sync()
        import_row(project, import_id)
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "only the researcher describes a record"))
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state the reason for the description"))
        elif len(rationale) > MAX_RATIONALE:
            issues.append(ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters"))
        record = next(
            (r for r in effective_records(project, import_id) if r.ordinal == ordinal), None
        )
        if record is None:
            issues.append(ValidationIssue("ordinal", "no such record"))
        else:
            issues += _record_issues(project, import_id, record, description)
        if issues:
            raise FactoryValidationError(issues)
        stated = description.model_dump(mode="json", exclude_none=True)
        if not description.authors:
            stated.pop("authors")
        merged = {**stored_description(project, import_id, ordinal), **stated}
        payload = ImportRecordDescribed.model_validate(
            {"import_id": import_id, "ordinal": ordinal, "rationale": rationale, **merged}
        )
        project.record(
            [
                project.events.make(
                    _DESCRIBED, payload, actor, refs=(import_id, record_key(import_id, ordinal))
                )
            ]
        )


def describe_records(
    project: Project, actor: Actor, import_id: str, path: Path, *, rationale: str
) -> DescribeSummary:
    """Apply a CSV of `ordinal,title,authors,year,doi,arxiv,venue` (a header names the columns it
    uses; authors are separated by `;`). A bad row is reported and the others are applied. Raises
    `FactoryValidationError`, writing nothing, when the file cannot be read as such a CSV."""
    import_row(project, import_id)
    rows = _csv_rows(path)
    described = 0
    rejected: list[RowProblem] = []
    for line, row in rows:
        try:
            ordinal, raw = _row_fields(row)
            describe_record(
                project, actor, import_id, ordinal, parse_description(raw), rationale=rationale
            )
        except FactoryValidationError as exc:
            reasons = [f"{issue.field}: {issue.reason}" for issue in exc.issues]
            rejected.append(RowProblem(line=line, reasons=reasons))
        else:
            described += 1
    return DescribeSummary(described=described, rejected=rejected)


def _record_issues(
    project: Project, import_id: str, record: ImportRecord, description: RecordDescription
) -> list[ValidationIssue]:
    if record.outcome is ParseOutcome.MALFORMED or record.fields is None:
        return [ValidationIssue("ordinal", "the record is malformed: its file is not a PDF")]
    if admission_names(project, import_id, record.ordinal):
        return [ValidationIssue("ordinal", "an admission already names this record")]
    if not _changes(record.fields, description):
        return [ValidationIssue("fields", "the description changes nothing")]
    return []


def _changes(fields: ImportFields, description: RecordDescription) -> bool:
    for name in DESCRIBED_FIELDS:
        value = getattr(description, name)
        if value in (None, ()):
            continue
        current = getattr(fields, name)
        if (list(value) if name == "authors" else value) != current:
            return True
    return False


def _csv_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            unknown = sorted(columns - _CSV_COLUMNS)
            if unknown or "ordinal" not in columns:
                wanted = ", ".join(sorted(_CSV_COLUMNS))
                raise FactoryValidationError(
                    [ValidationIssue("csv", f"a header with ordinal, from: {wanted}")]
                )
            return [(reader.line_num, _plain(row)) for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise FactoryValidationError([ValidationIssue("csv", "not a readable CSV")]) from exc


def _plain(row: Mapping[str | None, object]) -> dict[str, str]:
    """A row's named cells, stripped; a surplus cell (key None) is dropped by the header check."""
    return {k: v.strip() for k, v in row.items() if k is not None and isinstance(v, str)}


def _row_fields(row: Mapping[str, str]) -> tuple[int, dict[str, object]]:
    raw: dict[str, object] = {k: v for k, v in row.items() if k != "ordinal"}
    if raw.get("authors"):
        raw["authors"] = _authors(str(raw["authors"]).split(_AUTHOR_SEPARATOR))
    if raw.get("year"):
        raw["year"] = _integer("year", str(raw["year"]))
    return _integer("ordinal", row.get("ordinal", "")), raw


def _authors(names: Iterable[str]) -> list[str]:
    return [name.strip() for name in names if name.strip()]


def _integer(field: str, value: str) -> int:
    if not value.isascii() or not value.isdigit() or len(value) > 9:
        raise FactoryValidationError([ValidationIssue(field, "must be a whole number")])
    return int(value)
