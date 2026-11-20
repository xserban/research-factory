"""Payload of the hub Learn page: the tutorial stage cards and where this project stands on each.

Invariants:
- Read-only; no model is called. The text is `factory.learn` data, verbatim; the only computed
  parts are the progress of each stage (`learn_progress`) and `fresh`.
- `fresh` is true when the log holds no event of any stage after setup and search (`LATER`); the
  served hub then opens on this page (`landing_page`). It is a count of event types, no judgement.
- A reference carries its kind, its name and what to show: a command with `factory` before it, a
  hub page by title with its file. A page ref that names no hub page is an error of the data
  (the content test forbids it), never a dead link here.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Final

from factory.learn.concepts import CONCEPTS
from factory.learn.glossary import GLOSSARY
from factory.learn.model import Ref, RefKind
from factory.learn.stages import STAGES
from factory.services import hub_ui
from factory.services.context import Project
from factory.services.learn_progress import project_progress
from factory.services.site import TypeCounts, type_counts

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

__all__ = ["build", "fresh", "landing_page", "learn_payload", "ref_view"]

LATER: Final = (
    "screening.",
    "dedup.",
    "fulltext.",
    "document.",
    "extraction.",
    "miner.",
    "mine.",
    "reference.",
    "contribution.",
    "relation.",
    "idea.",
    "hypothesis.",
    "draft.",
    "watch.",
    "feed.",
)
HOW_IT_WORKS: Final = "platform.html#tab=how"
"""The run map of the Platform page; the Learn page points to it for the overview."""

METHODS: Final[dict[str, str]] = {
    "progress": (
        "Each stage is read from facts the platform already computes: the stage rule, counts of "
        "events by type, and the queue of acts waiting for a person. A stage with an act waiting "
        "for you shows as blocked. Stages with no computed finish are never shown as done."
    ),
    "content": (
        "The cards are written text. A test checks that every skill, tool, command and page "
        "they name exists. They state what is true of the code, not what happened in this project."
    ),
}


def ref_view(ref: Ref) -> dict[str, str]:
    """One reference as the page shows it: kind, name, label and (for a page) its file."""
    if ref.kind is RefKind.PAGE:
        spec = hub_ui.PAGES[ref.name]
        return {"kind": "page", "name": ref.name, "label": spec.title, "href": f"{ref.name}.html"}
    label = f"factory {ref.name}" if ref.kind is RefKind.CLI else ref.name
    return {"kind": ref.kind.value, "name": ref.name, "label": label, "href": ""}


def fresh(counts: TypeCounts) -> bool:
    """True when no event type of a stage after setup and search has been recorded."""
    return not any(t.startswith(LATER) for t in counts)


def landing_page(project: Project) -> str:
    """The page the served hub opens on: Learn for a fresh project, else Overview."""
    return "learn" if fresh(type_counts(project)) else "overview"


def learn_payload(project: Project) -> dict[str, Any]:
    progress = {p.stage_id: p for p in project_progress(project)}
    stages: list[dict[str, Any]] = []
    for card in STAGES:
        p = progress[card.id]
        stages.append(
            {
                "id": card.id,
                "title": card.title,
                "goal": card.goal,
                "acts": [a.value for a in card.acts],
                "gates": list(card.gates),
                "steps": [
                    {"actor": s.actor.value, "text": s.text, "refs": [ref_view(r) for r in s.refs]}
                    for s in card.steps
                ],
                "page": ref_view(card.page),
                "done": {
                    "condition": card.done.condition,
                    "shown_by": [ref_view(r) for r in card.done.shown_by],
                },
                "mistakes": list(card.mistakes),
                "rigour": list(card.rigour),
                "next_id": card.next_id,
                "progress": {
                    "state": p.state.value,
                    "facts": list(p.facts),
                    "waiting": [asdict(w) for w in p.waiting],
                    "next_step": p.next_step,
                },
            }
        )
    return {
        "ready": True,
        "fresh": fresh(type_counts(project)),
        "how_it_works": HOW_IT_WORKS,
        "methods": dict(METHODS),
        "stages": stages,
        "concepts": [asdict(c) for c in CONCEPTS],
        "glossary": [asdict(t) for t in GLOSSARY],
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The `learn` payload of the hub."""
    return learn_payload(ctx.project)
