"""MCP and CLI surfaces of the reports, `trace` and `check` (plan 5b, task 5).

The MCP tools are agent-facing: they withhold held-out seeds (R-20) and refuse pass sessions the
tools that report agreement figures. The CLI is the human view and shows everything.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.conventions import WITHHELD
from factory.model.project import RigorMode
from factory.model.search import QueryKind, QuerySpec
from factory.services import check as check_service
from factory.services import trace as trace_service
from factory.services.check import CheckReport, Finding
from factory.services.context import Project
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import prisma_flow, search_report
from factory.services.search import list_works, register_query, run_query
from factory.services.seeds import SeedRole, all_seeds, split_is_drawn
from factory.sources.registry import SourceFactory
from tests.helpers import _leaks, _positive_item, _setup, open_session, openalex_item
from tests.test_acceptance_supplementary import _corpus_missing_held_out, _held_out_tokens
from tests.test_chase_service import _corpus, _ordinary, _settle
from tests.test_check import _unfound_seed
from tests.test_cli import _cli_env, runner
from tests.test_screening_next import _draw

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
AGENT = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


def _held_out_forms(project: Project) -> set[str]:
    """Every form of each held-out seed an output must not carry: id, DOI, arXiv, OpenAlex."""
    tokens = _held_out_tokens(project)
    for seed in all_seeds(project):
        if seed.role is SeedRole.HELD_OUT:
            tokens.update(
                value for value in (seed.doi, seed.arxiv, seed.openalex, seed.work_id) if value
            )
    return tokens


@pytest.mark.anyio
async def test_mcp_check_and_trace_never_name_held_out(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    protocol_id, held, number = _corpus_missing_held_out(project, agent, human, mock_sources)
    doi = f"10.1000/p{number}"
    [seed] = [s for s in all_seeds(project) if s.seed_id == held]
    assert seed.role is SeedRole.HELD_OUT and seed.work_id is not None  # resolved by lookup

    # Held-out missing: the service names the seed; the MCP tool counts it by role.
    service_report = check_service.check(project)
    unscrubbed = service_report.model_dump_json()
    assert held in unscrubbed
    async with open_session(settings, clock) as session:
        pilot = await session.call("check", project="demo")
        promoted = await session.call("check", project="demo", promote_to="systematic")
    for body in (pilot, promoted):
        assert body["ok"] is True, body
        assert _leaks(json.dumps(body), _held_out_forms(project)) == []
    missing = [f for f in pilot["data"]["findings"] if f["code"] == "seed-missing"]
    assert [(f["role"], f["refs"], f["message"]) for f in missing if f["role"] == "held-out"] == [
        ("held-out", [], "1 held-out positive seed(s) missing")
    ]
    assert pilot["data"]["ok"] is False

    # The held-out positive is now retrieved by a search, so it is in the corpus and resolved.
    # A work title carries its DOI, so the service output names it where only the scrub removes it.
    reply = openalex_item(
        title=f"Reply to {doi}",
        author="Ada Zhou",
        published="2021-01-01",
        openalex_id="W777",
        doi="10.1000/r777",
    )
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    sources = mock_sources(openalex=[_positive_item(number), reply])
    run_query(project, register_query(project, human, spec, sources=sources), sources=sources)
    work_id = str(seed.work_id)
    assert work_id in {w.id for w in list_works(project)}
    back = trace_service.trace(project, work_id)
    assert held in back.model_dump_json()  # the seed node is in the unscrubbed service output
    assert any(n.kind == "seed" for n in _nodes(back))
    [reply_work] = [w for w in list_works(project) if w.title == f"Reply to {doi}"]
    assert doi in trace_service.trace(project, reply_work.id).model_dump_json()
    async with open_session(settings, clock) as session:
        refused = await session.call("trace", project="demo", ref=held)
        unknown = await session.call("trace", project="demo", ref="SEED99")
        by_work = await session.call("trace", project="demo", ref=work_id, direction="forward")
        by_back = await session.call("trace", project="demo", ref=work_id)
        by_reply = await session.call("trace", project="demo", ref=reply_work.id)
    assert _fields(refused) == _fields(unknown) == ["ref"]
    assert refused["errors"] == unknown["errors"]
    for body in (by_work, by_back, by_reply):
        assert body["ok"] is True, body
        text = json.dumps(body)
        assert _leaks(text, _held_out_forms(project) - {work_id}) == []
        assert "seed" not in {n["kind"] for n in _walk(body["data"])}
    assert protocol_id and by_reply["data"]["label"] == f"Reply to {WITHHELD}"


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [node, *(n for child in node["children"] for n in _walk(child))]


def _nodes(node: Any) -> list[Any]:
    return [node, *(n for child in node.children for n in _nodes(child))]


# --- MCP: pass sessions, shapes and refusals ---


@pytest.mark.anyio
async def test_mcp_report_methods_refused_to_pass_session_mid_screening(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    """`agreement_summary` underneath is unrestricted, so the tool is the only guard."""
    _setup(project, agent, human, mock_sources)
    _draw(project)
    before = len(read_all(project.paths.events_dir, project.catalog))
    async with open_session(settings, clock) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True and joined["data"]["batch"] is not None  # mid-screening
        mid = len(read_all(project.paths.events_dir, project.catalog))
        refused = await screener.call("report_methods", project="demo")
        gaps = await screener.call("check", project="demo")
        flow = await screener.call("report_prisma", project="demo")
    assert _fields(refused) == ["session"]
    assert _fields(gaps) == ["session"]
    assert "report" not in json.dumps(refused["errors"]) or refused.get("data") is None
    assert len(read_all(project.paths.events_dir, project.catalog)) == mid > before
    assert flow["ok"] is True  # counts only, as in `project_status`

    async with open_session(settings, clock) as reviewer:  # a session outside the passes
        allowed = await reviewer.call("report_methods", project="demo")
    assert allowed["ok"] is True
    assert set(allowed["data"]) == {"report", "text"}


@pytest.mark.anyio
async def test_mcp_report_methods_and_prisma_return_the_service_figures(
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
        methods = await session.call("report_methods", project="demo")
        prisma = await session.call("report_prisma", project="demo")
    report = methods_report(project)
    assert methods["data"]["report"] == json.loads(report.model_dump_json())
    assert methods["data"]["text"] == render_methods(report)
    assert prisma["data"]["flow"] == json.loads(prisma_flow(project).model_dump_json())
    assert prisma["data"]["search"] == json.loads(search_report(project).model_dump_json())
    forms = _held_out_forms(project) - {s.work_id for s in all_seeds(project) if s.work_id}
    assert _leaks(json.dumps([methods, prisma]), forms) == []


@pytest.mark.anyio
async def test_mcp_check_counts_unsplit_as_held_out_possible_never_development(
    settings: Settings,
    project: Project,
    agent: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    seed_id = _unfound_seed(project, agent, mock_sources)
    assert not split_is_drawn(project)
    async with open_session(settings, clock) as session:
        body = await session.call("check", project="demo")
    found = [f for f in body["data"]["findings"] if f["code"] == "seed-missing"]
    assert [(f["role"], f["refs"]) for f in found] == [("held-out-possible", [])]
    assert found[0]["message"] == "1 held-out-possible positive seed(s) missing"
    assert seed_id not in json.dumps(body)
    assert "development" not in json.dumps(found)


@pytest.mark.anyio
async def test_mcp_check_scrubs_what_it_is_given_as_a_backstop(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A finding that names a held-out identifier in its message or refs still comes out clean."""
    _, held, number = _corpus_missing_held_out(project, agent, human, mock_sources)
    doi = f"10.1000/p{number}"
    leaky = CheckReport(
        mode=RigorMode.PILOT,
        evaluated_as=RigorMode.PILOT,
        findings=[
            Finding(code="broken-link", severity="error", refs=[doi, "rf:x"], message=f"{doi}")
        ],
    )
    monkeypatch.setattr(check_service, "check", lambda _project, promote_to=None: leaky)
    async with open_session(settings, clock) as session:
        body = await session.call("check", project="demo")
    assert body["ok"] is True
    assert _leaks(json.dumps(body), {doi, held}) == []
    assert "rf:x" in json.dumps(body)


@pytest.mark.anyio
async def test_mcp_trace_and_check_name_bad_arguments(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as session:
        way = await session.call("trace", project="demo", ref="Q@00000000", direction="sideways")
        mode = await session.call("check", project="demo", promote_to="strict")
        none = await session.call("trace", project="demo", ref="nonsense")
        no_project = await session.call("check", project="nope")
    assert _fields(way) == ["direction"]
    assert _fields(mode) == ["promote_to"]
    assert _fields(none) == ["ref"]
    assert _fields(no_project) == ["project"]


# --- CLI: the human view ---


def test_cli_check_exit_code(
    tmp_path: Path,
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """Exit 1 when any finding is an error, 0 otherwise; the listing names ids."""
    other = _cli_env(tmp_path / "other")
    runner.invoke(app, ["init", "clean", "--mode", "exploratory"], env=other)
    clean = runner.invoke(app, ["check"], env=other)
    assert clean.exit_code == 0, clean.stderr + clean.stdout
    assert not any(line.startswith("error") for line in clean.stdout.splitlines())

    env = _cli_env(settings.root)
    assert runner.invoke(app, ["check"], env=env).exit_code == 1  # no protocol in a pilot

    _, held, _ = _corpus_missing_held_out(project, agent, human, mock_sources)
    failing = runner.invoke(app, ["check"], env=env)
    assert failing.exit_code == 1, failing.stdout
    line = next(row for row in failing.stdout.splitlines() if "seed-missing" in row)
    assert line.startswith("error") and held in line  # the human view names the seed

    bad = runner.invoke(app, ["check", "--promote-to", "strict"], env=env)
    assert bad.exit_code == 1 and "promote-to:" in bad.stderr
    promoted = runner.invoke(app, ["check", "--promote-to", "systematic"], env=env)
    assert promoted.stdout.splitlines()[0].endswith("evaluated as systematic")


@pytest.mark.anyio
async def test_cli_report_prisma_matches_mcp_numbers(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id, leave=_ordinary(project)[0])
    async with open_session(settings, clock) as session:
        mcp = (await session.call("report_prisma", project="demo"))["data"]
    env = _cli_env(settings.root)
    flow = runner.invoke(app, ["report", "prisma", "--json"], env=env)
    search = runner.invoke(app, ["report", "search", "--json"], env=env)
    assert flow.exit_code == 0 and search.exit_code == 0, flow.stderr + search.stderr
    assert json.loads(flow.stdout) == mcp["flow"]
    assert json.loads(search.stdout) == mcp["search"]

    markdown = runner.invoke(app, ["report", "prisma"], env=env).stdout
    figures = mcp["flow"]
    assert f"- records screened: {figures['screened']}" in markdown
    assert f"- included: {figures['included']}" in markdown
    assert f"- pending: {figures['pending']}" in markdown and figures["pending"] == 1
    assert f"- duplicates removed: {figures['duplicates_removed']}" in markdown
    for source, n in figures["identified_databases"].items():
        assert f"- {source}: {n}" in markdown
    assert "provisional" in markdown


def test_cli_report_methods_and_search_markdown(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    env = _cli_env(settings.root)
    text = runner.invoke(app, ["report", "methods"], env=env)
    data = runner.invoke(app, ["report", "methods", "--json"], env=env)
    assert text.stdout == render_methods(methods_report(project))
    assert json.loads(data.stdout) == json.loads(methods_report(project).model_dump_json())
    search = runner.invoke(app, ["report", "search"], env=env).stdout
    [row] = search_report(project).rows
    assert f"`{row.text}`" in search and f"retrieved: {row.retrieved}" in search


def test_cli_trace_prints_an_indented_tree_with_seeds(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _, held, _number = _corpus_missing_held_out(project, agent, human, mock_sources)
    env = _cli_env(settings.root)
    seed = runner.invoke(app, ["trace", held], env=env)  # the human may trace a held-out seed
    assert seed.exit_code == 0, seed.stderr
    first, *rest = seed.stdout.splitlines()
    assert first.startswith(f"seed {held}  ") and rest
    assert all(line.startswith("  ") for line in rest)

    [work] = [s.work_id for s in all_seeds(project) if s.seed_id == held]
    back = runner.invoke(app, ["trace", str(work)], env=env).stdout
    assert f"seed {held}" in back
    forward = runner.invoke(app, ["trace", str(work), "--forward"], env=env)
    assert forward.exit_code == 0
    unknown = runner.invoke(app, ["trace", "SEED99"], env=env)
    assert unknown.exit_code == 1 and "ref: unknown id" in unknown.stderr
