"""MCP `export_bibliography` and the `factory export` commands (slice 7b, plan X-A task 5)."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.services.context import Project
from factory.services.exports import export_bibliography, export_prisma_svg, select_works
from factory.sources.registry import SourceFactory
from tests.helpers import open_session
from tests.test_chase_service import _corpus, _settle
from tests.test_cli import _cli_env, runner
from tests.test_screening_next import _draw

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
AGENT = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


def _tree(root: Path) -> dict[str, int]:
    return {
        str(p.relative_to(root)): p.stat().st_size for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.mark.anyio
async def test_mcp_export_bibliography(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    expected = "".join(export_bibliography(project, "bibtex"))
    async with open_session(settings, clock) as session:
        body = await session.call("export_bibliography", project="demo")
        csl = await session.call("export_bibliography", project="demo", format="csl")
        some = select_works(project, "corpus")[:2]
        explicit = await session.call("export_bibliography", project="demo", ids=some)
        bad_ids = await session.call(
            "export_bibliography", project="demo", ids=["rf:nope-00000000"]
        )
        bad_fmt = await session.call("export_bibliography", project="demo", format="ris")
        bad_scope = await session.call("export_bibliography", project="demo", scope="all")
    assert body["ok"] is True
    # Held-out seed identifiers are withheld from agents (R-20); nothing else differs.
    got = body["data"]["text"].splitlines()
    assert len(got) == len(expected.splitlines())
    differing = [(a, b) for a, b in zip(got, expected.splitlines(), strict=True) if a != b]
    assert differing and all("[withheld]" in a for a, _ in differing)
    assert body["data"]["scope"] == "included"
    assert body["data"]["count"] == len(select_works(project, "included"))
    assert isinstance(json.loads(csl["data"]["text"]), list)
    assert explicit["data"]["count"] == 2 and explicit["data"]["scope"] == "ids"
    assert bad_ids["errors"][0]["field"] == "ids"
    assert bad_fmt["errors"][0]["field"] == "format"
    assert bad_scope["errors"][0]["field"] == "scope"


@pytest.mark.anyio
async def test_mcp_export_refused_to_pass_session(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    _corpus(project, agent, human, mock_sources)
    _draw(project)
    async with open_session(settings, clock) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True
        refused = await screener.call("export_bibliography", project="demo", scope="corpus")
    assert refused["ok"] is False and refused["errors"][0]["field"] == "session"


@pytest.mark.anyio
async def test_mcp_export_cap_enforced(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _corpus(project, agent, human, mock_sources)
    assert mcp_server.MCP_EXPORT_MAX_WORKS == 2000
    monkeypatch.setattr(mcp_server, "MCP_EXPORT_MAX_WORKS", 3)
    async with open_session(settings, clock) as session:
        refused = await session.call("export_bibliography", project="demo", scope="corpus")
    assert refused["ok"] is False
    [error] = refused["errors"]
    assert error["field"] == "scope" and "use the CLI" in error["reason"]


def test_cli_export_matches_service(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    tmp_path: Path,
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    env = _cli_env(settings.root)
    before = _tree(project.paths.dir / "events")
    out = tmp_path / "refs.bib"
    done = runner.invoke(app, ["export", "bibtex", "--out", str(out)], env=env)
    assert done.exit_code == 0, done.stderr + done.stdout
    assert out.read_text(encoding="utf-8") == "".join(export_bibliography(project, "bibtex"))
    assert _tree(project.paths.dir / "events") == before  # exports write no event

    printed = runner.invoke(app, ["export", "bibtex", "--scope", "corpus"], env=env)
    assert printed.stdout == "".join(export_bibliography(project, "bibtex", scope="corpus"))

    csl = runner.invoke(app, ["export", "csl", "--ascii"], env=env)
    assert csl.exit_code == 0 and isinstance(json.loads(csl.stdout), list)

    ids = select_works(project, "corpus")[:2]
    chosen = runner.invoke(
        app, ["export", "bibtex", "--id", ids[0], "--id", ids[1], "--scope", "corpus"], env=env
    )
    assert (
        chosen.exit_code == 1 and "scope:" in chosen.stderr
    )  # a scope and ids together are refused
    only_ids = runner.invoke(app, ["export", "bibtex", "--id", ids[0], "--id", ids[1]], env=env)
    assert only_ids.exit_code == 0, only_ids.stderr
    assert only_ids.stdout == "".join(export_bibliography(project, "bibtex", ids=ids))

    unknown = runner.invoke(app, ["export", "bibtex", "--id", "rf:nope-00000000"], env=env)
    assert unknown.exit_code == 1 and "ids:" in unknown.stderr and unknown.stdout == ""

    # --out onto an existing file overwrites without asking.
    out.write_text("stale", encoding="utf-8")
    again = runner.invoke(app, ["export", "bibtex", "--out", str(out)], env=env)
    assert again.exit_code == 0 and "stale" not in out.read_text(encoding="utf-8")


def test_cli_export_prisma_svg(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    tmp_path: Path,
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    env = _cli_env(settings.root)
    svg = export_prisma_svg(project)
    out = tmp_path / "prisma.svg"
    assert runner.invoke(app, ["export", "prisma", "--out", str(out)], env=env).exit_code == 0
    assert out.read_text(encoding="utf-8") == svg
    assert runner.invoke(app, ["export", "prisma"], env=env).stdout == svg
    report = runner.invoke(app, ["report", "prisma", "--format", "svg"], env=env)
    assert report.exit_code == 0 and report.stdout == svg
    markdown = runner.invoke(app, ["report", "prisma"], env=env)
    assert markdown.stdout.startswith("# PRISMA 2020 flow")
    both = runner.invoke(app, ["report", "prisma", "--format", "svg", "--json"], env=env)
    assert both.exit_code == 2


def test_cli_export_unwritable_out(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    tmp_path: Path,
) -> None:
    _corpus(project, agent, human, mock_sources)
    env = _cli_env(settings.root)
    missing: Any = tmp_path / "no" / "such" / "dir" / "x.bib"
    failed = runner.invoke(
        app, ["export", "bibtex", "--scope", "corpus", "--out", str(missing)], env=env
    )
    assert failed.exit_code == 1 and "cannot write" in failed.stderr
