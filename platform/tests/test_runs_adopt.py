"""`factory runs adopt` (plan restart-and-costs R4): a driver started outside the runner is recorded
as a run folder. No real `claude` is started; the files are temporary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.errors import FactoryValidationError
from factory.services import resume, runner
from factory.services.context import Project
from tests.cli_helpers import _env

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
