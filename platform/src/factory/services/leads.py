"""Leads: research-idea notes tied to resolved triggers, with the failed directions that share them
(slice 6, plan H-C; rulings 1, 2 and 11).

Invariants:
- A lead is refused without a trigger. An id trigger must resolve (trace's `dangling_refs` for the
  kinds trace knows, a table lookup for the others). A builder trigger stores the builder's key
  and the row it showed, and is accepted only while the builder still returns that very row
  (`trigger-stale` otherwise), so the reader sees what the proposer saw.
- `prior` is computed at write time from the lead's keys and stored in the event: every parked or
  discarded lead, every hypothesis in any state and every provider's rows that share a key, sorted,
  capped at `PRIOR_CAP` with the total count beside it.
- A lead is immutable; a decision supersedes the earlier one and nothing is deleted. Who may decide
  is the gate `hypotheses.lead_decide` (`hypothesis_gates.may_pass`); the lead's author never
  decides under an `agent` policy.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.hypotheses import (
    BUILDER_KINDS,
    PRIOR_CAP,
    DiscardReason,
    LeadDecided,
    LeadDecision,
    LeadInput,
    LeadRecorded,
    Trigger,
    TriggerKind,
)
from factory.services.context import Project
from factory.services.hypothesis_gates import may_pass
from factory.services.trace import dangling_refs

LeadState = Literal["open", "promoted", "parked", "discarded"]
_ALL_STATES: tuple[LeadState, ...] = ("open", "promoted", "parked", "discarded")
_TRACE_KINDS = frozenset(
    {
        TriggerKind.WORK,
        TriggerKind.ROW,
        TriggerKind.CLAIM,
        TriggerKind.ITEM,
        TriggerKind.IDEA,
        TriggerKind.INTERPRETATION,
        TriggerKind.CONCEPT,
    }
)
_TABLE_KINDS: dict[TriggerKind, tuple[str, str]] = {
    TriggerKind.CARD: ("cards", "card_id"),
    TriggerKind.CONTRADICTION: ("contradictions", "contradiction_id"),
    TriggerKind.LEAD: ("leads", "lead_id"),
    TriggerKind.HYPOTHESIS: ("hypotheses", "hypothesis_id"),
}
_BUILDER_PAGE = 500
_GAP_ROW_KEYS = frozenset({"rows_axis", "columns_axis", "filters", "row", "column", "count"})

PriorSource = Callable[[Project, Collection[str]], Iterable[str]]
PRIOR_SOURCES: list[PriorSource] = []
"""Providers of prior-failure ids beyond leads: the failed-directions registry, which
`services.directions` registers at import (`trigger_issues` and `prior_for` import it where they
read the list, so a surface that never imported it still sees the registry). Each takes the
lead's keys and returns the ids that share at least one."""

DirectionExists = Callable[[Project, str], bool]
DIRECTION_RESOLVERS: list[DirectionExists] = []
"""Resolvers of `dir_` triggers; `services.directions` registers the closed directions."""


class LeadView(StrictModel):
    lead_id: str
    text: str
    triggers: tuple[Trigger, ...]
    framework: str | None
    prior: tuple[str, ...]
    prior_total: int
    state: LeadState
    author_session: str
    event_id: str
    decision: str | None = None
    reason: str | None = None
    note: str | None = None


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


# --- Trigger resolution -------------------------------------------------------------------


def _exists(project: Project, table: str, column: str, value: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(f"SELECT 1 FROM {table} WHERE {column} = :v"),
            {"v": value},
        ).first()
    return row is not None


def _builder_row_current(project: Project, trigger: Trigger) -> bool:
    """Whether the builder returns, now, the very row the trigger stored under its key."""
    row = dict(trigger.row or {})
    try:
        if trigger.kind is TriggerKind.MATCH:
            return _match_current(project, trigger.ref, row)
        if trigger.kind is TriggerKind.CONFLICT:
            return _conflict_current(project, trigger.ref, row)
        return _gap_current(project, trigger.ref, row)
    except (FactoryValidationError, KeyError, TypeError):
        return False


def _match_current(project: Project, match_key: str, stored: dict[str, JsonValue]) -> bool:
    from factory.services.matching import match  # matching imports ideas, cards

    problem = str(stored.pop("problem_id"))
    for inferred in (False, True):
        after: str | None = None
        while True:
            page = match(
                project, problem, include_inferred=inferred, limit=_BUILDER_PAGE, after=after
            )
            for found in page.rows:
                if (
                    found.row_key == stored.get("row_key")
                    and page.match_key == match_key
                    and found.model_dump(mode="json") == stored
                ):
                    return True
            if page.next_after is None:
                break
            after = page.next_after
    return False


def _conflict_current(project: Project, group_id: str, stored: dict[str, JsonValue]) -> bool:
    from factory.services.finders import find_conflicts  # finders import the evidence report

    after: str | None = None
    while True:
        page = find_conflicts(project, group_id=group_id, limit=_BUILDER_PAGE, after=after)
        for pair in page.conflicts:
            if (pair.row_a, pair.row_b) == (stored.get("row_a"), stored.get("row_b")):
                return pair.model_dump(mode="json") == stored
        if page.next_after is None:
            return False
        after = page.next_after


def _gap_current(project: Project, gap_key: str, stored: dict[str, JsonValue]) -> bool:
    from factory.services.finders import find_gaps  # finders import the evidence report

    if set(stored) != _GAP_ROW_KEYS:  # nothing but the builder's own row reaches the critic
        return False
    filters = stored["filters"]
    if not isinstance(filters, dict):  # free text in `filters` would reach the critic (R-51)
        return False
    report = find_gaps(
        project,
        rows_axis=str(stored["rows_axis"]),
        columns_axis=str(stored["columns_axis"]),
        filters={str(k): str(v) for k, v in filters.items()},
    )
    if report.gap_key != gap_key:
        return False
    return any(
        {
            "rows_axis": report.rows_axis,
            "columns_axis": report.columns_axis,
            "filters": report.filters,
            **cell.model_dump(mode="json"),
        }
        == stored
        for cell in report.empty
    )


def trigger_issues(project: Project, triggers: Sequence[Trigger]) -> list[ValidationIssue]:
    """Why a trigger cannot be recorded; empty when every one resolves (see module invariants)."""
    import factory.services.directions  # noqa: F401  (fills DIRECTION_RESOLVERS; imports this)

    issues: list[ValidationIssue] = []
    by_trace = {i: t for i, t in enumerate(triggers) if t.kind in _TRACE_KINDS}
    dangling = set(dangling_refs(project, [t.ref for t in by_trace.values()]))
    for i, trigger in enumerate(triggers):
        field = f"triggers.{i}"
        if trigger.kind in _TRACE_KINDS:
            if trigger.ref in dangling:
                issues.append(ValidationIssue(field, "unknown"))
        elif trigger.kind in _TABLE_KINDS:
            table, column = _TABLE_KINDS[trigger.kind]
            if not _exists(project, table, column, trigger.ref):
                issues.append(ValidationIssue(field, "unknown"))
        elif trigger.kind in BUILDER_KINDS:
            if not _builder_row_current(project, trigger):
                issues.append(ValidationIssue(field, "trigger-stale"))
        elif not any(resolve(project, trigger.ref) for resolve in DIRECTION_RESOLVERS):
            issues.append(ValidationIssue(field, "unknown"))
    return issues


# --- Keys and prior -----------------------------------------------------------------------


def card_keys(project: Project, card_id: str) -> set[str]:
    """The card, its subject (a work or the idea, with the idea it resolves to) and the property
    keys it asserts: what is reachable from a card in one step."""
    from factory.services.ideas import resolve_idea  # ideas import the lineage services

    keys = {card_id}
    with project.index.connect() as conn:
        subject = conn.execute(
            text("SELECT subject FROM cards WHERE card_id = :c"), {"c": card_id}
        ).scalar()
        props = conn.execute(
            text("SELECT DISTINCT property_key FROM card_props WHERE card_id = :c"), {"c": card_id}
        ).scalars()
        keys.update(str(p) for p in props)
    if subject is not None:
        keys.add(str(subject))
        if str(subject).startswith("ida_"):
            keys.add(resolve_idea(project, str(subject)))
    return keys


def lead_keys(project: Project, triggers: Sequence[Trigger]) -> tuple[str, ...]:
    """The keys of a lead: its trigger refs plus the cards, ideas and properties reachable in one
    step (a card's subject, properties and idea; both rows of a conflict), sorted."""
    project.index.sync()
    keys: set[str] = set()
    for trigger in triggers:
        keys.add(trigger.ref)
        row = trigger.row or {}
        if trigger.kind is TriggerKind.CARD:
            keys |= card_keys(project, trigger.ref)
        elif trigger.kind is TriggerKind.MATCH and isinstance(row.get("card_id"), str):
            keys |= card_keys(project, str(row["card_id"]))
        elif trigger.kind is TriggerKind.CONFLICT:
            keys.update(str(row[k]) for k in ("row_a", "row_b") if k in row)
    return tuple(sorted(keys))


def _hypothesis_prior(project: Project, keys: Collection[str]) -> list[str]:
    from factory.services.hypotheses import hypothesis_prior  # hypotheses import this module

    return hypothesis_prior(project, keys)


def prior_for(
    project: Project, keys: Collection[str], *, exclude: str | None = None
) -> tuple[list[str], int]:
    """Ids of the failures and earlier work sharing at least one key: parked and discarded leads,
    then each registered provider's ids; sorted, capped at `PRIOR_CAP`, with the total count."""
    import factory.services.directions  # noqa: F401  (fills PRIOR_SOURCES; imports this)

    project.index.sync()
    found: set[str] = set()
    if keys:
        marks = ", ".join(f":k{i}" for i in range(len(keys)))
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT l.lead_id FROM lead_keys k JOIN leads l "
                    "ON l.lead_id = k.lead_id WHERE l.state IN ('parked', 'discarded') "
                    f"AND k.key IN ({marks})"
                ),
                {f"k{i}": k for i, k in enumerate(sorted(keys))},
            ).scalars()
            found.update(str(r) for r in rows)
        found.update(_hypothesis_prior(project, keys))
        for source in PRIOR_SOURCES:
            found.update(source(project, keys))
    found.discard(exclude or "")
    ordered = sorted(found)
    return ordered[:PRIOR_CAP], len(ordered)


# --- Recording and deciding ----------------------------------------------------------------


def record_lead(project: Project, actor: Actor, item: LeadInput) -> str:
    """Record a lead and return its id. Refused, with nothing written: an actor that is neither
    an agent nor a human (`actor`); a trigger that names no row (`triggers.<i>`: `unknown`) or a
    builder row that has since changed (`triggers.<i>`: `trigger-stale`). A lead without a
    trigger, a text over 600 characters or a malformed trigger fail `LeadInput` itself."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human records a lead")
    with project.index.exclusive():
        project.index.sync()
        issues = trigger_issues(project, item.triggers)
        if issues:
            raise FactoryValidationError(issues)
        keys = lead_keys(project, item.triggers)
        prior, total = prior_for(project, keys)
        lead_id = project.ids.new("led")
        payload = LeadRecorded(
            lead_id=lead_id,
            text=item.text,
            triggers=item.triggers,
            framework=item.framework,
            prior=tuple(prior),
            prior_total=total,
            keys=keys,
        )
        input_blob = (
            project.blobs.put_json(item.model_dump(mode="json")) if actor.kind == "agent" else None
        )
        refs = [lead_id] + [t.ref for t in item.triggers if t.kind not in BUILDER_KINDS]
        project.record(
            [project.events.make("lead.recorded", payload, actor, refs=refs, input_blob=input_blob)]
        )
    return lead_id


def _row_view(project: Project, row: object) -> LeadView:
    import json

    m = row._mapping  # type: ignore[attr-defined]
    return LeadView(
        lead_id=str(m["lead_id"]),
        text=str(m["text"]),
        triggers=tuple(Trigger.model_validate(t) for t in json.loads(str(m["triggers_json"]))),
        framework=None if m["framework"] is None else str(m["framework"]),
        prior=tuple(json.loads(str(m["prior_json"]))),
        prior_total=int(m["prior_total"]),
        state=m["state"],
        author_session=str(m["author_session"]),
        event_id=str(m["event_id"]),
        decision=None if m["decision"] is None else str(m["decision"]),
        reason=None if m["reason"] is None else str(m["reason"]),
        note=None if m["note"] is None else str(m["note"]),
    )


def lead_view(project: Project, lead_id: str) -> LeadView | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT * FROM leads WHERE lead_id = :l"), {"l": lead_id}).first()
    return None if row is None else _row_view(project, row)


def list_leads(project: Project, *, states: Collection[LeadState] = _ALL_STATES) -> list[LeadView]:
    """Leads in id order whose state is in `states` (`open`: undecided)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT * FROM leads ORDER BY lead_id")).all()
    return [v for v in (_row_view(project, r) for r in rows) if v.state in states]


def decide_lead(
    project: Project,
    actor: Actor,
    lead_id: str,
    decision: LeadDecision,
    reason: DiscardReason | None = None,
    note: str | None = None,
) -> str:
    """Promote, park or discard a lead and return the event id. Refused, with nothing written: an
    unknown lead (`lead_id`); a discard without a reason, a reason on another decision, or the
    reason `other` without a note (`reason`, `note`); an agent at a `human` gate (`actor`); the
    lead's own session under an `agent` policy (`session`)."""
    with project.index.exclusive():
        project.index.sync()
        view = lead_view(project, lead_id)
        if view is None:
            raise _refuse("lead_id", "unknown")
        issues: list[ValidationIssue] = []
        if decision == "discard" and reason is None:
            issues.append(ValidationIssue("reason", "a discard needs a reason"))
        elif decision != "discard" and reason is not None:
            issues.append(ValidationIssue("reason", "only a discard has a reason"))
        elif reason is DiscardReason.OTHER and not (note and note.strip()):
            issues.append(ValidationIssue("note", "the reason `other` needs a note"))
        if note is not None and not note.strip():
            issues.append(ValidationIssue("note", "must not be blank"))
        elif note is not None and len(note) > 300:
            issues.append(ValidationIssue("note", "at most 300 characters"))
        if issues:
            raise FactoryValidationError(issues)
        verdict = may_pass(
            project, actor, "hypotheses.lead_decide", proposer_sessions={view.author_session}
        )
        verdict.raise_if_refused()
        payload = LeadDecided(
            lead_id=lead_id,
            decision=decision,
            reason=reason,
            note=note.strip() if note else None,
            policy=verdict.policy.kind,
        )
        input_blob = (
            project.blobs.put_json(payload.model_dump(mode="json"))
            if actor.kind == "agent"
            else None
        )
        event = project.events.make(
            "lead.decided", payload, actor, refs=[lead_id], input_blob=input_blob
        )
        project.record([event])
    return event.id
