"""Events of a living review (slice 4b, plan living-B): review snapshots.

A snapshot pins the computed cumulative PRISMA flow and the included set at a cut-off event; its
blob (`services.snapshots.SnapshotBlob`) is content-addressed, so the event holds only its ref.
Pure value types; written by `factory.services.snapshots`, folded by `index.living`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE

SNP_ID_RE = rf"^snp_{ULID_RE}$"


class SnapshotRecorded(StrictModel):
    """A snapshot taken by a human (`human`) or by the cycle hook of a living review (`cycle`).

    `cutoff_event` is the last event of the log when the snapshot was taken; the blob is computed
    from the events up to it. `projection_version` names the projection that computed the blob."""

    snapshot_id: str = Field(pattern=SNP_ID_RE)
    cutoff_event: str = Field(min_length=1)
    protocol_id: str = Field(min_length=1)
    blob: str = Field(pattern=BLOB_REF_RE)
    projection_version: str = Field(min_length=1)
    trigger: Literal["human", "cycle"]
