"""The runner stages `spar` and `ask` (plan spar-night N3). No real `claude` is started."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.model.runner import RunnerStarted
from factory.services import chat_requests as cr
from factory.services import runner
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.helpers import install_skill
from tests.test_runner import FakeLauncher

SPEC = SelectionSpec(layers=["core"])
PREFIX = "mcp__factory__"
COMMON = (
    "selection_resolve", "claims_digest", "corpus_search", "chat_sections", "chat_verify",
    "paper_profiles", "chat_candidates", "chat_request_next", "chat_request_view",
    "document_read",
)  # fmt: skip


@pytest.fixture(autouse=True)
def chat_env(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    install_skill(project.settings, "rf-chat", "CHAT SKILL BODY")
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")


def test_the_stages_are_declared_with_the_chat_tools_and_sonnet() -> None:
    spar, ask = runner.STAGES["spar"], runner.STAGES["ask"]
    for spec in (spar, ask):
        assert spec.skill == "rf-chat" and spec.model == "claude-sonnet-5-5"
        assert spec.fixed_cap == 1
        assert {f"{PREFIX}{t}" for t in COMMON} <= set(spec.tools)
        assert all(t.startswith(PREFIX) for t in spec.tools)
    assert {f"{PREFIX}sheet_{t}" for t in ("open", "argue", "close", "view")} <= set(spar.tools)
    assert {f"{PREFIX}answer_{t}" for t in ("record", "view")} <= set(ask.tools)
    assert not any("answer_" in t for t in spar.tools)
    assert not any("sheet_" in t for t in ask.tools)
    assert runner.is_stage_key("spar") and runner.is_stage_key("ask")
    assert "spar" in runner.stage_keys() and "ask" in runner.stage_keys()
    RunnerStarted(
        run_id="rnr_" + "0" * 26, stage="spar", model="m", allowed_tools=("t",), prompt_blob="sha256:" + "0" * 64,
        unit_cap=1, counts_before={"spar": 1}, command=("c",),
    )  # fmt: skip


def test_pending_units_are_the_open_requests_of_the_kind(
    project: Project,
) -> None:
    human = project.human_actor()
    assert runner.pending_units(project, "spar") == {"spar": 0}
    cr.request_chat(project, human, "spar", SPEC, hypothesis="h")
    cr.request_chat(project, human, "spar", SPEC, hypothesis="h2", mode="prepare")
    cr.request_chat(project, human, "ask", SPEC, question="q")
    assert runner.pending_units(project, "spar") == {"spar": 2}
    assert runner.pending_units(project, "ask") == {"ask": 1}


def test_start_run_refuses_with_no_open_request_and_writes_nothing(project: Project) -> None:
    launcher = FakeLauncher()
    human = project.human_actor()
    cr.request_chat(project, human, "ask", SPEC, question="q")
    with pytest.raises(FactoryValidationError) as err:
        runner.start_run(project, "spar", launcher=launcher)
    assert err.value.issues[0].field == "stage" and "no pending unit" in err.value.issues[0].reason
    assert launcher.calls == [] and runner.run_status(project) == []


def test_start_run_launches_one_unit_whatever_the_cap_asked(project: Project) -> None:
    cr.request_chat(project, project.human_actor(), "spar", SPEC, hypothesis="h")
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "spar", unit_cap=25, launcher=launcher)
    argv = launcher.calls[0][0]
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    record = runner.run_record(project, run_id)
    assert record is not None and record.stage == "spar" and record.unit_cap == 1
    assert record.allowed_tools == runner.STAGES["spar"].tools
    config = (project.paths.dir / "runs" / run_id / "mcp.json").read_text(encoding="utf-8")
    assert '"FACTORY_UNIT_CAP": "1"' in config and run_id in config
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)
    # the run ended without taking the request: it is open again, not failed (nothing took it)
    assert cr.open_count(project, "spar") == 1


def test_the_prompt_tells_an_unattended_run_to_take_a_request(project: Project) -> None:
    _, _, spar = runner.build_command(project, "spar")
    _, _, ask = runner.build_command(project, "ask")
    for prompt, kind in ((spar, "spar"), (ask, "ask")):
        assert "chat_request_next" in prompt and "CHAT SKILL BODY" in prompt
        assert "skill `rf-chat`" in prompt and "role `" in prompt
        assert "stop after 1 units" in prompt
        assert "no question" in prompt.lower() and "unattended" in prompt.lower()
        assert f"`{kind}`" in prompt
        assert "request_id" in prompt
    assert "Explore" in spar and "Prepare" in spar and "case against" in spar
    assert "case for" in spar and "parent" in spar
    assert "sheet_open" in spar and "answer_record" not in spar
    assert "answer_record" in ask and "sheet_open" not in ask
    assert "Prepare" not in ask


def test_a_resumed_chat_run_keeps_its_recorded_prompt(project: Project) -> None:
    cr.request_chat(project, project.human_actor(), "ask", SPEC, question="q")
    launcher = FakeLauncher(1)
    run_id = runner.start_run(project, "ask", launcher=launcher)
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)
    again = runner.start_run(project, "ask", launcher=FakeLauncher(), resumes=run_id)
    assert again != run_id
