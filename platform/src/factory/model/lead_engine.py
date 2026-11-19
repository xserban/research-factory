"""Result models of the hypothesis engine's candidate and queue layer (job J2; plan
2026-11-19-hypothesis-engine-techniques, tasks 1, 2 and 5).

Everything here is a derived, read-time reading of rows other services recorded: nothing is stored
and no event type, table or trigger kind is added. Invariants: a candidate is an observation, never
a lead and never a claim of novelty; every result carries `class = interpretation`,
`exploratory = True` and the notice; a candidate's `triggers` are exactly the list a `lead_record`
call accepts (`item` of live, non-stale miner rows and `work`; never `row` for a miner row, whose
`rk_` key does not resolve as a trigger); every measure is computed from recorded rows, and a
score is comparable only with the others of the same call. Serialise with `by_alias=True` so the
`class` key is written.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from factory.model.base import StrictModel
from factory.model.technique_graph import NOTICE as TECHNIQUE_NOTICE

__all__ = [
    "BASIS_STATES",
    "DEFAULT_ORDER",
    "MAX_TRIGGERS_PER_CANDIDATE",
    "MEASURES",
    "NOTICE",
    "SOURCES",
    "BasisRow",
    "Candidate",
    "CandidateQuote",
    "CandidateTrigger",
    "CandidateWork",
    "Candidates",
    "LeadStats",
    "Measures",
    "OldestLead",
    "PriorHit",
    "Queue",
    "QueueItem",
    "Skipped",
    "Verification",
]

NOTICE = (
    f"{TECHNIQUE_NOTICE}; a candidate is an observation to check against its quotes, "
    "not a lead and not a claim of novelty"
)
SOURCES = (
    "technique-challenge",
    "technique-combination",
    "technique-gap",
    "claims-limitation",
)
Source = Literal[
    "technique-challenge", "technique-combination", "technique-gap", "claims-limitation"
]
MAX_TRIGGERS_PER_CANDIDATE = 20
"""A lead holds at most 20 triggers (`model.hypotheses.MAX_TRIGGERS`)."""
MEASURES = (
    "support",
    "independence",
    "verification",
    "supportive_share",
    "overlap",
    "diversity",
    "prior_hits",
    "score",
    "basis",
)
"""The measures an order may name: M1 support, M2 independence, M3 verification, M4 supportive
share, M5 overlap, M6 diversity, M7 prior hits, M8 score, M9 basis (live rows first)."""
DEFAULT_ORDER = ("prior_hits", "independence", "support", "verification", "diversity", "score")
"""Fewest prior hits first, then most independent works, most supporting works, highest share of
verified quotes, most different from the promoted leads, highest source score; ties by id."""
BASIS_STATES = ("live", "stale", "superseded", "unknown")


class _Labelled(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    klass: Literal["interpretation"] = Field("interpretation", alias="class")
    exploratory: Literal[True] = True


class CandidateTrigger(StrictModel):
    """One trigger as `lead_record` takes it: `{"kind": "item"|"work", "ref": ...}`."""

    kind: Literal["item", "work"]
    ref: str


class CandidateWork(StrictModel):
    work_id: str
    title: str


class CandidateQuote(StrictModel):
    """A verbatim quote of a cited row with its anchor; `role` names the side it supports
    (`failed`, `supported`, `a`, `b`, `from-stage`, `limitation`)."""

    role: str
    work_id: str
    extraction_id: str
    quote: str
    anchor: str | None


class BasisRow(StrictModel):
    """A row a candidate rests on: the `item` trigger's extraction id."""

    extraction_id: str
    work_id: str
    role: str


class Candidate(_Labelled):
    """One observation. `observation` never claims novelty. `works` are the cited works (at most
    ten); `works_total` is every work the observation counts. `triggers` are exactly what a lead
    recorded from it would cite (at most 20); `trigger_note` states a cut. `overlap_works` counts
    corpus works whose rows already state the observed combination (None for claims); `score` is
    the technique rank composite where it exists (None for challenges and claims)."""

    candidate_id: str
    source: Source
    observation: str
    approaches: tuple[str, ...] = ()
    works: tuple[CandidateWork, ...]
    works_total: int
    quotes: tuple[CandidateQuote, ...]
    triggers: tuple[CandidateTrigger, ...]
    basis: tuple[BasisRow, ...]
    trigger_note: str | None = None
    miners: tuple[str, ...]
    overlap_works: int | None = None
    score: float | None = None


class Skipped(StrictModel):
    """A candidate not offered, with why (never dropped silently)."""

    candidate_id: str
    reason: str


class Candidates(_Labelled):
    """The candidates of one call: `totals` is the number each source produced before `per_source`
    capped it; `absence_only_works` counts works whose only m-claims rows state no limitation
    (counted, never a trigger)."""

    notice: str = NOTICE
    parameters: dict[str, str | int | float | tuple[str, ...] | None]
    totals: dict[str, int]
    candidates: tuple[Candidate, ...]
    skipped: tuple[Skipped, ...] = ()
    miners: tuple[str, ...] = ()
    absence_only_works: int = 0


class Verification(StrictModel):
    """M3: the cited rows whose quote is verbatim in the row's pinned conversion."""

    verified: int
    total: int
    share: float | None


class PriorHit(StrictModel):
    """M7: an earlier parked or discarded lead, a hypothesis or a direction sharing keys. A hit on
    a shared `item` is narrow; one on works only is broad (two leads citing the same work always
    collide)."""

    kind: Literal["lead", "hypothesis", "direction"]
    id: str
    detail: str | None
    shared_items: tuple[str, ...]
    shared_works: tuple[str, ...]


class Measures(StrictModel):
    """The computed measures of one queue entry (see `MEASURES`). `diversity` is 1 minus the
    largest Jaccard of the entry's item ids and approaches with a promoted lead's (1.0 with none),
    shared works never count (B4); `diversity_vs` names that lead."""

    support: int
    independence: int
    verification: Verification
    supportive_share: float | None
    overlap: int | None
    diversity: float
    diversity_vs: str | None
    prior_hits: int
    narrow_prior_hits: int
    closed_direction_hit: bool
    score: float
    score_flag: str | None
    basis: Literal["live", "stale", "superseded", "unknown"]


class QueueItem(_Labelled):
    """A candidate or an open lead with its measures. `rank` is 1-based within `Queue.items` or
    `Queue.leads`. A candidate whose rows are not all live is flagged and sorted last."""

    kind: Literal["candidate", "lead"]
    entry_id: str
    source: str
    rank: int
    measures: Measures
    prior: tuple[PriorHit, ...]
    flags: tuple[str, ...]
    stale_refs: tuple[str, ...] = ()
    candidate: Candidate | None = None


class Queue(_Labelled):
    notice: str = NOTICE
    order_by: tuple[str, ...]
    order_rule: str
    comparability: str
    parameters: dict[str, str | int | float | tuple[str, ...] | None]
    items: tuple[QueueItem, ...]
    leads: tuple[QueueItem, ...]
    total_candidates: int
    excluded: tuple[Skipped, ...] = ()


class OldestLead(StrictModel):
    lead_id: str
    framework: str | None
    triggers: int
    source: str
    event_id: str


class LeadStats(StrictModel):
    """Counts computed from the lead, hypothesis, review, registration and evaluation tables.
    `recorded` is every lead; `by_state` has `open`, `promoted`, `parked`, `discarded`.
    `promotion_rate` is promoted over recorded and `decided_promotion_rate` promoted over decided
    (None without a denominator). `by_source` counts leads by the source of their `item` triggers
    (`technique`, `claims`, `other-miner`, `rows`, `none`, `mixed`), each with its states."""

    recorded: int
    by_state: dict[str, int]
    decided: int
    promotion_rate: float | None
    decided_promotion_rate: float | None
    discard_reasons: dict[str, int]
    by_trigger_kind: dict[str, int]
    by_source: dict[str, dict[str, int]]
    hypotheses_drafted: int
    hypotheses_by_state: dict[str, int]
    hypotheses_registered: int
    hypotheses_closed: dict[str, int]
    reviews: int
    reviews_by_recommendation: dict[str, int]
    outcomes: dict[str, int]
    oldest_undecided: tuple[OldestLead, ...]
    notice: str = (
        "counts of recorded work, computed; a promotion share is a use figure, not a quality figure"
    )
