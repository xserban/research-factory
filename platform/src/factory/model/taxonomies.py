"""Taxonomies as versioned objects, mining requests and work layer moves (IDEA-50).

Invariants:
- `taxonomy.registered` is the researcher's act (human actor only) and first write wins per
  `(name, version)`: a later event for the same pair is stored in the log but never folded.
- `taxonomy.change_proposed` is an agent's proposal; it changes no taxonomy. Its provenance is the
  event envelope's: the actor's `model` and `skill` and the event's `input_blob`.
- `mining.requested` and `work.layer_set` are the researcher's acts (human actor only). A layer
  request stores the work ids it resolved to, so a later move never widens it; the latest
  `work.layer_set` of a work is its effective layer.

Written by `factory.services.taxonomies` and `factory.services.work_layers`, folded by
`factory.index.taxonomies`.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from factory.events.blobs import BLOB_REF_RE
from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.miners import DIGEST_RE
from factory.model.references import LayerId
from factory.model.screening import NonBlank

TAXONOMY_NAME_RE = r"^t-[a-z0-9][a-z0-9-]*$"
PROPOSAL_ID_RE = rf"^tp_{ULID_RE}$"
"""Minted by `project.ids.new("tp")`."""
MINING_REQUEST_ID_RE = rf"^mr_{ULID_RE}$"
"""Minted by `project.ids.new("mr")`."""

MAX_REASON = 500
MAX_RATIONALE = 2000

ProposalKind = Literal["add", "split", "merge", "redefine", "rename", "retire"]


class ProposalRejection(StrictModel):
    """A proposal the researcher declined when registering a version, with the reason."""

    proposal_id: str = Field(pattern=PROPOSAL_ID_RE)
    reason: Annotated[NonBlank, Field(max_length=MAX_REASON)]


class TaxonomyRegistered(StrictModel):
    """Version `version` of taxonomy `name`; immutable, first write wins per `(name, version)`.

    The spec lives in a blob; the event holds its digest. `accepts` and `rejects` name the
    proposals this version settles. Human actor only."""

    name: str = Field(pattern=TAXONOMY_NAME_RE)
    version: int = Field(ge=1)
    digest: str = Field(pattern=DIGEST_RE)
    spec_blob: str = Field(pattern=BLOB_REF_RE)
    accepts: tuple[str, ...] = ()
    rejects: tuple[ProposalRejection, ...] = ()

    @model_validator(mode="after")
    def _settled_once(self) -> Self:
        ids = list(self.accepts) + [r.proposal_id for r in self.rejects]
        if any(re.fullmatch(PROPOSAL_ID_RE, i) is None for i in self.accepts):
            raise ValueError("accepts names proposal ids")
        if len(set(ids)) != len(ids):
            raise ValueError("a proposal is accepted or rejected once")
        return self


class TaxonomyChangeProposed(StrictModel):
    """An agent's proposed change to the taxonomy at `base_version`; it changes nothing itself.

    `targets` are full category ids `dim/cat` of the base version (empty for `add`). `draft_blob`
    holds the drafted categories as JSON. `rows` are the extraction ids and `works` the work ids
    that motivate it. Agent actor; provenance is carried by the envelope."""

    proposal_id: str = Field(pattern=PROPOSAL_ID_RE)
    taxonomy: str = Field(pattern=TAXONOMY_NAME_RE)
    base_version: int = Field(ge=1)
    kind: ProposalKind
    targets: tuple[str, ...] = ()
    draft_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)
    works: tuple[str, ...] = ()
    rows: tuple[str, ...] = ()
    cluster_id: str | None = Field(default=None, min_length=1, max_length=200)
    rationale: Annotated[NonBlank, Field(max_length=MAX_RATIONALE)]


class MiningRequested(StrictModel):
    """The researcher asks for works to be mined beyond the protocol's automatic layers.

    `layer` and `layer_scheme` are set exactly when `target` is `layer`; `works` are then the
    work ids the layer resolved to when recorded. `miners` empty means every miner the protocol
    lists with `on_demand`. Human actor only."""

    request_id: str = Field(pattern=MINING_REQUEST_ID_RE)
    target: Literal["works", "layer"]
    layer: LayerId | None = None
    layer_scheme: int | None = Field(default=None, ge=1)
    works: tuple[str, ...] = Field(min_length=1)
    miners: tuple[str, ...] = ()
    reason: str | None = Field(default=None, max_length=MAX_REASON)

    @model_validator(mode="after")
    def _layer_iff_layer_target(self) -> Self:
        is_layer = self.target == "layer"
        if is_layer != (self.layer is not None) or is_layer != (self.layer_scheme is not None):
            raise ValueError("layer and layer_scheme are set if and only if target is layer")
        return self


class WorkLayerSet(StrictModel):
    """The researcher moves a work to `layer` of scheme `scheme_version`. The latest move of a
    work is its effective layer. Human actor only."""

    work_id: str = Field(min_length=1)
    scheme_version: int = Field(ge=1)
    layer: LayerId
    reason: Annotated[NonBlank, Field(max_length=MAX_REASON)]
