"""Result models of the technique landscape (IDEA-78, plan 2026-11-18-technique-graph).

Every model here is a derived, read-time reading of rows the technique miners recorded: nothing
is stored. Invariants: every node and edge carries `class = interpretation` and a `state`
(`exploratory`; `accepted` exists for a later recorded decision and nothing sets it now); every
result carries `exploratory = True` and the notice. A count is a number of works with a current
pass-A row in the named lens, never a figure for a report. Serialise with `by_alias=True` so the
`class` key is written.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from factory.model.base import StrictModel

NOTICE = (
    "exploratory: uncalibrated miners, pass A, interpretation layer, not evidence; "
    "not found in this corpus is not absent from the field; no figure here enters a report"
)
CORPUS_SENTENCE = (
    "Counts are works of this corpus with a current pass-A row of the stage's technique miner "
    "in the named lens; a technique not found here may exist outside the corpus."
)
CANDIDATE_SENTENCE = "hypothesis to check against the verified quotes, never a finding"
EVIDENCE_LEVELS = (
    "independent-test",
    "own-ablation",
    "own-comparison",
    "asserted-only",
    "reported-failure",
)
NOT_STATED = "not-stated"
SUPPORTIVE = ("independent-test", "own-ablation", "own-comparison")


class Labelled(StrictModel):
    """A node or an edge of the derived layer."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    klass: Literal["interpretation"] = Field("interpretation", alias="class")
    state: Literal["exploratory", "accepted"] = "exploratory"


class Lens(StrictModel):
    """The filter a result was computed under; named in every result."""

    layer: str = "core"
    stage: str | None = None
    evidence: str | None = None
    status: str | None = None
    min_co_works: int = 2
    rows: Literal["pass-A"] = "pass-A"


class Approach(Labelled):
    """A node: one category of a stage's technique taxonomy (UI word: approach)."""

    id: str
    stage: str
    name: str
    definition: str
    works: int
    rows: int
    by_evidence: dict[str, int]
    by_status: dict[str, int]
    kind: Literal["technique"] = "technique"


class WorkNode(Labelled):
    id: str
    title: str
    year: int | None
    date: str | None
    layer: str | None
    kind: Literal["work"] = "work"


class Edge(Labelled):
    """`co-used-with` (approach, approach; weight and works), `derives-from` (work, work; candidate,
    `approach` names the technique, `basis` the reference link), `earliest-in-corpus` (approach,
    work; a date rule, not an origin claim), `uses` (work, approach)."""

    kind: Literal["co-used-with", "derives-from", "earliest-in-corpus", "uses"]
    source: str
    target: str
    approach: str | None = None
    weight: int = 1
    works: tuple[str, ...] = ()
    basis: str | None = None
    note: str | None = None


class UseRow(Labelled):
    """One miner row: the evidence node of a `uses` edge. Quote and anchor are the verified ones."""

    approach: str
    stage: str
    work_id: str
    extraction_id: str
    status: str
    evidence: str
    described_as: str | None
    quote: str | None
    anchor: str | None
    parameters: str | None = None


class StageSummary(StrictModel):
    stage: str
    miner: str
    version: int
    approaches: int
    works: int
    rows: int
    residual_rows: int
    no_evidence_share: float | None
    agreement: float | None
    agreement_aligned: float | None
    agreement_note: str


class Landscape(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    klass: Literal["interpretation"] = Field("interpretation", alias="class")
    exploratory: Literal[True] = True
    notice: str = NOTICE
    corpus: str = CORPUS_SENTENCE
    lens: Lens
    stages: tuple[StageSummary, ...]
    approaches: tuple[Approach, ...]
    edges: tuple[Edge, ...]
    edges_omitted: int = 0
    undated_works: tuple[str, ...] = ()
    cross_stage_note: str = (
        "an approach that two stage taxonomies both hold is two nodes here (decision 127, Q7)"
    )


class ApproachView(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    klass: Literal["interpretation"] = Field("interpretation", alias="class")
    exploratory: Literal[True] = True
    notice: str = NOTICE
    lens: Lens
    approach: Approach
    works: tuple[WorkNode, ...]
    uses: tuple[UseRow, ...]
    derives_from: tuple[Edge, ...]
    earliest: Edge | None
    undated_works: tuple[str, ...]
    not_stated_share: float | None


class CoUse(StrictModel):
    approach: Approach
    weight: int
    works: tuple[str, ...]


class StageReach(StrictModel):
    stage: str
    works: int


class Neighbors(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    klass: Literal["interpretation"] = Field("interpretation", alias="class")
    exploratory: Literal[True] = True
    notice: str = NOTICE
    lens: Lens
    approach: Approach
    co_used: tuple[CoUse, ...]
    stages: tuple[StageReach, ...]
    works: tuple[str, ...]
    derives_from: tuple[Edge, ...]


class Score(StrictModel):
    """The components of a ranking score, each in 0..1 (`popularity_raw` and `bridge_links` are the
    counts they come from), the weights used and the composite. Nothing here is a probability or a
    measure of novelty: it orders a list of hypotheses to check. Components that do not apply to a
    kind are None. `flags` name pairs to judge by hand (e.g. `same-name-across-stages`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rank_by: str
    value: float
    popularity: float
    popularity_raw: int
    stage: float | None = None
    stage_relation: str | None = None
    strength: float | None = None
    bridge: float
    bridge_links: int
    evidence: float | None = None
    generic: float | None = None
    composite: float
    weights: dict[str, float]
    flags: tuple[str, ...] = ()


class GapCandidate(StrictModel):
    approach: Approach
    from_stage: str
    to_stage: str
    works: tuple[str, ...]
    works_with_to_stage: tuple[str, ...]
    statement: str
    label: str = CANDIDATE_SENTENCE
    rank: int = 0
    score: Score | None = None
    quote: UseRow | None = None


class CombinationCandidate(StrictModel):
    a: Approach
    b: Approach
    co_works: tuple[str, ...]
    works_a: int
    works_b: int
    statement: str
    label: str = CANDIDATE_SENTENCE
    rank: int = 0
    score: Score | None = None
    support_a: tuple[str, ...] = ()
    support_b: tuple[str, ...] = ()
    quote_a: UseRow | None = None
    quote_b: UseRow | None = None


class ChallengeCandidate(StrictModel):
    approach: Approach
    failed: tuple[UseRow, ...]
    supported: tuple[UseRow, ...]
    statement: str
    label: str = CANDIDATE_SENTENCE


class Candidates(StrictModel):
    """Gap, combination or challenge candidates of one lens; `total` is before the `limit`."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    klass: Literal["interpretation"] = Field("interpretation", alias="class")
    exploratory: Literal[True] = True
    notice: str = NOTICE
    kind: Literal["gaps", "combinations", "challenges"]
    lens: Lens
    parameters: dict[str, str | int | float | None]
    total: int
    gaps: tuple[GapCandidate, ...] = ()
    combinations: tuple[CombinationCandidate, ...] = ()
    challenges: tuple[ChallengeCandidate, ...] = ()
