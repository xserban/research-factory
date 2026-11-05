"""The human audit of `supported` verdicts (slice 7b, plan W-B, ruling 5; spec ruling 12).

Declares: `DRAFT_VERIFY_ERROR_CEILING`, `draw_audit`, `record_audit`, `audit_report`,
`agent_audit_report`, `incorrect_verdicts`, `open_audit_items`. The only module that writes
`draft.audit_drawn` and `draft.audited`.

Invariants:
- A sample is drawn from the `supported` verdicts of live sentences not drawn before, n =
  min(N, max(ceil(0.1 N), 20)), from a recorded seed: the fold recomputes the draw, so a sample
  cannot be picked by hand. A new sample waits for a verdict newer than the last draw, so samples
  cannot be drawn again until an easy one comes up.
- A label is a human act at the gate `writing.audit_label`; a later label of a verdict replaces the
  earlier.
- The error rate, the count behind it and the ceiling flag are for the researcher: the agent
  variant carries none of them (decisions 37.14 and 52). The drawn and labelled counts say how far
  the audit has gone and nothing about its result.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.drafts import audit_due, audit_population
from factory.model.drafts import (
    DRAFT_AUDIT_FRACTION,
    DRAFT_AUDIT_MINIMUM,
    DRAFT_VERIFY_ERROR_CEILING,
    NOTE_MAX_CHARS,
    AuditLabel,
    DraftAuditDrawn,
    DraftAudited,
    DraftAuditReport,
)
from factory.model.screening import Channel
from factory.quality.stats import audit_size, draw_uniform
from factory.services import audit_core
from factory.services.context import Project

GATE = "writing.audit_label"


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def draw_audit(project: Project, draft_id: str, *, seed: int | None = None) -> str:
    """Draw a sample of the draft's unaudited `supported` verdicts and return its `dau_` id. The
    draw is the platform's (`draft.audit_drawn`, system). Refused, with nothing written, for an
    unknown draft (`draft_id`), a seed out of range (`random_seed`), and when no verdict waits or
    none is newer than the last draw (`audit`)."""
    chosen, issues = audit_core.validate_seed(seed)
    if issues:
        raise FactoryValidationError(issues)
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            known = conn.execute(
                text("SELECT 1 FROM drafts WHERE draft_id = :d"), {"d": draft_id}
            ).first()
            if known is None:
                raise _refuse("draft_id", "unknown draft")
            population = audit_population(conn, draft_id)
            due = audit_due(conn, draft_id)
        if not population:
            raise _refuse("audit", "no supported verdict waits for an audit")
        if not due:
            raise _refuse("audit", "no verdict is newer than the last draw")
        size = audit_size(len(population), DRAFT_AUDIT_FRACTION, DRAFT_AUDIT_MINIMUM)
        audit_id = project.ids.new("dau")
        payload = DraftAuditDrawn(
            audit_id=audit_id,
            draft_id=draft_id,
            seed=chosen,
            population=len(population),
            verdict_ids=draw_uniform(population, size, chosen, key=str),
        )
        project.record(
            [
                project.events.make(
                    "draft.audit_drawn",
                    payload,
                    project.system_actor(),
                    refs=[audit_id, draft_id, *payload.verdict_ids],
                )
            ]
        )
        return audit_id


def record_audit(
    project: Project,
    audit_id: str,
    verdict_id: str,
    label: AuditLabel,
    note: str | None,
    *,
    actor: Actor,
    channel: Channel = Channel.CLI,
) -> str:
    """Record a human's label on one sampled verdict and return the event id. Refused, with nothing
    written: an agent (`actor`), an MCP relay from a session in a pass (`channel`), an unknown audit
    (`audit_id`), a verdict outside its sample (`verdict_id`), a note over 300 characters (`note`).
    """
    with project.index.exclusive():
        project.index.sync()
        issues = audit_core.human_gate(project, actor, channel, noun="draft-label", gate_id=GATE)
        with project.index.connect() as conn:
            known = conn.execute(
                text("SELECT draft_id FROM draft_audits WHERE audit_id = :a"), {"a": audit_id}
            ).first()
            sampled = conn.execute(
                text("SELECT 1 FROM draft_audit_items WHERE audit_id = :a AND verdict_id = :v"),
                {"a": audit_id, "v": verdict_id},
            ).first()
        if known is None:
            issues.append(ValidationIssue("audit_id", "unknown audit"))
        elif sampled is None:
            issues.append(ValidationIssue("verdict_id", "not in this audit sample"))
        if note is not None and len(note) > NOTE_MAX_CHARS:
            issues.append(ValidationIssue("note", f"at most {NOTE_MAX_CHARS} characters"))
        if issues or known is None:
            raise FactoryValidationError(issues)
        payload = DraftAudited(
            audit_id=audit_id,
            verdict_id=verdict_id,
            label=label,
            note=note or None,
            channel=channel,
        )
        event = project.events.make(
            "draft.audited", payload, actor, refs=[audit_id, verdict_id, str(known[0])]
        )
        project.record([event])
        return event.id


def audit_report(project: Project, draft_id: str) -> DraftAuditReport:
    """Every sample of the draft read together. The rate is incorrect / labelled, undefined until a
    verdict is labelled; `outdated` says a verdict is newer than the last draw."""
    project.index.sync()
    with project.index.connect() as conn:
        labels = [
            None if r[0] is None else str(r[0])
            for r in conn.execute(
                text(
                    "SELECT i.label FROM draft_audit_items i JOIN draft_audits a "
                    "ON a.audit_id = i.audit_id WHERE a.draft_id = :d"
                ),
                {"d": draft_id},
            )
        ]
        outdated = bool(labels) and audit_due(conn, draft_id)
    labelled = [x for x in labels if x is not None]
    incorrect = sum(1 for x in labelled if x == AuditLabel.INCORRECT.value)
    rate = incorrect / len(labelled) if labelled else None
    return DraftAuditReport(
        drawn=len(labels),
        labelled=len(labelled),
        incorrect=incorrect,
        rate=rate,
        above_ceiling=None if rate is None else rate > DRAFT_VERIFY_ERROR_CEILING,
        outdated=outdated,
    )


def agent_audit_report(report: DraftAuditReport) -> DraftAuditReport:
    """The report an agent may read: no rate, no ceiling flag, and no count of incorrect labels,
    from which the rate follows."""
    return report.model_copy(update={"incorrect": None, "rate": None, "above_ceiling": None})


def incorrect_verdicts(project: Project, draft_id: str) -> frozenset[str]:
    """The verdicts of the draft whose latest audit label is `incorrect`. For the researcher."""
    with project.index.connect() as conn:
        return frozenset(
            str(r[0])
            for r in conn.execute(
                text(
                    "SELECT i.verdict_id FROM draft_audit_items i JOIN draft_audits a "
                    "ON a.audit_id = i.audit_id WHERE a.draft_id = :d AND i.label = :l"
                ),
                {"d": draft_id, "l": AuditLabel.INCORRECT.value},
            )
        )


def open_audit_items(project: Project, draft_id: str) -> list[tuple[str, str]]:
    """(audit id, verdict id) of the sampled verdicts still unlabelled, in order."""
    project.index.sync()
    with project.index.connect() as conn:
        return [
            (str(r[0]), str(r[1]))
            for r in conn.execute(
                text(
                    "SELECT i.audit_id, i.verdict_id FROM draft_audit_items i JOIN draft_audits a "
                    "ON a.audit_id = i.audit_id WHERE a.draft_id = :d AND i.label IS NULL "
                    "ORDER BY i.audit_id, i.verdict_id"
                ),
                {"d": draft_id},
            )
        ]


__all__ = [
    "DRAFT_VERIFY_ERROR_CEILING",
    "GATE",
    "agent_audit_report",
    "audit_report",
    "draw_audit",
    "incorrect_verdicts",
    "open_audit_items",
    "record_audit",
]
