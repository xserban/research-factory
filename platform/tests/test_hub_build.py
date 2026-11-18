"""Static build harness for hub v2: payload registry, pages and the CLI (plan hub-ui)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services import hub_build as hb
from factory.services import hub_payloads as hp
from factory.services import hub_ui
from factory.services.context import Project
from tests.cli_helpers import _env
from tests.fulltext_helpers import _ft_world
from tests.helpers import SourcesFor
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)

CORE = {"shell", "overview", "flow", "screening", "graph", "lenses", "living"}


@pytest.fixture
def world(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    listed_miners: None,  # noqa: F811
) -> Project:
    _ft_world(project, agent, human, mock_sources)
    return project


def _tree(out: Path) -> dict[str, bytes]:
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def test_every_payload_is_written_as_json_and_js(world: Project, tmp_path: Path) -> None:
    report = hb.build_static(world, tmp_path / "ui")
    assert report.errors == {}
    assert set(report.payloads) == CORE
    for name in CORE:
        data = json.loads((tmp_path / "ui/data" / f"{name}.json").read_text(encoding="utf-8"))
        js = (tmp_path / "ui/data" / f"{name}.js").read_text(encoding="utf-8")
        assert js.startswith("window.HUB_DATA=window.HUB_DATA||{};")
        assert json.loads(js.split("=", 2)[2].rstrip(";\n")) == data
        assert report.payloads[name].bytes == len(
            (tmp_path / "ui/data" / f"{name}.json").read_bytes()
        )
    for asset in hub_ui.ASSETS:
        assert (tmp_path / "ui/assets" / asset).read_bytes() == hub_ui.asset_bytes(asset)
    assert (tmp_path / "ui/overview.html").is_file()


def test_shell_payload_carries_works_glossary_and_labels(world: Project, tmp_path: Path) -> None:
    hb.build_static(world, tmp_path / "ui", only={"shell"})
    shell = json.loads((tmp_path / "ui/data/shell.json").read_text(encoding="utf-8"))
    assert shell["slug"] == world.paths.slug
    assert set(shell["labels"]) == set(hub_ui.LABELS)
    assert set(shell["glossary"]) == set(hub_ui.GLOSSARY)
    ids = [w["id"] for w in shell["works"]]
    assert ids == sorted(ids) and len(ids) == shell["prisma"]["included"]
    assert {"id", "title", "year", "month", "layer"} <= set(shell["works"][0])


def test_build_is_deterministic(world: Project, tmp_path: Path) -> None:
    hb.build_static(world, tmp_path / "a")
    hb.build_static(world, tmp_path / "b")
    assert _tree(tmp_path / "a") == _tree(tmp_path / "b")


def test_flow_data_is_computed_once(
    world: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = hp.load_flow_data

    def counted(project: Project) -> hp.FlowData:
        calls.append(1)
        return real(project)

    monkeypatch.setattr(hp, "load_flow_data", counted)
    hb.build_static(world, tmp_path / "ui")
    assert len(calls) == 1


def test_failing_flow_data_is_computed_once_and_reported(
    world: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def boom(project: Project) -> hp.FlowData:
        calls.append(1)
        raise ValueError("ledger broke")

    monkeypatch.setattr(hp, "load_flow_data", boom)
    report = hb.build_static(world, tmp_path / "ui")
    assert len(calls) == 1
    assert {"shell", "overview", "flow"} <= set(report.errors)
    assert "ledger broke" in report.errors["flow"]
    assert (tmp_path / "ui/data/living.json").is_file()
    assert not (tmp_path / "ui/data/flow.json").exists()


def test_a_failing_builder_does_not_stop_the_others(
    world: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(ctx: hb.HubContext) -> dict[str, object]:
        raise RuntimeError("lenses exploded")

    monkeypatch.setitem(hb.BUILDERS, "lenses", boom)
    report = hb.build_static(world, tmp_path / "ui")
    assert list(report.errors) == ["lenses"]
    assert "lenses exploded" in report.errors["lenses"]
    assert not (tmp_path / "ui/data/lenses.json").exists()
    for name in CORE - {"lenses"}:
        assert (tmp_path / "ui/data" / f"{name}.json").is_file()


def test_only_is_honoured_and_unknown_names_refused(world: Project, tmp_path: Path) -> None:
    report = hb.build_static(world, tmp_path / "ui", only={"living"})
    assert set(report.payloads) == {"living"}
    assert sorted(p.name for p in (tmp_path / "ui/data").iterdir()) == ["living.js", "living.json"]
    assert not (tmp_path / "ui/overview.html").exists()
    with pytest.raises(ValueError, match="nope"):
        hb.build_static(world, tmp_path / "x", only={"nope"})


def test_pages_use_registered_assets_and_no_external_url(world: Project, tmp_path: Path) -> None:
    hb.build_static(world, tmp_path / "ui")
    pages = sorted((tmp_path / "ui").glob("*.html"))
    assert pages
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"https?://|//cdn", text), page.name
        refs = re.findall(r'(?:src|href)="([^"]+)"', text)
        assert refs
        for ref in refs:
            path = ref.split("?")[0]
            if path.startswith("assets/"):
                assert path[len("assets/") :] in hub_ui.ASSETS, (page.name, ref)
            else:
                assert re.fullmatch(r"data/[a-z_]+\.js", path), (page.name, ref)
                assert (tmp_path / "ui" / path).is_file()
        assert f"v={hub_ui.asset_version()}" in text


def test_page_html_in_server_mode_loads_by_fetch() -> None:
    html = hub_ui.page_html(
        "overview", "Overview", ["pages/overview.js"], ["shell"], "abc", static_data=False
    )
    assert "data/shell.js" not in html and 'src="assets/pages/overview.js?v=abc"' in html


def test_cli_hub_build_smoke(world: Project, settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "ui"
    result = CliRunner().invoke(
        app,
        ["hub", "build", world.paths.slug, "--out", str(out), "--only", "shell,overview"],
        env=_env(settings.root),
    )
    assert result.exit_code == 0, result.output
    assert "overview" in result.output
    assert (out / "data/overview.json").is_file()
    assert not (out / "data/flow.json").exists()
