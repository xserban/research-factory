"""The property vocabulary: proposals, human decisions, reversible merges and `V@` (slice 6, H-A).

Invariants:
- An agent or a human proposes a definition; only a human approves or rejects it, and never from
  the session that proposed it (proposer != evaluator; no MCP tool decides, so no relay route
  exists). A property is unusable until approved.
- A key has at most one live approved definition. A changed definition is a superseding proposal
  that names its key; the earlier definition stays live until the new one is approved.
- `V@` is the first 8 hex digits of sha256 over the canonical JSON of the live approved
  definitions sorted by key, `description` stripped; a key merged into another is not live. The
  empty vocabulary is `V@00000000`.
- Merges are human, reversible and acyclic, and join properties of one kind only. They are read on
  demand from the indexed `property_merges` rows.
- The vocabulary scope is the project (slice-6 ruling 4); a region scope is Later.
- Every refusal writes nothing.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.cards import (
    MAX_RATIONALE,
    PropertyDecided,
    PropertyDef,
    PropertyMerged,
    PropertyProposed,
    PropertyUnmerged,
)
from factory.services.context import Project

PropertyState = Literal["proposed", "approved", "rejected", "superseded"]
EMPTY_VERSION = "V@00000000"
PAGE = 500


class PropertyView(StrictModel):
    key: str
    definition: PropertyDef
    state: PropertyState
    merged_into: str | None
    event_id: str


def _human_only(actor: Actor) -> None:
    if actor.kind != "human":
        raise FactoryValidationError(
            [ValidationIssue("actor", "human-only")],
        )


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _reason_issues(field: str, value: str) -> list[ValidationIssue]:
    if not value.strip():
        return [ValidationIssue(field, "state the reason for the decision")]
    if len(value) > MAX_RATIONALE:
        return [ValidationIssue(field, f"at most {MAX_RATIONALE} characters")]
    return []


def _live_row(project: Project, key: str) -> Any | None:
    """The key's live approved definition row (event id, definition json), if any."""
    with project.index.connect() as conn:
        return conn.execute(
            text(
                "SELECT event_id, definition_json FROM properties "
                "WHERE key = :k AND state = 'approved' ORDER BY event_id DESC LIMIT 1"
            ),
            {"k": key},
        ).first()


def _pending_row(project: Project, key: str) -> Any | None:
    """The key's latest pending proposal (event id, session of the proposing event)."""
    with project.index.connect() as conn:
        return conn.execute(
            text(
                "SELECT p.event_id, e.session FROM properties p JOIN events e ON e.id = p.event_id "
                "WHERE p.key = :k AND p.state = 'proposed' ORDER BY p.event_id DESC LIMIT 1"
            ),
            {"k": key},
        ).first()


def propose_property(
    project: Project,
    actor: Actor,
    definition: PropertyDef,
    *,
    supersedes: str | None = None,
) -> str:
    """Record a definition proposal (agent or human) and return its key. Refused, with nothing
    written: for another actor kind (`actor`); a scope other than `project` (`scope`); a key that
    is approved already without `supersedes` naming it (`key`: `exists`); a `supersedes` that is
    not the proposal's key or names no approved definition (`supersedes`); a key with a proposal
    pending (`key`: `pending`)."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human proposes a property")
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if definition.scope != "project":
            issues.append(ValidationIssue("scope", "unsupported"))
        live = _live_row(project, definition.key)
        if supersedes is not None and supersedes != definition.key:
            issues.append(ValidationIssue("supersedes", "must name the definition's own key"))
        elif supersedes is not None and live is None:
            issues.append(ValidationIssue("supersedes", "unknown"))
        elif supersedes is None and live is not None:
            issues.append(ValidationIssue("key", "exists"))
        if _pending_row(project, definition.key) is not None:
            issues.append(ValidationIssue("key", "pending"))
        if issues:
            raise FactoryValidationError(issues)
        input_blob = (
            project.blobs.put_json(
                {"definition": definition.model_dump(mode="json"), "supersedes": supersedes}
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "vocabulary.property_proposed",
                    PropertyProposed(definition=definition, supersedes=supersedes),
                    actor,
                    refs=[definition.key],
                    input_blob=input_blob,
                )
            ]
        )
    return definition.key


def decide_property(
    project: Project,
    actor: Actor,
    key: str,
    decision: Literal["approve", "reject"],
    rationale: str,
) -> str:
    """Record a human decision on a key's pending proposal and return the event id. A rejection
    with no proposal pending withdraws the live approved definition. Refused, with nothing
    written: for a non-human actor (`actor`: `human-only`) or the proposing session (`actor`:
    `proposer-session`); nothing to decide (`key`: `nothing-to-decide`); a blank or long
    rationale (`rationale`)."""
    _human_only(actor)  # gate hypotheses.property_approve (slice-M gate, floor human)
    with project.index.exclusive():
        project.index.sync()
        pending = _pending_row(project, key)
        issues = _reason_issues("rationale", rationale)
        if pending is None and (decision == "approve" or _live_row(project, key) is None):
            issues.append(ValidationIssue("key", "nothing-to-decide"))
        elif pending is not None and str(pending[1]) == actor.session:
            issues.append(ValidationIssue("actor", "proposer-session"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "vocabulary.property_decided",
            PropertyDecided(key=key, decision=decision, rationale=rationale),
            actor,
            refs=[key],
        )
        project.record([event])
        return event.id


def _merged_into(project: Project, key: str) -> str | None:
    """Where the latest merge event of `key` sends it; None when the latest is an unmerge."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT kind, into_key FROM property_merges WHERE from_key = :k "
                "ORDER BY event_id DESC LIMIT 1"
            ),
            {"k": key},
        ).first()
    return None if row is None or row[0] != "merged" else str(row[1])


def _chain_reaches(project: Project, start: str, goal: str) -> bool:
    seen: set[str] = set()
    current: str | None = start
    while current is not None and current not in seen:
        if current == goal:
            return True
        seen.add(current)
        current = _merged_into(project, current)
    return False


def _kind_of(row: Any) -> str:
    return str(PropertyDef.model_validate_json(str(row[1])).kind.value)


def merge_properties(project: Project, actor: Actor, from_key: str, into: str, reason: str) -> str:
    """Merge `from_key` into `into` (human, reversible) and return the event id. Both must be
    approved (`from_key`, `into`: `unknown`), of one kind (`into`: `kind-differs`); `from_key`
    must not be merged already (`already-merged`); a merge that closes a cycle is `merge-cycle`
    (`into`); the reason must be stated (`reason`)."""
    _human_only(actor)
    with project.index.exclusive():
        project.index.sync()
        issues = _reason_issues("reason", reason)
        rows = {}
        for field, key in (("from_key", from_key), ("into", into)):
            row = _live_row(project, key)
            if row is None:
                issues.append(ValidationIssue(field, "unknown"))
            else:
                rows[field] = row
        if len(rows) == 2 and _kind_of(rows["from_key"]) != _kind_of(rows["into"]):
            issues.append(ValidationIssue("into", "kind-differs"))
        if "from_key" in rows and _merged_into(project, from_key) is not None:
            issues.append(ValidationIssue("from_key", "already-merged"))
        elif not issues and (from_key == into or _chain_reaches(project, into, from_key)):
            issues.append(ValidationIssue("into", "merge-cycle"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "vocabulary.property_merged",
            PropertyMerged(from_key=from_key, into=into, reason=reason),
            actor,
            refs=[from_key, into],
        )
        project.record([event])
        return event.id


def unmerge_property(project: Project, actor: Actor, from_key: str, reason: str) -> str:
    """Revert the latest merge of `from_key` (human) and return the event id. Refused for a key
    that is not merged (`from_key`: `not-merged`) or a blank reason."""
    _human_only(actor)
    with project.index.exclusive():
        project.index.sync()
        into = _merged_into(project, from_key)
        issues = _reason_issues("reason", reason)
        if into is None:
            issues.append(ValidationIssue("from_key", "not-merged"))
        if issues or into is None:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "vocabulary.property_unmerged",
            PropertyUnmerged(from_key=from_key, into=into, reason=reason),
            actor,
            refs=[from_key, into],
        )
        project.record([event])
        return event.id


# --- Reads ---


def _live_definitions(project: Project) -> list[PropertyDef]:
    """The live approved definitions, by key, without the keys merged into another."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT key, definition_json FROM properties WHERE state = 'approved' ORDER BY key"
            )
        ).all()
    return [
        PropertyDef.model_validate_json(str(r[1]))
        for r in rows
        if _merged_into(project, str(r[0])) is None
    ]


def vocabulary_version(project: Project) -> str:
    """`V@` of the live approved vocabulary (module docstring)."""
    project.index.sync()
    definitions = _live_definitions(project)
    if not definitions:
        return EMPTY_VERSION
    body: list[JsonValue] = [
        d.model_dump(mode="json", exclude={"description"}) for d in definitions
    ]
    return "V@" + hashlib.sha256(canonical_json(body)).hexdigest()[:8]


def resolve_property(project: Project, key: str) -> PropertyDef | None:
    """The live approved definition `key` stands for after following its merges; None when the
    key (or the one it resolves to) has no approved definition."""
    project.index.sync()
    seen: set[str] = set()
    current = key
    while current not in seen:
        seen.add(current)
        nxt = _merged_into(project, current)
        if nxt is None:
            break
        current = nxt
    row = _live_row(project, current)
    return None if row is None else PropertyDef.model_validate_json(str(row[1]))


def resolved_key(project: Project, key: str) -> str:
    """`key` after following its merges (cycle-safe); the caller syncs the index."""
    seen: set[str] = set()
    current = key
    while current not in seen:
        seen.add(current)
        nxt = _merged_into(project, current)
        if nxt is None:
            break
        current = nxt
    return current


def list_properties(
    project: Project,
    *,
    include_proposed: bool = False,
    include_rejected: bool = False,
    limit: int = PAGE,
    offset: int = 0,
) -> list[PropertyView]:
    """Definitions by key then event: the live approved ones; with `include_proposed` also the
    pending proposals; with `include_rejected` also the rejected and superseded ones."""
    states = ["approved"]
    if include_proposed:
        states.append("proposed")
    if include_rejected:
        states += ["rejected", "superseded"]
    project.index.sync()
    marks = ", ".join(f":s{i}" for i in range(len(states)))
    params: dict[str, Any] = {f"s{i}": s for i, s in enumerate(states)}
    params.update(n=limit, o=offset)
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT key, definition_json, state, event_id FROM properties "
                f"WHERE state IN ({marks}) ORDER BY key, event_id LIMIT :n OFFSET :o"
            ),
            params,
        ).all()
    return [
        PropertyView(
            key=str(r[0]),
            definition=PropertyDef.model_validate_json(str(r[1])),
            state=r[2],
            merged_into=_merged_into(project, str(r[0])),
            event_id=str(r[3]),
        )
        for r in rows
    ]
