"""Search vocabulary shared by source adapters, services and events.

Event payloads for search runs and queries are added alongside the services that emit them.
This module holds only the value types the source contract is written against.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE
from factory.model.work import QUERY_ID_RE, RUN_ID_RE, Work


class QueryKind(StrEnum):
    """How a source is asked: free-text keywords, a source-native filter, or explicit IDs."""

    KEYWORD = "keyword"
    FILTER = "filter"
    ID_LIST = "id_list"


class QueryPurpose(StrEnum):
    """Why a query is being run: a probe, a search, a citation chase, a seed or a supplied link."""

    PROBE = "probe"
    SEARCH = "search"
    CHASE = "chase"
    SEED = "seed"
    SUPPLIED = "supplied"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class QuerySpec(StrictModel):
    """One request to one source, as the caller states it before any adapter touches it."""

    source: str
    kind: QueryKind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    purpose: QueryPurpose = QueryPurpose.SEARCH
    filters: dict[str, str] = Field(default_factory=dict)
    limit: int | None = Field(default=None, ge=1)


# --- Event payloads (schema 1). Written by `factory.services.search`, folded by `index.search`.


class QueryRegistered(StrictModel):
    query_id: str = Field(pattern=QUERY_ID_RE)
    spec: QuerySpec
    interface: str


class SearchRunStarted(StrictModel):
    run_id: str = Field(pattern=RUN_ID_RE)
    query_id: str = Field(pattern=QUERY_ID_RE)
    resume_of: str | None = Field(default=None, pattern=RUN_ID_RE)
    resume_from: str | None = None


class SearchPageArchived(StrictModel):
    run_id: str = Field(pattern=RUN_ID_RE)
    ordinal: int = Field(ge=0)
    url: str
    fetched_at: AwareDatetime
    raw_blob: str = Field(pattern=BLOB_REF_RE)


class SearchRecordsParsed(StrictModel):
    run_id: str = Field(pattern=RUN_ID_RE)
    raw_blob: str = Field(pattern=BLOB_REF_RE)
    records: tuple[Work, ...]


class SearchRunFinished(StrictModel):
    run_id: str = Field(pattern=RUN_ID_RE)
    status: RunStatus
    reported_count: int | None = Field(default=None, ge=0)
    retrieved_count: int = Field(ge=0)
    skipped: int = Field(default=0, ge=0)
    note: str | None = None
    resume_token: str | None = None

    @model_validator(mode="after")
    def _finished_status_is_explained(self) -> SearchRunFinished:
        if self.status not in {RunStatus.COMPLETE, RunStatus.PARTIAL, RunStatus.FAILED}:
            raise ValueError("a finished run is complete, partial or failed")
        has_note = self.note is not None and bool(self.note.strip())
        shortfall = self.reported_count is not None and self.retrieved_count < self.reported_count
        if not has_note and (self.status is not RunStatus.COMPLETE or shortfall):
            raise ValueError("a run that is not fully explained needs a note (R-23)")
        return self
