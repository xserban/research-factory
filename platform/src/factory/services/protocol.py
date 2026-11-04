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
from datetime import datetime
from typing import Literal

from sqlalchemy import text

from factory.clock import parse_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.chase import round_texts
from factory.model.base import StrictModel
from factory.model.project import RigorMode
from factory.model.protocol import (
    ChangeKind,
    CriterionChange,
    CriterionEffect,
    DeviationRecorded,
    PressConfirmed,
    PressFinding,
    PressReviewed,
    ProtocolAmended,
    ProtocolRecorded,
    ProtocolSpec,
    ProtocolStatus,
    ScreeningStage,
    StaleRule,
    protocol_version,
    search_strategy_hash,
)
from factory.model.search import QueryPurpose, QuerySpec
from factory.services.context import Project
from factory.services.protocol_rules import (
    criterion_changes,
    extraction_stale,
    other_changes,
    protocol_issues,
    stale_rules,
)
from factory.services.question import current_question, get_question
from factory.services.seeds import all_seeds
from factory.sources.registry import default_sources


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


_RIGOR_MODES_GATED = frozenset({RigorMode.PILOT, RigorMode.SYSTEMATIC})


def record_protocol(
    project: Project, actor: Actor, spec: ProtocolSpec, *, ready: bool
) -> ProtocolResult:
    """Record the protocol as a draft or as ready. Writes nothing if the spec does not fit."""
    with project.index.exclusive():
        project.index.sync()
        question = current_question(project)
        if question is None:
            raise FactoryValidationError(
                [ValidationIssue("question", "record a question before the protocol")]
            )
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

        payload = ProtocolRecorded(protocol_id=protocol_id, status=status, spec=spec)
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
) -> AmendResult:
    """Record the current ready protocol as amended to `spec`, or refuse and write nothing.

    `effects` must name exactly the changed criteria. `semantic` must be false if and only if
    nothing but clarifications and prose changed. The amended protocol must stay ready, so
    errors and gaps both refuse it. `spec.question_id` must be the current question."""
    issues: list[ValidationIssue] = []
    if not reason.strip():
        issues.append(ValidationIssue("reason", "must not be empty"))
    with project.index.exclusive():
        project.index.sync()
        current = current_protocol(project)
        question = current_question(project)
        if current is None or current.status is not ProtocolStatus.READY:
            issues.append(ValidationIssue("protocol", "only a ready protocol can be amended"))
        if question is None:
            issues.append(ValidationIssue("question", "record a question before amending"))
        if issues or current is None or question is None:
            raise FactoryValidationError(issues)

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
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        issues.append(ValidationIssue("actor", "a PRESS confirmation is human-only"))
    with project.index.exclusive():
        project.index.sync()
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
) -> str:
    """Record a deviation from the current protocol, and return its id."""
    issues: list[ValidationIssue] = []
    if not description.strip():
        issues.append(ValidationIssue("description", "must not be empty"))
    if not reason.strip():
        issues.append(ValidationIssue("reason", "must not be empty"))
    with project.index.exclusive():
        project.index.sync()
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
) -> list[ValidationIssue]:
    """Why a query may not run under the protocol. Empty when it may, or when it is not gated.

    Every purpose except a probe is gated the same way: a search, a citation chase and a seed
    lookup each need the protocol, unless the project is exploratory. Probes measure the seeds
    and are not gated.

    A `deviation_id`, when given, must name a deviation of the current protocol, whether or not
    the query is planned: a stale or foreign id is refused rather than recorded in the events.

    A chase query is planned by its round: its text is waived when a recorded round registered
    it, or when it is in `pending_round_texts`, the texts of a round about to be written.
    """
    if spec.purpose is QueryPurpose.PROBE or _rigor_mode(project) not in _RIGOR_MODES_GATED:
        return []
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
        and not _chase_round_waives(project, spec, pending_round_texts)
    ):
        issues.append(
            ValidationIssue("query", "not planned by the current protocol; record a deviation")
        )
    return issues


def registered_deviation(project: Project, query_id: str) -> str | None:
    """The deviation a registered query was run under, read from its `query.registered` refs,
    or None when it was planned. A ref is a deviation when the deviations table names it."""
    with project.index.connect() as conn:
        events = conn.execute(
            text("SELECT refs FROM events WHERE type = 'query.registered' AND refs LIKE :pattern"),
            {"pattern": f'%"{query_id}"%'},
        ).all()
        for (refs,) in events:
            for ref in json.loads(str(refs)):
                known = conn.execute(
                    text("SELECT 1 FROM deviations WHERE deviation_id = :deviation"),
                    {"deviation": ref},
                ).one_or_none()
                if known is not None:
                    return str(ref)
    return None


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


def _chase_round_waives(project: Project, spec: QuerySpec, pending: Collection[str]) -> bool:
    """Whether a chase spec's text is one a round registered, recorded or about to be."""
    if spec.purpose is not QueryPurpose.CHASE:
        return False
    if spec.text in pending:
        return True
    with project.index.connect() as conn:
        return spec.text in round_texts(conn)


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
