"""The human queue of one project: where a human is blocking, one count per gate kind.

Every count is derived from existing services (R-05); nothing is written. A gate with nothing
waiting is absent, and a gate whose precondition is not met (an agreement refused while a pass is
open, no schema declared) is absent rather than an error. Counts only: no work, label, rate or
audit identifier appears, and each `command` is a fixed template the human completes.

Invariants: items are sorted by gate order, then title/abstract before full text; every item has
`count > 0`.
"""

from enum import StrEnum

from factory.errors import FactoryValidationError
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.services.agreement import screen_agreement
from factory.services.audit import audit_report
from factory.services.calibration import calibration_status
from factory.services.context import Project
from factory.services.extraction_agreement import extraction_agreement
from factory.services.extraction_audit import extraction_audit_report
from factory.services.prisma import has_full_text_plan
from factory.services.protocol import current_protocol


class Gate(StrEnum):
    """The gate kinds whose policy is `human`, in display order."""

    PRESS_CONFIRMATION = "press-confirmation"
    CALIBRATION_LABELS = "calibration-labels"
    SCREENING_DISAGREEMENTS = "screening-disagreements"
    SCREENING_AUDIT = "screening-audit"
    EXTRACTION_DISAGREEMENTS = "extraction-disagreements"
    EXTRACTION_AUDIT = "extraction-audit"


class HumanItem(StrictModel):
    gate: Gate
    stage: str | None
    count: int
    command: str


class HumanQueue(StrictModel):
    items: list[HumanItem]


def human_queue(project: Project) -> HumanQueue:
    """The pending human acts of `project`; items with a positive count only."""
    project.index.sync()
    slug = project.paths.slug
    base = f"factory --project {slug}"
    stages = [ScreeningStage.TITLE_ABSTRACT]
    if has_full_text_plan(project):
        stages.append(ScreeningStage.FULL_TEXT)
    items: list[HumanItem] = []

    def add(gate: Gate, stage: ScreeningStage | None, count: int, command: str) -> None:
        if count > 0:
            items.append(
                HumanItem(
                    gate=gate,
                    stage=None if stage is None else stage.value,
                    count=count,
                    command=command,
                )
            )

    protocol = current_protocol(project)
    add(
        Gate.PRESS_CONFIRMATION,
        None,
        int(protocol is not None and protocol.press == "reviewed"),
        f"{base} protocol confirm-press <review-id>",
    )
    for stage in stages:
        calibration = calibration_status(project, stage=stage)
        add(
            Gate.CALIBRATION_LABELS,
            stage,
            calibration.drawn - calibration.labelled,
            f"{base} calibrate label <work> <include|exclude> --stage {stage.value}",
        )
    for stage in stages:
        add(
            Gate.SCREENING_DISAGREEMENTS,
            stage,
            _screening_disagreements(project, stage),
            f"{base} screen disagreements --stage {stage.value}",
        )
    for stage in stages:
        report = audit_report(project, stage=stage)
        add(
            Gate.SCREENING_AUDIT,
            stage,
            0 if report is None else report.sample_size - report.labelled,
            f"{base} audit label <audit-id> <work> <include|exclude>",
        )
    add(
        Gate.EXTRACTION_DISAGREEMENTS,
        None,
        _extraction_disagreements(project),
        f"{base} extract agreement",
    )
    extraction = extraction_audit_report(project)
    add(
        Gate.EXTRACTION_AUDIT,
        None,
        0 if extraction is None else extraction.sample_size - extraction.labelled,
        f"{base} extract audit-label <audit-id> <work> <row-key> <field> --correct|--incorrect",
    )
    return HumanQueue(items=items)


def _screening_disagreements(project: Project, stage: ScreeningStage) -> int:
    """Unresolved disagreements, `unsure` included; 0 while the agreement is refused."""
    try:
        return len(screen_agreement(project, project.human_actor(), stage=stage).disagreements)
    except FactoryValidationError:
        return 0


def _extraction_disagreements(project: Project) -> int:
    """Unresolved extraction disagreements; 0 while the agreement is refused."""
    try:
        return len(extraction_agreement(project, project.human_actor()).disagreements)
    except FactoryValidationError:
        return 0
