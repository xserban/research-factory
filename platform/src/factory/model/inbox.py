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
from typing import Literal, Self

from pydantic import Field, model_validator

from factory.inbox.links import MAX_LINK, IdentifierKind
from factory.model.base import StrictModel
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import ULID_RE
from factory.model.protocol import DEVIATION_ID_RE
from factory.model.screening import Channel, NonBlank
from factory.model.work import QUERY_ID_RE, RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE

INBOX_ID_RE = rf"^inb_{ULID_RE}$"
MAX_NOTE = 300
MAX_ANCHOR = 200


class InboxRoute(StrEnum):
    """How an item reached the inbox; `link` is the only route in v1 (spec ruling 14)."""

    LINK = "link"


class Basis(StrictModel):
    """Why an agent proposes a link: a citing span it read, or outside knowledge.

    `document_id` and `anchor` are both set exactly when `kind` is `document`.
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


# --- Event payloads (schema 1).


class InboxLinkAdded(StrictModel):
    item_id: str = Field(pattern=INBOX_ID_RE)
    route: InboxRoute
    link: NonBlank = Field(max_length=MAX_LINK)
    identifier_kind: IdentifierKind
    identifier_value: str = Field(min_length=1)
    identifier_version: str | None = Field(default=None, pattern=r"^v\d+$")
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    basis: Basis | None = None
    channel: Channel


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

    @model_validator(mode="after")
    def _work_iff_found(self) -> Self:
        if (self.work_id is not None) != (self.status in FOUND_STATUSES):
            raise ValueError("work_id is set exactly when status is new or in-corpus")
        return self
