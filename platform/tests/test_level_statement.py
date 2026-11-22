"""The level statement and its presence in every report (plan tiers-and-autonomy, C7)."""

import inspect
import json
import re
from pathlib import Path

from factory.clock import FixedClock
from factory.config import Settings
from factory.model.levels import Tier
from factory.services import agent_view, level_statement
from factory.services.level_statement import (
    LEVEL_STATEMENT_KEY,
    render_level_statement,
)
from factory.services.level_statement import (
    level_statement as build_statement,
)
from factory.services.project import init_project
from tests.helpers import SESSION


def test_legacy_project_says_tier_not_declared(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    statement = build_statement(project)
    assert statement.tier is None
    assert statement.human_confirmed
    assert statement.steps_skipped == ()
    assert "tier: not declared" in render_level_statement(statement)


def test_brief_attended_lists_its_skipped_steps(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", None, session=SESSION, clock=clock, tier="brief")

    def fake(tier: Tier) -> tuple[str, ...]:
        assert tier is Tier.BRIEF
        return ("no hold-out split", "no dual screening")

    statement = build_statement(project, skipped=fake)
    assert statement.steps_skipped == ("no hold-out split", "no dual screening")
    assert statement.human_confirmed
    text = render_level_statement(statement)
    assert "tier: brief" in text
    assert "no hold-out split; no dual screening" in text
    assert "exploratory" in text


def test_autonomous_output_is_never_human_confirmed(settings: Settings, clock: FixedClock) -> None:
    project = init_project(
        settings,
        "demo",
        None,
        session=SESSION,
        clock=clock,
        tier="brief",
        autonomy_level="autonomous",
    )
    statement = build_statement(project, skipped=lambda _t: ())
    assert not statement.human_confirmed
    assert "not human-confirmed" in render_level_statement(statement)


def test_view_gets_one_field(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    out = level_statement.with_level_statement(project, {"a": 1})
    assert isinstance(out, dict)
    assert out["a"] == 1
    stated = out[LEVEL_STATEMENT_KEY]
    assert isinstance(stated, dict)
    assert stated["tier"] is None


def test_every_report_view_carries_the_statement(settings: Settings, clock: FixedClock) -> None:
    """Each `*_view` of the five report tools returns the statement; a new report service that
    does not call `with_level_statement` fails here."""
    views = {
        "prisma_view": agent_view.prisma_view,
        "search_view": agent_view.search_view,
        "methods_view": agent_view.methods_view,
        "discovery_view": agent_view.discovery_view,
        "evidence_view": agent_view.evidence_view,
    }
    for name, fn in views.items():
        assert "level_statement_service.with_level_statement" in inspect.getsource(fn), name
    project = init_project(settings, "demo", None, session=SESSION, clock=clock, tier="brief")
    for name, fn in views.items():
        view = fn(project)
        assert isinstance(view, dict), name
        assert LEVEL_STATEMENT_KEY in view, name


def test_every_report_tool_calls_a_statement_view() -> None:
    """The MCP `report_*` tools and CLI report commands reach their output only through these
    views; enumerate the tools so a new one without the statement fails."""
    source = (Path(agent_view.__file__).parents[1] / "mcp" / "server.py").read_text()
    tools = re.findall(r"def (report_\w+)\(", source)
    assert set(tools) == {
        "report_prisma",
        "report_methods",
        "report_discovery",
        "report_evidence",
        "report_search",
    }
    for tool in tools:
        body = source.split(f"def {tool}(", 1)[1].split("@server.tool()", 1)[0]
        assert re.search(r"agent_view_service\.\w+_view\(", body), tool


def test_every_cli_report_command_carries_the_statement() -> None:
    """The researcher's `factory report *` commands (the `_full_view` branches included) reach
    their output through the shared statement helpers; a new command without them fails here
    (finding I1)."""
    source = (Path(agent_view.__file__).parents[1] / "cli" / "main.py").read_text()
    commands = re.findall(r'@report_app\.command\("([\w-]+)"\)\ndef (\w+)\(', source)
    assert {c for c, _ in commands} == {
        "prisma",
        "search",
        "flow",
        "flow-works",
        "flow-trail",
        "flow-skipped",
        "methods",
        "discovery",
        "evidence",
    }
    for command, fn in commands:
        body = source.split(f"def {fn}(", 1)[1].split("\n@", 1)[0]
        assert "level_statement_service." in body or "_view(project" in body, command
    for fn in (
        agent_view.flow_works_view,
        agent_view.flow_trail_view,
        agent_view.flow_skipped_view,
    ):
        assert "with_level_statement" in inspect.getsource(fn), fn.__name__


def test_text_and_json_helpers_append_the_statement(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", None, session=SESSION, clock=clock, tier="brief")
    text = level_statement.text_with_statement(project, "body\n")
    assert text.startswith("body\n\n---\ntier: brief")
    assert level_statement.text_with_statement(project, "<svg/>", style="xml").endswith("-->\n")
    csv = level_statement.text_with_statement(project, "a,b\n1,2\n", style="csv")
    assert csv.splitlines()[0] == "a,b"
    assert all(line.startswith("# ") for line in csv.splitlines()[2:])
    loaded = json.loads(level_statement.json_text_with_statement(project, '{"a": 1}'))
    assert loaded["a"] == 1
    assert loaded[LEVEL_STATEMENT_KEY]["tier"] == "brief"
