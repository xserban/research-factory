"""Discovery record: how each work was found, by which route first, and by whom (slice 4a).

Computed on read, never stored (spec ruling 10). A builder over the projection (ruling 14);
its inputs are:

- `provenance` joined to `queries` (non-probe purposes only: probe lookups never count);
- the `query.registered` events' refs in the `events` table, which name the inbox item a
  supplied lookup resolved and the chase (`chs_`) or snowball (`snw_`) round that planned a
  chase query, so chase and snowball runs are told apart by reference, never by text;
- `search.run_started` events (the surfacing event of a search-run route, and its actor kind);
- `chase_rounds` and `snowball_rounds` (the round event's actor; a snowball round's delegated
  chase round; the snowball direction);
- `inbox_items` (a supplied route's capturing event, actor kind and basis);
- active dedup merges (absorbed works fold into their primary, R-26);
- `final_outcomes` at title/abstract and, with a full-text plan, at full text; and the final
  evidence rows (`final_rows`).

Invariants: the surfacing event of a route is the earliest event naming the work for it (the
run start for search runs, the capture for a supplied link, which precedes its lookup); the
first-surfaced route is the one with the smallest surfacing event id (00-system §4.2: id order
is the global order). Every column of the report sums over first-surfaced routes to the
column's total. Figures are reported, never used to weight anything (ruling 11).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges, canonical_works
from factory.services.extraction_agreement import final_rows
from factory.services.protocol import current_protocol

ActorKind = Literal["human", "agent", "system"]
IDENTIFIED = "identified"
TA_INCLUDED = "ta-included"
FT_INCLUDED = "ft-included"
IN_EVIDENCE = "in-evidence"


class Route(StrEnum):
    DATABASE = "database"
    CHASE_BACKWARD = "chase-backward"
    CHASE_FORWARD = "chase-forward"
    SNOWBALL_BACKWARD = "snowball-backward"
    SNOWBALL_FORWARD = "snowball-forward"
    SEED_ADMISSION = "seed-admission"
    HAND_SEARCH = "hand-search"
    SUPPLIED_HUMAN = "supplied-human"
    SUPPLIED_AGENT = "supplied-agent"
    SUPPLIED_AGENT_KNOWLEDGE = "supplied-agent-knowledge"


class WorkDiscovery(StrictModel):
    work_id: str
    routes: tuple[Route, ...]
    sources: tuple[str, ...]
    first_route: Route
    first_event_id: str
    first_actor_kind: ActorKind


class DiscoveryReport(StrictModel):
    """Counts per level (`levels`): by first-surfaced route, by first surfacer's actor kind,
    and route overlaps (`a+b` keys, works with more than one route, identified level)."""

    levels: tuple[str, ...]
    by_first_route: dict[Route, dict[str, int]]
    by_first_actor: dict[str, dict[str, int]]
    overlaps: dict[str, int]
    totals: dict[str, int]


@dataclass(frozen=True)
class _Surfacing:
    route: Route
    event_id: str
    actor_kind: ActorKind
    source: str


_ROWS = """
SELECT p.work_id, p.method, p.source, p.query_id, q.text, qe.refs,
       rs.id, rs.actor_kind
FROM provenance p
JOIN queries q ON q.query_id = p.query_id AND q.purpose != 'probe'
JOIN events qe ON qe.type = 'query.registered' AND json_extract(qe.refs, '$[0]') = p.query_id
JOIN events rs ON rs.type = 'search.run_started' AND json_extract(rs.refs, '$[0]') = p.run_id
"""


def _kind(value: object) -> ActorKind:
    kind = str(value)
    return "human" if kind == "human" else "agent" if kind == "agent" else "system"


def _surfacings(project: Project) -> dict[str, list[_Surfacing]]:
    """Every (route, surfacing event) per stored work, before merges are folded."""
    project.index.sync()
    out: dict[str, list[_Surfacing]] = {}
    with project.index.connect() as conn:
        snowball = {
            str(r[0]): (str(r[1]), None if r[2] is None else str(r[2]), str(r[3]))
            for r in conn.execute(
                text(
                    "SELECT s.round_id, s.direction, s.chase_round_id, e.actor_kind"
                    " FROM snowball_rounds s JOIN events e ON e.id = s.event_id"
                )
            ).all()
        }
        delegated = {chase: snw for snw, (_d, chase, _k) in snowball.items() if chase is not None}
        chase_actor = {
            str(r[0]): str(r[1])
            for r in conn.execute(
                text(
                    "SELECT c.round_id, e.actor_kind FROM chase_rounds c"
                    " JOIN events e ON e.id = c.event_id"
                )
            ).all()
        }
        items = {
            str(r[0]): (str(r[1]), str(r[2]), None if r[3] is None else str(r[3]))
            for r in conn.execute(
                text("SELECT item_id, added_event_id, actor_kind, basis FROM inbox_items")
            ).all()
        }
        rows = conn.execute(text(_ROWS)).all()
    for work_id, method, source, _query_id, query_text, refs, run_event, run_actor in rows:
        ref_list = [str(r) for r in json.loads(str(refs))]
        surfacing = _route(
            str(method),
            str(source),
            str(query_text),
            ref_list,
            str(run_event),
            _kind(run_actor),
            snowball=snowball,
            delegated=delegated,
            chase_actor=chase_actor,
            items=items,
        )
        out.setdefault(str(work_id), []).append(surfacing)
    return out


def _route(
    method: str,
    source: str,
    query_text: str,
    refs: list[str],
    run_event: str,
    run_actor: ActorKind,
    *,
    snowball: Mapping[str, tuple[str, str | None, str]],
    delegated: Mapping[str, str],
    chase_actor: Mapping[str, str],
    items: Mapping[str, tuple[str, str, str | None]],
) -> _Surfacing:
    if method == "citation-chase":
        snw = next((r for r in refs if r in snowball), None)
        chs = next((r for r in refs if r.startswith("chs_")), None)
        if snw is None and chs is not None:
            snw = delegated.get(chs)
        if snw is not None:
            direction, _chase, actor = snowball[snw]
            route = Route.SNOWBALL_FORWARD if direction == "forward" else Route.SNOWBALL_BACKWARD
            return _Surfacing(route, run_event, _kind(actor), source)
        forward = query_text.startswith("cites:")
        route = Route.CHASE_FORWARD if forward else Route.CHASE_BACKWARD
        actor_kind = (
            _kind(chase_actor[chs]) if chs is not None and chs in chase_actor else run_actor
        )
        return _Surfacing(route, run_event, actor_kind, source)
    if method == "supplied":
        item = next((items[r] for r in refs if r in items), None)
        if item is None:
            # A supplied lookup without an inbox item: its run is the surfacing event.
            kind = "agent" if run_actor == "agent" else "human"
            route = Route.SUPPLIED_AGENT if kind == "agent" else Route.SUPPLIED_HUMAN
            return _Surfacing(route, run_event, run_actor, source)
        added, actor, basis = item
        if actor == "agent":
            knowledge = basis is not None and json.loads(basis).get("kind") == "knowledge"
            route = Route.SUPPLIED_AGENT_KNOWLEDGE if knowledge else Route.SUPPLIED_AGENT
        else:
            route = Route.SUPPLIED_HUMAN
        return _Surfacing(route, added, _kind(actor), source)
    if method == "seed-admission":
        return _Surfacing(Route.SEED_ADMISSION, run_event, "human", source)
    if method == "hand-search":
        return _Surfacing(Route.HAND_SEARCH, run_event, run_actor, source)
    return _Surfacing(Route.DATABASE, run_event, run_actor, source)


def _groups(project: Project) -> dict[str, str]:
    """Each absorbed work mapped to its merge primary."""
    return {
        absorbed: merge.primary for merge in active_merges(project) for absorbed in merge.absorbed
    }


def discovery(project: Project) -> list[WorkDiscovery]:
    """The discovery record of every canonical work, sorted by work id."""
    surfacings = _surfacings(project)
    primary = _groups(project)
    folded: dict[str, list[_Surfacing]] = {}
    for work_id, found in surfacings.items():
        folded.setdefault(primary.get(work_id, work_id), []).extend(found)
    records: list[WorkDiscovery] = []
    for work in sorted(canonical_works(project), key=lambda w: w.id):
        found = folded.get(work.id, [])
        if not found:
            continue
        first: dict[Route, _Surfacing] = {}
        for s in found:
            if s.route not in first or s.event_id < first[s.route].event_id:
                first[s.route] = s
        earliest = min(first.values(), key=lambda s: s.event_id)
        records.append(
            WorkDiscovery(
                work_id=work.id,
                routes=tuple(sorted(first, key=list(Route).index)),
                sources=tuple(sorted({s.source for s in found})),
                first_route=earliest.route,
                first_event_id=earliest.event_id,
                first_actor_kind=earliest.actor_kind,
            )
        )
    return records


def _included(outcomes: Mapping[str, Outcome]) -> set[str]:
    return {w for w, outcome in outcomes.items() if outcome is Outcome.INCLUDED}


def discovery_report(project: Project) -> DiscoveryReport:
    """Per-level counts by first-surfaced route and by first surfacer, with route overlaps."""
    records = discovery(project)
    protocol = current_protocol(project)
    full_text = protocol is not None and protocol.spec.full_text_screening is not None
    primary = _groups(project)
    members: dict[str, set[str]] = {IDENTIFIED: {r.work_id for r in records}}
    members[TA_INCLUDED] = _included(final_outcomes(project))
    if full_text:
        members[FT_INCLUDED] = _included(final_outcomes(project, stage=ScreeningStage.FULL_TEXT))
    members[IN_EVIDENCE] = {primary.get(r.work_id, r.work_id) for r in final_rows(project)}
    levels = tuple(members)
    by_route: dict[Route, dict[str, int]] = {}
    by_actor: dict[str, dict[str, int]] = {}
    totals = dict.fromkeys(levels, 0)
    for record in records:
        for level in levels:
            if record.work_id not in members[level]:
                continue
            _bump(by_route.setdefault(record.first_route, dict.fromkeys(levels, 0)), level)
            _bump(by_actor.setdefault(record.first_actor_kind, dict.fromkeys(levels, 0)), level)
            totals[level] += 1
    return DiscoveryReport(
        levels=levels,
        by_first_route={route: by_route[route] for route in Route if route in by_route},
        by_first_actor=dict(sorted(by_actor.items())),
        overlaps=_overlaps(records),
        totals=totals,
    )


def _bump(counts: dict[str, int], level: str) -> None:
    counts[level] += 1


def _overlaps(records: Iterable[WorkDiscovery]) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in records:
        if len(record.routes) > 1:
            key = "+".join(route.value for route in record.routes)
            out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
