"""Lab-library vocabulary: adoption of a document another project acquired, and the owner's
confirmation of a source project (slice 5, plan deploy-C).

Invariants enforced here (validated at the boundary, before any event is written):
- An adoption names the source project, the source document and attempt, the shared bytes and the
  conversions adopted with the document; the local document and attempt it creates are named too.
- A confirmation names a source project and a reason; it records no fact about the research.

This module is pure. `factory.services.lab_library` decides when these events are written.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from factory.model.base import StrictModel
from factory.model.fulltext import ATTEMPT_ID_RE, DOCUMENT_ID_RE, LicenceStatus, WorkId
from factory.model.identity import BLOB_REF_RE, SLUG_RE
from factory.model.screening import NonBlank

MAX_REASON = 2000
SlugText = Annotated[str, StringConstraints(pattern=SLUG_RE, max_length=64)]


class FulltextAdopted(StrictModel):
    """The adopting project took the source project's document `source_doc` for `work_id`.

    `document_id` and `attempt_id` are this project's own document and `lab-library` attempt,
    written in the same append. `sha256` is the shared bytes' library reference. `conversions` are
    the source's conversion ids adopted with the document (hashes copied, not recomputed)."""

    work_id: WorkId
    source_project: SlugText
    source_doc: str = Field(pattern=DOCUMENT_ID_RE)
    source_attempt: str = Field(pattern=ATTEMPT_ID_RE)
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    attempt_id: str = Field(pattern=ATTEMPT_ID_RE)
    sha256: str = Field(pattern=BLOB_REF_RE)
    licence_status: LicenceStatus
    conversions: tuple[str, ...] = ()


class SourceConfirmed(StrictModel):
    """The owner of the adopting project confirms `source_project` as a source of documents a
    researcher supplied (spec open question 5): once, by a person."""

    source_project: SlugText
    reason: Annotated[NonBlank, Field(max_length=MAX_REASON)]
