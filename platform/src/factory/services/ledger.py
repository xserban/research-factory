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
- A confirmation is a person's own act, by CLI or elicitation, never an agent's or a relay. Only an
  owner confirms for another person, and only for one the lab holds as deactivated, with a reason.
- One event that changes the rows, the unmapped list or the map stales every confirmation. An event
  that credits nobody (a person's task claim, a `system` page) leaves the hash as it was.
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import select, text

from factory.canonical import canonical_json
from factory.clock import parse_ts
from factory.events.envelope import Actor
from factory.index.ledger import LEDGER_TABLES
from factory.index.members import MEMBER_TABLES, any_grant
from factory.model.ledger import (
    LEDGER_CONFIRMED,
    MAP_VERSION,
    PEOPLE_ONLY,
    AgentRow,
    Confirmation,
    CreditRole,
    Ledger,
    LedgerConfirmed,
    LedgerReport,
    PersonRow,
    map_entry,
)
from factory.model.screening import Channel
from factory.services.access import Permission, authorize
from factory.services.context import Principal, Project
from factory.services.lab import lab_exists, open_lab, payload_of, refuse, user_record

EMPTY_NOTICE = "no contribution has been recorded on this project yet"

_ROWS = text(
    "SELECT type, actor_kind, actor_id, user, model, skill, COUNT(*), MIN(ts), MAX(ts) "
    "FROM events "
    "WHERE type != :confirmed "
    "AND NOT (type LIKE 'member.%' AND id NOT IN (SELECT event_id FROM member_events)) "
    "AND NOT (type = 'budget.set' AND id NOT IN (SELECT event_id FROM budgets)) "
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


def confirmations(project: Project) -> dict[str, Confirmation]:
    """Each person's latest confirmation, by user, and whether it pins the ledger as it stands."""
    return _confirmations(project, ledger(project))


def _confirmations(project: Project, current: Ledger) -> dict[str, Confirmation]:
    table = LEDGER_TABLES.confirmations
    with project.index.connect() as conn:
        rows = conn.execute(
            select(table.c.user, table.c.ledger_hash, table.c.map_version).order_by(table.c.user)
        ).all()
    return {
        str(user): Confirmation(
            ledger_hash=str(pinned),
            current=pinned == current.ledger_hash and version == current.map_version,
        )
        for user, pinned, version in rows
    }


def ledger_report(project: Project) -> LedgerReport:
    """The ledger with its confirmations: empty, with a notice, on a fresh project."""
    current = ledger(project)
    notice = EMPTY_NOTICE if not current.named else None
    return LedgerReport(
        ledger=current, confirmations=_confirmations(project, current), notice=notice
    )


def confirm_ledger(
    project: Project, actor: Actor, *, user: str | None = None, reason: str | None = None
) -> LedgerReport:
    """Pin the ledger as it stands to `user` (the actor by default) and return what was confirmed.

    Refused, with nothing written: to anyone but a person; over an MCP relay; for someone the ledger
    does not name; and for another person unless the actor holds `project:govern`, states a reason,
    and the lab holds that person as deactivated. The ledger is read and the event written under one
    hold of the write lock, so the pin is of the ledger the caller is given."""
    target = actor.user if user is None else user
    with project.writing():
        channel = project.principal.channel
        if actor.kind != "human":
            raise refuse("actor", "only a person confirms the ledger")
        if channel is Channel.MCP:
            raise refuse("channel", "the ledger is confirmed by CLI or elicitation, not a relay")
        if target == actor.user:
            if reason is not None:
                raise refuse("reason", "a reason is for confirming on another person's behalf")
        else:
            _require_on_behalf(project, actor, target, reason)
        current = ledger(project)
        if target not in current.named:
            raise refuse("user", f"the ledger does not name {target}")
        payload = payload_of(
            LedgerConfirmed,
            user=target,
            ledger_hash=current.ledger_hash,
            map_version=current.map_version,
            channel=channel,
            reason=reason,
        )
        project.record([project.events.make(LEDGER_CONFIRMED, payload, actor)])
        return ledger_report(project)


def _require_on_behalf(project: Project, actor: Actor, user: str, reason: str | None) -> None:
    if reason is None:
        raise refuse("reason", "confirming for another person needs a reason")
    settings = project.settings
    if not lab_exists(settings):
        raise refuse("user", "only a deactivated user's entry is confirmed by an owner")
    lab = open_lab(settings, session=project.session, clock=project.clock)
    principal = Principal(actor.user, actor.credential, project.principal.channel)
    authorize(project, principal, actor.kind, Permission.PROJECT_GOVERN, lab=lab)
    record = user_record(lab, user)
    if record is None or record.active:
        raise refuse("user", "only a deactivated user's entry is confirmed by an owner")


def is_team_project(project: Project) -> bool:
    """Whether people share the project: it is hosted, or a grant has counted. A single researcher's
    stage-0 project has no one to confirm for (acceptance 1)."""
    if project.is_hosted():
        return True
    with project.index.connect() as conn:
        return any_grant(conn, MEMBER_TABLES)


def unconfirmed(project: Project) -> list[str]:
    """Everyone the ledger names who has no confirmation of it as it stands."""
    current = ledger(project)
    confirmed = _confirmations(project, current)
    return [user for user in current.named if _status(user, confirmed) != "confirmed"]


def _when(value: datetime) -> str:
    return value.date().isoformat()


def _status(user: str, confirmed: Mapping[str, Confirmation]) -> str:
    entry = confirmed.get(user)
    if entry is None:
        return "unconfirmed"
    return "confirmed" if entry.current else "stale"


def _credit_table(rows: Sequence[PersonRow]) -> list[str]:
    lines = ["| Person | CRediT role | Events | First | Last |", "| --- | --- | --- | --- | --- |"]
    lines += [
        f"| {r.user} | {r.role.value} | {r.events} | {_when(r.first)} | {_when(r.last)} |"
        for r in rows
    ]
    return lines


def _agent_table(rows: Sequence[AgentRow]) -> list[str]:
    lines = [
        "| Delegating user | Agent role | Model | Skill | Would map to | Events |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {r.user} | {r.agent_role} | {r.model} | {r.skill} | "
        f"{r.role.value if r.role is not None else 'no role'} | {r.events} |"
        for r in rows
    ]
    return lines


def render_ledger(report: Ledger, confirmed: Mapping[str, Confirmation]) -> str:
    """The CRediT statement, the AI-assistance statement, the map version, the hash and each named
    person's confirmation status, as Markdown. A ledger with no rows is one notice."""
    head = ["# Contribution ledger", ""]
    tail = ["", f"Map version: {report.map_version}", f"Ledger hash: {report.ledger_hash}"]
    if not report.named and not report.unmapped:
        return "\n".join([*head, EMPTY_NOTICE.capitalize() + ".", *tail]) + "\n"
    lines = [*head, "## CRediT statement", ""]
    lines += _credit_table(report.people) if report.people else ["No person has a CRediT role."]
    lines += ["", "## AI-assistance statement", ""]
    lines += _agent_table(report.agents) if report.agents else ["No agent contributed."]
    if report.unmapped:
        lines += ["", "## Unmapped event types", ""]
        lines += [f"- {name}: {count}" for name, count in report.unmapped.items()]
    lines += ["", "## Confirmation", ""]
    lines += [f"- {user}: {_status(user, confirmed)}" for user in report.named]
    return "\n".join([*lines, *tail]) + "\n"
