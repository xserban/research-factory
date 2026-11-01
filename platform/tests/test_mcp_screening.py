"""The screening, calibration and agreement MCP tools: refusals, partial success, scrub (R-20).

Each MCP server is one session, so a screener's calls share one server and client, as a Claude
Code session does. Screening tools withhold held-out seed identifiers but not held-out work ids.
"""

import json
import re
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import read_all
from factory.model.screening import Channel
from factory.services.calibration import calibration_items, calibration_labels, label_calibration
from factory.services.context import Project
from factory.services.seeds import SeedRole, all_seeds
from tests.helpers import _leaks, _of_type, _setup, open_session
from tests.test_screening_next import _draw

AGENT = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


def _include(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_id": record["work_id"],
        "verdict": "include",
        "criterion": None,
        "quote": record["title"],
        "rationale": "fits",
    }


@pytest.mark.anyio
async def test_held_out_seed_is_screened_without_being_named(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    for item in _draw(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    held = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held, "the fixture must hold out a positive seed"

    seen: list[dict[str, Any]] = []
    transcript: list[Any] = []
    async with open_session(settings, clock) as screener:
        while True:
            body = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
            transcript.append(body)
            assert body["ok"] is True, body
            batch = body["data"]["batch"]
            if batch is None:
                break
            seen.extend(batch["records"])
            items = [_include(record) for record in batch["records"]]
            written = await screener.call(
                "screen_record", project="demo", task_id=batch["task_id"], items=items, **AGENT
            )
            transcript.append(written)
            assert written["ok"] is True and written["data"]["rejected"] == []

    held_works = {s.work_id for s in held}
    assert held_works <= {record["work_id"] for record in seen}
    tokens = {t for s in held for t in (s.seed_id, s.doi, s.arxiv, s.openalex) if t}
    assert _leaks(json.dumps(transcript), tokens) == []


@pytest.mark.anyio
async def test_screen_tools_require_model_and_skill(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as screener:
        unknown = await screener.call(
            "screen_next",
            project="demo",
            pass_label="A",
            role="screener-a",
            model="claude-sonnet-5-5",
            skill="no-such-skill",
        )
        assert _fields(unknown) == ["skill"]
        no_model = await screener.call(
            "screen_next",
            project="demo",
            pass_label="A",
            role="screener-a",
            model="",
            skill="rf-screen",
        )
        assert _fields(no_model) == ["model"]
        bad_label = await screener.call("screen_next", project="demo", pass_label="C", **AGENT)
        assert _fields(bad_label) == ["pass_label"]
    assert _of_type(project, "screening.pass_opened") == []


@pytest.mark.anyio
async def test_screen_record_partial_success_over_mcp(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    for item in _draw(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    async with open_session(settings, clock) as screener:
        batch = (await screener.call("screen_next", project="demo", pass_label="A", **AGENT))[
            "data"
        ]["batch"]
        records = batch["records"]
        assert len(records) >= 3
        items = [
            _include(records[0]),
            {**_include(records[1]), "quote": "a span that is not in this record"},
            {
                "work_id": records[2]["work_id"],
                "verdict": "exclude",
                "criterion": None,
                "quote": records[2]["title"],
                "rationale": "off topic",
            },
        ]
        body = await screener.call(
            "screen_record", project="demo", task_id=batch["task_id"], items=items, **AGENT
        )
    assert body["ok"] is True
    data = body["data"]
    assert len(data["written"]) == 1
    rejected = {r["index"]: [i["field"] for i in r["issues"]] for r in data["rejected"]}
    assert rejected == {1: ["items.1.quote"], 2: ["items.2"]}


@pytest.mark.anyio
async def test_calibration_label_flow_over_mcp(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as reviewer:
        first = await reviewer.call("calibration_label", project="demo")
        assert first["ok"] is True
        assert first["data"]["labelled"] == 0
        assert first["data"]["drawn"] == len(calibration_items(project)) > 0
        record = first["data"]["record"]
        assert {"work_id", "title", "abstract"} <= set(record)

        written = await reviewer.call(
            "calibration_label", project="demo", work_id=record["work_id"], verdict="include"
        )
        assert written["ok"] is True and isinstance(written["data"]["event_id"], str)

        other = calibration_items(project)[1]
        assert _fields(await reviewer.call("calibration_label", project="demo", work_id=other)) == [
            "verdict"
        ]
        assert _fields(
            await reviewer.call("calibration_label", project="demo", work_id=other, verdict="maybe")
        ) == ["verdict"]
        assert _fields(
            await reviewer.call(
                "calibration_label",
                project="demo",
                work_id=other,
                verdict="exclude",
                criterion="EX09",
            )
        ) == ["criterion"]
        assert _fields(
            await reviewer.call(
                "calibration_label", project="demo", work_id="W-not-drawn", verdict="include"
            )
        ) == ["work_id"]

        labelled = await reviewer.call(
            "calibration_label",
            project="demo",
            work_id=other,
            verdict="exclude",
            criterion="EX01",
        )
        assert labelled["ok"] is True
        counted = await reviewer.call("calibration_label", project="demo")
        assert counted["data"]["labelled"] == 2

    assert calibration_labels(project)[record["work_id"]] == "include"
    [event] = [
        e
        for e in _of_type(project, "calibration.labelled")
        if e.payload["work_id"] == record["work_id"]
    ]
    assert event.payload["channel"] == "mcp" and event.actor.kind == "human"


@pytest.mark.anyio
async def test_agreement_over_mcp_is_refused_until_passes_finish(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as reviewer:
        body = await reviewer.call("screen_agreement", project="demo")
    assert _fields(body) == ["passes"]


@pytest.mark.anyio
async def test_held_out_work_ids_stay_visible_to_screeners(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    """The narrower scrub: a held-out work's id is what the screener records against."""
    _setup(project, agent, human, mock_sources)
    for item in _draw(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    held_works = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT}
    seen: set[str] = set()
    async with open_session(settings, clock) as screener:
        while True:
            batch = (await screener.call("screen_next", project="demo", pass_label="A", **AGENT))[
                "data"
            ]["batch"]
            if batch is None:
                break
            seen.update(record["work_id"] for record in batch["records"])
            await screener.call(
                "screen_record",
                project="demo",
                task_id=batch["task_id"],
                items=[_include(r) for r in batch["records"]],
                **AGENT,
            )
    assert held_works <= seen
    assert held_works and all(held_works), "held-out work ids must be non-empty strings"
    assert [e.type for e in read_all(project.paths.events_dir, project.catalog)].count(
        "screening.decision_recorded"
    ) == len(seen)


@pytest.mark.anyio
async def test_malformed_calibration_call_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    """A refused calibration_label call writes nothing, even before the set is first drawn."""
    _setup(project, agent, human, mock_sources)
    before = len(read_all(project.paths.events_dir, project.catalog))
    malformed = [
        {"verdict": "include"},
        {"criterion": "EX01"},
        {"work_id": "W-x"},
        {"work_id": "W-x", "verdict": "maybe"},
        {"work_id": "W-x", "verdict": "exclude"},
    ]
    async with open_session(settings, clock) as reviewer:
        for args in malformed:
            body = await reviewer.call("calibration_label", project="demo", **args)
            assert body["ok"] is False, (args, body)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    assert _of_type(project, "calibration.drawn") == []


@pytest.mark.anyio
async def test_labelled_call_never_draws_the_set(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    """A labelled call on an undrawn set is refused and writes nothing; the set is drawn only by
    the no-argument call."""
    _setup(project, agent, human, mock_sources)
    before = len(read_all(project.paths.events_dir, project.catalog))
    async with open_session(settings, clock) as reviewer:
        body = await reviewer.call(
            "calibration_label", project="demo", work_id="W-x", verdict="include"
        )
    assert _fields(body) == ["work_id"]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    assert _of_type(project, "calibration.drawn") == []


@pytest.mark.anyio
async def test_labelled_call_with_unknown_criterion_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as reviewer:
        first = await reviewer.call("calibration_label", project="demo")
        work_id = first["data"]["record"]["work_id"]
        before = len(read_all(project.paths.events_dir, project.catalog))
        body = await reviewer.call(
            "calibration_label",
            project="demo",
            work_id=work_id,
            verdict="exclude",
            criterion="EX09",
        )
    assert _fields(body) == ["criterion"]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    assert _of_type(project, "calibration.labelled") == []


def _exclude(record: dict[str, Any]) -> dict[str, Any]:
    return {**_include(record), "verdict": "exclude", "criterion": "EX01"}


@pytest.mark.anyio
async def test_pass_session_sees_no_label_derived_rate(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    """A screener's status and blocked reasons carry calibration counts and a passed flag, never a
    sensitivity, a specificity, a threshold or a false-exclusion rate."""
    _setup(project, agent, human, mock_sources)
    for item in _draw(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    async with open_session(settings, clock) as screener:
        while True:
            body = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
            batch = body["data"]["batch"]
            if batch is None:
                break
            items = [_exclude(record) for record in batch["records"]]
            await screener.call(
                "screen_record", project="demo", task_id=batch["task_id"], items=items, **AGENT
            )
        blocked = body["data"]["blocked"]
        status = await screener.call("project_status", project="demo")

    assert blocked, "the gate must be closed: every positive was excluded"
    assert not re.search(r"\d\.\d", json.dumps(blocked)), blocked
    calibration = status["data"]["screening"]["calibration"]
    assert set(calibration) == {"drawn", "labelled", "required", "passed"}
    assert calibration["passed"] == {"A": False, "B": False}
    assert not re.search(r"sensitiv|specific|threshold|false_exclusion", json.dumps(status))


@pytest.mark.anyio
async def test_pass_session_cannot_read_agreement_or_draw_an_audit(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    async with open_session(settings, clock) as screener:
        await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        before = len(read_all(project.paths.events_dir, project.catalog))
        agreement = await screener.call("screen_agreement", project="demo")
        sample = await screener.call("audit_sample", project="demo")
    assert _fields(agreement) == ["session"]
    assert _fields(sample) == ["session"]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    assert _of_type(project, "audit.sampled") == []


@pytest.mark.anyio
async def test_pass_session_cannot_draw_the_calibration_set_or_read_a_record(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    async with open_session(settings, clock) as screener:
        await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        body = await screener.call("calibration_label", project="demo")
    assert _fields(body) == ["session"]


@pytest.mark.anyio
async def test_session_that_labelled_over_mcp_cannot_screen(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    async with open_session(settings, clock) as reviewer:
        first = await reviewer.call("calibration_label", project="demo")
        labelled = await reviewer.call(
            "calibration_label",
            project="demo",
            work_id=first["data"]["record"]["work_id"],
            verdict="include",
        )
        assert labelled["ok"] is True
        refused = await reviewer.call("screen_next", project="demo", pass_label="A", **AGENT)
    assert _fields(refused) == ["session"]
    assert _of_type(project, "screening.pass_joined") == []
