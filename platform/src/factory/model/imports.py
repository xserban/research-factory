"""Event payloads of an imported library (slice 3d rulings 17-20, 23; plan Import-A).

Invariants:
- `import.recorded` names the export by its library ref (`file_hash`); the export itself never
  leaves the git-ignored library. `records_blob` holds only allow-listed fields and hashes.
- `counts` covers every parse outcome, and its total is the number of records in the blob.
- `import.split_drawn` is written with `import.recorded` in one append; its parts partition the
  ordinals of the records that were not malformed.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from factory.imports.model import ImportFormat, ParseOutcome
from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE

IMPORT_ID_RE = rf"^imp_{ULID_RE}$"
RECORD_KEY_RE = rf"^imp_{ULID_RE}:[1-9][0-9]*$"
MAX_COLLECTION = 120

SplitMode = Literal["drawn", "post-search", "declined"]


class ImportRole(StrEnum):
    REFERENCE = "reference"
    CORPUS = "corpus"


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
