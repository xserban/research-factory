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
from typing import Literal

from pydantic import Field, ValidationError
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.model.screening import AuditLabelled, AuditSampled, Channel, ScreeningPhase
from factory.modules.presets import Enforcement, enforcement
from factory.services import audit_core, passes
from factory.services.agreement import AgreedWork, agreed_works, screen_agreement
from factory.services.audit_core import AuditPopulation
from factory.services.context import Project
from factory.services.human_channel import require_human_channel
from factory.services.protocol import current_protocol
from factory.services.screening import decision_events, live_decisions
from factory.services.screening_stats import (
    AUDIT_ERROR_CEILING,
    AuditRates,
    audit_error_rates,
    audit_size,
    draw_audit,
)
from factory.services.seeds import _rigor_mode
from factory.services.stages import require_pass_stage, screening_plan
from factory.services.work_ref import resolve_work_id


class AuditItemView(StrictModel):
    """One sampled work: the agreed verdict, its cited criteria and the human's label, if any."""

    work_id: str
    agreed_verdict: Literal["include", "exclude"]
    criteria: list[str]
    human_verdict: Literal["include", "exclude"] | None


class AuditReport(StrictModel):
    audit_id: str
    sample_size: int
    labelled: int
    rates: AuditRates
    ceiling: float
    above_ceiling: bool
    enforced: bool
    criteria_implicated: list[str]
    items: list[AuditItemView] = Field(default_factory=list)


def audit_sample(
    project: Project,
    actor: Actor,
    *,
    random_seed: int | None = None,
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT,
    top_up: bool = False,
) -> AuditSampled:
    """Draw and record an audit sample of the agreed works of `stage`; return the event payload.

    Refused, with nothing written, when the actor is not human, the seed is out of range, the passes
    do not yet agree (see `screen_agreement`), there is no agreed work, an audit of the current
    agreed set is already open, or, on a hosted project, the person is a member of either pass of
    the stage (the sample shows both passes' decisions).

    With `top_up` (a living review's update) the sample instead extends the previous audit of the
    stage: it draws `audit_shortfall` works, 3:1 as always, from the works agreed since that audit
    was drawn, never one already sampled. Refused (field `top_up`) when the stage has no previous
    audit, the previous audit has unlabelled items, there is no shortfall, or no work has been
    agreed since.
    """
    require_pass_stage(stage)
    seed, seed_issues = audit_core.validate_seed(random_seed)
    with project.index.exclusive():
        project.index.sync()
        passes.require_outside_passes(project, actor.user, stage)
        issues: list[ValidationIssue] = []
        protocol = current_protocol(project)
        if protocol is not None:
            screening_plan(protocol, stage)  # refuses full text without a declared plan
        issues.extend(audit_core.human_gate(project, actor, Channel.CLI, noun="sample"))
        issues.extend(seed_issues)
        if issues:
            raise FactoryValidationError(issues)
        if not top_up and _living_with_audit(project, stage):
            raise _refuse_top_up(
                "a cycle has run since the audit: extend it with a top-up (audit sample "
                "--top-up); a full redraw would drop its labels"
            )
        screen_agreement(project, actor, stage=stage)
        agreed = agreed_works(project, stage=stage)
        if not agreed:
            raise _refuse("there are no agreed dual-coded works to audit")
        if not top_up:
            audit_core.refuse_reopen(_last_population_digest(project, stage), _population(agreed))
        if protocol is None:  # unreachable once screen_agreement has passed
            raise _refuse("record a protocol first")
        plan = screening_plan(protocol, stage)
        pool = agreed
        previous: str | None = None
        size = audit_size(len(agreed), plan.audit_fraction, plan.audit_minimum)
        if top_up:
            previous = _last_audit(project, stage)
            pool = _newly_agreed(project, stage, agreed, previous)
            size = _top_up_size(project, stage, size, pool)
        exclusions = sorted(w for w, item in pool.items() if item.verdict == "exclude")
        inclusions = sorted(w for w, item in pool.items() if item.verdict == "include")
        drawn = draw_audit(exclusions, inclusions, size, random.Random(seed))
        payload = AuditSampled(
            audit_id=project.ids.new("aud"),
            work_ids=tuple(drawn),
            random_seed=seed,
            population=len(agreed),
            exclusions=len(set(drawn) & set(exclusions)),
            inclusions=len(set(drawn) & set(inclusions)),
            stage=stage,
            top_up_of=previous,
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
    verdict, an MCP-relayed label from a session that has joined a pass, or, on a hosted project, a
    member of either pass of the audit's stage.
    """
    with project.index.exclusive():
        project.index.sync()
        require_human_channel(project, actor, channel, "audit-label")
        work_id = resolve_work_id(project, work_id)
        issues = audit_core.human_gate(
            project, actor, channel, noun="screening-label", gate_id="screening.audit_label"
        )
        stage = _audit_stage(project, audit_id)
        if stage is None:
            issues.append(ValidationIssue("audit_id", "unknown audit"))
        else:
            passes.require_outside_passes(project, actor.user, stage)
            if not _sampled(project, audit_id, work_id):
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
        # A top-up pools its items with those of every audit it extends.
        chain = _chain(conn, str(latest[0]))
        items = conn.execute(
            text(
                "SELECT work_id, agreed_verdict, agreed_criteria, human_verdict FROM audit_items "
                "WHERE audit_id IN :a ORDER BY work_id"
            ).bindparams(bindparam("a", expanding=True)),
            {"a": chain},
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
    verdict = audit_core.ceiling_verdict(
        rates.false_exclusion,
        AUDIT_ERROR_CEILING,
        enforced=(
            enforcement(_rigor_mode(project), "screening.audit_ceiling") is Enforcement.ENFORCED
        ),
    )
    return AuditReport(
        audit_id=str(latest[0]),
        sample_size=len(items),
        labelled=rates.labelled,
        rates=rates,
        ceiling=verdict.ceiling,
        above_ceiling=verdict.above,
        enforced=verdict.enforced,
        criteria_implicated=implicated,
        items=[
            AuditItemView(
                work_id=str(work_id),
                agreed_verdict="include" if agreed_v == "include" else "exclude",
                criteria=str(criteria).split(",") if criteria else [],
                human_verdict=None
                if human_v is None
                else ("include" if human_v == "include" else "exclude"),
            )
            for work_id, agreed_v, criteria, human_v in items
        ],
    )


def audit_outstanding(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> bool:
    """Whether the agreed set of `stage` is non-empty and no audit of the stage has sampled its
    current population.

    The population is the agreed set's work ids and verdicts (`audit_sample`'s digest). A set that
    changed since the last audit is outstanding again. False when there is nothing to audit.

    Once an audit exists and a watch cycle has run (a living review), it is outstanding only by
    its shortfall (`audit_shortfall`): a changed agreed set is topped up, never redrawn.
    """
    require_pass_stage(stage)
    project.index.sync()
    agreed = agreed_works(project, stage=stage)
    if not agreed:
        return False
    if _living_with_audit(project, stage):
        return audit_shortfall(project, stage=stage) > 0
    return _last_population_digest(project, stage) != _population(agreed).digest


def audit_shortfall(
    project: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT
) -> int:
    """How many works a top-up would draw at `stage`: the audit size now over the agreed set, less
    the works already sampled in any audit of the stage. 0 when the stage has no audit yet (its
    first audit is `audit_outstanding`) or nothing is agreed. Computed, never stored."""
    require_pass_stage(stage)
    project.index.sync()
    protocol = current_protocol(project)
    if protocol is None or not _audit_ids(project, stage):
        return 0
    agreed = agreed_works(project, stage=stage)
    if not agreed:
        return 0
    plan = screening_plan(protocol, stage)
    target = audit_size(len(agreed), plan.audit_fraction, plan.audit_minimum)
    return max(0, target - len(_sampled_works(project, stage)))


# --- Top-up ---


def _living_with_audit(project: Project, stage: ScreeningStage) -> bool:
    """Whether `stage` has an audit and a watch cycle has run: audits are then topped up."""
    if not _audit_ids(project, stage):
        return False
    with project.index.connect() as conn:
        return bool(conn.execute(text("SELECT count(*) FROM watch_cycles")).scalar_one())


def _refuse_top_up(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("top_up", reason)])


def _last_audit(project: Project, stage: ScreeningStage) -> str:
    """The latest audit of `stage`, which a top-up extends; refused when it has none or when it
    still has unlabelled items."""
    ids = _audit_ids(project, stage)
    if not ids:
        raise _refuse_top_up("there is no previous audit of this stage to top up")
    with project.index.connect() as conn:
        unlabelled = conn.execute(
            text("SELECT count(*) FROM audit_items WHERE audit_id = :a AND human_verdict IS NULL"),
            {"a": ids[-1]},
        ).scalar_one()
    if unlabelled:
        raise _refuse_top_up(f"the previous audit has {unlabelled} unlabelled item(s)")
    return ids[-1]


def _newly_agreed(
    project: Project,
    stage: ScreeningStage,
    agreed: dict[str, AgreedWork],
    previous: str,
) -> dict[str, AgreedWork]:
    """The agreed works whose later live decision was recorded after `previous` was drawn and
    that no audit of the stage has sampled."""
    with project.index.connect() as conn:
        cut = str(
            conn.execute(
                text("SELECT event_id FROM audit_events WHERE audit_id = :a"), {"a": previous}
            ).scalar_one()
        )
    events = decision_events(project)
    latest: dict[str, str] = {}
    for decision in live_decisions(project, stage=stage):
        if decision.phase is not ScreeningPhase.SCREENING:
            continue
        at = events.get(decision.decision_id, "")
        latest[decision.work_id] = max(latest.get(decision.work_id, ""), at)
    sampled = _sampled_works(project, stage)
    return {
        work: item
        for work, item in agreed.items()
        if latest.get(work, "") > cut and work not in sampled
    }


def _top_up_size(
    project: Project, stage: ScreeningStage, size_now: int, pool: dict[str, AgreedWork]
) -> int:
    shortfall = max(0, size_now - len(_sampled_works(project, stage)))
    if shortfall == 0:
        raise _refuse_top_up("the works already sampled meet the audit size")
    if not pool:
        raise _refuse_top_up("no work has been agreed since the previous audit")
    return shortfall


def _audit_ids(project: Project, stage: ScreeningStage) -> list[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT audit_id FROM audits WHERE stage = :stage ORDER BY audit_id"),
            {"stage": stage.value},
        ).all()
    return [str(r[0]) for r in rows]


def _sampled_works(project: Project, stage: ScreeningStage) -> set[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT i.work_id FROM audit_items i JOIN audits a"
                " ON a.audit_id = i.audit_id WHERE a.stage = :stage"
            ),
            {"stage": stage.value},
        ).all()
    return {str(r[0]) for r in rows}


def _chain(conn: Connection, audit_id: str) -> list[str]:
    """`audit_id` and every audit it tops up, newest first."""
    chain = [audit_id]
    while True:
        row = conn.execute(
            text("SELECT top_up_of FROM audit_top_ups WHERE audit_id = :a"), {"a": chain[-1]}
        ).one_or_none()
        if row is None or str(row[0]) in chain:
            return chain
        chain.append(str(row[0]))


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


def _population(agreed: dict[str, AgreedWork]) -> AuditPopulation:
    """The agreed set of a stage as an audit population: each work with its agreed verdict."""
    return AuditPopulation.of((work, item.verdict) for work, item in agreed.items())


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(".".join(str(part) for part in err["loc"]) or "label", str(err["msg"]))
        for err in exc.errors()
    ]
