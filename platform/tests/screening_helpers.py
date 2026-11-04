"""Direct screening decisions for tests of later slices (no calibration, no batches)."""

from __future__ import annotations

from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.screening import (
    DecisionRecorded,
    PassLabel,
    ScreeningPhase,
    Verdict,
)
from factory.services.context import Project


def decide(
    project: Project,
    actor: Actor,
    work_id: str,
    protocol_id: str,
    verdict: str,
    *,
    pass_label: PassLabel = PassLabel.A,
    criterion: str | None = None,
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT,
    supersedes: str | None = None,
) -> str:
    """Write one screening-phase decision event directly; return its id."""
    decision_id = f"dec_{project.ids.ulid()}"
    payload = DecisionRecorded(
        decision_id=decision_id,
        work_id=work_id,
        pass_label=pass_label,
        phase=ScreeningPhase.SCREENING,
        stage=stage,
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
                "screening.decision_recorded", payload, actor, refs=(decision_id,), input_blob=blob
            )
        ]
    )
    return decision_id
