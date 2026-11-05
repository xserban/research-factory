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

import json
from collections.abc import Mapping, Sequence
from datetime import date

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.notices import (
    AssessmentDecision,
    NoticeAssessed,
    NoticeKind,
    NoticeObserved,
    WorkNoticeState,
    notice_state,
)
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel
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
    effective_last_checked,
    groups,
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
    failed: int = 0
    """Lookups that did not complete. Each is a failed run on the log; `check` reports it until a
    later complete run of the same source covers the works it asked about."""


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
    known = works_by_ids(project, dependents)
    checked_at = effective_last_checked(project, known, notice_sources)
    # Never checked first (""), then least recently checked; a work no source can be asked about
    # (None) is left to the end. Ties by work id.
    order = sorted(known, key=lambda w: (checked_at[w.id] is None, checked_at[w.id] or "", w.id))
    works = order[: max(budget, 0)]
    selected = [w.id for w in works]
    if not selected:
        return NoticeCheckSummary(checked=0, new_notices=0, unchecked_crossref=(), run_ids=())

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
    with project.writing():
        events = _observation_events(project, outcomes, resolver)
        if events:
            project.record(events)
    return NoticeCheckSummary(
        checked=len(covered),
        new_notices=len(events),
        unchecked_crossref=tuple(sorted(unchecked)),
        run_ids=tuple(o.run_id for o in outcomes),
        work_ids=tuple(selected),
        failed=sum(1 for o in outcomes if o.status is not RunStatus.COMPLETE),
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


# --- reads ---


def observed_notices(project: Project) -> list[NoticeObserved]:
    """Every observed notice, in observation order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT notice_id, work_id, kind, notice_date, notice_doi, source, run_id, "
                "raw_blob FROM notices ORDER BY event_id"
            )
        ).all()
    return [
        NoticeObserved(
            notice_id=str(n),
            work_id=str(w),
            kind=NoticeKind(str(k)),
            notice_date=None if d is None else date.fromisoformat(str(d)),
            notice_doi=None if doi is None else str(doi),
            source=str(src),
            run_id=str(run),
            raw_blob=str(blob),
        )
        for n, w, k, d, doi, src, run, blob in rows
    ]


def assessments(project: Project) -> list[tuple[str, NoticeAssessed]]:
    """Every assessment as (event id, payload), in recording order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event_id, notice_id, decision, fields, rationale, channel "
                "FROM notice_assessments "
                "ORDER BY event_id"
            )
        ).all()
    return [
        (
            str(event_id),
            NoticeAssessed(
                notice_id=str(notice),
                decision=AssessmentDecision(str(decision)),
                fields=tuple(json.loads(str(fields))),
                rationale=str(rationale),
                channel=Channel(str(channel)),
            ),
        )
        for event_id, notice, decision, fields, rationale, channel in rows
    ]


class NoticeView(StrictModel):
    """A notice as a list shows it: what was observed and the latest assessment, if any."""

    notice_id: str
    work_id: str
    kind: NoticeKind
    notice_date: date | None
    notice_doi: str | None
    source: str
    assessment: AssessmentDecision | None
    fields: tuple[str, ...]
    flag: str
    """The work's computed notice flag (`retracted`, `correction-pending`, `concern`, `none`)."""
    synthesis: str
    """What the synthesis does with the work's rows: `excluded`, `labelled` or `normal`."""
    rows: int
    """Live extraction rows of the work that the notice puts in doubt or labels."""
    claims: int


def notice_views(project: Project) -> list[NoticeView]:
    """Observed notices with their latest assessment. A seed's work is listed like any work: the
    evidence report shows it, so a list that left it out would single it out (decision 43)."""
    assessed = current_assessments(project)
    states = work_states(project)
    counts = _live_counts(project, {n.work_id for n in observed_notices(project)})
    views: list[NoticeView] = []
    for notice in observed_notices(project):
        current = assessed.get(notice.notice_id)
        state = states[notice.work_id]
        rows, claims = counts.get(notice.work_id, (0, 0))
        views.append(
            NoticeView(
                notice_id=notice.notice_id,
                work_id=notice.work_id,
                kind=notice.kind,
                notice_date=notice.notice_date,
                notice_doi=notice.notice_doi,
                source=notice.source,
                assessment=None if current is None else current[1].decision,
                fields=() if current is None else current[1].fields,
                flag=state.flag,
                synthesis=state.synthesis,
                rows=rows,
                claims=claims,
            )
        )
    return views


def _live_counts(project: Project, work_ids: set[str]) -> dict[str, tuple[int, int]]:
    """Live extraction rows and claims per work, for the works given: indexed by work id."""
    if not work_ids:
        return {}
    found: dict[str, list[int]] = {w: [0, 0] for w in work_ids}
    with project.index.connect() as conn:
        for index, table in enumerate(("extraction_rows", "extraction_claims")):
            for work_id, count in conn.execute(
                text(
                    f"SELECT work_id, COUNT(*) FROM {table} "
                    "WHERE superseded_by IS NULL GROUP BY work_id"
                )
            ):
                if str(work_id) in found:
                    found[str(work_id)][index] = int(count)
    return {w: (c[0], c[1]) for w, c in found.items()}


def current_assessments(project: Project) -> dict[str, tuple[str, NoticeAssessed]]:
    """The latest assessment of each assessed notice, by notice id, as (event id, payload)."""
    return {a.notice_id: (event_id, a) for event_id, a in assessments(project)}


def work_states(project: Project) -> dict[str, WorkNoticeState]:
    """The read-time state of every work with a notice (`model.notices.notice_state`). Read from
    the observations and assessments only; nothing derived is stored."""
    return notice_state(observed_notices(project), assessments(project))


def declared_fields(project: Project) -> frozenset[str]:
    """The fields of the protocol's declared schemas, evidence and contribution."""
    protocol = current_protocol(project)
    if protocol is None:
        return frozenset()
    names: set[str] = set()
    for schema in (protocol.spec.extraction_schema, protocol.spec.contribution_schema):
        if schema is not None:
            names.update(schema.fields)
    return frozenset(names)


# --- the human's act ---

_CORRECTION_DECISIONS = frozenset({AssessmentDecision.AFFECTS, AssessmentDecision.NO_EFFECT})


def assess_notice(
    project: Project,
    actor: Actor,
    notice_id: str,
    decision: AssessmentDecision,
    *,
    fields: Sequence[str] = (),
    rationale: str,
    channel: Channel = Channel.CLI,
) -> str:
    """Record a human's assessment of a notice; a later one supersedes it. Returns the event id.

    Refused, writing nothing, for an actor that is not a human (gate living.notice_assess, floor
    human), an unknown notice, a reinstatement (no assessment is needed), a decision that does not
    answer the notice's kind, `fields` that are not exactly the named fields of a declared schema
    for `affects`, or a blank rationale. Gate: living.notice_assess.
    """
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "a notice is assessed by a human"))
        notice = next((n for n in observed_notices(project) if n.notice_id == notice_id), None)
        if notice is None:
            issues.append(ValidationIssue("notice_id", f"{notice_id}: unknown notice"))
        elif notice.kind is NoticeKind.REINSTATEMENT:
            issues.append(ValidationIssue("notice_id", "a reinstatement needs no assessment"))
        elif (notice.kind is NoticeKind.CORRECTION) != (decision in _CORRECTION_DECISIONS):
            answers = (
                "affects or no-effect"
                if notice.kind is NoticeKind.CORRECTION
                else ("exclude or keep-flagged")
            )
            issues.append(
                ValidationIssue("decision", f"a {notice.kind.value} is answered by {answers}")
            )
        if decision is AssessmentDecision.AFFECTS and not fields:
            issues.append(ValidationIssue("fields", "name the fields the correction affects"))
        elif decision is not AssessmentDecision.AFFECTS and fields:
            issues.append(ValidationIssue("fields", "fields belong to an affects decision"))
        unknown = sorted(set(fields) - declared_fields(project))
        if unknown:
            issues.append(
                ValidationIssue("fields", f"not fields of a declared schema: {', '.join(unknown)}")
            )
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "a rationale is required"))
        if issues or notice is None:
            raise FactoryValidationError(issues)
        payload = NoticeAssessed(
            notice_id=notice_id,
            decision=decision,
            fields=tuple(fields),
            rationale=rationale,
            channel=channel,
        )
        event = project.events.make(
            "notice.assessed", payload, actor, refs=(notice_id, notice.work_id)
        )
        project.record([event])
        return event.id
