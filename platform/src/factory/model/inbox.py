"""Link inbox: captured links, their withdrawal and their resolution (slice 4a).

An inbox item is one captured link, parsed at capture to one identifier. Capture is offline and
never gated; resolution is a recorded `supplied`-purpose lookup. Written by
`factory.services.inbox`, folded by `factory.index.inbox`.

Invariants: `note` is human text of at most 300 characters and never reaches screening or
extraction content; `basis` is set for agent captures only (the service enforces who may give
which); a resolution names a work exactly when its status is `new` or `in-corpus`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from factory.inbox.links import MAX_LINK, IdentifierKind
from factory.model.base import StrictModel
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.protocol import DEVIATION_ID_RE
from factory.model.screening import Channel, NonBlank
from factory.model.work import QUERY_ID_RE, RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE

INBOX_ID_RE = rf"^inb_{ULID_RE}$"
MAX_NOTE = 300
MAX_ANCHOR = 200
MAX_MINER_NOTES = 600
HINT_LAYER_RE = r"^[a-z][a-z0-9-]{0,31}$"
"""The pattern of a layer id (the same as `factory.model.references.LAYER_ID_RE`)."""
HINT_CATEGORY_RE = r"^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$"
"""A full category id `dimension/category`."""
HINT_TAXONOMY_RE = r"^[a-z][a-z0-9-]*$"


class InboxRoute(StrEnum):
    """How an item reached the inbox; `link` is the only route in v1 (spec ruling 14)."""

    LINK = "link"


class Basis(StrictModel):
    """Why an agent proposes a link: a citing span it read, or outside knowledge.

    `document_id` and `anchor` are both set exactly when `kind` is `document`. `anchor` is a
    locator of the citing span (a section or anchor name), not a quote: the span is read from
    the document, and no check treats this text as what the document says.
    """

    kind: Literal["document", "knowledge"]
    document_id: str | None = Field(default=None, pattern=DOCUMENT_ID_RE)
    anchor: str | None = Field(default=None, min_length=1, max_length=MAX_ANCHOR)

    @model_validator(mode="after")
    def _document_fields(self) -> Self:
        located = self.document_id is not None and self.anchor is not None
        if self.kind == "document" and not located:
            raise ValueError("a document basis names both document_id and anchor")
        if self.kind == "knowledge" and (self.document_id is not None or self.anchor is not None):
            raise ValueError("a knowledge basis names no document_id or anchor")
        return self


class ResolveStatus(StrEnum):
    NEW = "new"
    IN_CORPUS = "in-corpus"
    NOT_FOUND = "not-found"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


FOUND_STATUSES = frozenset({ResolveStatus.NEW, ResolveStatus.IN_CORPUS})
"""Statuses that name exactly one work."""


class CaptureHints(StrictModel):
    """The researcher's hints at capture (IDEA-81): a layer of the layer scheme, a category of a
    taxonomy, and notes addressed to the miners. The researcher's label, with the actor and time of
    the capturing event; never a miner row and never read by screening.

    `layer` and `scheme_version` are set together (the scheme version current at capture);
    `category`, `taxonomy` and `taxonomy_version` are set together. A hint goes stale when its
    scheme or taxonomy version is no longer the latest (computed, never stored). At least one of
    layer, category and notes is set."""

    layer: Annotated[str, StringConstraints(pattern=HINT_LAYER_RE)] | None = None
    scheme_version: int | None = Field(default=None, ge=1)
    category: Annotated[str, StringConstraints(pattern=HINT_CATEGORY_RE)] | None = None
    taxonomy: Annotated[str, StringConstraints(pattern=HINT_TAXONOMY_RE)] | None = None
    taxonomy_version: int | None = Field(default=None, ge=1)
    miner_notes: str | None = Field(default=None, min_length=1, max_length=MAX_MINER_NOTES)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.layer is None) != (self.scheme_version is None):
            raise ValueError("layer and scheme_version are set together")
        named = (self.category, self.taxonomy, self.taxonomy_version)
        if any(v is None for v in named) and any(v is not None for v in named):
            raise ValueError("category, taxonomy and taxonomy_version are set together")
        if self.layer is None and self.category is None and self.miner_notes is None:
            raise ValueError("a hint sets a layer, a category or notes for the miners")
        return self


# --- Event payloads (schema 1).


class InboxLinkAdded(StrictModel):
    item_id: str = Field(pattern=INBOX_ID_RE)
    route: InboxRoute
    link: NonBlank = Field(max_length=MAX_LINK)
    identifier_kind: IdentifierKind
    identifier_value: str = Field(min_length=1, max_length=MAX_LINK)
    identifier_version: str | None = Field(default=None, pattern=r"^v\d+$")
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    basis: Basis | None = None
    channel: Channel
    hints: CaptureHints | None = None
    """A human's capture hints (IDEA-81). Omitted from serialisation when None, so an event
    written without hints is byte-identical to one written before the field existed."""

    @model_serializer(mode="wrap")
    def _no_empty_hints(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        if self.hints is None:
            out.pop("hints", None)
        return out

    @model_validator(mode="after")
    def _version_is_arxiv(self) -> Self:
        if self.identifier_version is not None and self.identifier_kind != IdentifierKind.ARXIV:
            raise ValueError("identifier_version is set for arXiv identifiers only")
        return self


class InboxLinkWithdrawn(StrictModel):
    item_id: str = Field(pattern=INBOX_ID_RE)
    reason: NonBlank


class InboxLinkResolved(StrictModel):
    item_id: str = Field(pattern=INBOX_ID_RE)
    query_id: str = Field(pattern=QUERY_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)
    status: ResolveStatus
    work_id: str | None = Field(default=None, pattern=WORK_ID_RE)
    deviation_id: str | None = Field(default=None, pattern=DEVIATION_ID_RE)
    page_sha256: str | None = Field(default=None, pattern=BLOB_REF_RE)
    """The library hash of the publisher page read for a `page` item (plan SG); the bytes stay in
    the library. None for every other item."""

    @model_validator(mode="after")
    def _work_iff_found(self) -> Self:
        if (self.work_id is not None) != (self.status in FOUND_STATUSES):
            raise ValueError("work_id is set exactly when status is new or in-corpus")
        return self


class InboxPrioritised(StrictModel):
    """A human marks an open item as one to look at first, or clears the mark. A hint for the
    researcher's inbox listing only: it never orders a screening batch (R-34)."""

    item_id: str = Field(pattern=INBOX_ID_RE)
    prioritised: bool = True
