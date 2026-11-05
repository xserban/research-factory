"""Relation proposals and human decisions (slice 3b, plan G2-C).

An agent or a human proposes a `builds-on` / `improves-on` relation from a recorded contribution
item; the platform classifies it (`lineage.classify`), never the proposer. Invariants:
- A basis item must be a live, non-stale `base-idea` or `addition` row of the source work. It is
  read through `_basis`, the one place a relation reads an item, so the read can move to the
  final (post-resolution) view in one line.
- The source is in the contribution population; the target is a known work or a live, not
  rejected idea. A held-out seed's work is an ordinary known work (decided item 37.9).
- Re-proposing the same (source, target, type) with the same basis writes nothing; with another
  basis it supersedes the live relation (its decision does not carry over) unless a human rejected
  that relation, which refuses the proposal.
- Only a human decides, and never from the session that proposed (proposer != evaluator, relay
  included); no MCP tool reaches `decide_relation`. A confirmation applies to inferred relations
  only, a rejection to any live relation.
- Every refusal writes nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.lineage.classify import CLASSIFIER_VERSION, BasisFacts, LinkFacts, classify
from factory.model.base import StrictModel
from factory.model.extraction import Scope
from factory.model.lineage import (
    DEFAULT_STATUSES,
    IDEA_ID_RE,
    EdgeStatus,
    LineageDecision,
    ProposalStatus,
    RelationDecided,
    RelationProposal,
    RelationProposed,
    RelationType,
    StatusReason,
)
from factory.model.references import LinkState
from factory.services.call_memo import memoised
from factory.services.context import Project
from factory.services.contributions import ItemView, contribution_item, final_item, final_items
from factory.services.extraction import scope_population, stale_extractions
from factory.services.notices import work_states
from factory.services.reference_view import reference_view, reference_view_of
from factory.services.view_corpus import CORPUS_PARAMS, CORPUS_SQL

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
    """The item a relation rests on: its final view (what the item finally says, field by field,
    after agreement or a human resolution). None while the item is unresolved, superseded or
    unknown. The single read of contribution items in this module."""
    return final_item(project, item_id)


def _basis_issues(
    project: Project, proposal: RelationProposal
) -> tuple[ItemView | None, str | None]:
    """The basis item (final view) and, when it is unusable, the reason."""
    if proposal.basis_item is None:
        return None, None
    raw = contribution_item(project, proposal.basis_item)
    if raw is None:
        return None, "basis-unknown"
    if raw.work_id != proposal.source_work:
        return None, "basis-other-work"
    if not raw.live:
        return None, "basis-not-live"
    item = _basis(project, proposal.basis_item)
    if item is None:
        return None, "basis-unresolved"
    if item.stale:
        return item, "basis-stale"
    if item.item_kind not in BASIS_KINDS:
        return item, "basis-kind"
    return item, None


def known_work(project: Project, work_id: str) -> bool:
    """Whether `work_id` is a corpus work or the target of a G1 link."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM works WHERE work_id = :t "
                "UNION SELECT 1 FROM reference_links WHERE work_id = :t LIMIT 1"
            ),
            {"t": work_id},
        ).first()
    return row is not None


def _target_known(project: Project, target: str) -> bool:
    if _IDEA.fullmatch(target):
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM ideas WHERE idea_id = :t AND superseded_by IS NULL "
                    "AND (decision IS NULL OR decision != 'reject')"
                ),
                {"t": target},
            ).first()
        return row is not None
    return known_work(project, target)


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
        issues: list[ValidationIssue] = []
        if proposal.source_work not in set(scope_population(project, Scope.CONTRIBUTION)):
            issues.append(ValidationIssue("source_work", "not-in-population"))
        is_idea = _IDEA.fullmatch(proposal.target) is not None
        if not _target_known(project, proposal.target):
            issues.append(ValidationIssue("target", "target-unknown"))
        item, bad = _basis_issues(project, proposal)
        if bad is not None:
            issues.append(ValidationIssue("basis_item", bad))
        if proposal.basis_item is None:
            if is_idea:
                issues.append(ValidationIssue("basis_item", "basis-required-for-idea"))
            elif proposal.note is None or not proposal.note.strip():
                issues.append(ValidationIssue("note", "note-required-without-basis"))
        if item is not None:  # the relation is keyed by the item's canonical row
            proposal = proposal.model_copy(update={"basis_item": item.extraction_id})
        live = _live_relation(project, proposal)
        if live is not None and live[2] == "reject":
            issues.append(ValidationIssue("target", "rejected-by-human"))
        if issues:
            raise FactoryValidationError(issues)
        if live is not None and live[1] == proposal.basis_item and not _is_stale(project, live[0]):
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
        reference_extraction_id=None if cited is None else cited.reference_extraction_id,
        cited_entry=None if cited is None else cited.ordinal,
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
    with project.writing():
        project.record(
            [
                project.events.make(
                    "relation.proposed", payload, actor, refs=refs, input_blob=input_blob
                )
            ]
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
                    "SELECT r.status, r.superseded_by, e.session, r.basis_item FROM relations r "
                    "JOIN events e ON e.id = r.event_id WHERE r.relation_id = :r"
                ),
                {"r": relation_id},
            ).first()
        if row is None:
            raise FactoryValidationError([ValidationIssue("relation_id", "unknown-relation")])
        if row[1] is not None:
            issues.append(ValidationIssue("relation_id", "superseded-relation"))
        # An unresolved item confirms nothing.
        if (
            decision is LineageDecision.CONFIRM
            and row[3] is not None
            and _basis(project, str(row[3])) is None
        ):
            issues.append(ValidationIssue("basis_item", "basis-unresolved"))
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


# --- Views: effective status and staleness, computed on read ---


class RelationView(StrictModel):
    """A relation as the log and the current state of its basis give it. `effective` is the
    status a view shows (ruling 6); `stale_reasons` is non-empty exactly when a stale reason
    holds, whatever the latest decision."""

    relation_id: str
    source_work: str
    target: str
    edge_type: RelationType
    basis_item: str | None
    proposal_status: ProposalStatus
    status_reason: StatusReason | None
    decision: LineageDecision | None
    effective: EdgeStatus
    stale_reasons: tuple[str, ...]
    flags: tuple[str, ...]
    reference_extraction_id: str | None
    cited_entry: int | None
    has_note: bool
    event_id: str


_EFFECTIVE_SQL = """
WITH eff AS (
  SELECT r.relation_id, r.source_work, r.target, r.edge_type, r.basis_item, r.status,
         r.status_reason, r.decision, r.flags, r.reference_extraction_id, r.cited_entry,
         r.note, r.event_id, r.superseded_by,
         COALESCE(b.superseded_by IS NOT NULL, 0) AS f_superseded,
         COALESCE(r.basis_item IN (SELECT value FROM json_each(:stale)), 0) AS f_stale,
         COALESCE(r.basis_item IN (SELECT value FROM json_each(:unresolved)), 0) AS f_unresolved,
         COALESCE(r.basis_item IS NOT NULL AND
                  r.source_work IN (SELECT value FROM json_each(:retracted)), 0) AS f_retracted,
         COALESCE(r.basis_item IN (SELECT key FROM json_each(:cited)) AND
                  (SELECT value FROM json_each(:cited) c WHERE c.key = r.basis_item)
                  != COALESCE(r.reference_extraction_id || ':' || r.cited_entry, ''), 0)
           AS f_changed,
         COALESCE(r.reference_extraction_id IS NOT NULL AND x.live = 0, 0) AS f_references,
         COALESCE(r.status = 'stated' AND
                  (l.state IS NULL OR l.state != 'resolved' OR l.work_id IS NOT r.target), 0)
           AS f_link
  FROM relations r
  LEFT JOIN extraction_rows b ON b.extraction_id = r.basis_item
  LEFT JOIN reference_extractions x ON x.extraction_id = r.reference_extraction_id
  LEFT JOIN reference_links l
    ON l.extraction_id = r.reference_extraction_id AND l.ordinal = r.cited_entry
), shown AS (
  SELECT *, CASE
    WHEN decision = 'reject' THEN 'rejected'
    WHEN f_superseded OR f_stale OR f_unresolved OR f_retracted OR f_changed OR f_references
      OR f_link THEN 'stale'
    WHEN decision = 'confirm' THEN 'confirmed'
    ELSE status END AS effective
  FROM eff
)
"""
_COLUMNS = (
    "relation_id, source_work, target, edge_type, basis_item, status, status_reason, decision, "
    "flags, reference_extraction_id, cited_entry, note, event_id, effective, "
    "f_superseded, f_stale, f_unresolved, f_retracted, f_changed, f_references, f_link"
)


@memoised
def _basis_params(project: Project) -> dict[str, str]:
    """The state of the items relations rest on, read once per call from the final view: `stale`
    (a field source of the final item is stale), `retracted` (works whose notice state excludes
    them from the synthesis: their items are no basis), `unresolved` (no final item: superseded,
    reopened or disputed) and `cited` (basis -> `extraction:ordinal` its final item now cites,
    empty for none). Only the bases some relation names are looked at."""
    project.index.sync()
    with project.index.connect() as conn:
        bases = [
            str(r[0])
            for r in conn.execute(
                text("SELECT DISTINCT basis_item FROM relations WHERE basis_item IS NOT NULL")
            )
        ]
    wanted = set(bases)
    finals: dict[str, ItemView] = {}
    if wanted:
        for item in final_items(project):
            for source in item.sources.values():
                if source.extraction_id in wanted:
                    finals[source.extraction_id] = item
    raw = stale_extractions(project, scope=Scope.CONTRIBUTION) & wanted
    stale = sorted(raw | {b for b in bases if b in finals and finals[b].stale})
    unresolved = sorted(b for b in bases if b not in finals)
    cited = {
        b: "" if (c := finals[b].cited) is None else f"{c.reference_extraction_id}:{c.ordinal}"
        for b in bases
        if b in finals
    }
    retracted = sorted(w for w, st in work_states(project).items() if st.synthesis == "excluded")
    return {
        "stale": json.dumps(stale),
        "retracted": json.dumps(retracted),
        "unresolved": json.dumps(unresolved),
        "cited": json.dumps(cited),
    }


def _view_of(row: Mapping[str, Any]) -> RelationView:
    reasons = tuple(
        name
        for flag, name in (
            ("f_superseded", "basis-superseded"),
            ("f_stale", "basis-stale"),
            ("f_unresolved", "basis-unresolved"),
            ("f_retracted", "basis-retracted"),
            ("f_changed", "basis-changed"),
            ("f_references", "references-superseded"),
            ("f_link", "link-changed"),
        )
        if row[flag]
    )
    return RelationView(
        relation_id=row["relation_id"],
        source_work=row["source_work"],
        target=row["target"],
        edge_type=row["edge_type"],
        basis_item=row["basis_item"],
        proposal_status=row["status"],
        status_reason=None if row["status_reason"] is None else StatusReason(row["status_reason"]),
        decision=None if row["decision"] is None else LineageDecision(row["decision"]),
        effective=EdgeStatus(row["effective"]),
        stale_reasons=reasons,
        flags=tuple(json.loads(row["flags"])),
        reference_extraction_id=row["reference_extraction_id"],
        cited_entry=row["cited_entry"],
        has_note=row["note"] is not None,
        event_id=row["event_id"],
    )


def _query(
    project: Project,
    where: str,
    params: Mapping[str, Any],
    tail: str = "",
    tail_params: Mapping[str, Any] | None = None,
) -> list[Any]:
    project.index.sync()
    bound = {**_basis_params(project), **params, **(tail_params or {})}
    with project.index.connect() as conn:
        return list(
            conn.execute(
                text(f"{_EFFECTIVE_SQL} SELECT {_COLUMNS} FROM shown WHERE {where} {tail}"), bound
            )
            .mappings()
            .all()
        )


def relation_view(project: Project, relation_id: str) -> RelationView | None:
    """One relation, live or superseded; None for an unknown id."""
    rows = _query(project, "relation_id = :r", {"r": relation_id})
    return _view_of(rows[0]) if rows else None


def relation_views(project: Project, relation_ids: Collection[str]) -> dict[str, RelationView]:
    """The views of the named relations (unknown ids omitted); the stale set is read once."""
    if not relation_ids:
        return {}
    rows = _query(
        project,
        "relation_id IN (SELECT value FROM json_each(:ids))",
        {"ids": json.dumps(sorted(set(relation_ids)))},
    )
    return {v.relation_id: v for v in map(_view_of, rows)}


def _is_stale(project: Project, relation_id: str) -> bool:
    view = relation_view(project, relation_id)
    return view is not None and bool(view.stale_reasons)


def list_relations(
    project: Project,
    *,
    statuses: Collection[EdgeStatus] = DEFAULT_STATUSES,
    work_id: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[RelationView]:
    """Live (not superseded) relations whose effective status is in `statuses`, sorted by
    (source, type, target, id), one page of at most `limit` from `offset`; the filter, order and
    page are applied in SQL. `work_id` matches the source or the target."""
    rows = _query(
        project,
        "superseded_by IS NULL AND effective IN (SELECT value FROM json_each(:st)) "
        "AND (:w IS NULL OR source_work = :w OR target = :w)",
        {"st": json.dumps(sorted(s.value for s in statuses)), "w": work_id},
        "ORDER BY source_work, edge_type, target, relation_id LIMIT :limit OFFSET :offset",
        {"limit": limit, "offset": offset},
    )
    return [_view_of(r) for r in rows]


def relation_years(
    project: Project, statuses: Collection[EdgeStatus] = DEFAULT_STATUSES
) -> dict[str | None, int]:
    """Live relations whose effective status is in `statuses` and whose source is a corpus work,
    counted by the publication year of the source work (None: undated), in SQL. A source absorbed
    by an active dedup merge is read as its primary."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                f"{_EFFECTIVE_SQL}, src AS (SELECT s.relation_id, "
                "COALESCE(ab.p, s.source_work) AS w "
                'FROM shown s LEFT JOIN (SELECT mm.work_id AS a, m."primary" AS p '
                "FROM merge_members mm JOIN merges m ON m.merge_id = mm.merge_id "
                "WHERE m.status = 'active' AND mm.work_id != m.\"primary\") ab "
                "ON ab.a = s.source_work "
                "WHERE s.superseded_by IS NULL AND s.effective IN "
                "(SELECT value FROM json_each(:st))) "
                "SELECT substr(json_extract(w.data, '$.dates.published'), 1, 4), COUNT(*) "
                "FROM src LEFT JOIN works w ON w.work_id = src.w "
                f"WHERE src.w IN {CORPUS_SQL} GROUP BY 1"
            ),
            {
                **_basis_params(project),
                "st": json.dumps(sorted(s.value for s in statuses)),
                **CORPUS_PARAMS,
            },
        ).all()
    return {(str(y) if y is not None and str(y).isdigit() else None): int(n) for y, n in rows}


def relation_counts(project: Project) -> dict[str, dict[str, int]]:
    """Live relations by edge type and effective status; every status is present."""
    counts = {t: {s.value: 0 for s in EdgeStatus} for t in ("builds-on", "improves-on")}
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                f"{_EFFECTIVE_SQL} SELECT edge_type, effective, COUNT(*) FROM shown "
                "WHERE superseded_by IS NULL GROUP BY edge_type, effective"
            ),
            _basis_params(project),
        ).all()
    for edge_type, effective, n in rows:
        counts[str(edge_type)][str(effective)] = int(n)
    return counts


def relation_notes(project: Project, relation_ids: Collection[str]) -> dict[str, str]:
    """The free `note` an agent gave each named relation (those without one are omitted). It is
    agent text, not evidence: callers label it `agent-note` and never count or export it."""
    if not relation_ids:
        return {}
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relation_id, note FROM relations WHERE note IS NOT NULL "
                "AND relation_id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": json.dumps(sorted(set(relation_ids)))},
        ).all()
    return {str(r[0]): str(r[1]) for r in rows}
