"""Core works: where a forward snowball round may start (slice 8, IDEA-43).

Invariants:
- Marking and unmarking are the researcher's: a non-human actor is refused (`actor`: `human-only`)
  and nothing is written; the fold ignores an agent-written event as well (`index.core_works`).
- A mark names a work the project holds (`work_id`: `unknown`), once (`work_id`: `already-core`);
  an unmark names a marked work (`work_id`: `not-marked`).
- A development positive seed's work is core without a mark. A held-out seed's work is never an
  automatic core work (R-20: it must not steer the search); it is core only if a human marks it.
  `seed_core_works` without `development_only` lists every positive seed's work and is for the
  researcher's own view only; no round plan, event or agent view uses it.
- `forward_core_sources` is the core works that a forward round may start from: the marked ones
  that are included at the last declared stage, and the development seeds' works. Nothing is
  typed in.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import TypeVar

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.core_works import WorkMarkedCore, WorkUnmarkedCore
from factory.model.search import QueryPurpose
from factory.model.seed import SeedKind
from factory.model.work_ids import WORK_ID_RE
from factory.services.context import Project
from factory.services.seeds import agent_seeds, all_seeds


class CoreMark(StrictModel):
    """One work currently marked core."""

    work_id: str
    note: str | None
    event_id: str
    marked_by: str


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def core_marks(project: Project) -> list[CoreMark]:
    """The works currently marked core, by work id."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id, note, event_id, marked_by FROM core_works ORDER BY work_id")
        ).all()
    return [
        CoreMark(
            work_id=str(w),
            note=None if n is None else str(n),
            event_id=str(e),
            marked_by=str(m),
        )
        for w, n, e, m in rows
    ]


def seed_core_works(project: Project, *, development_only: bool = False) -> list[str]:
    """The works of the positive seeds that resolved to a work, sorted. With `development_only`
    the held-out seeds' works are left out (the only list a search or an agent view may use)."""
    if development_only:
        works = {
            s.work_id
            for s in agent_seeds(project)
            if s.kind is SeedKind.POSITIVE and s.work_id is not None
        }
    else:
        works = {
            s.work_id
            for s in all_seeds(project)
            if s.kind is SeedKind.POSITIVE and s.work_id is not None
        }
    return sorted(works)


def forward_core_sources(project: Project, included: Collection[str]) -> list[str]:
    """The core works a forward round may start from, sorted: the marked works among `included`
    and every development positive seed's work (never a held-out seed's, unless marked)."""
    marked = {m.work_id for m in core_marks(project)}
    return sorted((marked & set(included)) | set(seed_core_works(project, development_only=True)))


def mark_core(project: Project, actor: Actor, work_id: str, note: str | None = None) -> str:
    """Mark a work core and return the event id. Refused, with nothing written, as the module
    invariants say; a blank or overlong note is refused by the model."""
    if actor.kind != "human":
        raise _refuse("actor", "human-only")
    payload = _payload(WorkMarkedCore, work_id, note)
    with project.writing():
        if not _known(project, work_id):
            raise _refuse("work_id", "unknown")
        if any(m.work_id == work_id for m in core_marks(project)):
            raise _refuse("work_id", "already-core")
        event = project.events.make("work.marked_core", payload, actor, refs=(work_id,))
        project.record([event])
    return event.id


def unmark_core(project: Project, actor: Actor, work_id: str, note: str | None = None) -> str:
    """Take a work's core mark back and return the event id (a seed's work stays core)."""
    if actor.kind != "human":
        raise _refuse("actor", "human-only")
    payload = _payload(WorkUnmarkedCore, work_id, note)
    with project.writing():
        if not any(m.work_id == work_id for m in core_marks(project)):
            raise _refuse("work_id", "not-marked")
        event = project.events.make("work.unmarked_core", payload, actor, refs=(work_id,))
        project.record([event])
    return event.id


_Mark = TypeVar("_Mark", WorkMarkedCore, WorkUnmarkedCore)


def _payload(model: type[_Mark], work_id: str, note: str | None) -> _Mark:
    if re.fullmatch(WORK_ID_RE, work_id) is None:
        raise _refuse("work_id", "not a work id")
    try:
        return model(work_id=work_id, note=None if note is None else note.strip() or None)
    except ValidationError as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(".".join(str(p) for p in err["loc"]), str(err["msg"]))
                for err in exc.errors()
            ]
        ) from exc


def _known(project: Project, work_id: str) -> bool:
    """Whether the work is in the corpus (found by a non-probe query or admitted); a work only
    a probe saw is not."""
    project.index.sync()
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM provenance WHERE work_id = :w AND query_id NOT IN "
                    "(SELECT query_id FROM queries WHERE purpose = :probe)"
                ),
                {"w": work_id, "probe": QueryPurpose.PROBE.value},
            ).first()
            is not None
        )
