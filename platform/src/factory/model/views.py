"""Read models of the views (slice 7b, plan V-A).

Invariants:
- Every view carries a `ViewMeta`: its name and version, the project, the filter it applied, the
  log position it was built at (`as_of`), whether any list was cut, and its notices.
- A view is a value computed from the log; it is never stored and never written as an event.
"""

from __future__ import annotations

from pydantic import Field, JsonValue

from factory.model.base import StrictModel


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
