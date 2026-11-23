"""The `intuition` hub payload (page "Intuition"): interpretations of why ideas work (slice 3c),
their review queue and the background concepts.

Invariants:
- `build` is pure over its `HubContext`: it reads the project's index and conversions, writes
  nothing and calls no model or network. Every count is computed here.
- Every interpretation is labelled with the layer language of the spec (`class`
  `interpretation`, then its review state); nothing here presents one as a finding.
- Lists are capped (`QUEUE_CAP`, `REVIEWED_CAP`, `CONCEPT_CAP`, `LINK_CAP`) and every cap has the
  exact total beside it, so a page says how many were left out.
- Output is a function of the events: sorted by id, no clock, no randomness.
- The review itself is not here: the page posts to `act_review`, which calls
  `interpretations.review_interpretation` (the reviewer-is-not-author rule stays there).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.intuition.labels import LAYER_CLASS, layer_label
from factory.model.intuition import ReviewState
from factory.model.screening import Channel
from factory.services import concepts as concepts_service
from factory.services import interpretations as interpretations_service
from factory.services.context import Project
from factory.services.hub_chat import _paragraph
from factory.services.ideas import confirmed_ideas, idea_view
from factory.services.search import get_work

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

QUEUE_CAP = 40
REVIEWED_CAP = 60
CONCEPT_CAP = 150
LINK_CAP = 400
PASSAGE_CAP = 4000
NOTE_CAP = 2000

METHODS: dict[str, str] = {
    "summary": (
        "Interpretations by review state, counted from the events. An interpretation is an "
        "agent's reading of why an idea or a paper works, bound to quotes of its source; it is "
        "never a finding. Wrong and superseded ones are counted and hidden from the lists."
    ),
    "queue": (
        "Interpretations no human has reviewed yet, by id. Each shows the text, the quotes it "
        "is bound to with their anchors, and the whole paragraph of each quote. The platform "
        "checked that every quote is in its paragraph; it did not check that the reading is "
        "right. That is your judgement."
    ),
    "reviewed": (
        "Interpretations a human has reviewed: right (reviewed) or wrong, with the note the "
        "reviewer left. The latest review stands; a wrong verdict needs a note."
    ),
    "concepts": (
        "Background concepts: named notions an interpretation may lean on, each with a source "
        "the researcher approved. The ideas listed under a concept are the ones a confirmed or "
        "stated link says use it. Concepts and links are agent-written too."
    ),
}

PRODUCER = (
    "Interpretations come from the skill rf-intuition, run in a separate Claude Code session "
    "after the lineage ideas are confirmed. Nothing here is written by the hub itself."
)


def _idea_name(project: Project, node: str, memo: dict[str, str]) -> str:
    if node not in memo:
        if node.startswith("ida_"):
            view = idea_view(project, node)
            memo[node] = node if view is None else view.name
        else:
            found = get_work(project, node)
            memo[node] = node if found is None else str(found.title)
    return memo[node]


def _sources(project: Project, view: Any, cache: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.sources:
        row: dict[str, Any] = {
            "kind": s.kind,
            "role": str(s.role),
            "work_id": s.work_id,
            "anchor": s.anchor,
            "quote": s.quote,
            "reference": s.reference,
            "link_state": s.link_state,
            "paragraph": "",
            "paragraph_cut": False,
        }
        if s.kind == "quote" and s.conversion_id and s.anchor and s.quote:
            shown, _span = _paragraph(project, s.conversion_id, s.anchor, s.quote, cache)
            row["paragraph"] = shown[:PASSAGE_CAP]
            row["paragraph_cut"] = len(shown) > PASSAGE_CAP
        out.append(row)
    return out


def _sessions(project: Project, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT interpretation_id, writer_session FROM interpretations "
                "WHERE interpretation_id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": json.dumps(ids)},
        ).all()
    return {str(r[0]): str(r[1]) for r in rows}


def _last_review(project: Project, interpretation_id: str) -> dict[str, Any] | None:
    reviews = [
        h
        for h in interpretations_service.interpretation_history(project, interpretation_id)
        if h.kind == "reviewed"
    ]
    if not reviews:
        return None
    last = reviews[-1]
    return {
        "state": last.state,
        "by": last.actor,
        "note": last.note[:NOTE_CAP],
        "self_reviewed": last.self_reviewed,
    }


def _items(
    project: Project,
    views: list[Any],
    names: dict[str, str],
    with_review: bool,
) -> list[dict[str, Any]]:
    cache: dict[str, Any] = {}
    sessions = _sessions(project, [v.interpretation_id for v in views])
    return [
        {
            "id": v.interpretation_id,
            "class": LAYER_CLASS,
            "label": layer_label(v.review_state),
            "state": v.review_state,
            "subject": v.target,
            "subject_kind": v.target_kind,
            "subject_name": _idea_name(project, v.target, names),
            "text": v.text,
            "sources": _sources(project, v, cache),
            "author": v.author,
            "writer": v.writer,
            "session": sessions.get(v.interpretation_id, ""),
            "source_stale": list(v.source_stale),
            "review": _last_review(project, v.interpretation_id) if with_review else None,
        }
        for v in views
    ]


def _concepts(project: Project, names: dict[str, str]) -> dict[str, Any]:
    listed: list[Any] = []
    cursor: str | None = None
    while len(listed) <= CONCEPT_CAP:
        page = concepts_service.list_concepts(project, cursor=cursor)
        listed += page.items
        cursor = page.next_cursor
        if cursor is None:
            break
    total = concepts_service.visible_concept_count(project)
    shown = listed[:CONCEPT_CAP]
    uses: dict[str, list[dict[str, Any]]] = {c.concept_id: [] for c in shown}
    links: list[Any] = []
    cursor = None
    while len(links) <= LINK_CAP:
        lpage = concepts_service.list_concept_links(project, cursor=cursor)
        links += lpage.items
        cursor = lpage.next_cursor
        if cursor is None:
            break
    for link in links[:LINK_CAP]:
        if link.concept_id in uses and link.from_kind in ("idea", "paper"):
            uses[link.concept_id].append(
                {
                    "node": link.from_node,
                    "kind": link.from_kind,
                    "name": _idea_name(project, link.from_node, names),
                    "status": str(link.status),
                }
            )
    return {
        "total": total,
        "omitted": max(0, total - len(shown)),
        "links_omitted": max(0, len(links) - LINK_CAP),
        "items": [
            {
                "id": c.concept_id,
                "class": LAYER_CLASS,
                "label": layer_label(c.review_state.value),
                "name": c.name,
                "aliases": list(c.aliases),
                "text": c.text or "",
                "source": None if c.source is None else c.source.citation,
                "ideas": sorted(uses[c.concept_id], key=lambda u: (u["name"], u["node"])),
            }
            for c in shown
        ],
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `intuition` page: counts, the review queue, the reviewed list and the
    background concepts, each capped with its exact total."""
    project = ctx.project
    counts = interpretations_service.review_counts(project)
    names: dict[str, str] = {}
    queue = interpretations_service.list_interpretations(
        project, states=[ReviewState.UNREVIEWED], limit=QUEUE_CAP
    )
    done = interpretations_service.list_interpretations(
        project, states=[ReviewState.REVIEWED, ReviewState.WRONG], limit=REVIEWED_CAP
    )
    unreviewed = counts[ReviewState.UNREVIEWED]
    reviewed_total = counts[ReviewState.REVIEWED] + counts[ReviewState.WRONG]
    concepts = _concepts(project, names)
    return {
        "ready": True,
        "methods": dict(METHODS),
        "producer": PRODUCER,
        "counts": {
            "unreviewed": unreviewed,
            "reviewed": counts[ReviewState.REVIEWED],
            "wrong": counts[ReviewState.WRONG],
            "superseded": counts[ReviewState.SUPERSEDED],
            "concepts": concepts["total"],
            "confirmed_ideas": len(confirmed_ideas(project)),
            "waiting_targets": interpretations_service.intuition_pending(project),
        },
        "empty": sum(counts.values()) == 0 and concepts["total"] == 0,
        "queue": {
            "items": _items(project, queue.items, names, with_review=False),
            "omitted": max(0, unreviewed - len(queue.items)),
        },
        "reviewed": {
            "items": _items(project, done.items, names, with_review=True),
            "omitted": max(0, reviewed_total - len(done.items)),
        },
        "concepts": concepts,
    }


def act_review(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """The researcher's review of one interpretation from the hub: `verdict` `reviewed` or
    `wrong`, optional `note` (required for `wrong`, which the service checks). The service
    refuses the author's own session, a non-human and an unknown id, writing nothing."""
    issues: list[ValidationIssue] = []
    iid = body.get("interpretation_id")
    verdict = body.get("verdict")
    note = body.get("note", "")
    if not isinstance(iid, str) or not iid.strip():
        issues.append(ValidationIssue("interpretation_id", "required"))
    if verdict == "reviewed" or verdict == "wrong":
        state: Literal["reviewed", "wrong"] = verdict
    else:
        state = "reviewed"
        issues.append(ValidationIssue("verdict", "must be reviewed or wrong"))
    if not isinstance(note, str) or len(note) > NOTE_CAP:
        issues.append(ValidationIssue("note", "must be text of at most 2000 characters"))
    if issues:
        raise FactoryValidationError(issues)
    event_id = interpretations_service.review_interpretation(
        project, actor, str(iid), state, str(note), Channel.CLI
    )
    return {"interpretation_id": iid, "verdict": verdict, "event_id": event_id}
