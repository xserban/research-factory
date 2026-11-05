"""The portfolio across projects: derived stage, open work and pending human decisions each.

The stage is a pure first-match rule over `StageFacts` (spec 7a ruling 4); the facts are read from
existing services. The portfolio shows counts only: no label-derived rate, seed identifier or work
title, so its JSON is safe to hand to any agent (ruling 3).

Invariants: `derive_stage` is total and its rows are tried in order; reading a project writes no
event (each project is opened under a fresh session and only its index may refresh); a project that
cannot be read becomes a row with `error` (the exception class name) and the others still build;
the output is a function of the events and `as_of`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from factory.clock import Clock, parse_ts
from factory.config import Settings
from factory.errors import FactoryError
from factory.model.base import StrictModel
from factory.model.identity import IdGenerator
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolStatus
from factory.model.references import Direction
from factory.model.search import QueryPurpose, RunStatus
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items
from factory.services.context import Project, list_projects, open_project
from factory.services.extraction import unit_states
from factory.services.human_queue import HumanQueue, extraction_disagreement_count
from factory.services.prisma import full_text_boxes, has_full_text_plan, prisma_flow
from factory.services.project import ProtocolSummary, project_status
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


# --- The portfolio ---


class PortfolioRow(StrictModel):
    """One project: counts and the derived stage only, never a label-derived rate, seed
    identifier or work title. An unreadable project has `error` and no other figure."""

    slug: str
    rigor_mode: RigorMode | None = None
    question_id: str | None = None
    protocol_id: str | None = None
    protocol_status: ProtocolStatus | None = None
    press: Literal["none", "reviewed", "confirmed"] | None = None
    stage: Stage | None = None
    tasks_open: int = 0
    tasks_claimed: int = 0
    tasks_expired: int = 0
    works: int = 0
    ta_included: int = 0
    ft_included: int = 0
    last_event_at: datetime | None = None
    last_search_at: datetime | None = None
    human: HumanQueue = HumanQueue(items=[])
    error: str | None = None


class Portfolio(StrictModel):
    """The JSON contract (`schema_version` 1): rows sorted by slug, timestamps as recorded."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    projects: list[PortfolioRow]


def portfolio(settings: Settings, *, clock: Clock, as_of: datetime) -> Portfolio:
    """Every project under the root, sorted by slug; `as_of` is only stamped on the result."""
    ids = IdGenerator(clock)
    rows = [_row(settings, slug, ids.ulid(), clock) for slug in list_projects(settings)]
    return Portfolio(generated_at=as_of, projects=rows)


def _row(settings: Settings, slug: str, session: str, clock: Clock) -> PortfolioRow:
    try:
        project = open_project(settings, slug, session=session, clock=clock)
        status = project_status(project)
        flow = prisma_flow(project)
        stage = derive_stage(stage_facts(project))
        last_search = _last_search_at(project)
    except (FactoryError, ValidationError, OSError, SQLAlchemyError) as exc:
        return PortfolioRow(slug=slug, error=type(exc).__name__)
    protocol: ProtocolSummary | None = status.protocol
    return PortfolioRow(
        slug=slug,
        rigor_mode=status.rigor_mode,
        question_id=status.question,
        protocol_id=None if protocol is None else protocol.protocol_id,
        protocol_status=None if protocol is None else protocol.status,
        press=None if protocol is None else protocol.press,
        stage=stage,
        tasks_open=status.tasks.open,
        tasks_claimed=status.tasks.claimed,
        tasks_expired=status.tasks.expired,
        works=status.works,
        ta_included=flow.included,
        ft_included=flow.full_text.included,
        last_event_at=status.last_event_at,
        last_search_at=last_search,
        human=status.human or HumanQueue(items=[]),
    )


def _last_search_at(project: Project) -> datetime | None:
    """When the latest search-purpose run finished; None before any run finished."""
    with project.index.connect() as conn:
        latest = conn.execute(
            text(
                "SELECT MAX(r.finished_at) FROM runs r JOIN queries q ON q.query_id = r.query_id "
                "WHERE q.purpose != :probe AND r.finished_at IS NOT NULL"
            ),
            {"probe": QueryPurpose.PROBE.value},
        ).scalar_one()
    return None if latest is None else parse_ts(str(latest))
