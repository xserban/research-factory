"""The protocol as recorded: its versions, PRESS reviews, deviations and the search gate.

`record_protocol` validates a spec with `protocol_rules.protocol_issues`. Errors always refuse
the write. Gaps refuse a `ready` declaration and are returned with a draft. Once the current
protocol is ready it cannot be replaced by `record_protocol`, stale or not: `amend_protocol` is
the only path to a new version. An identical spec and status writes nothing.

`amend_protocol` records a `protocol.amended` event. It names each criterion's effect, computes
the criterion changes and the stale rules they create, and checks that the `semantic` flag
matches the changes. A prose-only amendment keeps the version; the event is still recorded.

`search_authorization` is the gate `services.search.register_query` applies to searches in pilot
and systematic projects: the current protocol must be ready and built on the current question, a
confirmed PRESS review must cover its search strategy, and the query must be planned or named by
a deviation of the current protocol. Probe and exploratory searches are not gated.
"""

import json
from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime
from typing import Literal

from sqlalchemy import text

from factory.clock import parse_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.chase import chase_round_texts, snowball_round_texts
from factory.living.window import window_spec
from factory.model.base import StrictModel
from factory.model.decisions import DecisionLevel
from factory.model.grey import GreyMethod, structured_types
from factory.model.miners import MinerUse
from factory.model.project import RigorMode
from factory.model.protocol import (
    ChangeKind,
    CriterionChange,
    CriterionEffect,
    DeviationRecorded,
    ExtractionSchema,
    MinerStale,
    PressConfirmed,
    PressFinding,
    PressReviewed,
    ProtocolAmended,
    ProtocolRecorded,
    ProtocolSpec,
    ProtocolStatus,
    ScreeningStage,
    StaleRule,
    SubmitterKind,
    protocol_version,
    search_strategy_hash,
)
from factory.model.reviews import ReviewKind
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.watch import CycleStatus
from factory.modules.presets import Enforcement, enforcement
from factory.services.context import Project
from factory.services.decision_binding import bind
from factory.services.gates import gate_issues
from factory.services.protocol_rules import (
    criterion_changes,
    extraction_stale,
    other_changes,
    protocol_issues,
    stale_rules,
)
from factory.services.question import current_question, get_question
from factory.services.reviews import require_protocol_change
from factory.services.seeds import all_seeds
from factory.sources.registry import default_sources, window_filter_sources


class ProtocolResult(StrictModel):
    """`created` is false when the spec and status were already current; `gaps` are returned
    whether or not the protocol was written."""

    protocol_id: str
    status: ProtocolStatus
    created: bool
    gaps: list[ValidationIssue]


class ProtocolVersion(StrictModel):
    protocol_id: str
    spec: ProtocolSpec
    status: ProtocolStatus
    recorded_at: datetime
    press: Literal["none", "reviewed", "confirmed"]


def miner_fields(project: Project) -> dict[tuple[str, int], tuple[str, ...]]:
    """The field names of every registered miner, by `(name, version)` (the `miners` table)."""
    from factory.mining.spec import spec_from_json  # a leaf module; keeps protocol import-light

    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT name, version, spec_blob FROM miners")).all()
    return {
        (str(name), int(version)): tuple(
            f.name for f in spec_from_json(project.blobs.get_json(str(blob))).fields
        )
        for name, version, blob in rows
    }


def miner_extraction_schema(use: MinerUse, fields: tuple[str, ...]) -> ExtractionSchema:
    """The `ExtractionSchema` a listed miner runs under: its pack is the miner, its fields are all
    the miner's fields, it records no claims and declares no comparability keys."""
    return ExtractionSchema(
        pack=use.name,
        pack_version=use.version,
        fields=fields,
        dual_extract_sample=use.dual_extract_sample,
        audit_fraction=use.audit_fraction,
        audit_minimum=use.audit_minimum,
        claims=False,
    )


ADMISSION_IS_HUMAN = "admitting a miner as evidence is a human act"


def agent_admission_issues(
    actor: Actor, old: ProtocolSpec | None, new: ProtocolSpec
) -> list[ValidationIssue]:
    """Issues for an agent that relaxes what only the researcher relaxes (R-51): it turns
    `evidence` on for a miner use (the proposer, or any agent, must not confirm its own evidence
    status), or it sets `hypothesis_plan.test_access_limit` above the value in force (the mode's
    default of 1 when no protocol is in force). Empty for a human or a change that relaxes
    nothing. Used by `record_protocol` and `amend_protocol` alike."""
    if actor.kind == "human":
        return []
    before = {(u.name, u.version) for u in (old.miners or ()) if u.evidence} if old else set()
    issues = [
        ValidationIssue(f"miners.{i}.evidence", ADMISSION_IS_HUMAN)
        for i, use in enumerate(new.miners or ())
        if use.evidence and (use.name, use.version) not in before
    ]
    if _plan_limit(new) > (1 if old is None else _plan_limit(old)):
        issues.append(ValidationIssue("hypothesis_plan.test_access_limit", "agent-cannot-raise"))
    return issues


def _plan_limit(spec: ProtocolSpec) -> int:
    plan = spec.hypothesis_plan
    return 1 if plan is None else plan.test_access_limit


def calibrated_miners(project: Project, spec: ProtocolSpec) -> set[tuple[str, int]]:
    """The miner versions `spec` lists whose calibration passed in this project and that are not
    retired (they alone may be admitted as evidence). Computed only for a listed use that asks for
    evidence."""
    from factory.services.miners import MinerState, miner_state  # miners imports this module

    known = miner_fields(project)
    return {
        (use.name, use.version)
        for use in spec.miners or ()
        if use.evidence
        and (use.name, use.version) in known
        and miner_state(project, use.name, use.version) is MinerState.CALIBRATED
    }


def miner_stale(project: Project, old: ProtocolSpec, new: ProtocolSpec) -> tuple[MinerStale, ...]:
    """The rows each listed miner's amendment stales, by plan D's `extraction_stale` on the miner's
    schema: a miner left out of the protocol, or listed at another version, stales all its rows;
    sampling and audit settings stale nothing. Computed per miner, so amending one leaves the
    others' rows alone."""
    fields = miner_fields(project)
    new_uses = {u.name: u for u in new.miners or ()}
    out: list[MinerStale] = []
    for use in old.miners or ():
        known = fields.get((use.name, use.version))
        if known is None:
            continue
        after = new_uses.get(use.name)
        later = None if after is None else fields.get((after.name, after.version))
        rule = extraction_stale(
            miner_extraction_schema(use, known),
            None if after is None or later is None else miner_extraction_schema(after, later),
        )
        if rule is not None:
            out.append(MinerStale(name=use.name, rule=rule))
    return tuple(sorted(out, key=lambda m: m.name))


def record_protocol(
    project: Project,
    actor: Actor,
    spec: ProtocolSpec,
    *,
    ready: bool,
    review_request_id: str | None = None,
    decision_ids: Sequence[str] | None = None,
) -> ProtocolResult:
    """Record the protocol as a draft or as ready. Writes nothing if the spec does not fit.

    `decision_ids` are the selected `protocol` decisions this recording implements. In `pilot` and
    `systematic` a recording that would write an event without one is refused (`decision_ids`, see
    `decision_binding.bind`); an unchanged protocol writes nothing and needs none.

    `review_request_id` consumes an approved request whose proposal is this call."""
    with project.index.exclusive():
        project.index.sync()
        require_protocol_change(
            project,
            actor,
            ReviewKind.PROTOCOL_RECORD,
            review_request_id,
            {"spec": spec.model_dump(mode="json"), "ready": ready},
        )
        question = current_question(project)
        if question is None:
            raise FactoryValidationError(
                [ValidationIssue("question", "record a question before the protocol")]
            )
        previous = current_protocol(project)
        admission = agent_admission_issues(actor, None if previous is None else previous.spec, spec)
        if admission:
            raise FactoryValidationError(admission)
        spec_question = get_question(project, spec.question_id)
        if spec_question is None:
            raise FactoryValidationError([ValidationIssue("question_id", "unknown question")])

        check = protocol_issues(
            spec,
            question=spec_question,
            current_question_id=question.question_id,
            mode=_rigor_mode(project),
            seeds=all_seeds(project),
            probes=_measured_probes(project),
            known_sources=set(default_sources()),
            window_sources=window_filter_sources(),
            registered_miners=set(miner_fields(project)),
            calibrated_miners=calibrated_miners(project, spec),
        )
        if check.errors:
            raise FactoryValidationError(check.errors)

        status = ProtocolStatus.READY if ready else ProtocolStatus.DRAFT
        protocol_id = protocol_version(spec)
        current = current_protocol(project)
        if current is not None and current.spec == spec and current.status is status:
            return ProtocolResult(
                protocol_id=protocol_id, status=status, created=False, gaps=check.gaps
            )
        if current is not None and current.status is ProtocolStatus.READY:
            raise FactoryValidationError(
                [ValidationIssue("protocol", "protocol is ready; change it with protocol_amend")]
            )
        if ready and check.gaps:
            raise FactoryValidationError(check.gaps)

        bound = bind(project, DecisionLevel.PROTOCOL, decision_ids)
        payload = ProtocolRecorded(
            decision_ids=bound,
            protocol_id=protocol_id,
            status=status,
            spec=spec,
            review_request_id=review_request_id,
        )
        input_blob = (
            project.blobs.put_json({"spec": spec.model_dump(mode="json"), "status": status.value})
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "protocol.recorded",
                    payload,
                    actor,
                    refs=(protocol_id,),
                    input_blob=input_blob,
                )
            ]
        )
    return ProtocolResult(protocol_id=protocol_id, status=status, created=True, gaps=check.gaps)


def current_protocol(project: Project) -> ProtocolVersion | None:
    """The latest recorded protocol, with the state of its PRESS review."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT protocol_id, status, spec, at FROM protocols ORDER BY event_id DESC LIMIT 1"
            )
        ).one_or_none()
        if row is None:
            return None
        protocol_id = str(row[0])
        reviews = conn.execute(
            text(
                "SELECT r.responses FROM press_reviews r JOIN protocols p "
                "ON p.protocol_id = r.protocol_id WHERE p.search_hash = "
                "(SELECT search_hash FROM protocols WHERE protocol_id = :protocol "
                "ORDER BY event_id DESC LIMIT 1)"
            ),
            {"protocol": protocol_id},
        ).all()
    if any(responses is not None for (responses,) in reviews):
        press: Literal["none", "reviewed", "confirmed"] = "confirmed"
    elif reviews:
        press = "reviewed"
    else:
        press = "none"
    return ProtocolVersion(
        protocol_id=protocol_id,
        spec=ProtocolSpec.model_validate_json(str(row[2])),
        status=ProtocolStatus(str(row[1])),
        recorded_at=parse_ts(str(row[3])),
        press=press,
    )


class AmendResult(StrictModel):
    """`from_version == to_version` and `prose_only` for a change that keeps the version."""

    amendment_id: str
    from_version: str
    to_version: str
    stale_rules: list[StaleRule]
    prose_only: bool


def amend_protocol(
    project: Project,
    actor: Actor,
    spec: ProtocolSpec,
    *,
    reason: str,
    semantic: bool,
    effects: Mapping[str, CriterionEffect],
    review_request_id: str | None = None,
) -> AmendResult:
    """Record the current ready protocol as amended to `spec`, or refuse and write nothing.

    `effects` must name exactly the changed criteria. `semantic` must be false if and only if
    nothing but clarifications and prose changed. The amended protocol must stay ready, so
    errors and gaps both refuse it. `spec.question_id` must be the current question.
    `review_request_id` consumes an approved request whose proposal is this call."""
    issues: list[ValidationIssue] = []
    if not reason.strip():
        issues.append(ValidationIssue("reason", "must not be empty"))
    with project.index.exclusive():
        project.index.sync()
        require_protocol_change(
            project,
            actor,
            ReviewKind.PROTOCOL_AMEND,
            review_request_id,
            {
                "spec": spec.model_dump(mode="json"),
                "reason": reason,
                "semantic": semantic,
                "effects": {cid: effect.value for cid, effect in effects.items()},
            },
        )
        current = current_protocol(project)
        question = current_question(project)
        if current is None or current.status is not ProtocolStatus.READY:
            issues.append(ValidationIssue("protocol", "only a ready protocol can be amended"))
        if question is None:
            issues.append(ValidationIssue("question", "record a question before amending"))
        if issues or current is None or question is None:
            raise FactoryValidationError(issues)
        admission = agent_admission_issues(actor, current.spec, spec)
        if admission:
            raise FactoryValidationError(admission)

        spec_question = get_question(project, spec.question_id)
        if spec_question is None:
            issues.append(ValidationIssue("question_id", "unknown question"))
            raise FactoryValidationError(issues)
        check = protocol_issues(
            spec,
            question=spec_question,
            current_question_id=question.question_id,
            mode=_rigor_mode(project),
            seeds=all_seeds(project),
            probes=_measured_probes(project),
            known_sources=set(default_sources()),
            window_sources=window_filter_sources(),
            registered_miners=set(miner_fields(project)),
            calibrated_miners=calibrated_miners(project, spec),
        )
        if check.errors or check.gaps:
            raise FactoryValidationError([*check.errors, *check.gaps])

        changes = criterion_changes(current.spec, spec)
        changed = {cid for cid, kind in changes if kind is ChangeKind.CHANGED}
        missing = sorted(changed - effects.keys())
        unexpected = sorted(effects.keys() - changed)
        if missing or unexpected:
            detail = []
            if missing:
                detail.append(f"missing: {', '.join(missing)}")
            if unexpected:
                detail.append(f"unexpected: {', '.join(unexpected)}")
            issues.append(
                ValidationIssue(
                    "effects", "must name exactly the changed criteria; " + "; ".join(detail)
                )
            )

        others = other_changes(current.spec, spec)
        # A changed criterion without a declared effect counts as semantic until it is declared.
        expected_semantic = bool(
            others
            or any(kind is not ChangeKind.CHANGED for _, kind in changes)
            or any(effects.get(cid) is not CriterionEffect.CLARIFIED for cid in changed)
        )
        if semantic != expected_semantic:
            issues.append(
                ValidationIssue(
                    "semantic",
                    "must be true when criteria are added or removed, another field changed, "
                    "or an effect is not clarified; otherwise false",
                )
            )
        if issues:
            raise FactoryValidationError(issues)

        change_records = tuple(
            CriterionChange(
                cid=cid,
                change=kind,
                effect=effects[cid] if kind is ChangeKind.CHANGED else None,
            )
            for cid, kind in changes
        )
        rules = stale_rules(change_records, current.spec, spec)
        amendment_id = project.ids.new("amd")
        to_version = protocol_version(spec)
        payload = ProtocolAmended(
            amendment_id=amendment_id,
            from_version=current.protocol_id,
            to_version=to_version,
            spec=spec,
            reason=reason.strip(),
            semantic=semantic,
            changes=change_records,
            stale_rules=tuple(rules),
            other_changes=tuple(others),
            extraction_stale=extraction_stale(
                current.spec.extraction_schema, spec.extraction_schema
            ),
            contribution_stale=extraction_stale(
                current.spec.contribution_schema, spec.contribution_schema
            ),
            miner_stale=miner_stale(project, current.spec, spec),
            review_request_id=review_request_id,
        )
        input_blob = (
            project.blobs.put_json(
                {
                    "spec": spec.model_dump(mode="json"),
                    "reason": reason.strip(),
                    "semantic": semantic,
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "protocol.amended",
                    payload,
                    actor,
                    refs=(amendment_id,),
                    input_blob=input_blob,
                )
            ]
        )
    return AmendResult(
        amendment_id=amendment_id,
        from_version=current.protocol_id,
        to_version=to_version,
        stale_rules=rules,
        prose_only=to_version == current.protocol_id,
    )


def protocol_lineage(project: Project) -> list[str]:
    """Every protocol version in recording order, each once, at its first recording."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT protocol_id FROM protocols ORDER BY event_id")).all()
    seen: dict[str, None] = {}
    for (protocol_id,) in rows:
        seen.setdefault(str(protocol_id), None)
    return list(seen)


def lineage_through(project: Project, protocol_id: str) -> frozenset[str]:
    """The protocol versions recorded up to and including the latest recording of `protocol_id`
    (decision 50): the versions whose decisions still count under `protocol_id` unless a stale
    rule says otherwise. A reverted amendment (A, B, A) keeps B in the lineage of A. Empty when
    `protocol_id` was never recorded."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = [
            str(row[0])
            for row in conn.execute(text("SELECT protocol_id FROM protocols ORDER BY event_id"))
        ]
    if protocol_id not in rows:
        return frozenset()
    last = len(rows) - 1 - rows[::-1].index(protocol_id)
    return frozenset(rows[: last + 1])


def amendments_with_events(project: Project) -> list[tuple[str, ProtocolAmended]]:
    """Every recorded amendment with the event ID it was recorded at, in recording order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT event_id, payload FROM amendments ORDER BY event_id")
        ).all()
    return [
        (str(event), ProtocolAmended.model_validate_json(str(payload))) for event, payload in rows
    ]


def last_criterion_change(project: Project, *, stage: ScreeningStage | None = None) -> str | None:
    """The event ID of the latest amendment that changed a criterion (a clarification included);
    calibration decisions recorded before it no longer count (R-26).

    With `stage`, only an amendment that changes a criterion applying at that stage or at `either`
    (in the old or the new spec: added, removed or changed) counts, so a criterion that only
    concerns the other stage does not move this stage's cut."""
    amendments = amendments_with_events(project)
    if stage is None:
        changed = [event for event, amendment in amendments if amendment.changes]
    else:
        changed = [event for event, amendment in amendments if _touches(project, amendment, stage)]
    return changed[-1] if changed else None


def _touches(project: Project, amendment: ProtocolAmended, stage: ScreeningStage) -> bool:
    """Whether a change of `amendment` concerns a criterion that applies at `stage` or `either`."""
    applies = (stage, ScreeningStage.EITHER)
    new_at = {c.id: c.applies_at for c in amendment.spec.criteria}
    old_spec = _spec_of(project, amendment.from_version)
    old_at = {} if old_spec is None else {c.id: c.applies_at for c in old_spec.criteria}
    return any(
        new_at.get(change.cid) in applies or old_at.get(change.cid) in applies
        for change in amendment.changes
    )


def _spec_of(project: Project, protocol_id: str) -> ProtocolSpec | None:
    """The spec recorded for `protocol_id`, from the protocol or an amendment that reached it."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT spec FROM protocols WHERE protocol_id = :id LIMIT 1"), {"id": protocol_id}
        ).one_or_none()
    if row is not None:
        return ProtocolSpec.model_validate_json(str(row[0]))
    for _, amendment in amendments_with_events(project):
        if amendment.to_version == protocol_id:
            return amendment.spec
    return None


def list_amendments(project: Project) -> list[ProtocolAmended]:
    """Every recorded amendment, in recording order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT payload FROM amendments ORDER BY event_id")).all()
    return [ProtocolAmended.model_validate_json(str(payload)) for (payload,) in rows]


class AmendmentSummary(StrictModel):
    """One amendment as `protocol_view` lists it: everything but the whole spec it records."""

    amendment_id: str
    from_version: str
    to_version: str
    reason: str
    semantic: bool
    changes: tuple[CriterionChange, ...]
    other_changes: tuple[str, ...]


class ProtocolView(StrictModel):
    """The current protocol, whole, so a fresh session can read it and amend it. Every field is
    None and `amendments` is empty before a protocol is recorded. Carries no seed record: a
    criterion's worked examples are never held-out seeds (`CriterionExamples`)."""

    protocol_id: str | None
    status: ProtocolStatus | None
    press: Literal["none", "reviewed", "confirmed"] | None
    spec: ProtocolSpec | None
    amendments: list[AmendmentSummary]


def protocol_view(project: Project) -> ProtocolView:
    """The current protocol with its status, PRESS state and amendments, oldest first."""
    current = current_protocol(project)
    if current is None:
        return ProtocolView(protocol_id=None, status=None, press=None, spec=None, amendments=[])
    return ProtocolView(
        protocol_id=current.protocol_id,
        status=current.status,
        press=current.press,
        spec=current.spec,
        amendments=[
            AmendmentSummary(
                amendment_id=row.amendment_id,
                from_version=row.from_version,
                to_version=row.to_version,
                reason=row.reason,
                semantic=row.semantic,
                changes=row.changes,
                other_changes=row.other_changes,
            )
            for row in list_amendments(project)
        ],
    )


def list_deviations(project: Project) -> list[DeviationRecorded]:
    """Every recorded deviation, in recording order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT deviation_id, protocol_id, description, reason, affects "
                "FROM deviations ORDER BY event_id"
            )
        ).all()
    return [
        DeviationRecorded(
            deviation_id=str(deviation),
            protocol_id=str(protocol_id),
            description=str(description),
            reason=str(reason),
            affects=tuple(str(item) for item in _json_list(affects)),
        )
        for deviation, protocol_id, description, reason, affects in rows
    ]


def press_review(
    project: Project,
    actor: Actor,
    protocol_id: str,
    findings: Sequence[PressFinding],
) -> str:
    """Record an agent's PRESS review of the current protocol, and return its review id."""
    issues: list[ValidationIssue] = []
    if actor.kind != "agent":
        issues.append(ValidationIssue("actor", "a PRESS review is written by an agent"))
    with project.index.exclusive():
        current = current_protocol(project)
        if current is None or current.protocol_id != protocol_id:
            issues.append(ValidationIssue("protocol_id", "must be the current protocol"))
        if issues:
            raise FactoryValidationError(issues)
        review_id = project.ids.new("prs")
        payload = PressReviewed(
            review_id=review_id, protocol_id=protocol_id, findings=tuple(findings)
        )
        input_blob = project.blobs.put_json(
            {
                "protocol_id": protocol_id,
                "findings": [finding.model_dump(mode="json") for finding in findings],
            }
        )
        project.record(
            [
                project.events.make(
                    "protocol.press_reviewed",
                    payload,
                    actor,
                    refs=(review_id,),
                    input_blob=input_blob,
                )
            ]
        )
    return review_id


def confirm_press(project: Project, actor: Actor, review_id: str, responses: Sequence[str]) -> None:
    """A human's confirmation of a PRESS review: one non-empty response per finding."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(
            project,
            actor,
            "protocol.press_confirm",
            agent_text="a PRESS confirmation is human-only",
        )
        review = _review(project, review_id)
        if review is None:
            issues.append(ValidationIssue("review_id", "unknown review"))
        elif review.confirmed:
            issues.append(ValidationIssue("review_id", "already confirmed"))
        elif len(responses) != review.finding_count or any(
            not response.strip() for response in responses
        ):
            issues.append(
                ValidationIssue("responses", "one non-empty response per finding is required")
            )
        if issues or review is None:
            raise FactoryValidationError(issues)
        payload = PressConfirmed(
            review_id=review_id, protocol_id=review.protocol_id, responses=tuple(responses)
        )
        project.record(
            [project.events.make("protocol.press_confirmed", payload, actor, refs=(review_id,))]
        )


def record_deviation(
    project: Project,
    actor: Actor,
    *,
    description: str,
    reason: str,
    affects: Sequence[str] = (),
    review_request_id: str | None = None,
) -> str:
    """Record a deviation from the current protocol, and return its id. `review_request_id`
    consumes an approved request whose proposal is this call."""
    issues: list[ValidationIssue] = []
    if not description.strip():
        issues.append(ValidationIssue("description", "must not be empty"))
    if not reason.strip():
        issues.append(ValidationIssue("reason", "must not be empty"))
    with project.index.exclusive():
        project.index.sync()
        require_protocol_change(
            project,
            actor,
            ReviewKind.DEVIATION,
            review_request_id,
            {"description": description, "reason": reason, "affects": list(affects)},
        )
        current = current_protocol(project)
        if current is None:
            issues.append(ValidationIssue("protocol", "record a protocol before a deviation"))
        if issues or current is None:
            raise FactoryValidationError(issues)
        deviation_id = project.ids.new("dev")
        payload = DeviationRecorded(
            deviation_id=deviation_id,
            protocol_id=current.protocol_id,
            description=description,
            reason=reason,
            affects=tuple(affects),
            review_request_id=review_request_id,
        )
        input_blob = (
            project.blobs.put_json(
                {
                    "description": description,
                    "reason": reason,
                    "affects": list(affects),
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "protocol.deviation_recorded",
                    payload,
                    actor,
                    refs=(deviation_id,),
                    input_blob=input_blob,
                )
            ]
        )
    return deviation_id


def search_authorization(
    project: Project,
    spec: QuerySpec,
    *,
    deviation_id: str | None,
    pending_round_texts: Collection[str] = (),
    round_id: str | None = None,
    supplied_by: SubmitterKind | None = None,
    cycle_id: str | None = None,
    import_id: str | None = None,
) -> list[ValidationIssue]:
    """Why a query may not run under the protocol. Empty when it may, or when it is not gated.

    Every purpose except a probe is gated the same way: a search, a citation chase and a seed
    lookup each need the protocol, unless the project is exploratory. Probes measure the seeds
    and are not gated.

    A `deviation_id`, when given, must name a deviation of the current protocol, whether or not
    the query is planned: a stale or foreign id is refused rather than recorded in the events.

    A chase query is planned by its round: its text is waived when it is in
    `pending_round_texts`, the texts of a round about to be written, when a recorded
    `search_chase` round registered it, or when `round_id` names the recorded snowball round
    whose texts include it (a snowball text is waived only for a query naming its round).

    A `supplied` lookup is planned when `supplied_by`, the kind of actor that captured the link,
    is in the protocol's `supplied_links.accept_from` (slice 4a, ruling 7). Without the section,
    or with `supplied_by` unset, it needs a deviation. `supplied_by` waives nothing for any other
    purpose, and no waiver lifts the readiness, question or PRESS checks.

    A window query of a watch (slice 4b, ruling 3) is planned by its cycle: it is waived when
    `cycle_id` names an open cycle of the current protocol that runs `spec.source` as a window
    and `spec` is a planned query plus that cycle's `listed_since` date, nothing more.

    An `import` query (slice 3d, ruling 22) is authorised only through `import_id`, the import
    whose recorded admission planned this source, kind and text, in every rigour mode. That plan
    waives the planned-queries rule like a snowball round does; the readiness, question and PRESS
    checks still hold.
    """
    import_issues = _import_issues(project, spec, import_id)
    if spec.purpose is QueryPurpose.PROBE or (
        enforcement(_rigor_mode(project), "protocol.ready") is Enforcement.OFF
    ):
        return import_issues
    current = current_protocol(project)
    if current is None:
        return [ValidationIssue("protocol", "record and ready a protocol before searching")]

    issues: list[ValidationIssue] = []
    if current.status is not ProtocolStatus.READY:
        issues.append(ValidationIssue("protocol", "the protocol is not ready"))
    question = current_question(project)
    if question is not None and current.spec.question_id != question.question_id:
        issues.append(
            ValidationIssue(
                "protocol",
                f"protocol is built on {current.spec.question_id}; "
                "amend it to the current question",
            )
        )
    if not _strategy_confirmed(project, search_strategy_hash(current.spec)):
        issues.append(ValidationIssue("press", "a confirmed PRESS review is required"))
    if deviation_id is not None and not _is_deviation_of(
        project, deviation_id, current.protocol_id
    ):
        issues.append(
            ValidationIssue("deviation_id", "must name a deviation of the current protocol")
        )
    planned = any(query.matches(spec) for query in current.spec.queries)
    if (
        not planned
        and deviation_id is None
        and not _chase_round_waives(project, spec, pending_round_texts, round_id)
        and not _supplied_waives(current.spec, spec, supplied_by)
        and not _grey_waives(current.spec, spec)
        and not _cycle_waives(project, current, spec, cycle_id)
        and not _status_waives(project, current, spec, cycle_id)
        and not (spec.purpose is QueryPurpose.IMPORT and not import_issues)
    ):
        issues.append(
            ValidationIssue("query", "not planned by the current protocol; record a deviation")
        )
    return issues + import_issues


def _import_issues(
    project: Project, spec: QuerySpec, import_id: str | None
) -> list[ValidationIssue]:
    """Why an `import` query is not planned by an admission; empty for any other purpose."""
    if spec.purpose is not QueryPurpose.IMPORT:
        return []
    if import_id is None:
        return [
            ValidationIssue(
                "import_id", "an import query names the import whose admission planned it"
            )
        ]
    with project.index.connect() as conn:
        planned = conn.execute(
            text(
                "SELECT 1 FROM import_admission_queries WHERE import_id = :i AND source = :s "
                'AND kind = :k AND "text" = :t LIMIT 1'
            ),
            {"i": import_id, "s": spec.source, "k": spec.kind.value, "t": spec.text},
        ).first()
    if planned is None:
        return [
            ValidationIssue("import_id", f"{import_id}: no recorded admission plans this query")
        ]
    return []


def _cycle_waives(
    project: Project, current: ProtocolVersion, spec: QuerySpec, cycle_id: str | None
) -> bool:
    """Whether `cycle_id` is an open window cycle of the current protocol that plans `spec`."""
    if cycle_id is None or spec.purpose is not QueryPurpose.SEARCH:
        return False
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT c.status, c.protocol_id, s.mode, s.window_start, s.full_replay "
                "FROM watch_cycles c JOIN watch_cycle_sources s ON s.cycle_id = c.cycle_id "
                "WHERE c.cycle_id = :cycle AND s.source = :source"
            ),
            {"cycle": cycle_id, "source": spec.source},
        ).one_or_none()
    if row is None:
        return False
    status, protocol_id, mode, start, full_replay = row
    if (
        status != CycleStatus.OPEN.value
        or protocol_id != current.protocol_id
        or mode != "window"
        or full_replay
        or start is None
    ):
        return False
    since = date.fromisoformat(str(start))
    for planned in current.spec.queries:
        wanted = window_spec(planned, since)
        if (wanted.source, wanted.kind, wanted.text, wanted.filters) == (
            spec.source,
            spec.kind,
            spec.text.strip(),
            spec.filters,
        ):
            return True
    return False


def _status_waives(
    project: Project, current: ProtocolVersion, spec: QuerySpec, cycle_id: str | None
) -> bool:
    """Whether `cycle_id` is an open cycle of the current protocol and `spec` a status lookup.

    Gate living.status_lookup: a platform-built identifier lookup is planned by its cycle, as a
    window query is (slice 4b, living-C)."""
    if cycle_id is None or spec.purpose is not QueryPurpose.STATUS:
        return False
    if spec.kind not in (QueryKind.ID_LIST, QueryKind.FILTER):
        return False
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT status, protocol_id FROM watch_cycles WHERE cycle_id = :c"),
            {"c": cycle_id},
        ).one_or_none()
    return row is not None and row[0] == CycleStatus.OPEN.value and row[1] == current.protocol_id


def _supplied_waives(
    protocol: ProtocolSpec, spec: QuerySpec, supplied_by: SubmitterKind | None
) -> bool:
    """Whether the protocol's `supplied_links` section plans this supplied lookup."""
    plan = protocol.supplied_links
    return (
        spec.purpose is QueryPurpose.SUPPLIED
        and supplied_by is not None
        and plan is not None
        and supplied_by in plan.accept_from
    )


def _grey_waives(protocol: ProtocolSpec, spec: QuerySpec) -> bool:
    """Whether `grey_sources` plans this structured grey search (plan SG): an OpenAlex query of
    purpose `grey` whose `type` filter names only types a `structured` entry declares."""
    if spec.purpose is not QueryPurpose.GREY:
        return False
    if spec.source == "webcapture":
        return any(
            s.method is GreyMethod.WEBSITE and s.target == spec.filters.get("source_id")
            for s in protocol.grey_sources or ()
        )
    if spec.source != "openalex":
        return False
    asked = {t.strip() for t in spec.filters.get("type", "").split("|") if t.strip()}
    return bool(asked) and asked <= structured_types(protocol.grey_sources)


def registered_deviation(project: Project, query_id: str) -> str | None:
    """The deviation a registered query was run under, read from its `query.registered` refs,
    or None when it was planned. A ref is a deviation when the deviations table names it."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT o.ref FROM event_refs q JOIN event_refs o ON o.event_id = q.event_id "
                "JOIN deviations d ON d.deviation_id = o.ref "
                "WHERE q.ref = :q AND q.position = 0 AND q.type = 'query.registered' "
                "ORDER BY o.event_id, o.position LIMIT 1"
            ),
            {"q": query_id},
        ).one_or_none()
    return None if row is None else str(row[0])


def search_refs(project: Project, spec: QuerySpec, deviation_id: str | None) -> tuple[str, ...]:
    """The ids a registered query refers to: the current protocol, when one exists, and the
    deviation it was run under. A probe refers to nothing here."""
    if spec.purpose is QueryPurpose.PROBE:
        return ()
    current = current_protocol(project)
    refs: list[str] = []
    if current is not None:
        refs.append(current.protocol_id)
    if deviation_id is not None:
        refs.append(deviation_id)
    return tuple(refs)


class _Review(StrictModel):
    protocol_id: str
    finding_count: int
    confirmed: bool


def _review(project: Project, review_id: str) -> _Review | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT protocol_id, findings, responses FROM press_reviews "
                "WHERE review_id = :review"
            ),
            {"review": review_id},
        ).one_or_none()
    if row is None:
        return None
    protocol_id, findings, responses = row
    return _Review(
        protocol_id=str(protocol_id),
        finding_count=len(_json_list(findings)),
        confirmed=responses is not None,
    )


def _strategy_confirmed(project: Project, search_hash: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM press_reviews r JOIN protocols p ON p.protocol_id = r.protocol_id "
                "WHERE p.search_hash = :hash AND r.responses IS NOT NULL LIMIT 1"
            ),
            {"hash": search_hash},
        ).one_or_none()
    return row is not None


def _is_deviation_of(project: Project, deviation_id: str, protocol_id: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM deviations WHERE deviation_id = :deviation "
                "AND protocol_id = :protocol"
            ),
            {"deviation": deviation_id, "protocol": protocol_id},
        ).one_or_none()
    return row is not None


def _chase_round_waives(
    project: Project, spec: QuerySpec, pending: Collection[str], round_id: str | None
) -> bool:
    """Whether a chase spec's text is one a round planned: a round about to be written, a
    recorded chase round, or the recorded snowball round `round_id`."""
    if spec.purpose is not QueryPurpose.CHASE:
        return False
    if spec.text in pending:
        return True
    with project.index.connect() as conn:
        if spec.text in chase_round_texts(conn):
            return True
        return round_id is not None and spec.text in snowball_round_texts(conn, round_id)


def recorded_round(project: Project, round_id: str) -> Literal["chase", "snowball"] | None:
    """The kind of recorded round `round_id` names: a snowball round, a chase round, or None."""
    with project.index.connect() as conn:
        if conn.execute(
            text("SELECT 1 FROM snowball_rounds WHERE round_id = :r"), {"r": round_id}
        ).one_or_none():
            return "snowball"
        if conn.execute(
            text("SELECT 1 FROM chase_rounds WHERE round_id = :r"), {"r": round_id}
        ).one_or_none():
            return "chase"
    return None


def is_open_watch_cycle(project: Project, cycle_id: str) -> bool:
    """Whether `cycle_id` names a watch cycle that has not finished."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM watch_cycles WHERE cycle_id = :c AND status = :open"),
            {"c": cycle_id, "open": CycleStatus.OPEN.value},
        ).one_or_none()
    return row is not None


def is_watch_cycle(project: Project, cycle_id: str) -> bool:
    """Whether `cycle_id` names a recorded watch cycle."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM watch_cycles WHERE cycle_id = :c"), {"c": cycle_id}
        ).one_or_none()
    return row is not None


def _registered_ref(project: Project, query_id: str, table: str, column: str) -> str | None:
    """The first ref, after the query's own, of its `query.registered` event that `table` names
    in `column`."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT o.ref FROM event_refs q JOIN event_refs o ON o.event_id = q.event_id "
                f"JOIN {table} t ON t.{column} = o.ref "
                "WHERE q.ref = :q AND q.position = 0 AND q.type = 'query.registered' "
                "ORDER BY o.event_id, o.position LIMIT 1"
            ),
            {"q": query_id},
        ).one_or_none()
    return None if row is None else str(row[0])


def registered_cycle(project: Project, query_id: str) -> str | None:
    """The watch cycle a registered query names in its `query.registered` refs, or None."""
    return _registered_ref(project, query_id, "watch_cycles", "cycle_id")


def registered_import(project: Project, query_id: str) -> str | None:
    """The import a registered query names in its `query.registered` refs, or None."""
    return _registered_ref(project, query_id, "imports", "import_id")


def registered_round(project: Project, query_id: str) -> str | None:
    """The snowball round a registered query names in its `query.registered` refs, or None."""
    return _registered_ref(project, query_id, "snowball_rounds", "round_id")


def _measured_probes(project: Project) -> dict[str, set[str]]:
    """The sources each probe measured, keyed by probe id."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT probe_id, source FROM probes WHERE status = 'measured'")
        ).all()
    measured: dict[str, set[str]] = {}
    for probe_id, source in rows:
        measured.setdefault(str(probe_id), set()).add(str(source))
    return measured


def _rigor_mode(project: Project) -> RigorMode:
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT rigor_mode FROM project WHERE slug = :slug"),
            {"slug": project.paths.slug},
        ).scalar_one()
    return RigorMode(str(value))


def _json_list(stored: object) -> list[object]:
    return list(json.loads(str(stored)))
