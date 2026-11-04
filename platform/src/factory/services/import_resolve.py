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

import json
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.imports.model import ImportFormat, ParseOutcome
from factory.model.base import StrictModel
from factory.model.imports import ImportResolutionDecided, ImportResolved
from factory.model.references import (
    BINDING_DECISIONS,
    MAX_QUOTE,
    MAX_RATIONALE,
    ConfirmedBy,
    Decision,
    LinkState,
)
from factory.references.match import MATCHER, MATCHER_VERSION
from factory.services.context import Project
from factory.services.imports import import_records, import_row, record_key
from factory.services.reference_resolve import _rigor_mode, confirmer_ruling, resolve_entries
from factory.services.search import get_work
from factory.sources.registry import SourceFactory

_RESOLVED = "import.resolved"
_DECIDED = "import.resolution_decided"
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


# --- Decisions on fuzzy and ambiguous matches ---


@dataclass(frozen=True)
class _Link:
    base_state: LinkState
    base_work_id: str | None
    candidates: tuple[str, ...]
    confirmed_by: str | None


def _link(project: Project, import_id: str, ordinal: int) -> _Link | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT base_state, base_work_id, candidates, confirmed_by FROM import_records "
                "WHERE import_id = :i AND ordinal = :o AND base_state IS NOT NULL"
            ),
            {"i": import_id, "o": ordinal},
        ).first()
    if row is None:
        return None
    listed = tuple(str(c["work_id"]) for c in json.loads(str(row[2] or "[]")))
    return _Link(
        base_state=LinkState(str(row[0])),
        base_work_id=None if row[1] is None else str(row[1]),
        candidates=listed,
        confirmed_by=None if row[3] is None else str(row[3]),
    )


def _identity_case(project: Project, import_id: str, ordinal: int, link: _Link) -> bool:
    """Whether the decision vouches for a file's identity: a PDF-folder record that resolved to a
    work (by identifier) and carries its file. Such a record's `confirm` is what lets
    `attach_import` attach a file whose first page does not show the work's title; only a human
    can give it (a second agent decides `unconfirmed` records only)."""
    if link.base_state is not LinkState.RESOLVED or link.base_work_id is None:
        return False
    if import_row(project, import_id).format is not ImportFormat.PDFS:
        return False
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM import_records WHERE import_id = :i AND ordinal = :o "
                "AND attachment_content_sha256 IS NOT NULL"
            ),
            {"i": import_id, "o": ordinal},
        ).first()
    return row is not None


def _has_proposal(project: Project, import_id: str, ordinal: int) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM import_decisions WHERE import_id = :i AND ordinal = :o "
                "AND kind = 'proposal'"
            ),
            {"i": import_id, "o": ordinal},
        ).first()
    return row is not None


def _barred_sessions(project: Project, import_id: str, ordinal: int) -> set[str]:
    """Sessions that proposed or decided on the record, and agent sessions that resolved the
    import (a second agent is unrelated to both)."""
    key = json.dumps(record_key(import_id, ordinal))
    with project.index.connect() as conn:
        decided = conn.execute(
            text("SELECT session FROM events WHERE type = :t AND instr(refs, :key) > 0"),
            {"t": _DECIDED, "key": key},
        ).all()
        resolved = conn.execute(
            text(
                "SELECT session FROM events WHERE type = :t AND actor_kind = 'agent' "
                "AND instr(refs, :key) > 0"
            ),
            {"t": _RESOLVED, "key": json.dumps(import_id)},
        ).all()
    return {str(r[0]) for r in (*decided, *resolved)}


def decide_import(
    project: Project,
    actor: Actor,
    import_id: str,
    ordinal: int,
    decision: Decision,
    *,
    rationale: str,
    work_id: str | None = None,
) -> None:
    """Record one decision on an import record's match. Writes nothing when invalid.

    The record's recorded state is `unconfirmed` or `ambiguous`. `work_id` defaults to the
    match's own work for an `unconfirmed` record; an `ambiguous` record's confirmation names one
    of its candidates. A binding decision (`confirm`, `reject`) comes from a human or, in `pilot`
    mode, from a second agent under the slice-3a policy (`confirmer_ruling`); the quotes are the
    record's title and the candidate's title, read from the record and the stored work.
    """
    # Gate import.resolution_confirm (slice M declares it; preset as reference.link_confirm).
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state the reason for the decision"))
        elif len(rationale) > MAX_RATIONALE:
            issues.append(ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters"))
        import_row(project, import_id)
        link = _link(project, import_id, ordinal)
        if link is None:
            issues.append(ValidationIssue("ordinal", "no such resolved record"))
            raise FactoryValidationError(issues)
        identity = _identity_case(project, import_id, ordinal, link)
        if link.base_state not in (LinkState.UNCONFIRMED, LinkState.AMBIGUOUS) and not identity:
            issues.append(
                ValidationIssue(
                    "ordinal",
                    f"the record is {link.base_state.value}; only unconfirmed or ambiguous "
                    "records are decided",
                )
            )
        options = tuple(
            dict.fromkeys(w for w in (link.base_work_id, *link.candidates) if w is not None)
        )
        target = work_id
        if target is None and link.base_state in (LinkState.UNCONFIRMED, LinkState.RESOLVED):
            target = link.base_work_id
        if target is None and decision in (Decision.CONFIRM, Decision.PROPOSE_CONFIRM):
            issues.append(ValidationIssue("work_id", "a confirmation names the work it confirms"))
        if target is not None and target not in options:
            issues.append(ValidationIssue("work_id", f"{target}: not a candidate of this record"))
        confirmed_by: ConfirmedBy | None = None
        if decision in BINDING_DECISIONS:
            has_proposal = _has_proposal(project, import_id, ordinal)
            confirmed_by, refused = confirmer_ruling(
                actor,
                mode=_rigor_mode(project),
                base_state=link.base_state,
                confirmed_by=link.confirmed_by,
                has_proposal=has_proposal,
                deciding_sessions=(
                    _barred_sessions(project, import_id, ordinal) if has_proposal else set()
                ),
            )
            issues += refused
        quoted = target or (options[0] if options else None)
        work = None if quoted is None else get_work(project, quoted)
        record_title = _record_title(project, import_id, ordinal)
        if work is None:
            issues.append(ValidationIssue("work_id", "the candidate work is not stored"))
        if record_title is None and not identity:
            issues.append(ValidationIssue("ordinal", "the record has no title to quote"))
        if issues or work is None:
            raise FactoryValidationError(issues)

        payload = ImportResolutionDecided(
            import_id=import_id,
            ordinal=ordinal,
            decision=decision,
            work_id=target,
            rationale=rationale,
            quotes=((record_title or work.title)[:MAX_QUOTE], work.title[:MAX_QUOTE]),
            confirmed_by=confirmed_by,
        )
        input_blob = (
            project.blobs.put_json(
                {
                    "import_id": import_id,
                    "ordinal": ordinal,
                    "decision": decision.value,
                    "work_id": work_id,
                    "rationale": rationale,
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    _DECIDED,
                    payload,
                    actor,
                    refs=(import_id, record_key(import_id, ordinal)),
                    input_blob=input_blob,
                )
            ]
        )


def _record_title(project: Project, import_id: str, ordinal: int) -> str | None:
    for record in import_records(project, import_id):
        if record.ordinal == ordinal:
            title = record.fields.title if record.fields else None
            return title or None
    return None
