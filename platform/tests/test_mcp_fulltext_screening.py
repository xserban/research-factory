"""The screening MCP tools at the full-text stage (plan 2C, task 8; rulings 4-6)."""

from collections.abc import Callable, Mapping

import pytest
from mcp import Client
from pydantic import JsonValue

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.calibration import draw_calibration
from factory.services.context import Project
from factory.services.screening import live_decisions
from factory.sources.registry import SourceFactory
from tests.document_helpers import promoted_works
from tests.helpers import SESSION, _setup, open_session
from tests.test_fulltext_eligibility import _convert, _world

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
AGENT = {"role": "screener-a", "model": "claude-opus-5-5", "skill": "rf-screen"}


class _FixedIds:
    def __init__(self, _clock: object) -> None: ...

    def ulid(self) -> str:
        return SESSION


def _make(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> None:
    """Full-text screening declared, works promoted and converted, the full-text calibration set
    drawn. Nothing is claimed: the MCP session below is the first screener."""
    _world(project, agent, human, mock_sources, dual_sample=0.5)
    _convert(project, promoted_works(project))
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


@pytest.mark.anyio
async def test_full_text_screen_next_serves_a_pinned_batch(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make(project, agent, human, mock_sources)
    monkeypatch.setattr(mcp_server, "IdGenerator", _FixedIds)
    async with open_session(settings, clock) as client:
        served = await client.call(
            "screen_next", project="demo", pass_label="A", stage="full-text", **AGENT
        )
        assert served["ok"] is True, served
        batch = served["data"]["batch"]
        assert batch["stage"] == "full-text"
        assert all(r["conversion_id"] and r["document_id"] for r in batch["records"])

        items = [
            {
                "work_id": r["work_id"],
                "verdict": "include",
                "criterion": None,
                "quote": "Lorem ipsum dolor sit amet.",
                "rationale": "fits",
                "anchor": "s3.p1",
            }
            for r in batch["records"]
        ]
        recorded = await client.call(
            "screen_record", project="demo", task_id=batch["task_id"], items=items, **AGENT
        )
        assert recorded["ok"] is True, recorded
        assert len(recorded["data"]["written"]) == len(items)
        assert recorded["data"]["rejected"] == []

    decisions = live_decisions(project, PassLabel.A, stage=FT)
    assert {d.work_id for d in decisions} >= {str(r["work_id"]) for r in batch["records"]}
    assert all(d.anchor == "s3.p1" for d in decisions)


@pytest.mark.anyio
async def test_screen_record_reports_a_bad_anchor_by_index(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make(project, agent, human, mock_sources)
    monkeypatch.setattr(mcp_server, "IdGenerator", _FixedIds)
    async with open_session(settings, clock) as client:
        served = await client.call(
            "screen_next", project="demo", pass_label="A", stage="full-text", **AGENT
        )
        batch = served["data"]["batch"]
        work = str(batch["records"][0]["work_id"])
        body = await client.call(
            "screen_record",
            project="demo",
            task_id=batch["task_id"],
            items=[
                {
                    "work_id": work,
                    "verdict": "include",
                    "quote": "Lorem ipsum dolor sit amet.",
                    "rationale": "fits",
                    "anchor": "s1.p1",
                }
            ],
            **AGENT,
        )
    assert body["ok"] is True
    assert [e["issues"][0]["field"] for e in body["data"]["rejected"]] == ["items.0.quote"]


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["either", "bogus", "full_text", ""])
async def test_unknown_stage_is_a_structured_error_and_writes_nothing(
    stage: str,
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make(project, agent, human, mock_sources)
    monkeypatch.setattr(mcp_server, "IdGenerator", _FixedIds)
    before = _count(project)
    calls: list[tuple[str, dict[str, JsonValue]]] = [
        ("screen_next", {"pass_label": "A", **AGENT}),
        ("screen_agreement", {}),
        ("audit_sample", {}),
        ("calibration_label", {}),
    ]
    async with open_session(settings, clock) as client:
        for name, args in calls:
            body = await client.call(name, project="demo", stage=stage, **args)
            assert body["ok"] is False, (name, body)
            assert [e["field"] for e in body["errors"]] == ["stage"], (name, body)
    assert _count(project) == before


TOOLS = [
    "project_status", "search_run", "search_chase", "dedup_run", "question_record", "seed_add",
    "seed_list", "probe_run", "protocol_record", "protocol_press_review", "protocol_amend",
    "screen_next", "screen_record", "screen_agreement", "calibration_label", "audit_sample",
    "audit_record", "protocol_deviation", "report_prisma", "report_methods", "trace", "check",
    "fulltext_fetch", "fulltext_status", "document_read",
]  # fmt: skip


@pytest.mark.anyio
async def test_tool_list_is_unchanged(settings: Settings, clock: FixedClock) -> None:
    """The full-text stage adds arguments, not tools."""
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert names == TOOLS


@pytest.mark.anyio
async def test_calibration_record_shows_full_text_evidence(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _make(project, agent, human, mock_sources)
    async with open_session(settings, clock) as client:
        ft = await client.call("calibration_label", project="demo", stage="full-text")
    record = ft["data"]["record"]
    assert set(record) == {
        "work_id",
        "title",
        "abstract",
        "document_id",
        "conversion_id",
        "decisions",
    }
    assert record["conversion_id"].startswith("cnv_") and record["document_id"].startswith("doc_")
    assert record["decisions"] == {}


def test_title_abstract_decision_views_carry_no_evidence(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from factory.services.evidence import work_evidence

    _make(project, agent, human, mock_sources)
    work = promoted_works(project)[0]
    assert work_evidence(project, work, ScreeningStage.TITLE_ABSTRACT).conversion_id is None
    assert work_evidence(project, work, FT).conversion_id is not None


@pytest.mark.anyio
async def test_title_abstract_calibration_record_is_unchanged(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as client:
        body = await client.call("calibration_label", project="demo")
    assert set(body["data"]["record"]) == {"work_id", "title", "abstract"}
