"""The `write` hub payload (stub of step 0; the page port fills it in).

Invariants:
- `build` is pure over its `HubContext` and reads no network.
- The stub payload is `{"methods": {}, "ready": False}`; a later step replaces it with computed data
  whose `methods` entries feed the page's info panels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext


def build(ctx: HubContext) -> dict[str, Any]:
    """The stub payload of the `write` page."""
    del ctx
    return {"methods": {}, "ready": False}
