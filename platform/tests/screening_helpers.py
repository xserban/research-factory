"""Shared screening, calibration, chase, protocol-rule and index test helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.errors import ValidationIssue
from factory.events.catalog import EventCatalog, EventType
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.index.index import Index
from factory.index.projection import Projection, core_tables
from factory.model.project import RigorMode
from factory.model.protocol import (
    Criterion,
    CriterionEffect,
    Limit,
    MethodProfile,
    PlannedQuery,
    ProtocolSpec,
    Reviewer,
    ScreeningPlan,
    ScreeningStage,
    SourcePlan,
    protocol_version,
)
from factory.model.question import NonGoal, QuestionSpec, Slot, question_version
from factory.model.screening import (
    Channel,
    DecisionRecorded,
    PassLabel,
    ScreeningItem,
    ScreeningPhase,
    Verdict,
)
from factory.model.search import (
    QueryKind,
    QuerySpec,
)
from factory.model.seed import SeedKind, SeedSpec
from factory.services.calibration import (
    calibration_items,
    draw_calibration,
    label_calibration,
)
from factory.services.context import Project
from factory.services.protocol import (
    amend_protocol,
    current_protocol,
)
from factory.services.protocol_rules import ProtocolCheck, protocol_issues
from factory.services.question import QuestionVersion
from factory.services.screening import (
    SCREEN_BATCH,
    ScreenBatch,
    open_pass,
    pass_b_sample,
    screen_next,
)
from factory.services.search import list_works, register_query, run_query
from factory.services.seeds import (
    SeedRecord,
    SeedRole,
    add_seeds,
    all_seeds,
)
from factory.services.tasks import (
    complete_task,
)
from tests.helpers import (
    Demo,
    SourcesFor,
    _negative_item,
    _of_type,
    _positive_item,
    _protocol,
    _random_item,
    _setup,
    openalex_item,
    ready_protocol,
)


def decide(
    project: Project,
    actor: Actor,
    work_id: str,
    protocol_id: str,
    verdict: str,
    *,
    pass_label: PassLabel = PassLabel.A,
    criterion: str | None = None,
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT,
    supersedes: str | None = None,
) -> str:
    """Write one screening-phase decision event directly; return its id."""
    decision_id = f"dec_{project.ids.ulid()}"
    payload = DecisionRecorded(
        decision_id=decision_id,
        work_id=work_id,
        pass_label=pass_label,
        phase=ScreeningPhase.SCREENING,
        stage=stage,
        verdict=Verdict(verdict),
        criterion=None if criterion is None else f"{protocol_id}:{criterion}",
        quote="Paper",
        rationale="rationale",
        protocol_id=protocol_id,
        task_id="tsk_test",
        supersedes=supersedes,
    )
    blob = project.blobs.put_json({"work_id": work_id, "verdict": verdict})
    project.record(
        [
            project.events.make(
                "screening.decision_recorded", payload, actor, refs=(decision_id,), input_blob=blob
            )
        ]
    )
    return decision_id


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _serve_calibration(project: Project, agent: Actor, count: int) -> list[Any]:
    """Claim and complete `count` calibration batches, as a screener would."""
    batches = []
    for _ in range(count):
        result = screen_next(project, agent, PassLabel.A)
        assert result.batch is not None
        assert result.batch.phase is ScreeningPhase.CALIBRATION
        complete_task(project, agent, result.batch.task_id)
        batches.append(result.batch)
    return batches


def _late(project: Project, human: Actor, mock_sources: SourcesFor, first: int, count: int) -> None:
    """Add `count` works to the corpus after the passes are open, through a new query."""
    sources = mock_sources(openalex=[_random_item(k) for k in range(first, first + count)])
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)


def _queued(project: Project, protocol_id: str) -> set[str]:
    """Every work id named in a task created under one protocol version."""
    works: set[str] = set()
    for event in _of_type(project, "task.created"):
        assert event.input_blob is not None
        content: Any = project.blobs.get_json(event.input_blob)
        if content.get("protocol_id") == protocol_id:
            works.update(record["work_id"] for record in content["records"])
    return works


def _loosen_ex01(project: Project, agent: Actor) -> str:
    """Amend the current protocol so that EX01 is loosened; returns the new version id."""
    current = current_protocol(project)
    assert current is not None
    criteria = tuple(
        Criterion(
            id="EX01",
            parent="NG01",
            statement="not topic 1",
            rule="exclude only severe topic one",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
            priority=1,
        )
        if c.id == "EX01"
        else c
        for c in current.spec.criteria
    )
    loosened = current.spec.model_copy(update={"criteria": criteria})
    amend_protocol(
        project,
        agent,
        loosened,
        reason="loosen EX01",
        semantic=True,
        effects={"EX01": CriterionEffect.LOOSENED},
    )
    return protocol_version(loosened)


def _pass_calibration_under(
    project: Project, agent: Actor, human: Actor, protocol_id: str
) -> list[str]:
    """Label every calibration item include and decide it include under `protocol_id`."""
    items = calibration_items(project)
    for item in items:
        label_calibration(project, human, item, "include", None, Channel.CLI)
        _decide(project, agent, item, "A", "calibration", "include", None, protocol_id)
    return items


def _citing(n: int) -> dict[str, Any]:
    return openalex_item(
        title=f"Citing {n}",
        author="Cai Wu",
        published="2024-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/c{n}",
    )


def _corpus(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    extra: Sequence[dict[str, Any]] = (),
) -> str:
    """A ready pilot protocol, its seeded corpus, the calibration set and both passes opened.

    `extra` records are added to the corpus through the planned query before the draw.
    """
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    if extra:
        spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
        query_id = register_query(project, human, spec, sources=mock_sources(openalex=list(extra)))
        run_query(project, query_id, sources=mock_sources(openalex=list(extra)))
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    return protocol_id


def _settle(
    project: Project,
    agent: Actor,
    human: Actor,
    protocol_id: str,
    *,
    verdict: str = "include",
    leave: str | None = None,
) -> None:
    """Decide every corpus work the same way in both passes, and label every calibration work.

    `leave` names one ordinary work to leave undecided.
    """
    calibration = set(calibration_items(project))
    criterion = "EX01" if verdict == "exclude" else None
    for work in sorted(w.id for w in list_works(project)):
        if work == leave:
            continue
        if work in calibration:
            label_calibration(project, human, work, verdict, criterion, Channel.CLI)
            continue
        _decide(project, agent, work, "A", "screening", verdict, criterion, protocol_id)
        _decide(project, agent, work, "B", "screening", verdict, criterion, protocol_id)


def _ordinary(project: Project) -> list[str]:
    calibration = set(calibration_items(project))
    return sorted(w.id for w in list_works(project) if w.id not in calibration)


def _batch(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> ScreenBatch:
    """An ordinary pass A batch held by the agent, served once the calibration gate has passed."""
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    _serve_calibration(project, agent, math.ceil(len(items) / SCREEN_BATCH))
    _pass_calibration_under(project, agent, human, protocol_id)
    batch = screen_next(project, agent, PassLabel.A).batch
    assert batch is not None
    assert batch.phase is ScreeningPhase.SCREENING
    assert len(batch.records) >= 3
    return batch


def _item(
    record: Mapping[str, Any],
    verdict: Verdict = Verdict.INCLUDE,
    criterion: str | None = None,
    quote: str | None = None,
) -> ScreeningItem:
    return ScreeningItem(
        work_id=str(record["work_id"]),
        verdict=verdict,
        criterion=criterion,
        quote=str(record["title"]) if quote is None else quote,
        rationale="it fits",
    )


MERGE_TITLE = "Linear attention in transformers"


def _merge_items() -> list[dict[str, Any]]:
    """Two records of one paper: one with a DOI, one without. The cascade merges them by title,
    first author and year."""
    return [
        openalex_item(
            title=MERGE_TITLE,
            author="Ada Zhou",
            published="2021-06-01",
            openalex_id="W500",
            doi="10.1000/merge",
        ),
        openalex_item(
            title=MERGE_TITLE, author="Ada Zhou", published="2021-06-01", openalex_id="W501"
        ),
    ]


# The same paper, published and as a preprint: one cascade merge (title + first author + year).
PUBLISHED: dict[str, Any] = {
    "title": "Linear attention in transformers",
    "authors": ["Ada Zhou"],
    "year": 2024,
    "doi": "10.1000/x",
    "type": "journal-article",
}


PREPRINT: dict[str, Any] = {
    "title": "Linear attention in transformers",
    "authors": ["Ada Zhou"],
    "year": 2024,
    "arxiv": "2301.00001",
    "type": "preprint",
}


# A third record of the same paper, under an OpenAlex id only.
OPENALEX_COPY: dict[str, Any] = {
    "title": "Linear attention in transformers",
    "authors": ["Ada Zhou"],
    "year": 2024,
    "openalex": "W2001",
}


def _ingest(project: Project, fake_sources: SourcesFor, pages: list[list[dict[str, Any]]]) -> None:
    sources = fake_sources(pages=pages)
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="linear attention")
    qid = register_query(project, project.human_actor(), spec, sources=sources)
    run_query(project, qid, sources=sources)


def demo_catalog() -> EventCatalog:
    catalog = EventCatalog()
    catalog.register(EventType("demo.recorded", Demo, 1))
    # Registered without a handler: its events must still get an `events` row.
    catalog.register(EventType("demo.noted", Demo, 1))
    return catalog


def demo_projection(version: str = "t1") -> Projection:
    metadata = MetaData()
    core_tables(metadata)
    totals = Table(
        "demo_totals",
        metadata,
        Column("key", String, primary_key=True),
        Column("total", Integer, nullable=False),
    )

    def record(conn: Connection, event: Event) -> None:
        n = event.payload["n"]
        assert isinstance(n, int)
        conn.execute(
            sqlite_insert(totals)
            .values(key="all", total=n)
            .on_conflict_do_update(index_elements=["key"], set_={"total": totals.c.total + n})
        )

    return Projection(version=version, metadata=metadata, handlers={"demo.recorded": record})


def make_index(project_dir: Path, version: str = "t1") -> Index:
    return Index(
        project_dir / ".index" / "factory.sqlite",
        project_dir / "events",
        demo_catalog(),
        demo_projection(version),
    )


SEED_DOI = "10.1000/p7"


def _calibrate(project: Project, agent: Actor, human: Actor, protocol_id: str) -> None:
    """Label every calibration work and decide it the same way in both passes (sensitivity 1)."""
    for work in calibration_items(project):
        label_calibration(project, human, work, "include", None, Channel.CLI)
        _decide(project, agent, work, "A", "calibration", "include", None, protocol_id)
        _decide(project, agent, work, "B", "calibration", "include", None, protocol_id)


def _screen_ordinary(
    project: Project,
    agent: Actor,
    protocol_id: str,
    *,
    pass_a: str = "include",
    pass_b: str = "include",
    b_sample_only: bool = False,
) -> None:
    """Decide the ordinary works in pass A, and in pass B: all of them, or its sample only."""
    sample = set(pass_b_sample(project) or ())
    for work in _ordinary(project):
        _decide(project, agent, work, "A", "screening", pass_a, _cite(pass_a), protocol_id)
        if b_sample_only and work not in sample:
            continue
        _decide(project, agent, work, "B", "screening", pass_b, _cite(pass_b), protocol_id)


def _partial_corpus(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
    """As `test_chase_service._corpus`, with a dual sample of 0.3: pass B screens a part of the
    ordinary works, so some works are decided by pass A alone (and some by both)."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.3, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    return protocol_id


def _cite(verdict: str) -> str | None:
    """The criterion an exclusion must name; no criterion for any other verdict."""
    return "EX01" if verdict == "exclude" else None


def _unfound_seed(project: Project, agent: Actor, mock_sources: SourcesFor) -> str:
    """Add a positive seed whose lookup finds no work; returns its id."""
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 7", doi=SEED_DOI)
    result = add_seeds(project, agent, [spec], sources=mock_sources(openalex=[]))
    [outcome] = result.written
    return outcome.seed_id


def _held_out_tokens(project: Project) -> set[str]:
    """The seed id and every stated or normalised identifier of each held-out seed."""
    tokens: set[str] = set()
    for seed in all_seeds(project):
        if seed.role is not SeedRole.HELD_OUT:
            continue
        stated = SeedSpec(kind=seed.kind, cite=seed.cite, doi=seed.doi, arxiv=seed.arxiv)
        tokens.add(seed.seed_id)
        tokens.update(stated.identity_keys().values())
        tokens.update(v for v in (seed.doi, seed.arxiv, seed.openalex) if v)
    return tokens


def _corpus_missing_held_out(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[str, str, int]:
    """A pilot corpus whose base search lacks one held-out positive seed, resolved by lookup.

    Returns the protocol id, the held-out seed's id and its paper number. The seed's work is
    stored by the seed lookup only (a probe), so it is not in the corpus: `seed_check` says
    `missing` until something else retrieves it."""
    protocol_id = _protocol(project, agent, human, mock_sources, dual_sample=0.5)
    [held] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    number = int(held.cite.split()[-1])
    items = [_positive_item(n) for n in (1, 2, 3) if n != number]
    items += [_negative_item(k) for k in range(1, 4)]
    items += [_random_item(k) for k in range(1, 5)]
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    sources = mock_sources(openalex=items)
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    return protocol_id, held.seed_id, number


QUESTION_SPEC = QuestionSpec(
    scheme="PICO",
    primary_question="Do remote workers report higher focus?",
    slots=(
        Slot(name="population", value="knowledge workers"),
        Slot(name="setting", open="?", resolve_in="stage 2"),
    ),
    non_goals=(NonGoal(id="NG01", text="gig platforms"), NonGoal(id="NG02", text="teams")),
)


QID = question_version(QUESTION_SPEC)


QUESTION = QuestionVersion(
    question_id=QID,
    spec=QUESTION_SPEC,
    supersedes=None,
    reason=None,
    recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
)


PROBES: dict[str, set[str]] = {"prb_1": {"openalex"}}


KNOWN_SOURCES = {"openalex", "arxiv"}


def _in(cid: str = "IN01", parent: str | None = "slot:population", **kw: object) -> Criterion:
    base: dict[str, object] = {
        "id": cid,
        "parent": parent,
        "statement": "adults",
        "rule": "include adults",
        "applies_at": ScreeningStage.TITLE_ABSTRACT,
    }
    base.update(kw)
    return Criterion.model_validate(base)


def _ex(cid: str = "EX01", parent: str | None = "NG01", priority: int = 1) -> Criterion:
    return Criterion.model_validate(
        {
            "id": cid,
            "parent": parent,
            "statement": "gig work",
            "rule": "exclude gig work",
            "applies_at": ScreeningStage.TITLE_ABSTRACT,
            "priority": priority,
        }
    )


def _reviewer(role: str = "reviewer-of-record", kind: str = "human") -> Reviewer:
    return Reviewer.model_validate({"role": role, "actor": "ana", "kind": kind})


def _screening(**kw: object) -> ScreeningPlan:
    base: dict[str, object] = {
        "passes": 2,
        "dual_sample": 0.5,
        "kappa_floor": 0.7,
        "reviewers": (_reviewer(),),
    }
    base.update(kw)
    return ScreeningPlan.model_validate(base)


def _spec(**kw: object) -> ProtocolSpec:
    base: dict[str, object] = {
        "question_id": QID,
        "method_profile": MethodProfile.SYSTEMATIC_REVIEW,
        "criteria": (_in(), _ex(), _ex("EX02", "NG02", priority=2)),
        "sources": (SourcePlan(name="openalex", included=True, probe_id="prb_1"),),
        "queries": (PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="remote focus"),),
        "limits": (Limit(field="year", value="2015"),),
        "screening": _screening(),
    }
    base.update(kw)
    return ProtocolSpec.model_validate(base)


def _check(
    spec: ProtocolSpec,
    mode: RigorMode = RigorMode.PILOT,
    *,
    seeds: Sequence[SeedRecord] = (),
    current: str = QID,
    question: QuestionVersion = QUESTION,
) -> ProtocolCheck:
    return protocol_issues(
        spec,
        question=question,
        current_question_id=current,
        mode=mode,
        seeds=list(seeds),
        probes=PROBES,
        known_sources=KNOWN_SOURCES,
    )


def _fields(issues: list[ValidationIssue]) -> list[str]:
    return [issue.field for issue in issues]


POSITIVES = 6


NEGATIVES = 3


RANDOM_WORKS = 40


def _calibration_setup(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> str:
    """A ready pilot protocol, six positive and three negative seeds, and a corpus of every seed
    work plus random works. The probe of `ready_protocol` draws the hold-out split over the first
    three positives; the later positives are late, and count as development. Returns the protocol
    id."""
    protocol_id = ready_protocol(project, agent, human, mock_sources)
    for n in range(4, POSITIVES + 1):
        spec = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
        add_seeds(project, agent, [spec], sources=mock_sources(openalex=[_positive_item(n)]))
    for k in range(1, NEGATIVES + 1):
        spec = SeedSpec(kind=SeedKind.NEGATIVE, cite=f"Negative {k}", doi=f"10.1000/n{k}")
        add_seeds(project, agent, [spec], sources=mock_sources(openalex=[_negative_item(k)]))
    items = [_positive_item(n) for n in range(1, POSITIVES + 1)]
    items += [_negative_item(k) for k in range(1, NEGATIVES + 1)]
    items += [_random_item(k) for k in range(1, RANDOM_WORKS + 1)]
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    sources = mock_sources(openalex=items)
    query_id = register_query(project, human, query, sources=sources)
    run_query(project, query_id, sources=sources)
    return protocol_id


def _draw(project: Project) -> list[str]:
    return draw_calibration(project, project.system_actor(), random_seed=11)


def _decide(
    project: Project,
    agent: Actor,
    work_id: str,
    pass_label: str,
    phase: str,
    verdict: str,
    criterion: str | None,
    protocol_id: str,
    *,
    supersedes: str | None = None,
) -> str:
    """Write one decision event directly (screen_record arrives in a later task)."""
    decision_id = f"dec_{project.ids.ulid()}"
    payload = DecisionRecorded(
        decision_id=decision_id,
        work_id=work_id,
        pass_label=PassLabel(pass_label),
        phase=ScreeningPhase(phase),
        stage=ScreeningStage.TITLE_ABSTRACT,
        verdict=Verdict(verdict),
        criterion=None if criterion is None else f"{protocol_id}:{criterion}",
        quote="Paper",
        rationale="rationale",
        protocol_id=protocol_id,
        task_id="tsk_test",
        supersedes=supersedes,
    )
    blob = project.blobs.put_json({"work_id": work_id, "verdict": verdict})
    project.record(
        [
            project.events.make(
                "screening.decision_recorded",
                payload,
                agent,
                refs=(decision_id,),
                input_blob=blob,
            )
        ]
    )
    return decision_id
