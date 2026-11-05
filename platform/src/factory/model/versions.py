"""Events about versions of a known work (slice 4b, living-C).

`version.observed`: a source states a newer version than the work's current document on a route;
nothing is fetched. `version.linked`: a source names a published version of a preprint work; the
published identifiers become aliases of the existing work (used by incremental deduplication), so
the two are linked, not merged away (R-26). A link whose identifier already belongs to a different
work is recorded with `conflicts_with` and applies nothing: it is a dedup question for a human.

Written by `factory.services.versions` (system actor); folded by `index.notices`.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.model.fulltext import Route
from factory.model.work import RUN_ID_RE, Identifiers
from factory.model.work_ids import WORK_ID_RE


class VersionObserved(StrictModel):
    work_id: str = Field(pattern=WORK_ID_RE)
    route: Route
    source_version: str = Field(min_length=1)
    run_id: str = Field(pattern=RUN_ID_RE)


class VersionLinked(StrictModel):
    work_id: str = Field(pattern=WORK_ID_RE)
    identifiers: Identifiers
    venue: str | None = None
    source: str = Field(min_length=1)
    run_id: str = Field(pattern=RUN_ID_RE)
    conflicts_with: str | None = Field(default=None, pattern=WORK_ID_RE)
    """The work that already holds one of `identifiers`; the link then applies nothing."""

    @model_validator(mode="after")
    def _names_an_identifier(self) -> VersionLinked:
        if not any(v is not None for v in self.identifiers.model_dump().values()):
            raise ValueError("a link names at least one published identifier")
        return self


class DocumentPreferred(StrictModel):
    """A human moves the extraction basis of a work to one of its live documents.

    `automatic` is set by the service when the named document is the one the automatic route
    order would serve anyway: the act then clears an earlier override instead of making one."""

    work_id: str = Field(pattern=WORK_ID_RE)
    document_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    automatic: bool = False
