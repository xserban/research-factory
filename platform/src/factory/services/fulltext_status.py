"""Full-text status: what has been retrieved for each promoted work, read from the projection.

A work is `retrieved` when it has a live document, `not-retrieved` when it has attempts but no live
document, and `unsought` when no route has been tried for it. `reasons` gives the reason of the
latest attempt on each route, for a not-retrieved work. `changed_sources` lists each source change
no human has resolved, with the hash `factory fulltext resolve` needs.

Invariants:
- Only works the title/abstract screening promoted (`final_outcomes` gives `Outcome.INCLUDED`) are
  counted. A named work that is not promoted is refused, as `fetch_fulltext` refuses it.
- "Latest" means latest in event order (the event id), never by timestamp text.
- The status never reads the library (decision 39): removing a library entry changes no count.
- Read-only: nothing is written, and the index is synced before it is read.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.fulltext import Route
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.work_ref import resolve_work_ids

_NOT_RETRIEVED = frozenset({"not-available", "failed"})
"""The attempt outcomes that record a reason and no document (`Attempted`)."""


class WorkFulltext(StrictModel):
    """One promoted work's full-text state. `documents` are its live documents, in event order.
    `reasons` holds, for a not-retrieved work, the reason of its latest attempt on each route."""

    work_id: str
    state: Literal["unsought", "retrieved", "not-retrieved"]
    documents: list[str]
    reasons: dict[Route, str]


class ChangedSource(StrictModel):
    """An unresolved source change: one document and one hash a re-fetch observed."""

    document_id: str
    work_id: str
    expected_hash: str
    observed_hash: str


class FulltextStatus(StrictModel):
    """Counts over the works in scope. `promoted` is the number of works in scope, so the three
    states sum to it; `by_route` counts live documents per route over those works.
    `changed_sources` are the open changes of those works, each document and hash once."""

    promoted: int
    unsought: int
    retrieved: int
    not_retrieved: int
    by_route: dict[Route, int]
    works: list[WorkFulltext]
    changed_sources: list[ChangedSource]


def fulltext_status(project: Project, *, work_ids: Sequence[str] | None = None) -> FulltextStatus:
    """The full-text status of every promoted work, or of the named ones (sorted by id).

    Raises `FactoryValidationError` if a named work is not promoted. Read-only.
    """
    project.index.sync()
    promoted = {w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED}
    if work_ids is None:
        scope = sorted(promoted)
    else:
        work_ids = resolve_work_ids(project, work_ids)
        issues = [
            ValidationIssue("work_ids", f"{work_id}: not promoted at title/abstract")
            for work_id in sorted(set(work_ids))
            if work_id not in promoted
        ]
        if issues:
            raise FactoryValidationError(issues)
        scope = sorted(set(work_ids))
    attempts = _latest_attempts(project)
    documents = _live_documents(project)

    works = [_work(work_id, attempts, documents) for work_id in scope]
    by_route: dict[Route, int] = {route: 0 for route in Route}
    for entry in works:
        for document in entry.documents:
            by_route[documents[document].route] += 1
    return FulltextStatus(
        promoted=len(works),
        unsought=_count(works, "unsought"),
        retrieved=_count(works, "retrieved"),
        not_retrieved=_count(works, "not-retrieved"),
        by_route=by_route,
        works=works,
        changed_sources=_changed_sources(project, frozenset(scope)),
    )


def _count(works: Sequence[WorkFulltext], state: str) -> int:
    return sum(1 for entry in works if entry.state == state)


@dataclass(frozen=True)
class _Live:
    """A live document as the status reads it: its work and its route."""

    work_id: str
    route: Route


def _work(
    work_id: str,
    attempts: dict[str, dict[Route, tuple[str, str | None]]],
    documents: dict[str, _Live],
) -> WorkFulltext:
    """One work's state. `documents` is in event order, so the live list is too."""
    live = [doc for doc, row in documents.items() if row.work_id == work_id]
    tried = attempts.get(work_id, {})
    if live:
        state: Literal["unsought", "retrieved", "not-retrieved"] = "retrieved"
    elif tried:
        state = "not-retrieved"
    else:
        state = "unsought"
    reasons: dict[Route, str] = {}
    if state == "not-retrieved":
        for route, (outcome, reason) in tried.items():
            if outcome in _NOT_RETRIEVED and reason is not None:
                reasons[route] = reason
    return WorkFulltext(work_id=work_id, state=state, documents=live, reasons=reasons)


def _changed_sources(project: Project, scope: frozenset[str]) -> list[ChangedSource]:
    """The open source changes of the works in scope, first seen first, without repeats."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT c.document_id, d.work_id, c.expected_hash, c.observed_hash "
                    "FROM fulltext_source_changes c "
                    "JOIN fulltext_documents d ON d.document_id = c.document_id "
                    "WHERE c.resolution IS NULL ORDER BY c.event_id"
                )
            )
            .mappings()
            .all()
        )
    changes: dict[tuple[str, str], ChangedSource] = {}
    for row in rows:
        if str(row["work_id"]) in scope:
            key = (str(row["document_id"]), str(row["observed_hash"]))
            changes.setdefault(key, ChangedSource.model_validate(dict(row)))
    return list(changes.values())


def _latest_attempts(project: Project) -> dict[str, dict[Route, tuple[str, str | None]]]:
    """Per work and route, the outcome and reason of the latest attempt (by event id)."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT work_id, route, outcome, reason FROM fulltext_attempts "
                    "ORDER BY event_id"
                )
            )
            .mappings()
            .all()
        )
    latest: dict[str, dict[Route, tuple[str, str | None]]] = {}
    for row in rows:
        reason = None if row["reason"] is None else str(row["reason"])
        latest.setdefault(str(row["work_id"]), {})[Route(str(row["route"]))] = (
            str(row["outcome"]),
            reason,
        )
    return latest


def _live_documents(project: Project) -> dict[str, _Live]:
    """Every live (not superseded) document by id, with its work and route."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT document_id, work_id, route FROM fulltext_documents "
                    "WHERE superseded_by IS NULL ORDER BY event_id"
                )
            )
            .mappings()
            .all()
        )
    return {
        str(row["document_id"]): _Live(str(row["work_id"]), Route(str(row["route"])))
        for row in rows
    }
