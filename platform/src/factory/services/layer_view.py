"""The visible interpretation layer, assembled for a graph view (slice 3c, plan G3-C, task 1).

The layer is never merged into the evidence graph: this module reads only the layer's own tables
and hands the result back as a separate part (`LayerGraph`). Importers re-export it from
`factory.services.interpretations`.

Invariants (rulings C1, C2):
- Read-only, SQL only, ordered pages of `LAYER_PAGE` rows; nothing loads every row. The whole
  layer streams through `iter_layer_nodes` / `iter_layer_edges`; `layer_graph` collects them and
  is for views bounded by `attach_to`.
- An interpretation is shown iff `unreviewed` or `reviewed`; a concept iff its source is
  approved, it is unmerged and its definition is `unreviewed` or `reviewed`; an `explains` edge
  iff its interpretation is shown; a `uses` edge iff its status is `stated` or `confirmed` (also
  `inferred` on request) and both its endpoints are shown. Edges dropped for a hidden endpoint
  are counted, never silently lost.
- `attach_to` limits the layer to the evidence nodes of a view: the interpretations that target
  them, the `uses` edges from them, the concepts those reach and those concepts' own `uses`
  closure (followed only through shown concepts, so a hidden concept ends a path).
- Every node and edge carries `class = interpretation` and its review state in its label.
- The concept visibility predicate repeats `services.concepts._VISIBLE_SQL`; a test compares them.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator
from typing import Any

from sqlalchemy import text

from factory.intuition.labels import LAYER_CLASS, layer_label
from factory.model.intuition import (
    ConceptHidden,
    ConceptState,
    InterpretationHidden,
    LayerCounts,
    LayerEdge,
    LayerGraph,
    LayerHidden,
    LayerNode,
    LinkStatus,
    ReviewState,
)
from factory.services.context import Project
from factory.services.intuition_sources import stale_sources

__all__ = [
    "LAYER_PAGE",
    "iter_layer_edges",
    "iter_layer_nodes",
    "layer_counts",
    "layer_graph",
    "layer_hidden",
]

LAYER_PAGE = 500
_LIVE = "('unreviewed', 'reviewed')"
_CONCEPT_VISIBLE = f"source_state = 'approved' AND merged_into IS NULL AND review_state IN {_LIVE}"
_USES_STATUSES = (LinkStatus.STATED.value, LinkStatus.CONFIRMED.value)


def _statuses(include_inferred: bool) -> str:
    wanted = (*_USES_STATUSES, LinkStatus.INFERRED.value) if include_inferred else _USES_STATUSES
    return json.dumps(sorted(wanted))


def _params(attach_to: Collection[str] | None, include_inferred: bool) -> dict[str, Any]:
    return {
        "attach": json.dumps(sorted(attach_to or ())),
        "all": 1 if attach_to is None else 0,
        "statuses": _statuses(include_inferred),
    }


def _uses_cte(attached: bool) -> str:
    """`allowed` (the `uses` edges of an allowed status), `vis` (the shown concepts) and `reach`
    (the edges in scope). Scoped to the attached nodes, `reach` is the recursive closure."""
    base = (
        "WITH RECURSIVE allowed AS (SELECT edge_id, source, target, review_state, basis "
        "FROM layer_edges WHERE edge_type = 'uses' "
        "AND review_state IN (SELECT value FROM json_each(:statuses))), "
        f"vis AS (SELECT concept_id FROM concepts WHERE {_CONCEPT_VISIBLE}), "
    )
    if not attached:
        return base + "reach(edge_id) AS (SELECT edge_id FROM allowed), "
    return base + (
        "reach(edge_id) AS (SELECT a.edge_id FROM allowed a "
        "WHERE a.source IN (SELECT value FROM json_each(:attach)) "
        "UNION SELECT a2.edge_id FROM allowed a2 JOIN allowed a1 ON a2.source = a1.target "
        "JOIN reach r ON r.edge_id = a1.edge_id "
        "WHERE a1.target IN (SELECT concept_id FROM vis)), "
    )


_SHOWN = (
    "shown AS (SELECT a.edge_id, a.source, a.target, a.review_state, a.basis FROM allowed a "
    "JOIN reach r ON r.edge_id = a.edge_id "
    "WHERE a.target IN (SELECT concept_id FROM vis) "
    "AND (substr(a.source, 1, 4) != 'cpt_' OR a.source IN (SELECT concept_id FROM vis))) "
)
_ATTACHED_INTERPRETATION = "(:all = 1 OR i.target IN (SELECT value FROM json_each(:attach)))"


def _flags(
    stale: dict[str, tuple[str, ...]], ident: str, self_reviewed: bool, unverifiable: bool = False
) -> list[str]:
    flags = []
    if ident in stale:
        flags.append("source-stale")
    if self_reviewed:
        flags.append("self-reviewed")
    if unverifiable:
        flags.append("unverifiable-source")
    return flags


def iter_layer_nodes(
    project: Project,
    *,
    attach_to: Collection[str] | None = None,
    include_inferred: bool = False,
) -> Iterator[LayerNode]:
    """The shown interpretations by id, then the shown concepts by id. `attach_to=None` is the
    whole layer; else the layer attached to those evidence nodes."""
    project.index.sync()
    params = _params(attach_to, include_inferred)
    last = ""
    while True:
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT n.node_id, n.review_state, i.self_reviewed FROM layer_nodes n "
                    "JOIN interpretations i ON i.interpretation_id = n.node_id "
                    f"WHERE n.node_type = 'interpretation' AND n.review_state IN {_LIVE} "
                    f"AND {_ATTACHED_INTERPRETATION} AND n.node_id > :last "
                    "ORDER BY n.node_id LIMIT :n"
                ),
                {**params, "last": last, "n": LAYER_PAGE},
            ).all()
        stale = stale_sources(project, only=[str(r[0]) for r in rows]) if rows else {}
        for node_id, state, self_reviewed in rows:
            yield LayerNode(
                node_id=str(node_id),
                node_type="interpretation",
                class_=LAYER_CLASS,
                review_state=str(state),
                label=layer_label(str(state)),
                name=None,
                flags=_flags(stale, str(node_id), bool(self_reviewed)),
            )
        if len(rows) < LAYER_PAGE:
            break
        last = str(rows[-1][0])
    last = ""
    attached = attach_to is not None
    scope = (
        "AND (c.concept_id IN (SELECT target FROM shown) OR c.concept_id IN "
        "(SELECT source FROM shown))"
        if attached
        else ""
    )
    sql = (
        _uses_cte(attached)
        + _SHOWN
        + "SELECT c.concept_id, c.name, c.review_state, c.self_reviewed, c.source_verifiable "
        f"FROM concepts c WHERE c.concept_id IN (SELECT concept_id FROM vis) {scope} "
        "AND c.concept_id > :last ORDER BY c.concept_id LIMIT :n"
    )
    while True:
        with project.index.connect() as conn:
            rows = conn.execute(text(sql), {**params, "last": last, "n": LAYER_PAGE}).all()
        stale = stale_sources(project, only=[str(r[0]) for r in rows]) if rows else {}
        for concept_id, name, state, self_reviewed, verifiable in rows:
            yield LayerNode(
                node_id=str(concept_id),
                node_type="concept",
                class_=LAYER_CLASS,
                review_state=str(state),
                label=layer_label(str(state)),
                name=str(name),
                flags=_flags(
                    stale,
                    str(concept_id),
                    bool(self_reviewed),
                    verifiable is not None and not verifiable,
                ),
            )
        if len(rows) < LAYER_PAGE:
            break
        last = str(rows[-1][0])


def iter_layer_edges(
    project: Project,
    *,
    attach_to: Collection[str] | None = None,
    include_inferred: bool = False,
) -> Iterator[LayerEdge]:
    """The shown `explains` edges, then the shown `uses` edges, each by edge id."""
    project.index.sync()
    params = _params(attach_to, include_inferred)
    last = ""
    while True:
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT e.edge_id, e.edge_type, e.source, e.target, e.review_state, e.basis "
                    "FROM layer_edges e JOIN layer_nodes n ON n.node_id = e.source "
                    "JOIN interpretations i ON i.interpretation_id = e.source "
                    f"WHERE e.edge_type = 'explains' AND n.review_state IN {_LIVE} "
                    f"AND {_ATTACHED_INTERPRETATION} AND e.edge_id > :last "
                    "ORDER BY e.edge_id LIMIT :n"
                ),
                {**params, "last": last, "n": LAYER_PAGE},
            ).all()
        yield from (_edge(r) for r in rows)
        if len(rows) < LAYER_PAGE:
            break
        last = str(rows[-1][0])
    last = ""
    sql = (
        _uses_cte(attach_to is not None)
        + _SHOWN
        + "SELECT edge_id, 'uses', source, target, review_state, basis FROM shown "
        "WHERE edge_id > :last ORDER BY edge_id LIMIT :n"
    )
    while True:
        with project.index.connect() as conn:
            rows = conn.execute(text(sql), {**params, "last": last, "n": LAYER_PAGE}).all()
        yield from (_edge(r) for r in rows)
        if len(rows) < LAYER_PAGE:
            break
        last = str(rows[-1][0])


def _edge(r: Any) -> LayerEdge:
    state = str(r[4])
    return LayerEdge(
        edge_id=str(r[0]),
        edge_type=r[1],
        source=str(r[2]),
        target=str(r[3]),
        class_=LAYER_CLASS,
        review_state=state,
        label=layer_label(state),
        basis=None if r[5] is None else str(r[5]),
    )


def layer_hidden(
    project: Project,
    *,
    attach_to: Collection[str] | None = None,
    include_inferred: bool = False,
) -> LayerHidden:
    """The hidden counts of a view: interpretations within the attached nodes, concepts and links
    over the whole layer, and `uses` edges in scope dropped for a hidden endpoint."""
    project.index.sync()
    params = _params(attach_to, include_inferred)
    with project.index.connect() as conn:
        interp: dict[Any, Any] = dict(
            conn.execute(
                text(
                    "SELECT i.review_state, COUNT(*) FROM interpretations i "
                    "WHERE i.review_state IN ('wrong', 'superseded') "
                    f"AND {_ATTACHED_INTERPRETATION} GROUP BY i.review_state"
                ),
                params,
            ).all()
        )
        endpoint = conn.execute(
            text(
                _uses_cte(attach_to is not None)
                + "bad AS (SELECT a.edge_id FROM allowed a JOIN reach r ON r.edge_id = a.edge_id "
                "WHERE a.target NOT IN (SELECT concept_id FROM vis) "
                "OR (substr(a.source, 1, 4) = 'cpt_' AND a.source NOT IN "
                "(SELECT concept_id FROM vis))) SELECT COUNT(*) FROM bad"
            ),
            params,
        ).scalar_one()
        found = conn.execute(
            text(
                "SELECT item, reason, n FROM layer_hidden WHERE item IN ('concept', 'concept_link')"
            )
        ).all()
    n = {(str(i), str(r)): int(c) for i, r, c in found}
    return LayerHidden(
        interpretations=InterpretationHidden(
            wrong=int(interp.get("wrong", 0)), superseded=int(interp.get("superseded", 0))
        ),
        concepts=ConceptHidden(
            unapproved=n.get(("concept", "unapproved"), 0),
            wrong=n.get(("concept", "wrong"), 0),
            merged=n.get(("concept", "merged"), 0),
            links_inferred=n.get(("concept_link", "inferred"), 0),
            links_rejected=n.get(("concept_link", "rejected"), 0),
        ),
        endpoint_hidden=int(endpoint),
    )


def layer_graph(
    project: Project,
    *,
    attach_to: Collection[str] | None = None,
    include_inferred: bool = False,
) -> LayerGraph:
    """The visible layer as one value: nodes and edges by id and the hidden counts. With
    `attach_to` it is bounded by the view; without it it is the whole layer (small projects and
    tests; a whole-layer export streams `iter_layer_nodes` / `iter_layer_edges` instead)."""
    return LayerGraph(
        nodes=list(
            iter_layer_nodes(project, attach_to=attach_to, include_inferred=include_inferred)
        ),
        edges=list(
            iter_layer_edges(project, attach_to=attach_to, include_inferred=include_inferred)
        ),
        hidden=layer_hidden(project, attach_to=attach_to, include_inferred=include_inferred),
    )


def layer_counts(project: Project) -> LayerCounts:
    """The layer's counts by SQL aggregates, separate from every evidence count."""
    project.index.sync()
    with project.index.connect() as conn:
        interp: dict[Any, Any] = dict(
            conn.execute(
                text("SELECT review_state, COUNT(*) FROM interpretations GROUP BY review_state")
            ).all()
        )
        concepts: dict[Any, Any] = dict(
            conn.execute(
                text("SELECT review_state, COUNT(*) FROM concepts GROUP BY review_state")
            ).all()
        )
        unapproved = conn.execute(
            text("SELECT COUNT(*) FROM concepts WHERE source_state != 'approved'")
        ).scalar_one()
        uses: dict[Any, Any] = dict(
            conn.execute(text("SELECT status, COUNT(*) FROM concept_uses GROUP BY status")).all()
        )
        explains = conn.execute(
            text(
                "SELECT COUNT(*) FROM layer_edges e JOIN layer_nodes n ON n.node_id = e.source "
                f"WHERE e.edge_type = 'explains' AND n.review_state IN {_LIVE}"
            )
        ).scalar_one()
    return LayerCounts(
        interpretations={s.value: int(interp.get(s.value, 0)) for s in ReviewState},
        concepts={
            **{s.value: int(concepts.get(s.value, 0)) for s in ConceptState},
            "unapproved": int(unapproved),
        },
        explains=int(explains),
        uses={s.value: int(uses.get(s.value, 0)) for s in LinkStatus},
        hidden=layer_hidden(project),
    )
