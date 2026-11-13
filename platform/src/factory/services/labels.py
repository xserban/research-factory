"""Free labels: applications, withdrawals, human decisions and reversible key merges (slice 3d,
plan Regions-C).

A label is organisation, not evidence: it lives in its own tables, selects nothing until its key
is promoted to a term (`services/terms.py`), and no evidence module imports this one.

Invariants:
- The platform computes an application's status. A human's application, and a Zotero tag, is
  `confirmed`; an agent's is `stated` when its quote is verbatim in the anchored element of a
  conversion of the work and contains the label key, otherwise `inferred`. A human's `confirm`
  makes any live application `confirmed`; a `reject` or a withdrawal removes it from every view.
- A batch is accepted partially: a bad item is reported with its position and nothing of it is
  written; the rest are written in one append.
- Merges are human, recorded and reversible: `label.merged` adds an alias from one key to another
  and `label.unmerged` ends it; applications are never edited. A merge that closes a cycle is
  refused.
- Agent-written events carry `input_blob` (the items as sent).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import ConfigDict, Field
from sqlalchemy import text

from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.index.labels import live_key_of
from factory.model.base import StrictModel
from factory.model.cards import QuoteBasis
from factory.model.labels import (
    LabelApplicationDecided,
    LabelApplied,
    LabelMerged,
    LabelUnmerged,
    LabelWithdrawn,
    Origin,
    key_problem,
    label_key,
)
from factory.regions.rules import MemberType
from factory.services.context import Project
from factory.services.conversions import conversion_manifest, conversion_work
from factory.services.gates import gate_issues
from factory.services.imports import import_records, record_key
from factory.services.regions import _member_issues
from factory.services.results import BatchResult, ItemError
from factory.services.work_ref import resolve_work_id

PAGE = 500
ORGANISATION = "organisation"


class LabelInput(StrictModel):
    target_type: MemberType
    target: str
    text: str
    quote: QuoteBasis | None = None


class LabelView(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    """One live application as a reader sees it (`class` is `organisation` on every row)."""

    application_id: str
    target_type: MemberType
    target: str
    text: str
    key: str
    live_key: str
    status: Literal["confirmed", "stated", "inferred"]
    origin: Origin
    quote: str | None
    import_ref: str | None
    class_: str = Field(default=ORGANISATION, serialization_alias="class")


def _refuse(*issues: ValidationIssue) -> FactoryValidationError:
    return FactoryValidationError(list(issues))


# --- Quote and status ---


def quote_issues(
    project: Project, basis: QuoteBasis, prefix: str = "quote"
) -> list[ValidationIssue]:
    """Whether the quote is verbatim in the anchored element of a conversion of its work."""
    owner = conversion_work(project, basis.conversion_id)
    if owner is None:
        return [ValidationIssue(f"{prefix}.conversion_id", "conversion-unknown")]
    if owner != basis.work_id:
        return [ValidationIssue(f"{prefix}.conversion_id", "conversion-other-work")]
    try:
        manifest = conversion_manifest(project, basis.conversion_id)
    except FactoryValidationError:
        return [ValidationIssue(f"{prefix}.conversion_id", "conversion-unreadable")]
    anchor = manifest.get(basis.anchor)
    if anchor is None:
        return [ValidationIssue(f"{prefix}.anchor", "anchor-unknown")]
    if not quote_in_element(anchor.text, basis.quote):
        return [ValidationIssue(f"{prefix}.quote", "quote-not-verbatim")]
    return []


def quote_has_key(quote: str | None, *keys: str) -> bool:
    """Whether the folded quote contains any of the folded keys."""
    if quote is None:
        return False
    folded = label_key(quote)
    return any(k and k in folded for k in keys)


def _status(actor: Actor, origin: Origin, item_key: str, quote: QuoteBasis | None) -> str:
    if actor.kind == "human" or origin != "agent":
        return "confirmed"
    return (
        "stated" if quote_has_key(None if quote is None else quote.quote, item_key) else "inferred"
    )


# --- Reads ---

_LIVE = "withdrawn = 0 AND COALESCE(decision, '') != 'reject'"
_SELECT = (
    "SELECT application_id, target_type, target, text, key, live_key, status, origin, "
    "quote_text, import_ref, decision FROM labels "
)


def _view(row: Any) -> LabelView:
    return LabelView(
        application_id=str(row[0]),
        target_type=MemberType(str(row[1])),
        target=str(row[2]),
        text=str(row[3]),
        key=str(row[4]),
        live_key=str(row[5]),
        status="confirmed" if row[10] == "confirm" else str(row[6]),
        origin=str(row[7]),
        quote=None if row[8] is None else str(row[8]),
        import_ref=None if row[9] is None else str(row[9]),
    )


def labels_of(project: Project, target_type: MemberType, target: str) -> list[LabelView]:
    """The live applications on one target, by key then id."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                f"{_SELECT}WHERE target_type = :t AND target = :x AND {_LIVE} "
                "ORDER BY key, application_id"
            ),
            {"t": target_type.value, "x": target},
        ).all()
    return [_view(r) for r in found]


def list_labels(
    project: Project, *, key: str | None = None, limit: int = PAGE, offset: int = 0
) -> list[LabelView]:
    """Live applications by id, one page; `key` limits to a label key or a key merged into it."""
    where = _LIVE
    params: dict[str, Any] = {"n": limit, "o": offset}
    if key is not None:
        where += " AND (key = :k OR live_key = :k)"
        params["k"] = label_key(key)
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(f"{_SELECT}WHERE {where} ORDER BY application_id LIMIT :n OFFSET :o"), params
        ).all()
    return [_view(r) for r in found]


def _row(project: Project, application_id: str) -> Any | None:
    with project.index.connect() as conn:
        return conn.execute(
            text(
                "SELECT application_id, withdrawn, decision, applier_kind, applier_session "
                "FROM labels WHERE application_id = :a"
            ),
            {"a": application_id},
        ).first()


# --- Apply ---


def _item_issues(
    project: Project, item: LabelInput, seen: set[tuple[str, str, str]], *, agent: bool = False
) -> list[ValidationIssue]:
    problem = key_problem(item.text)
    if problem is not None:
        return [ValidationIssue("text", problem)]
    issues = [
        ValidationIssue("target", i.reason)
        for i in _member_issues(project, item.target_type, item.target)
    ]
    if issues:
        return issues
    key = label_key(item.text)
    signature = (item.target_type.value, item.target, key)
    if signature in seen:
        return [ValidationIssue("text", "duplicate-application")]
    with project.index.connect() as conn:
        live = conn.execute(
            text(
                f"SELECT 1 FROM labels WHERE target_type = :t AND target = :x AND key = :k "
                f"AND {_LIVE} AND (:agent = 0 OR origin != 'import-tag') LIMIT 1"
            ),
            {"t": item.target_type.value, "x": item.target, "k": key, "agent": int(agent)},
        ).first()
    if live is not None:
        return [ValidationIssue("text", "duplicate-application")]
    if item.quote is not None:
        issues = quote_issues(project, item.quote)
        if not issues and item.target_type is MemberType.WORK and item.quote.work_id != item.target:
            issues = [ValidationIssue("quote.work_id", "quote-other-work")]
        return issues
    return []


def _works_as_stored(project: Project, item: LabelInput) -> LabelInput:
    """`item` with a work target and the quote's work spelled as stored (IDEA-66)."""
    update: dict[str, object] = {}
    if item.target_type is MemberType.WORK:
        update["target"] = resolve_work_id(project, item.target, field="target")
    if item.quote is not None:
        work = resolve_work_id(project, item.quote.work_id, field="quote.work_id")
        update["quote"] = item.quote.model_copy(update={"work_id": work})
    return item.model_copy(update=update) if update else item


def _apply(
    project: Project,
    actor: Actor,
    items: Sequence[LabelInput],
    *,
    origin: Origin,
    import_refs: Sequence[str | None] | None = None,
) -> BatchResult[str]:
    if actor.kind not in ("agent", "human"):
        raise _refuse(ValidationIssue("actor", "only an agent or a human applies a label"))
    with project.index.exclusive():
        project.index.sync()
        rejected: list[ItemError] = []
        events: list[Event] = []
        written: list[str] = []
        seen: set[tuple[str, str, str]] = set()
        blob = (
            project.blobs.put_json([i.model_dump(mode="json") for i in items])
            if actor.kind == "agent"
            else None
        )
        for index, item in enumerate(items):
            try:
                item = _works_as_stored(project, item)
            except FactoryValidationError as exc:
                rejected.append(ItemError(index=index, issues=exc.issues))
                continue
            issues = _item_issues(project, item, seen, agent=actor.kind == "agent")
            if issues:
                rejected.append(ItemError(index=index, issues=issues))
                continue
            key = label_key(item.text)
            seen.add((item.target_type.value, item.target, key))
            application_id = f"lbl_{project.ids.ulid()}"
            ref = None if import_refs is None else import_refs[index]
            payload = LabelApplied(
                application_id=application_id,
                target_type=item.target_type,
                target=item.target,
                text=item.text.strip(),
                key=key,
                quote=item.quote,
                status=_status(actor, origin, key, item.quote),
                origin=origin,
                import_ref=ref,
            )
            events.append(
                project.events.make(
                    "label.applied",
                    payload,
                    actor,
                    refs=[application_id, item.target],
                    input_blob=blob,
                )
            )
            written.append(application_id)
        if events:
            project.record(events)
        return BatchResult[str](written=written, rejected=rejected)


def apply_labels(project: Project, actor: Actor, items: Sequence[LabelInput]) -> BatchResult[str]:
    """Apply labels (agent or human), partially accepting the batch; returns the new application
    ids in input order and the rejected items (fields `text`, `target`, `quote...`)."""
    return _apply(project, actor, items, origin="agent" if actor.kind == "agent" else "human")


def import_tags_as_labels(project: Project, import_id: str) -> int:
    """Apply the tags of an import's resolved records, as the researcher, to the works they
    resolved to (origin `import-tag`, confirmed); a tag already applied from the same record is
    skipped, so the step is idempotent. Returns the number of applications written."""
    project.index.sync()
    with project.index.connect() as conn:
        resolved = {
            int(o): str(w)
            for o, w in conn.execute(
                text(
                    "SELECT ordinal, work_id FROM import_records WHERE import_id = :i "
                    "AND link_state = 'resolved' AND work_id IS NOT NULL"
                ),
                {"i": import_id},
            ).all()
        }
        applied = {
            (str(t), str(k))
            for t, k in conn.execute(
                text("SELECT target, key FROM labels WHERE origin = 'import-tag'")
            ).all()
        }
    items: list[LabelInput] = []
    refs: list[str | None] = []
    for record in import_records(project, import_id):
        work = resolved.get(record.ordinal)
        if work is None:
            continue
        ref = record_key(import_id, record.ordinal)
        for tag in record.fields.tags if record.fields else []:
            # keyed on the work and the key, withdrawn or not: a withdrawn tag stays withdrawn
            if key_problem(tag) is None and (work, label_key(tag)) not in applied:
                applied.add((work, label_key(tag)))
                items.append(LabelInput(target_type=MemberType.WORK, target=work, text=tag))
                refs.append(ref)
    if not items:
        return 0
    return len(
        _apply(project, project.human_actor(), items, origin="import-tag", import_refs=refs).written
    )


# --- Withdraw and decide ---


def withdraw_label(project: Project, actor: Actor, application_id: str, reason: str) -> str:
    """Withdraw an application: a human any, an agent only its own session's. Returns the event
    id. Refused (fields `actor`, `application_id`, `reason`) for an unknown or already withdrawn
    application, another session's, or a blank reason."""
    if actor.kind not in ("agent", "human"):
        raise _refuse(ValidationIssue("actor", "only an agent or a human withdraws a label"))
    with project.index.exclusive():
        project.index.sync()
        row = _row(project, application_id)
        issues: list[ValidationIssue] = []
        if row is None:
            issues.append(ValidationIssue("application_id", "application-unknown"))
        elif row[1]:
            issues.append(ValidationIssue("application_id", "already-withdrawn"))
        elif actor.kind == "agent" and (row[3] != "agent" or row[4] != actor.session):
            issues.append(ValidationIssue("application_id", "not-yours"))
        if not reason.strip():
            issues.append(ValidationIssue("reason", "state why"))
        if issues:
            raise _refuse(*issues)
        event = project.events.make(
            "label.withdrawn",
            LabelWithdrawn(application_id=application_id, reason=reason),
            actor,
            refs=[application_id],
            input_blob=project.blobs.put_json({"application_id": application_id})
            if actor.kind == "agent"
            else None,
        )
        project.record([event])
        return event.id


def decide_application(
    project: Project, actor: Actor, application_id: str, decision: Literal["confirm", "reject"]
) -> str:
    """A human confirms or rejects an application (gate `labels.application_confirm`); the latest
    decision binds. Returns the event id."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "labels.application_confirm")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human decides an application")]
        row = _row(project, application_id)
        if row is None:
            issues.append(ValidationIssue("application_id", "application-unknown"))
        elif row[1]:
            issues.append(ValidationIssue("application_id", "already-withdrawn"))
        if issues:
            raise _refuse(*issues)
        event = project.events.make(
            "label.application_decided",
            LabelApplicationDecided(application_id=application_id, decision=decision),
            actor,
            refs=[application_id],
        )
        project.record([event])
        return event.id


# --- Key merges ---


def _key_known(project: Project, key: str) -> bool:
    with project.index.connect() as conn:
        return (
            conn.execute(text("SELECT 1 FROM labels WHERE key = :k LIMIT 1"), {"k": key}).first()
            is not None
        )


def label_merge_issues(project: Project, into_key: str, from_key: str) -> list[ValidationIssue]:
    """Why `from_key` cannot be merged into `into_key` now (the caller holds the index lock and has
    synced)."""
    issues: list[ValidationIssue] = []
    for field, key in (("into_key", into_key), ("from_key", from_key)):
        if key_problem(key) is not None or label_key(key) != key:
            issues.append(ValidationIssue(field, "not-a-label-key"))
        elif not _key_known(project, key):
            issues.append(ValidationIssue(field, "label-unknown"))
    if issues:
        return issues
    with project.index.connect() as conn:
        if conn.execute(
            text("SELECT 1 FROM label_merges WHERE from_key = :k AND active = 1"), {"k": from_key}
        ).first():
            return [ValidationIssue("from_key", "already-merged")]
        if from_key == into_key or live_key_of(conn, into_key) == from_key:
            return [ValidationIssue("into_key", "merge-cycle")]
    return []


def build_label_merge(
    project: Project,
    actor: Actor,
    into_key: str,
    from_key: str,
    reason: str,
    proposal_id: str | None = None,
) -> Event:
    """The `label.merged` event for a merge that passes `label_merge_issues` (not recorded). The
    caller holds the index lock, has synced, and records the event with the decision it serves."""
    issues = label_merge_issues(project, into_key, from_key)
    if not reason.strip():
        issues.append(ValidationIssue("reason", "state why"))
    if issues:
        raise _refuse(*issues)
    return project.events.make(
        "label.merged",
        LabelMerged(into_key=into_key, from_key=from_key, reason=reason, proposal_id=proposal_id),
        actor,
        refs=[into_key, from_key],
    )


def merge_labels(project: Project, actor: Actor, into_key: str, from_key: str, reason: str) -> str:
    """Merge `from_key` into `into_key` (human, reversible; gate `consolidation.decide`) and
    return the event id. Refused (fields `actor`, `into_key`, `from_key`, `reason`) for a
    non-human, an unknown key, a key already merged, a cycle or a blank reason."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "consolidation.decide")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human merges labels")]
        if issues:
            raise _refuse(*issues)
        event = build_label_merge(project, actor, label_key(into_key), label_key(from_key), reason)
        project.record([event])
        return event.id


def unmerge_labels(project: Project, actor: Actor, merge_event: str, reason: str) -> str:
    """Reverse one active label merge (human) and return the event id. Refused (fields `actor`,
    `merge_event`, `reason`) for a non-human, a merge that is unknown or already reversed, or a
    blank reason."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "consolidation.decide")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human unmerges labels")]
        with project.index.connect() as conn:
            active = conn.execute(
                text("SELECT 1 FROM label_merges WHERE event_id = :e AND active = 1"),
                {"e": merge_event},
            ).first()
        if active is None:
            issues.append(ValidationIssue("merge_event", "not-merged"))
        if not reason.strip():
            issues.append(ValidationIssue("reason", "state why"))
        if issues:
            raise _refuse(*issues)
        event = project.events.make(
            "label.unmerged",
            LabelUnmerged(merge_event=merge_event, reason=reason),
            actor,
            refs=[merge_event],
        )
        project.record([event])
        return event.id
