"""The `pipeline` hub payload (Control room, Work queue, Activity): shape, guards, tallies."""

from __future__ import annotations

import json
from typing import Any

import pytest

from factory.services import hub_build as hb
from factory.services import hub_pipeline as hpl
from factory.services import pipeline as pipeline_service
from factory.services import resume as resume_service
from factory.services import work_queue as work_queue_service
from factory.services.context import Project
from tests.test_hub_build import mined_world, world  # noqa: F401  (fixtures)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)

SECTIONS = (
    "status",
    "stations",
    "next_actions",
    "heartbeat",
    "queue",
    "runs",
    "interrupted",
    "activity",
    "screening_live",
)


def payload(project: Project) -> dict[str, Any]:
    return hpl.build(hb.HubContext(project))


def item(entry: str, stage: str = "added", stopped: bool = False) -> work_queue_service.QueueItem:
    return work_queue_service.QueueItem(
        entry_id=entry,
        title=f"t-{entry}",
        inbox_item_id=f"i-{entry}",
        sent_at="2026-11-01T00:00:00Z",
        work_id=None,
        stage=stage,  # type: ignore[arg-type]
        stopped=stopped,
        detail="",
    )


def test_pct_is_a_whole_percent_or_none() -> None:
    assert hpl._pct(1, 3) == 33
    assert hpl._pct(None, 3) is None
    assert hpl._pct(2, 0) is None
    assert hpl._pct(2, None) is None


def test_payload_has_every_section_and_a_method_for_each_panel(world: Project) -> None:  # noqa: F811
    out = payload(world)
    assert out["ready"] is True and out["slug"] == world.paths.slug
    for key in SECTIONS:
        assert key in out
        assert not (isinstance(out[key], dict) and "error" in out[key]), (key, out[key])
    for key in (
        "stations",
        "status",
        "heartbeat",
        "queue",
        "grid",
        "pending",
        "process",
        "interrupted",
        "runs",
        "held",
        "passes",
        "operations",
        "traces",
        "screening",
    ):
        assert out["methods"][key].startswith("<b>")
    json.dumps(out)  # the payload is plain JSON


def test_stations_are_the_seven_of_the_line_and_read_the_prisma_counts(world: Project) -> None:  # noqa: F811
    ctx = hb.HubContext(world)
    rows = hpl.stations(ctx)
    assert [r["key"] for r in rows] == [
        "search",
        "screen",
        "fulltext",
        "convert",
        "mine",
        "synthesize",
        "report",
    ]
    prisma = ctx.flow_data.prisma
    assert rows[0]["n"] == sum(prisma.identified_databases.values()) + sum(
        prisma.identified_other.values()
    )
    assert rows[1]["n"] == prisma.screened and rows[1]["of"] == rows[0]["n"]
    assert rows[1]["pct"] == hpl._pct(rows[1]["n"], rows[1]["of"])
    assert all(r["page"] and r["sub"] for r in rows)


def test_status_counts_the_events_of_the_log(world: Project) -> None:  # noqa: F811
    got = hpl.status(hb.HubContext(world))
    world.index.sync()
    with world.index.connect() as conn:
        total = conn.exec_driver_sql("SELECT COUNT(*) FROM events").scalar()
    assert got["events_total"] == total
    assert got["last_event_id"] == world.index.last_event_id()


def test_heartbeat_is_oldest_first_and_sums_to_the_log(world: Project) -> None:  # noqa: F811
    days = hpl.heartbeat(world, days=1000)
    assert [d for d, _ in days] == sorted(d for d, _ in days)
    assert sum(n for _, n in days) == hpl.status(hb.HubContext(world))["events_total"]


def test_queue_tallies_cells_per_stage(
    world: Project,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [item("a"), item("b", stopped=True), item("c")]
    monkeypatch.setattr(
        work_queue_service,
        "queue",
        lambda project: work_queue_service.WorkQueue(items=items, pending={"screen": 2}),
    )
    monkeypatch.setattr(
        pipeline_service,
        "paper_progress",
        lambda project, its, plan: {
            "a": {"screen": "done"},
            "b": {"screen": "stopped"},
        },
    )
    plan = [
        pipeline_service.PipelineStage(
            key="screen",
            label="Screening",
            skill="s",
            role="r",
            model="m",
            tools=(),
            pending=2,
            applies=True,
            reason="",
        ),
        pipeline_service.PipelineStage(
            key="intuition",
            label="Intuition",
            skill="s",
            role="r",
            model="m",
            tools=(),
            pending=0,
            applies=True,
            reason="",
        ),
        pipeline_service.PipelineStage(
            key="appraise",
            label="Appraisal",
            skill="s",
            role="r",
            model="m",
            tools=(),
            pending=0,
            applies=False,
            reason="no",
        ),
    ]
    got = hpl.queue_section(world, plan)
    assert got["columns"] == [{"key": "screen", "label": "Screening"}]  # no intuition, no n/a stage
    assert got["stage_counts"]["screen"] == {"done": 1, "pending": 0, "n/a": 1, "stopped": 1}
    assert got["stopped"] == 1 and got["pending"] == {"screen": 2}
    assert len(got["items"]) == 3


def test_a_failing_section_is_an_error_entry_and_the_others_stay(
    world: Project,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(project: Project) -> None:
        raise ValueError("cannot read")

    monkeypatch.setattr(resume_service, "interrupted", boom)
    out = payload(world)
    assert out["interrupted"] == {"error": "ValueError: cannot read"}
    assert "error" not in out["queue"] and out["stations"]


def test_interrupted_section_carries_the_panel_lines_and_is_clean_flag(
    world: Project,  # noqa: F811
) -> None:
    got = hpl.interrupted_section(world)
    assert isinstance(got["is_clean"], bool) and got["lines"]
    if got["is_clean"]:
        assert got["lines"] == ["Nothing is interrupted."]


@pytest.mark.parametrize(("status", "expected"), [("running", True), ("done", False)])
def test_runs_section_pipeline_open_follows_a_running_pipeline(
    world: Project,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: bool,
) -> None:
    class Pipe:
        def __init__(self, status: str) -> None:
            self.status = status

        def model_dump(self, mode: str = "python") -> dict[str, Any]:
            return {"status": self.status}

    monkeypatch.setattr(
        pipeline_service,
        "pipeline_status",
        lambda project, limit=None: [Pipe("done"), Pipe(status)],
    )
    assert hpl.runs_section(world)["pipeline_open"] is expected
    monkeypatch.setattr(pipeline_service, "pipeline_status", lambda project, limit=None: [])
    assert hpl.runs_section(world)["pipeline_open"] is False


def test_activity_section_states_its_constants(world: Project) -> None:  # noqa: F811
    got = hpl.activity_section(world)
    assert got["stale_minutes"] == 10
    assert {"active", "passes", "dormant", "operations", "traces", "now"} <= set(got)


def test_unit_cap_bounds_are_the_runners(world: Project) -> None:  # noqa: F811
    from factory.services import runner

    cap = payload(world)["unit_cap"]
    assert cap == {"default": runner.DEFAULT_UNIT_CAP, "max": runner.MAX_UNIT_CAP}


def test_page_cards_lead_with_the_pipeline_and_skip_the_kit() -> None:
    ids = [c["id"] for c in hpl.page_cards()]
    assert "pipeline" in ids and "kit" not in ids
    assert "learn" in ids  # a blurb for the Start here page
    assert all(c["blurb"] for c in hpl.page_cards())


def test_payload_is_deterministic(world: Project) -> None:  # noqa: F811
    assert json.dumps(payload(world), sort_keys=True) == json.dumps(payload(world), sort_keys=True)


def test_stations_show_the_pending_units_under_the_station_that_runs_them(
    world: Project,  # noqa: F811
) -> None:
    rows = hpl.stations(
        hb.HubContext(world), {"screen": 4, "extract": 2, "mine:m-x": 3, "appraise": 9}
    )
    by = {r["key"]: r for r in rows}
    assert by["screen"]["pending"] == 4 and by["mine"]["pending"] == 5
    assert by["search"]["pending"] is None
    assert hpl.stations(hb.HubContext(world))[1]["pending"] is None
