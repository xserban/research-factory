"""The researcher's facet setting of a project's hub (HS-60 to HS-65, slice-7-hub-scope spec).

Invariants:
- `hub.facets_set` is the researcher's act (human actor only). The payload is the whole ordered list
  of facets the hub offers as filters; the latest valid event of a project wins, and a later event
  replaces the earlier list as a whole (an empty list is not allowed: to return to the default,
  record the default list).
- A pick names a protocol-listed miner and one of its enum fields; `label` is the researcher's
  rename (absent: the field's own name made readable). The service refuses an unknown miner or field
  or a non-enum field at the boundary; a reader skips a pick that no longer resolves.

Written and read by `factory.services.hub_facets`; not folded into the index (the setting is read
from the log, which is small for this event type).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.screening import NonBlank

MAX_FACETS = 24
MAX_LABEL = 60


class FacetPick(StrictModel):
    """One facet: the enum field `field` of the listed miner `miner`, shown as `label`."""

    miner: str = Field(min_length=1, max_length=80)
    field: str = Field(min_length=1, max_length=80)
    label: Annotated[NonBlank, Field(max_length=MAX_LABEL)] | None = None


class HubFacetsSet(StrictModel):
    """The ordered facets of the hub. Human actor only; the latest valid event wins."""

    facets: tuple[FacetPick, ...] = Field(min_length=1, max_length=MAX_FACETS)
