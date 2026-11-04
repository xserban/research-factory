"""The derived stage (spec 7a ruling 4): a pure first-match rule over `StageFacts`, and the facts
read from four projects at known stages."""

from collections.abc import Callable, Mapping
from dataclasses import replace

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.portfolio import Stage, StageFacts, derive_stage, stage_facts
from factory.services.project import init_project
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION, ready_protocol, record_pilot_question
from tests.portfolio_helpers import fresh, ta_world

SourcesFor = Callable[..., Mapping[str, SourceFactory]]

REPORTING = StageFacts(
    has_question=True,
    has_protocol=True,
    protocol_ready=True,
    press_confirmed=True,
    press_required=True,
    complete_search_runs=2,
    ta_pending=0,
    ft_plan=True,
    ft_open=0,
    extraction_schema=True,
    extraction_open=0,
    snowball_plan=True,
    snowball_open=False,
)

CASES: list[tuple[str, dict[str, object], Stage]] = [
    ("no question", {"has_question": False}, Stage.SCOPING),
    ("no protocol", {"has_protocol": False, "protocol_ready": False}, Stage.SCOPING),
    ("protocol draft", {"protocol_ready": False}, Stage.PROTOCOL),
    ("press unconfirmed", {"press_confirmed": False}, Stage.PROTOCOL),
    ("press not required", {"press_confirmed": False, "press_required": False}, Stage.REPORTING),
    ("no complete run", {"complete_search_runs": 0}, Stage.SEARCH),
    ("ta pending", {"ta_pending": 3}, Stage.TA_SCREENING),
    ("ft open", {"ft_open": 2}, Stage.FULL_TEXT),
    ("ft open without plan", {"ft_plan": False, "ft_open": 2}, Stage.REPORTING),
    ("extraction open", {"extraction_open": 1}, Stage.EXTRACTION),
    (
        "extraction open without schema",
        {"extraction_schema": False, "extraction_open": 1},
        Stage.REPORTING,
    ),
    ("snowball open", {"snowball_open": True}, Stage.SNOWBALLING),
    (
        "snowball open without plan",
        {"snowball_plan": False, "snowball_open": True},
        Stage.REPORTING,
    ),
    ("nothing left", {}, Stage.REPORTING),
    # Precedence: the first matching row wins.
    ("scoping beats protocol", {"has_question": False, "protocol_ready": False}, Stage.SCOPING),
    ("protocol beats search", {"protocol_ready": False, "complete_search_runs": 0}, Stage.PROTOCOL),
    ("search beats screening", {"complete_search_runs": 0, "ta_pending": 4}, Stage.SEARCH),
    ("ta beats ft", {"ta_pending": 1, "ft_open": 1}, Stage.TA_SCREENING),
    ("ft beats extraction", {"ft_open": 1, "extraction_open": 1}, Stage.FULL_TEXT),
    ("extraction beats snowball", {"extraction_open": 1, "snowball_open": True}, Stage.EXTRACTION),
]


@pytest.mark.parametrize(("name", "change", "expected"), CASES, ids=[c[0] for c in CASES])
def test_derive_stage_table(name: str, change: dict[str, object], expected: Stage) -> None:
    assert derive_stage(replace(REPORTING, **change)) is expected  # type: ignore[arg-type]


def test_every_stage_is_reached() -> None:
    assert {derive_stage(replace(REPORTING, **c)) for _, c, _ in CASES} == set(Stage)  # type: ignore[arg-type]


def test_scoping_project(settings: Settings, clock: FixedClock) -> None:
    init_project(settings, "bare", "pilot", session=SESSION, clock=clock)
    facts = stage_facts(fresh(settings, "bare", clock))
    assert not facts.has_question and not facts.has_protocol
    assert derive_stage(facts) is Stage.SCOPING


def test_question_without_protocol_is_scoping(
    project: Project, agent: Actor, settings: Settings, clock: FixedClock
) -> None:
    record_pilot_question(project, agent)
    facts = stage_facts(fresh(settings, "demo", clock))
    assert facts.has_question and not facts.has_protocol
    assert derive_stage(facts) is Stage.SCOPING


def test_unconfirmed_press_is_protocol_stage(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    settings: Settings,
    clock: FixedClock,
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    facts = stage_facts(fresh(settings, "demo", clock))
    assert facts.protocol_ready and facts.press_required and not facts.press_confirmed
    assert derive_stage(facts) is Stage.PROTOCOL


def test_ready_protocol_without_a_complete_run_is_search(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    settings: Settings,
    clock: FixedClock,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    facts = stage_facts(fresh(settings, "demo", clock))
    assert facts.complete_search_runs == 0  # the probe run does not count
    assert derive_stage(facts) is Stage.SEARCH


def test_screening_project_is_ta_screening(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    settings: Settings,
    clock: FixedClock,
) -> None:
    ta_world(project, agent, human, mock_sources)
    facts = stage_facts(fresh(settings, "demo", clock))
    assert facts.complete_search_runs >= 1 and facts.ta_pending > 0
    assert derive_stage(facts) is Stage.TA_SCREENING
