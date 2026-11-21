"""Registered miners: the `miner.registered` event and the protocol's use of a miner (M-C).

Invariants:
- A miner is immutable once registered: `(name, version)` names one `digest`; a change is a new
  version. The spec itself lives in a blob (`spec_blob`), the event holds its digest.
- `MinerUse` names a registered `(name, version)`; the protocol hashes it (sorted by name and
  version), so a miner is part of `P@`.

Written by `factory.services.mining`, folded by `factory.index.miners`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from factory.events.blobs import BLOB_REF_RE
from factory.events.envelope import ActorKind
from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

MINER_NAME_RE = r"^m-[a-z0-9]+(?:-[a-z0-9]+)*$"
"""A registered miner's name: a namespace no built-in pack uses, so the scope of an extraction event
stays a pure function of its `pack` (slice M ruling 11)."""
MINER_ID_RE = rf"^mnr_{ULID_RE}$"
DIGEST_RE = r"^[0-9a-f]{16}$"
_LAYER_ID_RE = r"^[a-z][a-z0-9-]{0,31}$"
"""Same pattern as `factory.model.references.LAYER_ID_RE`, repeated because that module imports the
protocol model, which imports this one."""
_LayerId = Annotated[str, StringConstraints(pattern=_LAYER_ID_RE)]
_ORIGIN_RE = r"^(inbox|feed)(:(cli|mcp|elicit))?$"
"""An origin tag of a work (IDEA-81): how it entered the corpus, optionally with the channel."""
_Origin = Annotated[str, StringConstraints(pattern=_ORIGIN_RE)]


class ImportedFrom(StrictModel):
    """Where a registered miner was copied from (M-E): the source project and its digest."""

    project: str
    digest: str = Field(pattern=DIGEST_RE)
    proposer_session: str | None = Field(default=None, min_length=1, max_length=200)
    """The session of an agent that authored the source's version, kept so that adopting it does
    not turn an agent proposal into a human one (R-04, R-51). None when the source's was not an
    agent's. It only ever adds the agent proposer; it never removes one."""


class MinerRegistered(StrictModel):
    miner_id: str = Field(pattern=MINER_ID_RE)
    name: str = Field(pattern=MINER_NAME_RE)
    version: int = Field(ge=1)
    digest: str = Field(pattern=DIGEST_RE)
    spec_blob: str = Field(pattern=BLOB_REF_RE)
    proposer_kind: ActorKind
    imported_from: ImportedFrom | None = None


class MinerRetired(StrictModel):
    """A miner version taken out of use (R-52): its rows stay and are reported, no task is served.
    Written by `factory.services.miners.retire_miner`."""

    name: str = Field(pattern=MINER_NAME_RE)
    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=300)


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
    layers: tuple[_LayerId, ...] = ()
    """The layers mined automatically (empty: no layer filter). Omitted from serialisation when
    empty, so protocol version hashes written before it existed do not change."""
    on_demand: bool = False
    """True lets the researcher's mining requests add works beyond `layers`. Omitted when false."""
    order: Literal["id", "by-layer"] = "id"
    """`by-layer` serves works by ring, then work id. Omitted when `id`."""
    origins: tuple[_Origin, ...] = ()
    """Only works whose computed origin tag (`services.capture_hints.origins_of`) is one of these
    are mined automatically (empty: no origin filter). Omitted from serialisation when empty."""
    hint_context: bool = False
    """True serves the researcher's capture hints (layer, category, notes) to this miner as context
    on its production tasks. Defaults OFF because a hint can anchor the miner; a miner that ever
    had it on is not scored against hints (`capture_hints.hint_agreement`). Omitted when false."""
    exploratory: bool = False
    """Declared by a protocol amendment, whose reason is the record (IDEA-69). True allows
    production mining passes of a version whose calibration has not passed; its rows carry no
    quality claim and never reach the evidence report, so it is refused together with `evidence`.
    Omitted when false, so every protocol hash written before it existed is unchanged."""

    @model_validator(mode="after")
    def _exploratory_is_not_evidence(self) -> MinerUse:
        if self.exploratory and self.evidence:
            raise ValueError("an exploratory miner use cannot also be admitted as evidence")
        return self

    @model_serializer(mode="wrap")
    def _defaults_say_nothing(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """A use without layer fields serialises as it did before they existed."""
        out: dict[str, Any] = handler(self)
        if not self.layers:
            out.pop("layers", None)
        if not self.on_demand:
            out.pop("on_demand", None)
        if self.order == "id":
            out.pop("order", None)
        if not self.origins:
            out.pop("origins", None)
        if not self.hint_context:
            out.pop("hint_context", None)
        if not self.exploratory:
            out.pop("exploratory", None)
        return out
