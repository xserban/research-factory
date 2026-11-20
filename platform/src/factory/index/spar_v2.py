"""Projection of the agentic spar, engine v2 (plan spar-night N6): role starts, readings, argument
checks and the coverage sweep, and the derived plan of a v2 request.

Tables: `spar_roles` (one row per role run, from `spar.role_started`), `spar_readings` (what each
reader recorded and covered), `argument_checks` (the critic's checks; every one kept, the latest of
an argument stands) and `spar_coverage` (one sweep per request).

The plan of a request (`plan`) is derived from these rows and the sheet and the runs; nothing of it
is stored. Roles run in order: search, one read per planned paper, against, for, critic, cover.

Folded only if (a hand-written event failing a guard changes nothing on rebuild):
- `spar.role_started`: system actor; a v2 request; the stage of a known run is `spar2-<role>`; the
  role is the next undone one of the plan, no role run is open, and the request's session budget
  is not spent (readers: a reader session left; a fixed role: its first session or a retry of the
  separate allowance, `FIXED_RETRIES`).
- `spar.reading_recorded`, `sheet.argument_checked`, `spar.coverage_recorded`: an agent actor and a
  role row of that run (and request) for the matching role; a reading of a planned work, once; a
  check of a folded argument of the request's sheet; a sweep over papers no source proposed, once.
  A check never touches `sheet_ratings`: a rating stays a human act.

Handlers are total: a failure at any point folds nothing and never raises, on rebuild too.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.errors import FactoryError
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.spar_v2 import (
    SheetArgumentChecked,
    SparCoverageRecorded,
    SparReadingRecorded,
    SparRoleStarted,
)

DEFAULT_MAX_SESSIONS = 15
"""Role sessions a v2 request may start unless it says otherwise."""
FIXED_ROLES = 5
"""Search, against, for, critic and cover: one session each; the readers share the rest."""
MIN_MAX_SESSIONS = FIXED_ROLES
FIXED_RETRIES = 2
"""Retries of the fixed roles a request may start, over all five together, beyond the cap: the
readers' sessions (retries included) are bounded by `max_sessions - 5` and a reader's retry never
takes a fixed role's session; a fixed role that fails is retried within this separate allowance."""


def stage_of(role: str) -> str:
    return f"spar2-{role}"


@dataclass(frozen=True)
class Slot:
    role: str
    work_id: str | None = None


@dataclass(frozen=True)
class Plan:
    request_id: str
    max_sessions: int
    sheet_id: str | None
    slots: tuple[Slot, ...]
    done: tuple[bool, ...]
    readers_cut: tuple[str, ...]
    """Tier-1 papers left unread because the session budget leaves no session for them."""
    sessions: int
    """Role runs started for the request, retries included."""
    open_run: str | None
    next_index: int | None
    """Index in `slots` of the first slot not done; None when every slot is done."""
    failed: bool
    """The next slot has a run that has ended without finishing the slot."""
    reader_sessions: int = 0
    """Reader runs started, retries included; at most `max_sessions - 5`."""
    fixed_retries: int = 0
    """Retries started of the fixed roles (runs beyond the first of a role); at most
    `FIXED_RETRIES`."""
    role_sessions: tuple[tuple[str, int], ...] = ()
    """Runs started per fixed role."""

    def can_start(self, slot: Slot) -> bool:
        """Whether the budget allows a run (the first or a retry) of `slot`: a reader needs a
        reader session left, a fixed role its first session or a retry of the allowance."""
        if slot.role == "read":
            return self.reader_sessions < max(self.max_sessions - FIXED_ROLES, 0)
        if dict(self.role_sessions).get(slot.role, 0) == 0:
            return True
        return self.fixed_retries < FIXED_RETRIES

    @property
    def next(self) -> Slot | None:
        return None if self.next_index is None else self.slots[self.next_index]

    @property
    def state(self) -> str:
        if self.open_run is not None:
            return "taken"
        if self.next_index is None:
            return "done"
        return "failed" if self.failed else "open"


class SparV2Tables:
    def __init__(self, roles: Table, readings: Table, checks: Table, coverage: Table) -> None:
        self.roles = roles
        self.readings = readings
        self.checks = checks
        self.coverage = coverage


def spar_v2_tables(metadata: MetaData) -> SparV2Tables:
    roles = Table(
        "spar_roles",
        metadata,
        Column("run_id", String, primary_key=True),
        Column("request_id", String, nullable=False),
        Column("role", String, nullable=False),
        Column("work_id", String),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_spar_roles_request", "request_id", "event_id"),
    )
    readings = Table(
        "spar_readings",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("request_id", String, nullable=False),
        Column("run_id", String, nullable=False),
        Column("work_id", String, nullable=False),
        Column("items", String, nullable=False),
        Column("items_against", Integer, nullable=False),
        Column("items_for", Integer, nullable=False),
        Column("items_neither", Integer, nullable=False),
        Column("sections_read", String, nullable=False),
        Column("sections_read_count", Integer, nullable=False),
        Column("sections_total", Integer, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("markdown_hash", String, nullable=False),
        Column("note", String),
        Column("session", String),
        Column("actor", String, nullable=False),
        Column("model", String),
        Column("ts", String, nullable=False),
        Index("ux_spar_readings_work", "request_id", "work_id", unique=True),
    )
    checks = Table(
        "argument_checks",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("argument_id", String, nullable=False),
        Column("sheet_id", String, nullable=False),
        Column("request_id", String, nullable=False),
        Column("run_id", String, nullable=False),
        Column("verdict", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("session", String),
        Column("actor", String, nullable=False),
        Column("model", String),
        Column("ts", String, nullable=False),
        Index("ix_argument_checks_argument", "argument_id", "event_id"),
    )
    coverage = Table(
        "spar_coverage",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("request_id", String, nullable=False),
        Column("run_id", String, nullable=False),
        Column("sheet_id", String, nullable=False),
        Column("examined", String, nullable=False),
        Column("flagged", String, nullable=False),
        Column("unproposed_total", Integer, nullable=False),
        Column("not_examined", Integer, nullable=False),
        Column("note", String),
        Column("session", String),
        Column("actor", String, nullable=False),
        Column("model", String),
        Column("ts", String, nullable=False),
        Index("ux_spar_coverage_request", "request_id", unique=True),
    )
    return SparV2Tables(roles, readings, checks, coverage)


def plan(conn: Connection, request_id: str) -> Plan | None:
    """The derived plan of a v2 request, or None for a request that is not a folded v2 spar."""
    req = conn.execute(
        text("SELECT engine, max_sessions FROM chat_requests WHERE request_id = :r"),
        {"r": request_id},
    ).first()
    if req is None or str(req[0]) != "v2":
        return None
    cap = int(req[1]) if req[1] is not None else DEFAULT_MAX_SESSIONS
    sheet = conn.execute(
        text(
            "SELECT sheet_id, against_closed, for_closed FROM sheets WHERE request_id = :r "
            "ORDER BY event_id LIMIT 1"
        ),
        {"r": request_id},
    ).first()
    rows = conn.execute(
        text(
            "SELECT s.run_id, s.role, s.work_id, x.outcome FROM spar_roles s "
            "LEFT JOIN runner_runs x ON x.run_id = s.run_id WHERE s.request_id = :r "
            "ORDER BY s.event_id"
        ),
        {"r": request_id},
    ).all()
    slots: list[Slot] = [Slot("search")]
    done: list[bool] = [sheet is not None]
    cut: list[str] = []
    if sheet is not None:
        sheet_id = str(sheet[0])
        tier1 = conn.execute(
            text(
                "SELECT work_id, sources FROM sheet_candidates WHERE sheet_id = :s AND tier = 1 "
                "AND NOT over_cap"
            ),
            {"s": sheet_id},
        ).all()
        ordered = [
            str(w)
            for w, _ in sorted(
                tier1, key=lambda r: (-len([x for x in str(r[1]).split(",") if x]), str(r[0]))
            )
        ]
        allowed = max(cap - FIXED_ROLES, 0)
        read = {
            str(w)
            for (w,) in conn.execute(
                text("SELECT work_id FROM spar_readings WHERE request_id = :r"), {"r": request_id}
            )
        }
        started = {str(r[2]) for r in rows if r[1] == "read"}
        running = {str(r[2]) for r in rows if r[1] == "read" and r[3] is None}
        # reader sessions left, retries counted; a failed paper's retry is reserved before a new
        # paper is planned, so the tail of the list is what the budget cuts
        left = allowed - sum(1 for r in rows if r[1] == "read")
        keep = {w for w in ordered if w in read or w in running}
        for w in ordered:
            if w in started and w not in keep and left > 0:
                keep.add(w)
                left -= 1
        for w in ordered:
            if w not in started and left > 0:
                keep.add(w)
                left -= 1
        cut = [w for w in ordered if w not in keep]
        for work in ordered:
            if work in keep:
                slots.append(Slot("read", work))
                done.append(work in read)
        unchecked = conn.execute(
            text(
                "SELECT COUNT(*) FROM sheet_arguments a WHERE a.sheet_id = :s AND NOT EXISTS "
                "(SELECT 1 FROM argument_checks c WHERE c.argument_id = a.argument_id)"
            ),
            {"s": sheet_id},
        ).scalar_one()
        critic_ended = any(r[1] == "critic" and r[3] is not None for r in rows)
        covered = conn.execute(
            text("SELECT 1 FROM spar_coverage WHERE request_id = :r"), {"r": request_id}
        ).first()
        slots += [Slot("against"), Slot("for"), Slot("critic"), Slot("cover")]
        done += [
            bool(sheet[1]),
            bool(sheet[2]),
            bool(sheet[2]) and int(unchecked) == 0 and critic_ended,
            covered is not None,
        ]
    open_run = next((str(r[0]) for r in rows if r[3] is None), None)
    per_role: dict[str, int] = {}
    for r in rows:
        if r[1] != "read":
            per_role[str(r[1])] = per_role.get(str(r[1]), 0) + 1
    next_index = next((i for i, d in enumerate(done) if not d), None)
    failed = False
    if next_index is not None:
        slot = slots[next_index]
        failed = any((r[1], r[2]) == (slot.role, slot.work_id) and r[3] is not None for r in rows)
    return Plan(
        request_id=request_id,
        max_sessions=cap,
        sheet_id=None if sheet is None else str(sheet[0]),
        slots=tuple(slots),
        done=tuple(done),
        readers_cut=tuple(cut),
        sessions=len(rows),
        open_run=open_run,
        next_index=next_index,
        failed=failed,
        reader_sessions=sum(1 for r in rows if r[1] == "read"),
        fixed_retries=sum(max(n - 1, 0) for n in per_role.values()),
        role_sessions=tuple(sorted(per_role.items())),
    )


def role_row(conn: Connection, run_id: str) -> tuple[str, str, str | None, bool] | None:
    """`(request_id, role, work_id, open)` of the role run `run_id`, or None. `open` is true while
    the run has no `runner.finished`."""
    row = conn.execute(
        text(
            "SELECT s.request_id, s.role, s.work_id, x.outcome FROM spar_roles s "
            "LEFT JOIN runner_runs x ON x.run_id = s.run_id WHERE s.run_id = :r"
        ),
        {"r": run_id},
    ).first()
    if row is None:
        return None
    return str(row[0]), str(row[1]), None if row[2] is None else str(row[2]), row[3] is None


def spar_v2_handlers(tables: SparV2Tables) -> dict[str, Handler]:
    def started(conn: Connection, event: Event) -> None:
        payload = SparRoleStarted.model_validate(event.payload)
        if event.actor.kind != "system":
            return
        current = plan(conn, payload.request_id)
        if current is None or current.open_run is not None or current.next is None:
            return
        if current.next != Slot(payload.role, payload.work_id):
            return
        if not current.can_start(current.next):
            return
        stage = conn.execute(
            text("SELECT stage FROM runner_runs WHERE run_id = :r"), {"r": payload.run_id}
        ).first()
        if stage is not None and str(stage[0]) != stage_of(payload.role):
            return
        conn.execute(
            sqlite_insert(tables.roles)
            .values(
                run_id=payload.run_id,
                request_id=payload.request_id,
                role=payload.role,
                work_id=payload.work_id,
                ts=format_ts(event.ts),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["run_id"])
        )

    def holds(conn: Connection, run_id: str, request_id: str, role: str) -> bool:
        found = role_row(conn, run_id)
        return found is not None and found[0] == request_id and found[1] == role

    def reading(conn: Connection, event: Event) -> None:
        payload = SparReadingRecorded.model_validate(event.payload)
        if event.actor.kind != "agent":
            return
        found = role_row(conn, payload.run_id)
        if (
            found is None
            or found[0] != payload.request_id
            or found[1] != "read"
            or found[2] != payload.work_id
        ):
            return
        counts = {s: sum(1 for i in payload.items if i.stance == s) for s in ("against", "for")}
        conn.execute(
            sqlite_insert(tables.readings)
            .values(
                event_id=event.id,
                request_id=payload.request_id,
                run_id=payload.run_id,
                work_id=payload.work_id,
                items=canonical_json([i.model_dump(mode="json") for i in payload.items]).decode(),
                items_against=counts["against"],
                items_for=counts["for"],
                items_neither=len(payload.items) - counts["against"] - counts["for"],
                sections_read=canonical_json(list(payload.sections_read)).decode(),
                sections_read_count=len(set(payload.sections_read)),
                sections_total=payload.sections_total,
                conversion_id=payload.conversion_id,
                markdown_hash=payload.markdown_hash,
                note=payload.note,
                session=event.actor.session,
                actor=event.actor.id,
                model=event.actor.model,
                ts=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        )

    def checked(conn: Connection, event: Event) -> None:
        payload = SheetArgumentChecked.model_validate(event.payload)
        if event.actor.kind != "agent" or not holds(
            conn, payload.run_id, payload.request_id, "critic"
        ):
            return
        found = conn.execute(
            text(
                "SELECT 1 FROM sheet_arguments a JOIN sheets s ON s.sheet_id = a.sheet_id "
                "WHERE a.argument_id = :a AND a.sheet_id = :s AND s.request_id = :r"
            ),
            {"a": payload.argument_id, "s": payload.sheet_id, "r": payload.request_id},
        ).first()
        if found is None:
            return
        conn.execute(
            sqlite_insert(tables.checks)
            .values(
                event_id=event.id,
                argument_id=payload.argument_id,
                sheet_id=payload.sheet_id,
                request_id=payload.request_id,
                run_id=payload.run_id,
                verdict=payload.verdict,
                reason=payload.reason,
                session=event.actor.session,
                actor=event.actor.id,
                model=event.actor.model,
                ts=format_ts(event.ts),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    def covered(conn: Connection, event: Event) -> None:
        payload = SparCoverageRecorded.model_validate(event.payload)
        if event.actor.kind != "agent" or not holds(
            conn, payload.run_id, payload.request_id, "cover"
        ):
            return
        unproposed = {
            str(w)
            for (w,) in conn.execute(
                text(
                    "SELECT c.work_id FROM sheet_candidates c JOIN sheets s ON "
                    "s.sheet_id = c.sheet_id WHERE s.sheet_id = :s AND s.request_id = :r "
                    "AND c.tier = 3"
                ),
                {"s": payload.sheet_id, "r": payload.request_id},
            )
        }
        flagged = {f.work_id for f in payload.flagged}
        if not set(payload.examined) <= unproposed or not flagged <= set(payload.examined):
            return
        conn.execute(
            sqlite_insert(tables.coverage)
            .values(
                event_id=event.id,
                request_id=payload.request_id,
                run_id=payload.run_id,
                sheet_id=payload.sheet_id,
                examined=canonical_json(list(payload.examined)).decode(),
                flagged=canonical_json(
                    [f.model_dump(mode="json") for f in payload.flagged]
                ).decode(),
                unproposed_total=len(unproposed),
                not_examined=len(unproposed) - len(set(payload.examined)),
                note=payload.note,
                session=event.actor.session,
                actor=event.actor.id,
                model=event.actor.model,
                ts=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        )

    def total(fold: Handler) -> Handler:
        def run(conn: Connection, event: Event) -> None:
            try:
                with conn.begin_nested():
                    fold(conn, event)
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                FactoryError,
                SQLAlchemyError,
            ):
                return

        return run

    return {
        "spar.role_started": total(started),
        "spar.reading_recorded": total(reading),
        "sheet.argument_checked": total(checked),
        "spar.coverage_recorded": total(covered),
    }
