"""Shared helpers and fixtures of the extraction test modules (worlds, actors, rows, schemas)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.extraction import (
    ClaimInput,
    ClaimType,
    EvidenceType,
    ExtractedRowInput,
    FieldInput,
    ReportedIn,
    Strength,
    UnitReferences,
)
from factory.model.fulltext import Route
from factory.model.protocol import (
    ExtractionSchema,
    ProtocolSpec,
    ScreeningStage,
)
from factory.model.screening import (
    PassLabel,
)
from factory.packs.contribution import CONTRIBUTION_V1
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ContributionBatchContent,
    ExtractBatchContent,
    extract_next,
    extract_record,
)
from factory.services.fulltext import fetch_fulltext
from factory.services.protocol import amend_protocol, current_protocol
from tests.document_helpers import ARTICLE, make_registry, run_convert
from tests.fulltext_helpers import _screened_full_text_world
from tests.helpers import SourcesFor
from tests.route_helpers import StubRoute, always, retrieved
from tests.screening_helpers import _spec
from tests.world_cache import snapshot_world

FT = ScreeningStage.FULL_TEXT


FIELDS = ("method_name", "task", "dataset", "split", "metric", "value", "pretraining_data")


KEYS = ("task", "dataset", "split", "metric")


RowsFor = Callable[[str], list[ExtractedRowInput]]


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def ext_b() -> Actor:
    return _extractor(SESSION_B, "claude-sonnet-5-5")


@pytest.fixture
def screened(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    """Full text screened to the end; returns the works whose full-text outcome is INCLUDED."""
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


@snapshot_world
def _declare(
    project: Project,
    agent: Actor,
    fraction: float | None = 1.0,
    fields: tuple[str, ...] = FIELDS,
    keys: tuple[str, ...] = KEYS,
) -> None:
    current = current_protocol(project)
    assert current is not None
    schema = ExtractionSchema(
        pack="ml-benchmark",
        pack_version=1,
        fields=fields,
        comparability_keys=keys,
        dual_extract_sample=fraction,
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"extraction_schema": schema}),
        reason="declare extraction",
        semantic=True,
        effects={},
    )


@pytest.fixture
def world(project: Project, agent: Actor, screened: list[str]) -> list[str]:
    _declare(project, agent)
    return screened


def _r(
    value: str = "1",
    cell: str = "t1.r3.c2",
    *,
    unit: str | None = None,
    task: str = "classification",
    split: str | None = "val",
    reported_in: ReportedIn = ReportedIn.OWN,
    **extra: FieldInput,
) -> ExtractedRowInput:
    fields = {
        "method_name": FieldInput(value="Lorem", anchor="t1.r3.c1", quote="Lorem"),
        "task": FieldInput(value=task),
        "dataset": FieldInput(
            value="Lorem ipsum", anchor="s3.p1", quote="Lorem ipsum dolor sit amet."
        ),
        "metric": FieldInput(value="Low", anchor="t1.r2.c2", quote="Low"),
        "value": FieldInput(
            value=value, unit=unit, anchor="t1", cell=cell, quote=value, reported_in=reported_in
        ),
        **extra,
    }
    if split is not None:
        fields["split"] = FieldInput(value=split)
    return ExtractedRowInput(fields=fields)


def _same_rows(work: str) -> list[ExtractedRowInput]:
    return [_r()]


@snapshot_world
def _run(project: Project, actor: Actor, label: PassLabel, rows_for: RowsFor) -> None:
    """Serve every task of the pass and record `rows_for(work)` in it, closing the unit."""
    for _ in range(100):
        batch = extract_next(project, actor, label).batch
        if batch is None:
            return
        rows = rows_for(batch.records[0]["work_id"])
        res = extract_record(
            project, actor, batch.task_id, rows, finish=True, reason=None if rows else "no result"
        )
        assert res.completed, res.rows.rejected
    raise AssertionError("too many tasks")


def _both(
    project: Project, ext_a: Actor, ext_b: Actor, a: RowsFor = _same_rows, b: RowsFor = _same_rows
) -> None:
    _run(project, ext_a, PassLabel.A, a)
    _run(project, ext_b, PassLabel.B, b)


LATENCY_FIELDS = ("method_name", "task", "dataset", "split", "metric", "value", "latency")


SESSION_A = "01JZ9Q3K5M7N8P0R2S4T6V8W1A"


SESSION_B = "01JZ9Q3K5M7N8P0R2S4T6V8W1B"


def _extractor(session: str, model: str) -> Actor:
    return Actor(
        kind="agent",
        id="extractor",
        user="obd",
        session=session,
        model=model,
        skill="rf-extract@1a2b3c4d",
    )


@snapshot_world
def _declare_latency(project: Project, agent: Actor, fraction: float | None) -> None:
    current = current_protocol(project)
    assert current is not None
    schema = ExtractionSchema(
        pack="ml-benchmark",
        pack_version=1,
        fields=LATENCY_FIELDS,
        comparability_keys=("task", "dataset", "metric"),
        dual_extract_sample=fraction,
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"extraction_schema": schema}),
        reason="declare extraction",
        semantic=True,
        effects={},
    )


PINNED_P_ID = "P@1e7c316e"  # pilot_protocol_spec("Q@aaaaaaaa", "prb_1") before extraction_schema


LATENCY_KEYS = ("task", "dataset", "metric")


def _schema(**kw: Any) -> ExtractionSchema:
    base: dict[str, Any] = {
        "pack": "ml-benchmark",
        "pack_version": 1,
        "fields": LATENCY_FIELDS,
        "comparability_keys": LATENCY_KEYS,
        "dual_extract_sample": 0.5,
    }
    base.update(kw)
    return ExtractionSchema.model_validate(base)


def _with(schema: ExtractionSchema | None) -> ProtocolSpec:
    return _spec(extraction_schema=schema)


def _row(value: str = "1", cell: str = "t1.r3.c2", **extra: FieldInput) -> ExtractedRowInput:
    fields = {
        "method_name": FieldInput(value="Lorem", anchor="t1.r3.c1", quote="Lorem"),
        "task": FieldInput(value="classification"),
        "dataset": FieldInput(
            value="Lorem ipsum", anchor="s3.p1", quote="Lorem ipsum dolor sit amet."
        ),
        "metric": FieldInput(value="Low", anchor="t1.r2.c2", quote="Low"),
        "value": FieldInput(value=value, anchor="t1", cell=cell, quote=value),
        **extra,
    }
    return ExtractedRowInput(fields=fields)


def _claim(**over: str) -> ClaimInput:
    values = {
        "statement": "The method is described in the method section.",
        "claim_type": ClaimType.FINDING,
        "evidence_type": EvidenceType.EXPERIMENT,
        "strength": Strength.MODERATE,
        "anchor": "s3.p1",
        "quote": "Lorem ipsum dolor sit amet.",
        **over,
    }
    return ClaimInput.model_validate(values)


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _amend_schema(project: Project, agent: Actor, **update: object) -> str:
    current = current_protocol(project)
    assert current is not None and current.spec.extraction_schema is not None
    schema = current.spec.extraction_schema.model_copy(update=update)
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"extraction_schema": schema}),
        reason="amend the extraction schema",
        semantic=True,
        effects={},
    )
    amended = current_protocol(project)
    assert amended is not None
    return amended.protocol_id


def _new_document_version(project: Project, work: str) -> str:
    """Fetch a new arXiv HTML version of `work` (superseding its document) and convert it."""
    route = StubRoute(
        Route.ARXIV_HTML,
        always(retrieved(Route.ARXIV_HTML, ARTICLE + b"<!-- v3 -->", version="v3")),
    )
    fetch_fulltext(
        project, routes={Route.ARXIV_HTML: route}, work_ids=[work], only=[Route.ARXIV_HTML]
    )
    run_convert(project, make_registry())
    current = default_conversion(project, work)
    assert current is not None
    return current.document_id


SESSION_C = "01JZ9Q3K5M7N8P0R2S4T6V8W1C"


SESSION_D = "01JZ9Q3K5M7N8P0R2S4T6V8W1D"


QUOTE = "Lorem ipsum dolor sit amet."


CONTRIB_FIELDS = tuple(f.name for f in CONTRIBUTION_V1.fields)


@pytest.fixture
def ctr_a() -> Actor:
    return _extractor(SESSION_C, "claude-opus-5-5")


@pytest.fixture
def ctr_b() -> Actor:
    return _extractor(SESSION_D, "claude-sonnet-5-5")


def _schemas() -> tuple[ExtractionSchema, ExtractionSchema]:
    evidence = ExtractionSchema(
        pack="ml-benchmark",
        pack_version=1,
        fields=LATENCY_FIELDS,
        comparability_keys=("task", "dataset", "metric"),
        dual_extract_sample=1.0,
    )
    contribution = ExtractionSchema(
        pack="contribution",
        pack_version=1,
        fields=CONTRIB_FIELDS,
        dual_extract_sample=1.0,
        claims=False,
    )
    return evidence, contribution


def _declare_both(project: Project, agent: Actor) -> None:
    current = current_protocol(project)
    assert current is not None
    evidence, contribution = _schemas()
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(
            update={"extraction_schema": evidence, "contribution_schema": contribution}
        ),
        reason="declare both schemas",
        semantic=True,
        effects={},
    )


@pytest.fixture(name="world")
def scope_world(project: Project, agent: Actor, screened: list[str]) -> list[str]:
    _declare_both(project, agent)
    return screened


def add_refs(project: Project, content: ExtractBatchContent) -> ExtractBatchContent:
    """The content hook G2-B supplies: here a fixed reference list and one item rule."""
    return ContributionBatchContent(
        **content.model_dump(),
        references=UnitReferences(status="none", extraction_id=None, entries=[]),
        item_rules=["a not-stated item names absent_kind and nothing else"],
    )


def _item(
    kind: str = "base-idea", name: str | None = "Lorem", **extra: FieldInput
) -> ExtractedRowInput:
    fields: dict[str, FieldInput] = {
        "item_kind": FieldInput(value=kind),
        "statement": FieldInput(value=QUOTE, anchor="s3.p1", quote=QUOTE),
    }
    if name is not None:
        fields["name"] = FieldInput(value=name, anchor="s3.p1", quote=QUOTE)
    fields.update(extra)
    return ExtractedRowInput(fields=fields)


PROTOCOL = "P@1a2b3c4d"


WORK = "rf:jones2021-sparse-1e2f3a4b"


TASK = "tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


CNV = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


ROW = "rk_0123456789ab"


MODEL = "claude-opus-5-5"


def _agent(project: Project) -> Actor:
    return Actor(
        kind="agent",
        id="extractor",
        user="obd",
        session=project.session,
        model=MODEL,
        skill="rf-extract@1a2b3c4d",
    )


def _record(project: Project, type_: str, payload: Any, *, agent: bool = False) -> Event:
    if agent:
        blob = project.blobs.put(b"instruction")
        event = project.events.make(type_, payload, _agent(project), input_blob=blob)
    else:
        event = project.events.make(type_, payload, project.system_actor())
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]
