"""Regions and foci: definitions, pinned snapshots, drift, review and member decisions
(slice 3d, plan Regions-A).

A region selects works, ideas and concepts by typed rules; it asserts nothing about any paper. A
snapshot pins the evaluated member set as a version `R@`; the platform computes the set, the
counts and the hash, and no actor types a number.

Invariants:
- Only the projector writes the index. Live membership is computed on read from the latest
  definition and the human member decisions in effect; drift (members added and removed since the
  latest snapshot) is reported, never applied.
- `R@` hashes kind, facet, canonical rules, the decisions in effect and the member set; never the
  name, the definition prose or the author, so editing the prose leaves the version unchanged.
- A snapshot whose version equals the region's latest writes nothing and returns that version.
- Review and member decisions are human only (R-51) and pass the module gates `regions.review`
  and `regions.member_decide`; the session that wrote an agent definition never reviews it, and
  the human author of a definition does not review it once another human has acted (a single
  human records `self_reviewed`).
- A member proposal carries a basis verified when it is made (a verbatim quote of the candidate in
  an anchored element of its conversion, or a live edge incident to the candidate and to a current
  member); it never enters a snapshot until a human adds the member. A rejection closes a proposal
  and is never a decision in effect.
- A link joins two pinned versions and is a human act (gate `regions.link`). `subregion-of` is
  verified when it is written and re-read against the latest version of each region by
  `subregion_violations`; `related` is not verified. Overlap and diff are computed from the
  version blobs and never stored.
- Basis positions in a snapshot refer to the canonical (sorted, de-duplicated) include list.
- Every refusal reports all its issues together and writes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.lineage import EdgeType
from factory.model.regions import (
    PROPOSAL_NOTE_MAX_CHARS,
    REGION_DEFINITION_MAX_CHARS,
    REGION_NAME_MAX_CHARS,
    Facet,
    MemberBasis,
    QuoteBasis,
    RegionDefined,
    RegionKind,
    RegionLinked,
    RegionMemberDecided,
    RegionMemberProposed,
    RegionReviewed,
    RegionSnapshotTaken,
)
from factory.regions.concept_use import concept_exists, concept_live, use_link
from factory.regions.evaluate import Evaluation, Member, evaluate, read_members_blob
from factory.regions.rules import (
    CitesRule,
    ImportRule,
    MemberType,
    RegionRule,
    RuleSet,
    RunRule,
)
from factory.regions.version import (
    canonical_rules,
    compress,
    members_hash,
    members_text,
    region_version,
    rules_hash,
)
from factory.services.context import Project
from factory.services.conversions import conversion_manifest, conversion_work
from factory.services.gates import gate_issues
from factory.services.lineage import index_neighbours
from factory.services.question import current_question, get_question

ReviewState = Literal["unreviewed", "reviewed", "wrong", "superseded"]


def _refuse(*issues: ValidationIssue) -> FactoryValidationError:
    return FactoryValidationError(list(issues))


# --- Reads of single rows ---


def _definition(project: Project, region_id: str) -> Any | None:
    """The latest definition of the region joined with its fixed kind and facet."""
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT d.event_id, d.name, d.definition, d.rules, d.author, d.author_user, "
                    "d.writer_session, r.kind, r.facet_question, r.facet_slot "
                    "FROM region_definitions d JOIN regions r ON r.region_id = d.region_id "
                    "WHERE d.region_id = :r ORDER BY d.event_id DESC LIMIT 1"
                ),
                {"r": region_id},
            )
            .mappings()
            .first()
        )


def _latest_snapshot(project: Project, region_id: str) -> Any | None:
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT event_id, version, definition_event, members_blob, counts "
                    "FROM region_snapshots WHERE region_id = :r ORDER BY event_id DESC LIMIT 1"
                ),
                {"r": region_id},
            )
            .mappings()
            .first()
        )


def _snapshot_of(project: Project, version: str) -> Any | None:
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT event_id, region_id, version, definition_event, members_blob "
                    "FROM region_snapshots WHERE version = :v ORDER BY event_id DESC LIMIT 1"
                ),
                {"v": version},
            )
            .mappings()
            .first()
        )


def _human_users(project: Project) -> int:
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(DISTINCT user) FROM events WHERE actor_kind = 'human'")
            ).scalar_one()
        )


def _rules_of(row: Any) -> RuleSet:
    return RuleSet.model_validate_json(str(row["rules"]))


def _facet_of(row: Any) -> Facet | None:
    if row["facet_question"] is None:
        return None
    return Facet(question_id=str(row["facet_question"]), slot=str(row["facet_slot"]))


# --- Definition ---


def _question_root(project: Project, question_id: str) -> str:
    with project.index.connect() as conn:
        parents = {
            str(q): None if s is None else str(s)
            for q, s in conn.execute(text("SELECT question_id, supersedes FROM questions")).all()
        }
    seen: set[str] = set()
    current = question_id
    while parents.get(current) is not None and current not in seen:
        seen.add(current)
        current = str(parents[current])
    return current


def _focus_issues(project: Project, facet: Facet, region_id: str | None) -> list[ValidationIssue]:
    version = get_question(project, facet.question_id)
    if version is None:
        return [ValidationIssue("facet.question_id", "question-unknown")]
    if facet.slot not in {slot.name for slot in version.spec.slots}:
        return [ValidationIssue("facet.slot", "slot-unknown")]
    root = _question_root(project, facet.question_id)
    with project.index.connect() as conn:
        others = conn.execute(
            text(
                "SELECT region_id, facet_question FROM regions "
                "WHERE kind = 'focus' AND facet_slot = :s AND region_id != :r"
            ),
            {"s": facet.slot, "r": region_id or ""},
        ).all()
    for other, question in others:
        if _question_root(project, str(question)) == root:
            return [ValidationIssue("facet", f"focus-exists:{other}")]
    return []


_HELD_OUT_REASON = "agents may name the development part"
_BARRED_PURPOSES = ("import", "probe", "seed")
_WALK_LIMIT = 200


def _snapshot_rules(project: Project, version: str) -> RuleSet | None:
    """The rules of the definition a version was pinned under, or None for an unknown version."""
    snapshot = _snapshot_of(project, version)
    if snapshot is None:
        return None
    with project.index.connect() as conn:
        stored = conn.execute(
            text("SELECT rules FROM region_definitions WHERE event_id = :e"),
            {"e": snapshot["definition_event"]},
        ).scalar_one_or_none()
    return None if stored is None else RuleSet.model_validate_json(str(stored))


def _rules_of_set(rules: RuleSet) -> list[Any]:
    return [*rules.include, *rules.exclude, *([rules.within] if rules.within else [])]


def _reaches_all(project: Project, rules: RuleSet, seen: set[str]) -> bool:
    """Whether the rules name an import's `all` part or a run of a barred query purpose, directly
    or through pinned versions (a `region` rule or the base of a `cites` rule), nested to any
    depth. A walk longer than `_WALK_LIMIT` versions reports True: the guard refuses rather than
    pass what it could not check."""
    for rule in _rules_of_set(rules):
        if isinstance(rule, ImportRule) and rule.part == "all":
            return True
        if isinstance(rule, RunRule) and _purpose_of(project, rule) in _BARRED_PURPOSES:
            return True
        version = (
            rule.version
            if isinstance(rule, RegionRule)
            else rule.base
            if isinstance(rule, CitesRule)
            else None
        )
        if version is None or version in seen:
            continue
        if len(seen) >= _WALK_LIMIT:
            return True
        seen.add(version)
        nested = _snapshot_rules(project, version)
        if nested is not None and _reaches_all(project, nested, seen):
            return True
    return False


def _purpose_of(project: Project, rule: RunRule) -> str | None:
    with project.index.connect() as conn:
        query: str | None = rule.query_id
        if query is None:
            via_run = conn.execute(
                text("SELECT query_id FROM runs WHERE run_id = :r"), {"r": rule.run_id}
            ).scalar_one_or_none()
            query = None if via_run is None else str(via_run)
        if query is None:
            return None
        found = conn.execute(
            text("SELECT purpose FROM queries WHERE query_id = :q"), {"q": query}
        ).scalar_one_or_none()
    return None if found is None else str(found)


def _rule_issues(project: Project, actor: Actor, rules: RuleSet) -> list[ValidationIssue]:
    """Role-blind guard for an agent author (decision 37 item 9): a rule that would reach the
    held-out part of an import, or select by a query of purpose import, seed or probe, is refused
    as a whole; no work is ever filtered. A human is not restricted."""
    if actor.kind == "human":
        return []
    issues: list[ValidationIssue] = []
    labelled = [
        *((f"rules.include[{i}]", r) for i, r in enumerate(rules.include)),
        *((f"rules.exclude[{i}]", r) for i, r in enumerate(rules.exclude)),
        *((("rules.within", rules.within),) if rules.within is not None else ()),
    ]
    for field, rule in labelled:
        single = RuleSet(include=(rule,))
        if isinstance(rule, ImportRule) and rule.part == "all":
            issues.append(ValidationIssue(f"{field}.part", _HELD_OUT_REASON))
        elif isinstance(rule, RegionRule | CitesRule) and _reaches_all(project, single, set()):
            issues.append(ValidationIssue(field, _HELD_OUT_REASON))
        elif isinstance(rule, RunRule) and _purpose_of(project, rule) in _BARRED_PURPOSES:
            issues.append(ValidationIssue(field, "agents may not select by this query purpose"))
    return issues


def define_region(
    project: Project,
    actor: Actor,
    *,
    kind: RegionKind,
    name: str,
    definition: str,
    rules: RuleSet,
    facet: Facet | None = None,
    region_id: str | None = None,
) -> str:
    """Define a region, or a new definition of `region_id`, and return the region id. Refused,
    with nothing written (fields `actor`, `name`, `definition`, `kind`, `facet`, `region_id`,
    `rules.<position>.part`, `facet.question_id`, `facet.slot`): see the module docstring. A
    redefinition keeps the kind and the facet; `supersedes` is the previous definition."""
    if actor.kind not in ("agent", "human"):
        raise _refuse(ValidationIssue("actor", "only an agent or a human defines a region"))
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if not name.strip() or len(name) > REGION_NAME_MAX_CHARS:
            issues.append(ValidationIssue("name", f"1 to {REGION_NAME_MAX_CHARS} characters"))
        if not definition.strip() or len(definition) > REGION_DEFINITION_MAX_CHARS:
            issues.append(
                ValidationIssue("definition", f"1 to {REGION_DEFINITION_MAX_CHARS} characters")
            )
        previous = None
        if region_id is not None:
            previous = _definition(project, region_id)
            if previous is None:
                issues.append(ValidationIssue("region_id", "region-unknown"))
            else:
                if previous["kind"] != kind.value:
                    issues.append(ValidationIssue("kind", "cannot-change"))
                stored = _facet_of(previous)
                if facet is not None and facet != stored:
                    issues.append(ValidationIssue("facet", "cannot-change"))
                facet = stored
        if kind is RegionKind.FOCUS and facet is None:
            issues.append(ValidationIssue("facet", "a focus names a question slot"))
        elif kind is RegionKind.REGION and facet is not None:
            issues.append(ValidationIssue("facet", "a region takes no facet"))
        elif facet is not None and previous is None:
            issues += _focus_issues(project, facet, region_id)
        issues += _rule_issues(project, actor, rules)
        if issues:
            raise _refuse(*issues)
        new_id = region_id or f"reg_{project.ids.ulid()}"
        try:
            payload = RegionDefined(
                region_id=new_id,
                kind=kind,
                facet=facet,
                name=name,
                definition=definition,
                rules=rules,
                supersedes=None if previous is None else str(previous["event_id"]),
                author=actor.kind,
            )
        except ValidationError as exc:  # pragma: no cover - every field is checked above
            raise _refuse(ValidationIssue("payload", str(exc.errors()[0]["msg"]))) from exc
        input_blob = (
            project.blobs.put_json(
                {
                    "region_id": new_id,
                    "supersedes": payload.supersedes,
                    "rules": canonical_rules(rules),
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "region.defined", payload, actor, refs=[new_id], input_blob=input_blob
                )
            ]
        )
        return new_id


# --- Member decisions ---


_MEMBER_TABLES = {
    MemberType.WORK: ("works", "work_id"),
    MemberType.IDEA: ("ideas", "idea_id"),
}
_PREFIXES = {MemberType.IDEA: "ida_", MemberType.CONCEPT: "cpt_"}


def _member_issues(project: Project, member_type: MemberType, member: str) -> list[ValidationIssue]:
    """The id must be one line of printable, non-space characters (the projection folds the
    member blob line by line, and an event can never be corrected), carry the prefix of its
    type, and name a recorded work, idea or concept."""
    if not member or not member.isprintable() or any(ch.isspace() for ch in member):
        return [ValidationIssue("member", "member-invalid")]
    prefix = _PREFIXES.get(member_type)
    other = tuple(p for t, p in _PREFIXES.items() if t is not member_type)
    if (prefix is not None and not member.startswith(prefix)) or member.startswith(other):
        return [ValidationIssue("member", "member-type-mismatch")]
    with project.index.connect() as conn:
        if member_type is MemberType.CONCEPT:
            return (
                []
                if concept_exists(conn, member)
                else [ValidationIssue("member", "member-unknown")]
            )
        table, column = _MEMBER_TABLES[member_type]
        found = conn.execute(
            text(f"SELECT 1 FROM {table} WHERE {column} = :m"), {"m": member}
        ).first()
    return [] if found is not None else [ValidationIssue("member", "member-unknown")]


def decide_member(
    project: Project,
    actor: Actor,
    region_id: str,
    member_type: MemberType,
    member: str,
    decision: Literal["add", "remove", "reject"],
    note: str | None = None,
    *,
    proposal_id: str | None = None,
) -> str:
    """Record a human add, removal or rejection of one member (gate `regions.member_decide`); the
    latest add or remove per member binds the next snapshot, and a rejection only closes the
    proposals of that member (those it names, else every open one) and changes no membership.
    `proposal_id` must name a proposal of this region and member. Returns the event id."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "regions.member_decide")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human decides a member")]
        if _definition(project, region_id) is None:
            issues.append(ValidationIssue("region_id", "region-unknown"))
        issues += _member_issues(project, member_type, member)
        if proposal_id is not None and not _proposal_matches(
            project, proposal_id, region_id, member_type, member
        ):
            issues.append(ValidationIssue("proposal_id", "proposal-unknown"))
        if issues:
            raise _refuse(*issues)
        event = project.events.make(
            "region.member_decided",
            RegionMemberDecided(
                region_id=region_id,
                member_type=member_type,
                member=member,
                decision=decision,
                note=note,
                proposal_id=proposal_id,
            ),
            actor,
            refs=[region_id, member],
        )
        project.record([event])
        return event.id


def _resolve_member(project: Project, member_type: MemberType, member: str) -> str:
    """The canonical work id or live (merge-resolved) idea or concept id of a decided member."""
    with project.index.connect() as conn:
        if member_type is MemberType.WORK:
            primary = conn.execute(
                text(
                    'SELECT m."primary" FROM merge_members mm JOIN merges m '
                    "ON m.merge_id = mm.merge_id WHERE mm.work_id = :w AND m.status = 'active'"
                ),
                {"w": member},
            ).scalar_one_or_none()
            return member if primary is None else str(primary)
        if member_type is MemberType.CONCEPT:
            return concept_live(conn, member)
        current, seen = member, set()
        while current not in seen:
            seen.add(current)
            into = conn.execute(
                text("SELECT merged_into FROM ideas WHERE idea_id = :i"), {"i": current}
            ).scalar_one_or_none()
            if into is None:
                break
            current = str(into)
        return current


def _decisions_in_effect(
    project: Project, region_id: str
) -> list[tuple[str, MemberType, str, str]]:
    """`(event id, member type, member, decision)` of the latest decision per member, with the
    members resolved to canonical work ids and live idea and concept ids first: the latest
    decision of a resolved member binds, whichever id it was made under."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event_id, member_type, member, decision FROM region_member_decisions "
                "WHERE region_id = :r AND decision != 'reject' ORDER BY event_id"
            ),
            {"r": region_id},
        ).all()
    latest: dict[tuple[MemberType, str], tuple[str, str]] = {}
    for event_id, kind, member, decision in rows:
        member_type = MemberType(str(kind))
        key = (member_type, _resolve_member(project, member_type, str(member)))
        latest[key] = (str(event_id), str(decision))
    return sorted(((e, t, m, d) for (t, m), (e, d) in latest.items()), key=lambda x: x[0])


# --- Member proposals ---


def _proposal_matches(
    project: Project, proposal_id: str, region_id: str, member_type: MemberType, member: str
) -> bool:
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT 1 FROM region_member_proposals WHERE proposal_id = :p AND region_id = :r "
                "AND member_type = :t AND member = :m"
            ),
            {"p": proposal_id, "r": region_id, "t": member_type.value, "m": member},
        ).first()
    return found is not None


def _quote_issues(
    project: Project, member_type: MemberType, member: str, basis: QuoteBasis
) -> list[ValidationIssue]:
    """The quote must be verbatim in the anchored element of a conversion of the candidate work."""
    if member_type is not MemberType.WORK:
        return [ValidationIssue("basis", "quote-needs-work-member")]
    wanted = _resolve_member(project, MemberType.WORK, member)
    if _resolve_member(project, MemberType.WORK, basis.work_id) != wanted:
        return [ValidationIssue("basis.work_id", "quote-other-work")]
    owner = conversion_work(project, basis.conversion_id)
    if owner is None:
        return [ValidationIssue("basis.conversion_id", "conversion-unknown")]
    if _resolve_member(project, MemberType.WORK, owner) != wanted:
        return [ValidationIssue("basis.conversion_id", "conversion-other-work")]
    try:
        manifest = conversion_manifest(project, basis.conversion_id)
    except FactoryValidationError:
        return [ValidationIssue("basis.conversion_id", "conversion-unreadable")]
    anchor = manifest.get(basis.anchor)
    if anchor is None:
        return [ValidationIssue("basis.anchor", "anchor-unknown")]
    if not quote_in_element(anchor.text, basis.quote):
        return [ValidationIssue("basis.quote", "quote-not-verbatim")]
    return []


_USE_KINDS = {"paper": MemberType.WORK, "idea": MemberType.IDEA, "concept": MemberType.CONCEPT}
_ALL_EDGE_TYPES = frozenset(EdgeType)


def _graph_other_end(project: Project, member: Member, edge_id: str) -> Member | None:
    """The other end of graph edge `edge_id` seen from `member`, in the default view (stated or
    confirmed, live); None when no such edge touches the member."""
    if member[0] is MemberType.CONCEPT:
        return None
    neighbours = index_neighbours(project)
    for direction in ("out", "in"):
        for edge in neighbours(member[1], direction, _ALL_EDGE_TYPES):
            if edge.edge_id == edge_id:
                other = edge.target if direction == "out" else edge.source
                kind = MemberType.IDEA if other.startswith("ida_") else MemberType.WORK
                return kind, _resolve_member(project, kind, other)
    return None


def _edge_issues(
    project: Project, region_id: str, row: Any, member_type: MemberType, member: str, edge_id: str
) -> list[ValidationIssue]:
    me: Member = (member_type, _resolve_member(project, member_type, member))
    other: Member | None
    with project.index.connect() as conn:
        use = use_link(conn, edge_id) if edge_id.startswith("lnk_") else None
        known = (
            use is not None
            or conn.execute(
                text("SELECT 1 FROM graph_edges WHERE edge_id = :e"), {"e": edge_id}
            ).first()
            is not None
        )
    if not known:
        return [ValidationIssue("basis.edge_id", "edge-unknown")]
    if use is not None:
        from_node, from_kind, concept, _ = use
        kind = _USE_KINDS[from_kind]
        ends = [(kind, _resolve_member(project, kind, from_node)), (MemberType.CONCEPT, concept)]
        other = next((e for e in ends if e != me), None) if me in ends else None
    else:
        other = _graph_other_end(project, me, edge_id)
    if other is None:
        return [ValidationIssue("basis.edge_id", "edge-not-incident")]
    result, _ = _evaluate(project, region_id, row)
    if other not in set(result.members):
        return [ValidationIssue("basis.edge_id", "edge-not-in-region")]
    return []


def propose_member(
    project: Project,
    actor: Actor,
    region_id: str,
    member_type: MemberType,
    member: str,
    basis: MemberBasis,
    note: str | None = None,
) -> str:
    """Propose one member with a verified basis and return the proposal id (`rmp_`). Any actor
    may propose; the proposal changes no snapshot until a human adds the member. An identical open
    proposal (same member and basis) is returned and nothing is written. Refused, with nothing
    written (fields `actor`, `region_id`, `member`, `note`, `basis`, `basis.<field>`): an unknown
    region or member, a quote that is not verbatim, an edge that is unknown, not incident to the
    candidate or not touching a current member."""
    if actor.kind not in ("agent", "human"):
        raise _refuse(ValidationIssue("actor", "only an agent or a human proposes a member"))
    with project.index.exclusive():
        project.index.sync()
        row = _definition(project, region_id)
        issues: list[ValidationIssue] = []
        if row is None:
            issues.append(ValidationIssue("region_id", "region-unknown"))
        issues += _member_issues(project, member_type, member)
        if note is not None and len(note) > PROPOSAL_NOTE_MAX_CHARS:
            issues.append(ValidationIssue("note", f"at most {PROPOSAL_NOTE_MAX_CHARS} characters"))
        if not issues:
            if isinstance(basis, QuoteBasis):
                issues += _quote_issues(project, member_type, member, basis)
            else:
                issues += _edge_issues(project, region_id, row, member_type, member, basis.edge_id)
        if issues:
            raise _refuse(*issues)
        canonical = canonical_json(basis.model_dump(mode="json")).decode()
        for open_one in pending_proposals(project, region_id):
            same = canonical_json(open_one.basis.model_dump(mode="json")).decode() == canonical
            if same and open_one.member_type is member_type and open_one.member == member:
                return open_one.proposal_id
        proposal_id = f"rmp_{project.ids.ulid()}"
        payload = RegionMemberProposed(
            proposal_id=proposal_id,
            region_id=region_id,
            member_type=member_type,
            member=member,
            basis=basis,
            note=note,
        )
        input_blob = (
            project.blobs.put_json(
                {
                    "region_id": region_id,
                    "member_type": member_type.value,
                    "member": member,
                    "basis": json.loads(canonical),
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "region.member_proposed",
                    payload,
                    actor,
                    refs=[region_id, member, proposal_id],
                    input_blob=input_blob,
                )
            ]
        )
        return proposal_id


def pending_proposals(project: Project, region_id: str) -> list[RegionMemberProposed]:
    """The proposals of the region not yet closed, oldest first: a proposal is closed by any later
    human decision (add, remove or reject) on the same member, or one that names it."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.proposal_id, p.region_id, p.member_type, p.member, p.basis, p.note "
                "FROM region_member_proposals p WHERE p.region_id = :r AND NOT EXISTS ("
                "SELECT 1 FROM region_member_decisions d WHERE d.region_id = p.region_id "
                "AND d.member_type = p.member_type AND d.member = p.member "
                "AND (d.event_id > p.event_id OR d.proposal_id = p.proposal_id)) "
                "ORDER BY p.event_id"
            ),
            {"r": region_id},
        ).all()
    return [
        RegionMemberProposed.model_validate(
            {
                "proposal_id": pid,
                "region_id": rid,
                "member_type": kind,
                "member": member,
                "basis": json.loads(str(basis)),
                "note": note,
            }
        )
        for pid, rid, kind, member, basis, note in rows
    ]


# --- Evaluation and snapshots ---


def _evaluate(project: Project, region_id: str, row: Any) -> tuple[Evaluation, list[str]]:
    decisions = _decisions_in_effect(project, region_id)
    adds = [(t, m) for _, t, m, d in decisions if d == "add"]
    removes = [(t, m) for _, t, m, d in decisions if d == "remove"]
    with project.index.connect() as conn:
        result = evaluate(conn, project, _rules_of(row), adds=adds, removes=removes)
    return result, [e for e, *_ in decisions]


def snapshot_region(project: Project, actor: Actor, region_id: str) -> str:
    """Evaluate the region and pin the result; return its version `R@`. Any actor may snapshot
    (the step is deterministic bookkeeping); an agent's carries provenance. An unchanged
    evaluation returns the latest version and writes nothing. Refused (fields `region_id`,
    `rules...`) for an unknown region, an over-bound rule or a rule kind not yet available."""
    with project.index.exclusive():
        project.index.sync()
        row = _definition(project, region_id)
        if row is None:
            raise _refuse(ValidationIssue("region_id", "region-unknown"))
        result, decision_ids = _evaluate(project, region_id, row)
        rules = _rules_of(row)
        text_bytes = members_text(result.members)
        mh, rh = members_hash(text_bytes), rules_hash(rules)
        facet = _facet_of(row)
        version = region_version(region_id, str(row["kind"]), facet, rh, decision_ids, mh)
        latest = _latest_snapshot(project, region_id)
        if latest is not None and latest["version"] == version:
            return version
        decided = {
            (t, m): e for e, t, m, d in _decisions_in_effect(project, region_id) if d == "add"
        }
        basis: dict[str, Any] = {
            f"{t.value}\t{m}": {
                "rules": list(result.basis[(t, m)]),
                "decision": decided.get((t, m)),
            }
            for t, m in result.members
        }
        last = project.index.last_event_id()
        assert last is not None
        payload = RegionSnapshotTaken(
            region_id=region_id,
            version=version,
            definition_event=str(row["event_id"]),
            rules_hash=rh,
            decisions=tuple(sorted(decision_ids)),
            members_blob=project.blobs.put(compress(text_bytes)),
            members_hash=mh,
            basis_blob=project.blobs.put_json(basis),
            counts=dict(result.counts),
            as_of=last,
        )
        input_blob = (
            project.blobs.put_json(
                {"region_id": region_id, "definition_event": str(row["event_id"])}
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "region.snapshot_taken",
                    payload,
                    actor,
                    refs=[region_id, version],
                    input_blob=input_blob,
                )
            ]
        )
        return version


# --- Review ---


def review_region(
    project: Project,
    actor: Actor,
    version: str,
    state: Literal["reviewed", "wrong"],
    note: str | None = None,
) -> str:
    """Record a human review of a pinned version and return the event id; the latest review of a
    version wins. Refused, with nothing written (fields `actor`, `session`, `version`, `note`,
    `reviewer`): see the module docstring."""
    with project.index.exclusive():
        project.index.sync()
        snapshot = _snapshot_of(project, version)
        definition = None
        if snapshot is not None:
            with project.index.connect() as conn:
                definition = (
                    conn.execute(
                        text(
                            "SELECT author, author_user, writer_session FROM region_definitions "
                            "WHERE event_id = :e"
                        ),
                        {"e": snapshot["definition_event"]},
                    )
                    .mappings()
                    .first()
                )
        proposer = (
            str(definition["writer_session"])
            if definition is not None and definition["author"] == "agent"
            else None
        )
        issues = gate_issues(project, actor, "regions.review", proposer_session=proposer)
        if actor.kind != "human" and not issues:
            issues.append(ValidationIssue("actor", "only a human reviews"))
        if snapshot is None:
            issues.append(ValidationIssue("version", "version-unknown"))
        if state == "wrong" and not (note and note.strip()):
            issues.append(ValidationIssue("note", "state why the version is wrong"))
        self_reviewed = (
            definition is not None
            and definition["author"] == "human"
            and definition["author_user"] == actor.user
        )
        if self_reviewed and _human_users(project) > 1:
            issues.append(ValidationIssue("reviewer", "another human reviews this version"))
        if issues:
            raise _refuse(*issues)
        event = project.events.make(
            "region.reviewed",
            RegionReviewed(version=version, state=state, note=note, self_reviewed=self_reviewed),
            actor,
            refs=[version],
        )
        project.record([event])
        return event.id


def review_state(project: Project, version: str) -> ReviewState:
    """`superseded` when the region's latest snapshot is another version; else the latest human
    review of this version, or `unreviewed`."""
    project.index.sync()
    snapshot = _snapshot_of(project, version)
    if snapshot is not None:
        latest = _latest_snapshot(project, str(snapshot["region_id"]))
        if latest is not None and latest["version"] != version:
            return "superseded"
    with project.index.connect() as conn:
        state = conn.execute(
            text(
                "SELECT state FROM region_reviews WHERE version = :v ORDER BY event_id DESC LIMIT 1"
            ),
            {"v": version},
        ).scalar_one_or_none()
    return "unreviewed" if state is None else ("reviewed" if state == "reviewed" else "wrong")


# --- Reads ---


class RegionState(StrictModel):
    """A region as a reader sees it. `live_counts` and the drift come from evaluating the latest
    definition now; `live_error` names the refusal when it cannot be evaluated."""

    region_id: str
    kind: RegionKind
    facet: Facet | None
    name: str
    latest_version: str | None
    review_state: ReviewState
    live_counts: dict[str, int]
    drift_added: int
    drift_removed: int
    live_error: str | None
    definition_author: str


def _snapshot_members(project: Project, region_id: str) -> set[Member]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT member_type, member FROM region_members WHERE region_id = :r"),
            {"r": region_id},
        ).all()
    return {(MemberType(str(t)), str(m)) for t, m in rows}


def region_state(project: Project, region_id: str) -> RegionState:
    """The state of one region. Refused (field `region_id`) when unknown."""
    project.index.sync()
    row = _definition(project, region_id)
    if row is None:
        raise _refuse(ValidationIssue("region_id", "region-unknown"))
    latest = _latest_snapshot(project, region_id)
    live: dict[str, int] = {}
    added = removed = 0
    error: str | None = None
    try:
        result, _ = _evaluate(project, region_id, row)
        live = {k.value: v for k, v in result.counts.items()}
        if latest is not None:
            now, then = set(result.members), _snapshot_members(project, region_id)
            added, removed = len(now - then), len(then - now)
    except FactoryValidationError as exc:
        error = "; ".join(f"{i.field}: {i.reason}" for i in exc.issues)
    version = None if latest is None else str(latest["version"])
    return RegionState(
        region_id=region_id,
        kind=RegionKind(str(row["kind"])),
        facet=_facet_of(row),
        name=str(row["name"]),
        latest_version=version,
        review_state="unreviewed" if version is None else review_state(project, version),
        live_counts=live,
        drift_added=added,
        drift_removed=removed,
        live_error=error,
        definition_author=str(row["author"]),
    )


def region_ids(project: Project, *, kind: RegionKind | None = None) -> list[str]:
    project.index.sync()
    query = "SELECT region_id FROM regions"
    params: dict[str, str] = {}
    if kind is not None:
        query += " WHERE kind = :k"
        params["k"] = kind.value
    with project.index.connect() as conn:
        return [str(r[0]) for r in conn.execute(text(query + " ORDER BY region_id"), params)]


def region_members(
    project: Project, version: str, *, offset: int = 0, limit: int = 500
) -> list[Member]:
    """One page of a version's members, sorted by (type, id): from the projection for the latest
    version of its region, else from its blob. Empty for an unknown version."""
    project.index.sync()
    snapshot = _snapshot_of(project, version)
    if snapshot is None:
        return []
    region_id = str(snapshot["region_id"])
    latest = _latest_snapshot(project, region_id)
    if latest is not None and latest["version"] == version:
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT member_type, member FROM region_members WHERE region_id = :r "
                    "ORDER BY member_type, member LIMIT :n OFFSET :o"
                ),
                {"r": region_id, "n": limit, "o": offset},
            ).all()
        return [(MemberType(str(t)), str(m)) for t, m in rows]
    members = read_members_blob(project.blobs.get(str(snapshot["members_blob"])))
    return sorted(members, key=lambda m: (m[0].value, m[1]))[offset : offset + limit]


class VersionInfo(StrictModel):
    """A pinned version as a reader sees it: counts by member type come from its snapshot."""

    version: str
    region_id: str
    counts: dict[str, int]
    review_state: ReviewState
    latest: bool


def version_info(project: Project, version: str) -> VersionInfo | None:
    """The pinned version `version`, or None when no snapshot has it."""
    project.index.sync()
    snapshot = _snapshot_of(project, version)
    if snapshot is None:
        return None
    region_id = str(snapshot["region_id"])
    latest = _latest_snapshot(project, region_id)
    members = read_members_blob(project.blobs.get(str(snapshot["members_blob"])))
    counts = {kind.value: sum(1 for t, _ in members if t is kind) for kind in MemberType}
    return VersionInfo(
        version=version,
        region_id=region_id,
        counts={k: v for k, v in counts.items() if v},
        review_state=review_state(project, version),
        latest=latest is not None and latest["version"] == version,
    )


# --- Foci ---


def foci(project: Project) -> list[RegionState]:
    """Every focus, by region id."""
    return [region_state(project, rid) for rid in region_ids(project, kind=RegionKind.FOCUS)]


def focus_slot_missing(project: Project) -> list[str]:
    """Region ids of the foci whose slot the current question no longer has."""
    question = current_question(project)
    if question is None:
        return []
    slots = {slot.name for slot in question.spec.slots}
    missing: list[str] = []
    for region_id in region_ids(project, kind=RegionKind.FOCUS):
        row = _definition(project, region_id)
        if row is not None and row["facet_slot"] not in slots:
            missing.append(region_id)
    return missing


def snapshot_diff(project: Project, older: str, newer: str) -> tuple[list[Member], list[Member]]:
    """`(added, removed)` going from version `older` to version `newer`, both read in full from
    their blobs. Refused (field `version`) for an unknown version."""
    project.index.sync()
    sets: list[set[Member]] = []
    for version in (older, newer):
        snapshot = _snapshot_of(project, version)
        if snapshot is None:
            raise _refuse(ValidationIssue("version", f"version-unknown:{version}"))
        sets.append(set(read_members_blob(project.blobs.get(str(snapshot["members_blob"])))))
    key = lambda m: (m[0].value, m[1])  # noqa: E731
    return sorted(sets[1] - sets[0], key=key), sorted(sets[0] - sets[1], key=key)


# --- Links, overlap, diff and membership ---


def _version_members(project: Project, version: str, field: str) -> set[Member]:
    snapshot = _snapshot_of(project, version)
    if snapshot is None:
        raise _refuse(ValidationIssue(field, f"version-unknown:{version}"))
    return set(read_members_blob(project.blobs.get(str(snapshot["members_blob"]))))


def link_regions(
    project: Project,
    actor: Actor,
    link_type: Literal["subregion-of", "related"],
    source: str,
    target: str,
    note: str | None = None,
) -> None:
    """Declare a link between two pinned versions (gate `regions.link`, human only). `subregion-of`
    needs every member of `source` in `target`. Refused, with nothing written (fields `actor`,
    `source`, `target`, `note`): an unknown version, the same version twice, a note over 600
    characters, a subset that does not hold."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "regions.link")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human links regions")]
        sets: dict[str, set[Member]] = {}
        for field, version in (("source", source), ("target", target)):
            try:
                sets[field] = _version_members(project, version, field)
            except FactoryValidationError as exc:
                issues += exc.issues
        try:
            payload = RegionLinked(link_type=link_type, source=source, target=target, note=note)
        except ValidationError as exc:
            issues.append(ValidationIssue("link", str(exc.errors()[0]["msg"])))
            payload = None
        if payload is not None and link_type == "subregion-of" and len(sets) == 2:
            outside = len(sets["source"] - sets["target"])
            if outside:
                issues.append(ValidationIssue("source", f"not-a-subset:{outside}"))
        if issues:
            raise _refuse(*issues)
        assert payload is not None
        project.record(
            [project.events.make("region.linked", payload, actor, refs=[source, target])]
        )


def subregion_violations(project: Project) -> list[tuple[str, str, str]]:
    """`(link event id, child region, parent region)` of each `subregion-of` link whose child's
    latest version has a member the parent's latest version lacks."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT l.event_id, sc.region_id, sp.region_id FROM region_links l "
                "JOIN region_snapshots sc ON sc.version = l.source "
                "JOIN region_snapshots sp ON sp.version = l.target "
                "WHERE l.link_type = 'subregion-of' AND EXISTS ("
                "SELECT 1 FROM region_members c WHERE c.region_id = sc.region_id AND NOT EXISTS ("
                "SELECT 1 FROM region_members p WHERE p.region_id = sp.region_id "
                "AND p.member_type = c.member_type AND p.member = c.member)) "
                "ORDER BY l.event_id"
            )
        ).all()
    return [(str(e), str(c), str(p)) for e, c, p in rows]


class Overlap(StrictModel):
    """Counts by member type for two versions; `jaccard` is shared over union where the union is
    not empty. Computed, never stored."""

    a: str
    b: str
    shared: dict[MemberType, int]
    only_a: dict[MemberType, int]
    only_b: dict[MemberType, int]
    jaccard: dict[MemberType, float]


def _by_type(members: set[Member]) -> dict[MemberType, int]:
    counts = {kind: sum(1 for t, _ in members if t is kind) for kind in MemberType}
    return {kind: n for kind, n in counts.items() if n}


def overlap(project: Project, a: str, b: str) -> Overlap:
    """The overlap of two versions. Refused (fields `a`, `b`) for an unknown version."""
    project.index.sync()
    issues: list[ValidationIssue] = []
    sets: dict[str, set[Member]] = {}
    for field, version in (("a", a), ("b", b)):
        try:
            sets[field] = _version_members(project, version, field)
        except FactoryValidationError as exc:
            issues += exc.issues
    if issues:
        raise _refuse(*issues)
    union = _by_type(sets["a"] | sets["b"])
    shared = _by_type(sets["a"] & sets["b"])
    return Overlap(
        a=a,
        b=b,
        shared=shared,
        only_a=_by_type(sets["a"] - sets["b"]),
        only_b=_by_type(sets["b"] - sets["a"]),
        jaccard={kind: shared.get(kind, 0) / n for kind, n in union.items()},
    )


class RegionDiff(StrictModel):
    """One page of the changes going from version `a` to version `b`: the page runs over the added
    members first and then the removed ones, each sorted by (type, id)."""

    a: str
    b: str
    added: list[Member]
    removed: list[Member]
    total_added: int
    total_removed: int
    offset: int
    limit: int


def diff(project: Project, a: str, b: str, *, offset: int = 0, limit: int = 500) -> RegionDiff:
    """Members added and removed going from `a` to `b`, one deterministic page. Refused (fields
    `a`, `b`, `offset`, `limit`)."""
    if offset < 0 or limit < 1:
        raise _refuse(ValidationIssue("offset" if offset < 0 else "limit", "out-of-range"))
    try:
        added, removed = snapshot_diff(project, a, b)
    except FactoryValidationError as exc:
        raise _refuse(*(ValidationIssue("a", i.reason) for i in exc.issues)) from exc
    window = [*((0, m) for m in added), *((1, m) for m in removed)][offset : offset + limit]
    return RegionDiff(
        a=a,
        b=b,
        added=[m for side, m in window if side == 0],
        removed=[m for side, m in window if side == 1],
        total_added=len(added),
        total_removed=len(removed),
        offset=offset,
        limit=limit,
    )


class RegionMembership(StrictModel):
    """A region whose latest version holds a member, and the basis recorded for it. `adopted_from`
    is reserved for adopted versions (Later)."""

    region_id: str
    version: str
    review_state: ReviewState
    adopted_from: str | None
    basis: dict[str, Any]


def regions_of(project: Project, member_type: MemberType, member: str) -> list[RegionMembership]:
    """The regions whose latest version holds the member (merges applied to the id), by region id:
    one indexed read of `region_members`."""
    project.index.sync()
    resolved = _resolve_member(project, member_type, member)
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT m.region_id, m.version, m.basis, COALESCE((SELECT r.state FROM "
                "region_reviews r WHERE r.version = m.version ORDER BY r.event_id DESC LIMIT 1), "
                "'unreviewed') FROM region_members m "
                "WHERE m.member = :m AND m.member_type = :t ORDER BY m.region_id"
            ),
            {"m": resolved, "t": member_type.value},
        ).all()
    return [
        RegionMembership(
            region_id=str(region),
            version=str(version),
            review_state="reviewed"
            if state == "reviewed"
            else "wrong"
            if state == "wrong"
            else "unreviewed",
            adopted_from=None,
            basis=json.loads(str(basis)) or {},
        )
        for region, version, basis, state in rows
    ]


__all__: Sequence[str] = [
    "Overlap",
    "RegionDiff",
    "RegionMembership",
    "RegionState",
    "VersionInfo",
    "decide_member",
    "define_region",
    "diff",
    "foci",
    "focus_slot_missing",
    "link_regions",
    "overlap",
    "pending_proposals",
    "propose_member",
    "region_ids",
    "region_members",
    "region_state",
    "regions_of",
    "review_region",
    "review_state",
    "snapshot_diff",
    "snapshot_region",
    "subregion_violations",
    "version_info",
]
