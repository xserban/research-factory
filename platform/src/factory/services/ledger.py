"""The contribution ledger: who did what, derived from the log (slice 5 ruling 16, R-112).

The rows are one aggregate query over the `events` table, which holds every event of the log with
its actor, so the ledger never holds the log in memory, only a counter per key. `ledger` is the
contribution ledger; `benchmark_ledger` is slice 6's (decision 75).

Invariants:
- Nothing is typed: every count is computed from events (R-05).
- A person's event counts for that person. An agent's event counts under its delegating user in
  the AI-assistance rows, never in the CRediT table. A `system` event credits nobody: the platform
  wrote it, and the person or agent who started the work has their own event.
- The hash is of the rows, the unmapped list and the map version, never of a rendering, so it is
  the same after a rebuild.
- `ledger.confirmed` is outside the ledger altogether (see `model/ledger.py`).
- A governance event the fold refused (a hand-written grant from someone who holds no `owner`)
  stays in the log and credits nobody.
"""

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from sqlalchemy import text

from factory.canonical import canonical_json
from factory.clock import parse_ts
from factory.model.ledger import (
    LEDGER_CONFIRMED,
    MAP_VERSION,
    PEOPLE_ONLY,
    AgentRow,
    CreditRole,
    Ledger,
    PersonRow,
    map_entry,
)
from factory.services.context import Project

_ROWS = text(
    "SELECT type, actor_kind, actor_id, user, model, skill, COUNT(*), MIN(ts), MAX(ts) "
    "FROM events "
    "WHERE type != :confirmed "
    "AND NOT (type LIKE 'member.%' AND id NOT IN (SELECT event_id FROM member_events)) "
    "GROUP BY type, actor_kind, actor_id, user, model, skill"
)


@dataclass
class _Tally:
    """The counters of one row of the ledger."""

    first: str
    last: str
    by_type: dict[str, int] = field(default_factory=dict)

    def add(self, event_type: str, count: int, first: str, last: str) -> None:
        self.by_type[event_type] = self.by_type.get(event_type, 0) + count
        self.first = min(self.first, first)
        self.last = max(self.last, last)

    @property
    def events(self) -> int:
        return sum(self.by_type.values())


_K = TypeVar("_K")
_PersonKey = tuple[str, CreditRole]
_AgentKey = tuple[str, str, str | None, str | None, CreditRole | None]


def _tally(tallies: dict[_K, _Tally], key: _K, row: Sequence[Any]) -> None:
    first, last = str(row[7]), str(row[8])
    tallies.setdefault(key, _Tally(first, last)).add(str(row[0]), int(row[6]), first, last)


def ledger(project: Project) -> Ledger:
    """The ledger as of the log."""
    project.index.sync()
    with project.index.connect() as conn:
        return _fold(conn.execute(_ROWS, {"confirmed": LEDGER_CONFIRMED}))


def _fold(rows: Iterable[Sequence[Any]]) -> Ledger:
    people: dict[_PersonKey, _Tally] = {}
    agents: dict[_AgentKey, _Tally] = {}
    unmapped: dict[str, int] = {}
    for row in rows:
        event_type, kind = str(row[0]), str(row[1])
        entry = map_entry(event_type)
        if entry is None:
            unmapped[event_type] = unmapped.get(event_type, 0) + int(row[6])
        role = None if entry is None else entry[1]
        if kind == "human" and role is not None:
            _tally(people, (str(row[3]), role), row)
        elif kind == "agent":
            credit = None if role in PEOPLE_ONLY else role
            _tally(agents, (str(row[3]), str(row[2]), row[4], row[5], credit), row)
    return _built(people, agents, unmapped)


def _built(
    people: dict[_PersonKey, _Tally], agents: dict[_AgentKey, _Tally], unmapped: dict[str, int]
) -> Ledger:
    person_rows = [
        PersonRow(
            user=user,
            role=role,
            events=tally.events,
            by_type=dict(sorted(tally.by_type.items())),
            first=parse_ts(tally.first),
            last=parse_ts(tally.last),
        )
        for (user, role), tally in sorted(people.items(), key=lambda item: item[0])
    ]
    agent_rows = [
        AgentRow(
            user=user,
            agent_role=agent_role,
            model=model,
            skill=skill,
            role=role,
            events=tally.events,
            by_type=dict(sorted(tally.by_type.items())),
            first=parse_ts(tally.first),
            last=parse_ts(tally.last),
        )
        for (user, agent_role, model, skill, role), tally in sorted(
            agents.items(), key=lambda item: tuple(str(part) for part in item[0])
        )
    ]
    listed = dict(sorted(unmapped.items()))
    return Ledger(
        people=person_rows,
        agents=agent_rows,
        unmapped=listed,
        map_version=MAP_VERSION,
        ledger_hash=_hash(person_rows, agent_rows, listed),
    )


def _hash(people: list[PersonRow], agents: list[AgentRow], unmapped: dict[str, int]) -> str:
    """Plan ruling 3: SHA-256 of the canonical JSON of the rows and the map version."""
    body = canonical_json(
        {
            "agents": [row.model_dump(mode="json") for row in agents],
            "map_version": MAP_VERSION,
            "people": [row.model_dump(mode="json") for row in people],
            "unmapped": dict(unmapped),
        }
    )
    return f"sha256:{hashlib.sha256(body).hexdigest()}"
