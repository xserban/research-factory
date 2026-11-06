"""The portfolio across projects: derived stage, open work and pending human decisions each.

The stage rule lives in `services/project_stage.py`, where `project_status` reads it too, and is
exported here. The portfolio shows counts only: no label-derived rate, seed identifier or work
title, so its JSON is safe to hand to any agent (ruling 3).

Invariants: reading a project writes no event (each project is opened under a fresh session and
only its index may refresh); a project that cannot be read becomes a row with `error` (the exception
class name) and the others still build; the output is a function of the events and `as_of`.
"""

from datetime import datetime
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
from factory.model.search import QueryPurpose
from factory.services.context import Project, list_projects, open_project
from factory.services.human_queue import HumanQueue, human_queue
from factory.services.prisma import prisma_flow
from factory.services.project import ProtocolSummary, project_status
from factory.services.project_stage import Stage, StageFacts, derive_stage, stage_facts

# --- The portfolio ---


__all__ = [
    "Portfolio",
    "PortfolioRow",
    "Stage",
    "StageFacts",
    "derive_stage",
    "portfolio",
    "stage_facts",
]


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
        last_search = _last_search_at(project)
        human = human_queue(project, agent=True)  # the JSON is safe for any agent (ruling 3)
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
        stage=status.stage,
        tasks_open=status.tasks.open,
        tasks_claimed=status.tasks.claimed,
        tasks_expired=status.tasks.expired,
        works=status.works,
        ta_included=flow.included,
        ft_included=flow.full_text.included,
        last_event_at=status.last_event_at,
        last_search_at=last_search,
        human=human,
    )


def _last_search_at(project: Project) -> datetime | None:
    """When the latest search-purpose run finished; None before any run finished."""
    with project.index.connect() as conn:
        latest = conn.execute(
            text(
                "SELECT MAX(r.finished_at) FROM runs r JOIN queries q ON q.query_id = r.query_id "
                "WHERE q.purpose NOT IN (:probe, :status) AND r.finished_at IS NOT NULL"
            ),
            {"probe": QueryPurpose.PROBE.value, "status": QueryPurpose.STATUS.value},
        ).scalar_one()
    return None if latest is None else parse_ts(str(latest))
