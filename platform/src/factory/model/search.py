"""Search vocabulary shared by source adapters, services and events.

Event payloads for search runs and queries are added alongside the services that emit them.
This module holds only the value types the source contract is written against.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints

from factory.model.base import StrictModel


class QueryKind(StrEnum):
    """How a source is asked: free-text keywords, a source-native filter, or explicit IDs."""

    KEYWORD = "keyword"
    FILTER = "filter"
    ID_LIST = "id_list"


class QueryPurpose(StrEnum):
    """Why a query is being run: a feasibility probe, a search, a citation chase, or a seed."""

    PROBE = "probe"
    SEARCH = "search"
    CHASE = "chase"
    SEED = "seed"


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
