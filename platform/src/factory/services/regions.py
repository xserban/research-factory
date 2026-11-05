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
- Basis positions in a snapshot refer to the canonical (sorted, de-duplicated) include list.
- Every refusal reports all its issues together and writes nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.regions import (
    REGION_DEFINITION_MAX_CHARS,
    REGION_NAME_MAX_CHARS,
    Facet,
    RegionDefined,
    RegionKind,
    RegionMemberDecided,
    RegionReviewed,
    RegionSnapshotTaken,
)
from factory.regions.evaluate import Evaluation, Member, evaluate, read_members_blob
from factory.regions.rules import ImportRule, MemberType, RuleSet
from factory.regions.version import (
    canonical_rules,
    compress,
    members_hash,
    members_text,
    region_version,
    rules_hash,
)
from factory.services.context import Project
from factory.services.gates import gate_issues
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


def _rule_issues(actor: Actor, rules: RuleSet) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    labelled = [
        *((f"rules.include[{i}]", r) for i, r in enumerate(rules.include)),
        *((f"rules.exclude[{i}]", r) for i, r in enumerate(rules.exclude)),
        *((("rules.within", rules.within),) if rules.within is not None else ()),
    ]
    for field, rule in labelled:
        if isinstance(rule, ImportRule) and rule.part == "all" and actor.kind != "human":
            issues.append(ValidationIssue(f"{field}.part", "agents may name the development part"))
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
        issues += _rule_issues(actor, rules)
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


def decide_member(
    project: Project,
    actor: Actor,
    region_id: str,
    member_type: MemberType,
    member: str,
    decision: Literal["add", "remove"],
    note: str | None = None,
) -> str:
    """Record a human add or removal of one member (gate `regions.member_decide`); the latest
    decision per member binds the next snapshot. Returns the event id."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "regions.member_decide")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human decides a member")]
        if _definition(project, region_id) is None:
            issues.append(ValidationIssue("region_id", "region-unknown"))
        if not member.strip():
            issues.append(ValidationIssue("member", "a member id"))
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
            ),
            actor,
            refs=[region_id, member],
        )
        project.record([event])
        return event.id


def _decisions_in_effect(
    project: Project, region_id: str
) -> list[tuple[str, MemberType, str, str]]:
    """`(event id, member type, member, decision)` of the latest decision per member."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.event_id, d.member_type, d.member, d.decision "
                "FROM region_member_decisions d WHERE d.region_id = :r AND d.event_id = ("
                "SELECT MAX(x.event_id) FROM region_member_decisions x "
                "WHERE x.region_id = d.region_id AND x.member_type = d.member_type "
                "AND x.member = d.member) "
                "ORDER BY d.event_id"
            ),
            {"r": region_id},
        ).all()
    return [(str(e), MemberType(str(t)), str(m), str(d)) for e, t, m, d in rows]


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


__all__: Sequence[str] = [
    "RegionState",
    "VersionInfo",
    "decide_member",
    "define_region",
    "foci",
    "focus_slot_missing",
    "region_ids",
    "region_members",
    "region_state",
    "review_region",
    "review_state",
    "snapshot_diff",
    "snapshot_region",
    "version_info",
]
