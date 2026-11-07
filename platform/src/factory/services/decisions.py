"""Suggest and select: record, list and view the decisions the scientist owns (slice 8, plan A3).

Invariants:
- Only an agent suggests and only a human selects. A refusal writes nothing and returns
  `ValidationIssue`s; the checks are the ones the folds of `index/decisions.py` enforce, so what the
  service accepts is what the index folds, and a hand-written event that fails one changes nothing.
- R-20: a suggestion that names a held-out seed (its id or a stated identifier) in its subject,
  explanation, item text or grounds is refused, not scrubbed. `held_out_tokens` is called without
  work ids: a work's id is not a seed's identity (decisions 37 item 9 and 81).
- A decision is `open` while it has no accepted selection and is not superseded. The latest
  accepted selection decides the item statuses; earlier ones stay in the log.
- Binding (A7): `bind` is how the question, seed, probe and protocol records cite the decisions they
  implement. A cited id must be a known decision at the record's level, cited once, in every mode.
  In `pilot` and `systematic` the record must also cite at least one decision, and each cited
  decision must have an accepted selection and not be superseded. Whether the act matches the
  selection is a check rule, not a refusal.
- Reads come from the index, except the selection's note, channel and flags, which the view reads
  from the log. They are the human's view: an agent-facing surface scrubs them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.clock import format_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.index.human_channel import sign_off_counts
from factory.model.base import StrictModel
from factory.model.decisions import (
    DecisionItem,
    DecisionLevel,
    DecisionSelected,
    DecisionSuggested,
)
from factory.model.project import RigorMode
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.human_channel import require_human_channel
from factory.services.withholding import held_out_tokens, withhold

DecisionState = Literal["open", "selected", "superseded"]


class DecisionItemView(StrictModel):
    item_id: str
    text: str
    grounds: tuple[str, ...]
    recommended: bool
    origin: Literal["suggested", "added"]
    status: Literal["proposed", "validated", "rejected", "added"]


class SelectionView(StrictModel):
    """The latest accepted selection, read from the log."""

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


def _names_held_out(project: Project, fields: dict[str, str]) -> list[ValidationIssue]:
    """Issues for each field that contains a held-out seed's id or stated identifier (R-20)."""
    tokens = held_out_tokens(project, include_work_ids=False)
    if not tokens:
        return []
    return [
        ValidationIssue(name, "names a held-out seed (R-20)")
        for name, value in fields.items()
        if withhold(value, tokens) != value
    ]


def _grounds_fields(prefix: str, items: Sequence[DecisionItem]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for i, item in enumerate(items):
        fields[f"{prefix}.{i}.text"] = item.text
        for j, ground in enumerate(item.grounds):
            fields[f"{prefix}.{i}.grounds.{j}"] = ground
    return fields


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
    is unknown or already superseded; any text that names a held-out seed (R-20)."""
    if actor.kind != "agent":
        raise _refuse("actor", "only an agent suggests a decision")
    with project.writing():
        decision_id = project.ids.new("dec")
        try:
            payload = DecisionSuggested(
                decision_id=decision_id,
                level=level,
                subject=subject,
                explanation=explanation,
                items=tuple(items),
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
        fields = {"subject": subject, "explanation": explanation}
        fields.update(_grounds_fields("items", payload.items))
        issues.extend(_names_held_out(project, fields))
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


# --- Bind ---------------------------------------------------------------------------------------


def bind(
    project: Project, level: DecisionLevel, decision_ids: Sequence[str] | None
) -> tuple[str, ...]:
    """The decision ids a record cites, checked, for the event's `decision_ids`. The caller has
    synced the index. Refused, with nothing written (`decision_ids` and `decision_ids.<i>`): a
    duplicate, an unknown id, a decision at another level; and, outside `exploratory`, no id at all
    or an id with no accepted selection (open, or superseded). A cited decision is a selection the
    record implements; an empty result is legal only in `exploratory`."""
    ids = tuple(decision_ids or ())
    if len(set(ids)) != len(ids):
        raise _refuse("decision_ids", "a decision is cited once")
    with project.index.connect() as conn:
        mode = RigorMode(
            str(
                conn.execute(
                    text("SELECT rigor_mode FROM project WHERE slug = :slug"),
                    {"slug": project.paths.slug},
                ).scalar_one()
            )
        )
        issues: list[ValidationIssue] = []
        for i, decision_id in enumerate(ids):
            row = conn.execute(
                text(
                    "SELECT d.level, d.superseded_by, "
                    "(SELECT COUNT(*) FROM decision_items x WHERE x.decision_id = d.decision_id "
                    " AND x.status IN ('validated', 'rejected')) "
                    "FROM decision_sets d WHERE d.decision_id = :d"
                ),
                {"d": decision_id},
            ).first()
            field = f"decision_ids.{i}"
            if row is None:
                issues.append(ValidationIssue(field, "unknown decision"))
            elif str(row[0]) != level.value:
                issues.append(ValidationIssue(field, f"is a {row[0]} decision, not {level.value}"))
            elif mode is not RigorMode.EXPLORATORY:
                if row[1] is not None:
                    issues.append(ValidationIssue(field, f"superseded by {row[1]}"))
                elif not int(row[2]):
                    issues.append(ValidationIssue(field, "has no accepted selection"))
    if not ids and mode is not RigorMode.EXPLORATORY:
        issues.append(
            ValidationIssue(
                "decision_ids",
                f"{mode.value} needs a selected {level.value} decision "
                "(decision_suggest, then the scientist's selection)",
            )
        )
    if issues:
        raise FactoryValidationError(issues)
    return ids


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


def _latest_selection(
    project: Project, decision_id: str, suggested: set[str], superseded_by: str | None
) -> SelectionView | None:
    """The last selection event that the fold accepted: from a human on an allowed channel, naming
    only suggested items, and written before any suggestion that superseded the decision. The
    channel rule is read at the current rigor mode and host."""
    latest: Event | None = None
    superseded = False
    events = read_all(project.paths.events_dir, project.catalog)
    with project.index.connect() as conn:
        for event in events:
            if event.type == "decision.suggested":
                if (
                    superseded_by is not None
                    and event.payload.get("decision_id") == superseded_by
                    and event.payload.get("supersedes") == decision_id
                ):
                    superseded = True
                continue
            if event.type != "decision.selected" or superseded:
                continue
            if event.payload.get("decision_id") != decision_id or event.actor.kind != "human":
                continue
            payload = DecisionSelected.model_validate(event.payload)
            if (
                sign_off_counts(conn, event.actor, payload.channel)
                and set(payload.selected) <= suggested
            ):
                latest = event
    if latest is None:
        return None
    payload = DecisionSelected.model_validate(latest.payload)
    return SelectionView(
        event_id=latest.id,
        actor=latest.actor.id,
        ts=format_ts(latest.ts),
        selected=payload.selected,
        added=payload.added,
        note=payload.note,
        reconstructed=payload.reconstructed,
        channel=payload.channel.value,
    )


def view_decision(project: Project, decision_id: str) -> DecisionView:
    """One decision with its items (status, origin, grounds, recommended), its latest selection and
    its supersession links. Refused (`decision_id`: `unknown`) for an unknown id."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT level, subject, explanation, suggested_at, actor, supersedes, "
                "superseded_by FROM decision_sets WHERE decision_id = :d"
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
    suggested = {i.item_id for i in items if i.origin == "suggested"}
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
        selection=_latest_selection(
            project, decision_id, suggested, None if row[6] is None else str(row[6])
        ),
    )
