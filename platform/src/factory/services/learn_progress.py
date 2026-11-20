"""Where a project stands on each tutorial stage, derived only from facts that exist already.

Sources: `project_stage.stage_facts` (the facts the stage rule reads), the human queue, and
counts of events by type prefix from the index. Invariants: read-only (no event, no table); no
judgement (a stage with no computed finish, such as understand, is never `done`); a stage with
a waiting human gate is `blocked-by-human-gate`; the next step is text of the stage data, never
generated. `derive` is pure over its three inputs so that it is testable without a project.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlalchemy import text

from factory.learn.stages import STAGES, stage_card
from factory.services.context import Project
from factory.services.human_queue import Gate, HumanItem, human_queue
from factory.services.project_stage import StageFacts, stage_facts


class StageState(StrEnum):
    NOT_STARTED = "not-started"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    BLOCKED = "blocked-by-human-gate"


ACTIVITY: Final[dict[str, tuple[str, ...]]] = {
    "gather": ("dedup.", "inbox.", "import."),
    "screen": ("screening.decision_recorded",),
    "acquire": ("fulltext.", "document."),
    "extract": ("extraction.", "miner.", "mine.", "mining."),
    "understand": ("contribution.", "relation.", "idea.", "interpretation.", "region."),
    "develop": ("lead.", "hypothesis.", "sheet.", "chat."),
    "write": ("draft.",),
    "maintain": ("watch.", "feed."),
}
"""Event type prefixes whose presence shows that a stage has begun. Gather counts no search
event: a probe is a search too, and the facts count the complete runs of the real search."""

RELEASED: Final = "draft.released"

_GATE_STAGE: Final[dict[Gate, str]] = {
    Gate.PRESS_CONFIRMATION: "frame",
    Gate.CALIBRATION_LABELS: "screen",
    Gate.SCREENING_DISAGREEMENTS: "screen",
    Gate.SCREENING_AUDIT: "screen",
    Gate.EXTRACTION_DISAGREEMENTS: "extract",
    Gate.EXTRACTION_AUDIT: "extract",
    Gate.IMPORT_CONFIRMATION: "gather",
    Gate.IMPORT_ADMISSION: "gather",
    Gate.ATTACHMENTS_WAITING: "acquire",
    Gate.DOCUMENTS_UNCONVERTED: "acquire",
    Gate.INBOX_OPEN: "gather",
    Gate.VERSION_PAIRS: "gather",
}


@dataclass(frozen=True)
class WaitingGate:
    gate: str
    count: int
    command: str


@dataclass(frozen=True)
class StageProgress:
    stage_id: str
    state: StageState
    facts: tuple[str, ...]
    waiting: tuple[WaitingGate, ...]
    next_step: str


def gate_stage(item: HumanItem) -> str:
    """The tutorial stage a human queue item belongs to (full-text screening gates: acquire)."""
    if item.stage == "full-text" and _GATE_STAGE[item.gate] == "screen":
        return "acquire"
    return _GATE_STAGE[item.gate]


def activity_counts(project: Project) -> dict[str, int]:
    """Events per tutorial stage by type prefix, plus `released` (draft.released)."""
    out: dict[str, int] = {}
    with project.index.connect() as conn:
        for stage, prefixes in ACTIVITY.items():
            clause = " OR ".join(f"type LIKE :p{i}" for i in range(len(prefixes)))
            params = {f"p{i}": p + ("%" if p.endswith(".") else "") for i, p in enumerate(prefixes)}
            sql = text(f"SELECT COUNT(*) FROM events WHERE {clause}")
            out[stage] = int(conn.execute(sql, params).scalar() or 0)
        out["released"] = int(
            conn.execute(
                text("SELECT COUNT(*) FROM events WHERE type = :t"), {"t": RELEASED}
            ).scalar()
            or 0
        )
    return out


def _state(stage: str, f: StageFacts, n: dict[str, int]) -> StageState:
    began = n.get(stage, 0) > 0
    started = StageState.IN_PROGRESS if began else StageState.NOT_STARTED
    if stage == "frame":
        pressed = f.press_confirmed or not f.press_required
        if f.has_question and f.has_protocol and f.protocol_ready and pressed:
            return StageState.DONE
        return (
            StageState.IN_PROGRESS if f.has_question or f.has_protocol else StageState.NOT_STARTED
        )
    if stage == "gather":
        if f.complete_search_runs == 0:
            return started
        return StageState.IN_PROGRESS if f.snowball_plan and f.snowball_open else StageState.DONE
    if stage == "screen":
        if not began:
            return StageState.NOT_STARTED
        return StageState.IN_PROGRESS if f.ta_pending > 0 else StageState.DONE
    if stage == "acquire":
        if not began:
            return StageState.NOT_STARTED
        return StageState.IN_PROGRESS if (f.ft_open > 0 or not f.ft_plan) else StageState.DONE
    if stage == "extract":
        if not began:
            return StageState.NOT_STARTED
        done = f.extraction_schema and f.extraction_open == 0
        return StageState.DONE if done else StageState.IN_PROGRESS
    if stage == "write":
        if n.get("released", 0) > 0:
            return StageState.DONE
        return started
    return started  # understand, develop, maintain: no computed finish


def _protocol_word(f: StageFacts) -> str:
    if f.protocol_ready:
        return "ready"
    return "recorded" if f.has_protocol else "none"


def _facts_text(stage: str, f: StageFacts, n: dict[str, int]) -> tuple[str, ...]:
    if stage == "frame":
        return (
            f"question recorded: {'yes' if f.has_question else 'no'}",
            f"protocol: {_protocol_word(f)}",
            f"PRESS confirmed: {'yes' if f.press_confirmed else 'no'}"
            + ("" if f.press_required else " (not required in this mode)"),
        )
    if stage == "gather":
        return (f"complete search runs: {f.complete_search_runs}",)
    if stage == "screen":
        return (f"works pending at title and abstract: {f.ta_pending}",)
    if stage == "acquire":
        return (
            f"full-text plan in the protocol: {'yes' if f.ft_plan else 'no'}",
            f"works not yet through full text: {f.ft_open}",
        )
    if stage == "extract":
        return (
            f"extraction schema in the protocol: {'yes' if f.extraction_schema else 'no'}",
            f"units or disagreements open: {f.extraction_open}",
        )
    if stage == "write":
        return (f"drafts released: {n.get('released', 0)}",)
    return (f"events of this stage: {n.get(stage, 0)}",)


def derive(
    facts: StageFacts, activity: dict[str, int], items: list[HumanItem]
) -> list[StageProgress]:
    """One `StageProgress` per tutorial stage, in order. Pure."""
    out: list[StageProgress] = []
    for card in STAGES:
        waiting = tuple(
            WaitingGate(i.gate.value, i.count, i.command) for i in items if gate_stage(i) == card.id
        )
        state = _state(card.id, facts, activity)
        if waiting:
            state = StageState.BLOCKED
        out.append(
            StageProgress(
                card.id,
                state,
                _facts_text(card.id, facts, activity),
                waiting,
                _next_step(card.id, state, waiting),
            )
        )
    return out


def _next_step(stage_id: str, state: StageState, waiting: tuple[WaitingGate, ...]) -> str:
    card = stage_card(stage_id)
    assert card is not None
    if state is StageState.BLOCKED:
        w = waiting[0]
        return f"Waiting for you ({w.gate}, {w.count}): {w.command}"
    if state is StageState.NOT_STARTED:
        return card.steps[0].text
    if state is StageState.IN_PROGRESS:
        return f"Continue until: {card.done.condition}"
    nxt = stage_card(card.next_id) if card.next_id else None
    return f"Next stage: {nxt.title}." if nxt else "This is the last stage; the review stays open."


def project_progress(project: Project) -> list[StageProgress]:
    """The progress of `project`; reads only (it syncs the index)."""
    facts = stage_facts(project)
    return derive(facts, activity_counts(project), human_queue(project, agent=True).items)
