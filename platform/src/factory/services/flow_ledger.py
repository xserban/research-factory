"""The work ledger and the flow by source: one row per identified record, and the PRISMA counts
aggregated per source group.

Invariants: read-only (nothing is written); the ledger holds every canonical work and every
absorbed duplicate once; outcomes come from the functions `prisma_flow` uses, so the counts
reconcile with it (`ledger_reconciles`). Screening counts run over canonical rows only. Full-text
counts run over every row on the full-text queue, because the queue can hold a work merged after
its promotion (`noncanonical_promoted`), which `full_text_boxes` counts too.
"""

from collections.abc import Collection
from dataclasses import dataclass, field, fields
from typing import Literal

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.model.work import ProvenanceMethod, Work
from factory.services.agreement import (
    Outcome,
    cannot_assess_open,
    exclusion_criteria,
    final_outcomes,
)
from factory.services.context import Project
from factory.services.dedup import active_merges, canonical_works
from factory.services.fulltext_screening import fulltext_queue
from factory.services.fulltext_status import fulltext_status
from factory.services.prisma import UNSPECIFIED, full_text_boxes, prisma_flow
from factory.services.search import list_works

OTHER_GROUP = "other"
TOTAL = "total"
FtState = Literal["retrieved", "attempted-failed", "not-sought"]


class LedgerRow(StrictModel):
    """One identified record. `canonical_id` and `merge_rule` are set on an absorbed duplicate."""

    work_id: str
    title: str
    year: int | None
    source_group: str
    sources: list[str]
    query_ids: list[str]
    run_ids: list[str]
    canonical_id: str | None
    merge_rule: str | None
    ta_outcome: Outcome | None
    ta_criterion: str | None
    ft_state: FtState | None
    ft_reasons: list[str]
    ft_outcome: Literal["included", "excluded", "pending", "awaiting"] | None
    ft_criterion: str | None
    noncanonical_promoted: bool


class FlowCounts(StrictModel):
    """The PRISMA counts of one source group. `ft_*` count promoted works; `ft_retrieved` counts
    works with a live document, converted or not."""

    screened: int = 0
    ta_excluded: dict[str, int] = Field(default_factory=dict)
    ta_included: int = 0
    ta_pending: int = 0
    ft_not_sought: int = 0
    ft_attempted_failed: int = 0
    ft_retrieved: int = 0
    ft_excluded: dict[str, int] = Field(default_factory=dict)
    ft_included: int = 0
    ft_pending: int = 0
    ft_awaiting: int = 0
    ft_included_noncanonical: int = 0


@dataclass
class _Acc:
    """Mutable tally behind a `FlowCounts` (the model is frozen)."""

    screened: int = 0
    ta_excluded: dict[str, int] = field(default_factory=dict)
    ta_included: int = 0
    ta_pending: int = 0
    ft_not_sought: int = 0
    ft_attempted_failed: int = 0
    ft_retrieved: int = 0
    ft_excluded: dict[str, int] = field(default_factory=dict)
    ft_included: int = 0
    ft_pending: int = 0
    ft_awaiting: int = 0
    ft_included_noncanonical: int = 0

    def add(self, other: "_Acc") -> None:
        for f in fields(self):
            mine, theirs = getattr(self, f.name), getattr(other, f.name)
            if isinstance(mine, dict):
                for key, n in theirs.items():
                    mine[key] = mine.get(key, 0) + n
            else:
                setattr(self, f.name, mine + theirs)

    def freeze(self) -> FlowCounts:
        return FlowCounts(**{f.name: getattr(self, f.name) for f in fields(self)})


def source_group(database_sources: Collection[str]) -> str:
    """The group of a record from the database sources that found it: `arxiv-only`,
    `openalex-only`, `both` (arxiv and openalex), `other` when no database source found it, and
    otherwise the sorted sources joined with `+`."""
    sources = sorted(set(database_sources))
    if not sources:
        return OTHER_GROUP
    if sources == ["arxiv"]:
        return "arxiv-only"
    if sources == ["openalex"]:
        return "openalex-only"
    if sources == ["arxiv", "openalex"]:
        return "both"
    return "+".join(sources)


def _group_of(work: Work) -> str:
    return source_group(
        {p.source for p in work.provenance if p.method is ProvenanceMethod.DATABASE}
    )


def flow_ledger(project: Project) -> list[LedgerRow]:
    """One row per canonical work and per absorbed duplicate, sorted by work id."""
    project.index.sync()
    raw = {work.id: work for work in list_works(project)}
    canonical = {work.id: work for work in canonical_works(project)}
    merges = active_merges(project)
    absorbed_by = {a: (m.primary, m.rule) for m in merges for a in m.absorbed}
    ta = final_outcomes(project)
    ta_criteria = exclusion_criteria(project)

    boxes = full_text_boxes(project)
    queue = fulltext_queue(project)
    eligible = {e.work_id for e in queue.eligible}
    promoted = eligible | set(queue.not_retrieved)
    states = {entry.work_id: entry for entry in fulltext_status(project).works}
    ft = ScreeningStage.FULL_TEXT
    ft_outcomes = final_outcomes(project, stage=ft) if boxes.stage_run else {}
    ft_criteria = exclusion_criteria(project, stage=ft) if boxes.stage_run else {}
    unresolved = set(cannot_assess_open(project, stage=ft)) if boxes.stage_run else set()

    rows: list[LedgerRow] = []
    for work_id in sorted(set(canonical) | set(absorbed_by) | promoted):
        work = canonical.get(work_id) or raw.get(work_id)
        if work is None:
            continue
        primary, rule = absorbed_by.get(work_id, (None, None))
        outcome = ta.get(work_id)
        ft_state: FtState | None = None
        reasons: list[str] = []
        ft_outcome: Literal["included", "excluded", "pending", "awaiting"] | None = None
        if work_id in promoted:
            entry = states.get(work_id)
            if work_id in eligible or (entry is not None and entry.state == "retrieved"):
                ft_state = "retrieved"
            elif entry is not None and entry.state == "not-retrieved":
                ft_state = "attempted-failed"
                reasons = sorted(f"{r.value}: {why}" for r, why in entry.reasons.items())
            else:
                ft_state = "not-sought"
            if work_id in eligible and boxes.stage_run:
                if work_id in unresolved:
                    ft_outcome = "awaiting"
                else:
                    got = ft_outcomes.get(work_id, Outcome.PENDING)
                    ft_outcome = got.value
        rows.append(
            LedgerRow(
                work_id=work_id,
                title=work.title,
                year=work.dates.year,
                source_group=_group_of(work),
                sources=sorted({p.source for p in work.provenance}),
                query_ids=sorted({p.query_id for p in work.provenance}),
                run_ids=sorted({p.run_id for p in work.provenance}),
                canonical_id=primary,
                merge_rule=rule,
                ta_outcome=outcome,
                ta_criterion=(ta_criteria.get(work_id) or UNSPECIFIED)
                if outcome is Outcome.EXCLUDED
                else None,
                ft_state=ft_state,
                ft_reasons=reasons,
                ft_outcome=ft_outcome,
                ft_criterion=(ft_criteria.get(work_id) or UNSPECIFIED)
                if ft_outcome == "excluded"
                else None,
                noncanonical_promoted=ft_state is not None and work_id not in canonical,
            )
        )
    return rows


def _bump(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def flow_by_source(project: Project) -> dict[str, FlowCounts]:
    """The PRISMA counts per source group, with a `total` key over every group."""
    groups: dict[str, _Acc] = {}
    for row in flow_ledger(project):
        counts = groups.setdefault(row.source_group, _Acc())
        if not row.noncanonical_promoted and row.canonical_id is None:
            counts.screened += 1
            if row.ta_outcome is Outcome.INCLUDED:
                counts.ta_included += 1
            elif row.ta_outcome is Outcome.EXCLUDED:
                _bump(counts.ta_excluded, row.ta_criterion or UNSPECIFIED)
            else:
                counts.ta_pending += 1
        if row.ft_state == "not-sought":
            counts.ft_not_sought += 1
        elif row.ft_state == "attempted-failed":
            counts.ft_attempted_failed += 1
        elif row.ft_state == "retrieved":
            counts.ft_retrieved += 1
        if row.ft_outcome == "included":
            counts.ft_included += 1
            counts.ft_included_noncanonical += row.noncanonical_promoted
        elif row.ft_outcome == "excluded":
            _bump(counts.ft_excluded, row.ft_criterion or UNSPECIFIED)
        elif row.ft_outcome == "pending":
            counts.ft_pending += 1
        elif row.ft_outcome == "awaiting":
            counts.ft_awaiting += 1
    total = _Acc()
    for counts in groups.values():
        total.add(counts)
    result = {key: groups[key].freeze() for key in sorted(groups)}
    result[TOTAL] = total.freeze()
    return result


def ledger_reconciles(project: Project) -> list[str]:
    """Mismatches between the ledger totals and `prisma_flow`; empty when they agree."""
    total = flow_by_source(project)[TOTAL]
    flow = prisma_flow(project)
    boxes = flow.full_text
    pairs: list[tuple[str, object, object]] = [
        ("screened", total.screened, flow.screened),
        ("title/abstract included", total.ta_included, flow.included),
        ("title/abstract pending", total.ta_pending, flow.pending),
        ("title/abstract excluded", dict(sorted(total.ta_excluded.items())), flow.excluded),
        ("full-text included", total.ft_included, boxes.included),
        ("full-text pending", total.ft_pending, boxes.pending),
        ("full-text excluded", dict(sorted(total.ft_excluded.items())), boxes.excluded),
    ]
    return [
        f"{name}: ledger {ours} != prisma {theirs}"
        for name, ours, theirs in pairs
        if ours != theirs
    ]
