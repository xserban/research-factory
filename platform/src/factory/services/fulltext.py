"""Fetching full text for promoted works: the gate, route order, version rule and changed sources.

`fetch_fulltext` fetches full text for every work that the title/abstract screening promoted
(`final_outcomes` gives `Outcome.INCLUDED`). The caller supplies the routes; this module never
builds them. Routes are tried in `ROUTE_ORDER`, and without `only` the run stops at the first
retrieved attempt. `only` tries exactly the named routes and does not stop on success.

Invariants:
- Validation is complete before anything is written. A refused request writes nothing.
- `fulltext.fetch_started` is recorded first, by the triggering actor. An agent's trigger carries an
  `input_blob`, the request as the agent stated it, unless the caller supplies one.
- Each work's attempts, documents and source changes are recorded in one `project.record` call, so
  an interrupted call leaves whole works.
- Content goes to the project library, metadata to `blobs/`, and every URL is redacted before it
  reaches an event. The contact address (`mailto`) never reaches an event.
- A retrieved result needs content, a non-blank source version and a non-blank media type. Any of
  them missing is a failed attempt, with a fixed reason and no document.
- Version rule: (work, route, source_version) identifies a document. The same hash adds no document.
  A different hash records `fulltext.source_changed` and keeps the new bytes. A new version on a
  route with a live document is a new document that supersedes it.
- "Latest" means latest in event order (the event id), never by timestamp text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.fulltext import (
    QUALITY,
    ROUTE_ORDER,
    Attempted,
    AttemptOutcome,
    DocumentAdded,
    FetchStarted,
    LicenceStatus,
    Route,
    SourceChanged,
)
from factory.model.identity import BLOB_REF_RE
from factory.model.work import Work
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.search import list_works
from factory.sources.fulltext.base import FullTextRoute, RouteResult
from factory.sources.http import redact

MIN_LIMIT = 1
MAX_LIMIT = 200
_NOT_RETRIEVED = (AttemptOutcome.NOT_AVAILABLE, AttemptOutcome.FAILED)
_UNSPECIFIED = "unspecified"

Status = Literal["retrieved", "not-retrieved", "already-retrieved", "source-changed"]


class WorkFetch(StrictModel):
    """What one call did for one work. `documents` are the documents this call added."""

    work_id: str
    attempts: list[str]
    documents: list[str]
    status: Status


class FetchSummary(StrictModel):
    """What one `fetch_fulltext` call did. `remaining` counts promoted works with no document."""

    fetch_id: str
    works: list[WorkFetch]
    remaining: int


@dataclass(frozen=True)
class _Document:
    """A document as the projection holds it, in event order."""

    document_id: str
    route: str
    source_version: str
    raw_hash: str
    superseded: bool


@dataclass(frozen=True)
class _Content:
    """Bytes a route retrieved, already in the library, with the values a document needs."""

    raw_hash: str
    source_version: str
    media_type: str


@dataclass(frozen=True)
class _Fetched:
    """One route's answer after the service's own checks. `content` is set exactly when the
    outcome is retrieved."""

    route: Route
    outcome: AttemptOutcome
    reason: str | None
    url: str | None
    http_status: int | None
    source_version: str | None
    media_type: str | None
    licence: str | None
    metadata_blob: str | None
    content: _Content | None


def fetch_fulltext(
    project: Project,
    *,
    routes: Mapping[Route, FullTextRoute],
    work_ids: Sequence[str] | None = None,
    only: Sequence[Route] | None = None,
    refresh: bool = False,
    limit: int = 20,
    actor: Actor | None = None,
    input_blob: str | None = None,
) -> FetchSummary:
    """Fetch full text for promoted works and record every attempt.

    `work_ids=None` selects promoted works without a document, sorted by id. With `refresh` or
    `only`, every promoted work is selected. An explicit work that already has a document is
    `already-retrieved` with no attempt, unless `refresh` or `only` is given. At most `limit` works
    are processed; `remaining` counts the promoted works still without a document afterwards.

    Raises `FactoryValidationError` with nothing written if a work is not promoted, `only` names
    `researcher-supplied` or a route not supplied, `limit` is outside 1..200, or `input_blob` is not
    a stored blob. A route's failure is an attempt outcome, never an exception.
    """
    trigger = actor or project.system_actor()
    revisit = refresh or only is not None
    with project.index.exclusive():
        project.index.sync()
        corpus = {work.id: work for work in list_works(project)}
        promoted = _promoted(project)
        candidates = _candidates(routes, only)
        issues = _request_issues(project, promoted, routes, work_ids, only, limit, input_blob)
        if issues:
            raise FactoryValidationError(issues)
        targets = _targets(project, promoted, work_ids, revisit, limit)
        fetch_id = project.ids.new("fch")
        request = _request(work_ids, only, refresh, limit)
        blob = input_blob if input_blob is not None else _trigger_blob(project, trigger, request)
        started = FetchStarted(
            fetch_id=fetch_id,
            work_ids=targets,
            routes=None if only is None else [r for r in ROUTE_ORDER if r in only],
            refresh=refresh,
        )
        project.record(
            [
                project.events.make(
                    "fulltext.fetch_started",
                    started,
                    trigger,
                    refs=(fetch_id,),
                    input_blob=blob,
                )
            ]
        )

    works = [
        _fetch_work(project, fetch_id, corpus[work_id], routes, candidates, only, revisit)
        for work_id in targets
    ]

    with project.index.exclusive():
        project.index.sync()
        documented = _documented_works(project)
    remaining = len(promoted - documented)
    return FetchSummary(fetch_id=fetch_id, works=works, remaining=remaining)


# --- Validation and selection (under the write lock, before any write) ---


def _promoted(project: Project) -> frozenset[str]:
    """The works title/abstract screening promoted: the corpus's `INCLUDED` outcomes."""
    return frozenset(
        work for work, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _candidates(routes: Mapping[Route, FullTextRoute], only: Sequence[Route] | None) -> list[Route]:
    """The routes to try, in canonical order: the named ones, or every supplied automatic route."""
    return [r for r in ROUTE_ORDER if r in routes and (only is None or r in only)]


def _request_issues(
    project: Project,
    promoted: frozenset[str],
    routes: Mapping[Route, FullTextRoute],
    work_ids: Sequence[str] | None,
    only: Sequence[Route] | None,
    limit: int,
    input_blob: str | None,
) -> list[ValidationIssue]:
    """Every problem with the request, reported together so one call shows them all."""
    issues: list[ValidationIssue] = []
    if not MIN_LIMIT <= limit <= MAX_LIMIT:
        issues.append(ValidationIssue("limit", f"must be between {MIN_LIMIT} and {MAX_LIMIT}"))
    if only is not None:
        if not only:
            issues.append(ValidationIssue("only", "name at least one route"))
        if Route.RESEARCHER in only:
            issues.append(
                ValidationIssue("only", "a researcher-supplied route is imported, not fetched")
            )
        for route in only:
            if route is not Route.RESEARCHER and route not in routes:
                issues.append(ValidationIssue("only", f"no route supplied for {route.value}"))
    elif not _candidates(routes, only):
        issues.append(ValidationIssue("routes", "no automatic route supplied"))
    if work_ids is not None:
        for work_id in sorted(set(work_ids)):
            if work_id not in promoted:
                issues.append(
                    ValidationIssue("work_ids", f"{work_id}: not promoted at title/abstract")
                )
    if input_blob is not None:
        if not re.fullmatch(BLOB_REF_RE, input_blob):
            issues.append(ValidationIssue("input_blob", "not a blob reference"))
        elif not project.blobs.exists(input_blob):
            issues.append(ValidationIssue("input_blob", "no such blob"))
    return issues


def _targets(
    project: Project,
    promoted: frozenset[str],
    work_ids: Sequence[str] | None,
    revisit: bool,
    limit: int,
) -> list[str]:
    """The works this call processes, sorted by id and capped at `limit`."""
    if work_ids is not None:
        chosen = sorted(set(work_ids))
    else:
        documented = _documented_works(project)
        chosen = sorted(w for w in promoted if revisit or w not in documented)
    return chosen[:limit]


def _request(
    work_ids: Sequence[str] | None, only: Sequence[Route] | None, refresh: bool, limit: int
) -> JsonValue:
    """The request as the caller stated it, for an agent trigger's input blob."""
    return {
        "work_ids": None if work_ids is None else list(work_ids),
        "only": None if only is None else [r.value for r in only],
        "refresh": refresh,
        "limit": limit,
    }


def _trigger_blob(project: Project, trigger: Actor, request: JsonValue) -> str | None:
    """An agent's request is kept verbatim (R-03); a system or human trigger keeps no input."""
    return project.blobs.put_json(request) if trigger.kind == "agent" else None


# --- Per-work fetching and recording ---


def _fetch_work(
    project: Project,
    fetch_id: str,
    work: Work,
    routes: Mapping[Route, FullTextRoute],
    candidates: Sequence[Route],
    only: Sequence[Route] | None,
    revisit: bool,
) -> WorkFetch:
    """Run the routes for one work and record its events in one call.

    The state is read under the write lock before any network request, and again before the
    decision, so a document written in between is seen. The routes themselves run without the lock.
    """
    with project.index.exclusive():
        project.index.sync()
        if not revisit and _documents(project, work.id):
            return WorkFetch(work_id=work.id, attempts=[], documents=[], status="already-retrieved")
    fetched = _attempt_routes(project, work, routes, candidates, only)
    with project.index.exclusive():
        project.index.sync()
        docs = _documents(project, work.id)
        events, result = _work_events(project, fetch_id, work.id, fetched, docs)
        project.record(events)
    return result


def _attempt_routes(
    project: Project,
    work: Work,
    routes: Mapping[Route, FullTextRoute],
    candidates: Sequence[Route],
    only: Sequence[Route] | None,
) -> list[_Fetched]:
    """Ask each candidate route in order. Without `only`, stop at the first retrieved attempt."""
    fetched: list[_Fetched] = []
    for route in candidates:
        item = _check(project, route, routes[route].fetch(work))
        fetched.append(item)
        if only is None and item.content is not None:
            break
    return fetched


def _check(project: Project, route: Route, result: RouteResult) -> _Fetched:
    """Apply the service's checks to a route's answer and archive what it returned.

    Content is put into the library and metadata into `blobs/` here, before anything is recorded.
    A retrieved answer that cannot become a document is a failed attempt with a fixed reason.
    """
    secret = project.settings.mailto
    source_version = _clean(result.source_version, secret)
    media_type = _clean(result.media_type, secret)
    url = None if result.url is None else redact(result.url, secret)
    metadata_blob = None if result.metadata is None else project.blobs.put(result.metadata)
    licence = _clean(result.licence, secret)

    def answer(
        outcome: AttemptOutcome, reason: str | None, content: _Content | None = None
    ) -> _Fetched:
        return _Fetched(
            route=route,
            outcome=outcome,
            reason=reason,
            url=url,
            http_status=result.http_status,
            source_version=source_version,
            media_type=media_type,
            licence=licence,
            metadata_blob=metadata_blob,
            content=content,
        )

    if result.outcome in _NOT_RETRIEVED:
        return answer(result.outcome, _clean(result.reason, secret) or _UNSPECIFIED)
    if result.outcome is not AttemptOutcome.RETRIEVED:
        return answer(AttemptOutcome.FAILED, "unexpected-outcome")
    if result.content is None:
        return answer(AttemptOutcome.FAILED, "no-content")
    if source_version is None:
        return answer(AttemptOutcome.FAILED, "no-source-version")
    if media_type is None:
        return answer(AttemptOutcome.FAILED, "no-media-type")
    content = _Content(
        raw_hash=project.library.put(result.content),
        source_version=source_version,
        media_type=media_type,
    )
    return answer(AttemptOutcome.RETRIEVED, None, content)


def _clean(value: str | None, secret: str | None) -> str | None:
    """The value with the contact address removed and surrounding space stripped; None if blank."""
    if value is None:
        return None
    cleaned = redact(value, secret).strip()
    return cleaned or None


def _work_events(
    project: Project,
    fetch_id: str,
    work_id: str,
    fetched: Sequence[_Fetched],
    docs: Sequence[_Document],
) -> tuple[list[Event], WorkFetch]:
    """The events one work's routes produce, and the summary entry that describes them."""
    events: list[Event] = []
    attempt_ids: list[str] = []
    document_ids: list[str] = []
    dispositions: list[str | None] = []
    for item in fetched:
        attempt_id = project.ids.new("att")
        attempt_ids.append(attempt_id)
        if item.content is None:
            events.append(_attempted(project, fetch_id, work_id, attempt_id, item, None))
            dispositions.append(None)
            continue
        existing = _same_version(docs, item.route, item.content.source_version)
        if existing is None:
            document_id = project.ids.new("doc")
            disposition = "new"
        else:
            document_id = existing.document_id
            same = existing.raw_hash == item.content.raw_hash
            disposition = "same" if same else "changed"
        dispositions.append(disposition)
        events.append(_attempted(project, fetch_id, work_id, attempt_id, item, document_id))
        if existing is None:
            added = DocumentAdded(
                document_id=document_id,
                work_id=work_id,
                route=item.route,
                quality=QUALITY[item.route],
                source_version=item.content.source_version,
                raw_hash=item.content.raw_hash,
                media_type=item.content.media_type,
                attempt_id=attempt_id,
                provenance="retrieved",
                supersedes=_live(docs, item.route),
            )
            events.append(
                project.events.make(
                    "fulltext.document_added",
                    added,
                    project.system_actor(),
                    refs=(document_id, work_id, attempt_id),
                )
            )
            document_ids.append(document_id)
        elif disposition == "changed":
            change = SourceChanged(
                document_id=document_id,
                attempt_id=attempt_id,
                expected_hash=existing.raw_hash,
                observed_hash=item.content.raw_hash,
            )
            events.append(
                project.events.make(
                    "fulltext.source_changed",
                    change,
                    project.system_actor(),
                    refs=(document_id, attempt_id),
                )
            )
    summary = WorkFetch(
        work_id=work_id,
        attempts=attempt_ids,
        documents=document_ids,
        status=_status(dispositions),
    )
    return events, summary


def _attempted(
    project: Project,
    fetch_id: str,
    work_id: str,
    attempt_id: str,
    item: _Fetched,
    document_id: str | None,
) -> Event:
    payload = Attempted(
        attempt_id=attempt_id,
        fetch_id=fetch_id,
        work_id=work_id,
        route=item.route,
        url=item.url,
        http_status=item.http_status,
        outcome=item.outcome,
        reason=item.reason,
        retrieved_at=project.clock.now(),
        source_version=item.source_version,
        licence=item.licence,
        licence_status=(
            LicenceStatus.NOT_REPORTED if item.licence is None else LicenceStatus.REPORTED
        ),
        media_type=item.media_type,
        raw_hash=None if item.content is None else item.content.raw_hash,
        metadata_blob=item.metadata_blob,
        document_id=document_id,
    )
    return project.events.make(
        "fulltext.attempted", payload, project.system_actor(), refs=(attempt_id, work_id)
    )


def _status(dispositions: Sequence[str | None]) -> Status:
    """The work's status. A changed source needs a decision, so it outranks a new document."""
    if "changed" in dispositions:
        return "source-changed"
    if "new" in dispositions:
        return "retrieved"
    if "same" in dispositions:
        return "already-retrieved"
    return "not-retrieved"


# --- Projection reads (the projection, never the library) ---


def _documents(project: Project, work_id: str) -> list[_Document]:
    """Every document of one work, in event order. Requires a synced index."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT document_id, route, source_version, raw_hash, superseded_by "
                    "FROM fulltext_documents WHERE work_id = :work ORDER BY event_id"
                ),
                {"work": work_id},
            )
            .mappings()
            .all()
        )
    return [
        _Document(
            document_id=str(row["document_id"]),
            route=str(row["route"]),
            source_version=str(row["source_version"]),
            raw_hash=str(row["raw_hash"]),
            superseded=row["superseded_by"] is not None,
        )
        for row in rows
    ]


def _documented_works(project: Project) -> set[str]:
    """The works that have at least one document. Requires a synced index."""
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT work_id FROM fulltext_documents")).all()
    return {str(row[0]) for row in rows}


def _same_version(docs: Sequence[_Document], route: Route, version: str) -> _Document | None:
    """The document of this (route, source version), preferring a live one, then the latest."""
    matches = [d for d in docs if d.route == route and d.source_version == version]
    if not matches:
        return None
    live = [d for d in matches if not d.superseded]
    return (live or matches)[-1]


def _live(docs: Sequence[_Document], route: Route) -> str | None:
    """The latest live document on this route, which a new version of the route supersedes."""
    live = [d for d in docs if d.route == route and not d.superseded]
    return live[-1].document_id if live else None
