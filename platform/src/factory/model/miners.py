"""Registered miners: the `miner.registered` event and the protocol's use of a miner (M-C).

Invariants:
- A miner is immutable once registered: `(name, version)` names one `digest`; a change is a new
  version. The spec itself lives in a blob (`spec_blob`), the event holds its digest.
- `MinerUse` names a registered `(name, version)`; the protocol hashes it (sorted by name and
  version), so a miner is part of `P@`.

Written by `factory.services.mining`, folded by `factory.index.miners`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from factory.events.blobs import BLOB_REF_RE
from factory.events.envelope import ActorKind
from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

MINER_NAME_RE = r"^m-[a-z0-9]+(?:-[a-z0-9]+)*$"
"""A registered miner's name: a namespace no built-in pack uses, so the scope of an extraction event
stays a pure function of its `pack` (slice M ruling 11)."""
MINER_ID_RE = rf"^mnr_{ULID_RE}$"
DIGEST_RE = r"^[0-9a-f]{16}$"


class ImportedFrom(StrictModel):
    """Where a registered miner was copied from (M-E): the source project and its digest."""

    project: str
    digest: str = Field(pattern=DIGEST_RE)


class MinerRegistered(StrictModel):
    miner_id: str = Field(pattern=MINER_ID_RE)
    name: str = Field(pattern=MINER_NAME_RE)
    version: int = Field(ge=1)
    digest: str = Field(pattern=DIGEST_RE)
    spec_blob: str = Field(pattern=BLOB_REF_RE)
    proposer_kind: ActorKind
    imported_from: ImportedFrom | None = None


class MinerUse(StrictModel):
    """A protocol's use of a registered miner. `dual_extract_sample` is the fraction of works
    mined twice (None = every work); `evidence` admits its records to the evidence report (refused
    until the miner is calibrated, M-D); `imports` says whether records imported from another
    project are allowed (M-E)."""

    name: str = Field(pattern=MINER_NAME_RE)
    version: int = Field(ge=1)
    dual_extract_sample: float | None = Field(default=None, gt=0, le=1)
    audit_fraction: float = Field(default=0.02, ge=0, le=1)
    audit_minimum: int = Field(default=50, ge=0)
    evidence: bool = False
    imports: Literal["allow", "deny", "audit"] = "deny"
