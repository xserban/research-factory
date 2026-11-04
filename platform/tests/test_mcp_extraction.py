"""The extraction MCP tools (plan D, task 11): parse, call a service, reply; nothing else."""

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.model.extraction import ExtractedRowInput
from factory.services.context import Project
from tests.helpers import SESSION, install_skill, open_session
from tests.test_extraction_agreement import (  # noqa: F401
    _both,
    _r,
    ext_a,
    ext_b,
    screened,
    world,
)
from tests.test_extraction_next import SESSION_A, SESSION_B

FRESH = "01JZ9Q3K5M7N8P0R2S4T6V8W1C"
AGENT_A = {"role": "extractor", "model": "claude-opus-5-5", "skill": "rf-extract"}


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


def _dump(row: ExtractedRowInput) -> dict[str, object]:
    return row.model_dump(mode="json")


@pytest.mark.anyio
async def test_extract_next_serves_a_pinned_batch_and_no_other_pass_data(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    _session(monkeypatch, SESSION_A)
    async with open_session(settings, clock) as client:
        served = await client.call("extract_next", project="demo", pass_label="A", **AGENT_A)
    assert served["ok"] is True, served
    batch = served["data"]["batch"]
    record = batch["records"][0]
    assert record["conversion_id"] and record["document_id"]
    assert set(batch) >= {"task_id", "fields", "required", "claims", "instructions"}
    assert "rows" not in served["data"]


@pytest.mark.anyio
async def test_unknown_pass_label_is_a_structured_error_and_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    _session(monkeypatch, SESSION_A)
    before = _count(project)
    async with open_session(settings, clock) as client:
        out = await client.call("extract_next", project="demo", pass_label="C", **AGENT_A)
    assert out["ok"] is False
    assert out["errors"][0]["field"] == "pass_label"
    assert _count(project) == before


@pytest.mark.anyio
async def test_record_writes_valid_rows_and_rejects_the_rest_by_index(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    _session(monkeypatch, SESSION_A)
    async with open_session(settings, clock) as client:
        served = await client.call("extract_next", project="demo", pass_label="A", **AGENT_A)
        task = served["data"]["batch"]["task_id"]
        bad_quote = _dump(_r(value="2"))
        bad_quote["fields"]["value"]["quote"] = "not in the document"  # type: ignore[index]
        rows = [{"fields": {}}, _dump(_r()), bad_quote]
        out = await client.call(
            "extract_record", project="demo", task_id=task, rows=rows, finish=True, **AGENT_A
        )
    assert out["ok"] is True, out
    data = out["data"]
    assert len(data["rows"]["written"]) == 1
    assert [r["index"] for r in data["rows"]["rejected"]] == [0, 2]
    assert data["completed"] is False
    assert len(_of(project, "extraction.recorded")) == 1
    assert not _of(project, "extraction.closed")


@pytest.mark.anyio
async def test_supersedes_keys_are_row_indices_given_as_strings(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    _session(monkeypatch, SESSION_A)
    async with open_session(settings, clock) as client:
        served = await client.call("extract_next", project="demo", pass_label="A", **AGENT_A)
        task = served["data"]["batch"]["task_id"]
        first = await client.call(
            "extract_record", project="demo", task_id=task, rows=[_dump(_r())], **AGENT_A
        )
        target = first["data"]["rows"]["written"][0]
        before = _count(project)
        bad = await client.call(
            "extract_record",
            project="demo",
            task_id=task,
            rows=[_dump(_r())],
            supersedes={"first": target},
            **AGENT_A,
        )
        assert bad["ok"] is False
        assert bad["errors"][0]["field"] == "supersedes.first"
        assert _count(project) == before
        ok = await client.call(
            "extract_record",
            project="demo",
            task_id=task,
            rows=[_dump(_r())],
            supersedes={"0": target},
            **AGENT_A,
        )
    assert ok["ok"] is True, ok
    assert len(ok["data"]["rows"]["written"]) == 1


@pytest.mark.anyio
async def test_agreement_is_refused_to_pass_and_screening_sessions(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ext_a: Actor,  # noqa: F811
    ext_b: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _both(project, ext_a, ext_b)
    for session in (SESSION_B, SESSION_A, SESSION):  # pass B, pass A, screening passes
        _session(monkeypatch, session)
        async with open_session(settings, clock) as client:
            out = await client.call("extract_agreement", project="demo")
        assert out["ok"] is False
        assert out["errors"][0]["field"] == "session"
    _session(monkeypatch, FRESH)
    async with open_session(settings, clock) as client:
        out = await client.call("extract_agreement", project="demo")
    assert out["ok"] is True, out
    assert out["data"]["disagreements"] == []


@pytest.mark.anyio
async def test_audit_sample_returns_evidence_and_label_is_a_human_mcp_event(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ext_a: Actor,  # noqa: F811
    ext_b: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _both(project, ext_a, ext_b)
    _session(monkeypatch, SESSION_A)
    async with open_session(settings, clock) as client:
        refused = await client.call("extract_audit_sample", project="demo")
    assert refused["ok"] is False and not _of(project, "extraction.audit_sampled")
    _session(monkeypatch, FRESH)
    async with open_session(settings, clock) as client:
        out = await client.call("extract_audit_sample", project="demo")
        assert out["ok"] is True, out
        data = out["data"]
        item = data["items"][0]
        assert item["element_text"] and item["item"]["field"]
        assert data["population"] >= len(data["items"]) > 0
        labelled = await client.call(
            "extract_audit_record",
            project="demo",
            audit_id=data["audit_id"],
            work_id=item["item"]["work_id"],
            row_key=item["item"]["row_key"],
            field=item["item"]["field"],
            correct=True,
        )
    assert labelled["ok"] is True, labelled
    [event] = _of(project, "extraction.audit_labelled")
    assert event.actor.kind == "human"
    assert event.payload["channel"] == "mcp"
    assert event.id == labelled["data"]["event_id"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("check", {}),
        ("trace", {"ref": "anything"}),
        ("trace", {"ref": "rk_0123456789ab/value"}),
        ("report_prisma", {}),
        ("report_methods", {}),
    ],
)
async def test_reports_check_and_trace_are_refused_to_an_extraction_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    args: dict[str, str],
) -> None:
    install_skill(settings, "rf-extract")
    _session(monkeypatch, FRESH)
    async with open_session(settings, clock) as client:
        served = await client.call("extract_next", project="demo", pass_label="A", **AGENT_A)
        assert served["ok"] is True, served
        out = await client.call(tool, project="demo", **args)
    assert out["ok"] is False
    assert out["errors"][0]["field"] == "session"
