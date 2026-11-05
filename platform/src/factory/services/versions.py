"""Version observation, aliases and the preferred document (slice 4b, living-C).

For the dependent works of a cycle, a version check looks up two kinds of facts as STATUS runs of
the cycle: whether arXiv holds a newer version than the work's current arXiv document
(`version.observed`, nothing is fetched), and whether OpenAlex or arXiv names a published version
(`version.linked`). A link adds the published identifiers as aliases of the existing work; it
changes no screening decision and no document pin.

Invariants:
- A link whose identifier already belongs to a different work, not merged with this one, applies
  nothing: it is recorded with `conflicts_with` and reported (`link_conflicts`) as a dedup
  question for a human (R-26).
- A repeated observation or link writes nothing.
- Aliases are used only by deduplication; the work keeps its own identifiers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import bindparam, text

from factory.events.envelope import Event
from factory.model.base import StrictModel
from factory.model.dedup_keys import identifier_keys
from factory.model.fulltext import Route
from factory.model.search import QueryKind
from factory.model.versions import VersionLinked, VersionObserved
from factory.model.work import Identifiers, Work
from factory.model.work_ids import arxiv_id_from_doi
from factory.services.context import Project
from factory.services.search import works_by_ids
from factory.services.status_lookup import (
    DATACITE_ARXIV_PREFIX,
    Resolver,
    StatusBatch,
    StatusOutcome,
    groups,
    openalex_batches,
    run_batches,
)
from factory.sources.registry import SourceFactory

_ARXIV_ROUTES = (Route.ARXIV_HTML.value, Route.ARXIV_SOURCE.value)
_VERSION = re.compile(r"v(\d+)$")
_CHUNK = 500


class VersionCheckSummary(StrictModel):
    newer: int
    linked: int
    conflicts: int
    run_ids: tuple[str, ...]


@dataclass(frozen=True)
class LinkConflict:
    """A published identifier a work was linked to that another work already holds."""

    work_id: str
    doi: str
    other_work_id: str


def version_check(
    project: Project,
    cycle_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    work_ids: Sequence[str],
) -> VersionCheckSummary:
    """Look up versions and published-version links of `work_ids` inside the open cycle."""
    works = works_by_ids(project, work_ids)
    batches = openalex_batches(works) + _arxiv_batches(works)
    outcomes = run_batches(project, cycle_id, sources, batches)
    resolver = Resolver(works)
    events: list[Event] = []
    events += _observation_events(project, outcomes, resolver)
    link_events = _link_events(project, outcomes, resolver, {w.id: w for w in works})
    events += link_events
    if events:
        project.record(events)
    conflicts = sum(1 for e in link_events if e.payload.get("conflicts_with") is not None)
    return VersionCheckSummary(
        newer=sum(1 for e in events if e.type == "version.observed"),
        linked=len(link_events) - conflicts,
        conflicts=conflicts,
        run_ids=tuple(o.run_id for o in outcomes),
    )


def arxiv_id(work: Work) -> str | None:
    """The arXiv id a work is held under: its own, else the one in a DataCite arXiv DOI."""
    ids = work.identifiers
    if ids.arxiv:
        return ids.arxiv
    return arxiv_id_from_doi(ids.doi) if ids.doi else None


def _arxiv_batches(works: Sequence[Work]) -> list[StatusBatch]:
    pairs = sorted({(w.id, a) for w in works if (a := arxiv_id(w)) is not None})
    return [
        StatusBatch(
            source="arxiv",
            kind=QueryKind.ID_LIST,
            text=",".join(a for _, a in group),
            work_ids=tuple(w for w, _ in group),
        )
        for group in groups(pairs)
    ]


def _version_number(source_version: str) -> int | None:
    match = _VERSION.search(source_version)
    return None if match is None else int(match.group(1))


def _current_arxiv_documents(
    project: Project, work_ids: Sequence[str]
) -> dict[str, list[tuple[str, str]]]:
    """Each work's live arXiv-route documents as (route, source_version)."""
    project.index.sync()
    statement = text(
        "SELECT work_id, route, source_version FROM fulltext_documents "
        "WHERE superseded_by IS NULL AND route IN :routes AND work_id IN :ids "
        "ORDER BY work_id, route"
    ).bindparams(bindparam("routes", expanding=True), bindparam("ids", expanding=True))
    found: dict[str, list[tuple[str, str]]] = {}
    ids = sorted(set(work_ids))
    with project.index.connect() as conn:
        for start in range(0, len(ids), _CHUNK):
            for work_id, route, version in conn.execute(
                statement, {"routes": list(_ARXIV_ROUTES), "ids": ids[start : start + _CHUNK]}
            ):
                found.setdefault(str(work_id), []).append((str(route), str(version)))
    return found


def _observation_events(
    project: Project, outcomes: Sequence[StatusOutcome], resolver: Resolver
) -> list[Event]:
    documents = _current_arxiv_documents(project, [w for o in outcomes for w in o.batch.work_ids])
    project.index.sync()
    with project.index.connect() as conn:
        seen = {
            (str(w), str(r), str(v))
            for w, r, v in conn.execute(
                text("SELECT work_id, route, source_version FROM version_observations")
            )
        }
    events: list[Event] = []
    for outcome in outcomes:
        for record in outcome.records:
            if record.kind != "version" or not record.source_version:
                continue
            work_id = resolver.work_for(record.target)
            latest = _version_number(record.source_version)
            if work_id is None or latest is None:
                continue
            for route, held in documents.get(work_id, ()):
                current = _version_number(held)
                key = (work_id, route, record.source_version)
                if current is None or latest <= current or key in seen:
                    continue
                seen.add(key)
                payload = VersionObserved(
                    work_id=work_id,
                    route=Route(route),
                    source_version=record.source_version,
                    run_id=outcome.run_id,
                )
                events.append(
                    project.events.make(
                        "version.observed",
                        payload,
                        project.system_actor(),
                        refs=(work_id, outcome.run_id),
                    )
                )
    return events


def _holders(project: Project, kind: str, value: str) -> set[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id FROM work_keys WHERE kind = :k AND value = :v"),
            {"k": kind, "v": value},
        ).all()
    return {str(r[0]) for r in rows}


def _merged_together(project: Project, a: str, b: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM merge_members x JOIN merge_members y ON x.merge_id = y.merge_id "
                "JOIN merges m ON m.merge_id = x.merge_id "
                "WHERE m.status = 'active' AND x.work_id = :a AND y.work_id = :b LIMIT 1"
            ),
            {"a": a, "b": b},
        ).one_or_none()
    return row is not None


def _link_events(
    project: Project,
    outcomes: Sequence[StatusOutcome],
    resolver: Resolver,
    works: Mapping[str, Work],
) -> list[Event]:
    project.index.sync()
    with project.index.connect() as conn:
        seen = {
            (str(w), str(k))
            for w, k in conn.execute(text("SELECT work_id, link_key FROM version_links"))
        }
    events: list[Event] = []
    for outcome in outcomes:
        for record in outcome.records:
            linked = record.linked
            if record.kind != "version" or linked is None:
                continue
            work_id = resolver.work_for(record.target)
            if work_id is None:
                continue
            keys = [
                key
                for key in identifier_keys(linked)
                if not (key[0] == "doi" and key[1].startswith(DATACITE_ARXIV_PREFIX))
            ]
            if not keys:
                continue
            link_key = ":".join(keys[0])
            held_elsewhere = {h for key in keys for h in _holders(project, *key)} - {work_id}
            clashing = sorted(
                h for h in held_elsewhere if not _merged_together(project, work_id, h)
            )
            own = set(identifier_keys(works[work_id].identifiers))
            if (work_id, link_key) in seen or (not clashing and set(keys) <= own):
                continue
            seen.add((work_id, link_key))
            payload = VersionLinked(
                work_id=work_id,
                identifiers=linked,
                venue=record.venue,
                source=outcome.batch.source,
                run_id=outcome.run_id,
                conflicts_with=clashing[0] if clashing else None,
            )
            events.append(
                project.events.make(
                    "version.linked",
                    payload,
                    project.system_actor(),
                    refs=(work_id, outcome.run_id),
                )
            )
    return events


# --- reads ---


def aliases(project: Project, work_id: str) -> Identifiers:
    """The published identifiers linked to the work (applied links only)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT kind, value FROM work_aliases WHERE work_id = :w ORDER BY kind, value"),
            {"w": work_id},
        ).all()
    fields: dict[str, str] = {}
    for kind, value in rows:
        fields.setdefault(str(kind), str(value))
    return Identifiers(**fields)


def newer_versions(project: Project) -> list[VersionObserved]:
    """Observed versions still newer than the work's current live document on that route."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT o.work_id, o.route, o.source_version, o.run_id, d.source_version "
                "FROM version_observations o JOIN fulltext_documents d "
                "ON d.work_id = o.work_id AND d.route = o.route AND d.superseded_by IS NULL "
                "ORDER BY o.work_id, o.route, o.source_version"
            )
        ).all()
    out: list[VersionObserved] = []
    for work_id, route, observed, run_id, held in rows:
        latest, current = _version_number(str(observed)), _version_number(str(held))
        if latest is not None and current is not None and latest > current:
            out.append(
                VersionObserved(
                    work_id=str(work_id),
                    route=Route(str(route)),
                    source_version=str(observed),
                    run_id=str(run_id),
                )
            )
    return out


def vor_available(project: Project) -> list[str]:
    """Works with an applied published-version link whose current document is a preprint's."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT l.work_id FROM version_links l JOIN fulltext_documents d "
                "ON d.work_id = l.work_id AND d.superseded_by IS NULL AND d.route IN :routes "
                "WHERE l.conflicts_with IS NULL ORDER BY l.work_id"
            ).bindparams(bindparam("routes", expanding=True)),
            {"routes": list(_ARXIV_ROUTES)},
        ).all()
    return [str(r[0]) for r in rows]


def link_conflicts(project: Project) -> list[LinkConflict]:
    """Recorded refused links whose two works are still not merged: dedup questions for a human."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, link_key, conflicts_with FROM version_links "
                "WHERE conflicts_with IS NOT NULL ORDER BY work_id, link_key"
            )
        ).all()
    out: list[LinkConflict] = []
    for work_id, link_key, other in rows:
        if not _merged_together(project, str(work_id), str(other)):
            out.append(LinkConflict(str(work_id), str(link_key).split(":", 1)[-1], str(other)))
    return out
