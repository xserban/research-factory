"""Deduplication as recorded events: merges, their reversal, and the canonical corpus.

`dedup_run` is the only writer of automatic merges. It runs the pure cascade over the works the
event log holds, then reconciles the result with the active merges: an unchanged merge is kept,
a changed one is reverted and replaced, and a merge the cascade no longer produces is reverted.
A reversal is final: its blocked pairs keep the cascade from rebuilding the merge on a later run.
"""

import json

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.dedup import DedupMerged, DedupReverted, MergeStatus
from factory.model.work import Work
from factory.services.context import Project
from factory.services.dedup_cascade import CascadeMerge, dedup, merge_works
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


def _reconcile(project: Project) -> DedupSummary:
    works = list_works(project)
    result = dedup(works, blocked=blocked_pairs(project))
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
    new_ids = write_reconciliation(project, stale, fresh)

    return DedupSummary(
        created=new_ids,
        reverted=[merge.merge_id for merge in stale],
        unchanged=len(kept),
        records=corpus_size(project)[1],
        works=len(works),
        canonical=len(canonical_works(project)),
    )


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


def blocked_pairs(project: Project) -> frozenset[frozenset[str]]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT a, b FROM blocked_pairs ORDER BY a, b")).all()
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
