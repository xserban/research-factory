"""The contribution MCP tools (plan G2-B, task 5): parse, call a service, reply; nothing else."""

# ruff: noqa: F401, F811

import json

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.services.context import Project
from factory.services.seeds import SeedRole, all_seeds
from tests.contribution_helpers import (
    ENTRIES,
    P1,
    P2,
    SESSION_C,
    ctr_a,
    field,
    item,
    screened,
    with_references,
    world,
)
from tests.helpers import SESSION, install_skill, open_session
from tests.test_extraction_next import SESSION_A

AGENT = {"role": "extractor", "model": "claude-opus-5-5", "skill": "rf-contributions"}


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _of(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def _dump(row: object) -> dict[str, object]:
    return row.model_dump(mode="json")  # type: ignore[attr-defined, no-any-return]


@pytest.mark.anyio
async def test_next_serves_a_pinned_batch_with_references(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-contributions")
    with_references(project, agent, world[0])
    _session(monkeypatch, SESSION_C)
    async with open_session(settings, clock) as client:
        served = await client.call("contribution_next", project="demo", pass_label="A", **AGENT)
    assert served["ok"] is True, served
    batch = served["data"]["batch"]
    assert batch["schema_ref"] == "contribution@1" and batch["records"][0]["conversion_id"]
    assert batch["references"]["status"] == "current"
    assert [e["ordinal"] for e in batch["references"]["entries"]] == [1, 2, 3, 4, 5, 6]
    assert batch["item_rules"] and "rows" not in served["data"]
    [created] = [e for e in _of(project, "task.created") if e.payload["kind"] == "contrib_a"][:1]
    assert created.actor.skill is not None and created.actor.skill.startswith("rf-contributions@")


@pytest.mark.anyio
async def test_unknown_pass_label_is_a_structured_error_and_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-contributions")
    _session(monkeypatch, SESSION_C)
    before = _count(project)
    async with open_session(settings, clock) as client:
        out = await client.call("contribution_next", project="demo", pass_label="C", **AGENT)
    assert out["ok"] is False and out["errors"][0]["field"] == "pass_label"
    assert _count(project) == before


@pytest.mark.anyio
async def test_record_writes_valid_items_and_rejects_the_rest_by_index(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-contributions")
    with_references(project, agent, world[0])
    _session(monkeypatch, SESSION_C)
    async with open_session(settings, clock) as client:
        served = await client.call("contribution_next", project="demo", pass_label="A", **AGENT)
        task = served["data"]["batch"]["task_id"]
        bad_quote = _dump(item("addition", P2, name="softmax attention"))
        bad_quote["fields"]["statement"]["quote"] = "not in the document"  # type: ignore[index]
        good = _dump(item("base-idea", P1, name="linear attention", cited_entry=field(5)))
        items = [{"fields": {}}, good, bad_quote]
        out = await client.call(
            "contribution_record", project="demo", task_id=task, items=items, finish=True, **AGENT
        )
    assert out["ok"] is True, out
    data = out["data"]
    assert len(data["rows"]["written"]) == 1
    assert [r["index"] for r in data["rows"]["rejected"]] == [0, 2]
    assert data["completed"] is False and data["claims"] == {"written": [], "rejected": []}
    [recorded] = _of(project, "extraction.recorded")
    assert recorded.payload["cited"]["marker"] == "matched"
    assert recorded.actor.skill is not None and recorded.actor.skill.startswith("rf-contributions@")
    assert not _of(project, "extraction.closed")


@pytest.mark.anyio
async def test_supersedes_keys_are_item_indices_given_as_strings(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-contributions")
    with_references(project, agent, world[0])
    _session(monkeypatch, SESSION_C)
    first_item = _dump(item("base-idea", P1, name="linear attention"))
    async with open_session(settings, clock) as client:
        served = await client.call("contribution_next", project="demo", pass_label="A", **AGENT)
        task = served["data"]["batch"]["task_id"]
        first = await client.call(
            "contribution_record", project="demo", task_id=task, items=[first_item], **AGENT
        )
        target = first["data"]["rows"]["written"][0]
        before = _count(project)
        bad = await client.call(
            "contribution_record",
            project="demo",
            task_id=task,
            items=[first_item],
            supersedes={"first": target},
            **AGENT,
        )
        assert bad["ok"] is False and bad["errors"][0]["field"] == "supersedes.first"
        assert _count(project) == before
        ok = await client.call(
            "contribution_record",
            project="demo",
            task_id=task,
            items=[_dump(item("base-idea", P1, name="linear attention", cited_entry=field(5)))],
            supersedes={"0": target},
            **AGENT,
        )
    assert ok["ok"] is True, ok
    [_, new] = _of(project, "extraction.recorded")
    assert new.payload["supersedes"] == target


@pytest.mark.anyio
async def test_a_refused_close_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-contributions")
    with_references(project, agent, world[0])
    _session(monkeypatch, SESSION_C)
    async with open_session(settings, clock) as client:
        served = await client.call("contribution_next", project="demo", pass_label="A", **AGENT)
        task = served["data"]["batch"]["task_id"]
        before = _count(project)
        out = await client.call(
            "contribution_record",
            project="demo",
            task_id=task,
            items=[_dump(item("base-idea", P1, name="linear attention"))],
            finish=True,
            **AGENT,
        )
    assert out["ok"] is False
    assert {(e["field"], e["reason"]) for e in out["errors"]} >= {
        ("finish", "limitation-not-covered"),
        ("finish", "no-addition"),
    }
    assert _count(project) == before


@pytest.mark.anyio
async def test_held_out_entries_are_masked(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-contributions")
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.doi is not None
    entries = [*ENTRIES[:2], f"A. Zhou. A held paper. Journal of Tests, 2020. doi:{held.doi}."]
    with_references(project, agent, world[0], entries=[*entries, *ENTRIES[3:]])
    _session(monkeypatch, SESSION_C)
    async with open_session(settings, clock) as client:
        served = await client.call("contribution_next", project="demo", pass_label="A", **AGENT)
    assert served["ok"] is True, served
    listed = served["data"]["batch"]["references"]["entries"]
    masked = next(e for e in listed if e["ordinal"] == 3)
    assert masked["title"] is None and masked["doi"] is None and masked["arxiv"] is None
    assert masked["first_author"] == "Zhou" and masked["year"] == 2020
    text = json.dumps(served)
    assert held.doi not in text and "held paper" not in text
    assert next(e for e in listed if e["ordinal"] == 5)["title"] == "Linear attention with kernels"


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["report_prisma", "report_methods", "check", "trace"])
async def test_pass_sessions_of_either_scope_are_refused_the_report_surfaces(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
) -> None:
    install_skill(settings, "rf-contributions")
    install_skill(settings, "rf-extract")
    args = {"ref": world[0]} if tool == "trace" else {}
    for session, joining, extra in (
        (SESSION_C, "contribution_next", {"skill": "rf-contributions"}),
        (SESSION_A, "extract_next", {"skill": "rf-extract"}),
    ):
        _session(monkeypatch, session)
        async with open_session(settings, clock) as client:
            joined = await client.call(
                joining, project="demo", pass_label="A", **{**AGENT, **extra}
            )
            assert joined["ok"] is True, joined
            before = _count(project)
            out = await client.call(tool, project="demo", **args)
        assert out["ok"] is False and out["errors"][0]["field"] == "session"
        assert _count(project) == before
