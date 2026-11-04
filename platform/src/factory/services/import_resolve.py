"""Resolution of import records to work identities with the slice-3a resolver (plan Import-B).

`resolve_import` adapts the parsed records of an import to `resolve_entries` (the same ordered
methods and thresholds as a reference list, spec ruling 21) and records one `import.resolved`
event. Lookups are probe-purpose queries, recorded as searches and outside the corpus; nothing
enters the corpus here.

Invariants:
- Only records that parsed (`parsed`, `no-title-no-identifier`) are resolved; a record with
  neither title nor identifier is `unresolved`, listed, never dropped.
- The same fields as a `ReferenceEntry` and as an `ImportResolvable` resolve identically.
- A later `import.resolved` supersedes the earlier one for the import, decisions included.
- Counts are computed from the resolutions, never supplied. Summaries carry counts only; no
  ordinal or held-out membership appears in them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.imports.model import ParseOutcome
from factory.model.base import StrictModel
from factory.model.imports import ImportResolved
from factory.model.references import LinkState
from factory.references.match import MATCHER, MATCHER_VERSION
from factory.services.context import Project
from factory.services.imports import import_records, import_row
from factory.services.reference_resolve import resolve_entries
from factory.sources.registry import SourceFactory

_RESOLVED = "import.resolved"
_RESOLVABLE = (ParseOutcome.PARSED, ParseOutcome.NO_TITLE_NO_IDENTIFIER)


@dataclass(frozen=True)
class ImportResolvable:
    """One import record as the resolver reads it (`Resolvable`); `first_author` is a surname."""

    ordinal: int
    doi: str | None
    arxiv: str | None
    url: str | None
    year: int | None
    first_author: str | None
    title: str | None
    venue: str | None


class ImportResolutionSummary(StrictModel):
    import_id: str
    counts: dict[LinkState, int]
    lookup_runs: tuple[str, ...]


def surname(author: str) -> str:
    """The surname of a display name: before the comma of `Last, First`, else the last token."""
    name = author.strip()
    if "," in name:
        return name.split(",", 1)[0].strip()
    parts = name.split()
    return parts[-1] if parts else ""


def resolvables(project: Project, import_id: str) -> list[ImportResolvable]:
    """The records of an import the resolver reads, in ordinal order."""
    out: list[ImportResolvable] = []
    for record in import_records(project, import_id):
        f = record.fields
        if record.outcome not in _RESOLVABLE or f is None:
            continue
        out.append(
            ImportResolvable(
                ordinal=record.ordinal,
                doi=f.doi,
                arxiv=f.arxiv,
                url=f.url,
                year=f.year,
                first_author=(surname(f.authors[0]) or None) if f.authors else None,
                title=f.title,
                venue=f.venue,
            )
        )
    return out


def resolve_import(
    project: Project,
    import_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    actor: Actor | None = None,
) -> ImportResolutionSummary:
    """Resolve every resolvable record of the import and record `import.resolved`.

    `actor` defaults to the researcher. Raises `FactoryValidationError` for an unknown import,
    writing nothing.
    """
    import_row(project, import_id)
    who = actor or project.human_actor()
    outcome = resolve_entries(project, who, resolvables(project, import_id), sources=sources)
    payload = ImportResolved(
        import_id=import_id,
        resolutions=outcome.resolutions,
        lookup_runs=outcome.lookup_runs,
        matcher=MATCHER,
        matcher_version=MATCHER_VERSION,
    )
    input_blob = project.blobs.put_json({"import_id": import_id}) if who.kind == "agent" else None
    project.record(
        [project.events.make(_RESOLVED, payload, who, refs=(import_id,), input_blob=input_blob)]
    )
    counts = {state: 0 for state in LinkState}
    for r in outcome.resolutions:
        counts[r.state] += 1
    return ImportResolutionSummary(
        import_id=import_id, counts=counts, lookup_runs=outcome.lookup_runs
    )


def record_states(project: Project, import_id: str) -> dict[int, LinkState]:
    """The live link state per resolved ordinal (decisions folded in); unresolved-yet records
    are absent."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ordinal, link_state FROM import_records "
                "WHERE import_id = :i AND link_state IS NOT NULL ORDER BY ordinal"
            ),
            {"i": import_id},
        ).all()
    return {int(o): LinkState(str(s)) for o, s in rows}
