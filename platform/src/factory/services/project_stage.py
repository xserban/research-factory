"""The derived stage of one project: a pure first-match rule over facts read from services.

Spec 7a ruling 4. `project_status` and the portfolio both read it; it sits apart so that neither
pays for the other. Invariants: `derive_stage` is total and its rows are tried in order;
`stage_facts` writes no event. The stage is one word and names no work, seed or rate.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import text

from factory.model.project import RigorMode
from factory.model.protocol import ProtocolStatus
from factory.model.references import Direction
from factory.model.search import QueryPurpose, RunStatus
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items
from factory.services.context import Project
from factory.services.extraction import unit_states
from factory.services.human_queue import extraction_disagreement_count
from factory.services.prisma import full_text_boxes, has_full_text_plan
from factory.services.protocol import current_protocol
from factory.services.question import current_question
from factory.services.snowball import plan_round


class Stage(StrEnum):
    SCOPING = "scoping"
    PROTOCOL = "protocol"
    SEARCH = "search"
    TA_SCREENING = "ta-screening"
    FULL_TEXT = "full-text"
    EXTRACTION = "extraction"
    SNOWBALLING = "snowballing"
    REPORTING = "reporting"


@dataclass(frozen=True)
class StageFacts:
    """What the stage rule reads; every field is derived from a service."""

    has_question: bool
    has_protocol: bool
    protocol_ready: bool
    press_confirmed: bool
    press_required: bool
    complete_search_runs: int
    ta_pending: int
    ft_plan: bool
    ft_open: int
    extraction_schema: bool
    extraction_open: int
    snowball_plan: bool
    snowball_open: bool


_RULES: tuple[tuple[Callable[[StageFacts], bool], Stage], ...] = (
    (lambda f: not f.has_question or not f.has_protocol, Stage.SCOPING),
    (
        lambda f: not f.protocol_ready or (f.press_required and not f.press_confirmed),
        Stage.PROTOCOL,
    ),
    (lambda f: f.complete_search_runs == 0, Stage.SEARCH),
    (lambda f: f.ta_pending > 0, Stage.TA_SCREENING),
    (lambda f: f.ft_plan and f.ft_open > 0, Stage.FULL_TEXT),
    (lambda f: f.extraction_schema and f.extraction_open > 0, Stage.EXTRACTION),
    (lambda f: f.snowball_plan and f.snowball_open, Stage.SNOWBALLING),
)


def derive_stage(facts: StageFacts) -> Stage:
    """The first stage whose condition holds; `reporting` when none does."""
    for holds, stage in _RULES:
        if holds(facts):
            return stage
    return Stage.REPORTING


def stage_facts(project: Project) -> StageFacts:
    """Read the facts of `project` from its services; writes nothing."""
    project.index.sync()
    protocol = current_protocol(project)
    schema = None if protocol is None else protocol.spec.extraction_schema
    plan = None if protocol is None else protocol.spec.snowball_plan
    ft_plan = has_full_text_plan(project)
    boxes = full_text_boxes(project) if ft_plan else None
    return StageFacts(
        has_question=current_question(project) is not None,
        has_protocol=protocol is not None,
        protocol_ready=protocol is not None and protocol.status is ProtocolStatus.READY,
        press_confirmed=protocol is not None and protocol.press == "confirmed",
        press_required=_rigor_mode(project) in (RigorMode.PILOT, RigorMode.SYSTEMATIC),
        complete_search_runs=_complete_search_runs(project),
        ta_pending=_ta_pending(project),
        ft_plan=ft_plan,
        ft_open=0 if boxes is None else boxes.not_retrieved + boxes.pending,
        extraction_schema=schema is not None,
        extraction_open=0 if schema is None else _extraction_open(project),
        snowball_plan=plan is not None,
        snowball_open=plan is not None and _snowball_open(project),
    )


def _rigor_mode(project: Project) -> RigorMode:
    with project.index.connect() as conn:
        mode = conn.execute(text("SELECT rigor_mode FROM project")).scalar_one()
    return RigorMode(str(mode))


def _complete_search_runs(project: Project) -> int:
    """Complete runs of search-purpose queries; probe runs are not part of the search."""
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM runs r JOIN queries q ON q.query_id = r.query_id "
                    "WHERE r.status = :complete AND q.purpose NOT IN (:probe, :status)"
                ),
                {
                    "complete": RunStatus.COMPLETE.value,
                    "probe": QueryPurpose.PROBE.value,
                    "status": QueryPurpose.STATUS.value,
                },
            ).scalar_one()
        )


def _ta_pending(project: Project) -> int:
    """Works pending at title/abstract, calibration works left out."""
    calibration = set(calibration_items(project))
    return sum(
        1
        for work, outcome in final_outcomes(project).items()
        if outcome is Outcome.PENDING and work not in calibration
    )


def _extraction_open(project: Project) -> int:
    """Units whose extraction is not current, plus unresolved extraction disagreements."""
    units = sum(1 for unit in unit_states(project) if unit.state != "current")
    return units + extraction_disagreement_count(project)


def _snowball_open(project: Project) -> bool:
    """Whether the declared stopping rule has not yet stopped the backward direction: neither the
    round maximum nor the no-yield stop refuses another round."""
    stopped = {"round_no", "previous_round"}
    refusals = plan_round(project, Direction.BACKWARD).state.refusals
    return not any(issue.field in stopped for issue in refusals)
