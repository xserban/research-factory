from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.extraction import abandoned_task_ids
from factory.services.project import project_status
from factory.services.protocol import amend_protocol, current_protocol
from tests.helpers import SourcesFor, ready_protocol


def test_abandoned_is_zero_without_extraction(project: Project) -> None:
    assert abandoned_task_ids(project) == set()
    assert project_status(project).tasks.abandoned == 0


def test_no_full_text_plan_is_a_blocking_next_step(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    assert project_status(project).blocking == []
    ready_protocol(project, agent, human, mock_sources)
    protocol = current_protocol(project)
    assert protocol is not None
    if protocol.spec.full_text_screening is not None:
        amend_protocol(
            project,
            agent,
            protocol.spec.model_copy(update={"full_text_screening": None}),
            reason="no full text",
            semantic=True,
            effects={},
        )
    blocking = project_status(project).blocking
    assert len(blocking) == 1
    assert "full-text screening is not planned in the protocol" in blocking[0]
