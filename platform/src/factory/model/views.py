"""Read models of the views (slice 7b, plan V-A).

Invariants:
- Every view carries a `ViewMeta`: its name and version, the project, the filter it applied, the
  log position it was built at (`as_of`), whether any list was cut, and its notices.
- A view is a value computed from the log; it is never stored and never written as an event.
- An onion ring states its complete `total` and `by_depth` whatever its node list shows; a node
  list is cut only by `truncated`, which says so.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from factory.model.base import StrictModel

ProcessingDepth = Literal["indexed", "screened", "extracted", "verified"]
OnionEdgeType = Literal["cites", "builds-on", "improves-on"]


class ViewNotice(StrictModel):
    code: str
    text: str


class ViewMeta(StrictModel):
    view: str
    version: int
    project: str
    as_of: str | None
    filter: dict[str, JsonValue]
    truncated: bool = False
    notices: list[ViewNotice] = Field(default_factory=list)


class OnionFilter(StrictModel):
    """What the onion shows: rings up to `max_ring` around the included works (or `focus`) over
    the named edge types, in the default status filter (stated, confirmed) unless
    `include_inferred`."""

    max_ring: int = 2
    edge_types: tuple[OnionEdgeType, ...] = ("cites", "builds-on", "improves-on")
    include_inferred: bool = False
    focus: tuple[str, ...] | None = None


class OnionNode(StrictModel):
    work_id: str
    title: str
    year: int | None
    depth: ProcessingDepth
    scope: Literal["corpus", "external"]
    ideas: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)


class Ring(StrictModel):
    distance: int
    total: int
    by_depth: dict[str, int]
    nodes: list[OnionNode]
    truncated: bool


class OnionView(StrictModel):
    meta: ViewMeta
    rings: list[Ring]
    edges_considered: dict[str, int]


class GroupSummary(StrictModel):
    """One comparability group: its id (`grp_` and a hash of the key), the key pairs, and counts.
    `rows` = `independent` + `copied` + rows without a `value` field; no value appears here."""

    group_id: str
    key: list[tuple[str, str]]
    works: int
    rows: int
    independent: int
    copied: int


class CoverageCell(StrictModel):
    """Counts only, never a value (spec ruling 5; decision 41)."""

    independent: int
    copied: int
    works: int


class CoverageView(StrictModel):
    """The methods x comparability-group matrix of final evidence rows, and the confirmed ideas x
    group matrix from contribution `result_row` links. `cells[method][group_id]` is absent where
    the method has no row in the group. `total_groups` / `total_methods` / `total_ideas` are the
    complete counts whatever the lists show."""

    meta: ViewMeta
    groups: list[GroupSummary]
    methods: list[str]
    cells: dict[str, dict[str, CoverageCell]]
    ideas: list[str]
    idea_cells: dict[str, dict[str, CoverageCell]]
    total_groups: int
    total_methods: int
    total_ideas: int


class RecordPoint(StrictModel):
    """A record row of one group and unit: its trace id (`rk_.../value`), work, year and value."""

    trace_id: str
    work_id: str
    row_key: str
    year: int
    value: str


class UnitTimeline(StrictModel):
    """The records and per-year frontiers of one value unit (and, when the group key does not fix
    them, one metric and one input resolution). `frontiers[year][axis]` lists trace ids."""

    unit: str | None
    metric: str | None
    resolution: str | None
    records: list[RecordPoint]
    frontiers: dict[int, dict[str, list[str]]]


class TimelineView(StrictModel):
    """The timeline of one comparability group; no value crosses groups or units. `direction` is
    the evidence report's direction status; `units` is empty unless it is `declared` or
    `pack-default`. `undated` lists the works of rows without a publication date."""

    meta: ViewMeta
    group_id: str
    key: list[tuple[str, str]]
    direction: str
    higher_is_better: bool | None
    units: dict[str, UnitTimeline]
    undated: list[str]


class HorizonView(StrictModel):
    """Activity series by publication year; counts and ids only. `idea_members[idea][year]`:
    included works of the confirmed idea (merged ideas through their survivor); `new_ideas[year]`:
    ideas whose origin work is of that year; `new_edges[year]`: stated or confirmed lineage edges
    by the citing work's year; `group_records[group][year]`: record rows (groups with a timeline
    only). `undated` counts items without a date, by series. `horizon[source]`: latest finished
    search or watch run date. No label and no bibliometric score is computed."""

    meta: ViewMeta
    years: list[int]
    idea_members: dict[str, dict[int, int]]
    new_ideas: dict[int, list[str]]
    new_edges: dict[int, int]
    group_records: dict[str, dict[int, int]]
    undated: dict[str, int]
    horizon: dict[str, str]
    total_ideas: int
    total_groups: int
