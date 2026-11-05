"""An intuition session cannot join a pass; task counts; truncation (G3-A fix round 1)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.model.extraction import Scope
from factory.model.screening import PassLabel
from factory.services import interpretations as interpretations_service
from factory.services.context import Project
from factory.services.extraction import join_extraction_pass
from factory.services.interpretations import intuition_next
from factory.services.screening import join_pass
from factory.services.tasks import TaskSpec, create_tasks, task_counts
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world, writer_actor


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def test_session_served_an_intuition_task_cannot_join_either_pass(
    project: Project, iw: IWorld
) -> None:
    assert intuition_next(project, iw.writer).batch is not None
    for join in (
        lambda: join_pass(project, iw.writer, PassLabel.A),
        lambda: join_extraction_pass(project, iw.writer, PassLabel.A),
        lambda: join_extraction_pass(project, iw.writer, PassLabel.A, scope=Scope.CONTRIBUTION),
    ):
        before = _events(project)
        with pytest.raises(FactoryValidationError) as e:
            join()
        assert [i.field for i in e.value.issues] == ["session"]
        assert "intuition" in e.value.issues[0].reason
        assert _events(project) == before


def test_a_session_never_served_an_intuition_task_still_joins(project: Project, iw: IWorld) -> None:
    fresh = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W4A", "other").model_copy(
        update={"model": "claude-haiku-5-5", "skill": "rf-extract@1a2b3c4d"}
    )
    join_extraction_pass(project, fresh, PassLabel.A)


def test_task_counts_leave_out_intuition_tasks(project: Project, iw: IWorld) -> None:
    before = task_counts(project)
    assert intuition_next(project, iw.writer).batch is not None
    assert task_counts(project) == before


def test_served_items_report_truncation(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = intuition_next(project, iw.writer, targets=[iw.idea2]).batch
    assert batch is not None and batch.truncated is False and len(batch.items) > 1
    monkeypatch.setattr(interpretations_service, "MAX_SERVED_ITEMS", 1)
    other = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W4B", "b")
    capped = intuition_next(project, other, targets=[iw.idea1]).batch
    assert capped is not None and capped.truncated is True and len(capped.items) == 1
