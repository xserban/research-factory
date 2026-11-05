"""Rows and the event of a digest (slice 4b, plan living-D).

A digest is a builder's output: computed facts since a cut-off, with no verdict, no abstract and
no quotation. These are its value types; the assembling type `Digest` (which holds an update flow)
lives in `factory.services.digest`. `digest.generated` is the system event a recorded digest
writes, one per project.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.watch import CycleStatus, SourceCounts

DIG_ID_RE = rf"^dig_{ULID_RE}$"

T = TypeVar("T")


class Listing(StrictModel, Generic[T]):
    """A capped listing: the first `items` and how many more there are."""

    items: tuple[T, ...] = ()
    more: int = Field(default=0, ge=0)


class CandidateRow(StrictModel):
    """A work new since the cut-off: its bibliographic title, the queries that returned it in the
    window and the route it first came by. No abstract, no score."""

    work_id: str
    title: str
    query_ids: tuple[str, ...]
    route: str


class NoticeRow(StrictModel):
    """A notice observed since the cut-off; `assessed` says whether a human has assessed it."""

    notice_id: str
    work_id: str
    kind: str
    notice_date: str | None
    source: str
    assessed: bool


class VersionRow(StrictModel):
    """A version fact observed since the cut-off: a newer version on a route, or a linked
    published version (identifiers only)."""

    work_id: str
    kind: Literal["newer-version", "version-of-record"]
    detail: str


class CycleSummaryRow(StrictModel):
    """A watch cycle started since the cut-off, with its computed per-source counts."""

    cycle_id: str
    status: CycleStatus
    started_at: str
    counts: tuple[SourceCounts, ...]


class DigestGenerated(StrictModel):
    """A recorded digest of one project (system). `blob` holds the canonical JSON and
    `markdown_blob` the Markdown; `counts` are computed from the digest."""

    digest_id: str = Field(pattern=DIG_ID_RE)
    project: str = Field(min_length=1)
    since_event: str | None = None
    cutoff_event: str = Field(min_length=1)
    blob: str = Field(pattern=BLOB_REF_RE)
    markdown_blob: str = Field(pattern=BLOB_REF_RE)
    counts: dict[str, int]
