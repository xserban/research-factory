"""The work ledger and the flow by source reconcile with the PRISMA flow (flow transparency)."""

from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.flow_ledger import (
    TOTAL,
    flow_by_source,
    flow_ledger,
    ledger_reconciles,
    source_group,
)
from factory.services.prisma import prisma_flow
from factory.services.search import list_works
from tests.fulltext_helpers import _ft_world, _ta_world
from tests.helpers import SourcesFor


def test_source_group_is_a_pure_grouping() -> None:
    assert source_group([]) == "other"
    assert source_group(["arxiv", "arxiv"]) == "arxiv-only"
    assert source_group(["openalex"]) == "openalex-only"
    assert source_group(["openalex", "arxiv"]) == "both"
    assert source_group(["pubmed", "arxiv"]) == "arxiv+pubmed"


def test_ledger_has_one_row_per_record_and_reconciles(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    rows = flow_ledger(project)
    ids = [row.work_id for row in rows]
    assert len(ids) == len(set(ids))
    assert set(ids) >= {work.id for work in list_works(project)}
    assert ledger_reconciles(project) == []
    total = flow_by_source(project)[TOTAL]
    flow = prisma_flow(project)
    assert total.screened == flow.screened
    assert total.ft_included == flow.full_text.included
    assert sum(g.screened for k, g in flow_by_source(project).items() if k != TOTAL) == (
        total.screened
    )


def test_full_text_states_follow_the_boxes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ta_world(project, agent, human, mock_sources)
    total = flow_by_source(project)[TOTAL]
    boxes = prisma_flow(project).full_text
    assert total.ft_not_sought + total.ft_attempted_failed == boxes.not_retrieved - 1
    failed = [r for r in flow_ledger(project) if r.ft_state == "attempted-failed"]
    assert failed and all(r.ft_reasons for r in failed)
    assert all(r.ft_outcome is None for r in flow_ledger(project))
