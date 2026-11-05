"""Review requests and their decisions (slice 5 ruling 14; plan teams-B).

A contributor proposes what they may not apply alone; a holder of the required role decides;
the ordinary tool, called by a holder of that role, applies it.

Invariants:
- Approval executes nothing. A proposal is applied only by the tool it was written for, which
  validates as it always does.
- The requester never decides their own request but to withdraw it: compared by user, so another
  session or an agent of the same user is the same person (R-51).
- A review's state is computed on read (`ReviewState`), from the `reviews` row and the protocol in
  force. Nothing stores it.
- Every check and the event it allows happen under one hold of the project write lock.
- A refusal writes nothing. The fold repeats each guard, for a hand-written event.
"""

from pydantic import JsonValue, ValidationError

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.reviews import (
    REVIEW_TABLES,
    ReviewRow,
    current_protocol_row,
    current_version,
    review_row,
    review_rows,
)
from factory.model.base import StrictModel
from factory.model.members import ProjectRole
from factory.model.protocol import ProtocolStatus
from factory.model.reviews import (
    PROPOSAL_MODELS,
    Proposal,
    ReviewDecided,
    ReviewDecision,
    ReviewKind,
    ReviewRequested,
    ReviewState,
)
from factory.model.screening import Channel
from factory.services import passes
from factory.services.access import Permission, governed, require_actor, role_suffices
from factory.services.context import Project
from factory.services.lab import payload_of, refuse
from factory.services.members import roles_of

NO_REVIEWS_NOTICE = "no review requests yet"


class ReviewView(StrictModel):
    review_request_id: str
    kind: ReviewKind
    target: str
    target_version: str | None
    proposal_blob: str
    required_role: ProjectRole
    reason: str
    requester: str
    requested_at: str
    state: ReviewState
    decision: ReviewDecision | None
    rationale: str | None
    channel: Channel | None
    decided_by: str | None
    consumed_event: str | None


def _state(row: ReviewRow, current: str | None) -> ReviewState:
    """A decided-against request stays as decided; consumption is final; anything else whose
    target moved on is stale (plan ruling 2, and the spec's "the protocol moved on")."""
    if row.decision == "reject":
        return ReviewState.REJECTED
    if row.decision == "withdraw":
        return ReviewState.WITHDRAWN
    if row.consumed_event is not None:
        return ReviewState.CONSUMED
    if row.target_version != current:
        return ReviewState.STALE
    return ReviewState.APPROVED if row.decision == "approve" else ReviewState.OPEN


def _view(row: ReviewRow, current: str | None) -> ReviewView:
    return ReviewView(
        review_request_id=str(row.review_request_id),
        kind=ReviewKind(str(row.kind)),
        target=str(row.target),
        target_version=None if row.target_version is None else str(row.target_version),
        proposal_blob=str(row.proposal_blob),
        required_role=ProjectRole(str(row.required_role)),
        reason=str(row.reason),
        requester=str(row.requester),
        requested_at=str(row.requested_at),
        state=_state(row, current),
        decision=row.decision,
        rationale=None if row.rationale is None else str(row.rationale),
        channel=None if row.channel is None else Channel(str(row.channel)),
        decided_by=None if row.decided_by is None else str(row.decided_by),
        consumed_event=None if row.consumed_event is None else str(row.consumed_event),
    )


def review(project: Project, review_request_id: str) -> ReviewView:
    """One request, or a refusal when no request has that id."""
    project.index.sync()
    with project.index.connect() as conn:
        row = review_row(conn, REVIEW_TABLES, review_request_id)
        current = current_version(conn)
    if row is None:
        raise refuse("review_request_id", "unknown review request")
    return _view(row, current)


def reviews(project: Project, *, state: ReviewState | None = None) -> list[ReviewView]:
    """Every request in filing order, or those in `state`. Empty on a fresh project."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = review_rows(conn, REVIEW_TABLES)
        current = current_version(conn)
    views = [_view(row, current) for row in rows]
    return views if state is None else [view for view in views if view.state is state]


def proposal_of(project: Project, review_request_id: str) -> JsonValue:
    """The proposal a request carries, as filed."""
    view = review(project, review_request_id)
    try:
        return project.blobs.get_json(view.proposal_blob)
    except FactoryError as exc:
        raise refuse("review_request_id", "the proposal cannot be read") from exc


def _parsed(kind: ReviewKind, proposal: JsonValue) -> Proposal:
    """The proposal as its kind's model reads it; every error names a path under `proposal`."""
    try:
        return PROPOSAL_MODELS[kind].model_validate(proposal)
    except ValidationError as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(".".join(["proposal", *map(str, e["loc"])]), str(e["msg"]))
                for e in exc.errors()
            ]
        ) from exc


def _target(project: Project, kind: ReviewKind) -> tuple[str, str | None]:
    """What a request of `kind` is filed on, or a refusal when that does not exist."""
    with project.index.connect() as conn:
        current = current_protocol_row(conn)
    version = None if current is None else current[0]
    if kind is ReviewKind.PROTOCOL_RECORD:
        return project.paths.slug, version
    if current is None or version is None:
        raise refuse("protocol", "record a protocol before filing this request")
    if kind is ReviewKind.PROTOCOL_AMEND and current[1] != ProtocolStatus.READY.value:
        raise refuse("protocol", "only a ready protocol can be amended")
    return version, version


def request_review(
    project: Project, actor: Actor, kind: ReviewKind, proposal: JsonValue, reason: str
) -> str:
    """File a request, and return its id. Needs `work:run`. The proposal must validate as `kind`'s
    model; a refusal writes nothing."""
    parsed = _parsed(kind, proposal)
    with project.writing():
        require_actor(project, actor, Permission.WORK_RUN)
        target, version = _target(project, kind)
        review_request_id = project.ids.new("rrq")
        blob = project.blobs.put_json(parsed.model_dump(mode="json"))
        payload = payload_of(
            ReviewRequested,
            review_request_id=review_request_id,
            kind=kind,
            target=target,
            target_version=version,
            proposal_blob=blob,
            required_role=ProjectRole.MAINTAINER,
            reason=reason,
        )
        refs = (review_request_id,) if version is None else (review_request_id, version)
        project.record(
            [
                project.events.make(
                    "review.requested",
                    payload,
                    actor,
                    refs=refs,
                    input_blob=blob if actor.kind == "agent" else None,
                )
            ]
        )
    return review_request_id


def _decision_issues(
    project: Project, actor: Actor, view: ReviewView, decision: ReviewDecision
) -> list[ValidationIssue]:
    if view.decision is not None:
        return [ValidationIssue("review_request_id", f"already decided: {view.decision}")]
    if decision == "withdraw":
        if actor.user != view.requester:
            return [ValidationIssue("permission", "only the requester may withdraw")]
        return []
    if actor.user == view.requester:
        return [ValidationIssue("permission", "the requester cannot decide their own request")]
    require_actor(project, actor, Permission.REVIEW_DECIDE)
    if governed(project) and not role_suffices(roles_of(project, actor.user), view.required_role):
        return [ValidationIssue("permission", f"needs {view.required_role.value}")]
    if decision == "approve" and view.state is ReviewState.STALE:
        return [ValidationIssue("decision", "a stale request can be rejected or withdrawn only")]
    return []


def decide_review(
    project: Project,
    actor: Actor,
    review_request_id: str,
    decision: ReviewDecision,
    rationale: str,
    channel: Channel,
) -> None:
    """A person's decision. Approval makes the request consumable once and applies nothing."""
    payload = payload_of(
        ReviewDecided,
        review_request_id=review_request_id,
        decision=decision,
        rationale=rationale,
        channel=channel,
    )
    with project.writing():
        if actor.kind != "human" or actor.id != actor.user:
            raise refuse("actor", "a review decision is a person's own act")
        issues = passes.require_not_pass_session(project, actor, channel)
        issues.extend(
            _decision_issues(project, actor, review(project, review_request_id), decision)
        )
        if issues:
            raise FactoryValidationError(issues)
        project.record(
            [project.events.make("review.decided", payload, actor, refs=(review_request_id,))]
        )
