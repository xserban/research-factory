"""Registered conclusions, their predicates and their basis state (slice 4b, plan living-D).

A conclusion is the researcher's statement with a basis of references that resolve through
`trace`; the platform computes whether its predicate holds and whether its basis is affected
(R-105). Nothing here judges: a conclusion's wording comes from a human, its state from events.

Invariants:
- Registration and retirement are human acts (gate living.conclusion_register, floor human); an
  invalid call writes nothing.
- Every basis reference resolves at registration (cells, rows and works through `trace`, groups
  through the current facts); a basis that later stops resolving makes the conclusion
  `basis-affected`, never an error that blocks a cycle.
- A predicate's arguments exist in the current facts when it is registered. `path-exists` is
  refused while slice 3b's lineage service is absent.
- `predicate_value` is pure; `None` means undefined, not false.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Mapping, Sequence

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.living.facts import ConclusionFacts, FactsDiff, conclusion_facts, facts_diff
from factory.model.conclusions import (
    CCL_ID_RE,
    BasisRef,
    ConclusionDiff,
    ConclusionRecord,
    ConclusionRegistered,
    ConclusionRetired,
    ConclusionSnapshot,
    Predicate,
)
from factory.services.context import Project
from factory.services.evidence_report import evidence_report
from factory.services.extraction import live_rows, stale_extractions
from factory.services.extraction_agreement import final_rows
from factory.services.notices import work_states
from factory.services.prisma import prisma_flow
from factory.services.snapshots import (
    included_work_ids,
    last_snapshot_event,
    snapshot_blob,
    snapshots,
)
from factory.services.trace import trace

# Module kind (slice M): a builder; its human input event is conclusion.registered.


def lineage_available() -> bool:
    """Whether slice 3b's lineage service is built (relations and `path-exists` need it)."""
    return importlib.util.find_spec("factory.services.lineage") is not None


def current_facts(project: Project) -> ConclusionFacts:
    """The facts of the default evidence report (not the agent view, no notice-affected rows) and
    the included-set size. Read-only."""
    report = evidence_report(project)
    included = len(included_work_ids(project, prisma_flow(project)))
    return conclusion_facts(report, included=included)


def predicate_value(facts: ConclusionFacts, predicate: Predicate) -> bool | None:
    """Whether `predicate` holds over `facts`; None when it is undefined (the group is gone, no
    best row is defined, or the path was not computed). Pure."""
    kind = predicate.kind
    if kind == "path-exists":
        for source, target, exists in facts.paths:
            if (source, target) == (predicate.source, predicate.target):
                return exists
        return None
    group = next((g for g in facts.groups if g.group_id == predicate.group_id), None)
    if group is None:
        return None
    if kind == "group-row-count-at-least":
        assert predicate.count is not None
        return group.independent_rows >= predicate.count
    if kind == "best-in-group":
        return None if group.best is None else predicate.row_key in group.best
    return predicate.row_key in group.frontier.get(predicate.axis_key or "", ())


def register_conclusion(
    project: Project,
    actor: Actor,
    statement: str,
    basis: Sequence[BasisRef],
    predicate: Predicate | None,
) -> str:
    """Record a conclusion and return its id (`ccl_<ULID>`).

    Refused, writing nothing, for an actor that is not a human, a blank statement, an empty
    basis, a basis reference that does not resolve, or a predicate whose arguments are not in the
    current facts. Gate: living.conclusion_register."""
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        issues.append(ValidationIssue("actor", "a conclusion is registered by a human"))
    if not statement.strip():
        issues.append(ValidationIssue("statement", "a statement is required"))
    if not basis:
        issues.append(ValidationIssue("basis", "name at least one basis reference"))
    if issues:
        raise FactoryValidationError(issues)
    with project.index.exclusive():
        project.index.sync()
        facts = current_facts(project)
        issues += _basis_issues(project, basis, facts)
        if predicate is not None:
            issues += _predicate_issues(project, predicate, facts)
        if issues:
            raise FactoryValidationError(issues)
        payload = ConclusionRegistered(
            conclusion_id=project.ids.new("ccl"),
            statement=statement,
            basis=tuple(basis),
            predicate=predicate,
        )
        event = project.events.make(
            "conclusion.registered",
            payload,
            actor,
            refs=(payload.conclusion_id, *(b.ref for b in basis)),
        )
        project.record([event])
    return payload.conclusion_id


def retire_conclusion(project: Project, actor: Actor, conclusion_id: str, reason: str) -> None:
    """Withdraw a conclusion from evaluation (the registration stays in the log).

    Refused, writing nothing, for a non-human actor, an unknown or already retired conclusion, or
    a blank reason. Gate: living.conclusion_register."""
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        issues.append(ValidationIssue("actor", "a conclusion is retired by a human"))
    if not reason.strip():
        issues.append(ValidationIssue("reason", "a reason is required"))
    if issues:
        raise FactoryValidationError(issues)
    with project.index.exclusive():
        project.index.sync()
        known = {c.conclusion_id: c for c in conclusions(project, include_retired=True)}
        if conclusion_id not in known:
            issues.append(ValidationIssue("conclusion_id", "unknown conclusion"))
        elif known[conclusion_id].retired:
            issues.append(ValidationIssue("conclusion_id", "already retired"))
        if issues:
            raise FactoryValidationError(issues)
        payload = ConclusionRetired(conclusion_id=conclusion_id, reason=reason)
        project.record(
            [project.events.make("conclusion.retired", payload, actor, refs=(conclusion_id,))]
        )


def conclusions(project: Project, *, include_retired: bool = False) -> list[ConclusionRecord]:
    """The registered conclusions in registration order; retired ones only on request."""
    project.index.sync()
    where = "" if include_retired else " WHERE retired_event IS NULL"
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conclusion_id, statement, basis, predicate, event_id, retired_event,"
                f" retire_reason FROM conclusions{where} ORDER BY event_id"
            )
        ).all()
    return [
        ConclusionRecord(
            conclusion_id=r[0],
            statement=r[1],
            basis=tuple(BasisRef.model_validate(b) for b in json.loads(r[2])),
            predicate=None if r[3] is None else Predicate.model_validate(json.loads(r[3])),
            registered_event=r[4],
            retired=r[5] is not None,
            retire_reason=r[6],
        )
        for r in rows
    ]


def basis_state(
    project: Project, basis: Sequence[BasisRef], *, facts: ConclusionFacts | None = None
) -> tuple[str, ...]:
    """The affected basis references with the reason, sorted (plan ruling 3); empty when the
    basis stands. A reference is affected when its work has `synthesis != normal`, its row is
    stale, superseded or no longer a final row, its group no longer exists, or (relations) the
    lineage is unavailable. Read-only."""
    states = work_states(project)
    affected: set[str] = set()
    rows = [b for b in basis if b.kind in ("row", "cell")]
    if rows:
        stale = stale_extractions(project)
        live: dict[str, list[tuple[str, str]]] = {}
        for row in live_rows(project):
            live.setdefault(row.row_key, []).append((row.extraction_id, row.work_id))
        final = {r.row_key for r in final_rows(project)}
        for b in rows:
            key = b.ref.split("/")[0]
            label = f"{b.kind}:{b.ref}"
            entries = live.get(key, [])
            if not entries:
                affected.add(f"{label}: superseded")
                continue
            if any(extraction_id in stale for extraction_id, _ in entries):
                affected.add(f"{label}: stale")
            for work_id in sorted({w for _, w in entries}):
                state = states.get(work_id)
                if state is not None and state.synthesis != "normal":
                    affected.add(f"{label}: notice-{state.flag}")
            if key not in final:
                affected.add(f"{label}: not-final")
    for b in basis:
        if b.kind == "work":
            state = states.get(b.ref)
            if state is not None and state.synthesis != "normal":
                affected.add(f"work:{b.ref}: notice-{state.flag}")
        elif b.kind == "group":
            groups = {g.group_id for g in (facts or current_facts(project)).groups}
            if b.ref not in groups:
                affected.add(f"group:{b.ref}: group-gone")
        elif b.kind == "relation" and not lineage_available():
            affected.add(f"relation:{b.ref}: no-lineage")
    return tuple(sorted(affected))


def conclusion_section(project: Project) -> Mapping[str, JsonValue]:
    """The snapshot section of the conclusions (a living-B `SnapshotSection`): the conclusion
    facts and each active conclusion's predicate value and basis state, as computed now.

    Empty while no conclusion is active, so a snapshot of a review without conclusions is
    unchanged. No statement is stored in the blob."""
    active = conclusions(project)
    if not active:
        return {}
    facts = current_facts(project)
    states = [
        ConclusionSnapshot(
            conclusion_id=c.conclusion_id,
            predicate_value=None if c.predicate is None else predicate_value(facts, c.predicate),
            affected=basis_state(project, c.basis, facts=facts),
        )
        for c in active
    ]
    return {
        "conclusion_facts": facts.model_dump(mode="json"),
        "conclusions": [s.model_dump(mode="json") for s in states],
    }


def conclusion_diff(project: Project, *, since: str | None = None) -> list[ConclusionDiff]:
    """How each active conclusion stands against snapshot `since` (default: the last).

    `new` for a conclusion the snapshot does not hold (registered after it, or no snapshot at
    all); `basis-affected` when a basis reference is affected that was not at the snapshot;
    `changed` when the predicate's value differs from the snapshot's; else `unchanged`. Computed,
    never stored; refused (field `since`) for an unknown snapshot. Read-only."""
    active = conclusions(project)
    if not active:
        return []
    facts = current_facts(project)
    old_facts: ConclusionFacts | None = None
    old: dict[str, ConclusionSnapshot] = {}
    if since is not None or last_snapshot_event(project) is not None:
        named = since or snapshots(project)[-1].snapshot_id
        try:
            blob = snapshot_blob(project, named)
        except FactoryValidationError:
            raise FactoryValidationError([ValidationIssue("since", "unknown snapshot")]) from None
        old_facts = blob.conclusion_facts
        old = {c.conclusion_id: c for c in blob.conclusions or ()}
    diffs: list[ConclusionDiff] = []
    for c in active:
        now = None if c.predicate is None else predicate_value(facts, c.predicate)
        affected = basis_state(project, c.basis, facts=facts)
        before = old.get(c.conclusion_id)
        if before is None:
            diffs.append(
                ConclusionDiff(
                    conclusion_id=c.conclusion_id,
                    state="new",
                    predicate_before=None,
                    predicate_now=now,
                    affected=affected,
                    facts=None,
                )
            )
            continue
        if set(affected) - set(before.affected):
            state = "basis-affected"
        elif before.predicate_value != now:
            state = "changed"
        else:
            state = "unchanged"
        diffs.append(
            ConclusionDiff(
                conclusion_id=c.conclusion_id,
                state=state,
                predicate_before=before.predicate_value,
                predicate_now=now,
                affected=affected,
                facts=None if old_facts is None else _scoped(facts_diff(old_facts, facts), c),
            )
        )
    return diffs


def _scoped(diff: FactsDiff, conclusion: ConclusionRecord) -> FactsDiff | None:
    """The part of `diff` that concerns the groups the conclusion names (None if it names none)."""
    names = {b.ref for b in conclusion.basis if b.kind == "group"}
    if conclusion.predicate is not None and conclusion.predicate.group_id is not None:
        names.add(conclusion.predicate.group_id)
    if not names:
        return None
    return FactsDiff(
        groups_added=tuple(g for g in diff.groups_added if g in names),
        groups_removed=tuple(g for g in diff.groups_removed if g in names),
        groups=tuple(g for g in diff.groups if g.group_id in names),
        included_delta=diff.included_delta,
    )


def _resolves(project: Project, ref: str) -> bool:
    try:
        trace(project, ref)
    except FactoryValidationError:
        return False
    return True


def _basis_issues(
    project: Project, basis: Sequence[BasisRef], facts: ConclusionFacts
) -> list[ValidationIssue]:
    groups = {g.group_id for g in facts.groups}
    issues: list[ValidationIssue] = []
    for index, b in enumerate(basis):
        if b.kind == "group":
            ok = b.ref in groups
        elif b.kind == "relation":
            ok = False  # relations exist only with slice 3b
        else:
            ok = _resolves(project, b.ref)
        if not ok:
            issues.append(ValidationIssue("basis", f"basis[{index}] {b.kind} {b.ref}: unresolved"))
    return issues


def _predicate_issues(
    project: Project, predicate: Predicate, facts: ConclusionFacts
) -> list[ValidationIssue]:
    def bad(message: str) -> list[ValidationIssue]:
        return [ValidationIssue("predicate", message)]

    if predicate.kind == "path-exists":
        if not lineage_available():
            return bad("path-exists needs the lineage service (slice 3b), which is not built")
        known = {(s, t) for s, t, _ in facts.paths}
        if (predicate.source, predicate.target) not in known:
            return bad("path-exists: no such path fact")
        return []
    group = next((g for g in facts.groups if g.group_id == predicate.group_id), None)
    if group is None:
        return bad(f"{predicate.group_id}: no such group in the current facts")
    if predicate.kind == "frontier-member" and predicate.axis_key not in group.frontier:
        return bad(f"{predicate.axis_key}: no such frontier in the group")
    if predicate.row_key is not None and not _resolves(project, predicate.row_key):
        return bad(f"{predicate.row_key}: unresolved row")
    return []


__all__ = [
    "CCL_ID_RE",
    "basis_state",
    "conclusion_diff",
    "conclusion_section",
    "conclusions",
    "current_facts",
    "lineage_available",
    "predicate_value",
    "register_conclusion",
    "retire_conclusion",
]
