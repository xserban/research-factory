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
- A restore never adds a document. A hash match restores the library entry; a hash mismatch keeps
  the new bytes and records `fulltext.source_changed` against the existing document.
- Only a human resolves a source change. `keep-original` closes it, and a later re-fetch of the
  same hash is not a new change: its attempt is recorded and nothing else. A restore that receives
  a kept hash still records a change, since the original bytes it sought are gone.
  `accept-new-version` adds a document for the observed bytes that supersedes the original, from
  the attempt that observed them; conversions and pinned quotes of the original stay as they are.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, JsonValue
from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_FULLTEXT
from factory.model.fulltext import (
    MAX_RATIONALE,
    QUALITY,
    ROUTE_ORDER,
    Attempted,
    AttemptOutcome,
    DocumentAdded,
    FetchStarted,
    LicenceStatus,
    Route,
    SourceChanged,
    SourceDecision,
    SourceResolved,
)
from factory.model.identity import BLOB_REF_RE
from factory.model.work import Work
from factory.services.agreement import Outcome, final_outcomes
from factory.services.budgets import remaining as remaining_budget
from factory.services.budgets import require_for
from factory.services.context import Project
from factory.services.search import get_work, list_works
from factory.sources.fulltext.base import FullTextRoute, RouteResult
from factory.sources.http import redact

MIN_LIMIT = 1
MAX_LIMIT = 200
_NOT_RETRIEVED = (AttemptOutcome.NOT_AVAILABLE, AttemptOutcome.FAILED)
_UNSPECIFIED = "unspecified"

Status = Literal["retrieved", "not-retrieved", "already-retrieved", "source-changed"]
RestoreStatus = Literal[
    "present", "restored", "source-changed", "source-changed-unresolved", "unavailable"
]


class WorkFetch(StrictModel):
    """What one call did for one work. `documents` are the documents this call added."""

    work_id: str
    attempts: list[str]
    documents: list[str]
    status: Status


class FetchSummary(StrictModel):
    """What one `fetch_fulltext` call did. `remaining` counts promoted works with no document.
    `budget_stopped` names the works the request budget left unasked or cut short: one that has an
    attempt is asked again by naming it, or by `refresh`."""

    fetch_id: str
    works: list[WorkFetch]
    remaining: int
    budget_stopped: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _Document:
    """A document as the projection holds it, in event order."""

    document_id: str
    work_id: str
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

    `work_ids=None` selects promoted works that have neither a document nor any attempt, sorted by
    id, so a work whose routes all failed is retried only by `refresh`, `only` or an explicit id.
    With `refresh` or `only`, every promoted work is selected. An explicit work that already has a
    document is `already-retrieved` with no attempt, unless `refresh` or `only` is given. At most
    `limit` works are processed; explicit `work_ids` beyond `limit` are refused, not truncated.
    `remaining` counts the promoted works still without a document afterwards.

    A spent `requests:fulltext` budget refuses the call with nothing written. A budget spent during
    the call stops it before the next route is asked; what stopped is in `budget_stopped`.

    Raises `FactoryValidationError` with nothing written if a work is not promoted, `only` names
    `researcher-supplied` or a route not supplied, `limit` is outside 1..200, the distinct explicit
    `work_ids` exceed `limit`, or `input_blob` is not a stored blob. A route's failure is an
    attempt outcome, never an exception.
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
        require_for(project, trigger, REQUESTS_FULLTEXT)
        targets = _targets(project, promoted, work_ids, revisit, limit)
        fetch_id = project.ids.new("fft")
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

    works: list[WorkFetch] = []
    stopped: list[str] = []
    for work_id in targets:
        left = remaining_budget(project, trigger.user, REQUESTS_FULLTEXT, project.clock.now())
        if left == 0:
            stopped.append(work_id)
            continue
        fetched = _fetch_work(
            project, fetch_id, corpus[work_id], routes, candidates, only, revisit, left
        )
        works.append(fetched)
        if fetched.status == "not-retrieved" and left == len(fetched.attempts):
            stopped.append(work_id)

    with project.index.exclusive():
        project.index.sync()
        documented = _documented_works(project)
    remaining = len(promoted - documented)
    return FetchSummary(fetch_id=fetch_id, works=works, remaining=remaining, budget_stopped=stopped)


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
        distinct = len(set(work_ids))
        if distinct > limit:
            issues.append(ValidationIssue("limit", f"{distinct} work_ids exceed limit {limit}"))
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
    """The works this call processes. Explicit ids are validated against `limit` beforehand and
    returned sorted; the default selection is capped at `limit`. A revisit rotates: works are
    ordered by their last attempt, oldest first (never attempted first), then by id, so repeated
    calls reach the whole corpus (plan FL, ruling 3)."""
    if work_ids is not None:
        return sorted(set(work_ids))
    if revisit:
        last = _last_attempts(project)
        chosen = sorted(promoted, key=lambda w: (last.get(w, ""), w))
    else:
        excluded = _documented_works(project) | _attempted_works(project)
        chosen = sorted(w for w in promoted if w not in excluded)
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
    budget: int | None,
) -> WorkFetch:
    """Run the routes for one work, at most `budget` of them, and record its events in one call.

    The state is read under the write lock before any network request, and again before the
    decision, so a document written in between is seen. The routes themselves run without the lock.
    """
    with project.index.exclusive():
        project.index.sync()
        if not revisit and _documents(project, work.id):
            return WorkFetch(work_id=work.id, attempts=[], documents=[], status="already-retrieved")
    fetched = _attempt_routes(project, work, routes, candidates, only, budget)
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
    budget: int | None,
) -> list[_Fetched]:
    """Ask each candidate route in order, at most `budget` of them. Without `only`, stop at the
    first retrieved attempt. The attempts fold only once the work's events are written, so the
    budget is counted here."""
    fetched: list[_Fetched] = []
    for route in candidates:
        if budget is not None and len(fetched) >= budget:
            break
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
            kept = _kept_hashes(project, existing.document_id)
            same = item.content.raw_hash in {existing.raw_hash, *kept}
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
    fetch_id: str | None,
    work_id: str,
    attempt_id: str,
    item: _Fetched,
    document_id: str | None,
    *,
    outcome: AttemptOutcome | None = None,
    actor: Actor | None = None,
    input_blob: str | None = None,
    version_differs: str | None = None,
) -> Event:
    """One `fulltext.attempted`. `outcome` overrides the route's outcome (a restore records
    `restored`); `actor` and `input_blob` default to the system and to no input."""
    payload = Attempted(
        attempt_id=attempt_id,
        fetch_id=fetch_id,
        work_id=work_id,
        route=item.route,
        url=item.url,
        http_status=item.http_status,
        outcome=item.outcome if outcome is None else outcome,
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
        version_differs=version_differs,
    )
    return project.events.make(
        "fulltext.attempted",
        payload,
        actor or project.system_actor(),
        refs=(attempt_id, work_id),
        input_blob=input_blob,
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


# --- Restore (ruling 9) ---


def restore_document(
    project: Project,
    document_id: str,
    *,
    routes: Mapping[Route, FullTextRoute],
    actor: Actor | None = None,
) -> RestoreStatus:
    """Restore a document's library entry by re-requesting it from its recorded route.

    Returns `present` with no event if the library already holds the document's hash. Otherwise
    the document's route is asked for its recorded version and one attempt is recorded:
    - `restored`: the hash matches the document; the attempt names the document and its hash.
    - `source-changed`: the hash differs; the attempt names the existing document and the new
      hash, `fulltext.source_changed` records both hashes, and the new bytes stay in the library.
    - `unavailable`: the route did not retrieve; the attempt records its reason and no document
      changes.
    - `source-changed-unresolved`: an earlier change of this document's source awaits a human
      decision; nothing is requested and nothing is written (plan FL, ruling 2).

    Raises `FactoryValidationError` with nothing written if the document is unknown, is
    researcher-supplied (re-import it instead), its route is not supplied, or the
    `requests:fulltext` budget is spent.
    """
    trigger = actor or project.system_actor()
    with project.index.exclusive():
        project.index.sync()
        doc = _document(project, document_id)
        if doc is None:
            raise FactoryValidationError([ValidationIssue("document_id", "unknown document")])
        if doc.route == Route.LAB_LIBRARY.value:
            return _adopted_present(project, doc)
        issues = _restore_issues(doc, routes)
        if issues:
            raise FactoryValidationError(issues)
        if project.library.exists(doc.raw_hash):
            return "present"
        if _has_open_change(project, doc.document_id):
            return "source-changed-unresolved"
        work = get_work(project, doc.work_id)
        if work is None:
            raise FactoryValidationError([ValidationIssue("document_id", "work not found")])
        require_for(project, trigger, REQUESTS_FULLTEXT)

    route = Route(doc.route)
    item = _check(project, route, routes[route].fetch(work, version=doc.source_version))

    with project.index.exclusive():
        project.index.sync()
        events, status = _restore_events(project, doc, item, trigger)
        project.record(events)
    return status


def _adopted_present(project: Project, doc: _Document) -> RestoreStatus:
    """An adopted document has no route to ask: its bytes are in the lab library or they are not.
    They are `present` when the lab library serves them and they hash to the document's ref."""
    try:
        project.library.get(doc.raw_hash)
    except (BlobNotFoundError, BlobIntegrityError) as exc:
        raise FactoryValidationError(
            [ValidationIssue("document_id", "lab-library: push the blob or adopt it again")]
        ) from exc
    return "present"


def _has_open_change(project: Project, document_id: str) -> bool:
    """Whether a source change of this document awaits a decision. Requires a synced index."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM fulltext_source_changes "
                "WHERE document_id = :d AND resolution IS NULL LIMIT 1"
            ),
            {"d": document_id},
        ).first()
    return row is not None


@dataclass(frozen=True)
class RestoreOutcome:
    """One document's result in a restore of all missing entries. `status` is a `RestoreStatus`,
    `needs-reimport` (researcher-supplied), or `failed: <exception class name>` with no message."""

    document_id: str
    status: str


def restore_missing(
    project: Project,
    routes: Mapping[Route, FullTextRoute],
    actor: Actor | None = None,
) -> Iterator[RestoreOutcome]:
    """Restore every document whose library entry is missing, yielding each outcome as it is
    known. A researcher-supplied document is listed `needs-reimport` and never fetched. Each
    document is caught on its own: an unexpected exception gives `failed: <class name>` and the
    rest continue. A document with an unresolved source change is not requested again.
    """
    for document_id, route in library_missing(project):
        if route is Route.RESEARCHER:
            yield RestoreOutcome(document_id, "needs-reimport")
            continue
        if route is Route.LAB_LIBRARY:
            yield RestoreOutcome(document_id, "needs-lab-library")
            continue
        try:
            status: str = restore_document(project, document_id, routes=routes, actor=actor)
        except Exception as exc:
            status = f"failed: {type(exc).__name__}"
        yield RestoreOutcome(document_id, status)


def _restore_issues(doc: _Document, routes: Mapping[Route, FullTextRoute]) -> list[ValidationIssue]:
    """Why a document cannot be restored by a route. Empty if it can."""
    if doc.route == Route.RESEARCHER:
        return [ValidationIssue("document_id", "researcher-supplied: re-import the file")]
    route = Route(doc.route)
    if route not in routes:
        return [ValidationIssue("routes", f"no route supplied for {route.value}")]
    return []


def _restore_events(
    project: Project, doc: _Document, item: _Fetched, trigger: Actor
) -> tuple[list[Event], RestoreStatus]:
    """The attempt, and any source change, a restore produces, with its status."""
    attempt_id = project.ids.new("att")
    blob = _trigger_blob(project, trigger, {"document_id": doc.document_id})
    if item.content is None:
        attempt = _attempted(
            project,
            None,
            doc.work_id,
            attempt_id,
            item,
            None,
            actor=trigger,
            input_blob=blob,
        )
        return [attempt], "unavailable"
    same = item.content.raw_hash == doc.raw_hash
    observed = item.content.source_version
    attempt = _attempted(
        project,
        None,
        doc.work_id,
        attempt_id,
        item,
        doc.document_id,
        outcome=AttemptOutcome.RESTORED,
        actor=trigger,
        input_blob=blob,
        version_differs=observed if same and observed != doc.source_version else None,
    )
    events = [attempt]
    if same:
        return events, "restored"
    change = SourceChanged(
        document_id=doc.document_id,
        attempt_id=attempt_id,
        expected_hash=doc.raw_hash,
        observed_hash=item.content.raw_hash,
    )
    events.append(
        project.events.make(
            "fulltext.source_changed",
            change,
            trigger,
            refs=(doc.document_id, attempt_id),
            input_blob=blob,
        )
    )
    return events, "source-changed"


# --- Resolving a changed source (plan FL, ruling 1) ---


@dataclass(frozen=True)
class _ObservedChange:
    """The latest open change of one document and hash, with what its attempt recorded. The
    attempt fields are None if no attempt retrieved those bytes (only a hand-written change)."""

    attempt_id: str
    source_version: str | None
    media_type: str | None


def resolve_source_change(
    project: Project,
    actor: Actor,
    document_id: str,
    observed_hash: str,
    decision: SourceDecision,
    *,
    rationale: str,
) -> str | None:
    """Record a human's decision on a changed source. Returns the new document's id for
    `accept-new-version`, else None.

    Every open change of this document and hash closes. The new document takes the version and
    media type of the latest attempt that observed the bytes, and it is appended just before the
    resolution, which names it.

    Raises `FactoryValidationError` with nothing written if the actor is not human, the rationale
    is blank or long, the document is unknown, it has no open change for this hash, or, to accept,
    the document is superseded or researcher-supplied, no attempt retrieved the bytes, or the
    library does not hold them intact.
    """
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "human-only")])
    if not rationale.strip():
        raise FactoryValidationError([ValidationIssue("rationale", "must not be blank")])
    if len(rationale) > MAX_RATIONALE:
        raise FactoryValidationError(
            [ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters")]
        )
    with project.index.exclusive():
        project.index.sync()
        doc = _document(project, document_id)
        if doc is None:
            raise FactoryValidationError([ValidationIssue("document_id", "unknown document")])
        change = _open_change(project, document_id, observed_hash)
        if change is None:
            raise FactoryValidationError(
                [ValidationIssue("observed_hash", "no open change of this document has this hash")]
            )
        events: list[Event] = []
        new_document_id: str | None = None
        if decision is SourceDecision.ACCEPT_NEW_VERSION:
            issues = _accept_issues(project, doc, change, observed_hash)
            if issues:
                raise FactoryValidationError(issues)
            new_document_id = project.ids.new("doc")
            events.append(_accepted(project, actor, doc, change, observed_hash, new_document_id))
        resolved = SourceResolved(
            document_id=document_id,
            observed_hash=observed_hash,
            decision=decision,
            rationale=rationale,
            new_document_id=new_document_id,
        )
        refs = (document_id, doc.work_id, *([] if new_document_id is None else [new_document_id]))
        events.append(project.events.make("fulltext.source_resolved", resolved, actor, refs=refs))
        project.record(events)
    return new_document_id


def _accept_issues(
    project: Project, doc: _Document, change: _ObservedChange, observed_hash: str
) -> list[ValidationIssue]:
    """Why the observed bytes cannot become a document. Empty if they can."""
    issues: list[ValidationIssue] = []
    if doc.superseded:
        issues.append(ValidationIssue("document_id", "superseded: only keep-original applies"))
    if doc.route == Route.RESEARCHER:
        issues.append(ValidationIssue("document_id", "researcher-supplied: re-import the file"))
    if change.source_version is None or change.media_type is None:
        issues.append(ValidationIssue("observed_hash", "no attempt retrieved these bytes"))
    try:
        project.library.get(observed_hash)
    except FactoryError:
        issues.append(ValidationIssue("observed_hash", "the library does not hold these bytes"))
    return issues


def _accepted(
    project: Project,
    actor: Actor,
    doc: _Document,
    change: _ObservedChange,
    observed_hash: str,
    new_document_id: str,
) -> Event:
    """The `fulltext.document_added` of an accepted version. `_accept_issues` found it possible."""
    route = Route(doc.route)
    added = DocumentAdded(
        document_id=new_document_id,
        work_id=doc.work_id,
        route=route,
        quality=QUALITY[route],
        source_version=str(change.source_version),
        raw_hash=observed_hash,
        media_type=str(change.media_type),
        attempt_id=change.attempt_id,
        provenance="retrieved",
        supersedes=doc.document_id,
    )
    return project.events.make(
        "fulltext.document_added",
        added,
        actor,
        refs=(new_document_id, doc.work_id, change.attempt_id),
    )


# --- Researcher-supplied documents (ruling 7) ---


def record_supplied_document(
    project: Project,
    work_id: str,
    *,
    content: bytes,
    source_version: str,
    media_type: str,
    actor: Actor,
    link: Callable[[str], Event] | None = None,
) -> str | None:
    """Record a researcher-supplied PDF: its library entry, one attempt and one document.

    `link`, when given, builds one more event from the new document's id (an import's
    `import.attachment_linked`); it is appended in the same `record` call.

    Returns the new document's id, or None if the bytes already back a document of this work, in
    which case nothing is written (the library is not touched either). The caller holds the write
    lock with a synced index and has already checked that the work is promoted.
    """
    raw_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
    docs = _documents(project, work_id)
    if any(doc.raw_hash == raw_hash for doc in docs):
        return None
    project.library.put(content)
    attempt_id = project.ids.new("att")
    document_id = project.ids.new("doc")
    item = _Fetched(
        route=Route.RESEARCHER,
        outcome=AttemptOutcome.RETRIEVED,
        reason=None,
        url=None,
        http_status=None,
        source_version=source_version,
        media_type=media_type,
        licence=None,
        metadata_blob=None,
        content=_Content(raw_hash=raw_hash, source_version=source_version, media_type=media_type),
    )
    with project.writing():
        attempt = _attempted(project, None, work_id, attempt_id, item, document_id, actor=actor)
        added = DocumentAdded(
            document_id=document_id,
            work_id=work_id,
            route=Route.RESEARCHER,
            quality=QUALITY[Route.RESEARCHER],
            source_version=source_version,
            raw_hash=raw_hash,
            media_type=media_type,
            attempt_id=attempt_id,
            provenance="researcher-supplied",
            supersedes=_live(docs, Route.RESEARCHER),
        )
        document = project.events.make(
            "fulltext.document_added",
            added,
            actor,
            refs=(document_id, work_id, attempt_id),
        )
        project.record([attempt, document, *([] if link is None else [link(document_id)])])
    return document_id


# --- Projection reads (the projection, never the library) ---


_DOCUMENT_COLUMNS = "document_id, work_id, route, source_version, raw_hash, superseded_by"


def library_missing(project: Project) -> list[tuple[str, Route]]:
    """(document id, route) of every document whose library entry is missing, in event order.

    Superseded documents are included, as `check` includes them. The index is synced first; the
    library is read only to test each hash's presence, and nothing is written.
    """
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT document_id, route, raw_hash FROM fulltext_documents ORDER BY event_id")
        ).all()
    return [
        (str(document), Route(str(route)))
        for document, route, raw_hash in rows
        if not project.library.exists(str(raw_hash))
    ]


def _documents(project: Project, work_id: str) -> list[_Document]:
    """Every document of one work, in event order. Requires a synced index."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"SELECT {_DOCUMENT_COLUMNS} FROM fulltext_documents "
                    "WHERE work_id = :work ORDER BY event_id"
                ),
                {"work": work_id},
            )
            .mappings()
            .all()
        )
    return [_to_document(row) for row in rows]


def _document(project: Project, document_id: str) -> _Document | None:
    """One document by id, or None if the projection holds no such document."""
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text(
                    f"SELECT {_DOCUMENT_COLUMNS} FROM fulltext_documents WHERE document_id = :doc"
                ),
                {"doc": document_id},
            )
            .mappings()
            .first()
        )
    return None if row is None else _to_document(row)


def _open_change(project: Project, document_id: str, observed_hash: str) -> _ObservedChange | None:
    """The latest open change of this document and hash, or None. Requires a synced index."""
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT c.attempt_id, a.source_version, a.media_type "
                    "FROM fulltext_source_changes c LEFT JOIN fulltext_attempts a "
                    "ON a.attempt_id = c.attempt_id AND a.raw_hash = c.observed_hash "
                    "WHERE c.document_id = :doc AND c.observed_hash = :hash "
                    "AND c.resolution IS NULL ORDER BY c.event_id DESC LIMIT 1"
                ),
                {"doc": document_id, "hash": observed_hash},
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    version, media_type = row["source_version"], row["media_type"]
    return _ObservedChange(
        attempt_id=str(row["attempt_id"]),
        source_version=None if version is None else str(version),
        media_type=None if media_type is None else str(media_type),
    )


def _kept_hashes(project: Project, document_id: str) -> set[str]:
    """The observed hashes a human kept the original against. Requires a synced index."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT observed_hash FROM fulltext_source_changes "
                "WHERE document_id = :doc AND resolution = :kept"
            ),
            {"doc": document_id, "kept": SourceDecision.KEEP_ORIGINAL.value},
        ).all()
    return {str(row[0]) for row in rows}


def document_superseded(project: Project, document_id: str) -> bool:
    """Whether a newer document version superseded `document_id`; False for an unknown id. The
    caller syncs the index."""
    found = _document(project, document_id)
    return found is not None and found.superseded


def _to_document(row: RowMapping) -> _Document:
    return _Document(
        document_id=str(row["document_id"]),
        work_id=str(row["work_id"]),
        route=str(row["route"]),
        source_version=str(row["source_version"]),
        raw_hash=str(row["raw_hash"]),
        superseded=row["superseded_by"] is not None,
    )


def _documented_works(project: Project) -> set[str]:
    """The works that have at least one document. Requires a synced index."""
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT work_id FROM fulltext_documents")).all()
    return {str(row[0]) for row in rows}


def _last_attempts(project: Project) -> dict[str, str]:
    """Each attempted work's latest attempt time as recorded (UTC ISO text, so it sorts as time).
    Requires a synced index."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id, MAX(retrieved_at) FROM fulltext_attempts GROUP BY work_id")
        ).all()
    return {str(w): str(t) for w, t in rows}


def _attempted_works(project: Project) -> set[str]:
    """The works with at least one attempt of any outcome. Requires a synced index."""
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT work_id FROM fulltext_attempts")).all()
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
