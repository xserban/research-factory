from factory.services.context import Project
from factory.services.extraction import abandoned_task_ids
from factory.services.project import project_status


def test_abandoned_is_zero_without_extraction(project: Project) -> None:
    assert abandoned_task_ids(project) == set()
    assert project_status(project).tasks.abandoned == 0
