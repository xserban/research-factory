"""`factory runs adopt` (plan restart-and-costs R4): a driver started outside the runner is recorded
as a run folder. No real `claude` is started; the files are temporary."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.errors import FactoryValidationError
from factory.services import resume, runner
from factory.services.context import Project
from tests.cli_helpers import _env
from tests.helpers import install_skill

SCREEN_TOOLS = ("mcp__factory__screen_next", "mcp__factory__screen_record")
PROMPT = "Screen the batch.\nLimit: stop after 5 units.\n"


def _prompt(tmp_path: Path) -> Path:
    path = tmp_path / "pass.txt"
    path.write_text(PROMPT, encoding="utf-8")
    return path


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "factory-mcp.json"
    server = {
        "command": "factory",
        "args": ["serve"],
        "env": {
            "FACTORY_ROOT": "/data/root",
            "FACTORY_PLUGIN_DIR": "/data/plugins",
            "ANTHROPIC_API_KEY": "sk-should-not-be-kept",
            "PYTHONPATH": "/src",
        },
    }
    path.write_text(json.dumps({"mcpServers": {"factory": server}}), encoding="utf-8")
    return path


def _log(tmp_path: Path) -> Path:
    path = tmp_path / "pass.log"
    path.write_bytes(b'{"type":"assistant"}\n{"type":"result"}\n')
    return path


def _adopt(
    project: Project,
    prompt: Path,
    *,
    tools: tuple[str, ...] = SCREEN_TOOLS,
    mcp_config: Path | None = None,
    log_file: Path | None = None,
    stage: str = "screen",
    model: str = "claude-haiku-5-5",
) -> str:
    return runner.adopt_driver(
        project,
        stage=stage,
        prompt_file=prompt,
        model=model,
        tools=tools,
        mcp_config=mcp_config,
        log_file=log_file,
        started_at=None,
    )


def test_tools_outside_the_stage_spec_are_refused_and_named(
    project: Project, tmp_path: Path
) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        _adopt(
            project,
            _prompt(tmp_path),
            tools=(*SCREEN_TOOLS, "Bash", "mcp__factory__card_create"),
        )
    text = str(caught.value)
    assert "Bash" in text and "mcp__factory__card_create" in text
    assert runner.run_status(project, reconcile=False) == []


def test_an_unknown_stage_and_a_blank_model_are_refused(project: Project, tmp_path: Path) -> None:
    with pytest.raises(FactoryValidationError):
        _adopt(project, _prompt(tmp_path), stage="nonsense")
    with pytest.raises(FactoryValidationError):
        _adopt(project, _prompt(tmp_path), model="   ")
    with pytest.raises(FactoryValidationError):
        _adopt(project, _prompt(tmp_path), tools=())
    assert runner.run_status(project, reconcile=False) == []


def test_a_missing_prompt_is_refused(project: Project, tmp_path: Path) -> None:
    with pytest.raises(FactoryValidationError):
        _adopt(project, tmp_path / "absent.txt")


def test_env_keys_outside_the_factory_set_are_dropped(project: Project, tmp_path: Path) -> None:
    source = _config(tmp_path)
    before = source.read_text(encoding="utf-8")
    run_id = _adopt(project, _prompt(tmp_path), mcp_config=source)
    folder = project.paths.dir / "runs" / run_id
    kept = json.loads((folder / "mcp.json").read_text(encoding="utf-8"))
    env = kept["mcpServers"]["factory"]["env"]
    assert set(env) == {"FACTORY_ROOT", "FACTORY_PLUGIN_DIR", "PYTHONPATH"}
    assert "sk-should-not-be-kept" not in (folder / "mcp.json").read_text(encoding="utf-8")
    assert source.read_text(encoding="utf-8") == before  # the source is only read


def test_with_a_log_the_run_is_recorded_started_and_lost(project: Project, tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)
    log = _log(tmp_path)
    run_id = _adopt(project, prompt, log_file=log)
    folder = project.paths.dir / "runs" / run_id
    assert (folder / "prompt.txt").read_text(encoding="utf-8") == PROMPT
    assert (folder / "log.jsonl").read_bytes() == log.read_bytes()
    record = runner.run_record(project, run_id)
    assert record is not None
    assert record.stage == "screen"
    assert record.allowed_tools == SCREEN_TOOLS
    assert project.blobs.get(record.prompt_blob) == prompt.read_bytes()
    assert runner.run_outcome(project, run_id) == "lost"
    views = runner.run_status(project, reconcile=False)
    assert [(v.run_id, v.status) for v in views] == [(run_id, "lost")]


def test_an_adopted_run_is_an_interrupted_run_for_resume(project: Project, tmp_path: Path) -> None:
    run_id = _adopt(project, _prompt(tmp_path), log_file=_log(tmp_path))
    found = resume.interrupted(project)
    assert [r.run_id for r in found.runs] == [run_id]
    assert found.runs[0].kind == "lost"
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan)


def test_without_a_log_the_run_is_open_until_reconciled(project: Project, tmp_path: Path) -> None:
    run_id = _adopt(project, _prompt(tmp_path))
    assert runner.run_outcome(project, run_id) is None
    found = resume.interrupted(project)
    assert [(r.run_id, r.kind) for r in found.runs] == [(run_id, "open-gone")]


def test_a_second_adoption_while_one_is_open_is_refused(project: Project, tmp_path: Path) -> None:
    _adopt(project, _prompt(tmp_path))
    with pytest.raises(FactoryValidationError):
        _adopt(project, _prompt(tmp_path))


def test_cli_adopts_and_prints_the_run_id(project: Project, tmp_path: Path) -> None:
    from factory.cli.main import app

    result = CliRunner().invoke(
        app,
        [
            "--project",
            project.paths.slug,
            "runs",
            "adopt",
            "--stage",
            "screen",
            "--prompt",
            str(_prompt(tmp_path)),
            "--model",
            "claude-haiku-5-5",
            "--tool",
            SCREEN_TOOLS[0],
            "--tool",
            SCREEN_TOOLS[1],
            "--log",
            str(_log(tmp_path)),
        ],
        env=_env(project.settings.root),
    )
    assert result.exit_code == 0, result.output
    run_id = result.output.strip().splitlines()[-1]
    assert runner.run_outcome(project, run_id) == "lost"


def _row(project: Project, run_id: str) -> Any:
    project.index.sync()
    with project.index.connect() as conn:
        return (
            conn.execute(text("SELECT * FROM runner_runs WHERE run_id = :r"), {"r": run_id})
            .mappings()
            .one()
        )


def test_the_event_is_marked_adopted_with_the_tools_the_driver_had(
    project: Project, tmp_path: Path
) -> None:
    run_id = _adopt(project, _prompt(tmp_path), log_file=_log(tmp_path))
    row = _row(project, run_id)
    assert row["adopted"] == 1
    assert json.loads(row["allowed_tools"]) == list(SCREEN_TOOLS)
    record = runner.run_record(project, run_id)
    assert record is not None and record.adopted is True


def test_the_cap_is_read_from_the_prompt(project: Project, tmp_path: Path) -> None:
    run_id = _adopt(project, _prompt(tmp_path), log_file=_log(tmp_path))
    assert _row(project, run_id)["unit_cap"] == 5  # "stop after 5 units"


def test_a_prompt_without_a_cap_gets_the_default_and_the_sentence_in_the_copy_only(
    project: Project, tmp_path: Path
) -> None:
    source = tmp_path / "bare.txt"
    source.write_text("Screen the batch.\n", encoding="utf-8")
    run_id = _adopt(project, source, log_file=_log(tmp_path))
    assert _row(project, run_id)["unit_cap"] == runner.DEFAULT_UNIT_CAP
    stored = (project.paths.dir / "runs" / run_id / "prompt.txt").read_text(encoding="utf-8")
    assert f"Limit: stop after {runner.DEFAULT_UNIT_CAP} units" in stored
    record = runner.run_record(project, run_id)
    assert record is not None
    assert project.blobs.get(record.prompt_blob).decode("utf-8") == stored
    assert source.read_text(encoding="utf-8") == "Screen the batch.\n"  # the source is unchanged


def test_the_mcp_config_keeps_only_command_args_and_allowed_env(
    project: Project, tmp_path: Path
) -> None:
    source = tmp_path / "mcp.json"
    server = {
        "command": "factory",
        "args": ["serve", "--api-key", "sk-1", "--token=t-2", "--port", "8000", "--PassWord", "pw"],
        "url": "https://example.test/mcp",
        "headers": {"Authorization": "Bearer abc"},
        "env": {"FACTORY_ROOT": "/r", "OTHER": "x"},
    }
    source.write_text(json.dumps({"mcpServers": {"f": server}}), encoding="utf-8")
    run_id = _adopt(project, _prompt(tmp_path), mcp_config=source)
    raw = (project.paths.dir / "runs" / run_id / "mcp.json").read_text(encoding="utf-8")
    kept = json.loads(raw)["mcpServers"]["f"]
    assert kept == {
        "command": "factory",
        "args": ["serve", "--port", "8000"],
        "env": {"FACTORY_ROOT": "/r"},
    }
    for leaked in ("sk-1", "t-2", "pw", "Bearer", "example.test"):
        assert leaked not in raw


def test_the_recorded_prompt_path_is_relative_inside_the_project_else_a_name(
    project: Project, tmp_path: Path
) -> None:
    inside = project.paths.dir / "inputs" / "pass.txt"
    inside.parent.mkdir(parents=True)
    inside.write_text(PROMPT, encoding="utf-8")
    first = _adopt(project, inside, log_file=_log(tmp_path))
    assert json.loads(_row(project, first)["command"]) == ["adopted", "inputs/pass.txt"]
    second = _adopt(project, _prompt(tmp_path), log_file=_log(tmp_path))
    assert json.loads(_row(project, second)["command"]) == ["adopted", "pass.txt"]


class _Done:
    pid = os.getpid()

    def wait(self) -> int:
        return 0


def test_an_adopted_run_resumes_with_the_full_stage_tools(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skill(project.settings, "rf-screen", "SCREEN SKILL BODY")
    monkeypatch.setattr(runner, "pending_work", lambda p: {"screen_a": 2})
    monkeypatch.setattr(resume, "pending_work", lambda p: {"screen_a": 2})
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")
    monkeypatch.setattr(runner, "_advance_after", lambda p: None)
    spec = runner.STAGES["screen"]
    assert set(SCREEN_TOOLS) < set(spec.tools)  # the driver had a subset
    adopted = _adopt(
        project, _prompt(tmp_path), log_file=_log(tmp_path), model=spec.model, tools=SCREEN_TOOLS
    )
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan)
    assert plan.run is not None and plan.run.adopted is True

    def launch(argv: Sequence[str], log_path: Path) -> _Done:
        log_path.write_text('{"type":"result"}\n', encoding="utf-8")
        return _Done()

    result = resume.resume(project, launcher=launch, foreground=True)
    assert isinstance(result, resume.ResumeResult) and result.refused == []
    assert result.run_id is not None
    new = _row(project, result.run_id)
    assert new["resumes"] == adopted and new["adopted"] == 0
    assert json.loads(new["allowed_tools"]) == list(spec.tools)
