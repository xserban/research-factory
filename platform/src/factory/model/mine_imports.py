"""`mine.imported`: records one project reuses from another (slice M ruling 19; R-143).

Invariants:
- The event is self-contained: its rows are in it, as `extraction.recorded` stores them (values,
  anchors, quotes), so replaying the importing project never reads another project.
- Every id of an item is the importer's, and the `source_*` fields say what the source called it: a
  conversion id is minted per project, and a row key hashes the conversion id.
- An imported row counts as dual only when the source had two agreeing passes that are independent
  (`ImportedItem.dual`): the claim is checked against the passes the event names, never taken from
  `source_status` alone.

Written by `factory.services.shared_mining`, folded by `factory.index.mine_imports`. Named apart
from `factory.model.imports`, which is slice 3d's library import.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from factory.model.base import StrictModel
from factory.model.extraction import (
    EXTRACTION_ID_RE,
    ROW_KEY_RE,
    CitedEntry,
    FieldName,
    StoredField,
)
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import CONVERSION_ID_RE, SLUG_RE, ULID_RE
from factory.model.miners import DIGEST_RE, MINER_NAME_RE
from factory.model.protocol import PROTOCOL_ID_RE
from factory.model.screening import Channel, PassLabel

MINE_IMPORT_PREFIX = "mim_"
"""An imported row's `task_id` is its import's id, which no task id can equal: this prefix is how
the extraction tables tell an imported row from a mined one, so they gain no column."""
MINE_IMPORT_ID_RE = rf"^{MINE_IMPORT_PREFIX}{ULID_RE}$"
MAX_VERSION = 2**31 - 1
MAX_ORDINAL = 2**31 - 1
MAX_ITEMS = 2000
"""The most rows one event carries; a larger import is several events of whole units."""
MAX_IDENTITY = 200

SourceStatus = Literal["agreed", "resolved", "single"]
ExtractionId = Annotated[str, Field(pattern=EXTRACTION_ID_RE)]


class ImportedPass(StrictModel):
    """Who recorded a source row: its pass, session and model."""

    pass_label: PassLabel
    session: str = Field(min_length=1, max_length=MAX_IDENTITY)
    model: str | None = Field(default=None, min_length=1, max_length=MAX_IDENTITY)


class ImportedItem(StrictModel):
    """One record of a `mine.imported` event."""

    extraction_id: str = Field(pattern=EXTRACTION_ID_RE)
    work_id: str = Field(min_length=1)
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    row_key: str = Field(pattern=ROW_KEY_RE)
    fields: dict[FieldName, StoredField] = Field(min_length=1)
    cited: CitedEntry | None = None
    source_extraction_ids: tuple[ExtractionId, ...] = Field(min_length=1, max_length=4)
    source_conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    source_row_key: str = Field(pattern=ROW_KEY_RE)
    source_status: SourceStatus
    source_passes: tuple[ImportedPass, ...] = Field(min_length=1, max_length=4)

    @field_validator("cited")
    @classmethod
    def _bounded_ordinal(cls, value: CitedEntry | None) -> CitedEntry | None:
        if value is not None and value.ordinal > MAX_ORDINAL:
            raise ValueError("the ordinal is out of range")
        return value

    @property
    def dual(self) -> bool:
        """Whether the source had two agreeing, independent passes (R-143): agreed, one row of each
        pass, by different sessions and different models."""
        passes = self.source_passes
        return (
            self.source_status == "agreed"
            and len(passes) == 2
            and {p.pass_label for p in passes} == set(PassLabel)
            and passes[0].session != passes[1].session
            and None not in (passes[0].model, passes[1].model)
            and passes[0].model != passes[1].model
        )


class MineImported(StrictModel):
    """Records of one miner version imported from one project. `protocol_id` is the importer's;
    `channel` is how the human act reached the platform."""

    import_id: str = Field(pattern=MINE_IMPORT_ID_RE)
    source_project: str = Field(pattern=SLUG_RE, max_length=64)
    miner: str = Field(pattern=MINER_NAME_RE)
    version: int = Field(ge=1, le=MAX_VERSION)
    digest: str = Field(pattern=DIGEST_RE)
    protocol_id: str = Field(pattern=PROTOCOL_ID_RE)
    channel: Channel
    items: tuple[ImportedItem, ...] = Field(min_length=1, max_length=MAX_ITEMS)
