"""Requests for a headless spar or ask: record, take, view, list (plan spar-night N3).

The researcher orders a spar or an ask (`chat.requested`, a human act). A headless run of the
stage `spar` or `ask` (`services/runner.py`) takes the oldest open request of its kind
(`chat.request_taken`, written by the run's session) and answers it with a sheet or an answer that
names the request. Nothing here judges: the platform records, serves in order and derives state.

Invariants:
- Only a human requests, here and in the projection (`index/chat_requests.py`). Only an agent
  takes, and only a session that is an open run of stage `spar` or `ask` (`FACTORY_RUN_ID`), a
  request of the run's own kind; a session with no such run is refused and serves nothing. A
  refusal writes nothing.
- A result names a request only when the request is taken by the result's own session and the
  taking run is still open (`check_result_request`); a sheet opens only for a request of its mode
  with no parent (a follow-up writes into its parent sheet). One run takes one request.
- State is derived, never stored: `done` when a complete result names the request (an Explore sheet
  whose case for is closed, a Prepare sheet whose case against is closed, an answer that recorded
  it, or, for a follow-up, a sheet whose case for closed with it); else `open` when no run took
  it; else `taken` while that run is open, and `failed` once it has ended without a complete
  result (`result` still lists a sheet left incomplete). A failed request is not served again;
  the researcher asks again.
- `chat_request_next` serves the oldest open request of the run's kind, once: the taking is one
  event written under the index lock, so two runs never take the same request.
- Prepare, two sessions: a Prepare spar run writes only the case against of a new sheet and
  stops. The case for is a second request (a follow-up whose `parent` is that sheet, mode
  `prepare`) that the researcher makes; its run, a different session, argues for into the parent
  sheet and closes the section with this request id. Nothing makes that request automatically:
  recording a request is a human act.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, get_args

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.chat_requests import (
    NOTE_MAX,
    PARENT_RE,
    REQUEST_ID_RE,
    RUN_ID_RE,
    TEXT_MAX,
    ChatKind,
    ChatMode,
    ChatRequested,
    ChatRequestTaken,
)
from factory.services.context import Project
from factory.services.selection import SelectionSpec

__all__ = [
    "ChatRequestInfo",
    "check_result_request",
    "list_requests",
    "open_count",
    "request_chat",
    "request_respar",
    "respar_parent",
    "take_next",
    "view_request",
]

_STATE_SQL = """
SELECT r.*,
  COALESCE(
    (SELECT s.sheet_id FROM sheets s
       WHERE s.request_id = r.request_id OR s.for_request_id = r.request_id
       ORDER BY s.event_id LIMIT 1),
    (SELECT a.answer_id FROM answers a WHERE a.request_id = r.request_id
       ORDER BY a.event_id LIMIT 1)
  ) AS result,
  (
    EXISTS (SELECT 1 FROM sheets s
              WHERE s.for_request_id = r.request_id
                 OR (s.request_id = r.request_id
                     AND ((s.mode = 'explore' AND s.for_closed)
                          OR (s.mode = 'prepare' AND s.against_closed))))
    OR EXISTS (SELECT 1 FROM answers a WHERE a.request_id = r.request_id)
  ) AS complete,
  (SELECT x.outcome FROM runner_runs x WHERE x.run_id = r.taken_run) AS run_outcome
FROM chat_requests r
"""


@dataclass(frozen=True)
class ChatRequestInfo:
    request_id: str
    kind: str
    hypothesis: str | None
    question: str | None
    mode: str | None
    parent: str | None
    note: str | None
    state: str
    """`open`, `taken`, `done` or `failed` (derived)."""
    result: str | None
    """The first sheet or answer id that names the request. The request is `done` only when that
    result is complete for it (see the module docstring); a sheet still open is listed here."""
    taken_run: str | None
    actor: str
    ts: str
    selection: dict[str, Any] = field(default_factory=dict)
    respar: bool = False
    """A re-spar: `parent` is the earlier sheet, repeated over today's papers (N7)."""


def _issue(field_name: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, message)])


def _info(row: Any) -> ChatRequestInfo:
    if row["complete"]:
        state = "done"
    elif row["taken_run"] is None:
        state = "open"
    elif row["run_outcome"] is None:
        state = "taken"
    else:
        state = "failed"
    return ChatRequestInfo(
        request_id=row["request_id"],
        kind=row["kind"],
        hypothesis=row["hypothesis"],
        question=row["question"],
        mode=row["mode"],
        parent=row["parent"],
        note=row["note"],
        state=state,
        result=row["result"],
        taken_run=row["taken_run"],
        actor=row["actor"],
        ts=row["ts"],
        selection=json.loads(row["selection"]),
        respar=bool(row["respar"]),
    )


def _parent_exists(project: Project, parent: str) -> bool:
    table, column = (
        ("answers", "answer_id") if parent.startswith("ans_") else ("sheets", "sheet_id")
    )
    with project.index.connect() as conn:
        return (
            conn.execute(text(f"SELECT 1 FROM {table} WHERE {column} = :p"), {"p": parent}).first()
            is not None
        )


def _parent_issues(
    project: Project, kind: str, mode: str | None, parent: str
) -> list[ValidationIssue]:
    """Why `parent` is no parent for a new request (empty when it is one). A Prepare spar with a
    sheet parent is the case for: the parent is a Prepare sheet with against closed and for not
    closed, and no other follow-up of it is open or taken."""
    if re.fullmatch(PARENT_RE, parent) is None or not _parent_exists(project, parent):
        return [ValidationIssue("parent", f"{parent}: no such answer or sheet")]
    if kind != "spar" or mode != "prepare" or not parent.startswith("sht_"):
        return []
    with project.index.connect() as conn:
        sheet = conn.execute(
            text("SELECT mode, against_closed, for_closed FROM sheets WHERE sheet_id = :s"),
            {"s": parent},
        ).first()
    if sheet is None or sheet[0] != "prepare" or not sheet[1] or sheet[2]:
        return [
            ValidationIssue(
                "parent", f"{parent}: the case for follows a Prepare sheet with against closed"
            )
        ]
    pending = [
        r.request_id
        for r in _select(project, "WHERE r.parent = :p", {"p": parent})
        if r.state in ("open", "taken")
    ]
    if pending:
        return [ValidationIssue("parent", f"{parent}: already has the open request {pending[0]}")]
    return []


def _respar_issues(project: Project, parent: str) -> list[ValidationIssue]:
    """Why `parent` cannot be re-sparred (empty when it can): it is a sheet with both sections
    closed, and no other re-spar of it is open or taken."""
    if re.fullmatch(PARENT_RE, parent) is None or not parent.startswith("sht_"):
        return [ValidationIssue("parent", f"{parent}: a re-spar repeats a sheet")]
    with project.index.connect() as conn:
        sheet = conn.execute(
            text("SELECT against_closed, for_closed FROM sheets WHERE sheet_id = :s"),
            {"s": parent},
        ).first()
    if sheet is None:
        return [ValidationIssue("parent", f"{parent}: no such sheet")]
    if not (sheet[0] and sheet[1]):
        return [ValidationIssue("parent", f"{parent}: only a sheet with both sections closed")]
    pending = [
        r.request_id
        for r in _select(project, "WHERE r.parent = :p AND r.respar", {"p": parent})
        if r.state in ("open", "taken")
    ]
    if pending:
        return [ValidationIssue("parent", f"{parent}: already has the open re-spar {pending[0]}")]
    return []


def respar_parent(project: Project, request_id: str) -> str | None:
    """The sheet a re-spar request repeats; None for any other request. Read-only."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT parent, respar FROM chat_requests WHERE request_id = :r"),
            {"r": request_id},
        ).first()
    return None if row is None or not row[1] else str(row[0])


def request_chat(
    project: Project,
    actor: Actor,
    kind: str,
    spec: SelectionSpec,
    *,
    hypothesis: str | None = None,
    question: str | None = None,
    mode: str | None = None,
    parent: str | None = None,
    note: str | None = None,
    respar: bool = False,
) -> ChatRequested:
    """Record one request as the researcher. A spar needs `hypothesis` (and `mode`, default
    explore) and no `question`; an ask needs `question` and neither `hypothesis` nor `mode`.
    Raises `FactoryValidationError` (nothing written, every issue together) for a non-human actor,
    a bad kind, text, mode or note, or a `parent` that is no sheet or answer of the project.
    `respar` (a spar only) repeats the closed sheet `parent` over today's papers: `hypothesis` and
    `mode` default to the sheet's, and the Prepare case-for rule does not apply."""
    if actor.kind != "human":
        raise _issue("actor", "a request is the researcher's act")
    issues: list[ValidationIssue] = []
    if kind not in get_args(ChatKind):
        raise _issue("kind", f"{kind}: must be spar or ask")
    hypothesis = (hypothesis or "").strip() or None
    question = (question or "").strip() or None
    note = (note or "").strip() or None
    if respar:
        if kind != "spar":
            issues.append(ValidationIssue("kind", "only a spar can be a re-spar"))
        if parent is None:
            issues.append(ValidationIssue("parent", "a re-spar names the sheet it repeats"))
        else:
            project.index.sync()
            with project.index.connect() as conn:
                found = conn.execute(
                    text("SELECT hypothesis, mode FROM sheets WHERE sheet_id = :s"), {"s": parent}
                ).first()
            if found is not None:
                hypothesis = hypothesis or str(found[0])
                mode = mode or str(found[1])
    if kind == "spar":
        if hypothesis is None or len(hypothesis) > TEXT_MAX:
            issues.append(
                ValidationIssue(
                    "hypothesis", f"a spar has a hypothesis of 1 to {TEXT_MAX} characters"
                )
            )
        if question is not None:
            issues.append(ValidationIssue("question", "a spar has a hypothesis, not a question"))
        mode = mode or "explore"
        if mode not in get_args(ChatMode):
            issues.append(ValidationIssue("mode", f"{mode}: must be explore or prepare"))
    else:
        if question is None or len(question) > TEXT_MAX:
            issues.append(
                ValidationIssue("question", f"an ask has a question of 1 to {TEXT_MAX} characters")
            )
        if hypothesis is not None:
            issues.append(ValidationIssue("hypothesis", "an ask has a question, not a hypothesis"))
        if mode is not None:
            issues.append(ValidationIssue("mode", "only a spar has a mode"))
    if note is not None and len(note) > NOTE_MAX:
        issues.append(ValidationIssue("note", f"a note has at most {NOTE_MAX} characters"))
    project.index.sync()
    if parent is not None:
        issues.extend(
            _respar_issues(project, parent)
            if respar
            else _parent_issues(project, kind, mode, parent)
        )
    if issues:
        raise FactoryValidationError(issues)
    payload = ChatRequested(
        request_id=project.ids.new("chr"),
        kind=kind,
        selection=spec.model_dump(mode="json"),
        hypothesis=hypothesis,
        question=question,
        mode=mode,
        parent=parent,
        note=note,
        respar=respar,
    )
    with project.index.exclusive():
        project.index.sync()
        if parent is not None:
            again = (
                _respar_issues(project, parent)
                if respar
                else _parent_issues(project, kind, mode, parent)
            )
            if again:
                raise FactoryValidationError(again)
        project.record(
            [project.events.make("chat.requested", payload, actor, refs=(payload.request_id,))]
        )
    return payload


def request_respar(
    project: Project, actor: Actor, sheet_id: str, *, note: str | None = None
) -> ChatRequested:
    """Order the re-spar of the closed sheet `sheet_id`: the same hypothesis and mode over the
    sheet's own selection spec, resolved afresh when the run starts. A human act."""
    from factory.services.selection import SelectionSpec

    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT selection FROM sheets WHERE sheet_id = :s"), {"s": sheet_id}
        ).first()
    if row is None:
        raise _issue("parent", f"{sheet_id}: no such sheet")
    spec = SelectionSpec.model_validate(json.loads(row[0]))
    return request_chat(project, actor, "spar", spec, parent=sheet_id, note=note, respar=True)


def check_result_request(
    project: Project,
    actor: Actor,
    request_id: str | None,
    kind: ChatKind,
    *,
    parent: str | None = None,
    opens_mode: str | None = None,
) -> None:
    """Refuse (field `request_id`) a result that names no request of the project, a request of
    another kind, a request that this session did not take or whose taking run is no longer open,
    and, when `parent` is given, a request whose parent is not that. `opens_mode` is set when the
    result is a new sheet: the request's mode must be it and the request must have no parent (a
    follow-up writes into its parent sheet), unless it is a re-spar, which opens a new sheet. None
    passes. Read-only; the caller has synced the
    index."""
    if request_id is None:
        return
    if re.fullmatch(REQUEST_ID_RE, request_id) is None:
        raise _issue("request_id", f"{request_id}: not a chat request id")
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT r.kind, r.parent, r.mode, r.taken_run, r.taken_session, x.outcome,"
                " x.run_id, r.respar FROM chat_requests r"
                " LEFT JOIN runner_runs x ON x.run_id = r.taken_run WHERE r.request_id = :r"
            ),
            {"r": request_id},
        ).first()
    if row is None:
        raise _issue("request_id", f"{request_id}: no such chat request")
    if str(row[0]) != kind:
        raise _issue("request_id", f"{request_id}: is a request to {row[0]}, not to {kind}")
    if row[3] is None:
        raise _issue("request_id", f"{request_id}: not taken; take it with chat_request_next")
    if row[4] != actor.session:
        raise _issue("request_id", f"{request_id}: taken by another session")
    if row[6] is None or row[5] is not None:
        raise _issue("request_id", f"{request_id}: the run that took it is no longer open")
    if parent is not None and row[1] != parent:
        raise _issue("request_id", f"{request_id}: does not follow up {parent}")
    if opens_mode is not None:
        if row[1] is not None and not row[7]:
            raise _issue(
                "request_id", f"{request_id}: a follow-up writes into its parent sheet {row[1]}"
            )
        if row[2] != opens_mode:
            raise _issue("request_id", f"{request_id}: asks for mode {row[2]}, not {opens_mode}")


def _select(project: Project, where: str, params: dict[str, Any]) -> list[ChatRequestInfo]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = (
            conn.execute(text(f"{_STATE_SQL} {where} ORDER BY r.event_id"), params).mappings().all()
        )
    return [_info(r) for r in rows]


def list_requests(
    project: Project, *, kind: str | None = None, state: str | None = None
) -> list[ChatRequestInfo]:
    """Every request, oldest first, optionally of one kind and one derived state. Read-only."""
    rows = _select(project, "WHERE (:k IS NULL OR r.kind = :k)", {"k": kind})
    return [r for r in rows if state is None or r.state == state]


def open_count(project: Project, kind: str) -> int:
    """The open requests of `kind`: the pending units of the stage of that name."""
    return len(list_requests(project, kind=kind, state="open"))


def view_request(project: Project, request_id: str) -> ChatRequestInfo:
    """One request with its derived state. Read-only; refused for an unknown id."""
    rows = _select(project, "WHERE r.request_id = :r", {"r": request_id})
    if not rows:
        raise _issue("request_id", f"{request_id}: no such chat request")
    return rows[0]


def take_next(project: Project, actor: Actor, run_id: str | None) -> ChatRequestInfo | None:
    """Serve the oldest open request of the kind of run `run_id` to the agent session `actor`, and
    mark it taken by that run, in one step under the index lock. None when no request is open.
    Raises `FactoryValidationError` (nothing written) for a non-agent actor, or a `run_id` that is
    not an open run of stage `spar` or `ask` of this project (field `run`)."""
    if actor.kind != "agent":
        raise _issue("actor", "an agent session takes a request")
    with project.index.exclusive():
        project.index.sync()
        row = None
        if run_id is not None and re.fullmatch(RUN_ID_RE, run_id):
            with project.index.connect() as conn:
                row = conn.execute(
                    text("SELECT stage, outcome FROM runner_runs WHERE run_id = :r"), {"r": run_id}
                ).first()
        if row is None or row[1] is not None or str(row[0]) not in get_args(ChatKind):
            raise _issue(
                "run",
                "a request is taken only by a headless run of stage spar or ask that is open; "
                "this session is not one",
            )
        kind = str(row[0])
        with project.index.connect() as conn:
            already = conn.execute(
                text("SELECT request_id FROM chat_requests WHERE taken_run = :r"), {"r": run_id}
            ).first()
        if already is not None:
            raise _issue("run", f"this run took {already[0]} already: one run, one request")
        open_requests = [r for r in list_requests(project, kind=kind, state="open")]
        if not open_requests:
            return None
        chosen = open_requests[0]
        payload = ChatRequestTaken(request_id=chosen.request_id, run_id=str(run_id))
        project.record(
            [
                project.events.make(
                    "chat.request_taken",
                    payload,
                    actor,
                    refs=(chosen.request_id,),
                    input_blob=project.blobs.put_json(
                        {"request_id": chosen.request_id, "run_id": run_id, "kind": kind}
                    ),
                )
            ]
        )
    return replace(chosen, state="taken", taken_run=str(run_id))
