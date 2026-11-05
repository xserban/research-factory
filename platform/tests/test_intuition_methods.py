# ruff: noqa: F401, F811
"""The methods statement reads events, not skill names (G3-A fix round 2)."""

from __future__ import annotations

from factory.events.envelope import Actor
from factory.model.question import GoalStated
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import join_extraction_pass
from factory.services.interpretations import intuition_next, record_interpretation
from factory.services.methods import methods_report, render_methods
from tests.helpers import S3
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world
from tests.intuition_separation import status_without_log_counts


def _actor(session: str, model: str, skill: str) -> Actor:
    return Actor(kind="agent", id="probe", user="obd", session=session, model=model, skill=skill)


def test_a_pass_session_declaring_the_intuition_skill_stays_listed(
    project: Project, iw: IWorld
) -> None:
    impostor = _actor("01JZ9Q3K5M7N8P0R2S4T6V8W6A", "claude-pass-only", "rf-intuition@0a0a0a0a")
    join_extraction_pass(project, impostor, PassLabel.A)
    report = methods_report(project)
    assert "claude-pass-only" in report.models and "rf-intuition@0a0a0a0a" in report.skills
    assert "claude-pass-only" in render_methods(report)


def test_a_layer_writer_under_any_skill_is_not_listed(project: Project, iw: IWorld) -> None:
    writer = _actor("01JZ9Q3K5M7N8P0R2S4T6V8W6B", "claude-layer-only", "rf-other@0b0b0b0b")
    batch = intuition_next(project, writer, targets=[iw.idea1]).batch
    assert batch is not None
    record_interpretation(project, writer, iw.entry(iw.idea1), task_id=batch.task_id)
    report = methods_report(project)
    assert "claude-layer-only" not in report.models
    assert "rf-other@0b0b0b0b" not in report.skills
    assert "claude-layer-only" not in render_methods(report)


def test_the_status_comparison_sees_a_stray_evidence_event(project: Project) -> None:
    before = status_without_log_counts(project)
    project.record(
        [project.events.make("question.goal_stated", GoalStated(text="x"), project.human_actor())]
    )
    assert status_without_log_counts(project) != before
