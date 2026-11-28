"""The layer of a work, the researcher's moves, and on-demand mining requests (IDEA-50, T5).

Invariants:
- The layer of a work is, in this order: the latest `work.layer_set` of the work (the researcher's
  move, source `moved`); else the layer in the FINAL row of the first protocol-listed derived miner
  that projects a dimension-zero dimension, or is flagged `paper_layers` and projects any
  dimension (source `miner`): agreed, resolved, or single (a work
  outside the dual sample has one pass, which is its final value), never an unresolved
  disagreement; else none (source `pending`). A move beats a miner, but only while its layer is
  an id of the latest recorded scheme, or a category of the first projected dimension of a
  protocol-listed derived miner flagged `paper_layers` (which supplies layers even when its
  dimension has no layer scheme; its `scheme_version` is then None): a move to any other layer is
  not effective, the next rule
  applies, and the move stays visible as `WorkLayer.ignored_move`. A miner row whose value is
  `<dim>/not-stated`, `<dim>/other` or `<dim>/not-applicable` is no layer: the work is `pending`
  and `miner_layer` holds that value for display.
- `layers_of` is memoised per process, per project directory, keyed on the index's last folded
  event id (read after `sync`): the layers are a function of the log alone, so any new event
  changes the key and drops the entry; a rebuild to the same log gives the same key and the same
  answer. At most `_CACHE_MAX` projects are held (oldest dropped); nothing is persisted.
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
from factory.services.extraction_agreement import final_rows, final_rows_restricted
from factory.services.mining import _corpus_works, registered_miner
from factory.services.protocol import current_protocol
from factory.services.reference_layers import current_scheme
from factory.services.references import included_works
from factory.services.taxonomies import registered_taxonomy
from factory.services.work_ref import resolve_work_id, resolve_work_ids

__all__ = [
    "WorkLayer",
    "layer_dimension",
    "layer_history",
    "layer_moves",
    "layer_of",
    "layers_for",
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
    ignored_move: str | None = None
    """The layer of a latest move that is not in the latest scheme and so does not apply."""


_ABSENT_LAYERS = frozenset({"not-stated", "other", "not-applicable"})
"""The category ids of a dimension that say the text gives no category (never a layer)."""
_CACHE_MAX = 8
_CACHE: dict[str, tuple[str | None, dict[str, WorkLayer]]] = {}
"""Project directory -> (last folded event id, layers_of result)."""


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


def _paper_layer_dimension(project: Project, spec: MinerSpec) -> Dimension | None:
    """The first dimension a derived miner projects (the one of `spec.taxonomy.dimensions` that
    comes first in its taxonomy), or None for a miner that is not derived."""
    if spec.taxonomy is None:
        return None
    taxonomy = registered_taxonomy(project, spec.taxonomy.name, spec.taxonomy.version)
    if taxonomy is None:
        return None
    for dimension in taxonomy.dimensions:
        if dimension.id in spec.taxonomy.dimensions:
            return dimension
    return None


def _layer_sources(project: Project) -> list[tuple[str, Dimension, int | None, bool]]:
    """`(miner name, dimension, scheme version, flagged)` of every protocol-listed miner that
    supplies layers, in protocol order: a derived miner with a layer-scheme dimension, or one
    flagged `paper_layers` (scheme version None unless its dimension has one)."""
    protocol = current_protocol(project)
    out: list[tuple[str, Dimension, int | None, bool]] = []
    if protocol is None:
        return out
    for use in protocol.spec.miners or ():
        spec = registered_miner(project, use.name, use.version)
        if spec is None:
            continue
        dimension = layer_dimension(project, spec)
        if dimension is not None:
            out.append((use.name, dimension, dimension.layer_scheme, False))
        elif use.paper_layers:
            flagged = _paper_layer_dimension(project, spec)
            if flagged is not None:
                out.append((use.name, flagged, flagged.layer_scheme, True))
    return out


def _flagged_categories(project: Project) -> set[str]:
    """The category ids of the dimensions of the `paper_layers` miners: layers a move may name."""
    return {c.id for _n, d, _v, flagged in _layer_sources(project) if flagged for c in d.categories}


def _miner_layers(
    project: Project, works: frozenset[str] | None = None
) -> dict[str, tuple[str, int | None, bool]]:
    """`work_id -> (value, scheme_version, is_layer)` from the final rows of the layer miners, the
    first listed miner with a final row for a work winning. `scheme_version` is None for a
    `paper_layers` miner whose dimension has no layer scheme. `is_layer` is False for an absence
    value (`not-stated`, `other`, `not-applicable`)."""
    found: dict[str, tuple[str, int | None, bool]] = {}
    for name, dimension, scheme_version, _flagged in _layer_sources(project):
        prefix = f"{dimension.id}/"
        rows = (
            final_rows(project, scope=MinerScope(name))
            if works is None
            else final_rows_restricted(project, works, scope=MinerScope(name))
        )
        for row in rows:
            cell = row.fields.get(_LAYER_FIELD)
            if cell is None or not isinstance(cell.value, str):
                continue
            if cell.value.startswith(prefix) and len(cell.value) > len(prefix):
                value = cell.value[len(prefix) :]
                found.setdefault(row.work_id, (value, scheme_version, value not in _ABSENT_LAYERS))
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


def layer_history(
    rows: Iterable[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str]]:
    """The layer moves as `(ts, work_id, layer, who)` in time order, from `(ts, event_id, work_id,
    layer)` rows. Pure. Only the researcher moves a work (`move_layer`), so `who` is
    `researcher`."""
    ordered = sorted(rows, key=lambda r: (r[0], r[1]))
    return [(ts, work, layer, "researcher") for ts, _event, work, layer in ordered]


def layer_moves(project: Project) -> list[tuple[str, str, str, str]]:
    """Every `work.layer_set` event of the project as `(ts, work_id, layer, who)`, in time order.
    Read-only."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT ts, event_id, work_id, layer FROM work_layer_moves")).all()
    return layer_history((str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows)


def layers_of(project: Project) -> dict[str, WorkLayer]:
    """The layer of every work that has a move or a miner row, computed in one pass and memoised
    (see the module invariants); a work absent from the result is pending. Read-only. The result
    is a copy the caller may change."""
    project.index.sync()
    key = str(project.paths.dir)
    head = project.index.last_event_id()
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == head:
        return dict(hit[1])
    out = _compute(project)
    _CACHE.pop(key, None)
    while len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (head, out)
    return dict(out)


def layers_for(project: Project, works: Iterable[str]) -> dict[str, WorkLayer]:
    """`layers_of` restricted to `works`: the same rules over the final rows of those works only,
    so it does not fold the whole corpus. Equal to the filter of `layers_of` by work. Read-only."""
    project.index.sync()
    wanted = frozenset(works)
    return {w: v for w, v in _compute(project, wanted).items() if w in wanted}


def _compute(project: Project, works: frozenset[str] | None = None) -> dict[str, WorkLayer]:
    moved = _moves(project)
    mined = _miner_layers(project, works)
    scheme = current_scheme(project)
    valid = set() if scheme is None else {d.id for d in scheme.layers}
    valid |= _flagged_categories(project)
    out: dict[str, WorkLayer] = {}
    for work in moved.keys() | mined.keys():
        found = mined.get(work)
        miner_layer = None if found is None else found[0]
        ignored: str | None = None
        if work in moved:
            layer, version = moved[work]
            if layer in valid:
                out[work] = WorkLayer(layer, "moved", version, miner_layer)
                continue
            ignored = layer
        if found is not None and found[2]:
            out[work] = WorkLayer(found[0], "miner", found[1], found[0], ignored)
        else:
            out[work] = WorkLayer(None, "pending", None, miner_layer, ignored)
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
        work_id = resolve_work_id(project, work_id)
        if work_id not in set(_corpus_works(project)):
            raise _refuse("work_id", f"{work_id} is not a work of the corpus")
        scheme = current_scheme(project)
        if scheme is None:
            raise _refuse("layer", "no layer scheme is recorded")
        if layer not in {d.id for d in scheme.layers} | _flagged_categories(project):
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
            works = resolve_work_ids(project, works, field="works")
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
