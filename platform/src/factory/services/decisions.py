"""Suggest and select: record, list and view the decisions the scientist owns (slice 8, plan A3).

Invariants:
- Only an agent suggests and only a human selects. A refusal writes nothing and returns
  `ValidationIssue`s; the checks are the ones the folds of `index/decisions.py` enforce, so what the
  service accepts is what the index folds, and a hand-written event that fails one changes nothing.
- R-20: a suggestion that names a held-out seed (its id or a stated identifier) in its subject,
  explanation, item text or grounds is accepted and scrubbed before it is recorded, with the token
  the other agent surfaces use, and nothing in the reply or an error says that anything was
  scrubbed: a refusal would tell the agent which identifiers are held out. `held_out_tokens` is
  called without work ids: a work's id is not a seed's identity (decisions 37 item 9 and 81).
- A decision is `open` while it has no accepted selection and is not superseded. The latest
  accepted selection decides the item statuses; earlier ones stay in the log.
- Binding lives in `decision_binding` (no dependency on `withholding`, which would close an
  import cycle through `seeds`).
- Reads come from the index only. The fold stores the accepted selection on `decision_sets`
  (event id, channel, note, flag, time), so the view is what the fold took, whatever the rigor mode
  or host is now. The note is the human's view: an agent-facing surface scrubs it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.decisions import (
    DecisionItem,
    DecisionLevel,
    DecisionSelected,
    DecisionSuggested,
)
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.human_channel import require_human_channel
from factory.services.withholding import WITHHELD, held_out_tokens, withhold

DecisionState = Literal["open", "selected", "superseded"]


class DecisionItemView(StrictModel):
    item_id: str
    text: str
    grounds: tuple[str, ...]
    recommended: bool
    origin: Literal["suggested", "added"]
    status: Literal["proposed", "validated", "rejected", "added"]


class SelectionView(StrictModel):
    """The latest accepted selection, as the fold took it."""

    event_id: str
    actor: str
    ts: str
    selected: tuple[str, ...]
    added: tuple[str, ...]
    note: str
    reconstructed: bool
    channel: str


class DecisionView(StrictModel):
    decision_id: str
    level: str
    subject: str
    explanation: str
    suggested_at: str
    actor: str
    supersedes: str | None
    superseded_by: str | None
    state: DecisionState
    items: tuple[DecisionItemView, ...]
    selection: SelectionView | None = None


class DecisionRow(StrictModel):
    decision_id: str
    level: str
    subject: str
    suggested_at: str
    state: DecisionState
    supersedes: str | None
    superseded_by: str | None
    items: int
    selected: int


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []
    for err in exc.errors():
        loc = [str(p) for p in err["loc"]]
        reason = str(err["msg"]).removeprefix("Value error, ")
        out.append(ValidationIssue(".".join(loc) or "decision", reason))
    return out


def _state(superseded_by: object, validated_or_rejected: int) -> DecisionState:
    if superseded_by is not None:
        return "superseded"
    return "selected" if validated_or_rejected else "open"


# --- Suggest ------------------------------------------------------------------------------------


def _scrub_text(value: str, tokens: set[str]) -> str:
    cleaned = withhold(value, tokens)
    assert isinstance(cleaned, str)
    return cleaned


def _scrub_items(items: Sequence[DecisionItem], tokens: set[str]) -> tuple[DecisionItem, ...]:
    return tuple(
        item.model_copy(
            update={
                "text": _scrub_text(item.text, tokens),
                "grounds": tuple(_scrub_text(g, tokens) for g in item.grounds),
            }
        )
        for item in items
    )


def suggest(
    project: Project,
    actor: Actor,
    level: DecisionLevel,
    subject: str,
    explanation: str,
    items: Sequence[DecisionItem],
    supersedes: str | None = None,
) -> str:
    """Record an agent's suggestion set and return its `dec_` id. Refused, with nothing written:
    a non-agent actor (`actor`); a payload the model rejects, such as duplicate item ids, a
    `recommended` item on a research subject or a bad subject (dotted paths); a `supersedes` that
    is unknown or already superseded. Text that names a held-out seed (R-20) is scrubbed, silently,
    before it is recorded; in `subject` (a slug) the token is `withheld`."""
    if actor.kind != "agent":
        raise _refuse("actor", "only an agent suggests a decision")
    with project.writing():
        decision_id = project.ids.new("dec")
        tokens = held_out_tokens(project, include_work_ids=False)
        try:
            payload = DecisionSuggested(
                decision_id=decision_id,
                level=level,
                subject=_scrub_text(subject, tokens).replace(WITHHELD, "withheld"),
                explanation=_scrub_text(explanation, tokens),
                items=_scrub_items(items, tokens),
                supersedes=supersedes,
            )
        except ValidationError as exc:
            raise FactoryValidationError(_issues(exc)) from exc
        issues: list[ValidationIssue] = []
        if supersedes is not None:
            with project.index.connect() as conn:
                prior = conn.execute(
                    text("SELECT superseded_by FROM decision_sets WHERE decision_id = :d"),
                    {"d": supersedes},
                ).first()
            if prior is None:
                issues.append(ValidationIssue("supersedes", "unknown decision"))
            elif prior[0] is not None:
                issues.append(ValidationIssue("supersedes", "already superseded"))
        if issues:
            raise FactoryValidationError(issues)
        input_blob = project.blobs.put_json(payload.model_dump(mode="json"))
        refs = [decision_id] + ([supersedes] if supersedes else [])
        project.record(
            [
                project.events.make(
                    "decision.suggested", payload, actor, refs=refs, input_blob=input_blob
                )
            ]
        )
    return decision_id


# --- Select -------------------------------------------------------------------------------------


def select(
    project: Project,
    actor: Actor,
    decision_id: str,
    selected: Sequence[str],
    added: Sequence[str],
    note: str,
    channel: Channel,
    reconstructed: bool = False,
) -> str:
    """Record the scientist's selection and return the event id. Refused, with nothing written: a
    non-human actor (`actor`); a payload the model rejects, such as an empty selection without a
    note; an unknown (`decision_id`: `unknown`) or superseded decision; a selected id that is not
    a suggested item (`selected.<i>`); a channel the human-channel rules bar (`channel`)."""
    if actor.kind != "human":
        raise _refuse("actor", "only a human selects")
    try:
        payload = DecisionSelected(
            decision_id=decision_id,
            selected=tuple(selected),
            added=tuple(a.strip() for a in added),
            note=note.strip(),
            reconstructed=reconstructed,
            channel=channel,
        )
    except ValidationError as exc:
        raise FactoryValidationError(_issues(exc)) from exc
    with project.writing():
        with project.index.connect() as conn:
            row = conn.execute(
                text("SELECT superseded_by FROM decision_sets WHERE decision_id = :d"),
                {"d": decision_id},
            ).first()
            suggested = {
                str(r[0])
                for r in conn.execute(
                    text(
                        "SELECT item_id FROM decision_items "
                        "WHERE decision_id = :d AND origin = 'suggested'"
                    ),
                    {"d": decision_id},
                )
            }
        if row is None:
            raise _refuse("decision_id", "unknown")
        if row[0] is not None:
            raise _refuse("decision_id", f"superseded by {row[0]}")
        issues = [
            ValidationIssue(f"selected.{i}", "not an item of this decision")
            for i, item_id in enumerate(payload.selected)
            if item_id not in suggested
        ]
        if issues:
            raise FactoryValidationError(issues)
        require_human_channel(project, actor, channel, "sign-off")
        event = project.events.make("decision.selected", payload, actor, refs=[decision_id])
        project.record([event])
    return event.id


# --- Read ---------------------------------------------------------------------------------------


def list_decisions(
    project: Project, level: DecisionLevel | None = None, open_only: bool = False
) -> list[DecisionRow]:
    """Decisions in id order. `open_only` keeps those with no accepted selection that are not
    superseded."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.decision_id, d.level, d.subject, d.suggested_at, d.supersedes, "
                "d.superseded_by, "
                "(SELECT COUNT(*) FROM decision_items i WHERE i.decision_id = d.decision_id "
                " AND i.origin = 'suggested') AS n_items, "
                "(SELECT COUNT(*) FROM decision_items i WHERE i.decision_id = d.decision_id "
                " AND i.status = 'validated') AS n_valid, "
                "(SELECT COUNT(*) FROM decision_items i WHERE i.decision_id = d.decision_id "
                " AND i.status IN ('validated', 'rejected')) AS n_decided "
                "FROM decision_sets d ORDER BY d.decision_id"
            )
        ).all()
    found = [
        DecisionRow(
            decision_id=str(r[0]),
            level=str(r[1]),
            subject=str(r[2]),
            suggested_at=str(r[3]),
            state=_state(r[5], int(r[8])),
            supersedes=None if r[4] is None else str(r[4]),
            superseded_by=None if r[5] is None else str(r[5]),
            items=int(r[6]),
            selected=int(r[7]),
        )
        for r in rows
    ]
    return [
        d
        for d in found
        if (level is None or d.level == level.value) and (not open_only or d.state == "open")
    ]


def view_decision(project: Project, decision_id: str) -> DecisionView:
    """One decision with its items (status, origin, grounds, recommended), its latest selection and
    its supersession links. Refused (`decision_id`: `unknown`) for an unknown id."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT level, subject, explanation, suggested_at, actor, supersedes, "
                "superseded_by, sel_event, sel_actor, sel_ts, sel_channel, sel_note, "
                "sel_reconstructed, sel_selected, sel_added "
                "FROM decision_sets WHERE decision_id = :d"
            ),
            {"d": decision_id},
        ).first()
        if row is None:
            raise _refuse("decision_id", "unknown")
        item_rows = conn.execute(
            text(
                "SELECT item_id, text, grounds, recommended, origin, status FROM decision_items "
                "WHERE decision_id = :d ORDER BY origin DESC, item_id"
            ),
            {"d": decision_id},
        ).all()
    items = tuple(
        DecisionItemView(
            item_id=str(r[0]),
            text=str(r[1]),
            grounds=tuple(json.loads(str(r[2]))),
            recommended=bool(r[3]),
            origin=r[4],
            status=r[5],
        )
        for r in item_rows
    )
    decided = sum(1 for i in items if i.status in ("validated", "rejected"))
    return DecisionView(
        decision_id=decision_id,
        level=str(row[0]),
        subject=str(row[1]),
        explanation=str(row[2]),
        suggested_at=str(row[3]),
        actor=str(row[4]),
        supersedes=None if row[5] is None else str(row[5]),
        superseded_by=None if row[6] is None else str(row[6]),
        state=_state(row[6], decided),
        items=items,
        selection=None
        if row[7] is None
        else SelectionView(
            event_id=str(row[7]),
            actor=str(row[8]),
            ts=str(row[9]),
            selected=tuple(json.loads(str(row[13]))),
            added=tuple(json.loads(str(row[14]))),
            note=str(row[11]),
            reconstructed=bool(row[12]),
            channel=str(row[10]),
        ),
    )
