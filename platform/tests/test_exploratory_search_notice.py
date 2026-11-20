"""Exploratory mode has no search gate; the search report says so (the rule is unchanged)."""

from __future__ import annotations

from factory.clock import FixedClock
from factory.config import Settings
from factory.services.agent_view import search_view
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.protocol import EXPLORATORY_SEARCH_NOTICE, exploratory_search_notice
from tests.helpers import SESSION


def test_exploratory_project_carries_the_notice(explore_project: Project) -> None:
    assert exploratory_search_notice(explore_project) == EXPLORATORY_SEARCH_NOTICE
    data = search_view(explore_project)
    assert isinstance(data, dict)
    assert data["notice"] == EXPLORATORY_SEARCH_NOTICE


def test_pilot_project_has_no_notice(settings: Settings, clock: FixedClock) -> None:
    pilot = init_project(settings, "gated", "pilot", session=SESSION, clock=clock)
    assert exploratory_search_notice(pilot) is None
    data = search_view(pilot)
    assert isinstance(data, dict)
    assert "notice" not in data
