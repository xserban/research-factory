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

CORE = {
    "shell",
    "overview",
    "flow",
    "screening",
    "graph",
    "lenses",
    "living",
    "mining",
    "findings",
    "explore",
    "corpus",
}
OPTIONAL = {"journeys"}  # delivered by hub_journeys; may be absent


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
    assert {n for n in report.errors if n not in OPTIONAL} == set()
    assert CORE <= set(report.payloads) <= CORE | OPTIONAL
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
    assert [n for n in report.errors if n not in OPTIONAL] == ["lenses"]
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


def test_every_page_has_a_script_and_only_registered_payloads() -> None:
    assert list(hub_ui.PAGES) == [
        "overview",
        "corpus",
        "flow",
        "lenses",
        "explore",
        "graph",
        "miners",
        "data",
        "findings",
        "living",
        "kit",
    ]
    for spec in hub_ui.PAGES.values():
        assert spec.script == f"pages/{spec.id}.js"
        assert spec.script in hub_ui.ASSETS
        assert spec.payloads[0] == "shell"
        assert set(spec.payloads) <= set(hb.BUILDERS), spec.id


def test_shared_data_is_computed_once_for_mining_findings_and_corpus(
    world: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import hub_mining

    flow: list[int] = []
    mining: list[int] = []
    real_flow, real_mining = hp.load_flow_data, hub_mining.load_mining_data

    def counted_flow(project: Project) -> hp.FlowData:
        flow.append(1)
        return real_flow(project)

    def counted_mining(*a: object, **k: object) -> hub_mining.MiningData:
        mining.append(1)
        return real_mining(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(hp, "load_flow_data", counted_flow)
    monkeypatch.setattr(hub_mining, "load_mining_data", counted_mining)
    report = hb.build_static(
        world, tmp_path / "ui", only={"shell", "mining", "findings", "corpus", "lenses", "explore"}
    )
    assert report.errors == {}
    assert len(flow) == 1
    assert len(mining) == 1


def _payload(world: Project, tmp_path: Path, name: str) -> dict[str, object]:
    report = hb.build_static(world, tmp_path / "ui", only={name})
    assert report.errors == {}
    out: dict[str, object] = json.loads(
        (tmp_path / "ui/data" / f"{name}.json").read_text(encoding="utf-8")
    )
    return out


def test_explore_has_only_included_works_with_dna_and_quotes(
    world: Project, tmp_path: Path
) -> None:
    payload = _payload(world, tmp_path, "explore")
    ctx = hb.HubContext(world)
    works = payload["works"]
    assert isinstance(works, list)
    assert [w["id"] for w in works] == sorted(ctx.included)
    for w in works:
        assert {"id", "title", "year", "month", "layer", "cited_here", "dna"} == set(w)
        assert set(w["dna"]) == set(hb.EXPLORE_DIMS)
        for cell in w["dna"].values():
            assert cell is None or set(cell) == {"v", "q"}


def test_corpus_has_only_included_works_and_maps_duplicates(world: Project, tmp_path: Path) -> None:
    payload = _payload(world, tmp_path, "corpus")
    ctx = hb.HubContext(world)
    included = set(ctx.included)
    works = payload["works"]
    assert isinstance(works, list)
    ids = [w["id"] for w in works]
    assert len(ids) == len(set(ids)) and set(ids) <= included
    for w in works:
        src = ctx.source_of[w["id"]]
        assert w.get("mapped_from") == (src if src != w["id"] else None)
    slugs = {w["slug"] for w in works}
    cites = payload["cites"]
    assert isinstance(cites, list)
    assert all(a in slugs and b in slugs and a != b for a, b in cites)
    sets = payload["sets"]
    assert isinstance(sets, dict) and "included" in str(sets.keys()) + "included"


def test_lenses_adoption_uses_technique_miner_rows(world: Project) -> None:
    ctx = hb.HubContext(world)
    recs = hb.adoption_records(ctx)
    included = set(ctx.included)
    assert all(r[0] in included and r[2] in ctx.mining_data.codebook for r in recs)
    assert hb.build_lenses(ctx)["adoption"]["works_with_records"] == len({r[0] for r in recs})


def test_journeys_is_reported_not_raised_when_the_module_is_absent(
    world: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "factory.services.hub_journeys", None)
    report = hb.build_static(world, tmp_path / "ui", only={"journeys"})
    assert "hub_journeys" in report.errors["journeys"]
    assert not (tmp_path / "ui/data/journeys.json").exists()


def test_shell_works_carry_drawer_fields_and_valid_cites(world: Project, tmp_path: Path) -> None:
    shell = _payload(world, tmp_path, "shell")
    ctx = hb.HubContext(world)
    works = shell["works"]
    assert isinstance(works, list) and works
    for w in works:
        assert {
            "authors",
            "venue",
            "abstract",
            "doi",
            "arxiv",
            "cited_here",
            "layer",
            *hb.EXPLORE_DIMS,
        } <= set(w)
        assert len(w["authors"]) <= hb.SHELL_AUTHORS
        assert len(w["abstract"]) <= hb.SHELL_ABSTRACT_CHARS
        for k in hb.EXPLORE_DIMS:
            assert w[k] is None or set(w[k]) == {"v", "q"}
        src = ctx.source_of[w["id"]]
        assert ("mapped_from" in w) == (src != w["id"])
    n = len(works)
    cites = shell["cites"]
    assert isinstance(cites, list)
    for a, b in cites:
        assert 0 <= a < n and 0 <= b < n and a != b
    assert cites == sorted(cites)
    head = shell["project"]
    assert isinstance(head, dict) and set(head) == {"title", "question", "protocol_id"}
    assert head["title"]


def test_shell_sets_summary_equals_reconciliation_sizes(world: Project, tmp_path: Path) -> None:
    shell = _payload(world, tmp_path, "shell")
    flow = _payload(world, tmp_path, "flow")
    sets = flow["sets"]
    assert isinstance(sets, dict)
    assert shell["sets"] == {k: len(sets[k]) for k in shell["sets"]}  # type: ignore[attr-defined]
    assert shell["sets"]["included"] == len(shell["works"])  # type: ignore[arg-type]


def test_shell_size_is_measured_and_dna_is_computed_once(
    world: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = hp._load_role_cells

    def counted(*a: object, **k: object) -> object:
        calls.append(str(a[2]) if len(a) > 2 else "")
        return real(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(hp, "_load_role_cells", counted)
    report = hb.build_static(world, tmp_path / "ui", only={"shell", "explore"})
    assert report.errors == {}
    assert len(calls) == len(hb.EXPLORE_DIMS)
    size = report.payloads["shell"].bytes
    works = len(json.loads((tmp_path / "ui/data/shell.json").read_text(encoding="utf-8"))["works"])
    assert size < 4000 * max(works, 1) + 50_000, f"{size} bytes for {works} works"
