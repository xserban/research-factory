"""Event payloads of an imported library (slice 3d rulings 17-20, 23; plan Import-A).

Invariants:
- `import.recorded` names the export by its library ref (`file_hash`); the export itself never
  leaves the git-ignored library. `records_blob` holds only allow-listed fields and hashes.
- `counts` covers every parse outcome, and its total is the number of records in the blob.
- `import.split_drawn` is written with `import.recorded` in one append; its parts partition the
  ordinals of the records that were not malformed.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from factory.imports.model import ImportFormat, ImportRole, ParseOutcome
from factory.model.base import StrictModel
from factory.model.chase import WorkId
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.references import (
    BINDING_DECISIONS,
    MAX_QUOTE,
    MAX_RATIONALE,
    ConfirmedBy,
    Decision,
    Ordinal,
    Resolution,
    VersionLabel,
)
from factory.model.screening import NonBlank
from factory.model.search import QueryKind
from factory.model.work import RUN_ID_RE

IMPORT_ID_RE = rf"^imp_{ULID_RE}$"
RECORD_KEY_RE = rf"^imp_{ULID_RE}:[1-9][0-9]*$"
MAX_COLLECTION = 120

SplitMode = Literal["drawn", "post-search", "declined"]


class ImportRecorded(StrictModel):
    import_id: str = Field(pattern=IMPORT_ID_RE)
    format: ImportFormat
    role: ImportRole
    collection: str | None = Field(default=None, min_length=1, max_length=MAX_COLLECTION)
    parser: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    file_hash: str = Field(pattern=BLOB_REF_RE)
    records_blob: str = Field(pattern=BLOB_REF_RE)
    counts: dict[ParseOutcome, int]
    attachments: int = Field(ge=0)
    attachments_missing: int = Field(ge=0)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if set(self.counts) != set(ParseOutcome) or any(v < 0 for v in self.counts.values()):
            raise ValueError("counts name every parse outcome with a non-negative count")
        if self.attachments_missing > self.attachments:
            raise ValueError("more attachments missing than recorded")
        return self


class ImportSplitDrawn(StrictModel):
    """The development/held-out split of an import, or why there is none.

    `drawn` carries the random seed and the parts blob (`{"development": [...], "held_out":
    [...]}`, ordinals); `post-search` and `declined` carry neither.
    """

    import_id: str = Field(pattern=IMPORT_ID_RE)
    mode: SplitMode
    random_seed: int | None = Field(default=None, ge=0, lt=2**32)
    parts_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        drawn = self.mode == "drawn"
        if drawn != (self.random_seed is not None) or drawn != (self.parts_blob is not None):
            raise ValueError("a drawn split, and only a drawn split, has a seed and parts")
        return self


class ImportResolved(StrictModel):
    """How the resolvable records of an import resolved (plan Import-B task 1).

    Names each ordinal once, ascending. A later event for the same import supersedes an earlier
    one, decisions on the earlier resolution included. Records that are malformed are not named.
    """

    import_id: str = Field(pattern=IMPORT_ID_RE)
    resolutions: tuple[Resolution, ...]
    lookup_runs: tuple[Annotated[str, StringConstraints(pattern=RUN_ID_RE)], ...] = ()
    matcher: VersionLabel
    matcher_version: VersionLabel

    @model_validator(mode="after")
    def _ordinals(self) -> Self:
        ordinals = [r.ordinal for r in self.resolutions]
        if ordinals != sorted(set(ordinals)):
            raise ValueError("resolutions name each ordinal once, in ascending order")
        if len(set(self.lookup_runs)) != len(self.lookup_runs):
            raise ValueError("lookup_runs must not repeat a run")
        return self


Quote = Annotated[NonBlank, Field(max_length=MAX_QUOTE)]


class ImportResolutionDecided(StrictModel):
    """A decision on one import record's match; it supersedes the previous one of its kind.

    `quotes` is (the record's title, the candidate's title), as the service reads them from the
    record and the stored work. A binding decision (`confirm`, `reject`) names who confirmed it; a
    proposal never does; a confirmation names its work.
    """

    import_id: str = Field(pattern=IMPORT_ID_RE)
    ordinal: Ordinal
    decision: Decision
    work_id: WorkId | None
    rationale: Annotated[NonBlank, Field(max_length=MAX_RATIONALE)]
    quotes: tuple[Quote, Quote]
    confirmed_by: ConfirmedBy | None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if (self.decision in BINDING_DECISIONS) != (self.confirmed_by is not None):
            raise ValueError("a binding decision, and only a binding decision, names who confirmed")
        if self.decision in (Decision.CONFIRM, Decision.PROPOSE_CONFIRM) and self.work_id is None:
            raise ValueError("a confirmation names its work")
        return self


RecordKey = Annotated[str, StringConstraints(pattern=RECORD_KEY_RE)]
MAX_PLANNED_TEXT = 2_000


class PlannedImportQuery(StrictModel):
    """One query an admission plans: the source, kind and text as they will be registered, and
    the record keys it names (for the search report and the trace)."""

    source: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    kind: QueryKind
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_PLANNED_TEXT)]
    record_keys: tuple[RecordKey, ...] = ()


class ImportAdmissionPlanned(StrictModel):
    """The queries that admit an import's records, written before any of them is registered.

    A query is authorised as an `import`-purpose query only when it appears here, for the import
    that names it (`register_query(..., import_id=...)`).
    """

    import_id: str = Field(pattern=IMPORT_ID_RE)
    queries: tuple[PlannedImportQuery, ...] = Field(min_length=1)


class ImportAttachmentLinked(StrictModel):
    """A record's export-named file recorded as a document of its promoted work.

    Written in the same append as the document's attempt and `fulltext.document_added`, so a link
    never exists without its document.
    """

    import_id: str = Field(pattern=IMPORT_ID_RE)
    ordinal: Ordinal
    work_id: WorkId
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
