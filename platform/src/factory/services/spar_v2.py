"""The agentic spar, engine v2: the coordinator and the role records (plan spar-night N6, IDEA-101).

One chat request with `engine: v2` is worked by separate headless role sessions, each a `claude -p`
process of its own (its own MCP session, allow-list and prompt), started one at a time through the
runner, so the one-open-run rule holds. The order is fixed: search, one read per planned tier-1
paper, the case against, the case for (another session), the critic, the coverage sweep. The
coordinator is bookkeeping: it sequences, counts and derives; every judgement is a role's.

Invariants:
- State is derived, never stored (`index/spar_v2.plan`): which roles are done follows from the
  sheet (searcher: it opened; writers: the section closed), the readings, the critic's checks and
  the coverage record. `open` waits for the next role, `taken` while a role run is open, `failed`
  when the run of the next role ended without finishing it (the role is named), `done` when every
  role is. A failed role stops the chain; `advance` retries it as a new run in a new session.
- A role run is bound by the system event `spar.role_started`, written with `runner.started` when
  the run starts. A role tool names no request: the platform derives it from the run
  (`FACTORY_RUN_ID`), and refuses a session that is not an open run of the role the tool serves.
- Readers record verified quotes only (`chat_verify` against the pinned conversion) and the
  sections they say they read, checked to be sections of that paper; the counts of sections are
  computed. A reading is a proposal, never a rating.
- The critic records `sheet.argument_checked` (holds, overreaches or misread, with a reason). A
  check is not a rating: it never enters `sheet_ratings`, and no role rates, writes the balance of
  the evidence, or records a lead. The allow-lists of the stages (`runner.STAGES`) leave those
  tools out, and the services refuse a role that writes outside its own role.
- Budget: five roles are fixed (search, against, for, critic, cover), so the readers share
  `max_sessions - 5` sessions (default cap 15), their retries included; tier-1 papers beyond that
  are cut, fewest sources first, and listed as `readers_cut`. A reader's retry takes a reader
  session, never a fixed role's: when it spends the last one, the paper that no longer fits is cut
  (stated in `readers_cut`) and the chain still reaches the cover. A fixed role that fails is
  retried within a separate allowance of `FIXED_RETRIES` (2) retries per request, over all five
  roles, beyond the cap; past it the request is not advanced. Counts are from the folded role runs.
- Readers read one after another in v1 of v2; readers in parallel is later work.
- Held-out handling follows decision 37.9 (the MCP tools scrub every reply).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, get_args

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.spar_v2 import (
    DEFAULT_MAX_SESSIONS,
    FIXED_RETRIES,
    FIXED_ROLES,
    MIN_MAX_SESSIONS,
    Plan,
    Slot,
    plan,
    role_row,
    stage_of,
)
from factory.model.chat_requests import REQUEST_ID_RE, RUN_ID_RE
from factory.model.spar_v2 import (
    ARGUMENT_ID_RE,
    NOTE_MAX,
    REASON_MAX,
    SPAR_ROLES,
    WHY_MAX,
    CheckVerdict,
    FlaggedWork,
    ReadingItem,
    ReadingStance,
    SheetArgumentChecked,
    SparCoverageRecorded,
    SparReadingRecorded,
    SparRoleStarted,
)
from factory.services.chat_read import VerifyItem, chat_sections, chat_verify
from factory.services.context import Project
from factory.services.selection import SelectionSpec, resolve_selection_cached
from factory.services.work_ref import resolve_work_id

__all__ = [
    "DEFAULT_MAX_SESSIONS",
    "FIXED_RETRIES",
    "FIXED_ROLES",
    "MIN_MAX_SESSIONS",
    "CheckInput",
    "ReaderRow",
    "ReadingEntry",
    "ReadingInput",
    "ReadingsView",
    "RoleTask",
    "advance",
    "advance_open",
    "bound_role",
    "check_sheet_run",
    "progress",
    "readings_view",
    "refuse_blind_read",
    "record_checks",
    "record_coverage",
    "record_reading",
    "role_started_event",
    "serve_task",
    "stage_of",
]


def _issue(field_name: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, message)])


@dataclass(frozen=True)
class ReadingInput:
    anchor: str
    quote: str
    stance: str
    why: str


@dataclass(frozen=True)
class CheckInput:
    argument_id: str
    verdict: str
    reason: str


@dataclass(frozen=True)
class RoleTask:
    """What a role run is told: served by `spar_role_next` from the run's own assignment."""

    request_id: str
    role: str
    work_id: str | None
    hypothesis: str
    mode: str
    selection: dict[str, Any]
    sheet_id: str | None
    tier1: tuple[dict[str, Any], ...]
    unproposed: tuple[str, ...]
    readers_cut: tuple[str, ...]
    sessions: int
    max_sessions: int


@dataclass(frozen=True)
class ReaderRow:
    """What one reader covered; every number is computed from the folded reading."""

    work_id: str
    read: bool
    sections_read: int
    sections_total: int
    items_against: int
    items_for: int
    items_neither: int
    model: str | None
    session: str | None


@dataclass(frozen=True)
class ReadingEntry:
    work_id: str
    anchor: str
    quote: str
    stance: str
    why: str


@dataclass(frozen=True)
class ReadingsView:
    request_id: str
    readers: tuple[ReaderRow, ...]
    items: tuple[ReadingEntry, ...]
    readers_cut: tuple[str, ...]


# ---------------------------------------------------------------------------------------- derive


def progress(project: Project, request_id: str) -> Plan:
    """The derived plan and state of a v2 request. Refused (`request_id`) for any other request."""
    project.index.sync()
    with project.index.connect() as conn:
        found = plan(conn, request_id)
    if found is None:
        raise _issue("request_id", f"{request_id}: no such v2 spar request")
    return found


def bound_role(project: Project, run_id: str | None) -> tuple[str, str, str | None] | None:
    """`(request_id, role, work_id)` of the open role run `run_id`, or None for any other run id
    (none, unknown, a run of another stage, a role run that has ended). The caller has synced."""
    if run_id is None or re.fullmatch(RUN_ID_RE, run_id) is None:
        return None
    with project.index.connect() as conn:
        found = role_row(conn, run_id)
    if found is None or not found[3]:
        return None
    return found[0], found[1], found[2]


def _bound(
    project: Project, actor: Actor, run_id: str | None, roles: tuple[str, ...]
) -> tuple[str, str, str | None]:
    if actor.kind != "agent":
        raise _issue("actor", "a role session of an agent writes this")
    project.index.sync()
    found = bound_role(project, run_id)
    if found is None or found[1] not in roles:
        raise _issue(
            "run",
            "this session is not an open run of the role "
            + " or ".join(roles)
            + " of a v2 spar request",
        )
    return found


def check_sheet_run(
    project: Project, run_id: str | None, request_id: str | None, roles: tuple[str, ...]
) -> bool:
    """Refuse (field `run`) a sheet write that does not match the run. A sheet of a v2 request is
    written only by the open run of one of `roles` bound to that request; any other sheet is not
    written by a v2 role run. Returns whether the sheet is a v2 request's. The caller has synced
    the index."""
    v2 = False
    if request_id is not None:
        with project.index.connect() as conn:
            v2 = plan(conn, request_id) is not None
    bound = bound_role(project, run_id)
    if v2:
        if bound is None or bound[0] != request_id or bound[1] not in roles:
            raise _issue(
                "run",
                f"a sheet of the v2 request {request_id} is written only by its "
                + " or ".join(roles)
                + " role session",
            )
    elif bound is not None:
        raise _issue("run", "a v2 role session writes only the sheet of its own request")
    return v2


def refuse_blind_read(project: Project, run_id: str | None) -> None:
    """Refuse (field `run`) a read of a sheet to the open run of the for-writer of a v2 request:
    the case for is written without seeing the case against, so the sheet tools that show the
    against section (`sheet_view`, `sheet_list`) are closed to that run on the server, whatever
    its allow-list says. The writer is served the hypothesis and selection by `spar_role_next`.
    Any other session, and a run that has ended, reads as before."""
    project.index.sync()
    found = bound_role(project, run_id)
    if found is not None and found[1] == "for":
        raise _issue(
            "run",
            "the case for is written without reading the sheet; "
            "its assignment (`spar_role_next`) holds what it needs",
        )


def role_started_event(project: Project, request_id: str, run_id: str, slot: Slot) -> Any:
    """The system event that binds `run_id` to a role of the request."""
    payload = SparRoleStarted(
        request_id=request_id,
        run_id=run_id,
        role=slot.role,
        work_id=slot.work_id,
    )
    return project.events.make(
        "spar.role_started", payload, project.system_actor(), refs=(request_id, run_id)
    )


# ------------------------------------------------------------------------------------ the chain


def _check_startable(current: Plan, *, retry: bool) -> Slot:
    if current.state == "taken":
        raise _issue("request_id", f"a role run of this request is open ({current.open_run})")
    slot = current.next
    if slot is None:
        raise _issue("request_id", "every role of this request is done")
    if current.failed and not retry:
        raise _issue("request_id", f"the role {slot.role} failed; advance retries it")
    if not current.can_start(slot):
        if slot.role == "read":
            why = (
                f"the {current.max_sessions - FIXED_ROLES} reader sessions of the budget of "
                f"{current.max_sessions} are spent"
            )
        else:
            why = (
                f"the retry allowance of {FIXED_RETRIES} for the fixed roles is spent "
                f"(budget {current.max_sessions})"
            )
        raise _issue("request_id", f"{why}; the role {slot.role} is not started")
    return slot


def advance(
    project: Project,
    request_id: str,
    *,
    retry: bool = True,
    launcher: Callable[..., Any] | None = None,
) -> str | None:
    """Start the next role run of the request and return its run id. A failed role is retried
    (a new run, a new session) when `retry`. Returns None when the request is done. Refused
    (`request_id`, nothing started) while a role run is open, when the failed role is not to be
    retried, and when the session budget is spent; the runner's own refusals (another run of the
    project is open, `claude` missing) pass through."""
    from factory.services import runner

    current = progress(request_id=request_id, project=project)
    if current.next is None:
        return None
    slot = _check_startable(current, retry=retry)
    return runner.start_run(
        project,
        stage_of(slot.role),
        launcher=launcher,
        assignment=runner.RoleAssignment(request_id, slot.role, slot.work_id),
    )


def advance_open(project: Project, *, launcher: Callable[..., Any] | None = None) -> str | None:
    """After a run ends: start the next role of the first v2 request whose chain was begun and is
    waiting for it (not failed, not done, no run open). Returns the run id started, or None."""
    project.index.sync()
    with project.index.connect() as conn:
        ids = [
            str(r[0])
            for r in conn.execute(
                text("SELECT request_id FROM chat_requests WHERE engine = 'v2' ORDER BY event_id")
            )
        ]
        plans = [p for p in (plan(conn, i) for i in ids) if p is not None]
    for current in plans:
        if current.sessions > 0 and current.state == "open":
            return advance(project, current.request_id, retry=False, launcher=launcher)
    return None


def pending_by_role(project: Project, role: str) -> int:
    """The v2 requests whose next role is `role` and that have no role run open: the pending units
    of the stage `spar2-<role>`."""
    project.index.sync()
    with project.index.connect() as conn:
        ids = [
            str(r[0])
            for r in conn.execute(text("SELECT request_id FROM chat_requests WHERE engine = 'v2'"))
        ]
        plans = [p for p in (plan(conn, i) for i in ids) if p is not None]
    return sum(
        1
        for p in plans
        if p.open_run is None and p.next is not None and p.next.role == role and p.can_start(p.next)
    )


# ------------------------------------------------------------------------------------- serving


def serve_task(project: Project, actor: Actor, run_id: str | None) -> RoleTask:
    """The assignment of the role run this session is. Read-only."""
    request_id, role, work_id = _bound(project, actor, run_id, tuple(SPAR_ROLES))
    with project.index.connect() as conn:
        current = plan(conn, request_id)
        req = (
            conn.execute(
                text("SELECT hypothesis, mode, selection FROM chat_requests WHERE request_id=:r"),
                {"r": request_id},
            )
            .mappings()
            .one()
        )
        tier1: list[dict[str, Any]] = []
        unproposed: list[str] = []
        if current is not None and current.sheet_id is not None:
            tier1 = [
                {"work_id": str(w), "sources": str(s).split(","), "stances": str(t).split(",")}
                for w, s, t in conn.execute(
                    text(
                        "SELECT work_id, sources, stances FROM sheet_candidates "
                        "WHERE sheet_id = :s AND tier = 1 AND NOT over_cap ORDER BY work_id"
                    ),
                    {"s": current.sheet_id},
                )
            ]
            if role == "cover":
                unproposed = [
                    str(w)
                    for (w,) in conn.execute(
                        text(
                            "SELECT work_id FROM sheet_candidates WHERE sheet_id = :s "
                            "AND tier = 3 ORDER BY work_id"
                        ),
                        {"s": current.sheet_id},
                    )
                ]
    assert current is not None
    return RoleTask(
        request_id=request_id,
        role=role,
        work_id=work_id,
        hypothesis=str(req["hypothesis"]),
        mode=str(req["mode"]),
        selection=json.loads(req["selection"]),
        sheet_id=current.sheet_id,
        tier1=tuple(tier1),
        unproposed=tuple(unproposed),
        readers_cut=current.readers_cut,
        sessions=current.sessions,
        max_sessions=current.max_sessions,
    )


# ------------------------------------------------------------------------------------ readings


def _sheet_of(project: Project, request_id: str) -> dict[str, Any]:
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text("SELECT * FROM sheets WHERE request_id = :r ORDER BY event_id LIMIT 1"),
                {"r": request_id},
            )
            .mappings()
            .first()
        )
    if row is None:
        raise _issue("request_id", f"{request_id}: no sheet opened yet")
    return dict(row)


def _pinned(project: Project, sheet: dict[str, Any]) -> dict[str, str]:
    raw = json.loads(sheet["selection"])
    spec = SelectionSpec(
        layers=list(raw.get("layers", [])),
        include=list(raw.get("include", [])),
        exclude=list(raw.get("exclude", [])),
    )
    selection = resolve_selection_cached(project, spec)
    if selection.digest != sheet["selection_digest"]:
        raise _issue("sheet_id", "the selection changed since the sheet opened; ask again")
    return {w.work_id: w.conversion_id for w in selection.works}


def record_reading(
    project: Project,
    actor: Actor,
    run_id: str | None,
    work_id: str,
    items: Sequence[ReadingInput],
    sections_read: Sequence[str],
    note: str | None = None,
) -> SparReadingRecorded:
    """Record the reading of the paper this reader run was assigned. Refused (nothing written, every
    issue together, located as `items[i].<field>`) for a session that is not the open run of that
    reader, another paper, a quote that `chat_verify` does not accept in the pinned conversion, a
    stance or why that is not valid, sections that are not sections of the paper (or none), and a
    paper already read for the request."""
    request_id, _role, assigned = _bound(project, actor, run_id, ("read",))
    issues: list[ValidationIssue] = []
    work = resolve_work_id(project, work_id)
    if work != assigned:
        raise _issue("work_id", f"{work_id}: this run reads {assigned}")
    sheet = _sheet_of(project, request_id)
    pinned = _pinned(project, sheet)
    conversion = pinned.get(work)
    if conversion is None:
        raise _issue("work_id", f"{work}: not in the sheet's selection")
    note = (note or "").strip() or None
    if note is not None and len(note) > NOTE_MAX:
        issues.append(ValidationIssue("note", f"a note has at most {NOTE_MAX} characters"))
    outline = chat_sections(project, work, conversion)
    anchors = {s.anchor for s in outline.sections}
    wanted = list(dict.fromkeys(a.strip() for a in sections_read if a.strip()))
    if not wanted:
        issues.append(ValidationIssue("sections_read", "name the sections you read"))
    issues.extend(
        ValidationIssue("sections_read", f"{a}: not a section of the paper")
        for a in wanted
        if a not in anchors
    )
    checks: list[int] = []
    for i, item in enumerate(items):
        at = f"items[{i}]"
        if item.stance not in get_args(ReadingStance):
            issues.append(
                ValidationIssue(f"{at}.stance", f"{item.stance}: must be against, for or neither")
            )
        why = item.why.strip()
        if not why or len(why) > WHY_MAX:
            issues.append(ValidationIssue(f"{at}.why", f"a why has 1 to {WHY_MAX} characters"))
        if not item.anchor.strip() or not item.quote.strip():
            issues.append(ValidationIssue(f"{at}.quote", "an anchor and a quote are required"))
        else:
            checks.append(i)
    verified = chat_verify(
        project,
        [VerifyItem(work, items[i].anchor.strip(), items[i].quote, conversion) for i in checks],
    )
    for i, verdict in zip(checks, verified, strict=True):
        if verdict.status != "accepted":
            issues.append(
                ValidationIssue(f"items[{i}].quote", f"{verdict.status}: {verdict.item.anchor}")
            )
    if issues:
        raise FactoryValidationError(issues)
    payload = SparReadingRecorded(
        request_id=request_id,
        run_id=str(run_id),
        work_id=work,
        items=tuple(
            ReadingItem(
                anchor=i.anchor.strip(),
                quote=i.quote,
                stance=i.stance,
                why=i.why.strip(),
            )
            for i in items
        ),
        sections_read=tuple(wanted),
        sections_total=len(anchors),
        conversion_id=outline.conversion_id,
        markdown_hash=outline.markdown_hash,
        note=note,
    )
    blob = project.blobs.put_json(
        {
            "request_id": request_id,
            "work_id": work,
            "verified": [
                {"anchor": v.item.anchor, "quote": v.item.quote, "status": v.status}
                for v in verified
            ],
            "sections_read": [*wanted],
            "sections_total": len(anchors),
        }
    )
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            again = conn.execute(
                text("SELECT 1 FROM spar_readings WHERE request_id = :r AND work_id = :w"),
                {"r": request_id, "w": work},
            ).first()
        if again is not None:
            raise _issue("work_id", f"{work}: already read for this request")
        project.record(
            [
                project.events.make(
                    "spar.reading_recorded",
                    payload,
                    actor,
                    refs=(request_id, work),
                    input_blob=blob,
                )
            ]
        )
    return payload


def readings_view(project: Project, request_id: str) -> ReadingsView:
    """What the readers of the request recorded and covered, computed from the folded readings:
    one row per planned reader (read or not) and every passage with its proposed stance. Read-only.
    Refused for a request that is not a v2 spar."""
    current = progress(project, request_id)
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text("SELECT * FROM spar_readings WHERE request_id = :r ORDER BY event_id"),
                {"r": request_id},
            )
            .mappings()
            .all()
        )
    by_work = {str(r["work_id"]): r for r in rows}
    planned = [s.work_id for s in current.slots if s.role == "read" and s.work_id]
    readers: list[ReaderRow] = []
    for work in [*planned, *[w for w in by_work if w not in planned]]:
        r = by_work.get(work)
        readers.append(
            ReaderRow(
                work_id=work,
                read=r is not None,
                sections_read=0 if r is None else int(r["sections_read_count"]),
                sections_total=0 if r is None else int(r["sections_total"]),
                items_against=0 if r is None else int(r["items_against"]),
                items_for=0 if r is None else int(r["items_for"]),
                items_neither=0 if r is None else int(r["items_neither"]),
                model=None if r is None else r["model"],
                session=None if r is None else r["session"],
            )
        )
    entries = tuple(
        ReadingEntry(str(r["work_id"]), i["anchor"], i["quote"], i["stance"], i["why"])
        for r in rows
        for i in json.loads(r["items"])
    )
    return ReadingsView(request_id, tuple(readers), entries, current.readers_cut)


# --------------------------------------------------------------------------------- checks, sweep


def record_checks(
    project: Project, actor: Actor, run_id: str | None, checks: Sequence[CheckInput]
) -> list[SheetArgumentChecked]:
    """Record the critic's checks, all or none. Each names an argument of the request's sheet, a
    verdict (holds, overreaches or misread) and a reason; none is a rating. Refused (nothing
    written, located as `checks[i].<field>`) for a session that is not the critic run, an argument
    of another sheet, a verdict not in the list, a missing reason, or a repeated argument."""
    request_id, _role, _work = _bound(project, actor, run_id, ("critic",))
    if not checks:
        raise _issue("checks", "give at least one check")
    sheet = _sheet_of(project, request_id)
    with project.index.connect() as conn:
        known = {
            str(a)
            for (a,) in conn.execute(
                text("SELECT argument_id FROM sheet_arguments WHERE sheet_id = :s"),
                {"s": sheet["sheet_id"]},
            )
        }
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for i, c in enumerate(checks):
        at = f"checks[{i}]"
        if re.fullmatch(ARGUMENT_ID_RE, c.argument_id) is None or c.argument_id not in known:
            issues.append(
                ValidationIssue(f"{at}.argument_id", f"{c.argument_id}: no argument of this sheet")
            )
        if c.argument_id in seen:
            issues.append(ValidationIssue(f"{at}.argument_id", "checked twice in one call"))
        seen.add(c.argument_id)
        if c.verdict not in get_args(CheckVerdict):
            issues.append(
                ValidationIssue(
                    f"{at}.verdict", f"{c.verdict}: must be holds, overreaches or misread"
                )
            )
        reason = c.reason.strip()
        if not reason or len(reason) > REASON_MAX:
            issues.append(
                ValidationIssue(f"{at}.reason", f"a reason has 1 to {REASON_MAX} characters")
            )
    if issues:
        raise FactoryValidationError(issues)
    payloads = [
        SheetArgumentChecked(
            argument_id=c.argument_id,
            sheet_id=str(sheet["sheet_id"]),
            request_id=request_id,
            run_id=str(run_id),
            verdict=c.verdict,
            reason=c.reason.strip(),
        )
        for c in checks
    ]
    blob = project.blobs.put_json(
        {
            "request_id": request_id,
            "sheet_id": sheet["sheet_id"],
            "checks": [vars(c) for c in checks],
        }
    )
    with project.index.exclusive():
        project.record(
            [
                project.events.make(
                    "sheet.argument_checked",
                    p,
                    actor,
                    refs=(p.argument_id, p.sheet_id),
                    input_blob=blob,
                )
                for p in payloads
            ]
        )
    return payloads


def record_coverage(
    project: Project,
    actor: Actor,
    run_id: str | None,
    examined: Sequence[str],
    flagged: Sequence[tuple[str, str]] = (),
    note: str | None = None,
) -> SparCoverageRecorded:
    """Record the coverage sweep over the papers no source proposed (tier 3 of the sheet): which
    were examined and which should have been read, with a reason each. The counts (papers no
    source proposed, not examined) are computed. Refused (nothing written) for a session that is
    not the cover run, a paper that is not one no source proposed, a flagged paper not examined, a
    missing reason, and a second sweep for the request."""
    request_id, _role, _work = _bound(project, actor, run_id, ("cover",))
    sheet = _sheet_of(project, request_id)
    with project.index.connect() as conn:
        unproposed = {
            str(w)
            for (w,) in conn.execute(
                text("SELECT work_id FROM sheet_candidates WHERE sheet_id = :s AND tier = 3"),
                {"s": sheet["sheet_id"]},
            )
        }
        swept = conn.execute(
            text("SELECT 1 FROM spar_coverage WHERE request_id = :r"), {"r": request_id}
        ).first()
    issues: list[ValidationIssue] = []
    if swept is not None:
        issues.append(ValidationIssue("request_id", "the coverage sweep is already recorded"))
    seen = [resolve_work_id(project, w, field="examined") for w in examined]
    for i, w in enumerate(seen):
        if w not in unproposed:
            issues.append(
                ValidationIssue(f"examined[{i}]", f"{w}: not a paper that no source proposed")
            )
    marked: list[FlaggedWork] = []
    for i, (w, reason) in enumerate(flagged):
        work = resolve_work_id(project, w, field=f"flagged[{i}].work_id")
        if work not in seen:
            issues.append(ValidationIssue(f"flagged[{i}].work_id", f"{work}: not examined"))
        if not reason.strip() or len(reason.strip()) > WHY_MAX:
            issues.append(
                ValidationIssue(f"flagged[{i}].reason", f"a reason has 1 to {WHY_MAX} characters")
            )
        else:
            marked.append(FlaggedWork(work_id=work, reason=reason.strip()))
    note = (note or "").strip() or None
    if note is not None and len(note) > NOTE_MAX:
        issues.append(ValidationIssue("note", f"a note has at most {NOTE_MAX} characters"))
    if issues:
        raise FactoryValidationError(issues)
    distinct = tuple(dict.fromkeys(seen))
    payload = SparCoverageRecorded(
        request_id=request_id,
        run_id=str(run_id),
        sheet_id=str(sheet["sheet_id"]),
        examined=distinct,
        flagged=tuple(marked),
        unproposed_total=len(unproposed),
        not_examined=len(unproposed) - len(distinct),
        note=note,
    )
    blob = project.blobs.put_json(
        {
            "request_id": request_id,
            "examined": list(distinct),
            "flagged": [list(f) for f in flagged],
        }
    )
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            again = conn.execute(
                text("SELECT 1 FROM spar_coverage WHERE request_id = :r"), {"r": request_id}
            ).first()
        if again is not None:
            raise _issue("request_id", "the coverage sweep is already recorded")
        project.record(
            [
                project.events.make(
                    "spar.coverage_recorded", payload, actor, refs=(request_id,), input_blob=blob
                )
            ]
        )
    return payload


_ = REQUEST_ID_RE  # exported pattern kept for callers that validate ids
