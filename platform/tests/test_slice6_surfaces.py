"""The surfaces of plan XP-B: CLI commands and MCP tools (slice 6, task 8). No tool writes or sets
an evaluation; the agent variants carry no effect size, interval or reproduced value."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.model.directions import Conditions, DirectionReason
from factory.services.context import Project
from factory.services.directions import close_direction
from factory.services.evaluation import latest_evaluation
from factory.services.experiments import unlock_experiment
from tests.cli_helpers import _env
from tests.evaluation_helpers import REFUTED, SUPPORTED, own_result, report_runs, unlocked
from tests.experiment_helpers import XW, frozen_design, xw
from tests.extraction_helpers import SESSION_A
from tests.helpers import install_skill, open_session
from tests.hypothesis_helpers import HW, gw, hw
from tests.test_mcp_cards import SESSION_E, _session
from tests.test_reproduction import _repro

runner = CliRunner()
AGENT = {"role": "ideator", "model": "claude-opus-5-5", "skill": "rf-ideate"}


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


# --- CLI ----------------------------------------------------------------------------------------


def test_cli_evaluate_show_ledger_registry(
    settings: Settings, project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    root = settings.root
    code, out, _ = _run(root, "registry")
    assert code == 0 and out.strip() == "no failed directions recorded"
    code, out, _ = _run(root, "benchmark-ledger")
    assert code == 0 and "reproduction none" in out
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, dict(list(REFUTED.items())[:5]))
    code, _, err = _run(root, "hypotheses", "evaluate", xw.hid)
    assert code == 1 and "incomplete" in err  # the outcome is not typed in; it needs the runs
    code, out, _ = _run(root, "hypotheses", "evaluate", xw.hid, "--incomplete")
    assert code == 0 and "incomplete" in out
    report_runs(project, human, tmp_path, exp, {("baseline", 3): "76.0"})  # the last cell
    code, out, _ = _run(root, "hypotheses", "show", xw.hid)
    assert code == 0 and "evaluation" in out and "refuted" in out
    assert "interval [-1.496833, -0.503167]" in out and "specification curve" in out
    assert "control planted (positive)" in out
    code, out, _ = _run(root, "hypotheses", "evaluate", xw.hid)
    assert code == 0 and "refuted" in out and len(_of(project, "hypothesis.evaluated")) == 2
    code, out, _ = _run(root, "registry")
    assert code == 0 and xw.hid in out and "below-baseline" in out
    code, out, _ = _run(root, "registry", "--reason", "inconclusive")
    assert code == 0 and out.strip() == "no failed directions recorded"
    code, out, _ = _run(root, "registry", "--key", xw.hid, "--reason", "below-baseline")
    assert code == 0 and "1 failed direction(s)" in out
    code, _, err = _run(root, "registry", "--reason", "nonsense")
    assert code == 1 and "reasons" in err
    assert _run(root, "benchmark-ledger", "--group", "nope")[0] == 1


def test_cli_ledger_shows_an_own_result(
    settings: Settings, project: Project, human: Actor, xw: XW, hw: HW, tmp_path: Path
) -> None:
    hid = own_result(project, human, hw, xw, tmp_path, REFUTED)
    code, out, _ = _run(settings.root, "benchmark-ledger")
    assert code == 0 and f"own result {hid}: refuted" in out


def test_cli_directions_close(settings: Settings, project: Project, xw: XW) -> None:
    root = settings.root
    code, out, err = _run(
        root,
        "directions",
        "close",
        "--text",
        "Tried and abandoned for memory.",
        "--reason",
        "infeasible",
        "--key",
        xw.hid,
        "--condition",
        "models=m1",
        "--condition",
        "models=m2",
        "--condition",
        "gpu_hours_used=12",
    )
    assert code == 0, err
    [event] = _of(project, "direction.closed")
    assert event.actor.kind == "human" and event.payload["conditions"]["models"] == ["m1", "m2"]
    code, out, _ = _run(root, "registry")
    assert "Tried and abandoned for memory." in out and "infeasible" in out
    bad = ("directions", "close", "--text", "x", "--key", xw.hid)
    assert _run(root, *bad, "--reason", "nonsense")[0] == 2
    assert _run(root, *bad, "--reason", "other", "--condition", "colour=blue")[0] == 2
    code, _, err = _run(
        root, "directions", "close", "--text", "x", "--reason", "other", "--key", "hyp_nope"
    )
    assert code == 1 and "keys.0" in err
    assert len(_of(project, "direction.closed")) == 1


# --- MCP ----------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tool_list_has_the_read_tools_and_none_that_evaluates(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert "registry_query" in names and "benchmark_ledger_view" in names
    for name in names:  # nothing evaluates, concludes, closes or records an outcome
        assert not any(w in name for w in ("evaluate", "conclude", "outcome", "direction_close"))
    assert not [n for n in names if n.startswith("direction")]


@pytest.mark.anyio
async def test_hypothesis_view_carries_the_outcome_but_no_statistic(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    xw: XW,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    install_skill(settings, "rf-ideate")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        out = await client.call("hypothesis_view", project="demo", hypothesis_id=xw.hid)
    assert out["ok"] is True
    shown = out["data"]["evaluation"]
    assert shown["outcome"] == "refuted" and shown["n"] == 3 and shown["level"] == "0.95"
    assert shown["specification_curve"] == {"universes": 1, "flags": []}
    assert {c["name"]: c["passed"] for c in shown["controls"]} == {
        "planted": None,
        "shuffled": None,
    }
    text = json.dumps(out)
    for secret in ("-1.496833", "-0.503167", '"mean"', "ci_low", "ci_high"):
        assert secret not in text, secret


@pytest.mark.anyio
async def test_registry_and_ledger_tools(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    xw: XW,
    hw: HW,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "1.0", 2: "1.0", 3: "1.0"})
    unlock_experiment(project, human, exp)
    report_runs(project, human, tmp_path, exp, REFUTED)
    own_result(project, human, hw, xw, tmp_path, REFUTED)
    closed = close_direction(
        project, human, "Private note.", DirectionReason.INFEASIBLE, Conditions(), [xw.hid]
    )
    install_skill(settings, "rf-ideate")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        registry = await client.call("registry_query", project="demo", keys=[xw.hid])
        narrowed = await client.call(
            "registry_query", project="demo", keys=[xw.hid], reasons=["infeasible"]
        )
        bad = await client.call("registry_query", project="demo", reasons=["nope"])
        ledger = await client.call("benchmark_ledger_view", project="demo")
        missing = await client.call("benchmark_ledger_view", project="demo", group_id="nope")
    ids = {r["direction_id"] for r in registry["data"]["rows"]}
    assert ids == {xw.hid, closed}
    assert [r["direction_id"] for r in narrowed["data"]["rows"]] == [closed]
    assert "Private note." not in json.dumps(registry)  # the researcher's note is not an agent's
    assert bad["ok"] is False and bad["errors"][0]["field"] == "reasons"
    assert missing["ok"] is False and missing["errors"][0]["field"] == "group_id"
    rows = [r for g in ledger["data"]["groups"] for r in g["rows"]]
    mine = next(r for r in rows if r["row_key"] == xw.rows[0])
    assert mine["reproduction"] == "reproduced" and mine["reproduced"] is None
    own = [o for g in ledger["data"]["groups"] for o in g["own_results"]]
    assert own and all(o["mean"] is None and o["ci_low"] is None for o in own)
    assert {o["outcome"] for o in own} == {"refuted"}


@pytest.mark.anyio
async def test_a_confirmatory_reproduction_reads_resolved_until_the_unlock(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    xw: XW,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exp = frozen_design(
        project,
        human,
        xw,
        baselines=[{"row_key": xw.rows[0], "tolerance": "0.01", "split": "confirmatory"}],
    )
    _repro(
        project,
        human,
        tmp_path,
        exp,
        xw.rows[0],
        {1: "1.0", 2: "1.0", 3: "1.0"},
        split="confirmatory",
    )
    install_skill(settings, "rf-ideate")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        ledger = await client.call("benchmark_ledger_view", project="demo")
    rows = [r for g in ledger["data"]["groups"] for r in g["rows"]]
    mine = next(r for r in rows if r["row_key"] == xw.rows[0])
    assert (mine["reproduction"], mine["reproduced"]) == ("resolved", None)
    from factory.services.benchmark_ledger import ledger as researcher

    full = {r.row_key: r for g in researcher(project) for r in g.rows}[xw.rows[0]]
    assert (full.reproduction, full.reproduced) == (
        "reproduced",
        "1",
    )  # the researcher's is complete


@pytest.mark.anyio
async def test_new_tools_are_refused_to_pass_sessions_and_role_blind_before_a_pass(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    xw: XW,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-ideate")
    _session(monkeypatch, SESSION_A)  # an extraction-pass session of the evidence world
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("registry_query", project="demo"),
            await client.call("benchmark_ledger_view", project="demo"),
            await client.call("hypothesis_view", project="demo", hypothesis_id=xw.hid),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session", out


@pytest.mark.anyio
async def test_new_tools_are_role_blind_before_a_pass_opens(
    settings: Settings, project: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skill(settings, "rf-ideate")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("registry_query", project="demo"),
            await client.call("benchmark_ledger_view", project="demo"),
        ]
    assert {(o["ok"], o["errors"][0]["reason"]) for o in outs} == {(False, "not available yet")}
