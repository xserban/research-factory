"""The screening projection and the calibration set: draw, labels, status (R-20, R-31, R-35)."""

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.protocol import (
    Criterion,
    CriterionEffect,
    ScreeningStage,
    protocol_version,
)
from factory.model.screening import (
    AuditLabelled,
    AuditSampled,
    Channel,
    DecisionRecorded,
    DisagreementResolved,
    Framing,
    PassJoined,
    PassLabel,
    PassOpened,
    ScreeningPhase,
    Verdict,
)
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.services.calibration import (
    calibration_status,
    draw_calibration,
    label_calibration,
    worked_examples,
)
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.search import register_query, run_query
from factory.services.seeds import SeedRole, add_seeds, all_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION, openalex_item, ready_protocol

SourcesFor = Callable[..., Mapping[str, SourceFactory]]

POSITIVES = 6
NEGATIVES = 3
RANDOM_WORKS = 40
CALIBRATION_SIZE = 30


def _work(n: int, *, doi: str, title: str) -> dict[str, Any]:
    return openalex_item(
        title=title, author="Ada Zhou", published="2020-01-01", openalex_id=f"W{n}", doi=doi
    )


def _positive_item(n: int) -> dict[str, Any]:
    return _work(n, doi=f"10.1000/p{n}", title=f"Paper {n}")


def _negative_item(k: int) -> dict[str, Any]:
    return _work(100 + k, doi=f"10.1000/n{k}", title=f"Negative {k}")


def _random_item(k: int) -> dict[str, Any]:
    return _work(200 + k, doi=f"10.1000/r{k}", title=f"Random {k}")


def _setup(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
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


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


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


def _with_criterion(spec: Any, criterion: Criterion) -> Any:
    criteria = tuple(criterion if c.id == criterion.id else c for c in spec.criteria)
    return spec.model_copy(update={"criteria": criteria})


# --- Calibration set (R-20, R-35) ---


def test_calibration_set_includes_dev_seeds_excludes_held_out_and_examples(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    seeds = all_seeds(project)
    held_out = {s.work_id for s in seeds if s.role is SeedRole.HELD_OUT}
    examples = worked_examples(project)
    example_works = {v.work_id for v in examples}
    dev_positives = sorted(
        (s for s in seeds if s.kind is SeedKind.POSITIVE and s.role is not SeedRole.HELD_OUT),
        key=lambda s: s.seed_id,
    )
    negatives = {s.work_id for s in seeds if s.kind is SeedKind.NEGATIVE}

    items = set(_draw(project))

    assert held_out and None not in held_out
    assert [v.seed_id for v in examples if v.kind is SeedKind.POSITIVE] == [
        s.seed_id for s in dev_positives[:2]
    ]
    assert not items & held_out
    assert not items & example_works
    assert {s.work_id for s in dev_positives[2:]} <= items
    assert (negatives - example_works) <= items


def test_calibration_set_size_and_seed_recorded(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    first = _draw(project)
    assert len(first) == CALIBRATION_SIZE

    [event] = [e for e in _events(project) if e.type == "calibration.drawn"]
    assert event.payload["random_seed"] == 11
    assert event.payload["protocol_id"] == protocol_id

    again = draw_calibration(project, project.system_actor(), random_seed=99)
    assert again == first
    assert len([e for e in _events(project) if e.type == "calibration.drawn"]) == 1

    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert _draw(project) == first


# --- Labels (R-35) ---


def test_label_rejects_unknown_work_and_unknown_criterion(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    items = _draw(project)
    held_out = next(s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError):
        label_calibration(project, human, "wrk_unknown", "include", None, Channel.CLI)
    with pytest.raises(FactoryValidationError):
        label_calibration(project, human, str(held_out), "include", None, Channel.CLI)
    with pytest.raises(FactoryValidationError):
        label_calibration(project, human, items[0], "exclude", "EX99", Channel.CLI)
    with pytest.raises(FactoryValidationError):
        label_calibration(project, human, items[0], "exclude", None, Channel.CLI)

    assert len(_events(project)) == before


def test_mcp_label_refused_for_pass_session(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    items = _draw(project)
    joined = PassJoined(pass_label=PassLabel.A, session=SESSION, model="claude-opus-5-5")
    project.record(
        [
            project.events.make(
                "screening.pass_joined",
                joined,
                agent,
                input_blob=project.blobs.put_json({"pass": "A"}),
            )
        ]
    )

    with pytest.raises(FactoryValidationError):
        label_calibration(project, human, items[0], "include", None, Channel.MCP)

    event_id = label_calibration(project, human, items[0], "include", None, Channel.CLI)
    assert event_id.startswith("ev_")


# --- Status and the pass gate (R-31, R-35) ---


@pytest.mark.parametrize(("promoted", "passes"), [(9, True), (8, False)])
def test_calibration_passes_only_above_threshold(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    promoted: int,
    passes: bool,
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    assert len(items) == CALIBRATION_SIZE
    for index, work_id in enumerate(items):
        if index < 10:
            label_calibration(project, human, work_id, "include", None, Channel.CLI)
        else:
            label_calibration(project, human, work_id, "exclude", "EX01", Channel.CLI)
    for index, work_id in enumerate(items):
        if index < 10 and index < promoted:
            _decide(project, agent, work_id, "A", "calibration", "include", None, protocol_id)
        else:
            _decide(project, agent, work_id, "A", "calibration", "exclude", "EX01", protocol_id)

    status = calibration_status(project)

    assert status.drawn == CALIBRATION_SIZE
    assert status.labelled == CALIBRATION_SIZE
    assert status.required is True
    assert status.per_pass["A"].sensitivity == promoted / 10
    assert status.passed["A"] is passes
    assert status.passed["B"] is False


def test_amendment_requires_recalibration(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    items = _draw(project)
    current = current_protocol(project)
    assert current is not None
    old_id = current.protocol_id
    for work_id in items:
        label_calibration(project, human, work_id, "include", None, Channel.CLI)
        _decide(project, agent, work_id, "A", "calibration", "include", None, old_id)
    assert calibration_status(project).passed["A"] is True

    old = current_protocol(project)
    assert old is not None
    loosened = _with_criterion(
        old.spec,
        Criterion(
            id="EX02",
            parent="NG02",
            statement="not topic 2",
            rule="exclude only severe topic two",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
            priority=2,
        ),
    )
    amend_protocol(
        project,
        agent,
        loosened,
        reason="loosen",
        semantic=True,
        effects={"EX02": CriterionEffect.LOOSENED},
    )
    new = current_protocol(project)
    assert new is not None
    assert new.protocol_id == protocol_version(loosened)
    assert calibration_status(project).passed["A"] is False

    for work_id in items:
        _decide(project, agent, work_id, "A", "calibration", "include", None, new.protocol_id)
    assert calibration_status(project).passed["A"] is True


def test_exploratory_calibration_not_required(explore_project: Project) -> None:
    status = calibration_status(explore_project)

    assert status.required is False
    assert status.drawn == 0
    assert status.labelled == 0
    assert status.passed == {"A": True, "B": True}


# --- Projection: determinism and supersession ---


def test_rebuild_determinism_with_screening_events(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    opened = PassOpened(
        pass_label=PassLabel.A,
        framing=Framing.INCLUSION,
        criterion_order="protocol",
        random_seed=1,
        sample=None,
    )
    project.record(
        [
            project.events.make(
                "screening.pass_opened",
                opened,
                project.system_actor(),
            )
        ]
    )
    for work_id in items[:3]:
        label_calibration(project, human, work_id, "include", None, Channel.CLI)
    for work_id in items:
        _decide(project, agent, work_id, "A", "calibration", "include", None, protocol_id)
    _decide(project, agent, "wrk_unknown", "B", "screening", "include", None, protocol_id)
    status = calibration_status(project)

    before = project.index.state_hash()

    assert project.index.rebuild() == before
    assert calibration_status(project) == status


def test_superseded_decision_is_marked_in_the_projection(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    work_id = _draw(project)[0]
    first = _decide(project, agent, work_id, "A", "calibration", "exclude", "EX01", protocol_id)
    second = _decide(
        project,
        agent,
        work_id,
        "A",
        "calibration",
        "include",
        None,
        protocol_id,
        supersedes=first,
    )

    with project.index.connect() as conn:
        rows: dict[str, str | None] = dict(
            conn.execute(text("SELECT decision_id, superseded_by FROM decisions")).all()
        )

    assert rows[first] == second
    assert rows[second] is None


def test_audit_sample_takes_agreed_outcome_from_live_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    agreed, split = _draw(project)[:2]
    _decide(project, agent, agreed, "A", "screening", "include", None, protocol_id)
    _decide(project, agent, agreed, "B", "screening", "include", None, protocol_id)
    _decide(project, agent, split, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, split, "B", "screening", "include", None, protocol_id)
    audit_id = f"aud_{project.ids.ulid()}"
    sampled = AuditSampled(
        audit_id=audit_id,
        work_ids=(agreed, split),
        random_seed=3,
        population=2,
        exclusions=0,
        inclusions=1,
    )
    project.record([project.events.make("audit.sampled", sampled, project.system_actor())])
    label = AuditLabelled(
        audit_id=audit_id,
        work_id=agreed,
        verdict="exclude",
        criterion=f"{protocol_id}:EX01",
        channel=Channel.CLI,
    )
    project.record([project.events.make("audit.labelled", label, human)])
    resolution = DisagreementResolved(
        work_id=split, verdict="include", criterion=None, reason="borderline", channel=Channel.CLI
    )
    project.record([project.events.make("screening.disagreement_resolved", resolution, human)])

    with project.index.connect() as conn:
        items = conn.execute(
            text(
                "SELECT work_id, agreed_verdict, human_verdict FROM audit_items WHERE audit_id = :a"
            ),
            {"a": audit_id},
        ).all()
        resolved = conn.execute(
            text("SELECT verdict FROM resolutions WHERE work_id = :w"), {"w": split}
        ).all()

    by_work = {str(work): (agreed_v, human_v) for work, agreed_v, human_v in items}
    assert by_work[agreed] == ("include", "exclude")
    assert by_work[split] == (None, None)
    assert [str(row[0]) for row in resolved] == ["include"]
