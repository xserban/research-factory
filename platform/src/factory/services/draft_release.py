"""The release gate of a draft (slice 7b, plan W-B, ruling 6; spec ruling 13).

Declares: `GATE`, `release`, `released_drafts`. The only module that writes `draft.released`.

Who may release is the gate `writing.release` (`require_gate`). What must hold follows the rigor
mode: `exploratory`, a non-empty draft; `pilot`, the audit of the verdicts still live drawn after
the last verdict and fully labelled, and no `stale` sentence; `systematic`, the same and no
`flagged` or `unchecked` sentence and their audit rate under the ceiling, released by the reviewer
of record.

Invariants:
- A refusal has one issue per blocking condition, counts only, never text. The conditions an
  agent can reach read nothing of an audit's result: the audit rate and the flagged count bind only
  in `systematic`, where an agent is refused first, before the gate (R-39; a protocol weakening the
  gate there is refused when recorded, `protocol_rules`).
- A release writes one event with the log position it was read at, the policy, the counts by status
  and the audit as the researcher reads them. It does not freeze the draft; a later release is a new
  event with new counts.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.drafts import DraftAuditReport, DraftReleased
from factory.model.project import RigorMode
from factory.model.protocol import ReviewerRole
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.draft_audit import audit_report
from factory.services.drafts import require_draft, sentence_status, status_counts
from factory.services.gates import require_gate, rigor_mode
from factory.services.protocol import current_protocol

GATE = "writing.release"


def _reviewer_of_record(project: Project) -> str | None:
    current = current_protocol(project)
    if current is None:
        return None
    records = [
        r for r in current.spec.screening.reviewers if r.role is ReviewerRole.REVIEWER_OF_RECORD
    ]
    return records[0].actor if records else None


def _audit_issues(report: DraftAuditReport) -> list[ValidationIssue]:
    if report.drawn == 0:
        return [ValidationIssue("audit", "no audit is drawn")]
    issues: list[ValidationIssue] = []
    if report.labelled < report.drawn:
        unlabelled = report.drawn - report.labelled
        issues.append(ValidationIssue("audit", f"{unlabelled} sampled verdict(s) unlabelled"))
    if report.outdated:
        issues.append(ValidationIssue("audit", "a verdict is newer than the last draw"))
    return issues


def _count_issue(counts: dict[str, int], status: str) -> list[ValidationIssue]:
    n = counts[status]
    return [ValidationIssue(status, f"{n} {status} sentence(s)")] if n else []


def _blocking(
    mode: RigorMode, counts: dict[str, int], report: DraftAuditReport
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not sum(counts.values()):
        issues.append(ValidationIssue("draft_id", "the draft has no sentence"))
    if mode is RigorMode.EXPLORATORY:
        return issues
    issues += _audit_issues(report)
    issues += _count_issue(counts, "stale")
    if mode is RigorMode.SYSTEMATIC:
        issues += _count_issue(counts, "flagged")
        issues += _count_issue(counts, "unchecked")
        if report.above_ceiling:
            issues.append(ValidationIssue("audit", "the audit error rate is above the ceiling"))
    return issues


def release(project: Project, draft_id: str, *, actor: Actor) -> str:
    """Release the draft and return the event id. Refused, with nothing written, by the gate and by
    the conditions of the rigor mode (see the module docstring)."""
    with project.index.exclusive(), entering():
        project.index.sync()
        require_draft(project, draft_id)
        mode = rigor_mode(project)
        if mode is RigorMode.SYSTEMATIC and actor.kind != "human":
            raise FactoryValidationError(
                [ValidationIssue("actor", "in this mode a draft is released at the terminal")]
            )
        policy = require_gate(project, actor, GATE)
        if mode is RigorMode.SYSTEMATIC and actor.id != _reviewer_of_record(project):
            raise FactoryValidationError(
                [ValidationIssue("actor", "only the reviewer of record releases in this mode")]
            )
        rows = sentence_status(project, draft_id)
        counts = status_counts(rows)
        report = audit_report(project, draft_id)
        issues = _blocking(mode, counts, report)
        if issues:
            raise FactoryValidationError(issues)
        as_of = project.index.head()
        assert as_of is not None  # the draft's own event is in the log
        event = project.events.make(
            "draft.released",
            DraftReleased(
                draft_id=draft_id,
                as_of=as_of,
                policy=policy.kind,
                counts=counts,
                audit=report,
                released_by=actor.id,
            ),
            actor,
            refs=[draft_id],
            input_blob=(
                project.blobs.put_json({"draft_id": draft_id}) if actor.kind == "agent" else None
            ),
        )
        project.record([event])
        return event.id


def released_drafts(project: Project) -> frozenset[str]:
    """The drafts with at least one release folded."""
    project.index.sync()
    with project.index.connect() as conn:
        return frozenset(
            str(r[0]) for r in conn.execute(text("SELECT DISTINCT draft_id FROM draft_releases"))
        )
