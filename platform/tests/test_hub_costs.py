"""Hub costs payload (page "Costs & runs"): run-cost grouping, budgets, ops files."""

from __future__ import annotations

from typing import Any

from factory.services import hub_build as hb
from factory.services import hub_costs as hc
from factory.services.context import Project
from factory.services.run_costs import RunCost
from tests.test_hub_build import world  # noqa: F401  (fixture)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)


def run(run_id: str, stage: str, model: str, started: str, cost: float | None) -> RunCost:
    return RunCost(
        run_id=run_id,
        stage=stage,
        model=model,
        miner=None,
        started_at=started,
        outcome="ok",
        exit_status=0,
        units=2,
        units_source="mcp-counter",
        cost_usd=cost,
        cost_source=None if cost is None else "reported-by-cli",
        cost_per_unit_usd=None if cost is None else cost / 2,
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=1,
        cache_write_tokens=1,
        tokens_per_unit=2.0,
        turns=3,
        duration_ms=1000,
        complete=cost is not None,
        malformed_lines=0,
        log_source="none",
    )


def test_over_time_sums_per_day_and_aligns_series() -> None:
    rows = [
        run("run_aaaaaaaa", "screen", "m1", "2026-11-01T10:00:00Z", 1.5),
        run("run_bbbbbbbb", "screen", "m1", "2026-11-01T11:00:00Z", 0.5),
        run("run_cccccccc", "mine:x", "m2", "2026-11-03T00:00:00Z", 4.0),
        run("run_dddddddd", "mine:x", "m2", "2026-11-04T00:00:00Z", None),
    ]
    out = hc.over_time(rows)
    assert out["days"] == ["2026-11-01", "2026-11-03"]
    assert out["by_stage"] == {"mine:x": [0.0, 4.0], "screen": [2.0, 0.0]}
    assert out["by_model"] == {"m1": [2.0, 0.0], "m2": [0.0, 4.0]}
    assert all(len(v) == len(out["days"]) for v in out["by_stage"].values())


def test_over_time_is_empty_without_priced_runs() -> None:
    assert hc.over_time([]) == {"days": [], "by_stage": {}, "by_model": {}}


def test_build_on_a_project_without_runs(world: Project) -> None:  # noqa: F811
    data: dict[str, Any] = hc.build(hb.HubContext(world))
    assert data["ready"] is True
    assert set(hc.METHODS) <= set(data["methods"])
    assert data["groups"] == [] and data["runs"] == [] and data["growth"] == {}
    assert data["summary"]["runs"] == 0 and data["summary"]["cost"] is None
    assert data["summary"]["caveat"]
    assert data["budgets"]["lines"] == [] or all("share" in ln for ln in data["budgets"]["lines"])
    assert data["ops"] == {"groups": [], "files": 0, "unlinked": 0, "file_cap": hc.FILE_CAP}
    assert all({"model", "events"} <= set(m) for m in data["events_per_model"])


def test_ops_files_are_grouped_and_unlinked_first(world: Project) -> None:  # noqa: F811
    ops = world.paths.dir / "ops"
    (ops / "batch").mkdir(parents=True)
    (ops / "layerA-1.txt").write_text("a", encoding="utf-8")
    (ops / "layerA-2.txt").write_text("bb", encoding="utf-8")
    (ops / "batch" / "mineD_x.log").write_text("c", encoding="utf-8")
    data = hc.build(hb.HubContext(world))["ops"]
    assert data["files"] == 3
    assert data["unlinked"] == len(data["groups"]) == 2
    by = {(g["folder"], g["prefix"]): g for g in data["groups"]}
    assert by[(".", "layerA")]["files"] == 2 and by[(".", "layerA")]["size"] == 3
    assert [f["path"] for f in by[(".", "layerA")]["listed"]] == ["layerA-1.txt", "layerA-2.txt"]
    assert by[("batch", "mineD")]["linked"] is False and by[("batch", "mineD")]["run_ids"] == []


def test_ops_listing_is_capped_but_counts_are_exact(world: Project) -> None:  # noqa: F811
    ops = world.paths.dir / "ops"
    ops.mkdir()
    for i in range(hc.FILE_CAP + 3):
        (ops / f"big-{i:04d}.txt").write_text("x", encoding="utf-8")
    group = hc.build(hb.HubContext(world))["ops"]["groups"][0]
    assert group["files"] == hc.FILE_CAP + 3 and len(group["listed"]) == hc.FILE_CAP
