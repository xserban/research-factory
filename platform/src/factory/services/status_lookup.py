"""Status lookups inside a watch cycle: identifier queries about known works (living-C).

A lookup is an ordinary recorded search run of purpose STATUS that names its open cycle, so raw
pages are archived before they are parsed and the protocol gate is re-checked at run time. This
module only batches the queries, runs them and resolves what they read back to corpus works;
`services.notices` and `services.versions` turn the resolved records into events.

Invariants:
- A status query registers the work ids it asks about as refs of its `query.registered` event, so
  "when was this work last looked up" is an indexed read of completed runs (`last_checked`).
- A record is attributed to a work only when exactly one work of the batch carries one of the
  identifiers the record names; an ambiguous or unknown target is dropped, never guessed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import bindparam, text

from factory.model.chase import CHASE_CHUNK
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Identifiers, Work
from factory.services.context import Project
from factory.services.search import register_query, run_query
from factory.sources.base import StatusRecord
from factory.sources.registry import SourceFactory

DATACITE_ARXIV_PREFIX = "10.48550/"
"""DOIs of this prefix are DataCite's arXiv DOIs; Crossref holds no record of them."""

_ID_CHUNK = 500


@dataclass(frozen=True)
class StatusBatch:
    """One query of a lookup: its source, filter text and the works it asks about."""

    source: str
    kind: QueryKind
    text: str
    work_ids: tuple[str, ...]


@dataclass(frozen=True)
class StatusOutcome:
    """What one batch's run read: its status, records, works and first archived page."""

    batch: StatusBatch
    run_id: str
    status: RunStatus
    records: tuple[StatusRecord, ...]
    raw_blob: str | None


def chunks(items: Sequence[str], size: int = CHASE_CHUNK) -> list[list[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def run_batches(
    project: Project,
    cycle_id: str,
    sources: Mapping[str, SourceFactory],
    batches: Iterable[StatusBatch],
) -> list[StatusOutcome]:
    """Register and run each batch as a STATUS query of the cycle, in order.

    A batch whose source is not in `sources`, or whose run raises, is skipped; a failed run is
    already on the log. Returns the outcome of every batch that ran.
    """
    outcomes: list[StatusOutcome] = []
    system = project.system_actor()
    for batch in batches:
        if batch.source not in sources:
            continue
        spec = QuerySpec(
            source=batch.source, kind=batch.kind, text=batch.text, purpose=QueryPurpose.STATUS
        )
        query_id = ""
        try:
            query_id = register_query(
                project,
                system,
                spec,
                sources=sources,
                cycle_id=cycle_id,
                names_works=batch.work_ids,
            )
            summary = run_query(project, query_id, sources=sources, cycle_id=cycle_id)
        except Exception:  # a failed batch must not stop the others
            summary_or_none = None
        else:
            summary_or_none = summary
        if summary_or_none is None:
            # `run_query` records a crashed run as failed before it re-raises; keep its run id so
            # the cycle names it and `check` can report it. A registration refused writes nothing.
            crashed = _latest_run(project, query_id)
            if crashed is not None:
                outcomes.append(
                    StatusOutcome(
                        batch=batch,
                        run_id=crashed,
                        status=RunStatus.FAILED,
                        records=(),
                        raw_blob=first_page_blob(project, crashed),
                    )
                )
            continue
        summary = summary_or_none
        outcomes.append(
            StatusOutcome(
                batch=batch,
                run_id=summary.run_id,
                status=summary.status,
                records=summary.status_records,
                raw_blob=first_page_blob(project, summary.run_id),
            )
        )
    return outcomes


def _latest_run(project: Project, query_id: str) -> str | None:
    if not query_id:
        return None
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT run_id FROM runs WHERE query_id = :q ORDER BY run_id DESC LIMIT 1"),
            {"q": query_id},
        ).one_or_none()
    return None if row is None else str(row[0])


def first_page_blob(project: Project, run_id: str) -> str | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT raw_blob FROM pages WHERE run_id = :r ORDER BY ordinal LIMIT 1"),
            {"r": run_id},
        ).one_or_none()
    return None if row is None else str(row[0])


def last_checked_by_source(project: Project, work_ids: Sequence[str]) -> dict[str, dict[str, str]]:
    """For each source, the start time of the latest complete status run of that source that
    asked about each work. Works never looked up in a source are absent from its map. One indexed
    read keyed by work id; no corpus scan."""
    project.index.sync()
    found: dict[str, dict[str, str]] = {}
    statement = text(
        "SELECT r.ref, qu.source, MAX(run.started_at) FROM event_refs r "
        "JOIN event_refs q ON q.event_id = r.event_id AND q.position = 0 "
        "AND q.type = 'query.registered' "
        "JOIN queries qu ON qu.query_id = q.ref AND qu.purpose = :status "
        "JOIN runs run ON run.query_id = q.ref AND run.status = :complete "
        "WHERE r.type = 'query.registered' AND r.position > 0 AND r.ref IN :ids "
        "GROUP BY r.ref, qu.source"
    ).bindparams(bindparam("ids", expanding=True))
    ids = sorted(set(work_ids))
    with project.index.connect() as conn:
        for start in range(0, len(ids), _ID_CHUNK):
            for ref, source, at in conn.execute(
                statement,
                {
                    "status": QueryPurpose.STATUS.value,
                    "complete": RunStatus.COMPLETE.value,
                    "ids": ids[start : start + _ID_CHUNK],
                },
            ):
                found.setdefault(str(source), {})[str(ref)] = str(at)
    return found


def checkable_sources(work: Work, notice_sources: Sequence[str]) -> list[str]:
    """The notice sources a work can be asked about: OpenAlex by any handle, Crossref by a DOI
    of its own."""
    out: list[str] = []
    if "openalex" in notice_sources and openalex_handle(work) is not None:
        out.append("openalex")
    if "crossref" in notice_sources and crossref_doi(work) is not None:
        out.append("crossref")
    return out


def effective_last_checked(
    project: Project, works: Sequence[Work], notice_sources: Sequence[str]
) -> dict[str, str | None]:
    """When each work was last looked up in every source it can be asked about: the oldest of
    those sources' last complete runs, "" if one never completed, so one source's success never
    hides another's failure. None for a work no notice source can be asked about."""
    by_source = last_checked_by_source(project, [w.id for w in works])
    out: dict[str, str | None] = {}
    for work in works:
        sources = checkable_sources(work, notice_sources)
        out[work.id] = (
            min(by_source.get(s, {}).get(work.id, "") for s in sources) if sources else None
        )
    return out


def unrecovered_failures(project: Project) -> list[str]:
    """Ids of failed or partial status runs whose works some later complete run of the same source
    has not yet covered, sorted. A run that asked about no work is never listed."""
    project.index.sync()
    with project.index.connect() as conn:
        runs = conn.execute(
            text(
                "SELECT run.run_id, qu.source, run.started_at, q.event_id FROM runs run "
                "JOIN queries qu ON qu.query_id = run.query_id AND qu.purpose = :status "
                "JOIN event_refs q ON q.ref = qu.query_id AND q.position = 0 "
                "AND q.type = 'query.registered' "
                "WHERE run.status IN ('failed', 'partial') ORDER BY run.run_id"
            ),
            {"status": QueryPurpose.STATUS.value},
        ).all()
        named: dict[str, list[str]] = {}
        for run_id, _source, _at, event_id in runs:
            named[str(run_id)] = [
                str(r[0])
                for r in conn.execute(
                    text(
                        "SELECT ref FROM event_refs WHERE event_id = :e AND position > 0 "
                        "AND type = 'query.registered' AND ref LIKE 'rf:%'"
                    ),
                    {"e": str(event_id)},
                )
            ]
    every = sorted({w for ws in named.values() for w in ws})
    by_source = last_checked_by_source(project, every)
    return [
        str(run_id)
        for run_id, source, at, _ in runs
        if any(by_source.get(str(source), {}).get(w, "") < str(at) for w in named[str(run_id)])
    ]


def match_keys(ids: Identifiers) -> list[tuple[str, str]]:
    """The (kind, value) pairs a record or work is matched by."""
    keys: list[tuple[str, str]] = []
    if ids.doi:
        keys.append(("doi", ids.doi))
    if ids.openalex:
        keys.append(("openalex", ids.openalex))
    if ids.arxiv:
        keys.append(("arxiv", ids.arxiv))
    return keys


class Resolver:
    """Attributes status records to the works of one lookup by their identifiers."""

    def __init__(self, works: Iterable[Work]) -> None:
        self._index: dict[tuple[str, str], set[str]] = {}
        for work in works:
            for key in match_keys(work.identifiers):
                self._index.setdefault(key, set()).add(work.id)

    def work_for(self, target: Identifiers) -> str | None:
        found: set[str] = set()
        for key in match_keys(target):
            found |= self._index.get(key, set())
        return next(iter(found)) if len(found) == 1 else None


def crossref_doi(work: Work) -> str | None:
    """The DOI to look a work up by in Crossref: its own, unless it is a DataCite arXiv DOI."""
    doi = work.identifiers.doi
    if doi and not doi.startswith(DATACITE_ARXIV_PREFIX):
        return doi
    return None


def openalex_handle(work: Work) -> tuple[str, str] | None:
    """How OpenAlex is asked about a work: (`openalex` | `doi`, value), best handle first."""
    ids = work.identifiers
    if ids.openalex:
        return ("openalex", ids.openalex)
    if ids.doi:
        return ("doi", ids.doi)
    if ids.arxiv:
        return ("doi", f"{DATACITE_ARXIV_PREFIX}arxiv.{ids.arxiv}")
    return None


def groups(pairs: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """`pairs` in lookup batches of at most `CHASE_CHUNK`."""
    return [pairs[i : i + CHASE_CHUNK] for i in range(0, len(pairs), CHASE_CHUNK)]


def openalex_batches(works: Sequence[Work]) -> list[StatusBatch]:
    """OpenAlex lookups of `works`: `openalex:` ids and `doi:` values, batched."""
    by_kind: dict[str, list[tuple[str, str]]] = {"openalex": [], "doi": []}
    for work in works:
        handle = openalex_handle(work)
        if handle is not None:
            by_kind[handle[0]].append((work.id, handle[1]))
    return [
        StatusBatch(
            source="openalex",
            kind=QueryKind.FILTER,
            text=f"{kind}:{'|'.join(value for _, value in group)}",
            work_ids=tuple(work_id for work_id, _ in group),
        )
        for kind, pairs in by_kind.items()
        for group in groups(pairs)
    ]
