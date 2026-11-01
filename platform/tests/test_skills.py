"""Skill references are computed by the platform from the installed skill file."""

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.skills import skill_ref
from tests.helpers import install_skill


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def test_bare_name_resolves_to_hash_of_the_installed_file(settings: Settings) -> None:
    install_skill(settings, "rf-probe", "v1")
    assert skill_ref(settings, "rf-probe") == "rf-probe@" + _digest(b"v1")


def test_matching_supplied_hash_is_accepted(settings: Settings) -> None:
    ref = install_skill(settings, "rf-probe", "v1")
    assert skill_ref(settings, ref) == ref


def test_stale_supplied_hash_is_rejected(settings: Settings) -> None:
    stale = install_skill(settings, "rf-probe", "v1")
    install_skill(settings, "rf-probe", "v2")
    with pytest.raises(FactoryValidationError) as err:
        skill_ref(settings, stale)
    assert err.value.issues[0].field == "skill"
    assert err.value.issues[0].reason.startswith("skill file changed: installed rf-probe@")


def test_unknown_skill_is_rejected(settings: Settings) -> None:
    with pytest.raises(FactoryValidationError) as err:
        skill_ref(settings, "rf-missing")
    assert err.value.issues[0].field == "skill"
    assert err.value.issues[0].reason.startswith("no installed skill 'rf-missing' under ")


@pytest.mark.parametrize("bad", ["RF-probe", "rf probe", "../rf", "rf-probe@XYZ", "", "rf@1234"])
def test_malformed_skill_is_rejected(settings: Settings, bad: str) -> None:
    install_skill(settings, "rf-probe")
    with pytest.raises(FactoryValidationError) as err:
        skill_ref(settings, bad)
    assert [(i.field, i.reason) for i in err.value.issues] == [
        ("skill", "must be a skill name like rf-probe")
    ]


def test_plugin_dir_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FACTORY_PLUGIN_DIR", str(tmp_path / "plug"))
    assert Settings.load(root=tmp_path, user="obd").plugin_dir == tmp_path / "plug"
    argued = Settings.load(root=tmp_path, user="obd", plugin_dir=tmp_path / "arg")
    assert argued.plugin_dir == tmp_path / "arg"


def test_plugin_dir_defaults_to_root_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FACTORY_PLUGIN_DIR", raising=False)
    assert Settings.load(root=tmp_path, user="obd").plugin_dir == tmp_path / "plugin"
    assert Settings(root=tmp_path, user="obd").plugin_dir == tmp_path / "plugin"


@pytest.mark.anyio
async def test_tool_records_platform_computed_skill(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
) -> None:
    install_skill(settings, "rf-search", "search skill text")
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=dict(mock_sources(openalex=[])))
    async with Client(server) as client:
        res = await client.call_tool(
            "search_run",
            {
                "project": "demo",
                "source": "openalex",
                "query": "linear attention",
                "role": "screener-a",
                "model": "claude-opus-5-5",
                "skill": "rf-search",
            },
        )
    assert res.is_error is not True
    registered = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "query.registered"
    ]
    assert len(registered) == 1
    assert registered[0].actor.skill == skill_ref(settings, "rf-search")
