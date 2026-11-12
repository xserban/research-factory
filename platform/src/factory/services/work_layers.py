"""The layer of a work, the researcher's moves, and on-demand mining requests (IDEA-50, T5).

Invariants:
- The layer of a work is, in this order: the latest `work.layer_set` of the work (the researcher's
  move, source `moved`); else the layer in the FINAL row (status agreed or resolved, never a single
  or unresolved pass) of the first protocol-listed derived miner that projects a dimension-zero
  dimension (source `miner`); else none (source `pending`). A move always beats a miner.
- `move_layer` and `request_mining` are the researcher's acts: a non-human actor is refused with
  nothing written. Every refusal writes nothing.
- A layer request stores the work ids it resolved to when recorded, so a later move never widens it.
- Layers are read, never judged here: the layer a miner gave is the `<dim>/<layer>` category of its
  final row, and no layer is computed from text.
- Import order: this module imports `services.mining` at the top; `services.mining` imports this
  module only inside functions (`miner_population`), so there is no import cycle.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.mining.spec import MinerSpec
from factory.mining.taxonomy import Dimension
from factory.model.extraction import MinerScope
from factory.model.taxonomies import MiningRequested, WorkLayerSet
from factory.services.context import Project
from factory.services.extraction_agreement import final_rows
from factory.services.mining import _corpus_works, registered_miner
from factory.services.protocol import current_protocol
from factory.services.reference_layers import current_scheme
from factory.services.references import included_works
from factory.services.taxonomies import registered_taxonomy

__all__ = [
    "WorkLayer",
    "layer_dimension",
    "layer_of",
    "layers_of",
    "move_layer",
    "request_mining",
    "requested_works",
]

LayerSource = Literal["moved", "miner", "pending"]
_LAYER_FIELD = "category"
"""The field of a derived miner that holds the category id."""


@dataclass(frozen=True)
class WorkLayer:
    """The layer of one work. `layer` is None exactly when `source` is `pending`. `miner_layer` is
    what the layer miner's final row says even when a move overrides it (None without one).
    `scheme_version` is the scheme the layer belongs to (None when pending)."""

    layer: str | None
    source: LayerSource
    scheme_version: int | None
    miner_layer: str | None


def _refuse(field_: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, message)])


def layer_dimension(project: Project, spec: MinerSpec) -> Dimension | None:
    """The dimension zero (the layer-scheme dimension) `spec` projects, or None when `spec` is not
    a derived miner or projects none. A derived layer miner is never layer-filtered."""
    if spec.taxonomy is None:
        return None
    taxonomy = registered_taxonomy(project, spec.taxonomy.name, spec.taxonomy.version)
    if taxonomy is None:
        return None
    for dimension in taxonomy.dimensions:
        if dimension.layer_scheme is not None and dimension.id in spec.taxonomy.dimensions:
            return dimension
    return None


def _miner_layers(project: Project) -> dict[str, tuple[str, int]]:
    """`work_id -> (layer, scheme_version)` from the final rows of the listed layer miners, the
    first listed miner with a final row for a work winning."""
    protocol = current_protocol(project)
    found: dict[str, tuple[str, int]] = {}
    if protocol is None:
        return found
    for use in protocol.spec.miners or ():
        spec = registered_miner(project, use.name, use.version)
        dimension = None if spec is None else layer_dimension(project, spec)
        if dimension is None or dimension.layer_scheme is None:
            continue
        prefix = f"{dimension.id}/"
        for row in final_rows(project, scope=MinerScope(use.name)):
            cell = row.fields.get(_LAYER_FIELD)
            if row.status == "single" or cell is None or not isinstance(cell.value, str):
                continue
            if cell.value.startswith(prefix) and len(cell.value) > len(prefix):
                found.setdefault(row.work_id, (cell.value[len(prefix) :], dimension.layer_scheme))
    return found


def _moves(project: Project) -> dict[str, tuple[str, int]]:
    """The latest move of every moved work (highest `ts`, then event id)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, layer, scheme_version FROM work_layer_moves ORDER BY ts, event_id"
            )
        ).all()
    return {str(r[0]): (str(r[1]), int(r[2])) for r in rows}


def layers_of(project: Project) -> dict[str, WorkLayer]:
    """The layer of every work that has a move or a miner layer, computed in one pass; a work
    absent from the result is pending. Read-only."""
    project.index.sync()
    moved = _moves(project)
    mined = _miner_layers(project)
    out: dict[str, WorkLayer] = {}
    for work in moved.keys() | mined.keys():
        miner_layer = mined[work][0] if work in mined else None
        if work in moved:
            layer, version = moved[work]
            out[work] = WorkLayer(layer, "moved", version, miner_layer)
        else:
            layer, version = mined[work]
            out[work] = WorkLayer(layer, "miner", version, layer)
    return out


def layer_of(project: Project, work_id: str) -> WorkLayer:
    """The layer of `work_id`: the latest move, else the final row of the listed layer miner, else
    pending (see the module invariants). Read-only."""
    return layers_of(project).get(work_id, WorkLayer(None, "pending", None, None))


def move_layer(project: Project, actor: Actor, work_id: str, layer: str, reason: str) -> str:
    """Move `work_id` to `layer` of the latest recorded layer scheme; returns the event id.

    Refused, with nothing written: for a non-human actor (`actor`); a work that is not a corpus
    work (`work_id`); no recorded layer scheme or a layer that is not an id of the latest one
    (`layer`); a blank or over-long reason (`reason`)."""
    if actor.kind != "human":
        raise _refuse("actor", "only the researcher moves a work between layers")
    with project.index.exclusive():
        project.index.sync()
        if work_id not in set(_corpus_works(project)):
            raise _refuse("work_id", f"{work_id} is not a work of the corpus")
        scheme = current_scheme(project)
        if scheme is None:
            raise _refuse("layer", "no layer scheme is recorded")
        if layer not in {d.id for d in scheme.layers}:
            raise _refuse("layer", f"{layer} is not a layer of scheme version {scheme.version}")
        try:
            payload = WorkLayerSet(
                work_id=work_id, scheme_version=scheme.version, layer=layer, reason=reason
            )
        except ValueError as exc:
            raise _refuse("reason", str(exc)) from exc
        event = project.events.make("work.layer_set", payload, actor, refs=(work_id,))
        project.record([event])
    return event.id


def _on_demand_miners(project: Project) -> list[str]:
    protocol = current_protocol(project)
    if protocol is None:
        return []
    return [u.name for u in protocol.spec.miners or () if u.on_demand]


def request_mining(
    project: Project,
    actor: Actor,
    *,
    works: Sequence[str] = (),
    layer: str | None = None,
    miners: Sequence[str] = (),
    reason: str | None = None,
) -> str:
    """Record a request to mine works beyond the protocol's automatic layers; returns its id.

    Exactly one of `works` and `layer`. A layer request is resolved now to the included works whose
    `layer_of` is that layer; it stores the layer, the scheme version and the work ids.

    Refused, with nothing written: a non-human actor (`actor`); both or neither target (`works`);
    a work that is not an included work (`works`); a layer that is not one of the latest scheme's
    (`layer`) or that holds no included work (`layer`); a miner not listed in the current protocol
    with `on_demand` (`miners`); no such miner when none is named (`miners`)."""
    if actor.kind != "human":
        raise _refuse("actor", "only the researcher requests mining")
    if bool(works) == (layer is not None):
        raise _refuse("works", "give works or a layer, not both and not neither")
    with project.index.exclusive():
        project.index.sync()
        eligible = _on_demand_miners(project)
        named = tuple(dict.fromkeys(miners))
        for name in named:
            if name not in eligible:
                raise _refuse(
                    "miners", f"miner {name} is not listed in the protocol with on_demand"
                )
        if not named and not eligible:
            raise _refuse("miners", "no miner in the protocol is listed with on_demand")
        included = set(included_works(project))
        scheme_version: int | None = None
        if layer is not None:
            scheme = current_scheme(project)
            if scheme is None or layer not in {d.id for d in scheme.layers}:
                raise _refuse("layer", f"{layer} is not a layer of the latest scheme")
            scheme_version = scheme.version
            layers = layers_of(project)
            target = tuple(sorted(w for w in included if layers.get(w, _PENDING).layer == layer))
            if not target:
                raise _refuse("layer", f"no included work is in layer {layer}")
        else:
            outside = sorted(set(works) - included)
            if outside:
                raise _refuse("works", f"not included works: {', '.join(outside)}")
            target = tuple(sorted(set(works)))
        payload = MiningRequested(
            request_id=project.ids.new("mr"),
            target="layer" if layer is not None else "works",
            layer=layer,
            layer_scheme=scheme_version,
            works=target,
            miners=named,
            reason=reason,
        )
        event = project.events.make("mining.requested", payload, actor)
        project.record([event])
    return payload.request_id


_PENDING = WorkLayer(None, "pending", None, None)


def requested_works(project: Project, miner_name: str) -> set[str]:
    """The works of every recorded request that names `miner_name`, or names no miner when the
    protocol lists `miner_name` with `on_demand`. Requests are never withdrawn, so all are live.
    Read-only."""
    project.index.sync()
    listed = miner_name in _on_demand_miners(project)
    with project.index.connect() as conn:
        requests = conn.execute(text("SELECT request_id, miners FROM mining_requests")).all()
        wanted = [str(r[0]) for r in requests if _names(json.loads(str(r[1])), miner_name, listed)]
        found: set[str] = set()
        for request_id in wanted:
            rows = conn.execute(
                text("SELECT work_id FROM mining_request_works WHERE request_id = :r"),
                {"r": request_id},
            ).all()
            found.update(str(r[0]) for r in rows)
    return found


def _names(named: Iterable[str], miner_name: str, listed: bool) -> bool:
    names = list(named)
    return miner_name in names or (not names and listed)
