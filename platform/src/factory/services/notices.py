"""Notice observation for the works a review depends on (slice 4b, living-C).

For each watch cycle, up to `notice_budget` dependent works are looked up in OpenAlex and Crossref
as STATUS runs of the cycle; each notice the responses state is written once as `notice.observed`
(system actor). Nothing here judges a notice, changes a screening outcome or edits a row: effects
are computed at read time from the observations and the human's assessments.

Invariants:
- Dependents are the works with a final INCLUDED outcome at either stage, plus the works with a
  live extraction row or claim in any scope. Never a scan of the whole corpus beyond the outcome
  read every report already makes.
- Coverage is least-recently-checked first (a work never checked comes first, ties by work id),
  where checked means a complete status run that asked about the work.
- A notice's identity is `(work_id, kind, notice_doi or source)`; a repeat observation writes
  nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import text

from factory.events.envelope import Event
from factory.model.base import StrictModel
from factory.model.notices import NoticeObserved
from factory.model.protocol import ScreeningStage
from factory.model.search import QueryKind, RunStatus
from factory.model.work import Work
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.search import works_by_ids
from factory.services.status_lookup import (
    Resolver,
    StatusBatch,
    StatusOutcome,
    crossref_doi,
    groups,
    last_checked,
    openalex_batches,
    run_batches,
)
from factory.sources.registry import SourceFactory

NOTICE_SOURCES = ("openalex", "crossref")


class NoticeCheckSummary(StrictModel):
    checked: int
    """Selected works covered by at least one complete status run."""
    new_notices: int
    unchecked_crossref: tuple[str, ...]
    """Selected works Crossref cannot be asked about (no DOI of its own)."""
    run_ids: tuple[str, ...]
    work_ids: tuple[str, ...] = ()
    """The works selected for this cycle's lookups, which the version check covers too."""


def dependent_works(project: Project) -> list[str]:
    """The works the review depends on, sorted (ruling 1)."""
    project.index.sync()
    ids: set[str] = set()
    protocol = current_protocol(project)
    stages = [ScreeningStage.TITLE_ABSTRACT]
    if protocol is not None and protocol.spec.full_text_screening is not None:
        stages.append(ScreeningStage.FULL_TEXT)
    for stage in stages:
        ids |= {w for w, o in final_outcomes(project, stage=stage).items() if o is Outcome.INCLUDED}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id FROM extraction_rows WHERE superseded_by IS NULL "
                "UNION SELECT work_id FROM extraction_claims WHERE superseded_by IS NULL"
            )
        ).all()
    ids |= {str(r[0]) for r in rows}
    return sorted(ids)


def notice_check(
    project: Project,
    cycle_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    budget: int,
    notice_sources: Sequence[str] = NOTICE_SOURCES,
) -> NoticeCheckSummary:
    """Look up up to `budget` dependents in the notice sources and record new notices.

    Runs inside the open cycle `cycle_id`. Works with no identifier any source takes are selected
    like the rest but cannot be covered; works without a Crossref DOI are reported in
    `unchecked_crossref`.
    """
    dependents = dependent_works(project)
    checked_at = last_checked(project, dependents)
    selected = sorted(dependents, key=lambda w: (checked_at.get(w, ""), w))[: max(budget, 0)]
    if not selected:
        return NoticeCheckSummary(checked=0, new_notices=0, unchecked_crossref=(), run_ids=())
    works = works_by_ids(project, selected)

    batches: list[StatusBatch] = []
    unchecked: list[str] = []
    if "openalex" in notice_sources:
        batches += openalex_batches(works)
    if "crossref" in notice_sources:
        crossref_batches, unchecked = _crossref_batches(works)
        batches += crossref_batches

    outcomes = run_batches(project, cycle_id, sources, batches)
    covered = {w for o in outcomes if o.status is RunStatus.COMPLETE for w in o.batch.work_ids}
    resolver = Resolver(works)
    events = _observation_events(project, outcomes, resolver)
    if events:
        project.record(events)
    return NoticeCheckSummary(
        checked=len(covered),
        new_notices=len(events),
        unchecked_crossref=tuple(sorted(unchecked)),
        run_ids=tuple(o.run_id for o in outcomes),
        work_ids=tuple(selected),
    )


def _crossref_batches(works: Sequence[Work]) -> tuple[list[StatusBatch], list[str]]:
    pairs: list[tuple[str, str]] = []
    unchecked: list[str] = []
    for work in works:
        doi = crossref_doi(work)
        if doi is None:
            unchecked.append(work.id)
        else:
            pairs.append((work.id, doi))
    batches = [
        StatusBatch(
            source="crossref",
            kind=QueryKind.FILTER,
            # Repeated `updates:` filters are OR-ed (observed live, tests/test_living_network.py).
            text=",".join(f"updates:{doi}" for _, doi in group),
            work_ids=tuple(work_id for work_id, _ in group),
        )
        for group in groups(pairs)
    ]
    return batches, unchecked


def _known_identities(project: Project) -> set[tuple[str, str, str]]:
    project.index.sync()
    with project.index.connect() as conn:
        return {
            (str(w), str(k), str(i))
            for w, k, i in conn.execute(text("SELECT work_id, kind, identity FROM notices"))
        }


def _observation_events(
    project: Project, outcomes: Sequence[StatusOutcome], resolver: Resolver
) -> list[Event]:
    """One `notice.observed` per notice identity not yet on the log, in lookup order."""
    seen = _known_identities(project)
    events: list[Event] = []
    for outcome in outcomes:
        if outcome.raw_blob is None:
            continue
        for record in outcome.records:
            if record.kind != "notice" or record.notice_kind is None:
                continue
            work_id = resolver.work_for(record.target)
            if work_id is None:
                continue
            payload = NoticeObserved(
                notice_id=project.ids.new("ntc"),
                work_id=work_id,
                kind=record.notice_kind,
                notice_date=record.notice_date,
                notice_doi=record.notice_doi,
                source=outcome.batch.source,
                run_id=outcome.run_id,
                raw_blob=outcome.raw_blob,
            )
            identity = (work_id, payload.kind.value, payload.identity)
            if identity in seen:
                continue
            seen.add(identity)
            events.append(
                project.events.make(
                    "notice.observed",
                    payload,
                    project.system_actor(),
                    refs=(payload.notice_id, work_id, outcome.run_id),
                )
            )
    return events
