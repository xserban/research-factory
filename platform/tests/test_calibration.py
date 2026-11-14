"""The screening projection and the calibration set: draw, labels, status (R-20, R-31, R-35)."""

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
    DisagreementResolved,
    Framing,
    PassJoined,
    PassLabel,
    PassOpened,
)
from factory.model.seed import SeedKind
from factory.services.calibration import (
    calibration_status,
    draw_calibration,
    label_calibration,
    worked_examples,
)
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.seeds import SeedRole, all_seeds
from tests.helpers import SESSION, SourcesFor
from tests.screening_helpers import _calibration_setup, _decide, _draw

CALIBRATION_SIZE = 30


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _with_criterion(spec: Any, criterion: Criterion) -> Any:
    criteria = tuple(criterion if c.id == criterion.id else c for c in spec.criteria)
    return spec.model_copy(update={"criteria": criteria})


# --- Calibration set (R-20, R-35) ---


def test_calibration_set_includes_dev_seeds_excludes_held_out_and_examples(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _calibration_setup(project, agent, human, mock_sources)
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
    protocol_id = _calibration_setup(project, agent, human, mock_sources)
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
    _calibration_setup(project, agent, human, mock_sources)
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
    _calibration_setup(project, agent, human, mock_sources)
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
    protocol_id = _calibration_setup(project, agent, human, mock_sources)
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
    _calibration_setup(project, agent, human, mock_sources)
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
    protocol_id = _calibration_setup(project, agent, human, mock_sources)
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
    protocol_id = _calibration_setup(project, agent, human, mock_sources)
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
    protocol_id = _calibration_setup(project, agent, human, mock_sources)
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
        exclusions=1,
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
