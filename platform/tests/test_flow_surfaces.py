"""The flow surfaces: `report_prisma(by_source)`, `flow_works`, `flow_skipped` and `flow_trail` over
MCP, and the `report flow`, `report flow-works`, `report flow-skipped` and `report flow-trail`
commands (flow transparency, task 7).

The MCP tools are agent-facing: each is refused to a session that has joined a pass, and otherwise
answers as `report_prisma` does, before a screening pass opens too. The CLI full view shows the same
figures; the agent view is the same payload.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.flow_ledger import TOTAL, flow_by_source, flow_ledger, ledger_reconciles
from factory.services.flow_query import PAGE_LIMIT, flow_trail, flow_works
from factory.services.flow_skipped import run_gaps, skipped_records
from factory.services.flow_trails import flow_trails
from factory.sources.registry import SourceFactory
from tests.cli_helpers import _cli_env, runner
from tests.fulltext_helpers import _ft_world
from tests.helpers import _setup, open_session
from tests.screening_helpers import _corpus, _draw, _settle

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
AGENT = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


def test_flow_works_refuses_each_bad_filter_by_name(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    cases: list[tuple[dict[str, Any], str]] = [
        ({"step": "bogus"}, "step"),
        ({"outcome": "included"}, "outcome"),
        ({"step": "title-abstract", "outcome": "awaiting"}, "outcome"),
        ({"step": "full-text", "criterion": "EX04"}, "criterion"),
        ({"step": "title-abstract", "outcome": "included", "criterion": "EX04"}, "criterion"),
        ({"step": "full-text", "criterion": "EX99"}, "criterion"),
        ({"source_group": "no-such-group"}, "source_group"),
        ({"cursor": "x"}, "cursor"),
        ({"limit": 0}, "limit"),
        ({"limit": PAGE_LIMIT + 1}, "limit"),
        ({"cursor": "999999"}, "cursor"),
    ]
    for kwargs, field in cases:
        with pytest.raises(FactoryValidationError) as caught:
            flow_works(project, **kwargs)
        assert [issue.field for issue in caught.value.issues] == [field], kwargs


def test_flow_works_pages_cover_the_ledger_and_match_the_flow_counts(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    rows = flow_ledger(project)
    walked: list[str] = []
    cursor: str | None = None
    while True:
        page = flow_works(project, cursor=cursor, limit=1)
        walked += [row.work_id for row in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert walked == [row.work_id for row in rows]
    with pytest.raises(FactoryValidationError) as caught:
        flow_works(project, limit=PAGE_LIMIT * 10)
    assert [issue.field for issue in caught.value.issues] == ["limit"]

    excluded = flow_works(project, step="title-abstract", outcome="excluded")
    total = flow_by_source(project)[TOTAL]
    assert len(excluded.items) == sum(total.ta_excluded.values())
    assert ledger_reconciles(project) == []


def test_flow_skipped_reads_the_archived_pages_and_the_run_gaps(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    records = skipped_records(project)
    gaps = run_gaps(project)
    assert all(
        record.reason in {"untitled", "duplicate-within-run", "unparsed"} for record in records
    )
    assert all(gap.retrieved >= 0 for gap in gaps)


def test_flow_trail_is_the_trail_of_one_work_and_refuses_an_unknown_id(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    work_id = flow_ledger(project)[0].work_id
    assert flow_trail(project, work_id) == flow_trails(project).get(work_id, [])
    with pytest.raises(FactoryValidationError) as caught:
        flow_trail(project, "no-such-work")
    assert [issue.field for issue in caught.value.issues] == ["work_id"]


def test_cli_report_flow_trail_full_and_refused_ids(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _ft_world(project, agent, human, mock_sources)
    env = _cli_env(settings.root)
    work_id = flow_ledger(project)[0].work_id
    as_json = runner.invoke(app, ["report", "flow-trail", work_id, "--json"], env=env)
    assert as_json.exit_code == 0, as_json.stderr
    assert set(json.loads(as_json.stdout)) == {"work_id", "steps"}
    text_out = runner.invoke(app, ["report", "flow-trail", work_id], env=env)
    assert text_out.exit_code == 0, text_out.stderr
    assert f"# Trail of {work_id}" in text_out.stdout
    bad = runner.invoke(app, ["report", "flow-trail", "no-such-work"], env=env)
    assert bad.exit_code == 1
    assert "work_id: unknown work id" in bad.stderr + bad.stdout


@pytest.mark.anyio
async def test_flow_views_are_refused_to_a_pass_session_and_answer_before_a_pass(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as reviewer:
        early = await reviewer.call("flow_works", project="demo")
        early_gaps = await reviewer.call("flow_skipped", project="demo")
        early_flow = await reviewer.call("report_prisma", project="demo", by_source=True)
        early_trail = await reviewer.call("flow_trail", project="demo", work_id="no-such-work")
    assert early["ok"] is True
    assert early["data"]["items"] == [
        row.model_dump(mode="json") for row in flow_works(project).items
    ]
    assert early_gaps["ok"] is True and set(early_gaps["data"]) == {"skipped", "run_gaps"}
    expected = {key: v.model_dump(mode="json") for key, v in flow_by_source(project).items()}
    assert early_flow["data"]["by_source"] == expected
    assert early_flow["data"]["reconciles"] == ledger_reconciles(project)
    assert _fields(early_trail) == ["work_id"]

    _draw(project)
    before = len(read_all(project.paths.events_dir, project.catalog))
    async with open_session(settings, clock) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True and joined["data"]["batch"] is not None
        mid = len(read_all(project.paths.events_dir, project.catalog))
        works = await screener.call("flow_works", project="demo")
        gaps = await screener.call("flow_skipped", project="demo")
        flow = await screener.call("report_prisma", project="demo", by_source=True)
        trail = await screener.call("flow_trail", project="demo", work_id="no-such-work")
    assert _fields(works) == ["session"]
    assert _fields(gaps) == ["session"]
    assert _fields(flow) == ["session"]
    assert _fields(trail) == ["session"]
    assert len(read_all(project.paths.events_dir, project.catalog)) == mid > before


@pytest.mark.anyio
async def test_flow_views_return_the_service_figures_once_a_pass_is_open(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    async with open_session(settings, clock) as session:
        prisma = await session.call("report_prisma", project="demo", by_source=True)
        plain = await session.call("report_prisma", project="demo")
        works = await session.call("flow_works", project="demo", step="title-abstract")
        gaps = await session.call("flow_skipped", project="demo")
        bad = await session.call("flow_works", project="demo", outcome="included")
        bad_trail = await session.call("flow_trail", project="demo", work_id="no-such-work")
    assert prisma["ok"] is True and "by_source" not in plain["data"]
    expected = {key: v.model_dump(mode="json") for key, v in flow_by_source(project).items()}
    assert prisma["data"]["by_source"] == expected
    assert prisma["data"]["reconciles"] == []
    page = flow_works(project, step="title-abstract")
    assert [item["work_id"] for item in works["data"]["items"]] == [
        row.work_id for row in page.items
    ]
    assert set(gaps["data"]) == {"skipped", "run_gaps"}
    assert _fields(bad) == ["outcome"]
    assert _fields(bad_trail) == ["work_id"]


def test_cli_report_flow_by_source_table_and_refusals(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _ft_world(project, agent, human, mock_sources)
    env = _cli_env(settings.root)
    table = runner.invoke(app, ["report", "flow", "--by-source"], env=env)
    assert table.exit_code == 0, table.stderr
    assert "| step | " in table.stdout and f"| {TOTAL} |" in table.stdout
    assert "reconciles with the PRISMA flow" in table.stdout
    assert runner.invoke(app, ["report", "flow"], env=env).exit_code == 2

    as_json = runner.invoke(app, ["report", "flow", "--by-source", "--json"], env=env)
    assert as_json.exit_code == 0, as_json.stderr
    payload = json.loads(as_json.stdout)
    assert payload["reconciles"] == []
    assert TOTAL in payload["by_source"]

    bad = runner.invoke(app, ["report", "flow-works", "--outcome", "included"], env=env)
    assert bad.exit_code == 1
    assert "outcome: needs a step" in bad.stderr + bad.stdout


def test_cli_report_flow_works_and_skipped_listings(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _ft_world(project, agent, human, mock_sources)
    env = _cli_env(settings.root)
    page = runner.invoke(
        app,
        ["report", "flow-works", "--step", "full-text", "--outcome", "excluded", "--json"],
        env=env,
    )
    assert page.exit_code == 0, page.stderr
    data = json.loads(page.stdout)
    assert set(data) == {"items", "next_cursor"}
    assert all(item["ft_outcome"] == "excluded" for item in data["items"])

    text_out = runner.invoke(app, ["report", "flow-works", "--limit", "1"], env=env)
    assert text_out.exit_code == 0, text_out.stderr

    skipped = runner.invoke(app, ["report", "flow-skipped"], env=env)
    assert skipped.exit_code == 0, skipped.stderr
    assert "Run gaps by query" in skipped.stdout
    as_json = runner.invoke(app, ["report", "flow-skipped", "--json"], env=env)
    assert set(json.loads(as_json.stdout)) == {"skipped", "run_gaps"}


def test_cli_report_flow_works_refuses_a_criterion_without_a_step(
    settings: Settings, project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """A bad filter is refused by name on the CLI as on MCP, before any row is read."""
    _setup(project, agent, human, mock_sources)
    env = _cli_env(settings.root)
    refused = runner.invoke(app, ["report", "flow-works", "--criterion", "EX04"], env=env)
    assert refused.exit_code == 1
    assert "criterion: needs a step" in refused.stderr + refused.stdout
