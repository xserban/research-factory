"""Recorded pages: model-written documents of a project (plan site-hub, step 4).

The platform never calls a model, so a page that needs a model's judgement (a synthesis of the
corpus) is written in an agent session and recorded here. The event holds the identity and the
counts; the page text, the digest it was written from and the mechanical check result live in the
event's input blob (`factory.services.pages`), so the index needs no table of its own and every
reader goes through the generic event row.

Invariants:
- A page is never edited: a revision is a new page that names the earlier one in `supersedes`.
- A page is recorded only after its mechanical check passed: every cited work exists, every
  quotation is verbatim from a cited work's recorded quotes, every number comes from the computed
  statistics.
  Soft flags (a generalisation with no number or citation) are recorded with the page, not hidden.
- The page is an interpretation, shown as model-written; it enters no count, table or result.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

PAGE_ID_RE = rf"^pg_{ULID_RE}$"
SCOPE_RE = r"^(?:overview|(?:technique|stage|field)=[a-z0-9][a-z0-9-]*)$"
"""A page's scope: the whole corpus, or one technique, stage or field (a taxonomy value)."""
SHA256_HEX_RE = r"^[0-9a-f]{64}$"


class PageRecorded(StrictModel):
    page_id: str = Field(pattern=PAGE_ID_RE)
    kind: Literal["synthesis"]
    scope: str = Field(pattern=SCOPE_RE, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    body_sha256: str = Field(pattern=SHA256_HEX_RE)
    flags: int = Field(ge=0)
    """The number of soft flags the check raised (see `services.pages.check_page`)."""
    supersedes: str | None = Field(default=None, pattern=PAGE_ID_RE)
