"""Full-text eligibility, pinned batches and the staged pass-B sample (plan 2C, task 4)."""

import math
from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.index.chase import extended_works
from factory.model.chase import SampleExtended
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.calibration import (
    calibration_drawn,
    calibration_items,
    draw_calibration,
    stage_population,
)
from factory.services.context import Project
from factory.services.fulltext_screening import fulltext_queue
from factory.services.screening import (
    _extend_sample,
    _kind_tasks,
    open_pass,
    pass_b_sample,
    screen_next,
)
from factory.services.search import list_works
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    excluded_after_conversion,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.fulltext_helpers import _convert, _world
from tests.helpers import SourcesFor, _of_type
from tests.screening_helpers import _late

TA = ScreeningStage.TITLE_ABSTRACT
FT = ScreeningStage.FULL_TEXT


def _ft_records(project: Project, label: str = "A") -> list[dict[str, Any]]:
    tasks = _kind_tasks(project, f"screen_ft_{label.lower()}")
    return [dict(r) for _, _, content in tasks for r in content.records]


def _open_ft(project: Project, agent: Actor, human: Actor) -> None:
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    del human


def test_eligible_are_promoted_with_a_converted_document(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    promoted = promoted_works(project)
    assert len(promoted) >= 3
    first, second, *rest = promoted
    _convert(project, [first, second])
    queue = fulltext_queue(project)
    assert [e.work_id for e in queue.eligible] == sorted([first, second])
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.work_id, c.document_id, c.conversion_id FROM document_conversions c "
                "JOIN fulltext_documents d ON d.document_id = c.document_id"
            )
        ).all()
    expected = {str(w): (str(d), str(c)) for w, d, c in rows}
    for entry in queue.eligible:
        assert (entry.document_id, entry.conversion_id) == expected[entry.work_id]
    assert queue.not_retrieved == sorted(rest)


def test_promoted_without_conversion_is_not_retrieved(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=1.0)
    promoted = promoted_works(project)
    converted, fetched_only, bare = promoted[0], promoted[1], promoted[2]
    _convert(project, [converted])
    fetched_document(project, fetched_only, ARTICLE)  # a live document, never converted
    _open_ft(project, agent, human)

    queue = fulltext_queue(project)
    assert [e.work_id for e in queue.eligible] == [converted]
    assert fetched_only in queue.not_retrieved and bare in queue.not_retrieved

    screen_next(project, agent, PassLabel.A, stage=FT)
    queued = {r["work_id"] for r in _ft_records(project)}
    assert queued == {converted}


def test_batch_pins_conversion_and_ignores_later_conversion(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=1.0)
    work = promoted_works(project)[0]
    _convert(project, [work], version="1.0+a")
    _open_ft(project, agent, human)
    queue = fulltext_queue(project)
    [pinned] = queue.eligible

    result = screen_next(project, agent, PassLabel.A, stage=FT)
    assert result.batch is not None or _ft_records(project)
    [record] = _ft_records(project)
    assert record["conversion_id"] == pinned.conversion_id
    assert record["document_id"] == pinned.document_id
    assert set(record) == {"work_id", "title", "document_id", "conversion_id"}

    run_convert(project, make_registry(StubConverter(version="1.0+b")))
    assert fulltext_queue(project).eligible[0].conversion_id != pinned.conversion_id

    screen_next(project, agent, PassLabel.A, stage=FT)
    [again] = _ft_records(project)
    assert again["conversion_id"] == pinned.conversion_id
    contents = [c for _, _, c in _kind_tasks(project, "screen_ft_a")]
    assert all(c.stage is FT for c in contents)
    assert "quote" in contents[0].instructions and "document_read" in contents[0].instructions


def test_dual_sample_applies_at_full_text(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=0.5)
    promoted = promoted_works(project)
    _convert(project, promoted)
    _open_ft(project, agent, human)
    assert calibration_drawn(project, stage=FT)

    open_pass(project, agent, PassLabel.B, stage=FT)
    sample = pass_b_sample(project, stage=FT)
    eligible = {e.work_id for e in fulltext_queue(project).eligible}
    assert sample is not None
    assert set(sample) <= eligible
    calibration = set(calibration_items(project, stage=FT))
    assert calibration <= set(sample)
    # ceil(fraction * eligible) works are drawn from those outside the calibration set.
    assert len(set(sample) - calibration) == min(
        math.ceil(0.5 * len(eligible)), len(eligible - calibration)
    )

    screen_next(project, agent, PassLabel.B, stage=FT)
    assert {r["work_id"] for r in _ft_records(project, "B")} <= set(sample)
    # Pass A covers every eligible work.
    screener_a = agent_other.model_copy(update={"model": "claude-sonnet-5-5"})
    open_pass(project, screener_a, PassLabel.A, stage=FT)
    screen_next(project, screener_a, PassLabel.A, stage=FT)
    assert {r["work_id"] for r in _ft_records(project, "A")} == eligible


def test_full_text_sample_extends_when_works_become_eligible(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=0.5)
    promoted = promoted_works(project)
    half = len(promoted) // 2
    _convert(project, promoted[:half])
    _open_ft(project, agent, human)
    open_pass(project, agent, PassLabel.B, stage=FT)
    sample = pass_b_sample(project, stage=FT)
    assert sample is not None

    def ft_events() -> list[Event]:
        return [
            e
            for e in _of_type(project, "screening.sample_extended")
            if SampleExtended.model_validate(e.payload).stage is FT
        ]

    [opening] = ft_events()
    first = SampleExtended.model_validate(opening.payload)
    assert first.added == ()
    assert set(first.considered).isdisjoint(sample)

    _convert(project, promoted[half:], version="1.0+a")
    screen_next(project, agent, PassLabel.B, stage=FT)
    events = ft_events()
    assert len(events) == 2
    extension = SampleExtended.model_validate(events[1].payload)
    assert set(extension.considered) == set(promoted[half:])
    assert set(extension.added) <= set(extension.considered)
    grown = pass_b_sample(project, stage=FT)
    assert grown is not None and set(sample) <= set(grown)
    assert set(grown) - set(sample) == set(extension.added)
    with project.index.connect() as conn:
        assert extended_works(conn, FT) == set(extension.added)

    screen_next(project, agent, PassLabel.B, stage=FT)
    assert len(ft_events()) == 2  # a work is considered once
    assert _extend_sample(project, agent, stage=FT, random_seed=1) is None


def test_title_abstract_sample_tables_unchanged(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=0.5)
    _late(project, human, mock_sources, 1000, 20)
    screen_next(project, agent, PassLabel.B)  # a title/abstract extension over the late works
    promoted = promoted_works(project)
    _convert(project, promoted)
    rows = "SELECT stage, work_id, event_id, added FROM sample_considered ORDER BY work_id"
    with project.index.connect() as conn:
        before = conn.execute(text(rows)).all()
        extensions = conn.execute(text("SELECT event_id, stage FROM sample_extensions")).all()
    assert before and {row[0] for row in before} == {"title-abstract"}
    assert {row[1] for row in extensions} == {"title-abstract"}

    _open_ft(project, agent, human)
    open_pass(project, agent, PassLabel.B, stage=FT)
    screen_next(project, agent, PassLabel.B, stage=FT)
    with project.index.connect() as conn:
        ta_after = [row for row in conn.execute(text(rows)).all() if row[0] == "title-abstract"]
        assert extended_works(conn) == {row[1] for row in before if row[3]}
    assert ta_after == before


def test_ineligible_works_never_queued(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=1.0)
    promoted = promoted_works(project)
    excluded, kept = promoted[0], promoted[1]
    excluded_after_conversion(project, agent, excluded)
    _convert(project, [kept])
    _open_ft(project, agent, human)

    queue = fulltext_queue(project)
    assert [e.work_id for e in queue.eligible] == [kept]
    assert excluded not in queue.not_retrieved  # not promoted any more
    screen_next(project, agent, PassLabel.A, stage=FT)
    assert {r["work_id"] for r in _ft_records(project)} == {kept}


def test_full_text_calibration_population_requires_document(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources, dual_sample=1.0, calibration=5)
    promoted = promoted_works(project)
    corpus_ids = {w.id for w in list_works(project)}
    assert stage_population(project, TA) == corpus_ids
    assert stage_population(project, FT) == set()
    _convert(project, promoted[-3:])
    assert stage_population(project, FT) == set(promoted[-3:])
    drawn = draw_calibration(project, project.system_actor(), random_seed=9, stage=FT)
    assert drawn and set(drawn) <= set(promoted[-3:])
    assert calibration_drawn(project, stage=FT)
