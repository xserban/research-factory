"""The headless runner (plan feed-hub H5, decision 119 item 4). No real `claude` is started:
a fake launcher stands in for the process, and `claude_path` is patched."""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.services import runner, site_server
from factory.services.context import Project
from factory.services.site import site_dir
from tests.helpers import install_skill


class FakeProcess:
    """Stands in for the child: `wait` blocks until `release` is called."""

    def __init__(self, code: int = 0) -> None:
        self.pid = os.getpid()
        self.code = code
        self.done = threading.Event()

    def wait(self) -> int:
        self.done.wait(10)
        return self.code

    def release(self) -> None:
        self.done.set()


class FakeLauncher:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[tuple[list[str], Path]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, argv: Sequence[str], log_path: Path) -> FakeProcess:
        log_path.write_text('{"type":"result"}\n', encoding="utf-8")
        self.calls.append((list(argv), log_path))
        process = FakeProcess(self.code)
        self.processes.append(process)
        return process


@pytest.fixture(autouse=True)
def runner_env(project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, int]:
    install_skill(project.settings, "rf-extract", "EXTRACT SKILL BODY")
    install_skill(project.settings, "rf-screen", "SCREEN SKILL BODY")
    pending = {"screen_a": 3, "screen_ft_a": 0, "extract_a": 2}
    monkeypatch.setattr(runner, "pending_work", lambda p: dict(pending))
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")
    monkeypatch.setenv("PYTHONPATH", "/src")
    monkeypatch.setenv("FACTORY_RANKER_MODEL", "/models/specter2")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    return pending


@pytest.fixture
def stub_servable(runner_env: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    """For tests that start a run: `pending_units` takes the stage's servable count from the
    fixture's pending counts instead of the real DB (the gate tests below use the real function)."""

    def servable(project: Project, stage: ScreeningStage) -> tuple[int, bool]:
        key = "screen_a" if stage == ScreeningStage.TITLE_ABSTRACT else "screen_ft_a"
        return runner_env[key], False

    monkeypatch.setattr(runner, "_screen_servable", servable)


def _finish_all(launcher: FakeLauncher, run_id: str) -> None:
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)


def _issues(exc: pytest.ExceptionInfo[FactoryValidationError]) -> str:
    return " ".join(f"{i.field}: {i.reason}" for i in exc.value.issues)


def test_build_command_names_model_tools_skill_and_cap(project: Project) -> None:
    argv, config, prompt = runner.build_command(project, "screen", 7, claude="claude")
    assert argv[:2] == ["claude", "-p"] and argv[2] == prompt
    assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
    assert "--strict-mcp-config" in argv
    tools = argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]
    assert tools == [
        "mcp__factory__screen_next",
        "mcp__factory__screen_record",
        "mcp__factory__document_read",
        "mcp__factory__project_status",  # optional read named by the skill (a4d2bb8)
    ]
    assert "SCREEN SKILL BODY" in prompt
    assert "stop after 7 units or when the queue is empty" in prompt
    assert "project `demo`" in prompt and "role `screener`" in prompt
    assert "model `claude-haiku-5-5`" in prompt and "skill `rf-screen`" in prompt
    loaded: Any = config
    assert loaded["mcpServers"]["factory"]["args"] == ["serve"]


def test_child_is_denied_the_builtin_tools_and_asks_nothing(project: Project) -> None:
    argv, _, _ = runner.build_command(project, "screen")
    start = argv.index("--disallowedTools") + 1
    assert argv[start : argv.index("--permission-mode")] == list(runner.BUILTIN_TOOLS)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "Bash" in runner.BUILTIN_TOOLS and "Write" in runner.BUILTIN_TOOLS


def test_extract_stage_uses_sonnet_and_the_skills_tools(project: Project) -> None:
    argv, _, prompt = runner.build_command(project, "extract", 3)
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    tools = argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]
    assert tools == [
        "mcp__factory__extract_next",
        "mcp__factory__extract_record",
        "mcp__factory__document_read",
        "mcp__factory__project_status",  # optional read named by the skill (a4d2bb8)
    ]
    assert "EXTRACT SKILL BODY" in prompt


def test_mcp_config_carries_only_the_named_env_keys(project: Project) -> None:
    _, config, _ = runner.build_command(project, "screen")
    loaded: Any = config
    server = loaded["mcpServers"]["factory"]
    assert server["command"] == "/venv/bin/factory"
    assert set(server["env"]) == {
        "PYTHONPATH",
        "FACTORY_RANKER_MODEL",
        "FACTORY_PLUGIN_DIR",
        "FACTORY_ROOT",
        "FACTORY_UNIT_CAP",
    }
    assert server["env"]["FACTORY_ROOT"] == str(project.settings.root)
    assert "sk-secret" not in json.dumps(loaded)
    _, with_run, _ = runner.build_command(project, "screen", run_id="rnr_R")
    run_env = with_run["mcpServers"]["factory"]["env"]
    assert set(run_env) == set(server["env"]) | {"FACTORY_RUN_ID", "FACTORY_RUN_DIR"}
    assert run_env["FACTORY_RUN_DIR"] == str(project.paths.dir / "runs" / "rnr_R")


def test_unit_cap_and_stage_are_validated(project: Project) -> None:
    for cap in (0, runner.MAX_UNIT_CAP + 1):
        with pytest.raises(FactoryValidationError):
            runner.build_command(project, "screen", cap)
    with pytest.raises(FactoryValidationError):
        runner.build_command(project, "nonsense")


@pytest.mark.usefixtures("stub_servable")
def test_start_run_records_started_then_finished(project: Project) -> None:
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "screen", unit_cap=5, launcher=launcher)
    assert re.fullmatch(r"rnr_[0-9A-HJKMNP-TV-Z]{26}", run_id)
    [(argv, log_path)] = launcher.calls
    folder = log_path.parent
    assert argv[:4] == ["sh", "-c", runner._WRAPPER, "sh"] and argv[4] == str(folder / "exit")
    claude_argv = argv[5:]
    assert claude_argv[:2] == ["/usr/bin/claude", "-p"]
    assert (folder / "prompt.txt").read_text(encoding="utf-8") == claude_argv[2]
    assert json.loads((folder / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert (folder / "pid").read_text(encoding="utf-8") == str(os.getpid())
    [open_run] = runner.run_status(project)
    assert open_run.status == "running" and open_run.counts_before["screen_a"] == 3
    _finish_all(launcher, run_id)
    [done] = runner.run_status(project)
    assert done.status == "complete" and done.exit_status == 0 and done.counts_after is not None
    events = [e for e in _events(project) if e.type.startswith("runner.")]
    assert [e.type for e in events] == ["runner.started", "runner.finished"]
    assert all(e.actor.kind == "system" for e in events)
    started = events[0].payload
    assert started["command"][:2] == ["/usr/bin/claude", "-p"]
    assert started["command"][2] == "<prompt: see prompt.txt in the run folder>"
    assert "--permission-mode" in started["command"] and "--disallowedTools" in started["command"]
    assert claude_argv[2] not in json.dumps(started["command"])
    assert started["model"] == "claude-haiku-5-5" and started["unit_cap"] == 5
    assert project.blobs.get(started["prompt_blob"]).decode() == claude_argv[2]
    assert project.blobs.get(events[1].payload["log_blob"]) == b'{"type":"result"}\n'


def test_nonzero_exit_is_failed(project: Project) -> None:
    launcher = FakeLauncher(code=3)
    run_id = runner.start_run(project, "extract", launcher=launcher)
    _finish_all(launcher, run_id)
    [view] = runner.run_status(project)
    assert view.status == "failed" and view.exit_status == 3


@pytest.mark.usefixtures("stub_servable")
def test_one_run_per_project(project: Project) -> None:
    launcher = FakeLauncher()
    first = runner.start_run(project, "screen", launcher=launcher)
    with pytest.raises(FactoryValidationError) as exc:
        runner.start_run(project, "extract", launcher=launcher)
    assert "already open" in _issues(exc)
    assert len(launcher.calls) == 1
    assert len([e for e in _events(project) if e.type == "runner.started"]) == 1
    _finish_all(launcher, first)
    second = runner.start_run(project, "extract", launcher=launcher)
    _finish_all(launcher, second)


@pytest.mark.usefixtures("stub_servable")
def test_lost_run_is_reconciled_by_status_and_by_start(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "screen", launcher=launcher)
    launcher.processes[0].release()
    assert runner.wait(run_id, 10)
    lost_id = _start_unwatched(project)
    monkeypatch.setattr(runner, "_pid_alive", lambda pid: False)
    assert runner.run_status(project, reconcile=False)[0].status == "lost?"
    assert _outcome(project, lost_id) is None
    assert runner.run_status(project)[0].status == "lost"
    row = _outcome(project, lost_id)
    assert row == ("lost", None)
    # `start_run` closes an open run with a dead process first, then starts a new one
    again = _start_unwatched(project)
    new_launcher = FakeLauncher()
    fresh = runner.start_run(project, "extract", launcher=new_launcher)
    assert _outcome(project, again) == ("lost", None)
    _finish_all(new_launcher, fresh)


@pytest.mark.parametrize(("code", "outcome"), [(0, "complete"), (3, "failed")])
def test_reconcile_uses_the_recorded_exit_status(
    project: Project, monkeypatch: pytest.MonkeyPatch, code: int, outcome: str
) -> None:
    monkeypatch.setattr(runner, "_pid_alive", lambda pid: False)
    advanced: list[int] = []
    monkeypatch.setattr(runner, "_advance_after", lambda p: advanced.append(1))
    run_id = _start_unwatched(project)
    (project.paths.dir / "runs" / run_id / "exit").write_text(f"{code}\n", encoding="utf-8")
    assert runner.run_status(project)[0].status == outcome
    assert _outcome(project, run_id) == (outcome, code)
    assert advanced == [1]


def test_lost_without_exit_file_runs_no_steps(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "_pid_alive", lambda pid: False)
    run_id = _start_unwatched(project)
    (project.paths.dir / "runs" / run_id / "exit").write_text("", encoding="utf-8")
    assert runner.finish_lost(project, advance_after=False) == [run_id]
    assert _outcome(project, run_id) == ("lost", None)


def test_a_young_starting_marker_without_a_pid_keeps_the_run_alive(project: Project) -> None:
    run_id = _start_unwatched(project)
    folder = project.paths.dir / "runs" / run_id
    (folder / "pid").unlink()
    (folder / "starting").write_text("now", encoding="utf-8")
    assert runner.finish_lost(project) == []
    assert runner.run_status(project, reconcile=False)[0].status == "running"
    old = time.time() - runner.STARTING_GRACE - 5
    os.utime(folder / "starting", (old, old))
    assert runner.finish_lost(project, advance_after=False) == [run_id]


@pytest.mark.usefixtures("stub_servable")
def test_watcher_retries_a_failed_record_once(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "_RETRY_PAUSE", 0.0)
    monkeypatch.setattr(runner, "_advance_after", lambda p: None)
    real = runner._finish
    calls: list[int] = []

    def flaky(*args: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("disk")
        real(*args)

    monkeypatch.setattr(runner, "_finish", flaky)
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "screen", launcher=launcher)
    _finish_all(launcher, run_id)
    assert len(calls) == 2
    assert runner.run_status(project, reconcile=False)[0].status == "complete"


def test_refusals_write_nothing(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    launcher = FakeLauncher()
    monkeypatch.setattr(runner, "claude_path", lambda: None)
    with pytest.raises(FactoryValidationError) as exc:
        runner.start_run(project, "screen", launcher=launcher)
    assert "not on PATH" in _issues(exc) and "install Claude Code" in _issues(exc)
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "pending_work", lambda p: {})
    with pytest.raises(FactoryValidationError) as exc:
        runner.start_run(project, "screen", launcher=launcher)
    assert "no pending unit" in _issues(exc)
    assert launcher.calls == []
    assert [e for e in _events(project) if e.type.startswith("runner.")] == []


def test_runner_events_by_a_human_or_agent_fold_to_nothing(project: Project, agent: Actor) -> None:
    blob = project.blobs.put(b"prompt")
    started = {
        "run_id": "rnr_" + "0" * 26,
        "stage": "screen",
        "model": "claude-haiku-5-5",
        "allowed_tools": ["mcp__factory__screen_next"],
        "prompt_blob": blob,
        "unit_cap": 1,
        "counts_before": {"screen_a": 1},
        "command": ["claude"],
    }
    for actor in (project.human_actor(), agent):
        event = project.events.make(
            "runner.started",
            project.catalog.get("runner.started").payload.model_validate(started),
            actor,
            input_blob=blob if actor.kind == "agent" else None,
        )
        project.record([event])
    assert _count(project) == 0
    project.record(
        [
            project.events.make(
                "runner.started",
                project.catalog.get("runner.started").payload.model_validate(started),
                project.system_actor(),
            )
        ]
    )
    assert _count(project) == 1
    finished = {
        "run_id": started["run_id"],
        "exit_status": 0,
        "outcome": "complete",
        "log_blob": blob,
        "counts_after": {},
    }
    for actor in (project.human_actor(), agent):
        project.record(
            [
                project.events.make(
                    "runner.finished",
                    project.catalog.get("runner.finished").payload.model_validate(finished),
                    actor,
                    input_blob=blob if actor.kind == "agent" else None,
                )
            ]
        )
    assert _outcome(project, str(started["run_id"])) is None


def test_duplicate_started_is_ignored_and_the_first_finish_stands(project: Project) -> None:
    from factory.model.runner import RunnerFinished, RunnerStarted

    run_id = _start_unwatched(project)
    first = project.blobs.put(b"first")
    again = RunnerStarted(
        run_id=run_id,
        stage="extract",
        model="claude-sonnet-5-5",
        allowed_tools=("mcp__factory__extract_next",),
        prompt_blob=first,
        unit_cap=9,
        counts_before={"extract_a": 9},
        command=("other",),
    )
    project.record([project.events.make("runner.started", again, project.system_actor())])
    assert _count(project) == 1
    [view] = runner.run_status(project, reconcile=False)
    assert (view.stage, view.unit_cap, view.model) == ("screen", 1, "claude-haiku-5-5")
    for outcome, code in (("failed", 5), ("complete", 0)):
        finished = RunnerFinished(
            run_id=run_id,
            exit_status=code,
            outcome=outcome,  # type: ignore[arg-type]
            log_blob=first,
            counts_after={},
        )
        project.record([project.events.make("runner.finished", finished, project.system_actor())])
    assert _outcome(project, run_id) == ("failed", 5)


# --- POST /api/queue/process ---


@pytest.fixture
def served(project: Project) -> Iterator[tuple[int, str]]:
    queue_dir = site_dir(project) / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "index.html").write_text("<html><head></head><body>q</body></html>")
    httpd, _ = site_server.make_server(project, 0, background=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    status, body = _request(port, "GET", "/queue/")
    assert status == 200
    match = re.search(r"name='factory-token' content='([^']+)'", body)
    assert match is not None
    yield port, match.group(1)
    httpd.shutdown()
    httpd.server_close()


def _request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Content-Type": "application/json", **(headers or {})}
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
    response = conn.getresponse()
    data = response.read().decode()
    conn.close()
    return response.status, data


def _started_events(project: Project) -> list[Any]:
    return [e for e in _events(project) if e.type == "runner.started"]


def test_process_endpoint_needs_the_token_and_writes_nothing_without_it(
    project: Project, served: tuple[int, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = FakeLauncher()
    monkeypatch.setattr(runner, "default_launcher", launcher)
    port, token = served
    body = {"stage": "screen"}
    assert _request(port, "POST", "/api/queue/process", body)[0] == 403
    assert _request(port, "POST", "/api/queue/process", body, {"X-Factory-Token": "no"})[0] == 403
    auth = {"X-Factory-Token": token}
    assert (
        _request(port, "POST", "/api/queue/process", body, {**auth, "Origin": "http://x.y"})[0]
        == 403
    )
    assert (
        _request(port, "POST", "/api/queue/process", body, {**auth, "Host": "evil.example"})[0]
        == 403
    )
    assert (
        _request(port, "POST", "/api/queue/process", body, {**auth, "Content-Type": "text/plain"})[
            0
        ]
        == 415
    )
    assert _request(port, "POST", "/api/queue/process", {"stage": "x" * 20000}, auth)[0] == 413
    assert _started_events(project) == [] and launcher.calls == []


@pytest.mark.usefixtures("stub_servable")
def test_process_endpoint_starts_a_run_and_validates(
    project: Project, served: tuple[int, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = FakeLauncher()
    monkeypatch.setattr(runner, "default_launcher", launcher)
    port, token = served
    auth = {"X-Factory-Token": token}
    assert _request(port, "POST", "/api/queue/process", {"stage": "other"}, auth)[0] == 400
    code, _ = _request(
        port, "POST", "/api/queue/process", {"stage": "screen", "unit_cap": "9"}, auth
    )
    assert code == 400
    code, payload = _request(
        port, "POST", "/api/queue/process", {"stage": "screen", "unit_cap": 4}, auth
    )
    assert code == 200
    run_id = json.loads(payload)["run_id"]
    again = _request(port, "POST", "/api/queue/process", {"stage": "extract"}, auth)
    assert again[0] == 400 and "already open" in again[1]
    status, listing = _request(port, "GET", "/api/queue/runs")
    assert status == 200 and json.loads(listing)["runs"][0]["status"] == "running"
    _finish_all(launcher, run_id)
    assert len(_started_events(project)) == 1


def test_process_endpoint_is_authorised_by_its_own_row() -> None:
    from factory.services.access import TOOL_PERMISSIONS, Permission

    assert TOOL_PERMISSIONS["cli:queue process"] is Permission.WORK_RUN


# --- helpers ---


def _events(project: Project) -> list[Any]:
    from factory.events.reader import read_all

    return list(read_all(project.paths.events_dir, project.catalog))


def _count(project: Project) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM runner_runs")).scalar_one())


def _outcome(project: Project, run_id: str) -> tuple[str, int | None] | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT outcome, exit_status FROM runner_runs WHERE run_id = :r"), {"r": run_id}
        ).one()
    return None if row[0] is None else (str(row[0]), row[1])


def _start_unwatched(project: Project) -> str:
    """An open run as a crashed server leaves it: started, a pid file, no watcher."""
    from factory.model.runner import RunnerStarted

    run_id = project.ids.new("rnr")
    folder = project.paths.dir / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "pid").write_text("999999", encoding="utf-8")
    payload = RunnerStarted(
        run_id=run_id,
        stage="screen",
        model="claude-haiku-5-5",
        allowed_tools=("mcp__factory__screen_next",),
        prompt_blob=project.blobs.put(b"p"),
        unit_cap=1,
        counts_before={"screen_a": 1},
        command=("claude",),
    )
    project.record([project.events.make("runner.started", payload, project.system_actor())])
    return run_id


# --- Screening pending under the calibration gate ---


def _gate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    required: bool,
    drawn: bool,
    passed: bool,
    calibration: set[str],
    population: set[str],
    decided: set[str],
    dedup: bool = True,
) -> None:
    from types import SimpleNamespace

    status = SimpleNamespace(required=required, passed={"A": passed, "B": passed})
    monkeypatch.setattr("factory.services.dedup.dedup_current", lambda p: dedup)
    monkeypatch.setattr("factory.services.calibration.calibration_status", lambda p, stage: status)
    monkeypatch.setattr("factory.services.calibration.calibration_drawn", lambda p, stage: drawn)
    monkeypatch.setattr(
        "factory.services.calibration.calibration_items", lambda p, stage: sorted(calibration)
    )
    monkeypatch.setattr(
        "factory.services.calibration.stage_population", lambda p, stage: population
    )
    monkeypatch.setattr(
        "factory.services.screening.live_decisions",
        lambda p, label, stage: [SimpleNamespace(work_id=w) for w in sorted(decided)],
    )


def test_screen_pending_is_zero_until_the_calibration_set_is_drawn(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    pop = {"w1", "w2", "w3"}
    _gate(
        monkeypatch,
        required=True,
        drawn=False,
        passed=False,
        calibration=set(),
        population=pop,
        decided=set(),
    )
    assert sum(runner.pending_units(project, "screen").values()) == 0


def test_screen_pending_counts_only_calibration_while_the_gate_is_closed(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    pop = {"w1", "w2", "w3", "w4"}
    _gate(
        monkeypatch,
        required=True,
        drawn=True,
        passed=False,
        calibration={"w1", "w2"},
        population=pop,
        decided={"w1"},
    )
    counts = runner.pending_units(project, "screen")
    assert sum(counts.values()) == 2  # w2 per stage; the open tasks of ordinary work do not count
    assert counts[runner.STAGES["screen"].kinds[0]] == 1


def test_screen_pending_counts_everything_once_the_gate_is_passed_or_absent(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    pop = {"w1", "w2", "w3", "w4", "w5"}
    _gate(
        monkeypatch,
        required=True,
        drawn=True,
        passed=True,
        calibration={"w1"},
        population=pop,
        decided={"w1"},
    )
    assert runner.pending_units(project, "screen")[runner.STAGES["screen"].kinds[0]] == 4
    _gate(
        monkeypatch,
        required=False,
        drawn=False,
        passed=False,
        calibration=set(),
        population=pop,
        decided=set(),
    )
    assert runner.pending_units(project, "screen")[runner.STAGES["screen"].kinds[0]] == 5


def test_screen_pending_is_zero_while_dedup_is_not_current(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate(
        monkeypatch,
        required=False,
        drawn=False,
        passed=True,
        calibration=set(),
        population={"w1"},
        decided=set(),
        dedup=False,
    )
    assert sum(runner.pending_units(project, "screen").values()) == 0


# --- Mine stages: the calibration gate and the protocol's exploratory declaration (IDEA-69) ---

MINE = "mine:m-alpha"


def _mine_stage(project: Project, monkeypatch: pytest.MonkeyPatch, state: object | None) -> None:
    """A `mine:m-alpha` stage of listed version 2 with 3 pending units; `state` is the lifecycle
    state `miner_state` returns (None leaves the real function in place)."""
    from factory.services.miners import MinerState

    install_skill(project.settings, "rf-mine", "MINE SKILL BODY")
    monkeypatch.setattr(runner, "_mine_use", lambda p, m: 2)
    monkeypatch.setattr("factory.services.pipeline.unit_pending", lambda p, k: 3)
    if state is not None:
        assert isinstance(state, MinerState)
        monkeypatch.setattr("factory.services.miners.miner_state", lambda p, n, v: state)


def _started_payloads(project: Project) -> list[dict[str, Any]]:
    return [e.payload for e in _events(project) if e.type == "runner.started"]


def test_uncalibrated_mine_stage_is_refused_before_launch(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services.miners import MinerState

    _mine_stage(project, monkeypatch, MinerState.REGISTERED)
    launcher = FakeLauncher()
    with pytest.raises(FactoryValidationError) as exc:
        runner.start_run(project, MINE, launcher=launcher)
    assert launcher.calls == [] and runner.run_status(project) == []
    assert _started_payloads(project) == []
    assert [i.field for i in exc.value.issues] == ["stage"]
    text_out = _issues(exc)
    assert "m-alpha" in text_out and "version 2" in text_out
    assert "calibrate it first" in text_out and "factory protocol amend" in text_out


def _declared(monkeypatch: pytest.MonkeyPatch, value: bool = True) -> None:
    """The protocol's use of the miner is (not) declared exploratory."""
    monkeypatch.setattr("factory.services.mining.use_is_exploratory", lambda p, n, v: value)


def test_declared_exploratory_mine_stage_launches_and_records_it(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services.miners import MinerState

    _mine_stage(project, monkeypatch, MinerState.REGISTERED)
    _declared(monkeypatch)
    launcher = FakeLauncher()
    run_id = runner.start_run(project, MINE, launcher=launcher)
    [(_, log_path)] = launcher.calls
    prompt = (log_path.parent / "prompt.txt").read_text(encoding="utf-8")
    assert "exploratory" not in prompt  # the task carries the mark, not the prompt
    [started] = _started_payloads(project)
    assert started["exploratory"] is True
    _finish_all(launcher, run_id)


def test_calibrated_mine_stage_launches_as_before(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services.miners import MinerState

    _mine_stage(project, monkeypatch, MinerState.CALIBRATED)
    launcher = FakeLauncher()
    run_id = runner.start_run(project, MINE, launcher=launcher)
    [(_, log_path)] = launcher.calls
    prompt = (log_path.parent / "prompt.txt").read_text(encoding="utf-8")
    assert "exploratory" not in prompt
    [started] = _started_payloads(project)
    assert "exploratory" not in started  # omitted when false
    _finish_all(launcher, run_id)


def test_resumed_run_of_a_declared_use_records_it_again(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services.miners import MinerState

    _mine_stage(project, monkeypatch, MinerState.REGISTERED)
    _declared(monkeypatch)
    launcher = FakeLauncher(code=1)
    first = runner.start_run(project, MINE, launcher=launcher)
    _finish_all(launcher, first)
    second = runner.start_run(project, MINE, launcher=launcher, resumes=first)
    assert [p["exploratory"] for p in _started_payloads(project)] == [True, True]
    _finish_all(launcher, second)


def test_start_run_and_queue_process_have_no_exploratory_option() -> None:
    import inspect

    from typer.testing import CliRunner

    from factory.cli.main import app

    assert "exploratory" not in inspect.signature(runner.start_run).parameters
    assert "exploratory" not in inspect.signature(runner.build_command).parameters
    result = CliRunner().invoke(app, ["queue", "process", "--stage", MINE, "--exploratory"])
    assert result.exit_code != 0


def test_runner_started_omits_exploratory_when_false() -> None:
    """A production run's `runner.started` payload has no `exploratory` key (it reads as before
    the field existed); an exploratory one carries it; both read back."""
    from factory.model.runner import RunnerStarted

    fields: dict[str, object] = {
        "run_id": "rnr_01HZZZZZZZZZZZZZZZZZZZZZZZ",
        "stage": "mine:m-x",
        "model": "claude-haiku-5-5",
        "allowed_tools": ("mcp__factory__mine_next",),
        "prompt_blob": "sha256:" + "0" * 64,
        "unit_cap": 1,
        "counts_before": {"mine:m-x": 1},
        "command": ("claude",),
    }
    plain = RunnerStarted.model_validate(fields).model_dump(mode="json")
    assert "exploratory" not in plain
    assert RunnerStarted.model_validate(plain).exploratory is False
    marked = RunnerStarted.model_validate({**fields, "exploratory": True}).model_dump(mode="json")
    assert marked["exploratory"] is True
