"""Events of the discovery feed (slice 4c, decision 118): `feed.*`.

A feed entry is an arXiv listing item kept in the feed store. It is not a corpus record: it is
outside the corpus, PRISMA, dedup and screening until a human sends it, and then only through the
inbox and the `supplied` lookup. Entry ids are arXiv ids without version.

`feed.configured`, `feed.reacted` and `feed.sent` are human acts. The service refuses a non-human
actor and the fold ignores an agent-written one. `feed.fetched` and `feed.ranked` are system
events; a ranking records model, weight hash, reference-set hash, parameters and exploration seed,
so that it can be reproduced from events. Pure value types; written by `factory.services.feed`.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.inbox import INBOX_ID_RE, MAX_NOTE  # a sent note becomes the inbox note
from factory.model.screening import NonBlank
from factory.model.work_ids import WORK_ID_RE

FEED_CONFIG_ID_RE = rf"^fdc_{ULID_RE}$"
FEED_FETCH_ID_RE = rf"^fdf_{ULID_RE}$"
FEED_RANKING_ID_RE = rf"^fdr_{ULID_RE}$"
FEED_CATEGORY_RE = r"^[a-z\-]+(\.[A-Za-z\-]+)?$"
# arXiv id without version: new style `2401.01234`, old style `hep-th/9901001`.
FEED_ENTRY_RE = r"^(\d{4}\.\d{4,5}|[a-z\-]+(\.[A-Z]{2})?/\d{7})$"

BlobRef = Annotated[str, StringConstraints(pattern=BLOB_REF_RE)]
Category = Annotated[str, StringConstraints(pattern=FEED_CATEGORY_RE)]
EntryId = Annotated[str, StringConstraints(pattern=FEED_ENTRY_RE)]
FeedNote = Annotated[NonBlank, Field(max_length=MAX_NOTE)]


def _no_duplicates(categories: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(categories)) != len(categories):
        raise ValueError("categories must not repeat")
    return categories


class FeedReferences(StrEnum):
    CORE = "core"
    CORE_INCLUDED = "core+included"
    CORE_LAYER = "core-layer"
    """The works whose current layer is `core` (the researcher's move, else the layer miner)."""


class FeedReaction(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"
    SAVE = "save"
    DISMISS = "dismiss"


class FeedConfigured(StrictModel):
    config_id: str = Field(pattern=FEED_CONFIG_ID_RE)
    categories: tuple[Category, ...] = Field(min_length=1)
    references: FeedReferences = FeedReferences.CORE
    shown_per_cycle: int = Field(default=100, ge=1)
    exploration_share: float = Field(default=0.1, ge=0, lt=1)
    interval_days: int = Field(default=1, ge=1)
    overlap_days: int = Field(default=2, ge=0)
    drift_threshold: float = Field(default=0.5, gt=0, le=1)
    drift_min_count: int = Field(default=10, ge=1)

    @field_validator("categories")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _no_duplicates(value)


class FeedFetched(StrictModel):
    """One fetch of an arXiv category listing over a submission-date window. `held_count` entries
    were dropped because their work is already in the corpus (held-out seeds included)."""

    fetch_id: str = Field(pattern=FEED_FETCH_ID_RE)
    source: Literal["arxiv"] = "arxiv"
    categories: tuple[Category, ...] = Field(min_length=1)
    window_from: date
    window_to: date
    raw_blobs: tuple[BlobRef, ...]
    entries_blob: BlobRef
    count: int = Field(ge=0)
    held_count: int = Field(ge=0)
    complete: bool

    @field_validator("categories")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _no_duplicates(value)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.window_from > self.window_to:
            raise ValueError("window_from must not be after window_to")
        if self.held_count > self.count:
            raise ValueError("held_count must not exceed count")
        return self


class FeedRankParameters(StrictModel):
    shown_per_cycle: int = Field(ge=1)
    exploration_share: float = Field(ge=0, lt=1)
    references: FeedReferences


class FeedShown(StrictModel):
    entry_id: EntryId
    rank: int = Field(ge=1)
    score: float
    explore: bool
    nearest_reference: Annotated[str, StringConstraints(pattern=WORK_ID_RE)] | None = None


class FeedRanked(StrictModel):
    ranking_id: str = Field(pattern=FEED_RANKING_ID_RE)
    fetch_ids: tuple[Annotated[str, StringConstraints(pattern=FEED_FETCH_ID_RE)], ...]
    reference_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_count: int = Field(ge=0)
    model: str = Field(min_length=1)
    weights_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    software: str = Field(min_length=1)
    parameters: FeedRankParameters
    exploration_seed: int
    order_blob: BlobRef
    shown: tuple[FeedShown, ...]


class FeedReacted(StrictModel):
    entry_id: EntryId
    reaction: FeedReaction
    ranking_id: str = Field(pattern=FEED_RANKING_ID_RE)
    rank_shown: int = Field(ge=1)
    score_shown: float
    beyond_shown: bool = False


class FeedSent(StrictModel):
    entry_id: EntryId
    ranking_id: str = Field(pattern=FEED_RANKING_ID_RE)
    inbox_item_id: str = Field(pattern=INBOX_ID_RE)
    note: FeedNote | None = None
    beyond_shown: bool = False
