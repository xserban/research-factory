"""The audit of agreed decisions: a stratified sample, human labels, error rates (R-37, ruling 3).

`audit_sample` draws a sample of the agreed dual-coded works: about 75% agreed exclusions and the
rest agreed inclusions, sized by the protocol's `audit_fraction` and `audit_minimum`. It is
human-only and refused until the passes agree (`screen_agreement` must succeed). One audit is open
at a time: a new sample is refused while the last audit's population (the agreed set, work ids and
verdicts) is the agreed set now. A protocol amendment or new decisions that change the set allow a
new sample.

`audit_record` stores a human label on a sampled work. An MCP-relayed label is refused from a
session that has joined a pass, as for calibration.

`audit_report` reads the latest audit: its error rates, the false-exclusion ceiling, and the
agreed-exclusion criteria the human overturned. Counts are computed here, never supplied.

`audit_sample`, `audit_report` and `audit_outstanding` take a keyword `stage` (default
title/abstract; `either` is refused on field `stage`). An audit belongs to the stage of its sample:
its agreed set, its open/closed state and its report are those of that stage. `audit_record` takes
the stage of the audit it labels.

Invariants:
- Refusals raise FactoryValidationError and write nothing.
- Population strata used to weight the error rates are the live agreed set; when that set is no
  longer the audit's population, the weighted rate is not reported.
"""

from __future__ import annotations

import random
import secrets

from pydantic import ValidationError
from sqlalchemy import text

from factory.canonical import population_digest
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage
from factory.model.screening import AuditLabelled, AuditSampled, Channel
from factory.services.agreement import agreed_works, screen_agreement
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.screening_stats import (
    AUDIT_ERROR_CEILING,
    AuditRates,
    audit_error_rates,
    audit_size,
    draw_audit,
)
from factory.services.seeds import _rigor_mode
from factory.services.stages import require_pass_stage, screening_plan


class AuditReport(StrictModel):
    audit_id: str
    sample_size: int
    labelled: int
    rates: AuditRates
    ceiling: float
    above_ceiling: bool
    enforced: bool
    criteria_implicated: list[str]


def audit_sample(
    project: Project,
    actor: Actor,
    *,
    random_seed: int | None = None,
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT,
) -> AuditSampled:
    """Draw and record an audit sample of the agreed works of `stage`; return the event payload.

    Refused, with nothing written, when the actor is not human, the seed is out of range, the passes
    do not yet agree (see `screen_agreement`), there is no agreed work, or an audit of the current
    agreed set is already open.
    """
    require_pass_stage(stage)
    seed = secrets.randbits(32) if random_seed is None else random_seed
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        protocol = current_protocol(project)
        if protocol is not None:
            screening_plan(protocol, stage)  # refuses full text without a declared plan
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "audit samples are drawn by a human"))
        if not 0 <= seed < 2**32:
            issues.append(ValidationIssue("random_seed", "must be an integer from 0 to 2**32 - 1"))
        if issues:
            raise FactoryValidationError(issues)
        screen_agreement(project, actor, stage=stage)
        agreed = agreed_works(project, stage=stage)
        if not agreed:
            raise _refuse("there are no agreed dual-coded works to audit")
        digest = population_digest((work, item.verdict) for work, item in agreed.items())
        if _last_population_digest(project, stage) == digest:
            raise _refuse("an audit of this agreed set is open; a new one waits for a change to it")
        if protocol is None:  # unreachable once screen_agreement has passed
            raise _refuse("record a protocol first")
        plan = screening_plan(protocol, stage)
        exclusions = sorted(w for w, item in agreed.items() if item.verdict == "exclude")
        inclusions = sorted(w for w, item in agreed.items() if item.verdict == "include")
        size = audit_size(len(agreed), plan.audit_fraction, plan.audit_minimum)
        drawn = draw_audit(exclusions, inclusions, size, random.Random(seed))
        payload = AuditSampled(
            audit_id=project.ids.new("aud"),
            work_ids=tuple(drawn),
            random_seed=seed,
            population=len(agreed),
            exclusions=len(set(drawn) & set(exclusions)),
            inclusions=len(set(drawn) & set(inclusions)),
            stage=stage,
        )
        project.record([project.events.make("audit.sampled", payload, actor)])
    return payload


def audit_record(
    project: Project,
    actor: Actor,
    audit_id: str,
    work_id: str,
    verdict: str,
    criterion: str | None,
    channel: Channel,
) -> str:
    """Record a human's label on one sampled work and return the event id.

    The criterion, when given, is a criterion of the current protocol and is stored
    version-qualified; an exclusion needs an EX criterion. Refused, with nothing written, for an
    agent actor, an unknown audit, a work outside the sample, an unknown criterion, an invalid
    verdict, or an MCP-relayed label from a session that has joined a pass.
    """
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "audit labels are human acts"))
        stage = _audit_stage(project, audit_id)
        if stage is None:
            issues.append(ValidationIssue("audit_id", "unknown audit"))
        elif not _sampled(project, audit_id, work_id):
            issues.append(ValidationIssue("work_id", "not in this audit sample"))
        protocol = current_protocol(project)
        qualified: str | None = None
        if criterion is not None:
            if protocol is None:
                issues.append(ValidationIssue("criterion", "record a protocol first"))
            elif criterion not in {c.id for c in protocol.spec.criteria}:
                issues.append(ValidationIssue("criterion", "not a criterion of the protocol"))
            else:
                qualified = f"{protocol.protocol_id}:{criterion}"
        if channel is Channel.MCP and _is_pass_session(project, actor.session):
            issues.append(ValidationIssue("channel", "this session has joined a pass"))
        if issues:
            raise FactoryValidationError(issues)
        try:
            payload = AuditLabelled(
                audit_id=audit_id,
                work_id=work_id,
                verdict=verdict,
                criterion=qualified,
                channel=channel,
                stage=stage or ScreeningStage.TITLE_ABSTRACT,
            )
        except ValidationError as exc:
            raise FactoryValidationError(_issues(exc)) from exc
        event = project.events.make("audit.labelled", payload, actor)
        project.record([event])
    return event.id


def audit_report(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> AuditReport | None:
    """The latest audit's error rates and flags at `stage`; None when no audit has been sampled
    there."""
    require_pass_stage(stage)
    project.index.sync()
    with project.index.connect() as conn:
        latest = conn.execute(
            text(
                "SELECT audit_id, pop_exclusions, pop_inclusions FROM audits "
                "WHERE stage = :stage ORDER BY audit_id DESC LIMIT 1"
            ),
            {"stage": stage.value},
        ).one_or_none()
        if latest is None:
            return None
        items = conn.execute(
            text(
                "SELECT work_id, agreed_verdict, agreed_criteria, human_verdict FROM audit_items "
                "WHERE audit_id = :a ORDER BY work_id"
            ),
            {"a": str(latest[0])},
        ).all()
    # The population and the cited criteria were fixed when the sample was drawn, so later changes
    # to the agreed set leave the report as it was.
    labelled = [
        (agreed_v == "include", human_v == "include")
        for _, agreed_v, _, human_v in items
        if human_v is not None
    ]
    rates = audit_error_rates(labelled, int(latest[1]), int(latest[2]))
    implicated = sorted(
        {
            c
            for _, agreed_v, criteria, human_v in items
            if agreed_v == "exclude" and human_v == "include" and criteria
            for c in str(criteria).split(",")
        }
    )
    rate = rates.false_exclusion
    return AuditReport(
        audit_id=str(latest[0]),
        sample_size=len(items),
        labelled=rates.labelled,
        rates=rates,
        ceiling=AUDIT_ERROR_CEILING,
        above_ceiling=rate is not None and rate > AUDIT_ERROR_CEILING,
        enforced=_rigor_mode(project) is RigorMode.SYSTEMATIC,
        criteria_implicated=implicated,
    )


def audit_outstanding(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> bool:
    """Whether the agreed set of `stage` is non-empty and no audit of the stage has sampled its
    current population.

    The population is the agreed set's work ids and verdicts (`audit_sample`'s digest). A set that
    changed since the last audit is outstanding again. False when there is nothing to audit.
    """
    require_pass_stage(stage)
    project.index.sync()
    agreed = agreed_works(project, stage=stage)
    if not agreed:
        return False
    digest = population_digest((work, item.verdict) for work, item in agreed.items())
    return _last_population_digest(project, stage) != digest


# --- Reading the audit tables ---


def _last_population_digest(project: Project, stage: ScreeningStage) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT population_digest FROM audits WHERE stage = :stage "
                "ORDER BY audit_id DESC LIMIT 1"
            ),
            {"stage": stage.value},
        ).one_or_none()
    return None if row is None else str(row[0])


def _audit_stage(project: Project, audit_id: str) -> ScreeningStage | None:
    """The stage of a sampled audit; None for an unknown audit."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT stage FROM audits WHERE audit_id = :a"), {"a": audit_id}
        ).one_or_none()
    return None if row is None else ScreeningStage(str(row[0]))


def _sampled(project: Project, audit_id: str, work_id: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM audit_items WHERE audit_id = :a AND work_id = :w"),
            {"a": audit_id, "w": work_id},
        ).one_or_none()
    return row is not None


def _is_pass_session(project: Project, session: str) -> bool:
    """Whether the session joined a pass at any stage (it must not relay an audit label)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pass_sessions WHERE session = :session"), {"session": session}
        ).one_or_none()
    return row is not None


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(".".join(str(part) for part in err["loc"]) or "label", str(err["msg"]))
        for err in exc.errors()
    ]
