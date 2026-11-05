# ruff: noqa: F811
"""Extraction passes, population, pinned tasks and extract_next (plan D, task 5)."""

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.extraction import ExtractionAuditSampled, ExtractionResolved
from factory.model.screening import Channel, PassLabel
from factory.services import extraction
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.extraction import (
    EXTRACT_KINDS,
    ExtractBatch,
    extract_next,
    extraction_population,
    in_dual_sample,
    is_extraction_session,
    join_extraction_pass,
    pass_config,
    require_schema,
    unit_pin,
)
from factory.services.protocol import current_protocol
from factory.services.screening import join_pass, screen_next
from factory.services.tasks import complete_task
from tests.document_helpers import StubConverter, make_registry, run_convert
from tests.extraction_helpers import (  # noqa: F401
    FT,
    LATENCY_FIELDS,
    SESSION_A,
    SourcesFor,
    _declare_latency,
    _extractor,
    ext_a,
    ext_b,
    screened,
)
from tests.helpers import SESSION, _setup

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"


@pytest.fixture
def world(project: Project, agent: Actor, screened: list[str]) -> list[str]:
    _declare_latency(project, agent, 1.0)
    return screened


def _event_count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _extraction_types(project: Project) -> list[str]:
    return [
        e.type
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type.startswith("extraction.")
    ]


def _fields_of(exc: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [i.field for i in exc.value.issues]


def _serve_all(project: Project, actor: Actor, label: PassLabel) -> list[ExtractBatch]:
    out: list[ExtractBatch] = []
    while True:
        batch = extract_next(project, actor, label).batch
        if batch is None:
            return out
        out.append(batch)
        complete_task(project, actor, batch.task_id)


def _work(batch: ExtractBatch) -> str:
    return batch.records[0]["work_id"]


def test_refused_until_schema_declared(project: Project, ext_a: Actor, screened: list[str]) -> None:
    before = _event_count(project)
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, ext_a, PassLabel.A)
    assert e.value.issues[0].field == "extraction_schema"
    assert "R-13" in e.value.issues[0].reason
    assert _event_count(project) == before
    assert not _extraction_types(project)


def test_refused_without_full_text_plan(
    project: Project, agent: Actor, ext_a: Actor, mock_sources: SourcesFor, human: Actor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _declare_latency(project, agent, 1.0)
    before = _event_count(project)
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, ext_a, PassLabel.A)
    assert _fields_of(e) == ["full_text_screening"]
    assert _event_count(project) == before


def test_require_schema_refuses_without_a_protocol(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as e:
        require_schema(project)
    assert _fields_of(e) == ["protocol"]


def test_only_full_text_included_works_are_queued(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    assert world and extraction_population(project) == world
    served = {_work(b) for b in _serve_all(project, ext_a, PassLabel.A)}
    assert served == set(world)
    assert any(o is not Outcome.INCLUDED for o in final_outcomes(project, stage=FT).values())


def test_task_pins_current_conversion_and_both_passes_share_it(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    a = _serve_all(project, ext_a, PassLabel.A)
    b = _serve_all(project, ext_b, PassLabel.B)
    pins_a = {r["work_id"]: (r["document_id"], r["conversion_id"]) for x in a for r in x.records}
    pins_b = {r["work_id"]: (r["document_id"], r["conversion_id"]) for x in b for r in x.records}
    assert pins_b == pins_a
    for work, pin in pins_a.items():
        assert unit_pin(project, work) == pin


def test_batch_has_one_record_fields_and_instructions(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    assert len(batch.records) == 1
    assert set(batch.records[0]) == {"work_id", "title", "document_id", "conversion_id"}
    assert [f["name"] for f in batch.fields] == list(LATENCY_FIELDS)
    assert batch.schema_ref == "ml-benchmark@1"
    assert "value" in batch.required
    assert "never compute" in batch.instructions.lower()


def test_pass_b_serves_fields_reversed(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    batch_a = extract_next(project, ext_a, PassLabel.A).batch
    batch_b = extract_next(project, ext_b, PassLabel.B).batch
    assert batch_a is not None and batch_b is not None
    assert [f["name"] for f in batch_b.fields] == [f["name"] for f in batch_a.fields][::-1]
    config = pass_config(project, PassLabel.B)
    assert config is not None and config.field_order == "reversed"


def test_session_cannot_join_both_passes(project: Project, ext_a: Actor, world: list[str]) -> None:
    extract_next(project, ext_a, PassLabel.A)
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, ext_a, PassLabel.B)
    assert _fields_of(e) == ["pass"]
    with pytest.raises(FactoryValidationError) as e2:
        join_extraction_pass(project, ext_a, PassLabel.B)
    assert _fields_of(e2) == ["pass"]


def test_same_model_cannot_serve_both_passes(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    extract_next(project, ext_a, PassLabel.A)
    same = ext_b.model_copy(update={"model": ext_a.model})
    before = _event_count(project)
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, same, PassLabel.B)
    assert _fields_of(e) == ["model"]
    assert _event_count(project) == before


def test_screening_session_cannot_extract(project: Project, agent: Actor, world: list[str]) -> None:
    assert agent.session == SESSION  # screened both stages in this world
    fresh_model = agent.model_copy(update={"model": "claude-haiku-5-5"})
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, fresh_model, PassLabel.A)
    assert _fields_of(e) == ["session"]
    assert not is_extraction_session(project, SESSION)


def test_label_session_cannot_extract(project: Project, ext_a: Actor, world: list[str]) -> None:
    protocol = current_protocol(project)
    assert protocol is not None
    relay = ext_a.model_copy(update={"kind": "human", "model": None, "skill": None})
    resolved = ExtractionResolved(
        work_id=world[0],
        row_key="rk_0123456789ab",
        field=None,
        choice="a",
        reason="x",
        channel=Channel.MCP,
        protocol_id=protocol.protocol_id,
    )
    project.record([project.events.make("extraction.resolved", resolved, relay)])
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, ext_a, PassLabel.A)
    assert _fields_of(e) == ["session"]


def test_non_agent_refused(project: Project, human: Actor, world: list[str]) -> None:
    before = _event_count(project)
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, human, PassLabel.A)
    assert _fields_of(e) == ["actor"]
    assert _event_count(project) == before


WORKS = [f"rf:w{i}" for i in range(200)]


def test_dual_sample_is_monotone_and_stable() -> None:
    small = {w for w in WORKS if in_dual_sample(7, w, 0.3)}
    large = {w for w in WORKS if in_dual_sample(7, w, 0.6)}
    assert small <= large and small != large
    assert in_dual_sample(7, "rf:x", None)
    assert all(in_dual_sample(7, w, 1.0) for w in WORKS)
    assert small == {w for w in WORKS if in_dual_sample(7, w, 0.3)}
    assert 0.15 < len(small) / len(WORKS) < 0.45


def test_pass_b_queue_is_the_recorded_sample_only(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, screened: list[str]
) -> None:
    _declare_latency(project, agent, 0.5)
    _serve_all(project, ext_a, PassLabel.A)
    first = extract_next(project, ext_b, PassLabel.B)
    config = pass_config(project, PassLabel.B)
    assert config is not None
    expected = {w for w in screened if in_dual_sample(config.seed, w, 0.5)}
    got: set[str] = set()
    if first.batch is not None:
        got.add(_work(first.batch))
        complete_task(project, ext_b, first.batch.task_id)
        got |= {_work(b) for b in _serve_all(project, ext_b, PassLabel.B)}
    assert got == expected


def test_pass_opened_event_carries_seed_and_agent_provenance(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    extract_next(project, ext_a, PassLabel.A)
    events = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type.startswith("extraction.")
    ]
    assert [e.type for e in events] == ["extraction.pass_opened", "extraction.pass_joined"]
    config = pass_config(project, PassLabel.A)
    assert config is not None and config.seed == events[0].payload["random_seed"]
    assert events[0].payload["field_order"] == "schema"
    for e in events:
        assert e.actor.model == ext_a.model and e.actor.skill == ext_a.skill
        assert e.input_blob is not None
    assert is_extraction_session(project, SESSION_A)


def test_extract_next_idempotent_when_task_held(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    first = extract_next(project, ext_a, PassLabel.A)
    again = extract_next(project, ext_a, PassLabel.A)
    assert first.batch is not None and again.batch is not None
    assert again.batch.task_id == first.batch.task_id
    assert again.remaining == first.remaining == len(world)
    with project.index.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM tasks WHERE kind = :k"), {"k": EXTRACT_KINDS[PassLabel.A]}
        ).scalar_one()
    assert count == len(world)


def test_remaining_counts_down_and_ends_empty(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    complete_task(project, ext_a, batch.task_id)
    assert extract_next(project, ext_a, PassLabel.A).remaining == len(world) - 1
    _serve_all(project, ext_a, PassLabel.A)
    done = extract_next(project, ext_a, PassLabel.A)
    assert done.batch is None and done.remaining == 0


def test_blocked_reports_works_without_a_converted_document(
    project: Project, ext_a: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = world[0]
    real = extraction.default_conversion
    monkeypatch.setattr(
        extraction, "default_conversion", lambda p, w: None if w == missing else real(p, w)
    )
    result = extract_next(project, ext_a, PassLabel.A)
    assert result.blocked == ["1 works have no converted document"]
    assert result.remaining == len(world) - 1
    served = {_work(b) for b in _serve_all(project, ext_a, PassLabel.A)}
    assert missing not in served
    assert extract_next(project, ext_a, PassLabel.A).remaining == 0


def test_blocked_when_no_work_falls_in_the_dual_sample(
    project: Project, ext_b: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extraction, "in_dual_sample", lambda seed, work, fraction: False)
    result = extract_next(project, ext_b, PassLabel.B)
    assert result.batch is None
    assert result.blocked == ["no work falls in the dual sample"]
    assert result.remaining == 0


def test_full_dual_sample_puts_every_work_in_pass_b(
    project: Project, agent: Actor, ext_b: Actor, screened: list[str]
) -> None:
    _declare_latency(project, agent, 1.0)
    served = {_work(b) for b in _serve_all(project, ext_b, PassLabel.B)}
    assert served == set(screened)


def test_cli_label_does_not_mark_a_session_as_a_relay(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    protocol = current_protocol(project)
    assert protocol is not None
    cli = ext_a.model_copy(update={"kind": "human", "model": None, "skill": None})
    resolved = ExtractionResolved(
        work_id=world[0],
        row_key="rk_0123456789ab",
        field=None,
        choice="a",
        reason="x",
        channel=Channel.CLI,
        protocol_id=protocol.protocol_id,
    )
    project.record([project.events.make("extraction.resolved", resolved, cli)])
    assert extract_next(project, ext_a, PassLabel.A).batch is not None


def test_pass_b_keeps_the_pin_of_pass_a_after_a_later_conversion(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    a = {_work(b): b.records[0]["conversion_id"] for b in _serve_all(project, ext_a, PassLabel.A)}
    run_convert(project, make_registry(StubConverter(version="9.9+later")))
    b = {_work(x): x.records[0]["conversion_id"] for x in _serve_all(project, ext_b, PassLabel.B)}
    assert b == a


def test_two_sessions_of_one_pass_never_claim_the_same_task(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    other = _extractor("01JZ9Q3K5M7N8P0R2S4T6V8W1C", ext_a.model or "")
    first = extract_next(project, ext_a, PassLabel.A).batch
    second = extract_next(project, other, PassLabel.A).batch
    assert first is not None and second is not None
    assert first.task_id != second.task_id and _work(first) != _work(second)


def test_extraction_session_cannot_join_a_screening_pass(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    extract_next(project, ext_a, PassLabel.A)
    before = _event_count(project)
    with pytest.raises(FactoryValidationError) as e:
        join_pass(project, ext_a, PassLabel.A, stage=FT)
    assert _fields_of(e) == ["session"]
    with pytest.raises(FactoryValidationError) as e2:
        screen_next(project, ext_a, PassLabel.A, stage=FT)
    assert _fields_of(e2) == ["session"]
    assert _event_count(project) == before


def test_audit_sampling_session_cannot_extract(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    protocol = current_protocol(project)
    assert protocol is not None
    relay = ext_a.model_copy(update={"kind": "human", "model": None, "skill": None})
    sampled = ExtractionAuditSampled(
        audit_id="xau_01JZ9Q3K5M7N8P0R2S4T6V8W1C",
        items=(),
        random_seed=1,
        population=0,
        population_digest="sha256:0",
        protocol_id=protocol.protocol_id,
    )
    project.record([project.events.make("extraction.audit_sampled", sampled, relay)])
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, ext_a, PassLabel.A)
    assert _fields_of(e) == ["session"]


def test_extraction_relay_session_cannot_join_a_screening_pass(
    project: Project, agent: Actor, world: list[str]
) -> None:
    protocol = current_protocol(project)
    assert protocol is not None
    fresh = agent.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W1D"})
    relay = fresh.model_copy(update={"kind": "human", "model": None, "skill": None})
    resolved = ExtractionResolved(
        work_id=world[0],
        row_key="rk_0123456789ab",
        field=None,
        choice="a",
        reason="x",
        channel=Channel.MCP,
        protocol_id=protocol.protocol_id,
    )
    project.record([project.events.make("extraction.resolved", resolved, relay)])
    before = _event_count(project)
    with pytest.raises(FactoryValidationError) as e:
        join_pass(project, fresh, PassLabel.A, stage=FT)
    assert _fields_of(e) == ["session"]
    assert _event_count(project) == before
