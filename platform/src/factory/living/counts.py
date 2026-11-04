"""Per-source counts of one watch cycle, computed from run events and index rows (slice 4b).

Nothing here is supplied by a caller: `watch.cycle_finished` records what `source_counts` returns,
and a test recomputes it from the events. "Before the cycle" means a run that started before the
cycle did; rows from runs that started after the cycle finished are ignored, so counts do not move
when later cycles add provenance to the same works.

`runs` and `complete_runs` count planned queries, each by its latest run in the cycle, so a failed
attempt that a resume repeated is not counted twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from factory.model.search import QueryPurpose, RunStatus
from factory.model.watch import SourceCounts
from factory.model.work import ProvenanceMethod
from factory.services.context import Project

_CHUNK = 500
_FAR_FUTURE = "9999-12-31T23:59:59.999Z"


@dataclass(frozen=True)
class _CycleRun:
    run_id: str
    query_id: str
    source: str
    seq: int
    status: str
    retrieved: int


def source_counts(project: Project, cycle_id: str) -> tuple[SourceCounts, ...]:
    """The counts of every source the cycle ran, sorted by source name."""
    project.index.sync()
    with project.index.connect() as conn:
        facts = _facts(conn, cycle_id)
        if facts is None:
            return ()
        start, bound, sources, runs = facts
        works = _cycle_works(conn, cycle_id)
        before = _known_before(conn, set(works), start)
        counts: list[SourceCounts] = []
        for source, full_replay in sources:
            latest = _latest_by_query([r for r in runs if r.source == source])
            complete = sum(1 for r in latest if r.status == RunStatus.COMPLETE.value)
            new = sum(1 for w, (first, _) in works.items() if w not in before and first == source)
            dup = sum(
                1
                for w, (first, srcs) in works.items()
                if w not in before and source in srcs and first != source
            )
            disappeared = None
            if full_replay and latest and complete == len(latest):
                disappeared = _disappeared(conn, {r.query_id for r in latest}, start, bound)
            counts.append(
                SourceCounts(
                    source=source,
                    runs=len(latest),
                    complete_runs=complete,
                    retrieved=sum(r.retrieved for r in latest),
                    new_works=new,
                    duplicates_in_cycle=dup,
                    window_missed=None,
                    disappeared=disappeared,
                )
            )
    return tuple(counts)


def new_work_ids(project: Project, cycle_id: str) -> tuple[str, ...]:
    """The works the cycle's runs returned that no earlier run had, sorted."""
    project.index.sync()
    with project.index.connect() as conn:
        facts = _facts(conn, cycle_id)
        if facts is None:
            return ()
        start = facts[0]
        works = _cycle_works(conn, cycle_id)
        before = _known_before(conn, set(works), start)
    return tuple(sorted(w for w in works if w not in before))


def cycle_run_ids(project: Project, cycle_id: str) -> tuple[str, ...]:
    """Every run the cycle grouped, in the order they started."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT run_id FROM watch_cycle_runs WHERE cycle_id = :c ORDER BY seq"),
            {"c": cycle_id},
        ).all()
    return tuple(str(r[0]) for r in rows)


def _facts(
    conn: Connection, cycle_id: str
) -> tuple[str, str, list[tuple[str, bool]], list[_CycleRun]] | None:
    cycle = conn.execute(
        text("SELECT started_at, finished_at FROM watch_cycles WHERE cycle_id = :c"),
        {"c": cycle_id},
    ).one_or_none()
    if cycle is None:
        return None
    sources = [
        (str(s), bool(f))
        for s, f in conn.execute(
            text(
                "SELECT source, full_replay FROM watch_cycle_sources "
                "WHERE cycle_id = :c ORDER BY source"
            ),
            {"c": cycle_id},
        )
    ]
    runs = [
        _CycleRun(str(rid), str(qid), str(src), int(seq), str(status), int(retrieved or 0))
        for rid, qid, src, seq, status, retrieved in conn.execute(
            text(
                "SELECT wr.run_id, wr.query_id, wr.source, wr.seq, r.status, r.retrieved_count "
                "FROM watch_cycle_runs wr JOIN runs r ON r.run_id = wr.run_id "
                "WHERE wr.cycle_id = :c ORDER BY wr.seq"
            ),
            {"c": cycle_id},
        )
    ]
    bound = _FAR_FUTURE if cycle[1] is None else str(cycle[1])
    return str(cycle[0]), bound, sources, runs


def _latest_by_query(runs: list[_CycleRun]) -> list[_CycleRun]:
    latest: dict[str, _CycleRun] = {}
    for run in runs:  # ordered by seq
        latest[run.query_id] = run
    return list(latest.values())


def _cycle_works(conn: Connection, cycle_id: str) -> dict[str, tuple[str, frozenset[str]]]:
    """Each work the cycle's runs returned: the source of its earliest run, and all its sources."""
    first: dict[str, tuple[int, str]] = {}
    sources: dict[str, set[str]] = {}
    for work_id, source, seq in conn.execute(
        text(
            "SELECT p.work_id, wr.source, wr.seq FROM provenance p "
            "JOIN watch_cycle_runs wr ON wr.run_id = p.run_id WHERE wr.cycle_id = :c"
        ),
        {"c": cycle_id},
    ):
        wid = str(work_id)
        if wid not in first or int(seq) < first[wid][0]:
            first[wid] = (int(seq), str(source))
        sources.setdefault(wid, set()).add(str(source))
    return {wid: (first[wid][1], frozenset(sources[wid])) for wid in first}


def _known_before(conn: Connection, work_ids: set[str], start: str) -> set[str]:
    """The given works that have a non-probe provenance row from a run started before `start`."""
    statement = text(
        "SELECT DISTINCT p.work_id FROM provenance p "
        "JOIN runs r ON r.run_id = p.run_id JOIN queries q ON q.query_id = r.query_id "
        "WHERE q.purpose != :probe AND r.started_at < :start AND p.work_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    known: set[str] = set()
    ids = sorted(work_ids)
    for i in range(0, len(ids), _CHUNK):
        for (work_id,) in conn.execute(
            statement,
            {"probe": QueryPurpose.PROBE.value, "start": start, "ids": ids[i : i + _CHUNK]},
        ):
            known.add(str(work_id))
    return known


def _disappeared(conn: Connection, queries: set[str], start: str, bound: str) -> int:
    """Works whose every database provenance (up to `bound`) comes from earlier runs of one
    query of this replay, and which the replay did not return."""
    statement = text(
        "SELECT p.work_id FROM provenance p "
        "JOIN runs r ON r.run_id = p.run_id JOIN queries q ON q.query_id = r.query_id "
        "WHERE p.method = :db AND q.purpose != :probe AND r.started_at <= :bound "
        "GROUP BY p.work_id "
        "HAVING COUNT(DISTINCT r.query_id) = 1 AND MIN(r.query_id) IN :queries "
        "AND MAX(r.started_at) < :start"
    ).bindparams(bindparam("queries", expanding=True))
    rows = conn.execute(
        statement,
        {
            "db": ProvenanceMethod.DATABASE.value,
            "probe": QueryPurpose.PROBE.value,
            "bound": bound,
            "start": start,
            "queries": sorted(queries),
        },
    ).all()
    return len(rows)
