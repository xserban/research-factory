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
