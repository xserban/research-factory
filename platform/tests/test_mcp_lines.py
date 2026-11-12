"""`check` reports MCP configs that point at different code lines (IDEA-62)."""

import json
import os
from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.services.check import check
from factory.services.mcp_lines import (
    ServerLine,
    configured_paths,
    mcp_line_hits,
    read_config,
)
from factory.services.project import init_project
from tests.helpers import SESSION


def _write(path: Path, servers: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def _uv(project: str) -> dict[str, object]:
    return {"command": "uv", "args": ["run", "--project", project, "factory", "serve"]}


def _pythonpath(worktree: Path) -> dict[str, object]:
    return {
        "command": "/repo/platform/.venv/bin/factory",
        "args": ["serve"],
        "env": {"PYTHONPATH": f"{worktree}/platform/src", "FACTORY_ROOT": "/r"},
    }


def _only(read: list[ServerLine] | str) -> ServerLine:
    assert isinstance(read, list) and len(read) == 1, read
    return read[0]


def test_the_code_line_of_each_config_form(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    runtime = repo / ".claude" / "worktrees" / "runtime"
    in_repo = _write(repo / ".mcp.json", {"factory": _uv("platform")})
    outside = _write(tmp_path / "screeners" / "factory-mcp.json", {"factory": _pythonpath(runtime)})
    venv_only = _write(
        tmp_path / "v.json", {"f": {"command": f"{runtime}/platform/.venv/bin/factory"}}
    )
    a, b, c = (_only(read_config(p)) for p in (in_repo, outside, venv_only))
    assert a.code == repo.resolve()
    assert b.code == runtime.resolve()  # PYTHONPATH wins over the command's venv
    assert c.code == runtime.resolve()


def test_one_code_line_gives_no_finding(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    first = _write(tmp_path / "a.json", {"factory": _pythonpath(runtime)})
    second = _write(tmp_path / "b" / "c.json", {"factory": _uv(str(runtime / "platform"))})
    settings = Settings(root=tmp_path, user="obd", mcp_configs=(first, second))
    assert mcp_line_hits(settings) == []


def test_different_code_lines_are_reported_once(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    runtime = repo / ".claude" / "worktrees" / "runtime"
    in_repo = _write(repo / ".mcp.json", {"factory": _uv("platform")})
    outside = _write(tmp_path / "screeners" / "factory-mcp.json", {"factory": _pythonpath(runtime)})
    settings = Settings(root=tmp_path, user="obd", mcp_configs=(in_repo, outside))
    [hit] = mcp_line_hits(settings)
    assert hit.code == "mcp-code-lines-differ"
    assert set(hit.refs) == {str(in_repo), str(outside)}
    assert "2 code lines" in hit.message
    assert str(repo.resolve()) in hit.message and str(runtime.resolve()) in hit.message


def test_unreadable_and_unresolved_configs_are_reported(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    opaque = _write(tmp_path / "opaque.json", {"factory": {"command": "factory", "args": []}})
    other = _write(tmp_path / "other.json", {"git": {"command": "git-mcp"}})
    settings = Settings(root=tmp_path, user="obd", mcp_configs=(missing, broken, opaque, other))
    hits = mcp_line_hits(settings)
    assert [h.code for h in hits] == ["mcp-config-unresolved"] * 3
    assert [h.refs for h in hits] == [(str(missing),), (str(broken),), (str(opaque),)]


def test_configs_listed_in_the_root_file(tmp_path: Path) -> None:
    listed = _write(tmp_path / "x" / "a.json", {"factory": _uv("/w/platform")})
    env = tmp_path / "b.json"
    (tmp_path / "mcp-configs.txt").write_text(f"# pilot configs\n\nx/a.json\n{env}  # dup\n")
    settings = Settings(root=tmp_path, user="obd", mcp_configs=(env,))
    assert configured_paths(settings) == [env, listed]


def test_no_list_means_no_finding(tmp_path: Path) -> None:
    assert mcp_line_hits(Settings(root=tmp_path, user="obd")) == []


def test_settings_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACTORY_MCP_CONFIGS", os.pathsep.join(["/a.json", "", "/b.json"]))
    monkeypatch.setenv("FACTORY_INDEX_HOLD_MINUTES", "2.5")
    settings = Settings.load(root=tmp_path, user="obd")
    assert settings.mcp_configs == (Path("/a.json"), Path("/b.json"))
    assert settings.index_hold.total_seconds() == 150
    monkeypatch.delenv("FACTORY_INDEX_HOLD_MINUTES")
    assert Settings.load(root=tmp_path, user="obd").index_hold_minutes == 10
    monkeypatch.setenv("FACTORY_INDEX_HOLD_MINUTES", "soon")
    with pytest.raises(FactoryValidationError):
        Settings.load(root=tmp_path, user="obd")


def test_check_reports_the_finding_as_a_warning(tmp_path: Path, clock: FixedClock) -> None:
    first = _write(tmp_path / "cfg" / "a.json", {"factory": _uv("/one/platform")})
    second = _write(tmp_path / "cfg" / "b.json", {"factory": _uv("/two/platform")})
    settings = Settings(root=tmp_path, user="obd", mcp_configs=(first, second))
    project = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    findings = [f for f in check(project).findings if f.code.startswith("mcp-")]
    assert [(f.code, f.severity) for f in findings] == [("mcp-code-lines-differ", "warning")]
