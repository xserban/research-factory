"""The human audit of a manuscript's `supported` verdicts (slice 7b, plan W-C ruling 6; spec rulings
12 and 17).

Declares: `GATE`, `draw_audit`, `record_audit`, `audit_report`, `audit_sheet`. The only module that
writes `manuscript.audit_drawn` and `manuscript.audited`.

The rule is W-B's, per manuscript: n = min(N, max(ceil(0.1 N), 20)) from a recorded seed, a new
sample only for a verdict newer than the last draw, a label a human act at a gate, a later label
replacing the earlier. The plan asks `services/draft_audit.py` to take a subject; that module stays
as it is, since a draft's population is a matter of live sentences, and what the two share is
`quality.stats`, `audit_core` and the constants of `model.drafts`.

Invariants:
- The fold recomputes the draw, so a sample cannot be picked by hand.
- The error rate, the count behind it and the ceiling flag are the researcher's: no agent tool
  reads this module (decisions 37.14 and 52).
"""

from __future__ import annotations

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.manuscripts import LIVE_VERDICT, audit_due, audit_population
from factory.model.drafts import (
    DRAFT_AUDIT_FRACTION,
    DRAFT_AUDIT_MINIMUM,
    DRAFT_VERIFY_ERROR_CEILING,
    NOTE_MAX_CHARS,
    AuditLabel,
    DraftAuditReport,
)
from factory.model.manuscripts import ManuscriptAuditDrawn, ManuscriptAudited
from factory.model.screening import Channel
from factory.quality.stats import audit_size, draw_uniform
from factory.services import audit_core
from factory.services.context import Project
from factory.services.manuscripts import refuse_echo, require_manuscript

GATE = "manuscript.audit_label"


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def draw_audit(project: Project, manuscript_id: str, *, seed: int | None = None) -> str:
    """Draw a sample of the manuscript's unaudited `supported` verdicts and return its `mau_` id.
    Refused, with nothing written: an unknown manuscript, a seed out of range (`random_seed`), no
    verdict waiting or none newer than the last draw (`audit`)."""
    chosen, issues = audit_core.validate_seed(seed)
    if issues:
        raise FactoryValidationError(issues)
    with project.index.exclusive():
        project.index.sync()
        require_manuscript(project, manuscript_id)
        with project.index.connect() as conn:
            population = audit_population(conn, manuscript_id)
            due = audit_due(conn, manuscript_id)
        if not population:
            raise _refuse("audit", "no supported verdict waits for an audit")
        if not due:
            raise _refuse("audit", "no verdict is newer than the last draw")
        size = audit_size(len(population), DRAFT_AUDIT_FRACTION, DRAFT_AUDIT_MINIMUM)
        audit_id = project.ids.new("mau")
        payload = ManuscriptAuditDrawn(
            audit_id=audit_id,
            manuscript_id=manuscript_id,
            seed=chosen,
            population=len(population),
            verdict_ids=draw_uniform(population, size, chosen, key=str),
        )
        project.record(
            [
                project.events.make(
                    "manuscript.audit_drawn",
                    payload,
                    project.system_actor(),
                    refs=[audit_id, manuscript_id, *payload.verdict_ids],
                )
            ]
        )
        return audit_id


def record_audit(
    project: Project,
    verdict_id: str,
    label: AuditLabel,
    note: str | None,
    *,
    actor: Actor,
    channel: Channel = Channel.CLI,
) -> str:
    """Record a human's label on one sampled verdict and return the event id. Refused, with nothing
    written: an agent (`actor`), a relay from a pass session (`channel`), a verdict in no sample
    (`verdict_id`), a long note or one copying the manuscript (`note`)."""
    with project.index.exclusive():
        project.index.sync()
        issues = audit_core.human_gate(project, actor, channel, noun="draft-label", gate_id=GATE)
        with project.index.connect() as conn:
            sampled = conn.execute(
                text(
                    "SELECT i.audit_id, a.manuscript_id FROM manuscript_audit_items i "
                    "JOIN manuscript_audits a ON a.audit_id = i.audit_id "
                    "WHERE i.verdict_id = :v ORDER BY i.audit_id DESC"
                ),
                {"v": verdict_id},
            ).first()
        if sampled is None:
            issues.append(ValidationIssue("verdict_id", "not in an audit sample"))
        if note is not None and len(note) > NOTE_MAX_CHARS:
            issues.append(ValidationIssue("note", f"at most {NOTE_MAX_CHARS} characters"))
        if issues or sampled is None:
            raise FactoryValidationError(issues)
        audit_id, manuscript_id = str(sampled[0]), str(sampled[1])
        refuse_echo(project, require_manuscript(project, manuscript_id), note)
        payload = ManuscriptAudited(
            audit_id=audit_id,
            verdict_id=verdict_id,
            label=label,
            note=note or None,
            channel=channel,
        )
        event = project.events.make(
            "manuscript.audited", payload, actor, refs=[audit_id, verdict_id, manuscript_id]
        )
        project.record([event])
        return event.id


def audit_report(project: Project, manuscript_id: str) -> DraftAuditReport:
    """Every sample of the manuscript read together, for the researcher. The rate is incorrect /
    labelled, undefined until a verdict is labelled."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT i.label, {LIVE_VERDICT} FROM manuscript_audit_items i "
                "JOIN manuscript_audits a ON a.audit_id = i.audit_id "
                "JOIN manuscript_verdicts v ON v.verdict_id = i.verdict_id "
                "WHERE a.manuscript_id = :m"
            ),
            {"m": manuscript_id},
        ).all()
        labels = [None if r[0] is None else str(r[0]) for r in rows if r[1]]
        outdated = bool(labels) and audit_due(conn, manuscript_id)
    labelled = [x for x in labels if x is not None]
    incorrect = sum(1 for x in labelled if x == AuditLabel.INCORRECT.value)
    rate = incorrect / len(labelled) if labelled else None
    return DraftAuditReport(
        drawn=len(labels),
        all_drawn=len(rows),
        labelled=len(labelled),
        incorrect=incorrect,
        rate=rate,
        above_ceiling=None if rate is None else rate > DRAFT_VERIFY_ERROR_CEILING,
        outdated=outdated,
    )


def audit_sheet(project: Project, manuscript_id: str) -> list[tuple[str, str, int, str | None]]:
    """(audit id, verdict id, ordinal, label) of every sampled verdict, for the researcher."""
    project.index.sync()
    with project.index.connect() as conn:
        return [
            (str(r[0]), str(r[1]), int(r[2]), None if r[3] is None else str(r[3]))
            for r in conn.execute(
                text(
                    "SELECT i.audit_id, i.verdict_id, v.ordinal, i.label "
                    "FROM manuscript_audit_items i "
                    "JOIN manuscript_audits a ON a.audit_id = i.audit_id "
                    "JOIN manuscript_verdicts v ON v.verdict_id = i.verdict_id "
                    "WHERE a.manuscript_id = :m ORDER BY i.audit_id, i.verdict_id"
                ),
                {"m": manuscript_id},
            )
        ]
