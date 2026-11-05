"""The miner MCP tools: parse, call a service, reply; nothing else (M-C, task 7)."""

# ruff: noqa: F811
import json

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mining.spec import spec_to_json
from factory.services.context import Project
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import install_skill, open_session
from tests.miner_helpers import (
    SESSION_M1,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_row,
    vision_result,
)

AGENT = {"role": "miner", "model": "claude-opus-5-5", "skill": "rf-extract"}


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


@pytest.mark.anyio
async def test_register_list_and_a_full_record_through_the_tools(
    settings: Settings,
    project: Project,
    agent: Actor,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    _session(monkeypatch, SESSION_M1)
    async with open_session(settings, clock) as client:
        listed = await client.call("miner_list", project="demo")
        assert listed["ok"] is True and listed["data"]["miners"] == []
        spec = spec_to_json(method_vision())
        registered = await client.call("miner_register", project="demo", spec=spec, **AGENT)
        assert registered["ok"] is True, registered
        assert registered["data"]["name"] == VISION_NAME
        again = await client.call("miner_register", project="demo", spec=spec, **AGENT)
        assert again["data"]["miner_id"] == registered["data"]["miner_id"]
        listed = await client.call("miner_list", project="demo")
        assert [(m["name"], m["listed"]) for m in listed["data"]["miners"]] == [
            (VISION_NAME, False)
        ]
    list_miner(project, agent)  # the researcher lists it in the protocol
    async with open_session(settings, clock) as client:
        served = await client.call(
            "mine_next", project="demo", miner=VISION_NAME, version=1, pass_label="A", **AGENT
        )
        assert served["ok"] is True, served
        batch = served["data"]["batch"]
        assert batch["anchors"] == ["s3.p1", "t1"] and batch["miner"] == VISION_NAME
        out = await client.call(
            "mine_record",
            project="demo",
            task_id=batch["task_id"],
            rows=[mine_row().model_dump(mode="json"), {"fields": {}}],
            finish=True,
            **AGENT,
        )
        assert out["ok"] is True, out
        assert len(out["data"]["rows"]["written"]) == 1
        assert [r["index"] for r in out["data"]["rows"]["rejected"]] == [1]
        assert out["data"]["completed"] is False  # a rejected item keeps the unit open
        status = await client.call("mine_status", project="demo")
        assert status["ok"] is True
        entry = status["data"]["miners"][0]
        assert entry["name"] == VISION_NAME and entry["rows"] == 1 and entry["agreement"] is None
        assert "rate" not in json.dumps(status)


@pytest.mark.anyio
async def test_mcp_mine_tools_refuse_invalid_input_and_write_nothing(
    settings: Settings,
    project: Project,
    agent: Actor,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    _session(monkeypatch, SESSION_M1)
    before = _count(project)
    async with open_session(settings, clock) as client:
        bad_spec = spec_to_json(vision_result(name="ml-benchmark"))
        out = await client.call("miner_register", project="demo", spec=bad_spec, **AGENT)
        assert out["ok"] is False and out["errors"][0]["field"] == "name"
        out = await client.call("miner_register", project="demo", spec={"name": "m-x"}, **AGENT)
        assert out["ok"] is False
        assert "selector.population" in {e["field"] for e in out["errors"]}
        out = await client.call(
            "mine_next", project="demo", miner="m-nope", version=1, pass_label="A", **AGENT
        )
        assert out["ok"] is False and out["errors"][0]["field"] == "miners"
        out = await client.call(
            "mine_next", project="demo", miner="m-nope", version=1, pass_label="C", **AGENT
        )
        assert out["ok"] is False and out["errors"][0]["field"] == "pass_label"
        out = await client.call("mine_record", project="demo", task_id="tsk_nope", rows=[], **AGENT)
        assert out["ok"] is False and out["errors"][0]["field"] == "task_id"
        out = await client.call(
            "mine_record",
            project="demo",
            task_id="tsk_nope",
            rows=[],
            supersedes={"first": "ext_x"},
            **AGENT,
        )
        assert out["ok"] is False and out["errors"][0]["field"] == "supersedes.first"
    assert _count(project) == before
    del agent
