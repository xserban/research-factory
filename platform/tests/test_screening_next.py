"""Passes bound to sessions, and screen_next with the calibration gate (R-16, R-20, R-35)."""

import math
import re
import secrets
from typing import cast

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.chase import extended_works
from factory.model.screening import (
    Channel,
    Framing,
    PassLabel,
    ScreeningPhase,
)
from factory.model.seed import SeedKind
from factory.services.calibration import calibration_items, label_calibration
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.screening import (
    SCREEN_BATCH,
    _extend_sample,
    join_pass,
    live_decisions,
    obsolete_tasks,
    open_pass,
    pass_b_sample,
    screen_next,
)
from factory.services.search import list_works
from factory.services.seeds import SeedRole, all_seeds
from factory.services.tasks import task_counts
from tests.helpers import (
    SESSION,
    SourcesFor,
    _of_type,
    _protocol,
    _setup,
)
from tests.screening_helpers import (
    _decide,
    _draw,
    _events,
    _late,
    _loosen_ex01,
    _pass_calibration_under,
    _queued,
    _serve_calibration,
)


def test_open_does_not_redraw_unsampled_works(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5)
    _draw(project)
    open_pass(project, agent, PassLabel.B)
    assert len(_of_type(project, "screening.sample_extended")) == 1
    screen_next(project, agent, PassLabel.B)
    assert len(_of_type(project, "screening.sample_extended")) == 1
    with project.index.connect() as conn:
        assert extended_works(conn) == set()


def test_new_work_after_open_is_considered_once(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5)
    _draw(project)
    open_pass(project, agent, PassLabel.B)
    _late(project, human, mock_sources, 1000, 20)
    screen_next(project, agent, PassLabel.B)
    screen_next(project, agent, PassLabel.B)
    # One record at open, one draw over the late works, and no third.
    assert len(_of_type(project, "screening.sample_extended")) == 2


def test_extension_respects_fraction(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.B)
    _late(project, human, mock_sources, 1000, 200)
    project.index.sync()
    drawn = _extend_sample(project, agent, random_seed=7)
    assert drawn is not None
    event, added = drawn
    considered = cast(list[str], event.payload["considered"])
    assert len(considered) == 200  # the late works only, not the open remainder
    assert 70 <= len(added) <= 130
    replay = _extend_sample(project, agent, random_seed=7)
    assert replay is not None and replay[1] == added


def test_full_dual_coding_writes_no_extension(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    # The pilot protocol requires a dual sample; 1.0 is the full-coverage case (no sample).
    _setup(project, agent, human, mock_sources, dual_sample=1.0)
    _draw(project)
    open_pass(project, agent, PassLabel.B)
    _late(project, human, mock_sources, 1000, 20)
    screen_next(project, agent, PassLabel.B)
    assert _of_type(project, "screening.sample_extended") == []
    assert pass_b_sample(project) is None


# --- Protocol and pass gates (R-16, ruling 1) ---


def test_screen_next_refused_until_protocol_ready(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    before = len(_events(project))
    result = screen_next(project, agent, PassLabel.A)
    assert result.batch is None
    assert result.blocked and "ready" in result.blocked[0]
    assert len(_events(project)) == before

    _protocol(project, agent, human, mock_sources, ready=False)
    draft = screen_next(project, agent, PassLabel.A)
    assert draft.batch is None
    assert draft.blocked and "ready" in draft.blocked[0]
    assert _of_type(project, "screening.pass_opened") == []


def test_session_cannot_join_both_passes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    join_pass(project, agent, PassLabel.A)
    join_pass(project, agent, PassLabel.A)
    with pytest.raises(FactoryValidationError):
        join_pass(project, agent, PassLabel.B)

    joined = _of_type(project, "screening.pass_joined")
    assert [e.payload["pass_label"] for e in joined] == ["A"]
    assert _of_type(project, "screening.pass_opened") == []


def test_label_session_cannot_join_pass(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    item = _draw(project)[0]
    label_calibration(project, human, item, "include", None, Channel.MCP)

    with pytest.raises(FactoryValidationError):
        join_pass(project, agent, PassLabel.A)
    assert _of_type(project, "screening.pass_joined") == []


# --- Passes: framing, criterion order, sample ---


def test_pass_b_reverses_criterion_order_and_uses_exclusion_framing(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    agent_other = agent_other.model_copy(update={"model": "claude-sonnet-5-0"})

    batch_a = screen_next(project, agent_other, PassLabel.A).batch
    batch_b = screen_next(project, agent, PassLabel.B).batch
    assert batch_a is not None and batch_b is not None
    assert batch_a.framing is Framing.INCLUSION
    assert batch_b.framing is Framing.EXCLUSION
    assert [c["id"] for c in batch_a.criteria] == ["IN01", "EX01", "EX02", "EX03"]
    assert [c["id"] for c in batch_b.criteria] == ["EX03", "EX02", "EX01", "IN01"]
    assert batch_b.instructions.startswith("For each record look for a reason to exclude")
    assert "Quote the title or abstract span" in batch_b.instructions

    [opened_b] = [
        e for e in _of_type(project, "screening.pass_opened") if e.payload["pass_label"] == "B"
    ]
    assert opened_b.payload["criterion_order"] == "reversed"
    assert opened_b.payload["framing"] == "exclusion"


def test_pass_b_sample_respects_dual_sample(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.2, random_works=41)
    items = _draw(project)
    corpus = [w.id for w in list_works(project)]

    open_pass(project, agent, PassLabel.B)
    [opened] = _of_type(project, "screening.pass_opened")
    sample = opened.payload["sample"]
    assert isinstance(sample, list)
    assert len(sample) == math.ceil(0.2 * len(corpus)) + len(items)
    assert set(items) <= set(sample)
    assert set(sample) <= set(corpus)


def test_pass_a_covers_the_whole_corpus(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.A)
    opened = _of_type(project, "screening.pass_opened")
    assert len(opened) == 1
    assert opened[0].payload["sample"] is None


# --- Calibration gate (R-20, R-31, R-35) ---


def test_calibration_not_drawn_blocks_screening(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    result = screen_next(project, agent, PassLabel.A)
    assert result.batch is None
    assert result.blocked and "drawn" in result.blocked[0] and "labelled" in result.blocked[0]
    assert _of_type(project, "screening.pass_opened") == []
    assert _of_type(project, "task.created") == []


def test_calibration_batches_served_first_and_block_ordinary_batches(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    items = set(_draw(project))

    results = [screen_next(project, agent, PassLabel.A) for _ in range(3)]
    assert sum(len(r.batch.records) for r in results if r.batch) == len(items)
    for result in results:
        assert result.batch is not None
        assert result.batch.phase is ScreeningPhase.CALIBRATION
        assert {r["work_id"] for r in result.batch.records} <= items
        assert result.blocked and "labelled" in result.blocked[0]

    blocked = screen_next(project, agent, PassLabel.A)
    assert blocked.batch is None
    assert blocked.blocked and "labelled" in blocked.blocked[0]
    assert task_counts(project).open > 0


def test_ordinary_batches_follow_a_passed_calibration(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    _serve_calibration(project, agent, math.ceil(len(items) / SCREEN_BATCH))
    for item in items:
        label_calibration(project, human, item, "include", None, Channel.CLI)
        _decide(project, agent, item, "A", "calibration", "include", None, protocol_id)

    result = screen_next(project, agent, PassLabel.A)
    assert result.batch is not None
    assert result.batch.phase is ScreeningPhase.SCREENING
    assert not {r["work_id"] for r in result.batch.records} & set(items)
    assert result.blocked == []


def test_worked_examples_are_development_seeds_without_ids(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    batch = screen_next(project, agent, PassLabel.A).batch
    assert batch is not None

    held_ids = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT}
    held_titles = {w.title for w in list_works(project) if w.id in held_ids}
    expected = [e["expected"] for e in batch.worked_examples]
    assert expected == ["include", "include", "exclude", "exclude"]
    dev = [s for s in all_seeds(project) if s.role is not SeedRole.HELD_OUT and s.work_id]
    by_id = {w.id: w.title for w in list_works(project)}
    first_positives = sorted(
        (s for s in dev if s.kind is SeedKind.POSITIVE), key=lambda s: s.seed_id
    )[:2]
    first_negatives = sorted(
        (s for s in dev if s.kind is SeedKind.NEGATIVE), key=lambda s: s.seed_id
    )[:2]
    titles = {e["title"] for e in batch.worked_examples}
    assert titles == {by_id[s.work_id or ""] for s in [*first_positives, *first_negatives]}
    assert not titles & held_titles
    dumped = batch.model_dump_json()
    assert "SEED" not in dumped and "NEG" not in dumped


def test_batch_order_is_randomised_and_reproducible(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secrets, "randbits", lambda bits: 7)
    _setup(project, agent, human, mock_sources)
    _draw(project)
    first = screen_next(project, agent, PassLabel.A).batch
    assert first is not None

    twin = init_project(settings, "twin", "pilot", session=SESSION, clock=clock)
    _setup(twin, agent, human, mock_sources)
    _draw(twin)
    second = screen_next(twin, agent, PassLabel.A).batch
    assert second is not None

    ids = [str(r["work_id"]) for r in first.records]
    assert ids == [r["work_id"] for r in second.records]
    assert ids != sorted(ids)


def test_task_content_is_input_blob(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    batch = screen_next(project, agent, PassLabel.A).batch
    assert batch is not None

    [claimed] = [e for e in _of_type(project, "task.claimed") if e.refs == (batch.task_id,)]
    assert claimed.input_blob is not None
    assert project.blobs.get_json(claimed.input_blob) == batch.model_dump(
        mode="json", exclude={"task_id"}
    )


def test_no_decision_of_other_pass_in_batch(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    decided = [
        _decide(project, agent, item, "A", "calibration", "exclude", "EX01", protocol_id)
        for item in items
    ]
    batch = screen_next(project, agent, PassLabel.B).batch
    assert batch is not None

    dumped = batch.model_dump_json()
    assert not any(decision_id in dumped for decision_id in decided)
    assert "verdict" not in dumped and "rationale" not in dumped
    assert len(live_decisions(project, PassLabel.A)) == len(items)
    assert live_decisions(project, PassLabel.B) == []


def test_calibration_items_are_public(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    assert calibration_items(project) == []
    items = _draw(project)
    assert calibration_items(project) == items


def test_sensitivity_below_threshold_is_named_in_blocked(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    for item in items:
        label_calibration(project, human, item, "include", None, Channel.CLI)
    for index, item in enumerate(items):
        if index < 10:
            _decide(project, agent, item, "A", "calibration", "include", None, protocol_id)
        else:
            _decide(project, agent, item, "A", "calibration", "exclude", "EX01", protocol_id)

    result = screen_next(project, agent, PassLabel.A)
    assert result.batch is None
    assert any("sensitivity" in reason and "threshold" in reason for reason in result.blocked)
    assert not any(re.search(r"\d\.\d", reason) for reason in result.blocked), result.blocked


def test_amendment_requeues_open_tasks_under_the_new_version(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    _serve_calibration(project, agent, math.ceil(len(items) / SCREEN_BATCH))
    _pass_calibration_under(project, agent, human, protocol_id)

    stale_batch = screen_next(project, agent, PassLabel.A).batch
    assert stale_batch is not None
    assert stale_batch.phase is ScreeningPhase.SCREENING
    old_works = {r["work_id"] for r in stale_batch.records}

    new_id = _loosen_ex01(project, agent)
    _pass_calibration_under(project, agent, human, new_id)
    assert stale_batch.task_id in obsolete_tasks(project, PassLabel.A)

    served = screen_next(project, agent, PassLabel.A).batch
    assert served is not None
    assert served.protocol_id == new_id
    assert old_works <= {r["work_id"] for r in served.records}
    assert served.task_id != stale_batch.task_id


def test_stale_decision_is_queued_again_and_counted_in_remaining(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    _serve_calibration(project, agent, math.ceil(len(items) / SCREEN_BATCH))
    _pass_calibration_under(project, agent, human, protocol_id)

    ordinary = sorted(w.id for w in list_works(project) if w.id not in set(items))
    work = ordinary[0]
    _decide(project, agent, work, "A", "screening", "exclude", "EX01", protocol_id)
    before = screen_next(project, agent, PassLabel.A).remaining
    assert before == len(ordinary) - 1

    new_id = _loosen_ex01(project, agent)
    _pass_calibration_under(project, agent, human, new_id)
    after = screen_next(project, agent, PassLabel.A)
    assert after.remaining == len(ordinary)
    assert work in _queued(project, new_id)


def test_refused_screen_writes_nothing_for_the_refused_pass(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    screen_next(project, agent, PassLabel.A)
    opened_before = len(_of_type(project, "screening.pass_opened"))
    joined_before = len(_of_type(project, "screening.pass_joined"))

    with pytest.raises(FactoryValidationError):
        screen_next(project, agent, PassLabel.B)
    assert len(_of_type(project, "screening.pass_opened")) == opened_before
    assert len(_of_type(project, "screening.pass_joined")) == joined_before
    assert [e.payload["pass_label"] for e in _of_type(project, "screening.pass_opened")] == ["A"]


def test_refused_label_session_writes_no_pass_opened(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    item = _draw(project)[0]
    label_calibration(project, human, item, "include", None, Channel.MCP)

    with pytest.raises(FactoryValidationError):
        screen_next(project, agent, PassLabel.A)
    assert _of_type(project, "screening.pass_opened") == []
    assert _of_type(project, "screening.pass_joined") == []


def test_model_of_the_other_pass_cannot_join(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    join_pass(project, agent, PassLabel.A)
    assert agent_other.model == agent.model

    with pytest.raises(FactoryValidationError) as raised:
        join_pass(project, agent_other, PassLabel.B)
    assert [issue.field for issue in raised.value.issues] == ["model"]
    assert [e.payload["pass_label"] for e in _of_type(project, "screening.pass_joined")] == ["A"]


def test_failed_batch_build_writes_no_pass_or_join(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    monkeypatch.setattr(
        "factory.services.tasks._spec_issues",
        lambda spec: [ValidationIssue("content", "refused")],
    )
    before = len(_events(project))
    with pytest.raises(FactoryValidationError):
        screen_next(project, agent, PassLabel.A)
    assert len(_events(project)) == before
    assert _of_type(project, "screening.pass_opened") == []
    assert _of_type(project, "screening.pass_joined") == []
