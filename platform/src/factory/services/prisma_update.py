"""The PRISMA 2020 update flow of a living review (living-B, R-103).

`prisma_update` counts one update: the records whose first identification lies between two
snapshots (or a snapshot and now), through the same boxes as `prisma_flow`, besides the
"studies included in the previous version". Every number is computed from the events.

Time. A provenance row of a run is dated by the run's first `search.records_parsed` event (event
ids are the global order). A canonical work (a merge group) belongs to the update in which the
earliest dated row over all its records, absorbed ones included, lies; it is `new` there. A
record of the update is a dated row of a non-probe query in the window, whether its work is new
or was found by an earlier update.

Boxes (identities as `PrismaFlow`, over the update's new works):
- `identified_databases[source]` counts the update's database records of search queries;
  `identified_other[method]` counts new works without a database record up to the cut-off, by the
  first method in the order citation-chase, seed-admission, hand-search, supplied (decision 38
  item 6, spec reconciliation 2). `supplied` and `seed-admission` are not search finds
  (decision 54) but are counted here under "other", as in `prisma_flow`.
- `duplicates_removed` = database records of the update less its new works that have one, so a
  re-find of an earlier work, and a second record of a new work, are duplicates.
- Outcomes (`excluded`, `pending`, `included`, `full_text`) are the current outcomes of the new
  works; only the identification counts are as of the cut-off.

`total_included` is the cumulative flow's current inclusion count; it need not equal
`previous_included + included` (an earlier work may have changed), and `changed_previous` lists
the works outside the update whose inclusion differs from the previous snapshot.

A closed update (the window between two consecutive snapshots) is pinned in the closing
snapshot's blob when it is taken and read back from it, so later decisions, merges and cycles
cannot rewrite it; only the open window, and a window spanning several snapshots, are computed
from the events as they stand.

Invariants: a window is one snapshot pair, `since < until`; unknown snapshot ids are refused
(fields `since`, `until`) and nothing is written. The agent view drops held-out works from
`changed_previous` (`agent_update`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pydantic import Field, model_validator
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.living import SnapshotRecorded
from factory.model.work import ProvenanceMethod
from factory.services.agreement import Outcome, exclusion_criteria, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.prisma import (
    NOT_RUN_BOXES,
    OTHER_METHODS,
    UNSPECIFIED,
    FullTextBoxes,
    full_text_boxes,
    prisma_flow,
)
from factory.services.seeds import held_out_work_ids
from factory.services.snapshots import (
    SnapshotBlob,
    included_work_ids,
    snapshot_blob,
    snapshots,
)

_CHUNK = 500
_RUN_TIME = (
    "(SELECT ref AS run_id, MIN(event_id) AS t FROM event_refs"
    " WHERE type = 'search.records_parsed' GROUP BY ref)"
)
"""Each run's date: its first `search.records_parsed` event."""
_FROM = (
    "FROM provenance p JOIN queries q ON q.query_id = p.query_id AND q.purpose != 'probe'"
    f" JOIN {_RUN_TIME} rt ON rt.run_id = p.run_id"
)


class UpdateFlow(StrictModel):
    """One update's PRISMA flow (see the module docstring)."""

    since_snapshot: str | None
    until_snapshot: str | None
    since_event: str | None
    until_event: str | None
    previous_included: int = Field(ge=0)
    identified_databases: dict[str, int]
    identified_other: dict[str, int]
    duplicates_removed: int = Field(ge=0)
    screened: int = Field(ge=0)
    excluded: dict[str, int]
    pending: int = Field(ge=0)
    included: int = Field(ge=0)
    full_text: FullTextBoxes = Field(default_factory=lambda: NOT_RUN_BOXES)
    total_included: int = Field(ge=0)
    changed_previous: tuple[str, ...] = ()
    provisional: bool

    @property
    def excluded_total(self) -> int:
        return sum(self.excluded.values())

    @model_validator(mode="after")
    def _identities_hold(self) -> UpdateFlow:
        identified = sum(self.identified_databases.values()) + sum(self.identified_other.values())
        if identified - self.duplicates_removed != self.screened:
            raise ValueError("identified less duplicates must equal screened")
        if self.excluded_total + self.pending + self.included != self.screened:
            raise ValueError("excluded, pending and included must sum to screened")
        if self.provisional != (self.pending > 0):
            raise ValueError("an update flow is provisional exactly while works are pending")
        return self


@dataclass(frozen=True)
class _Facts:
    works: frozenset[str]
    """The new canonical works of the update."""
    database_records: dict[str, int]
    with_database: frozenset[str]
    other: dict[str, str]
    """Each new work without a database record, mapped to its method."""

    @property
    def duplicates(self) -> int:
        return sum(self.database_records.values()) - len(self.with_database)


def prisma_update(
    project: Project,
    *,
    since: str | None = None,
    until: str | None = None,
    whole_log: bool = False,
) -> UpdateFlow:
    """The update flow between snapshots `since` and `until` (ids).

    `until=None` is now. `since=None` is the snapshot before `until`, or the last snapshot when
    `until` is also None; with no such snapshot the window opens at the start of the log.
    `whole_log` opens it at the start regardless (the update then equals the cumulative flow)."""
    project.index.sync()
    recorded = snapshots(project)
    start, end = _window(recorded, since, until, whole_log)
    if end is not None and not whole_log and _consecutive(recorded, start, end):
        pinned = _blob(project, end).update
        if pinned is not None:
            return UpdateFlow.model_validate(pinned)
    return compute_update(
        project,
        start,
        None if end is None else end.cutoff_event,
        None if end is None else end.snapshot_id,
    )


def pin_update(project: Project, snapshot_id: str, cutoff_event: str) -> UpdateFlow:
    """The update a snapshot closes, computed as the events stand at its cut-off: the window from
    the previous snapshot (the one before `snapshot_id` if recorded, else the last) to it. A
    snapshot stores this in its blob, so the closed update is read back, never recomputed."""
    recorded = snapshots(project)
    ids = [item.snapshot_id for item in recorded]
    if snapshot_id in ids:
        index = ids.index(snapshot_id)
        start = recorded[index - 1] if index > 0 else None
    else:
        start = recorded[-1] if recorded else None
    return compute_update(project, start, cutoff_event, snapshot_id)


def _consecutive(
    recorded: Sequence[SnapshotRecorded], start: SnapshotRecorded | None, end: SnapshotRecorded
) -> bool:
    """Whether the window is exactly the update `end` closed (a pinned one)."""
    ids = [item.snapshot_id for item in recorded]
    index = ids.index(end.snapshot_id)
    return (
        (start is None)
        if index == 0
        else (start is not None and start.snapshot_id == ids[index - 1])
    )


def compute_update(
    project: Project,
    start: SnapshotRecorded | None,
    until_event: str | None,
    until_snapshot: str | None,
) -> UpdateFlow:
    """The update flow of the window from snapshot `start` to `until_event`, from current events.
    Identification counts are as of `until_event`; outcomes are those of now, so a window that is
    closed is read from its pinned blob and only the open window comes here."""
    since_event = None if start is None else start.cutoff_event
    facts = _facts(project, since_event, until_event)
    new = facts.works
    outcomes = final_outcomes(project)
    criteria = exclusion_criteria(project)
    excluded: dict[str, int] = {}
    included = pending = 0
    for work in new:
        outcome = outcomes[work]
        if outcome is Outcome.INCLUDED:
            included += 1
        elif outcome is Outcome.PENDING:
            pending += 1
        else:
            criterion = criteria.get(work) or UNSPECIFIED
            excluded[criterion] = excluded.get(criterion, 0) + 1
    other = {method.value: 0 for method in OTHER_METHODS}
    for method in facts.other.values():
        other[method] += 1
    flow = prisma_flow(project)
    current = set(included_work_ids(project, flow))
    previous_blob: SnapshotBlob | None = None if start is None else _blob(project, start)
    previous_ids = set() if previous_blob is None else set(previous_blob.included_ids)
    changed = sorted((previous_ids - current) | ((current - new) - previous_ids))
    return UpdateFlow(
        since_snapshot=None if start is None else start.snapshot_id,
        until_snapshot=until_snapshot,
        since_event=since_event,
        until_event=until_event,
        previous_included=_included_count(previous_blob),
        identified_databases=dict(sorted(facts.database_records.items())),
        identified_other=other,
        duplicates_removed=facts.duplicates,
        screened=len(new),
        excluded=dict(sorted(excluded.items())),
        pending=pending,
        included=included,
        full_text=full_text_boxes(project, only=new),
        total_included=len(current) if flow.included_in_review is None else flow.included_in_review,
        changed_previous=tuple(changed),
        provisional=pending > 0,
    )


def update_work_ids(
    project: Project, since_event: str | None, until_event: str | None
) -> tuple[set[str], int]:
    """The canonical works new in the window `(since_event, until_event]` and the window's
    duplicate record count. Queries by event-id range over the provenance rows; the corpus is not
    loaded."""
    project.index.sync()
    facts = _facts(project, since_event, until_event)
    return set(facts.works), facts.duplicates


def agent_update(project: Project, flow: UpdateFlow) -> UpdateFlow:
    """`flow` as an agent may read it: held-out works never listed (decision 43, R-20)."""
    hidden = held_out_work_ids(project)
    return flow.model_copy(
        update={"changed_previous": tuple(w for w in flow.changed_previous if w not in hidden)}
    )


# --- the window ---


def _window(
    recorded: Sequence[SnapshotRecorded], since: str | None, until: str | None, whole_log: bool
) -> tuple[SnapshotRecorded | None, SnapshotRecorded | None]:
    by_id = {item.snapshot_id: i for i, item in enumerate(recorded)}
    issues: list[ValidationIssue] = []
    if since is not None and since not in by_id:
        issues.append(ValidationIssue("since", "unknown snapshot"))
    if until is not None and until not in by_id:
        issues.append(ValidationIssue("until", "unknown snapshot"))
    if issues:
        raise FactoryValidationError(issues)
    end = None if until is None else recorded[by_id[until]]
    if whole_log:
        start = None
    elif since is not None:
        start = recorded[by_id[since]]
    elif until is not None:
        start = recorded[by_id[until] - 1] if by_id[until] > 0 else None
    else:
        start = recorded[-1] if recorded else None
    if start is not None and end is not None and by_id[start.snapshot_id] >= by_id[end.snapshot_id]:
        raise FactoryValidationError([ValidationIssue("since", "must be an earlier snapshot")])
    return start, end


def _blob(project: Project, item: SnapshotRecorded) -> SnapshotBlob:
    return snapshot_blob(project, item.snapshot_id)


def _included_count(blob: SnapshotBlob | None) -> int:
    if blob is None:
        return 0
    flow = blob.prisma
    return flow.included_in_review if flow.included_in_review is not None else flow.included


# --- the facts ---


def _facts(project: Project, since: str | None, until: str | None) -> _Facts:
    bounds = {"since": since, "until": until}
    primary_of: dict[str, str] = {}
    members_of: dict[str, set[str]] = {}
    for merge in active_merges(project):
        members_of[merge.primary] = {merge.primary, *merge.absorbed}
        for absorbed in merge.absorbed:
            primary_of[absorbed] = merge.primary
    with project.index.connect() as conn:
        first = conn.execute(
            text(
                f"SELECT p.work_id {_FROM} WHERE (:until IS NULL OR rt.t <= :until)"
                " GROUP BY p.work_id HAVING (:since IS NULL OR MIN(rt.t) > :since)"
            ),
            bounds,
        ).all()
        candidates = {str(r[0]) for r in first}
        groups = {primary_of.get(w, w) for w in candidates}
        members = {g: members_of.get(g, {g}) for g in groups}
        # A group is new only if none of its records was first found before the window.
        older = _older(conn, since, set().union(*members.values()) - candidates)
        new_groups = {g for g, ids in members.items() if not ids & older}
        owner = {w: g for g in new_groups for w in members[g]}
        rows = _methods(conn, set(owner), until)
        records = conn.execute(
            text(
                f"SELECT p.source, COUNT(*) {_FROM} WHERE p.method = :database"
                " AND q.purpose = 'search' AND (:since IS NULL OR rt.t > :since)"
                " AND (:until IS NULL OR rt.t <= :until) GROUP BY p.source"
            ),
            {**bounds, "database": ProvenanceMethod.DATABASE.value},
        ).all()
    methods: dict[str, set[str]] = {g: set() for g in new_groups}
    for work_id, method in rows:
        methods[owner[work_id]].add(method)
    with_database = frozenset(
        g for g, found in methods.items() if ProvenanceMethod.DATABASE.value in found
    )
    other: dict[str, str] = {}
    for group, found in methods.items():
        if group not in with_database:
            chosen = next((m.value for m in OTHER_METHODS if m.value in found), None)
            if chosen is not None:
                other[group] = chosen
    return _Facts(
        works=frozenset(new_groups),
        database_records={str(source): int(count) for source, count in records},
        with_database=with_database,
        other=other,
    )


def _older(conn: Connection, since: str | None, ids: set[str]) -> set[str]:
    """The works among `ids` with a dated row at or before `since`."""
    if since is None or not ids:
        return set()
    found: set[str] = set()
    sql = text(f"SELECT DISTINCT p.work_id {_FROM} WHERE rt.t <= :since AND p.work_id IN :ids")
    for chunk in _chunks(sorted(ids)):
        found.update(
            str(r[0])
            for r in conn.execute(
                sql.bindparams(bindparam("ids", expanding=True)), {"since": since, "ids": chunk}
            ).all()
        )
    return found


def _methods(conn: Connection, ids: set[str], until: str | None) -> list[tuple[str, str]]:
    """The distinct (work, method) provenance rows of `ids` dated at or before `until`."""
    out: list[tuple[str, str]] = []
    sql = text(
        f"SELECT DISTINCT p.work_id, p.method {_FROM}"
        " WHERE p.work_id IN :ids AND (:until IS NULL OR rt.t <= :until)"
    ).bindparams(bindparam("ids", expanding=True))
    for chunk in _chunks(sorted(ids)):
        out.extend(
            (str(r[0]), str(r[1])) for r in conn.execute(sql, {"until": until, "ids": chunk})
        )
    return out


def _chunks(items: list[str]) -> Iterable[list[str]]:
    for i in range(0, len(items), _CHUNK):
        yield items[i : i + _CHUNK]
