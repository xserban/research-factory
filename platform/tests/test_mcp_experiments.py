"""The experiment MCP tools (slice 6, plan XP-A task 7).

Four tools and no more: an agent drafts a design and registers planned runs. Nothing over MCP
freezes, unlocks, ingests, accepts or records a deviation, and no view carries the nonce, a metric
value or a designer's session. Every tool is refused to a pass session and role-blind before a
pass opens.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.experiments import (
    experiment_view,
    freeze_experiment,
    unlock_experiment,
    unlock_nonce,
)
from factory.services.xruns import ingest_results, xrun_list
from tests.experiment_helpers import XW, cell, results_file, xw
from tests.extraction_helpers import SESSION_A
from tests.helpers import install_skill, open_session
from tests.hypothesis_helpers import HW, gw, hw
from tests.test_mcp_cards import SESSION_E, _session

TOOLS = ("experiment_design", "experiment_view", "xrun_register", "xrun_list")
EXPERIMENT = {"role": "designer", "model": "claude-opus-5-5", "skill": "rf-experiment"}


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


def _dump(w: XW, **over: object) -> dict[str, object]:
    return w.design(**over).model_dump(mode="json")


@pytest.mark.anyio
async def test_tool_list_pins_the_experiment_tools(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    related = [n for n in names if n.startswith(("experiment_", "xrun_"))]
    assert sorted(related) == sorted(TOOLS)
    for name in names:  # no tool of the platform freezes, unlocks, ingests or accepts
        assert not any(word in name for word in ("freeze", "unlock", "ingest", "accept")), name
    assert not [
        n
        for n in names
        if n.startswith(("experiment_", "xrun_", "baseline_", "runs_"))
        and n.endswith(("_record", "_report", "_deviation"))
    ]


@pytest.mark.anyio
async def test_design_view_register_flow_without_results_or_nonce(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    xw: XW,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-experiment")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        drafted = await client.call(
            "experiment_design", project="demo", design=_dump(xw), **EXPERIMENT
        )
        draft_view = await client.call(
            "experiment_view",
            project="demo",
            experiment_id=drafted["data"]["experiment_id"],
        )
        bad = await client.call(
            "experiment_design",
            project="demo",
            design=_dump(xw, seeds=[1, 2]),
            amend_of="exp_01JZ9Q3K5M7N8P0R2S4T6V8W99",
            reason="r",
            **EXPERIMENT,
        )
        unknown_field = await client.call(
            "experiment_design",
            project="demo",
            design={**_dump(xw), "e_version": "E@00000000"},
            **EXPERIMENT,
        )
    assert drafted["ok"] is True, drafted
    exp = drafted["data"]["experiment_id"]
    assert draft_view["data"]["baselines"] == {xw.rows[0]: "pending"}
    assert draft_view["data"]["state"] == "draft" and "nonce" not in json.dumps(draft_view)
    assert drafted["data"]["e_version"].startswith("E@") and drafted["data"]["issues"] == []
    assert bad["ok"] is False and unknown_field["ok"] is False
    assert unknown_field["errors"][0]["field"] == "design.e_version"
    [event] = _of(project, "experiment.designed")
    assert event.actor.kind == "agent" and event.input_blob is not None
    assert event.actor.skill is not None and event.actor.skill.startswith("rf-experiment@")

    async with open_session(settings, clock) as client:  # amend before the freeze
        amended = await client.call(
            "experiment_design",
            project="demo",
            design=_dump(xw, seeds=[1, 2, 3, 4], baselines=[]),
            amend_of=exp,
            reason="a fourth seed",
            semantic=False,
            **EXPERIMENT,
        )
        no_reason = await client.call(
            "experiment_design", project="demo", design=_dump(xw), amend_of=exp, **EXPERIMENT
        )
    assert amended["ok"] is True and amended["data"]["experiment_id"] == exp
    assert no_reason["ok"] is False and no_reason["errors"][0]["field"] == "reason"

    freeze_experiment(project, human, exp)
    async with open_session(settings, clock) as client:
        late = await client.call(
            "experiment_design",
            project="demo",
            design=_dump(xw),
            amend_of=exp,
            reason="too late",
            **EXPERIMENT,
        )
        with_config = await client.call(
            "xrun_register",
            project="demo",
            experiment_id=exp,
            cell={**cell("ablation:no-norm", split="dev").model_dump(mode="json"), "config": {}},
            **EXPERIMENT,
        )
        registered = await client.call(
            "xrun_register",
            project="demo",
            experiment_id=exp,
            cell=cell("ablation:no-norm", split="dev").model_dump(mode="json"),
            **EXPERIMENT,
        )
        locked = await client.call(
            "xrun_register",
            project="demo",
            experiment_id=exp,
            cell=cell("treatment").model_dump(mode="json"),
            **EXPERIMENT,
        )
    assert late["ok"] is False and late["errors"][0]["reason"] == "frozen"
    assert with_config["ok"] is False and with_config["errors"][0]["field"] == "cell.config"
    assert registered["ok"] is True
    assert locked["ok"] is False and locked["errors"][0]["reason"] == "locked"
    run = registered["data"]["run_id"]
    [reg] = _of(project, "xrun.registered")
    assert reg.actor.kind == "agent" and reg.input_blob is not None

    ingest_results(project, human, results_file(tmp_path, run, value="71.25"))
    exp_view = experiment_view(project, exp)
    assert exp_view is not None
    unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    assert nonce is not None
    async with open_session(settings, clock) as client:
        viewed = await client.call("experiment_view", project="demo", experiment_id=exp)
        listed = await client.call("xrun_list", project="demo", experiment_id=exp)
        filtered = await client.call(
            "xrun_list", project="demo", experiment_id=exp, arm="baseline", split="dev"
        )
        unknown = await client.call("experiment_view", project="demo", experiment_id="exp_nope")
    assert viewed["ok"] is True and viewed["data"]["state"] == "unlocked"
    text = json.dumps([viewed, listed, filtered])
    assert nonce not in text and "nonce" not in text  # the nonce is the researcher's alone
    assert "71.25" not in text and "gpu_hours" not in json.dumps(
        listed
    )  # no result reaches an agent
    assert "designer_sessions" not in text and SESSION_E not in text
    assert viewed["data"]["baselines"] == {}
    assert [r["state"] for r in listed["data"]["runs"]] == ["completed"]
    assert set(listed["data"]["runs"][0]) == {
        "run_id",
        "cell",
        "config_hash",
        "state",
        "exploratory",
        "flags",
        "event_id",
    }
    assert filtered["data"]["runs"] == []
    assert unknown["ok"] is False


@pytest.mark.anyio
async def test_the_hypothesis_rationale_and_lead_do_not_travel(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    xw: XW,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.hypothesis_helpers import LEAD_TEXT, RATIONALE

    install_skill(settings, "rf-experiment")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        drafted = await client.call(
            "experiment_design", project="demo", design=_dump(xw), **EXPERIMENT
        )
        viewed = await client.call(
            "experiment_view", project="demo", experiment_id=drafted["data"]["experiment_id"]
        )
    text = json.dumps([drafted, viewed])
    assert RATIONALE not in text and LEAD_TEXT not in text  # R-51: a critic-side tool of design


@pytest.mark.anyio
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    xw: XW,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-experiment")
    _session(monkeypatch, SESSION_A)  # an extraction-pass session of the evidence world
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("experiment_design", project="demo", design=_dump(xw), **EXPERIMENT),
            await client.call("experiment_view", project="demo", experiment_id="exp_x"),
            await client.call(
                "xrun_register",
                project="demo",
                experiment_id="exp_x",
                cell=cell().model_dump(mode="json"),
                **EXPERIMENT,
            ),
            await client.call("xrun_list", project="demo", experiment_id="exp_x"),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session", out
    assert _of(project, "experiment.designed") == []


@pytest.mark.anyio
async def test_tools_are_role_blind_before_a_pass_opens(
    settings: Settings, project: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skill(settings, "rf-experiment")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("experiment_design", project="demo", design={}, **EXPERIMENT),
            await client.call("experiment_view", project="demo", experiment_id="exp_x"),
            await client.call(
                "xrun_register", project="demo", experiment_id="exp_x", cell={}, **EXPERIMENT
            ),
            await client.call("xrun_list", project="demo", experiment_id="exp_x"),
        ]
    assert {(o["ok"], o["errors"][0]["reason"]) for o in outs} == {(False, "not available yet")}
