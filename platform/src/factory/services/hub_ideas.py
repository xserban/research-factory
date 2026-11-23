"""The `ideas` hub payload (page "Ideas") and the researcher's decisions on it.

Invariants:
- `build` is pure over its `HubContext`: it reads the project through the lineage, relation, idea
  and contribution services (the index, never the JSONL), writes nothing and calls no model or
  network. Output is deterministic: every list is sorted by a stated key.
- Nothing is invented. A node is a work read for contributions (or the end of a relation) or an
  idea; an edge is a stored relation (`builds-on`, `improves-on`) with its effective status, a
  `cites` edge between two shown works, or an idea-to-idea edge the lineage service derives from
  member edges. Each relation carries its basis item's quote and anchor and who proposed it.
- Agent-written items and every relation not yet confirmed are proposals, never findings: the
  payload says so in `methods` and marks each such edge `proposal`.
- The graph is capped: at most `NODE_CAP` nodes, `ITEM_CAP` items per node, `CITES_CAP` citation
  edges; every cut is counted in `omitted`.
- The acts at the end are the researcher's human-only decisions. They add no rule of their own:
  the proposer is not the evaluator, a confirmation applies to inferred relations only and a
  rationale is required, all enforced by `relations.decide_relation` and `ideas.decide_idea`.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.lineage.graph import Direction, GraphEdge, GraphFilter, Neighbours
from factory.lineage.paths import LINEAGE_TYPES, MAX_DEPTH, ancestors
from factory.model.extraction import Scope
from factory.model.lineage import EdgeStatus, EdgeType, LineageDecision
from factory.services import ideas as ideas_service
from factory.services import relations as relations_service
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.contributions import ItemView, final_items
from factory.services.extraction import scope_population
from factory.services.lineage import index_neighbours

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

NODE_CAP = 250
ITEM_CAP = 12
CITES_CAP = 400
RELATION_CAP = 2000
LINEAGE_FILTER = GraphFilter(include_inferred=True, include_stale=True)

EVENT_PREFIXES = (
    "extraction.",  # contribution items and their staleness
    "relation.",
    "idea.",
    "reference.",  # a stated relation rests on a resolved reference link
    "document.",  # a converted document makes an item stale
    "notice.",  # a retracted work is no basis
    "dedup.",  # a merged work reads as its primary
    "screening.",  # the included works (the population) and the works table
    "decision.",
    "search.",
    "import.",
    "seed.",
)
"""The event type prefixes the payload reads (its cache key); none of the runner, task, feed or
watch families that the live pilot writes constantly."""

METHODS: dict[str, str] = {
    "page": (
        "The lineage of ideas across the papers read for their contributions: which paper builds "
        "on or improves on which earlier paper or named idea. Everything here was proposed by a "
        "reading agent and is a proposal until you confirm it; the quotes are the evidence."
    ),
    "overview": (
        "Works read is the number of included works with at least one final contribution item. "
        "Items are the final (agreed or resolved) contribution items. Ideas and relations are "
        "counted by their current status, superseded ones excluded."
    ),
    "graph": (
        "Columns are publication years of the works (an idea sits in the year of its origin "
        "work). Solid lines are relations the paper's own reference list backs (stated) or you "
        "confirmed; dashed lines are proposals no one has checked; dotted lines need re-checking "
        "or are derived between ideas. Rejected relations are hidden until you ask for them."
    ),
    "status": (
        "Stated: the item cites a reference entry that resolves to the target. Proposed: the "
        "platform could not tie the item to the target through the references (target differs, no "
        "cited entry, link unconfirmed or no basis item). Confirmed and rejected are your "
        "decisions. Needs re-checking: the item the relation rests on changed after the "
        "proposal."
    ),
    "path": (
        "From the chosen work or idea, every earlier work or idea reached by following builds-on "
        "and improves-on relations, up to a fixed depth, including proposals and relations that "
        "need re-checking. A work or idea with nothing further back is shown as the start of "
        "the chain."
    ),
    "needs": (
        "Relations whose status is proposed, and ideas not yet confirmed, newest first. Only "
        "you decide them, and never from the session that proposed them."
    ),
}

STEPS: tuple[dict[str, str], ...] = (
    {
        "id": "contributions",
        "what": "No contribution items are recorded yet.",
        "step": (
            "The skill rf-contributions reads each included work twice and records what it "
            "builds on and adds, with a quote for each."
        ),
    },
    {
        "id": "lineage",
        "what": "No relations or ideas are recorded yet.",
        "step": (
            "The skill rf-lineage, run after rf-contributions in a separate Claude Code session, "
            "proposes builds-on and improves-on relations and names ideas."
        ),
    },
)


def _population(project: Project) -> list[str]:
    try:
        return scope_population(project, Scope.CONTRIBUTION)
    except FactoryValidationError:
        return []


def _events(project: Project, ids: Collection[str]) -> dict[str, dict[str, str | None]]:
    """The recording event of each id: when, by what kind of actor, and with which model."""
    if not ids:
        return {}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, ts, actor_kind, actor_id, model, skill FROM events "
                "WHERE id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": json.dumps(sorted(set(ids)))},
        ).all()
    return {
        str(r[0]): {
            "ts": str(r[1]),
            "kind": str(r[2]),
            "id": str(r[3]),
            "model": None if r[4] is None else str(r[4]),
            "skill": None if r[5] is None else str(r[5]),
        }
        for r in rows
    }


def _work_facts(project: Project, ids: Collection[str]) -> dict[str, dict[str, Any]]:
    """Title, publication year and corpus membership of each work id (unknown ids omitted)."""
    papers = sorted(i for i in set(ids) if not i.startswith("ida_"))
    if not papers:
        return {}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT w.work_id, json_extract(w.data, '$.title'), "
                "substr(json_extract(w.data, '$.dates.published'), 1, 4) FROM works w "
                "WHERE w.work_id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": json.dumps(papers)},
        ).all()
    out: dict[str, dict[str, Any]] = {}
    for work, title, year in rows:
        y = str(year) if year is not None and str(year).isdigit() else None
        out[str(work)] = {"title": None if title is None else str(title), "year": y}
    return out


def _item_row(item: ItemView) -> dict[str, Any]:
    return {
        "id": item.extraction_id,
        "kind": item.item_kind,
        "name": item.name,
        "statement": item.statement,
        "quote": item.quote,
        "anchor": item.anchor,
        "cited_entry": item.cited_entry,
        "stale": item.stale,
    }


def _proposer(event: dict[str, str | None] | None) -> dict[str, str | None]:
    if event is None:
        return {"kind": None, "id": None, "model": None}
    return {"kind": event["kind"], "id": event["id"], "model": event["model"]}


def _all_relations(project: Project) -> list[relations_service.RelationView]:
    out: list[relations_service.RelationView] = []
    while len(out) < RELATION_CAP:
        page = relations_service.list_relations(
            project, statuses=frozenset(EdgeStatus), limit=500, offset=len(out)
        )
        out += page
        if len(page) < 500:
            break
    return out


def _all_ideas(project: Project) -> list[ideas_service.IdeaView]:
    out: list[ideas_service.IdeaView] = []
    while True:
        page = ideas_service.list_ideas(
            project, include_unconfirmed=True, limit=ideas_service.PAGE, offset=len(out)
        )
        out += page
        if len(page) < ideas_service.PAGE:
            return out


def _rejected_ideas(project: Project) -> int:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM ideas WHERE superseded_by IS NULL AND decision = 'reject'")
        ).scalar_one()
    return int(row)


def _empty_counts() -> dict[str, Any]:
    return {
        "population": 0,
        "works_read": 0,
        "items": 0,
        "items_by_kind": {},
        "ideas": {"proposed": 0, "confirmed": 0, "rejected": 0},
        "relations": {s.value: 0 for s in EdgeStatus},
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `ideas` page; see the module docstring."""
    with entering():
        return _build(ctx.project)


def _build(project: Project) -> dict[str, Any]:
    project.index.sync()
    population = _population(project)
    items = final_items(project)
    relations = _all_relations(project)
    ideas = _all_ideas(project)
    rejected_ideas = _rejected_ideas(project)

    counts = _empty_counts()
    counts["population"] = len(population)
    counts["works_read"] = len({i.work_id for i in items})
    counts["items"] = len(items)
    counts["items_by_kind"] = dict(sorted(Counter(i.item_kind for i in items).items()))
    counts["ideas"] = {
        "proposed": sum(1 for i in ideas if i.state == "proposed"),
        "confirmed": sum(1 for i in ideas if i.state == "confirmed"),
        "rejected": rejected_ideas,
    }
    for r in relations:
        counts["relations"][r.effective.value] += 1

    base: dict[str, Any] = {
        "ready": True,
        "methods": dict(METHODS),
        "counts": counts,
        "caps": {"nodes": NODE_CAP, "items": ITEM_CAP, "cites": CITES_CAP},
    }
    if not items and not relations and not ideas:
        missing = [dict(s) for s in STEPS]
        return {
            **base,
            "empty": True,
            "missing": missing,
            "nodes": [],
            "edges": [],
            "needs": [],
            "paths": {},
            "omitted": {"nodes": 0, "edges": 0, "items": 0, "cites": 0},
        }

    by_work: dict[str, list[ItemView]] = {}
    for item in items:
        by_work.setdefault(item.work_id, []).append(item)
    for rows in by_work.values():
        rows.sort(key=lambda i: (i.item_kind, i.extraction_id))
    basis_of: dict[str, ItemView] = {}
    for item in items:
        for source in item.sources.values():
            basis_of.setdefault(source.extraction_id, item)

    # --- nodes: relation ends first, then the other works read; cut at NODE_CAP ---
    survivor = {
        r.target: ideas_service.resolve_idea(project, r.target)
        for r in relations
        if r.target.startswith("ida_")
    }
    ends = {r.source_work for r in relations} | {
        r.target for r in relations if not r.target.startswith("ida_")
    }
    read = set(by_work)
    wanted = sorted(ends | read)
    facts = _work_facts(project, [*wanted, *(i.origin for i in ideas)])
    rank = {w: (0 if w in ends else 1, facts.get(w, {}).get("year") or "9999", w) for w in wanted}
    kept = sorted(wanted, key=lambda w: rank[w])[: max(0, NODE_CAP - len(ideas))]
    shown_works = set(kept)
    omitted_nodes = len(wanted) - len(kept)
    omitted_items = 0

    nodes: list[dict[str, Any]] = []
    for w in sorted(shown_works):
        f = facts.get(w, {})
        rows = by_work.get(w, [])
        omitted_items += max(0, len(rows) - ITEM_CAP)
        nodes.append(
            {
                "id": w,
                "kind": "paper",
                "label": f.get("title") or w,
                "year": f.get("year"),
                "in_corpus": w in facts,
                "read": w in read,
                "items": [_item_row(i) for i in rows[:ITEM_CAP]],
                "items_total": len(rows),
            }
        )
    idea_events = _events(project, [i.event_id for i in ideas])
    for idea in ideas:
        name_item = basis_of.get(idea.name_item)
        origin_year = facts.get(idea.origin, {}).get("year")
        nodes.append(
            {
                "id": idea.idea_id,
                "kind": "idea",
                "label": idea.name,
                "year": origin_year,
                "state": idea.state,
                "origin": idea.origin,
                "members": list(idea.effective_members),
                "name_item": None if name_item is None else _item_row(name_item),
                "proposer": _proposer(idea_events.get(idea.event_id)),
                "proposed_at": (idea_events.get(idea.event_id) or {}).get("ts"),
                "proposal": idea.state != "confirmed",
            }
        )
    node_ids = {n["id"] for n in nodes}

    # --- edges: stored relations of every status, then citations among the shown works ---
    rel_events = _events(project, [r.event_id for r in relations])
    notes = relations_service.relation_notes(project, [r.relation_id for r in relations])
    edges: list[dict[str, Any]] = []
    omitted_edges = 0
    for r in relations:
        target = survivor.get(r.target, r.target)  # a merged idea reads as its survivor
        if r.source_work not in node_ids or target not in node_ids:
            omitted_edges += 1
            continue
        basis = None if r.basis_item is None else basis_of.get(r.basis_item)
        ev = rel_events.get(r.event_id)
        edges.append(
            {
                "id": r.relation_id,
                "kind": r.edge_type,
                "source": r.source_work,
                "target": target,
                "status": r.effective.value,
                "reason": None if r.status_reason is None else r.status_reason.value,
                "decision": None if r.decision is None else r.decision.value,
                "stale_reasons": list(r.stale_reasons),
                "flags": list(r.flags),
                "basis": r.basis_item,
                "basis_item": None if basis is None else _item_row(basis),
                "note": notes.get(r.relation_id),
                "proposer": _proposer(ev),
                "proposed_at": None if ev is None else ev["ts"],
                "proposal": r.effective not in (EdgeStatus.CONFIRMED, EdgeStatus.REJECTED),
            }
        )

    nb = index_neighbours(project, LINEAGE_FILTER)
    cites_nb = index_neighbours(
        project,
        GraphFilter(
            include_inferred=True,
            include_stale=True,
            edge_types=(EdgeType.CITES,),
            include_ideas=False,
        ),
    )
    cites: list[dict[str, Any]] = []
    omitted_cites = 0
    for w in sorted(shown_works):
        for e in cites_nb(w, "out", frozenset({EdgeType.CITES})):
            if e.target not in shown_works or e.target == w:
                continue
            if len(cites) >= CITES_CAP:
                omitted_cites += 1
                continue
            cites.append(
                {
                    "id": e.edge_id,
                    "kind": "cites",
                    "source": e.source,
                    "target": e.target,
                    "status": str(e.status),
                    "proposal": False,
                }
            )

    # --- lineage paths: ancestors of every node through builds-on / improves-on ---
    seen: dict[str, GraphEdge] = {}
    has_out: set[str] = set()

    def recording(node: str, direction: Direction, types: frozenset[EdgeType]) -> list[GraphEdge]:
        found = list(nb(node, direction, types))
        if direction == "out" and found:
            has_out.add(node)
        for e in found:
            seen[e.edge_id] = e
        return found

    rec: Neighbours = recording
    reached_by: dict[str, Any] = {}
    for node in sorted(node_ids):
        result = ancestors(rec, node, MAX_DEPTH)
        if any(n in node_ids for n in result.nodes):
            reached_by[node] = result
    paths: dict[str, dict[str, Any]] = {
        node: {
            "nodes": [n for n in result.nodes if n in node_ids],
            "edges": list(result.edges),
            "roots": [n for n in result.nodes if n in node_ids and n not in has_out],
            "truncated": result.truncated,
        }
        for node, result in reached_by.items()
    }
    known = {e["id"] for e in edges}
    for edge_id, g in sorted(seen.items()):
        if edge_id in known or g.edge_type not in LINEAGE_TYPES:
            continue
        if g.source in node_ids and g.target in node_ids:
            edges.append(
                {
                    "id": edge_id,
                    "kind": g.edge_type.value,
                    "source": g.source,
                    "target": g.target,
                    "status": str(g.status),
                    "proposal": False,
                    "derived": g.derived,
                }
            )
    edges.sort(key=lambda e: (e["source"], e["kind"], e["target"], e["id"]))
    cites.sort(key=lambda e: (e["source"], e["target"], e["id"]))

    needs: list[dict[str, Any]] = [
        {"type": "relation", "id": e["id"], "at": e["proposed_at"] or ""}
        for e in edges
        if e["status"] == EdgeStatus.INFERRED.value
    ] + [
        {"type": "idea", "id": n["id"], "at": n["proposed_at"] or ""}
        for n in nodes
        if n["kind"] == "idea" and n["state"] == "proposed"
    ]
    needs.sort(key=lambda n: (n["at"], n["id"]), reverse=True)

    return {
        **base,
        "empty": False,
        "missing": [dict(s) for s in STEPS if s["id"] == "lineage"] if not relations else [],
        "nodes": nodes,
        "edges": edges + cites,
        "needs": needs,
        "paths": paths,
        "omitted": {
            "nodes": omitted_nodes,
            "edges": omitted_edges,
            "items": omitted_items,
            "cites": omitted_cites,
        },
    }


# ---------------------------------------------------------------- the researcher's decisions


def _field(body: dict[str, Any], key: str, issues: list[ValidationIssue]) -> str:
    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value
    issues.append(ValidationIssue(key, "required"))
    return ""


def _decide(
    project: Project,
    actor: Actor,
    body: dict[str, Any],
    key: str,
    decision: LineageDecision,
) -> dict[str, object]:
    issues: list[ValidationIssue] = []
    target = _field(body, key, issues)
    rationale = _field(body, "rationale", issues)
    if issues:
        raise FactoryValidationError(issues)
    if key == "relation_id":
        event = relations_service.decide_relation(project, actor, target, decision, rationale)
    else:
        event = ideas_service.decide_idea(project, actor, target, decision, rationale)
    return {key: target, "decision": decision.value, "event_id": event}


def confirm_relation_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Confirm an inferred relation (`relation.decided`); `relation_id`, `rationale`."""
    return _decide(project, actor, body, "relation_id", LineageDecision.CONFIRM)


def reject_relation_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Reject a live relation (`relation.decided`); `relation_id`, `rationale`."""
    return _decide(project, actor, body, "relation_id", LineageDecision.REJECT)


def confirm_idea_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Confirm a proposed idea (`idea.decided`); `idea_id`, `rationale`."""
    return _decide(project, actor, body, "idea_id", LineageDecision.CONFIRM)


def reject_idea_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Reject a live idea (`idea.decided`); `idea_id`, `rationale`."""
    return _decide(project, actor, body, "idea_id", LineageDecision.REJECT)
