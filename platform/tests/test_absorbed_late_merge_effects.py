"""A work merged after full-text screening is read (rows, views) but never worked on again.

Decision 92 item 9 keeps the rows of an absorbed duplicate in the views; the queue of work to do,
the flow boxes and the extraction passes stay canonical, so one paper is neither extracted twice
nor counted twice."""

# ruff: noqa: F811

from __future__ import annotations

from factory.events.envelope import Actor
from factory.model.screening import PassLabel
from factory.services.appraisal_passes import appraisal_population
from factory.services.context import Project
from factory.services.extraction import (
    extract_next,
    extract_record,
    extraction_population,
    unit_states,
)
from factory.services.flow_ledger import flow_ledger
from factory.services.fulltext_screening import fulltext_queue
from factory.services.prisma import full_text_boxes, prisma_flow
from tests.extraction_helpers import _r, ext_a, ext_b, screened, world  # noqa: F401
from tests.views_b_helpers import real_merge


def _late_merge(project: Project, works: list[str]) -> tuple[str, str]:
    primary, absorbed = works[2], works[0]
    real_merge(project, primary, absorbed)
    return primary, absorbed


def test_the_absorbed_work_is_read_but_not_served_for_extraction(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    primary, absorbed = _late_merge(project, world)
    assert absorbed in extraction_population(project)  # read: its rows stay (decision 92 item 9)
    assert not [s for s in unit_states(project) if s.work_id == absorbed]
    served: list[str] = []
    for _ in range(len(world) + 2):
        batch = extract_next(project, ext_a, PassLabel.A).batch
        if batch is None:
            break
        work = batch.records[0]["work_id"]
        served.append(work)
        assert extract_record(project, ext_a, batch.task_id, [_r()], finish=True).completed
    assert absorbed not in served and primary in served
    assert len(served) == len(set(served)) == len(world) - 1


def test_appraisal_population_is_canonical_after_a_late_merge(
    project: Project, world: list[str]
) -> None:
    primary, absorbed = _late_merge(project, world)
    appraised = appraisal_population(project)
    assert absorbed not in appraised and primary in appraised


def test_flow_and_prisma_stay_canonical_after_a_late_merge(
    project: Project, world: list[str]
) -> None:
    before = prisma_flow(project)
    primary, absorbed = _late_merge(project, world)
    queue = fulltext_queue(project)
    queued = {e.work_id for e in queue.eligible} | set(queue.not_retrieved)
    assert absorbed not in queued and primary in queued
    boxes = full_text_boxes(project)
    assert boxes.eligible == len(queue.eligible)
    assert boxes.eligible == boxes.assessed + boxes.pending
    flow = prisma_flow(project)
    assert flow.full_text.not_sought + flow.full_text.sought == flow.included
    assert flow.included == before.included - 1
    row = next(r for r in flow_ledger(project) if r.work_id == absorbed)
    assert row.canonical_id == primary and row.ft_state is None and row.ft_outcome is None
