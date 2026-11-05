"""The document read gate for full-text screeners (plan 2C, task 6; decision 37).

A session joined to a full-text pass reads only the works of the batches it holds or has
completed, and only the conversion each batch pins. A title/abstract pass session reads nothing.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from mcp import Client
from mcp.types import TextContent
from pydantic import JsonValue

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel, ScreeningItem, Verdict
from factory.services import extraction
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items, draw_calibration, label_calibration
from factory.services.context import Project
from factory.services.document_read import DocumentPage, document_read
from factory.services.extraction import extract_next
from factory.services.fulltext_screening import fulltext_queue
from factory.services.screening import ScreenBatch, pass_b_sample, screen_next, screen_record
from factory.services.tasks import release_task
from factory.sources.registry import SourceFactory
from tests.document_helpers import (
    StubConverter,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.extraction_helpers import SESSION_A, SESSION_B, _declare_latency, _extractor
from tests.helpers import SESSION
from tests.test_acceptance_fulltext_screening import _screened_full_text_world
from tests.test_fulltext_eligibility import _convert, _world

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
STRANGER = "01JZ9Q3K5M7N8P0R2S4T6V8W0Z"


class _World:
    def __init__(self, a: ScreenBatch, b: ScreenBatch | None, outside: list[str]) -> None:
        self.a = a
        self.b = b
        self.outside = outside  # promoted, converted works not in pass A's claimed batch

    @property
    def mine(self) -> str:
        return str(self.a.records[0]["work_id"])


def _make(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    with_b: bool,
    dual: float = 0.5,
) -> _World:
    _world(project, agent, human, mock_sources, dual_sample=dual)
    promoted = promoted_works(project)
    _convert(project, promoted)
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    batch_a = screen_next(project, agent, PassLabel.A, stage=FT).batch
    assert batch_a is not None
    batch_b = None
    if with_b:
        other_model = agent_other.model_copy(update={"model": "claude-sonnet-5-5"})
        batch_b = screen_next(project, other_model, PassLabel.B, stage=FT).batch
    held = {str(r["work_id"]) for r in batch_a.records}
    return _World(batch_a, batch_b, [w for w in promoted if w not in held])


@pytest.fixture
def world(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> _World:
    return _make(project, agent, agent_other, human, mock_sources, with_b=False)


def _fields(project: Project, **kwargs: Any) -> list[str]:
    with pytest.raises(FactoryValidationError) as caught:
        document_read(project, **kwargs)
    return [issue.field for issue in caught.value.issues]


def test_ft_screener_reads_own_queue_pinned_conversion(project: Project, world: _World) -> None:
    record = world.a.records[0]
    page = document_read(project, work_id=world.mine, session=SESSION)
    assert page.conversion_id == record["conversion_id"]
    assert page.document_id == record["document_id"]
    named = document_read(
        project,
        work_id=world.mine,
        session=SESSION,
        document_id=str(record["document_id"]),
        conversion_id=str(record["conversion_id"]),
    )
    assert named.segments == page.segments


def test_ft_screener_refused_other_work(project: Project, world: _World) -> None:
    assert world.outside, "the world must hold works outside the claimed batch"
    assert _fields(project, work_id=world.outside[0], session=SESSION) == ["work_id"]
    # The researcher (no session) still reads it.
    assert isinstance(document_read(project, work_id=world.outside[0]), DocumentPage)


def test_ft_screener_refused_other_conversion(project: Project, world: _World) -> None:
    record = world.a.records[0]
    pinned = str(record["conversion_id"])
    run_convert(project, make_registry(StubConverter(version="9.9+later")))
    later = fulltext_queue(project)
    newer = next(e for e in later.eligible if e.work_id == world.mine)
    assert newer.conversion_id != pinned
    # The unpinned researcher read follows the default (the later conversion); the screener's
    # follows the pin.
    assert document_read(project, work_id=world.mine).conversion_id == newer.conversion_id
    assert document_read(project, work_id=world.mine, session=SESSION).conversion_id == pinned
    assert _fields(
        project, work_id=world.mine, session=SESSION, conversion_id=newer.conversion_id
    ) == ["conversion_id"]
    assert _fields(project, work_id=world.mine, session=SESSION, document_id="doc-nope") == [
        "document_id"
    ]
    ok = document_read(project, work_id=world.mine, session=SESSION, conversion_id=pinned)
    assert ok.conversion_id == pinned


def test_ta_pass_session_refused(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=0.5)
    work = promoted_works(project)[0]
    _convert(project, [work])
    assert screen_next(project, agent, PassLabel.A).batch is not None
    assert _fields(project, work_id=work, session=SESSION) == ["session"]


def test_session_in_both_stages_follows_full_text_rule(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=0.5)
    promoted = promoted_works(project)
    _convert(project, promoted)
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    assert screen_next(project, agent, PassLabel.A).batch is not None  # joins title/abstract
    batch = screen_next(project, agent, PassLabel.A, stage=FT).batch  # and full text
    assert batch is not None
    held = {str(r["work_id"]) for r in batch.records}
    mine = sorted(held)[0]
    assert document_read(project, work_id=mine, session=SESSION).work_id == mine
    outside = [w for w in promoted if w not in held]
    assert outside
    assert _fields(project, work_id=outside[0], session=SESSION) == ["work_id"]


def test_other_pass_screener_cannot_read_this_passes_queue_docs(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    w = _make(project, agent, agent_other, human, mock_sources, with_b=True, dual=0.2)
    assert w.b is not None
    # The calibration gate is closed, so both passes hold the same calibration batch; the works
    # outside it are in pass A's queue (and B's sample) but in no batch of B's.
    sample = pass_b_sample(project, stage=FT)
    assert sample is not None
    in_a_only = sorted(set(w.outside) - set(sample))
    assert in_a_only, "pass A's queue must hold a work outside pass B's sample"
    b_work = str(w.b.records[0]["work_id"])
    assert _fields(project, work_id=str(in_a_only[0]), session=agent_other.session) == ["work_id"]
    assert document_read(project, work_id=b_work, session=agent_other.session).work_id == b_work
    # Queued but unclaimed works are not readable by the pass that owns them either.
    assert _fields(project, work_id=str(in_a_only[0]), session=SESSION) == ["work_id"]


def test_non_pass_session_unchanged(project: Project, world: _World) -> None:
    page = document_read(project, work_id=world.outside[0], session=STRANGER)
    assert page.work_id == world.outside[0]
    assert page == document_read(project, work_id=world.outside[0])


def test_no_verdicts_in_output(project: Project, world: _World) -> None:
    page = document_read(project, work_id=world.mine, session=SESSION)
    assert set(page.model_dump()) == {
        "work_id",
        "document_id",
        "conversion_id",
        "route",
        "quality",
        "source_version",
        "converter",
        "converter_version",
        "markdown_hash",
        "segments",
        "next_after",
        "total_segments",
    }
    assert {key for seg in page.segments for key in seg.model_dump()} == {
        "anchor",
        "kind",
        "parent",
        "text",
        "truncated",
    }


@pytest.mark.anyio
async def test_mcp_document_read_gate(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: _World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedIds:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return SESSION

    monkeypatch.setattr(mcp_server, "IdGenerator", _FixedIds)
    server = build_server(settings, clock=clock)
    pinned = str(world.a.records[0]["conversion_id"])

    async def read(**args: JsonValue) -> dict[str, Any]:
        async with Client(server) as client:
            result = await client.call_tool("document_read", {"project": "demo", **args})
        block = result.content[0]
        assert isinstance(block, TextContent)
        body: dict[str, Any] = json.loads(block.text)
        return body

    ok = await read(work_id=world.mine)
    assert ok["ok"] is True, ok
    assert ok["data"]["conversion_id"] == pinned
    other = await read(work_id=world.outside[0])
    assert other["ok"] is False
    assert [e["field"] for e in other["errors"]] == ["work_id"]


def test_pass_b_cannot_read_a_batch_held_by_pass_a(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """With the calibration gate passed by pass A, A claims an ordinary batch that B does not."""
    w = _make(project, agent, agent_other, human, mock_sources, with_b=True, dual=0.2)
    assert w.b is not None
    for item in calibration_items(project, stage=FT):
        label_calibration(project, human, item, "include", None, Channel.CLI, stage=FT)
    done = screen_record(
        project,
        agent,
        w.a.task_id,
        [
            ScreeningItem(
                work_id=str(r["work_id"]),
                verdict=Verdict.INCLUDE,
                quote="Lorem ipsum dolor sit amet.",
                rationale="it fits",
                anchor="s3.p1",
            )
            for r in w.a.records
        ],
    )
    assert len(done.written) == len(w.a.records)
    ordinary = screen_next(project, agent, PassLabel.A, stage=FT)
    assert ordinary.blocked == [] and ordinary.batch is not None
    b_calibration = {str(r["work_id"]) for r in w.b.records}
    mine = next(
        str(r["work_id"]) for r in ordinary.batch.records if str(r["work_id"]) not in b_calibration
    )
    assert document_read(project, work_id=mine, session=SESSION).work_id == mine
    assert _fields(project, work_id=mine, session=agent_other.session) == ["work_id"]
    assert document_read(project, work_id=mine, session=STRANGER).work_id == mine
    release_task(project, agent, ordinary.batch.task_id, "test")
    assert _fields(project, work_id=mine, session=SESSION) == ["work_id"]


# --- Extraction sessions (plan D, task 5) ---


@pytest.fixture
def extraction_world(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    """Full text screened to the end and an extraction schema declared; the included works."""
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare_latency(project, agent, 1.0)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


def test_extraction_session_reads_own_queue_pinned_conversion(
    project: Project, extraction_world: list[str]
) -> None:
    batch = extract_next(project, _extractor(SESSION_A, "claude-opus-5-5"), PassLabel.A).batch
    assert batch is not None
    record = batch.records[0]
    page = document_read(project, work_id=record["work_id"], session=SESSION_A)
    assert (page.document_id, page.conversion_id) == (
        record["document_id"],
        record["conversion_id"],
    )
    named = document_read(
        project,
        work_id=record["work_id"],
        session=SESSION_A,
        document_id=record["document_id"],
        conversion_id=record["conversion_id"],
    )
    assert named.segments == page.segments


def test_extraction_session_refused_other_work(
    project: Project, extraction_world: list[str]
) -> None:
    batch = extract_next(project, _extractor(SESSION_A, "claude-opus-5-5"), PassLabel.A).batch
    assert batch is not None
    other = next(w for w in extraction_world if w != batch.records[0]["work_id"])
    assert _fields(project, work_id=other, session=SESSION_A) == ["work_id"]
    assert isinstance(document_read(project, work_id=other), DocumentPage)


def test_extraction_session_refused_other_conversion(
    project: Project, extraction_world: list[str]
) -> None:
    batch = extract_next(project, _extractor(SESSION_A, "claude-opus-5-5"), PassLabel.A).batch
    assert batch is not None
    work = batch.records[0]["work_id"]
    pinned = batch.records[0]["conversion_id"]
    run_convert(project, make_registry(StubConverter(version="9.9+later")))
    newer = next(e for e in fulltext_queue(project).eligible if e.work_id == work)
    assert newer.conversion_id != pinned
    assert document_read(project, work_id=work).conversion_id == newer.conversion_id
    assert document_read(project, work_id=work, session=SESSION_A).conversion_id == pinned
    assert _fields(project, work_id=work, session=SESSION_A, conversion_id=newer.conversion_id) == [
        "conversion_id"
    ]


def test_pass_b_session_cannot_read_a_only_work(
    project: Project, extraction_world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    a_only = extraction_world[-1]
    real = extraction.in_dual_sample
    monkeypatch.setattr(
        extraction,
        "in_dual_sample",
        lambda seed, work, fraction: work != a_only and real(seed, work, fraction),
    )
    ext_a = _extractor(SESSION_A, "claude-opus-5-5")
    ext_b = _extractor(SESSION_B, "claude-sonnet-5-5")
    assert extract_next(project, ext_a, PassLabel.A).batch is not None
    batch_b = extract_next(project, ext_b, PassLabel.B).batch
    assert batch_b is not None and batch_b.records[0]["work_id"] != a_only
    assert _fields(project, work_id=a_only, session=SESSION_B) == ["work_id"]
    own = batch_b.records[0]["work_id"]
    assert document_read(project, work_id=own, session=SESSION_B).work_id == own
