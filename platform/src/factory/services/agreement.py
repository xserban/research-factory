"""Agreement between the two screening passes, κ per criterion, human resolution, final outcomes
(R-36, R-38, ruling 1).

`screen_agreement` is read-only. It reports κ and the disagreements only once both passes have
finished: no open or claimed screening task is left (obsolete tasks aside), and every work in each
pass's queue has a live, non-stale screening decision under the current protocol. It refuses while
a session has joined both passes, or the two passes share a model. Only those decisions count;
calibration works are screened in the calibration phase and are left out.

A work's binary outcome is `promote` (include, cannot-assess) or exclude. `unsure` in either pass,
or differing outcomes, is a disagreement for the human (reason `unsure` or `outcome`). Exclusions
citing different criteria agree on the outcome and lower only the per-criterion κ.

`resolve_disagreement` records a human verdict on a disputed work, or on an `unsure` single-pass
work. It is human-only, and an MCP-relayed resolution is refused from a session that has joined a
pass.

`final_outcomes` gives each work of the corpus its outcome: a calibration work takes the human's
label; any other work takes its resolution, else the agreed outcome, else the single-pass outcome.
Anything undetermined is PENDING.

Every function takes a keyword `stage` (default title/abstract) and reads only that stage's
passes, decisions, calibration, resolutions and sessions; `either` is refused on field `stage`.
At full text the plan is the protocol's `full_text_screening` (refused on field
`full_text_screening` until declared) and the works are the promoted ones: a work whose
title/abstract final outcome is INCLUDED. `final_outcomes(stage=FULL_TEXT)` leaves every other work
PENDING.

Invariants:
- Refusals raise FactoryValidationError with field `passes` (screen_agreement) and write nothing.
- Every stored criterion is version-qualified against the current protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.protocol import CriterionKind, ScreeningPlan, ScreeningStage
from factory.model.screening import (
    Channel,
    DecisionRecorded,
    DisagreementResolved,
    Framing,
    PassJoined,
    PassLabel,
    ScreeningPhase,
    Verdict,
)
from factory.model.task import TaskStatus
from factory.services.calibration import calibration_items, calibration_labels, stage_population
from factory.services.call_memo import memoised
from factory.services.context import Project
from factory.services.conversions import conversion_document
from factory.services.passes import require_not_pass_session, shared_refusal
from factory.services.protocol import ProtocolVersion, current_protocol, lineage_through
from factory.services.screening import (
    live_decisions,
    obsolete_tasks,
    pass_b_sample,
    stale_screening_decisions,
)
from factory.services.screening_stats import cohen_kappa, kappa_by_criterion
from factory.services.search import list_works
from factory.services.stages import require_pass_stage, screening_plan, task_kind

TA = ScreeningStage.TITLE_ABSTRACT


class Outcome(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    PENDING = "pending"


class PassConfig(StrictModel):
    pass_label: PassLabel
    framing: Framing
    criterion_order: Literal["protocol", "reversed"]
    random_seed: int
    sessions: list[str]
    models: list[str]


class DecisionView(StrictModel):
    verdict: Verdict
    criterion: str | None
    quote: str
    rationale: str
    anchor: str | None = None
    """Full text only: the anchor the quote was verified in (None at title/abstract)."""
    conversion_id: str | None = None
    document_id: str | None = None


class Disagreement(StrictModel):
    work_id: str
    a: DecisionView
    b: DecisionView
    reason: Literal["outcome", "unsure"]


class Agreement(StrictModel):
    passes: list[PassConfig]
    n_dual: int
    kappa: float | None
    kappa_by_criterion: dict[str, float | None]
    kappa_floor: float | None
    below_floor: bool
    enforced: bool
    disagreements: list[Disagreement]
    single_pass: list[str]
    cannot_assess_rate: dict[str, float | None]


@dataclass(frozen=True)
class _Screen:
    """The screening state under the current protocol, read from the projection.

    `known` is False while the works each pass screens cannot yet be told apart (pass B of a
    two-pass plan not yet opened, or pass A not opened); `dual` and `single` are then empty.
    `decided` holds each pass's live, non-stale screening decisions by work. `resolutions` maps a
    resolved work to the human's verdict."""

    protocol: ProtocolVersion
    stage: ScreeningStage
    plan: ScreeningPlan
    ordinary: frozenset[str]
    queues: dict[PassLabel, frozenset[str] | None]
    decided: dict[PassLabel, dict[str, DecisionRecorded]]
    resolutions: dict[str, Verdict]
    known: bool
    dual: frozenset[str]
    single: frozenset[str]


def screen_agreement(project: Project, actor: Actor, *, stage: ScreeningStage = TA) -> Agreement:
    """The agreement of the two passes: κ, per-criterion κ, disagreements, single-pass works and
    the cannot-assess rate per criterion (R-36, R-38).

    Refused, with nothing written, while either pass has an open or claimed screening task, while
    a work in either pass's queue lacks a live screening decision, when the passes share a session
    or a model, when the protocol plans one pass, or when a pass has not been opened.
    """
    require_pass_stage(stage)
    with project.index.exclusive():
        project.index.sync()
        screen = _load(project, stage)
        if screen is None:
            raise FactoryValidationError([ValidationIssue("protocol", "record a protocol first")])
        if screen.plan.passes == 1:
            raise _refuse("the protocol plans one screening pass; agreement needs two")
        for label in PassLabel:
            if screen.queues[label] is None:
                raise _refuse(f"pass {label.value} has not been opened")
        _refuse_shared(project, stage)
        for label in PassLabel:
            open_tasks = _blocking_tasks(project, label, stage)
            if open_tasks:
                raise _refuse(
                    f"pass {label.value} has {len(open_tasks)} open or claimed screening "
                    "task(s); agreement waits until both passes finish"
                )
        for label in PassLabel:
            queue = screen.queues[label] or frozenset()
            missing = queue - screen.decided[label].keys()
            if missing:
                raise _refuse(
                    f"pass {label.value}: {len(missing)} works still lack a live screening "
                    "decision under the current protocol"
                )
        return _agreement(project, screen)


def resolve_disagreement(
    project: Project,
    actor: Actor,
    work_id: str,
    verdict: Literal["include", "exclude"],
    criterion: str | None,
    reason: str,
    channel: Channel,
    *,
    stage: ScreeningStage = TA,
) -> str:
    """Record the human's verdict on a disputed work of `stage` and return the event id (R-36).

    The work must be an unresolved disagreement, or an `unsure` single-pass work. The criterion,
    when given, is a criterion of the current protocol and is stored version-qualified; an
    exclusion needs an EX criterion. Refused, with nothing written, for an agent actor, a work
    that is not open for resolution, an unknown criterion, an invalid verdict or reason, or an
    MCP-relayed resolution from a session that has joined a pass.
    """
    require_pass_stage(stage)
    with project.index.exclusive():
        project.index.sync()
        screen = _load(project, stage)
        if screen is None:
            raise FactoryValidationError([ValidationIssue("protocol", "record a protocol first")])
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "disagreements are resolved by a human"))
        issues.extend(require_not_pass_session(project, actor, channel))
        if work_id not in _open_for_resolution(screen):
            issues.append(
                ValidationIssue(
                    "work_id",
                    "is not an unresolved disagreement or an unsure single-pass work",
                )
            )
        protocol = screen.protocol
        qualified: str | None = None
        if criterion is not None:
            if criterion not in {c.id for c in protocol.spec.criteria}:
                issues.append(ValidationIssue("criterion", "not a criterion of the protocol"))
            else:
                qualified = f"{protocol.protocol_id}:{criterion}"
        if issues:
            raise FactoryValidationError(issues)
        try:
            payload = DisagreementResolved(
                work_id=work_id,
                verdict=verdict,
                criterion=qualified,
                reason=reason,
                channel=channel,
                stage=stage,
            )
        except ValidationError as exc:
            raise FactoryValidationError(_issues(exc)) from exc
        event = project.events.make("screening.disagreement_resolved", payload, actor)
        project.record([event])
    return event.id


class AgreedWork(StrictModel):
    """A dual-coded work the passes agree on: its outcome, and for an exclusion the bare criteria
    either pass cited (sorted)."""

    verdict: Literal["include", "exclude"]
    criteria: list[str]


def agreed_works(project: Project, *, stage: ScreeningStage = TA) -> dict[str, AgreedWork]:
    """The ordinary works of `stage` both passes decided and agree on, with their agreed outcome.

    Agreement is read-only and needs no finished passes: a work counts when both passes hold a live,
    non-stale decision under the current protocol, neither verdict is `unsure`, and the outcomes
    match. Calibration works are left out. Empty before a protocol is recorded or while a pass is
    unopened.
    """
    require_pass_stage(stage)
    project.index.sync()
    screen = _load(project, stage)
    if screen is None or not screen.known:
        return {}
    agreed: dict[str, AgreedWork] = {}
    for work in sorted(screen.dual):
        a, b = screen.decided[PassLabel.A].get(work), screen.decided[PassLabel.B].get(work)
        if a is None or b is None or _disagreement(a.verdict, b.verdict) is not None:
            continue
        verdict: Literal["include", "exclude"] = "include" if a.verdict.promotes else "exclude"
        criteria = sorted({c for c in (_exclusion(a), _exclusion(b)) if c is not None})
        agreed[work] = AgreedWork(verdict=verdict, criteria=criteria)
    return agreed


@memoised
def final_outcomes(project: Project, *, stage: ScreeningStage = TA) -> dict[str, Outcome]:
    """The outcome of every work of the corpus at `stage`: the human's label for a calibration
    work; for any other work its resolution, else the agreed outcome of both passes, else the
    single-pass outcome of pass A. An `unsure` verdict, a disagreement, or a missing decision is
    PENDING. At full text only the promoted works (title/abstract INCLUDED) have an outcome; every
    other work is PENDING."""
    require_pass_stage(stage)
    labels = calibration_labels(project, stage=stage)
    calibration = set(calibration_items(project, stage=stage))
    screen = _load(project, stage)
    population = stage_population(project, stage)
    outcomes: dict[str, Outcome] = {}
    for work in sorted(work.id for work in list_works(project)):
        if work not in population:
            outcomes[work] = Outcome.PENDING
        elif work in calibration:
            outcomes[work] = _label_outcome(labels.get(work))
        elif screen is None:
            outcomes[work] = Outcome.PENDING
        else:
            outcomes[work] = _outcome(screen, work)
    return outcomes


def exclusion_criteria(project: Project, *, stage: ScreeningStage = TA) -> dict[str, str | None]:
    """The criterion each excluded work is excluded under (bare), for every work `final_outcomes`
    marks EXCLUDED. The same precedence applies: a calibration label's criterion, else a
    resolution's, else the first sorted criterion cited by the live, non-stale screening exclusions
    of the current protocol. None when the deciding label, resolution or decision names none.
    Works with any other outcome are absent. Read at `stage`."""
    require_pass_stage(stage)
    project.index.sync()
    outcomes = final_outcomes(project, stage=stage)
    calibration = set(calibration_items(project, stage=stage))
    with project.index.connect() as conn:
        labels = {
            str(work): _bare(criterion)
            for work, criterion in conn.execute(
                text("SELECT work_id, criterion FROM calibration_labels WHERE stage = :stage"),
                {"stage": stage.value},
            ).all()
        }
        resolved = {
            str(work): _bare(criterion)
            for work, criterion in conn.execute(
                text("SELECT work_id, criterion FROM resolutions WHERE stage = :stage"),
                {"stage": stage.value},
            ).all()
        }
    screen = _load(project, stage)
    cited: dict[str, set[str]] = {}
    if screen is not None:
        for label in PassLabel:
            for work, decision in screen.decided[label].items():
                criterion = _exclusion(decision)
                if criterion is not None:
                    cited.setdefault(work, set()).add(criterion)

    result: dict[str, str | None] = {}
    for work, outcome in outcomes.items():
        if outcome is not Outcome.EXCLUDED:
            continue
        if work in calibration:
            result[work] = labels.get(work)
        elif work in resolved:
            result[work] = resolved[work]
        else:
            result[work] = min(cited[work]) if work in cited else None
    return result


def agreement_summary(project: Project, *, stage: ScreeningStage = TA) -> Agreement | None:
    """The agreement of the two passes as the events stand, for reports (plan 5b).

    Refuses nothing: `screen_agreement` keeps the refusals, and any surface that exposes this to a
    pass session must apply them. None while the passes cannot be compared: no protocol, a
    one-pass plan, a pass not opened, or a dual-coded work lacking a live decision in either pass.
    """
    require_pass_stage(stage)
    project.index.sync()
    screen = _load(project, stage)
    if screen is None or not screen.known or screen.plan.passes == 1:
        return None
    for work in screen.dual:
        if work not in screen.decided[PassLabel.A] or work not in screen.decided[PassLabel.B]:
            return None
    return _agreement(project, screen)


def single_pass_works(project: Project, *, stage: ScreeningStage = TA) -> list[str]:
    """The ordinary works whose final outcome rests on pass A alone, sorted (R-33).

    In a two-pass plan these are the works outside pass B's queue; in a one-pass plan, every
    ordinary work. A work counts when `final_outcomes` gives it an outcome (include or exclude)
    from a live decision, not from a human resolution. Empty before a protocol is recorded or
    while pass B is not opened.
    """
    require_pass_stage(stage)
    project.index.sync()
    screen = _load(project, stage)
    if screen is None or not screen.known:
        return []
    single = screen.ordinary if screen.plan.passes == 1 else screen.single
    outcomes = final_outcomes(project, stage=stage)
    return sorted(
        work
        for work in single
        if work not in screen.resolutions
        and outcomes.get(work) in (Outcome.INCLUDED, Outcome.EXCLUDED)
    )


class PassProgress(StrictModel):
    """One pass's ordinary queue: works queued, those with a live non-stale decision, and those
    remaining. All three are None when the pass is not open."""

    queued: int | None
    decided: int
    remaining: int | None


def pass_progress(project: Project, *, stage: ScreeningStage = TA) -> dict[str, PassProgress]:
    """Each pass's progress over its ordinary queue at `stage`; calibration works are counted by
    the gate."""
    require_pass_stage(stage)
    project.index.sync()
    screen = _load(project, stage)
    progress: dict[str, PassProgress] = {}
    for label in PassLabel:
        queue = None if screen is None else screen.queues[label]
        if screen is None or queue is None:
            progress[label.value] = PassProgress(queued=None, decided=0, remaining=None)
            continue
        decided = sum(1 for work in queue if work in screen.decided[label])
        progress[label.value] = PassProgress(
            queued=len(queue), decided=decided, remaining=len(queue) - decided
        )
    return progress


# --- Reading the screening state ---


def _load(project: Project, stage: ScreeningStage = TA) -> _Screen | None:
    """The screening state of `stage` under the current protocol; None before a protocol is
    recorded. Raises on field `full_text_screening` at full text without a declared plan."""
    protocol = current_protocol(project)
    if protocol is None:
        return None
    plan = screening_plan(protocol, stage)
    calibration = set(calibration_items(project, stage=stage))
    corpus = stage_population(project, stage)
    ordinary = frozenset(corpus - calibration)
    queues = {label: _queue(project, label, corpus, calibration, stage) for label in PassLabel}
    decided = _decided(project, protocol.protocol_id, stage)
    resolutions = _resolutions(project, stage)
    queue_a = queues[PassLabel.A]
    queue_b = queues[PassLabel.B]
    if plan.passes == 1:
        known = queue_a is not None
        dual: frozenset[str] = frozenset()
        single = queue_a or frozenset()
    elif queue_a is None or queue_b is None:
        known = False
        dual = single = frozenset()
    else:
        known = True
        dual = queue_a & queue_b
        single = queue_a - queue_b
    return _Screen(
        protocol=protocol,
        stage=stage,
        plan=plan,
        ordinary=ordinary,
        queues=queues,
        decided=decided,
        resolutions=resolutions,
        known=known,
        dual=dual,
        single=single,
    )


def _queue(
    project: Project,
    label: PassLabel,
    corpus: set[str],
    calibration: set[str],
    stage: ScreeningStage = TA,
) -> frozenset[str] | None:
    """The ordinary works pass `label` screens at `stage`: its recorded sample, or the stage's
    population when the pass has none, less the calibration works (a full-text sample is also
    limited to the population now). None when the pass has not been opened."""
    with project.index.connect() as conn:
        opened = conn.execute(
            text("SELECT 1 FROM passes WHERE pass_label = :label AND stage = :stage"),
            {"label": label.value, "stage": stage.value},
        ).one_or_none()
    if opened is None:
        return None
    sample = pass_b_sample(project, stage=stage) if label is PassLabel.B else None
    base = corpus if sample is None else set(sample)
    if stage is not TA:
        base &= corpus
    return frozenset(base - calibration)


def _decided(
    project: Project, protocol_id: str, stage: ScreeningStage = TA
) -> dict[PassLabel, dict[str, DecisionRecorded]]:
    """Each pass's live, non-stale screening decisions at `stage` made under the protocol or an
    earlier version of its lineage, by work (decision 50: only the stale rules of R-15 discard a
    decision after an amendment)."""
    stale = stale_screening_decisions(project, stage=stage)
    versions = lineage_through(project, protocol_id)
    decided: dict[PassLabel, dict[str, DecisionRecorded]] = {label: {} for label in PassLabel}
    for decision in live_decisions(project, stage=stage):
        if (
            decision.phase is ScreeningPhase.SCREENING
            and decision.protocol_id in versions
            and decision.decision_id not in stale
        ):
            decided[decision.pass_label][decision.work_id] = decision
    return decided


def _resolutions(project: Project, stage: ScreeningStage = TA) -> dict[str, Verdict]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id, verdict FROM resolutions WHERE stage = :stage"),
            {"stage": stage.value},
        ).all()
    return {str(work_id): Verdict(str(verdict)) for work_id, verdict in rows}


def _blocking_tasks(project: Project, label: PassLabel, stage: ScreeningStage = TA) -> list[str]:
    """Open or claimed screening tasks of pass `label` at `stage` that are not obsolete."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT task_id FROM tasks WHERE kind = :kind AND status != :done"),
            {"kind": task_kind(stage, label), "done": TaskStatus.COMPLETED.value},
        ).all()
    obsolete = set(obsolete_tasks(project, label, stage=stage))
    return sorted(str(row[0]) for row in rows if str(row[0]) not in obsolete)


# --- Refusals ---


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])


def _refuse_shared(project: Project, stage: ScreeningStage = TA) -> None:
    """Refuse when one session joined both passes of `stage` or the passes share a model. The
    join events are read from the log: the projection keeps one join per session and stage, so a
    second join is invisible there. A session in pass A of one stage and pass B of the other is
    not shared."""
    joins: dict[PassLabel, set[str]] = {label: set() for label in PassLabel}
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type == "screening.pass_joined":
            payload = PassJoined.model_validate(event.payload)
            if payload.stage is stage:
                joins[payload.pass_label].add(payload.session)
    models = {label: _models(project, label, stage) for label in PassLabel}
    refusal = shared_refusal(joins, models, noun="screening")
    if refusal is not None:
        raise refusal


def _models(project: Project, label: PassLabel, stage: ScreeningStage = TA) -> set[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT model FROM pass_sessions WHERE pass_label = :label AND stage = :stage"),
            {"label": label.value, "stage": stage.value},
        ).all()
    return {str(row[0]) for row in rows}


# --- Agreement ---


def _agreement(project: Project, screen: _Screen) -> Agreement:
    plan = screen.plan
    decided_a = screen.decided[PassLabel.A]
    decided_b = screen.decided[PassLabel.B]
    disagreements: list[Disagreement] = []
    outcome_pairs: list[tuple[bool, bool]] = []
    criterion_pairs: list[tuple[str | None, str | None]] = []
    for work in sorted(screen.dual):
        a, b = decided_a[work], decided_b[work]
        outcome_pairs.append((a.verdict.promotes, b.verdict.promotes))
        criterion_pairs.append((_exclusion(a), _exclusion(b)))
        reason = _disagreement(a.verdict, b.verdict)
        if reason is not None and work not in screen.resolutions:
            disagreements.append(
                Disagreement(work_id=work, a=_view(project, a), b=_view(project, b), reason=reason)
            )
    criteria = screen.protocol.spec.criteria
    exclusion_ids = [
        c.id
        for c in criteria
        if c.kind is CriterionKind.EXCLUSION
        and (screen.stage is TA or c.applies_at in (screen.stage, ScreeningStage.EITHER))
    ]
    kappa = cohen_kappa(outcome_pairs)
    floor = plan.kappa_floor
    return Agreement(
        passes=[
            _pass_config(project, PassLabel.A, screen.stage),
            _pass_config(project, PassLabel.B, screen.stage),
        ],
        n_dual=len(outcome_pairs),
        kappa=kappa,
        kappa_by_criterion=kappa_by_criterion(criterion_pairs, exclusion_ids),
        kappa_floor=floor,
        below_floor=kappa is not None and floor is not None and kappa < floor,
        enforced=plan.kappa_enforced,
        disagreements=disagreements,
        single_pass=sorted(screen.single),
        cannot_assess_rate=_cannot_assess_rate(screen),
    )


def _cannot_assess_rate(screen: _Screen) -> dict[str, float | None]:
    """Per criterion applicable at the screen's stage: the share of the live screening decisions
    of both passes that are `cannot-assess` under that criterion (R-38). None when there are none.
    """
    decisions = [
        decision
        for label in PassLabel
        for work, decision in screen.decided[label].items()
        if work in screen.ordinary
    ]
    criteria = [
        c.id
        for c in screen.protocol.spec.criteria
        if c.applies_at in (screen.stage, ScreeningStage.EITHER)
    ]
    rates: dict[str, float | None] = {}
    for cid in criteria:
        named = sum(
            1 for d in decisions if d.verdict is Verdict.CANNOT_ASSESS and _bare(d.criterion) == cid
        )
        rates[cid] = named / len(decisions) if decisions else None
    return rates


def _disagreement(a: Verdict, b: Verdict) -> Literal["outcome", "unsure"] | None:
    if Verdict.UNSURE in (a, b):
        return "unsure"
    if a.promotes != b.promotes:
        return "outcome"
    return None


def _exclusion(decision: DecisionRecorded) -> str | None:
    """The exclusion criterion a decision cites, bare; None for any other verdict."""
    return _bare(decision.criterion) if decision.verdict is Verdict.EXCLUDE else None


def _bare(criterion: str | None) -> str | None:
    return None if criterion is None else criterion.rsplit(":", 1)[-1]


def _view(project: Project, decision: DecisionRecorded) -> DecisionView:
    return DecisionView(
        anchor=decision.anchor,
        conversion_id=decision.conversion_id,
        document_id=(
            None
            if decision.conversion_id is None
            else conversion_document(project, decision.conversion_id)
        ),
        verdict=decision.verdict,
        criterion=_bare(decision.criterion),
        quote=decision.quote,
        rationale=decision.rationale,
    )


def _pass_config(project: Project, label: PassLabel, stage: ScreeningStage = TA) -> PassConfig:
    with project.index.connect() as conn:
        framing, order, seed = conn.execute(
            text(
                "SELECT framing, criterion_order, random_seed FROM passes "
                "WHERE pass_label = :l AND stage = :s"
            ),
            {"l": label.value, "s": stage.value},
        ).one()
        joined = conn.execute(
            text(
                "SELECT session, model FROM pass_sessions WHERE pass_label = :l AND stage = :s "
                "ORDER BY session"
            ),
            {"l": label.value, "s": stage.value},
        ).all()
    return PassConfig.model_validate(
        {
            "pass_label": label,
            "framing": Framing(str(framing)),
            "criterion_order": str(order),
            "random_seed": int(seed),
            "sessions": [str(session) for session, _ in joined],
            "models": sorted({str(model) for _, model in joined}),
        }
    )


# --- Outcomes ---


def _open_for_resolution(screen: _Screen) -> set[str]:
    """Works a human may resolve now: unresolved disagreements and unresolved `unsure` works of
    pass A alone."""
    if not screen.known:
        return set()
    open_works = set()
    for work in screen.dual:
        a = screen.decided[PassLabel.A].get(work)
        b = screen.decided[PassLabel.B].get(work)
        if a is None or b is None or work in screen.resolutions:
            continue
        if _disagreement(a.verdict, b.verdict) is not None:
            open_works.add(work)
    for work in screen.single:
        a = screen.decided[PassLabel.A].get(work)
        if a is not None and a.verdict is Verdict.UNSURE and work not in screen.resolutions:
            open_works.add(work)
    return open_works


def _outcome(screen: _Screen, work: str) -> Outcome:
    resolved = screen.resolutions.get(work)
    if resolved is not None:
        return _verdict_outcome(resolved)
    if not screen.known or work not in screen.ordinary:
        return Outcome.PENDING
    a = screen.decided[PassLabel.A].get(work)
    if work in screen.dual:
        b = screen.decided[PassLabel.B].get(work)
        if a is None or b is None or _disagreement(a.verdict, b.verdict) is not None:
            return Outcome.PENDING
        return _promotes_outcome(a.verdict)
    if work in screen.single and a is not None and a.verdict is not Verdict.UNSURE:
        return _promotes_outcome(a.verdict)
    return Outcome.PENDING


def _promotes_outcome(verdict: Verdict) -> Outcome:
    return Outcome.INCLUDED if verdict.promotes else Outcome.EXCLUDED


def _verdict_outcome(verdict: Verdict) -> Outcome:
    return Outcome.INCLUDED if verdict is Verdict.INCLUDE else Outcome.EXCLUDED


def _label_outcome(label: str | None) -> Outcome:
    if label is None:
        return Outcome.PENDING
    return Outcome.INCLUDED if label == "include" else Outcome.EXCLUDED


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    # A model-level check (an exclusion without an EX criterion) has an empty location.
    return [
        ValidationIssue(".".join(str(part) for part in err["loc"]) or "criterion", str(err["msg"]))
        for err in exc.errors()
    ]
