"""The updates view: what entered the corpus since the frozen review, how it grew, and the watch.

Read-only. Every number is computed from events by existing services; nothing is written.

- `baseline` is the first snapshot (`snapshots.snapshots`), its included count read from the blob.
- `open_period` is the window after the last snapshot (`prisma_update.update_work_ids`).
- `additions` are the canonical works new after the baseline cut-off, one row each, newest first.
  Title, year and the title/abstract and full-text states come from the work ledger
  (`flow_ledger`, the service behind `flow_works`); the layer from `work_layers.layers_of`;
  `mined` from the final rows of each registered miner.
- `growth` is one point per snapshot; the update flow is the one pinned in the blob.
- `watch` is `watch.watch_status` joined with the current protocol's `watch_plan`.

Route rule. A work's route is read from its earliest non-probe provenance row (by `at`, then
run id) over the canonical record and every record merged into it. In this order:
1. the run belongs to a watch cycle (`watch_cycle_runs`): `watch`;
2. the query purpose is `supplied`: the inbox item whose resolution used that query
   (`inbox_resolutions`) is `feed` when the hub feed sent it (`feed_sends.inbox_item_id`), else
   `inbox` (the feed's add path writes an ordinary inbox item and resolves it);
3. purpose `chase`: `chase`; purpose `search`: `search`;
4. any other purpose (seed, import, grey, status) or no readable row: `other`.
A cycle run is therefore `watch` whatever its query purpose. `note` is the inbox item's note when
the route is `inbox` or `feed`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Literal

from sqlalchemy import bindparam, text

from factory.clock import parse_ts
from factory.errors import FactoryValidationError
from factory.model.base import StrictModel
from factory.model.extraction import MinerScope
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.extraction_agreement import final_rows
from factory.services.flow_ledger import LedgerRow, flow_ledger
from factory.services.mining import registered_miners
from factory.services.prisma_update import UpdateFlow, update_work_ids
from factory.services.protocol import current_protocol
from factory.services.snapshots import snapshot_blob, snapshots
from factory.services.watch import watch_status
from factory.services.work_layers import layers_of

Route = Literal["inbox", "feed", "watch", "chase", "search", "other"]
_CHUNK = 500


class BaselineView(StrictModel):
    snapshot_id: str
    cutoff_event: str
    recorded_at: datetime | None
    included_count: int
    trigger: str


class OpenPeriod(StrictModel):
    """The works new since the last snapshot."""

    since_snapshot: str | None
    new_works: int
    included_at_title_abstract: int


class AdditionRow(StrictModel):
    work_id: str
    title: str
    year: int | None
    added_at: datetime | None
    route: Route
    note: str | None
    ta_outcome: str | None
    ft_state: str | None
    ft_outcome: str | None
    layer: str | None
    mined: tuple[str, ...]


class GrowthPoint(StrictModel):
    snapshot_id: str
    recorded_at: datetime | None
    included_count: int
    identified: int | None
    screened: int | None
    included: int | None
    identified_databases: dict[str, int] | None
    identified_other: dict[str, int] | None


class WatchSourceView(StrictModel):
    source: str
    mode: str
    interval_days: int
    overlap_days: int | None
    full_replay_every: int | None
    last_cycle: str | None
    last_finished_at: datetime | None
    next_due: datetime | None
    due: bool


class WatchView(StrictModel):
    has_plan: bool
    until: date | None
    snapshot_every: int | None
    open_cycle: str | None
    sources: tuple[WatchSourceView, ...]


class UpdatesView(StrictModel):
    baseline: BaselineView | None
    open_period: OpenPeriod | None
    additions: tuple[AdditionRow, ...]
    growth: tuple[GrowthPoint, ...]
    watch: WatchView


def updates_view(project: Project) -> UpdatesView:
    """The whole updates page as data. Writes nothing (the index sync is the projector's read)."""
    project.index.sync()
    shots = snapshots(project)
    times = _snapshot_times(project)
    ledger = {r.work_id: r for r in flow_ledger(project) if r.canonical_id is None}
    baseline = None
    additions: tuple[AdditionRow, ...] = ()
    open_period = None
    growth: list[GrowthPoint] = []
    for shot in shots:
        blob = snapshot_blob(project, shot.snapshot_id)
        flow = None if blob.update is None else UpdateFlow.model_validate(blob.update)
        growth.append(
            GrowthPoint(
                snapshot_id=shot.snapshot_id,
                recorded_at=times.get(shot.snapshot_id),
                included_count=len(blob.included_ids),
                identified=None
                if flow is None
                else sum(flow.identified_databases.values()) + sum(flow.identified_other.values()),
                screened=None if flow is None else flow.screened,
                included=None if flow is None else flow.included,
                identified_databases=None if flow is None else dict(flow.identified_databases),
                identified_other=None if flow is None else dict(flow.identified_other),
            )
        )
    if shots:
        first = shots[0]
        baseline = BaselineView(
            snapshot_id=first.snapshot_id,
            cutoff_event=first.cutoff_event,
            recorded_at=times.get(first.snapshot_id),
            included_count=growth[0].included_count,
            trigger=first.trigger,
        )
        new, _ = update_work_ids(project, first.cutoff_event, None)
        additions = _rows(project, new, ledger)
        recent, _ = update_work_ids(project, shots[-1].cutoff_event, None)
        open_period = OpenPeriod(
            since_snapshot=shots[-1].snapshot_id,
            new_works=len(recent),
            included_at_title_abstract=sum(
                1 for w in recent if w in ledger and _ta_included(ledger[w])
            ),
        )
    return UpdatesView(
        baseline=baseline,
        open_period=open_period,
        additions=additions,
        growth=tuple(growth),
        watch=_watch(project),
    )


def _ta_included(row: LedgerRow) -> bool:
    return row.ta_outcome is not None and row.ta_outcome.value == "included"


def _snapshot_times(project: Project) -> dict[str, datetime]:
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT snapshot_id, ts FROM snapshots")).all()
    return {str(r[0]): parse_ts(str(r[1])) for r in rows}


def _chunks(items: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), _CHUNK):
        yield items[start : start + _CHUNK]


def _rows(
    project: Project, work_ids: set[str], ledger: dict[str, LedgerRow]
) -> tuple[AdditionRow, ...]:
    if not work_ids:
        return ()
    members_of: dict[str, set[str]] = {}
    for merge in active_merges(project):
        members_of[merge.primary] = {merge.primary, *merge.absorbed}
    owner = {m: w for w in work_ids for m in members_of.get(w, {w})}
    first = _first_provenance(project, owner)
    routes = _Routes.load(project)
    layers = layers_of(project)
    mined = _mined(project)
    out: list[AdditionRow] = []
    for work_id in sorted(work_ids):
        row = ledger.get(work_id)
        found = first.get(work_id)
        route: Route = "other"
        note: str | None = None
        at: datetime | None = None
        if found is not None:
            at = parse_ts(found[0])
            route, note = routes.of(found[1], found[2])
        layer = layers.get(work_id)
        out.append(
            AdditionRow(
                work_id=work_id,
                title="" if row is None else row.title,
                year=None if row is None else row.year,
                added_at=at,
                route=route,
                note=note,
                ta_outcome=None if row is None or row.ta_outcome is None else row.ta_outcome.value,
                ft_state=None if row is None else row.ft_state,
                ft_outcome=None if row is None else row.ft_outcome,
                layer=None if layer is None else layer.layer,
                mined=tuple(sorted(n for n, works in mined.items() if work_id in works)),
            )
        )
    out.sort(key=lambda r: (r.added_at is not None, r.added_at, r.work_id), reverse=True)
    return tuple(out)


def _first_provenance(project: Project, owner: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    """Per canonical work: (at, run_id, query_id) of its earliest non-probe provenance row."""
    best: dict[str, tuple[str, str, str]] = {}
    members = sorted(owner)
    with project.index.connect() as conn:
        for chunk in _chunks(members):
            rows = conn.execute(
                text(
                    "SELECT p.work_id, p.at, p.run_id, p.query_id FROM provenance p"
                    " JOIN queries q ON q.query_id = p.query_id AND q.purpose != 'probe'"
                    " WHERE p.work_id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": list(chunk)},
            ).all()
            for member, at, run_id, query_id in rows:
                key = owner[str(member)]
                cand = (str(at), str(run_id), str(query_id))
                if key not in best or cand < best[key]:
                    best[key] = cand
    return best


class _Routes:
    def __init__(
        self,
        cycle_runs: set[str],
        purposes: dict[str, str],
        items: dict[str, tuple[str, str | None]],
        fed: set[str],
    ) -> None:
        self._cycle_runs = cycle_runs
        self._purposes = purposes
        self._items = items
        self._fed = fed

    @classmethod
    def load(cls, project: Project) -> _Routes:
        with project.index.connect() as conn:
            cycle_runs = {
                str(r[0]) for r in conn.execute(text("SELECT run_id FROM watch_cycle_runs")).all()
            }
            purposes = {
                str(r[0]): str(r[1])
                for r in conn.execute(text("SELECT query_id, purpose FROM queries")).all()
            }
            items = {
                str(r[0]): (str(r[1]), None if r[2] is None else str(r[2]))
                for r in conn.execute(
                    text(
                        "SELECT r.query_id, i.item_id, i.note FROM inbox_resolutions r"
                        " JOIN inbox_items i ON i.item_id = r.item_id ORDER BY r.event_id"
                    )
                ).all()
            }
            fed = {
                str(r[0]) for r in conn.execute(text("SELECT inbox_item_id FROM feed_sends")).all()
            }
        return cls(cycle_runs, purposes, items, fed)

    def of(self, run_id: str, query_id: str) -> tuple[Route, str | None]:
        if run_id in self._cycle_runs:
            return "watch", None
        purpose = self._purposes.get(query_id)
        if purpose == "supplied":
            item = self._items.get(query_id)
            if item is None:
                return "inbox", None
            return ("feed" if item[0] in self._fed else "inbox"), item[1]
        if purpose == "chase":
            return "chase", None
        if purpose == "search":
            return "search", None
        return "other", None


def _mined(project: Project) -> dict[str, set[str]]:
    """Miner name -> works with a final row of that miner."""
    found: dict[str, set[str]] = {}
    for name in sorted({m.name for m in registered_miners(project)}):
        try:
            rows = final_rows(project, scope=MinerScope(name))
        except FactoryValidationError:
            continue
        if rows:
            found[name] = {r.work_id for r in rows}
    return found


def _watch(project: Project) -> WatchView:
    status = watch_status(project)
    current = current_protocol(project)
    plan = None if current is None else current.spec.watch_plan
    declared = {} if plan is None else {s.source: s for s in plan.sources}
    sources = tuple(
        WatchSourceView(
            source=s.source,
            mode=s.mode,
            interval_days=s.interval_days,
            overlap_days=None if s.source not in declared else declared[s.source].overlap_days,
            full_replay_every=None
            if s.source not in declared
            else declared[s.source].full_replay_every,
            last_cycle=s.last_cycle,
            last_finished_at=s.last_finished_at,
            next_due=s.next_due,
            due=s.due,
        )
        for s in status.sources
    )
    return WatchView(
        has_plan=status.has_plan,
        until=status.until,
        snapshot_every=None if plan is None else plan.snapshot_every,
        open_cycle=status.open_cycle,
        sources=sources,
    )
