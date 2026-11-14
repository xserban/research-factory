"""Deduplication as recorded events: merges, their reversal, and the canonical corpus.

`dedup_run` is the only writer of automatic merges. It runs the pure cascade over the works the
event log holds, then reconciles the result with the active merges: an unchanged merge is kept,
a changed one is reverted and replaced, and a merge the cascade no longer produces is reverted.
A reversal is final: its blocked pairs keep the cascade from rebuilding the merge on a later run.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import bindparam, text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.dedup import DedupMerged, DedupReverted, MergeStatus
from factory.model.work import Work
from factory.services.context import Project
from factory.services.dedup_cascade import CascadeMerge, dedup, merge_works
from factory.services.progress import track
from factory.services.search import corpus_size, list_works


class DedupSummary(StrictModel):
    """What one `dedup_run` recorded, and the corpus it left behind."""

    created: list[str]
    reverted: list[str]
    unchanged: int
    records: int
    works: int
    canonical: int


def dedup_run(project: Project) -> DedupSummary:
    """Reconcile the cascade's merges with the recorded ones, writing only what changed.

    The index's write lock is held from the read to the last write, so two concurrent runs cannot
    both record the same merge.
    """
    with project.index.exclusive():
        return _reconcile(project)


@dataclass(frozen=True)
class _Reconciliation:
    """What a run would do: `kept` merges stand, `stale` are reverted, `fresh` are recorded."""

    works: list[Work]
    kept: set[str]
    stale: list[DedupMerged]
    fresh: list[CascadeMerge]


def _reconciliation(project: Project, *, report: bool = True) -> _Reconciliation:
    works = list_works(project)
    blocked = blocked_pairs(project)
    joined = joined_pairs(project)
    aliases = alias_keys(project, [w.id for w in works])
    if report:
        with track(
            project, "dedup", "title comparison", unit="records", total=len(works)
        ) as reporter:
            result = dedup(
                works, blocked=blocked, joined=joined, aliases=aliases, progress=reporter.update
            )
    else:
        result = dedup(works, blocked=blocked, joined=joined, aliases=aliases)
    # Identity collapses (several records sharing one id) absorb nothing: they are not merges.
    groups = [group for group in result.merges if group.absorbed]
    active = active_merges(project)

    kept: set[str] = set()
    fresh: list[CascadeMerge] = []
    for group in groups:
        match = matching_merge(active, group)
        if match is None:
            fresh.append(group)
        else:
            kept.add(match.merge_id)
    stale = [merge for merge in active if merge.merge_id not in kept]
    return _Reconciliation(works, kept, stale, fresh)


def _reconcile(project: Project) -> DedupSummary:
    plan = _reconciliation(project)
    new_ids = write_reconciliation(project, plan.stale, plan.fresh)

    return DedupSummary(
        created=new_ids,
        reverted=[merge.merge_id for merge in plan.stale],
        unchanged=len(plan.kept),
        records=corpus_size(project)[1],
        works=len(plan.works),
        canonical=len(canonical_works(project)),
    )


def dedup_current(project: Project) -> bool:
    """Whether a `dedup_run` now would write nothing: no corpus work awaits deduplication.

    Read from the cascade, not from the log: a run that changes nothing writes no event, so the log
    cannot say when the last run was. A corpus with no duplicates is therefore current without any
    run, and every old project reads correctly. Screening waits on this (plan PF ruling 1).
    """
    project.index.sync()
    plan = _reconciliation(project, report=False)
    return not plan.stale and not plan.fresh


def write_reconciliation(
    project: Project, stale: list[DedupMerged], fresh: list[CascadeMerge]
) -> list[str]:
    """Record the reversal of each stale merge and the new merges, in one write.

    Returns the new merge ids, in the order of `fresh`. A stale merge's reversal names the first
    new merge that shares a member with it. Shared by `dedup_run` and incremental deduplication,
    so both write the same events under the same rules. The caller holds the index lock.
    """
    new_ids = [project.ids.new("mrg") for _ in fresh]
    system = project.system_actor()
    events: list[Event] = []
    for old in stale:
        successor = _successor(old, fresh, new_ids)
        reason = "no longer matched" if successor is None else f"superseded by {successor}"
        revert = DedupReverted(merge_id=old.merge_id, reason=reason, manual=False)
        events.append(project.events.make("dedup.reverted", revert, system, refs=(old.merge_id,)))
    for merge_id, group in zip(new_ids, fresh, strict=True):
        merged = DedupMerged(
            merge_id=merge_id,
            primary=group.primary,
            absorbed=tuple(group.absorbed),
            rule=group.rule,
            records=group.records,
        )
        events.append(
            project.events.make(
                "dedup.merged",
                merged,
                system,
                refs=(group.primary, *group.absorbed),
            )
        )
    if events:
        project.record(events)
    return new_ids


def revert_merge(project: Project, actor: Actor, merge_id: str, reason: str) -> None:
    """Undo an active merge by hand. The pair stays apart on every later dedup run."""
    issues: list[ValidationIssue] = []
    if not _is_active(project, merge_id):
        issues.append(ValidationIssue("merge_id", "unknown or already reverted"))
    if not reason.strip():
        issues.append(ValidationIssue("reason", "must not be empty"))
    if issues:
        raise FactoryValidationError(issues)

    clean = reason.strip()
    # An agent's reversal keeps its input verbatim, so the decision can be audited later.
    input_blob = (
        project.blobs.put_json({"merge_id": merge_id, "reason": clean})
        if actor.kind == "agent"
        else None
    )
    revert = DedupReverted(merge_id=merge_id, reason=clean, manual=True)
    with project.writing():
        project.record(
            [
                project.events.make(
                    "dedup.reverted",
                    revert,
                    actor,
                    refs=(merge_id,),
                    input_blob=input_blob,
                )
            ]
        )


def active_merges(project: Project) -> list[DedupMerged]:
    """Merges not yet reverted, ordered by merge id."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                'SELECT merge_id, "primary", absorbed, rule, records FROM merges '
                "WHERE status = :active ORDER BY merge_id"
            ),
            {"active": MergeStatus.ACTIVE.value},
        ).all()
    return [
        DedupMerged(
            merge_id=str(merge_id),
            primary=str(primary),
            absorbed=tuple(str(item) for item in json.loads(str(absorbed))),
            rule=str(rule),
            records=int(records),
        )
        for merge_id, primary, absorbed, rule, records in rows
    ]


class MergeRow(StrictModel):
    """One recorded merge, active or reverted, with the rule that matched. No verdict exists: the
    cascade matches identifiers. `primary`, `absorbed` and `reason` are None where works may not
    be named yet (`list_merges`)."""

    merge_id: str
    status: MergeStatus
    rule: str
    records: int
    primary: str | None
    absorbed: tuple[str, ...] | None
    reason: str | None
    manual: bool | None


def list_merges(project: Project, *, named: bool = True) -> list[MergeRow]:
    """Every merge by id. Without `named` a row keeps its id, status, rule and record count only:
    before a screening pass opens an agent must not read a held-out seed's work, and a human's
    reason may name one (decision 43). The shape does not depend on the row."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                'SELECT merge_id, status, rule, records, "primary", absorbed, reverted_reason, '
                "manual FROM merges ORDER BY merge_id"
            )
        ).all()
    return [
        MergeRow(
            merge_id=str(merge_id),
            status=MergeStatus(str(status)),
            rule=str(rule),
            records=int(records),
            primary=str(primary) if named else None,
            absorbed=tuple(str(w) for w in json.loads(str(absorbed))) if named else None,
            reason=None if reason is None or not named else str(reason),
            manual=None if manual is None else bool(manual),
        )
        for merge_id, status, rule, records, primary, absorbed, reason, manual in rows
    ]


def absorbed_ids(project: Project) -> set[str]:
    """The works an active merge absorbed: records of a work whose primary stands for them."""
    return {absorbed for merge in active_merges(project) for absorbed in merge.absorbed}


def canonical_works(project: Project) -> list[Work]:
    """The corpus with every active merge applied: one work per merge, all others unchanged."""
    works = {work.id: work for work in list_works(project)}
    members = [(merge.primary, *merge.absorbed) for merge in active_merges(project)]
    merged = [
        merge_works(group)
        for group in ([works[wid] for wid in ids if wid in works] for ids in members)
        if group
    ]
    covered = {wid for ids in members for wid in ids}
    rest = [work for wid, work in works.items() if wid not in covered]
    return sorted([*merged, *rest], key=lambda work: work.id)


def alias_keys(project: Project, work_ids: Sequence[str]) -> dict[str, list[tuple[str, str]]]:
    """The published identifiers linked to each of `work_ids` (version links), as exact-match keys.

    Read in chunks by work id; a work with no link is absent."""
    project.index.sync()
    found: dict[str, list[tuple[str, str]]] = {}
    statement = text(
        "SELECT work_id, kind, value FROM work_aliases WHERE work_id IN :ids ORDER BY kind, value"
    ).bindparams(bindparam("ids", expanding=True))
    ids = sorted(set(work_ids))
    with project.index.connect() as conn:
        for start in range(0, len(ids), 500):
            for work_id, kind, value in conn.execute(statement, {"ids": ids[start : start + 500]}):
                found.setdefault(str(work_id), []).append((str(kind), str(value)))
    return found


def blocked_pairs(project: Project) -> frozenset[frozenset[str]]:
    """Reverted merges' pairs plus the pairs the researcher ruled `different`."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT a, b FROM blocked_pairs ORDER BY a, b")).all()
        ruled = conn.execute(
            text("SELECT work_a, work_b FROM dedup_pair_decisions WHERE decision = 'different'")
        ).all()
    return frozenset(frozenset({str(a), str(b)}) for a, b in [*rows, *ruled])


def joined_pairs(project: Project) -> frozenset[frozenset[str]]:
    """Pairs the researcher ruled `same`."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_a, work_b FROM dedup_pair_decisions WHERE decision = 'same'")
        ).all()
    return frozenset(frozenset({str(a), str(b)}) for a, b in rows)


def matching_merge(active: list[DedupMerged], group: CascadeMerge) -> DedupMerged | None:
    for merge in active:
        if merge.primary == group.primary and set(merge.absorbed) == set(group.absorbed):
            return merge
    return None


def _successor(old: DedupMerged, fresh: list[CascadeMerge], new_ids: list[str]) -> str | None:
    """The first new merge that shares a member with `old`, if any."""
    members = {old.primary, *old.absorbed}
    for merge_id, group in zip(new_ids, fresh, strict=True):
        if members & {group.primary, *group.absorbed}:
            return merge_id
    return None


def _is_active(project: Project, merge_id: str) -> bool:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM merges WHERE merge_id = :merge"), {"merge": merge_id}
        ).one_or_none()
    return row is not None and row[0] == MergeStatus.ACTIVE.value


class MergedAfterScreening(StrictModel):
    """An absorbed work whose own title/abstract outcome differs from its primary's."""

    merge_id: str
    rule: str
    primary: str
    primary_title: str
    primary_outcome: str
    absorbed: str
    absorbed_title: str
    absorbed_outcome: str


def merged_after_screening(project: Project) -> list[MergedAfterScreening]:
    """Absorbed works whose own final title/abstract outcome differs from their primary's.

    Read-only, for the researcher's review: the primary's outcome stands in every count and
    nothing here changes an event. An absorbed work with no decided outcome of its own (pending
    records are left out by `final_outcomes`) was never screened separately and is not listed.
    Ordered by merge id, then absorbed id."""
    from factory.services.agreement import Outcome, final_outcomes  # circular at import time

    outcomes = final_outcomes(project)
    works = {work.id: work for work in list_works(project)}

    def outcome_of(work_id: str) -> str:
        return outcomes.get(work_id, Outcome.PENDING).value

    def title_of(work_id: str) -> str:
        work = works.get(work_id)
        return "" if work is None else work.title

    rows: list[MergedAfterScreening] = []
    for merge in active_merges(project):
        for absorbed in merge.absorbed:
            own = outcome_of(absorbed)
            if own == Outcome.PENDING.value or own == outcome_of(merge.primary):
                continue
            rows.append(
                MergedAfterScreening(
                    merge_id=merge.merge_id,
                    rule=merge.rule,
                    primary=merge.primary,
                    primary_title=title_of(merge.primary),
                    primary_outcome=outcome_of(merge.primary),
                    absorbed=absorbed,
                    absorbed_title=title_of(absorbed),
                    absorbed_outcome=outcome_of(absorbed),
                )
            )
    return rows
