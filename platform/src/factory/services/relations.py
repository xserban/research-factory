"""Relation proposals and human decisions (slice 3b, plan G2-C).

An agent or a human proposes a `builds-on` / `improves-on` relation from a recorded contribution
item; the platform classifies it (`lineage.classify`), never the proposer. Invariants:
- A basis item must be a live, non-stale `base-idea` or `addition` row of the source work. It is
  read through `_basis`, the one place a relation reads an item, so the read can move to the
  final (post-resolution) view in one line.
- The source is in the contribution population; the target is a known work or a live, not
  rejected idea. For an agent, a held-out work is `target-unknown`, exactly as a missing one.
- Re-proposing the same (source, target, type) with the same basis writes nothing; with another
  basis it supersedes the live relation (its decision does not carry over) unless a human rejected
  that relation, which refuses the proposal.
- Only a human decides, and never from the session that proposed (proposer != evaluator, relay
  included); no MCP tool reaches `decide_relation`. A confirmation applies to inferred relations
  only, a rejection to any live relation.
- Every refusal writes nothing.
"""

from __future__ import annotations

import re

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.lineage.classify import CLASSIFIER_VERSION, BasisFacts, LinkFacts, classify
from factory.model.base import StrictModel
from factory.model.extraction import Scope
from factory.model.lineage import (
    IDEA_ID_RE,
    LineageDecision,
    ProposalStatus,
    RelationDecided,
    RelationProposal,
    RelationProposed,
    StatusReason,
)
from factory.model.references import LinkState
from factory.services import seeds
from factory.services.context import Project
from factory.services.contributions import ItemView, contribution_item
from factory.services.extraction import scope_population
from factory.services.reference_view import reference_view, reference_view_of

_IDEA = re.compile(IDEA_ID_RE)
BASIS_KINDS = frozenset({"base-idea", "addition"})
MAX_RATIONALE = 2000


class ProposeResult(StrictModel):
    relation_id: str
    status: ProposalStatus
    status_reason: StatusReason | None
    flags: tuple[str, ...]
    written: bool


def _basis(project: Project, item_id: str) -> ItemView | None:
    """The item a relation rests on: the single read of contribution items in this module."""
    return contribution_item(project, item_id)


def _basis_issues(
    project: Project, proposal: RelationProposal
) -> tuple[ItemView | None, str | None]:
    """The basis item and, when it is unusable, the reason."""
    if proposal.basis_item is None:
        return None, None
    item = _basis(project, proposal.basis_item)
    if item is None:
        return None, "basis-unknown"
    if item.work_id != proposal.source_work:
        return item, "basis-other-work"
    if not item.live:
        return item, "basis-not-live"
    if item.stale:
        return item, "basis-stale"
    if item.item_kind not in BASIS_KINDS:
        return item, "basis-kind"
    return item, None


def _target_known(project: Project, target: str, held: set[str]) -> bool:
    if target in held:
        return False
    with project.index.connect() as conn:
        if _IDEA.fullmatch(target):
            row = conn.execute(
                text(
                    "SELECT 1 FROM ideas WHERE idea_id = :t AND superseded_by IS NULL "
                    "AND (decision IS NULL OR decision != 'reject')"
                ),
                {"t": target},
            ).first()
            return row is not None
        row = conn.execute(
            text(
                "SELECT 1 FROM works WHERE work_id = :t "
                "UNION SELECT 1 FROM reference_links WHERE work_id = :t LIMIT 1"
            ),
            {"t": target},
        ).first()
    return row is not None


def propose_relation(project: Project, actor: Actor, proposal: RelationProposal) -> ProposeResult:
    """Validate, classify and record `proposal`; see the module docstring. Raises
    `FactoryValidationError` (fields `actor`, `source_work`, `target`, `basis_item`, `note`) and
    writes nothing when invalid."""
    if actor.kind not in ("agent", "human"):
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent or a human proposes a relation")]
        )
    with project.index.exclusive():
        project.index.sync()
        held = set(seeds.held_out(project).work_ids) if actor.kind == "agent" else set[str]()
        issues: list[ValidationIssue] = []
        if proposal.source_work in held or proposal.source_work not in set(
            scope_population(project, Scope.CONTRIBUTION)
        ):
            issues.append(ValidationIssue("source_work", "not-in-population"))
        is_idea = _IDEA.fullmatch(proposal.target) is not None
        if not _target_known(project, proposal.target, held):
            issues.append(ValidationIssue("target", "target-unknown"))
        item, bad = _basis_issues(project, proposal)
        if bad is not None:
            issues.append(ValidationIssue("basis_item", bad))
        if proposal.basis_item is None:
            if is_idea:
                issues.append(ValidationIssue("basis_item", "basis-required-for-idea"))
            elif proposal.note is None or not proposal.note.strip():
                issues.append(ValidationIssue("note", "note-required-without-basis"))
        live = _live_relation(project, proposal)
        if live is not None and live[2] == "reject":
            issues.append(ValidationIssue("target", "rejected-by-human"))
        if issues:
            raise FactoryValidationError(issues)
        if live is not None and live[1] == proposal.basis_item:
            row = _view_row(project, live[0])
            return ProposeResult(
                relation_id=live[0],
                status=row[0],
                status_reason=row[1],
                flags=row[2],
                written=False,
            )
        return _write(project, actor, proposal, item, is_idea, live[0] if live else None)


def _live_relation(
    project: Project, p: RelationProposal
) -> tuple[str, str | None, str | None] | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT relation_id, basis_item, decision FROM relations WHERE source_work = :s "
                "AND target = :t AND edge_type = :e AND superseded_by IS NULL"
            ),
            {"s": p.source_work, "t": p.target, "e": p.edge_type},
        ).first()
    return None if row is None else (str(row[0]), row[1], row[2])


def _view_row(
    project: Project, relation_id: str
) -> tuple[ProposalStatus, StatusReason | None, tuple[str, ...]]:
    import json

    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT status, status_reason, flags FROM relations WHERE relation_id = :r"),
            {"r": relation_id},
        ).one()
    reason = None if row[1] is None else StatusReason(str(row[1]))
    return row[0], reason, tuple(json.loads(str(row[2])))


def _write(
    project: Project,
    actor: Actor,
    proposal: RelationProposal,
    item: ItemView | None,
    is_idea: bool,
    supersedes: str | None,
) -> ProposeResult:
    cited = None if item is None else item.cited
    link = None
    if cited is not None:
        view = reference_view_of(project, cited.reference_extraction_id)
        entry = None if view is None else view.entry(cited.ordinal)
        if entry is not None:
            link = LinkFacts(entry.link_state, entry.link_work)
    basis = (
        None
        if item is None
        else BasisFacts(
            item.item_kind,
            None if cited is None else cited.ordinal,
            None if cited is None else cited.reference_extraction_id,
        )
    )
    source_view = reference_view(project, proposal.source_work)
    target_cited = source_view is not None and any(
        e.link_state is LinkState.RESOLVED and e.link_work == proposal.target
        for e in source_view.entries
    )
    result = classify(
        basis, link, proposal.target, target_is_idea=is_idea, target_cited=target_cited
    )
    relation_id = f"rel_{project.ids.ulid()}"
    stated = result.status == "stated"
    payload = RelationProposed(
        relation_id=relation_id,
        source_work=proposal.source_work,
        target=proposal.target,
        edge_type=proposal.edge_type,
        basis_item=proposal.basis_item,
        note=proposal.note,
        status=result.status,
        status_reason=result.reason,
        resolved_target=result.resolved_target,
        reference_extraction_id=None
        if cited is None or not stated
        else cited.reference_extraction_id,
        cited_entry=None if cited is None or not stated else cited.ordinal,
        flags=result.flags,
        classifier=CLASSIFIER_VERSION,
        supersedes=supersedes,
    )
    input_blob = (
        project.blobs.put_json(proposal.model_dump(mode="json")) if actor.kind == "agent" else None
    )
    refs = [relation_id, proposal.source_work]
    if proposal.basis_item is not None:
        refs.append(proposal.basis_item)
    project.record(
        [project.events.make("relation.proposed", payload, actor, refs=refs, input_blob=input_blob)]
    )
    return ProposeResult(
        relation_id=relation_id,
        status=result.status,
        status_reason=result.reason,
        flags=result.flags,
        written=True,
    )


def decide_relation(
    project: Project,
    actor: Actor,
    relation_id: str,
    decision: LineageDecision,
    rationale: str,
) -> str:
    """Record a human decision on a live relation and return its event id. Refused (nothing
    written) for a non-human actor or the proposing session (`actor`), an unknown or superseded
    relation (`relation_id`), a blank or long rationale (`rationale`) and a confirmation of a
    stated relation (`decision`). A decision supersedes the previous one."""
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "only a human decides a relation")])
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT r.status, r.superseded_by, e.session FROM relations r "
                    "JOIN events e ON e.id = r.event_id WHERE r.relation_id = :r"
                ),
                {"r": relation_id},
            ).first()
        if row is None:
            raise FactoryValidationError([ValidationIssue("relation_id", "unknown-relation")])
        if row[1] is not None:
            issues.append(ValidationIssue("relation_id", "superseded-relation"))
        if str(row[2]) == actor.session:
            issues.append(
                ValidationIssue("actor", "the session that proposed a relation cannot decide it")
            )
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state the reason for the decision"))
        elif len(rationale) > MAX_RATIONALE:
            issues.append(ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters"))
        if decision is LineageDecision.CONFIRM and row[0] != "inferred":
            issues.append(ValidationIssue("decision", "only an inferred relation is confirmed"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "relation.decided",
            RelationDecided(relation_id=relation_id, decision=decision, rationale=rationale),
            actor,
            refs=[relation_id],
        )
        project.record([event])
        return event.id
