"""Ideas: named groupings of works, confirmed by a human, merged reversibly (slice 3b, plan G2-C).

Invariants:
- An idea's name occurs in the verified quote of its `name` field in a live, final, non-stale
  contribution item of the origin work (`name_item`); an agent or a human proposes it, only a human
  decides it, and never from the session that proposed it (proposer != evaluator).
- Members are known works , unique, and include the origin.
- A superseding proposal replaces the grouping; its decision does not carry over.
- `idea.merged` / `idea.unmerged` are human, reversible and acyclic: a merged idea is hidden and
  its members join the idea it was merged into (transitively); unmerging restores both exactly.
  Merges are read on demand from the indexed `merged_into` links, never loaded wholesale.
- Every refusal writes nothing.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.extraction.numbers import normalise_text
from factory.model.base import StrictModel
from factory.model.extraction import Scope
from factory.model.lineage import (
    DEFAULT_STATUSES,
    MAX_IDEA_NAME,
    IdeaDecided,
    IdeaMerged,
    IdeaProposed,
    IdeaUnmerged,
    LineageDecision,
)
from factory.services.context import Project
from factory.services.contributions import contribution_item, final_item
from factory.services.extraction import stale_extractions
from factory.services.relations import MAX_RATIONALE, known_work, list_relations

IdeaState = Literal["proposed", "confirmed", "rejected", "merged", "superseded"]
PAGE = 500


class IdeaView(StrictModel):
    idea_id: str
    name: str
    origin: str
    name_item: str
    members: tuple[str, ...]
    effective_members: tuple[str, ...]
    state: IdeaState
    merged_into: str | None
    event_id: str


class IdeaCandidate(StrictModel):
    work_id: str
    reasons: tuple[Literal["name-in-item", "builds-on-origin"], ...]


def _only_human(actor: Actor) -> None:
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "only a human decides an idea")])


def propose_idea(
    project: Project,
    actor: Actor,
    name: str,
    origin: str,
    name_item: str,
    members: list[str] | tuple[str, ...],
    *,
    supersedes: str | None = None,
) -> str:
    """Record an idea proposal (agent, or human via `idea_define`) and return its id. Refused,
    with nothing written (fields `actor`, `name`, `name_item`, `origin`, `members`,
    `supersedes`): see the module docstring."""
    if actor.kind not in ("agent", "human"):
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent or a human proposes an idea")]
        )
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if not name.strip() or len(name) > MAX_IDEA_NAME:
            issues.append(ValidationIssue("name", f"1 to {MAX_IDEA_NAME} non-blank characters"))
        else:
            issues += _name_issues(project, name, origin, name_item)
        if not known_work(project, origin):
            issues.append(ValidationIssue("origin", "unknown-work"))
        issues += _member_issues(project, origin, members)
        if supersedes is not None and _idea_row(project, supersedes, live=True) is None:
            issues.append(ValidationIssue("supersedes", "idea-not-live"))
        elif supersedes is not None and _has_merged_members(project, supersedes):
            # Superseding a merge target would hide the ideas merged into it from every view.
            issues.append(ValidationIssue("supersedes", "merge-target"))
        if issues:
            raise FactoryValidationError(issues)
        idea_id = f"ida_{project.ids.ulid()}"
        payload = IdeaProposed(
            idea_id=idea_id,
            name=name,
            name_item=name_item,
            origin=origin,
            members=tuple(sorted(members)),
            supersedes=supersedes,
        )
        input_blob = (
            project.blobs.put_json(
                {
                    "name": name,
                    "origin": origin,
                    "name_item": name_item,
                    "members": list(members),
                    "supersedes": supersedes,
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "idea.proposed",
                    payload,
                    actor,
                    refs=[idea_id, origin, name_item],
                    input_blob=input_blob,
                )
            ]
        )
        return idea_id


def _name_issues(project: Project, name: str, origin: str, name_item: str) -> list[ValidationIssue]:
    raw = contribution_item(project, name_item)
    if raw is None:
        return [ValidationIssue("name_item", "name-item-unknown")]
    if raw.work_id != origin:
        return [ValidationIssue("name_item", "name-item-other-work")]
    if not raw.live:
        return [ValidationIssue("name_item", "name-item-not-live")]
    item = final_item(project, name_item)
    if item is None:
        return [ValidationIssue("name_item", "name-item-unresolved")]
    if item.stale:
        return [ValidationIssue("name_item", "name-item-stale")]
    source = item.sources.get("name")
    if source is None or source.quote is None:
        return [ValidationIssue("name_item", "name-item-has-no-name")]
    if normalise_text(name) not in normalise_text(source.quote):
        return [ValidationIssue("name", "name-not-in-quote")]
    return []


def _member_issues(
    project: Project, origin: str, members: list[str] | tuple[str, ...]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(set(members)) != len(members):
        issues.append(ValidationIssue("members", "duplicate-member"))
    if origin not in members:
        issues.append(ValidationIssue("members", "must-include-origin"))
    if not members:
        return issues or [ValidationIssue("members", "must-include-origin")]
    if any(not known_work(project, m) for m in set(members)):
        issues.append(ValidationIssue("members", "unknown-work"))
    return issues


def _has_merged_members(project: Project, idea_id: str) -> bool:
    """Whether some idea is merged into `idea_id` (an indexed read)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM ideas WHERE merged_into = :i LIMIT 1"), {"i": idea_id}
        ).first()
    return row is not None


def _idea_row(project: Project, idea_id: str, *, live: bool = False) -> Any | None:
    """The idea's row; with `live`, only when not superseded and not rejected."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT i.idea_id, i.superseded_by, i.decision, i.merged_into, i.name_item, "
                "e.session FROM ideas i JOIN events e ON e.id = i.event_id WHERE i.idea_id = :i"
            ),
            {"i": idea_id},
        ).first()
    if row is None:
        return None
    if live and (row[1] is not None or row[2] == "reject"):
        return None
    return row


def decide_idea(
    project: Project,
    actor: Actor,
    idea_id: str,
    decision: LineageDecision,
    rationale: str,
) -> str:
    """Record a human decision on a live idea and return its event id. Refused (nothing written)
    for a non-human actor or the proposing session (`actor`), an unknown or superseded idea
    (`idea_id`), a rejection of an idea other ideas are merged into (`idea_id`: `merge-target`;
    unmerge first), a blank or long rationale (`rationale`) and a confirmation whose name item is no
    longer final (`name_item`)."""
    _only_human(actor)
    with project.index.exclusive():
        project.index.sync()
        row = _idea_row(project, idea_id)
        if row is None:
            raise FactoryValidationError([ValidationIssue("idea_id", "unknown-idea")])
        issues: list[ValidationIssue] = []
        if row[1] is not None:
            issues.append(ValidationIssue("idea_id", "superseded-idea"))
        if str(row[5]) == actor.session:
            issues.append(
                ValidationIssue("actor", "the session that proposed an idea cannot decide it")
            )
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state the reason for the decision"))
        elif len(rationale) > MAX_RATIONALE:
            issues.append(ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters"))
        if decision is LineageDecision.REJECT and _has_merged_members(project, idea_id):
            issues.append(ValidationIssue("idea_id", "merge-target"))
        if decision is LineageDecision.CONFIRM and final_item(project, str(row[4])) is None:
            issues.append(ValidationIssue("name_item", "name-item-unresolved"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "idea.decided",
            IdeaDecided(idea_id=idea_id, decision=decision, rationale=rationale),
            actor,
            refs=[idea_id],
        )
        project.record([event])
        return event.id


def _chain_reaches(project: Project, start: str, goal: str) -> bool:
    """Whether following `merged_into` from `start` reaches `goal` (cycle-safe)."""
    seen: set[str] = set()
    current: str | None = start
    with project.index.connect() as conn:
        while current is not None and current not in seen:
            if current == goal:
                return True
            seen.add(current)
            row = conn.execute(
                text("SELECT merged_into FROM ideas WHERE idea_id = :i"), {"i": current}
            ).first()
            current = None if row is None or row[0] is None else str(row[0])
    return False


def build_idea_merge(
    project: Project,
    actor: Actor,
    from_idea: str,
    into: str,
    reason: str,
    proposal: str | None = None,
) -> Event:
    """The `idea.merged` event for a valid merge, not recorded. The caller holds the index lock
    and has synced. Both ideas must be live and not rejected (`from_idea`, `into`: `unknown-idea`,
    `idea-not-live`); `from_idea` must not be merged already (`already-merged`); a merge that
    closes a cycle is `merge-cycle` (`into`); the reason must be stated (`reason`)."""
    _only_human(actor)
    issues: list[ValidationIssue] = []
    for field, ident in (("from_idea", from_idea), ("into", into)):
        row = _idea_row(project, ident)
        if row is None:
            issues.append(ValidationIssue(field, "unknown-idea"))
        elif row[1] is not None or row[2] == "reject":
            issues.append(ValidationIssue(field, "idea-not-live"))
        elif field == "from_idea" and row[3] is not None:
            issues.append(ValidationIssue(field, "already-merged"))
    if not reason.strip():
        issues.append(ValidationIssue("reason", "state the reason"))
    if not issues and (from_idea == into or _chain_reaches(project, into, from_idea)):
        issues.append(ValidationIssue("into", "merge-cycle"))
    if issues:
        raise FactoryValidationError(issues)
    return project.events.make(
        "idea.merged",
        IdeaMerged(from_idea=from_idea, into=into, reason=reason, proposal=proposal),
        actor,
        refs=[from_idea, into],
    )


def merge_ideas(project: Project, actor: Actor, from_idea: str, into: str, reason: str) -> str:
    """Merge `from_idea` into `into` (human, reversible) and return the event id; refusals as
    `build_idea_merge`."""
    _only_human(actor)
    with project.index.exclusive():
        project.index.sync()
        event = build_idea_merge(project, actor, from_idea, into, reason)
        project.record([event])
        return event.id


def unmerge_idea(project: Project, actor: Actor, from_idea: str, reason: str) -> str:
    """Revert the latest merge of `from_idea` (human) and return the event id. Refused for an
    idea that is unknown (`unknown-idea`) or not merged (`not-merged`), or a blank reason."""
    _only_human(actor)
    with project.index.exclusive():
        project.index.sync()
        row = _idea_row(project, from_idea)
        if row is None:
            raise FactoryValidationError([ValidationIssue("from_idea", "unknown-idea")])
        if row[3] is None:
            raise FactoryValidationError([ValidationIssue("from_idea", "not-merged")])
        if not reason.strip():
            raise FactoryValidationError([ValidationIssue("reason", "state the reason")])
        event = project.events.make(
            "idea.unmerged",
            IdeaUnmerged(from_idea=from_idea, into=str(row[3]), reason=reason),
            actor,
            refs=[from_idea, str(row[3])],
        )
        project.record([event])
        return event.id


# --- Reads ---

_VIEW_SQL = (
    "SELECT idea_id, name, name_item, origin, superseded_by, decision, merged_into, event_id "
    "FROM ideas "
)
_EFFECTIVE_MEMBERS = """
WITH RECURSIVE tree(idea_id) AS (
  SELECT :i
  UNION
  SELECT c.idea_id FROM ideas c JOIN tree t ON c.merged_into = t.idea_id
    WHERE c.superseded_by IS NULL
)
SELECT DISTINCT m.work_id FROM idea_members m JOIN tree ON m.idea_id = tree.idea_id
ORDER BY m.work_id
"""


def _state(row: Any) -> IdeaState:
    if row["superseded_by"] is not None:
        return "superseded"
    if row["decision"] == "reject":
        return "rejected"
    if row["merged_into"] is not None:
        return "merged"
    return "confirmed" if row["decision"] == "confirm" else "proposed"


def _views(project: Project, rows: list[Any]) -> list[IdeaView]:
    out: list[IdeaView] = []
    with project.index.connect() as conn:
        for row in rows:
            ident = str(row["idea_id"])
            own = conn.execute(
                text("SELECT work_id FROM idea_members WHERE idea_id = :i ORDER BY work_id"),
                {"i": ident},
            ).all()
            effective = conn.execute(text(_EFFECTIVE_MEMBERS), {"i": ident}).all()
            out.append(
                IdeaView(
                    idea_id=ident,
                    name=row["name"],
                    origin=row["origin"],
                    name_item=row["name_item"],
                    members=tuple(str(r[0]) for r in own),
                    effective_members=tuple(str(r[0]) for r in effective),
                    state=_state(row),
                    merged_into=row["merged_into"],
                    event_id=row["event_id"],
                )
            )
    return out


def idea_view(project: Project, idea_id: str) -> IdeaView | None:
    """One idea in any state; None for an unknown id."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text(_VIEW_SQL + "WHERE idea_id = :i"), {"i": idea_id}).mappings().all()
    return _views(project, list(rows))[0] if rows else None


def list_ideas(
    project: Project,
    *,
    include_unconfirmed: bool = False,
    limit: int = PAGE,
    offset: int = 0,
) -> list[IdeaView]:
    """Ideas by id, one page from `offset`: confirmed, not merged, not superseded; with
    `include_unconfirmed` also those still only proposed. A rejected idea is never listed."""
    where = "superseded_by IS NULL AND merged_into IS NULL AND "
    where += (
        "(decision IS NULL OR decision = 'confirm')"
        if include_unconfirmed
        else ("decision = 'confirm'")
    )
    project.index.sync()
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(_VIEW_SQL + f"WHERE {where} ORDER BY idea_id LIMIT :n OFFSET :o"),
                {"n": limit, "o": offset},
            )
            .mappings()
            .all()
        )
    return _views(project, list(rows))


def resolve_idea(project: Project, idea_id: str) -> str:
    """The idea `idea_id` stands for after following its merges; itself when not merged."""
    project.index.sync()
    seen: set[str] = set()
    current = idea_id
    with project.index.connect() as conn:
        while current not in seen:
            seen.add(current)
            row = conn.execute(
                text("SELECT merged_into FROM ideas WHERE idea_id = :i"), {"i": current}
            ).first()
            if row is None or row[0] is None:
                break
            current = str(row[0])
    return current


def idea_candidates(project: Project, origin: str, name: str) -> list[IdeaCandidate]:
    """Works that may belong to the idea `name` of `origin`, by work id; listing only (ruling 9).
    `name-in-item`: a live, non-stale item whose `name` equals the idea name once normalised;
    `builds-on-origin`: a stated or confirmed `builds-on` relation to the origin."""
    wanted = normalise_text(name)
    reasons: dict[str, set[str]] = {}
    stale = stale_extractions(project, scope=Scope.CONTRIBUTION)
    token = wanted.split()[0] if wanted.split() else ""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.extraction_id, r.work_id, f.value FROM extraction_fields f "
                "JOIN extraction_rows r ON r.extraction_id = f.extraction_id "
                "WHERE f.field = 'name' AND r.pack = 'contribution' AND r.superseded_by IS NULL "
                "AND LOWER(f.value) LIKE :pat ESCAPE '\\'"
            ),
            {"pat": "%" + _like(token) + "%"},
        ).all()
    for ident, work, value in rows:
        if ident not in stale and normalise_text(str(value)) == wanted:
            reasons.setdefault(str(work), set()).add("name-in-item")
    offset = 0
    while True:
        page = list_relations(
            project, statuses=DEFAULT_STATUSES, work_id=origin, limit=PAGE, offset=offset
        )
        for rel in page:
            if rel.edge_type == "builds-on" and rel.target == origin:
                reasons.setdefault(rel.source_work, set()).add("builds-on-origin")
        if len(page) < PAGE:
            break
        offset += PAGE
    return [IdeaCandidate(work_id=w, reasons=tuple(sorted(r))) for w, r in sorted(reasons.items())]


def _like(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
