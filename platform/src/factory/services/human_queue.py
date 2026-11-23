"""The human queue of one project: where a human is blocking, one count per gate kind.

Every count is derived from existing services (R-05); nothing is written. A gate with nothing
waiting is absent, and a gate whose precondition is not met (an agreement refused while a pass is
open, no schema declared) is absent rather than an error. Counts only: no work, label, rate or
audit identifier appears, and each `command` is a fixed template the human completes.

A conductor run that waits at a human-only gate is one item (`CONDUCTOR_WAITING`), computed from its
status; the researcher's act closes the gate and the item goes.

The intake gates (`services/intake_queue.py`) name acts that stay on the CLI: no tool performs an
import or a conversion (decisions 46 item 7 and 60, plan B1 ruling 6). `INTAKE_COMMANDS` holds what
the human runs; each act is a service taking its actor, so a relay would only add a tool over them.
With `agent`, an import gate counts the development part only, so that no figure gives the size or
the state of the held-out part (decision 43).

Invariants: items are sorted by gate order, then title/abstract before full text; every item has
`count > 0`.
"""

from enum import StrEnum

from factory.errors import FactoryValidationError
from factory.model.base import StrictModel
from factory.model.members import ProjectRole
from factory.model.protocol import ProtocolStatus, ScreeningStage
from factory.services import version_pairs
from factory.services.agreement import screen_agreement
from factory.services.audit import audit_report
from factory.services.calibration import calibration_drawn, calibration_status
from factory.services.context import Project
from factory.services.deferred_review import deferred_count
from factory.services.extraction_agreement import extraction_agreement
from factory.services.extraction_audit import extraction_audit_report
from factory.services.intake_queue import intake_counts
from factory.services.members import members
from factory.services.prisma import has_full_text_plan
from factory.services.protocol import current_protocol


class Gate(StrEnum):
    """The gate kinds whose policy is `human`, in display order. `DEFERRED_REVIEW` (contract C6)
    counts sampled agent-closed acts of a supervised or autonomous project; 0 under `attended`."""

    PRESS_CONFIRMATION = "press-confirmation"
    CALIBRATION_LABELS = "calibration-labels"
    SCREENING_DISAGREEMENTS = "screening-disagreements"
    SCREENING_AUDIT = "screening-audit"
    EXTRACTION_DISAGREEMENTS = "extraction-disagreements"
    EXTRACTION_AUDIT = "extraction-audit"
    IMPORT_CONFIRMATION = "import-confirmation"
    IMPORT_ADMISSION = "import-admission"
    ATTACHMENTS_WAITING = "attachments-waiting"
    DOCUMENTS_UNCONVERTED = "documents-unconverted"
    INBOX_OPEN = "inbox-open"
    VERSION_PAIRS = "version-pairs"
    DEFERRED_REVIEW = "deferred-review"
    CONDUCTOR_WAITING = "conductor-waiting"


INTAKE_COMMANDS: dict[Gate, str] = {
    Gate.IMPORT_CONFIRMATION: "import show <import-id> --researcher",
    Gate.IMPORT_ADMISSION: "import admit <import-id>",
    Gate.ATTACHMENTS_WAITING: "import attach <import-id>",
    Gate.DOCUMENTS_UNCONVERTED: "document converters",
    Gate.INBOX_OPEN: "inbox list --status open",
}
"""The command of each intake gate, after `factory --project <slug>`."""

CONDUCTOR_GATE_COMMANDS: dict[str, str] = {
    "protocol.ready": "protocol record",
    "protocol.press_confirm": "protocol confirm-press <review-id>",
    "import.resolution_confirm": "import confirm <import-id>",
    "mine.resolve": "mine resolve",
    "writing.release": "draft release <draft-id>",
    "manuscript.citation_confirm": "manuscript resolve",
    "hypotheses.lead_decide": "leads promote <lead-id>",
    "hypotheses.register": "hypotheses register",
}
"""The command a researcher runs to close each human-only gate a conductor run can wait at, after
`factory --project <slug>`; a gate not listed gets `conductor status`, which names it."""

_LABELLERS = (ProjectRole.SCREENER, ProjectRole.MAINTAINER, ProjectRole.OWNER)
_STEWARDS = (ProjectRole.MAINTAINER, ProjectRole.OWNER)

GATE_ROLES: dict[Gate, tuple[ProjectRole, ...]] = {
    Gate.PRESS_CONFIRMATION: _STEWARDS,
    Gate.CALIBRATION_LABELS: _LABELLERS,
    Gate.SCREENING_DISAGREEMENTS: _LABELLERS,
    Gate.SCREENING_AUDIT: _LABELLERS,
    Gate.EXTRACTION_DISAGREEMENTS: _LABELLERS,
    Gate.EXTRACTION_AUDIT: _LABELLERS,
    Gate.IMPORT_CONFIRMATION: _STEWARDS,
    Gate.IMPORT_ADMISSION: _STEWARDS,
    Gate.ATTACHMENTS_WAITING: _STEWARDS,
    Gate.DOCUMENTS_UNCONVERTED: _STEWARDS,
    Gate.INBOX_OPEN: _STEWARDS,
    Gate.VERSION_PAIRS: _STEWARDS,
    Gate.DEFERRED_REVIEW: _LABELLERS,
    Gate.CONDUCTOR_WAITING: _STEWARDS,
}
"""The project roles responsible for each gate, in order of preference (PD-8 routing): the first
role that has a holder supplies the assignee. Labelling gates go to a screener, then a maintainer
or the owner; the rest to a maintainer or the owner."""


def assignee_for(gate: Gate, held: dict[str, frozenset[ProjectRole]]) -> str | None:
    """The responsible person of `gate`: the first user, in name order, holding the first role of
    `GATE_ROLES[gate]` that anyone holds. None while no member holds any of them."""
    for role in GATE_ROLES[gate]:
        holders = sorted(user for user, roles in held.items() if role in roles)
        if holders:
            return holders[0]
    return None


class HumanItem(StrictModel):
    gate: Gate
    stage: str | None
    count: int
    command: str
    assignee: str | None = None
    """The person responsible, from the project roles; None on the agent path and while no member
    holds a responsible role."""


class HumanQueue(StrictModel):
    items: list[HumanItem]


def human_queue(project: Project, *, agent: bool = False) -> HumanQueue:
    """The pending human acts of `project`; items with a positive count only. `agent` is the
    agent path's variant (see the module docstring)."""
    project.index.sync()
    slug = project.paths.slug
    base = f"factory --project {slug}"
    stages = [ScreeningStage.TITLE_ABSTRACT]
    if has_full_text_plan(project):
        stages.append(ScreeningStage.FULL_TEXT)
    items: list[HumanItem] = []
    held = {} if agent else members(project)

    def add(gate: Gate, stage: ScreeningStage | None, count: int, command: str) -> None:
        if count > 0:
            items.append(
                HumanItem(
                    gate=gate,
                    stage=None if stage is None else stage.value,
                    count=count,
                    command=command,
                    assignee=assignee_for(gate, held),
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
        if (
            protocol is not None
            and protocol.status is ProtocolStatus.READY
            and calibration.required
            and not calibration_drawn(project, stage=stage)
        ):
            # The draw itself is the awaiting act: screening is refused until it is made.
            add(
                Gate.CALIBRATION_LABELS,
                stage,
                1,
                f"{base} calibrate draw --stage {stage.value}",
            )
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
        extraction_disagreement_count(project),
        f"{base} extract agreement",
    )
    extraction = extraction_audit_report(project)
    add(
        Gate.EXTRACTION_AUDIT,
        None,
        0 if extraction is None else extraction.sample_size - extraction.labelled,
        f"{base} extract audit-label <audit-id> <work> <row-key> <field> --correct|--incorrect",
    )
    intake = intake_counts(project, agent=agent)
    for gate, count in (
        (Gate.IMPORT_CONFIRMATION, intake.confirmation),
        (Gate.IMPORT_ADMISSION, intake.admission),
        (Gate.ATTACHMENTS_WAITING, intake.attachments),
        (Gate.DOCUMENTS_UNCONVERTED, intake.unconverted),
        (Gate.INBOX_OPEN, intake.inbox),
    ):
        add(gate, None, count, f"{base} {INTAKE_COMMANDS[gate]}")
    add(Gate.VERSION_PAIRS, None, len(version_pairs.candidates(project)), f"{base} dedup pairs")
    waiting = _conductor_waiting(project)
    if waiting is not None:
        gate_id, step = waiting
        command = CONDUCTOR_GATE_COMMANDS.get(gate_id, "conductor status")
        items.append(
            HumanItem(
                gate=Gate.CONDUCTOR_WAITING,
                stage=step,
                count=1,
                command=f"{base} {command}",
                assignee=assignee_for(Gate.CONDUCTOR_WAITING, held),
            )
        )
    if not agent:  # agent-closed acts and audit samples are the researcher's to see
        add(Gate.DEFERRED_REVIEW, None, deferred_count(project), f"{base} review deferred list")
    return HumanQueue(items=items)


def _conductor_waiting(project: Project) -> tuple[str, str] | None:
    """`(gate id, step)` when the project's conductor run waits at a human-only gate, else None.
    Computed from `conductor_status` (read-only: no event is written)."""
    from factory.services.conductor import conductor_status  # conductor imports project

    status = conductor_status(project)
    if status.state != "waiting" or status.gate_id is None or status.stage_id is None:
        return None
    return status.gate_id, status.stage_id


def _screening_disagreements(project: Project, stage: ScreeningStage) -> int:
    """Unresolved disagreements, `unsure` included; 0 while the agreement is refused."""
    try:
        return len(screen_agreement(project, project.human_actor(), stage=stage).disagreements)
    except FactoryValidationError:
        return 0


def extraction_disagreement_count(project: Project) -> int:
    """Unresolved extraction disagreements; 0 while the agreement is refused."""
    try:
        return len(extraction_agreement(project, project.human_actor()).disagreements)
    except FactoryValidationError:
        return 0
