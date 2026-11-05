"""A person's workspace: a view and a queue scope over the one shared log (slice 5 ruling 13).

Invariants:
- Read-only and computed: every item comes from the log by `actor.user`, so an agent's work counts
  for the person it acts for. No table of its own, no event.
- `reviews_to_decide` lists what the user could decide now: undecided, not their own request, and
  needing a role they hold.
- A fresh project gives an empty workspace with a notice.
"""

from pydantic import JsonValue, field_serializer
from sqlalchemy import text

from factory.clock import format_ts
from factory.model.base import StrictModel
from factory.model.members import ProjectRole
from factory.model.reviews import ReviewState
from factory.model.task import TaskStatus
from factory.services.access import role_suffices
from factory.services.context import Project
from factory.services.members import roles_of
from factory.services.reviews import ReviewView, reviews

EMPTY_NOTICE = "nothing recorded for this person on this project yet"

_PROPOSAL_DECISIONS = {
    "relation.proposed": "relation.decided",
    "idea.proposed": "idea.decided",
    "vocabulary.property_proposed": "vocabulary.property_decided",
    "concept.link_proposed": "concept.link_decided",
    "contradiction.proposed": "contradiction.decided",
    "consolidation.proposed": "consolidation.decided",
}
"""The proposal events whose first ref is the proposal, and the event that decides each. A region
member proposal is read from the regions tables: its decision does not always ref it."""

_UNDECIDED = (ReviewState.OPEN, ReviewState.STALE)


class SessionSummary(StrictModel):
    session: str
    first_event: str
    last_event: str
    events: int


class Workspace(StrictModel):
    user: str
    sessions: list[SessionSummary]
    open_tasks: list[str]
    proposals: list[str]
    reviews_requested: list[ReviewView]
    reviews_to_decide: list[ReviewView]
    roles: frozenset[ProjectRole]
    notice: str | None = None

    @field_serializer("roles")
    def _sorted_roles(self, value: frozenset[ProjectRole]) -> list[str]:
        return sorted(role.value for role in value)


def _sessions(project: Project, user: str) -> list[SessionSummary]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                'SELECT session, MIN(id), MAX(id), COUNT(*) FROM events WHERE "user" = :u '
                "GROUP BY session ORDER BY MIN(id)"
            ),
            {"u": user},
        ).all()
    return [
        SessionSummary(
            session=str(session), first_event=str(first), last_event=str(last), events=int(count)
        )
        for session, first, last, count in rows
    ]


def _open_tasks(project: Project, sessions: list[SessionSummary]) -> list[str]:
    """Tasks claimed by one of the user's sessions whose lease still runs."""
    mine = {summary.session for summary in sessions}
    now = format_ts(project.clock.now())
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id, claim_session FROM tasks WHERE status = :claimed "
                "AND lease_until > :now ORDER BY task_id"
            ),
            {"claimed": TaskStatus.CLAIMED.value, "now": now},
        ).all()
    return [str(task) for task, session in rows if session in mine]


def _proposals(project: Project, user: str) -> list[str]:
    """The user's proposals no decision has answered."""
    open_ids: list[str] = []
    with project.index.connect() as conn:
        for proposed, decided in _PROPOSAL_DECISIONS.items():
            rows = conn.execute(
                text(
                    "SELECT r.ref FROM events e "
                    "JOIN event_refs r ON r.event_id = e.id AND r.position = 0 "
                    'WHERE e."user" = :u AND e.type = :proposed AND NOT EXISTS '
                    "(SELECT 1 FROM event_refs d WHERE d.ref = r.ref AND d.type = :decided) "
                    "ORDER BY e.id"
                ),
                {"u": user, "proposed": proposed, "decided": decided},
            ).all()
            open_ids.extend(str(ref) for (ref,) in rows)
        rows = conn.execute(
            text(
                "SELECT p.proposal_id FROM region_member_proposals p "
                'JOIN events e ON e.id = p.event_id WHERE e."user" = :u AND NOT EXISTS '
                "(SELECT 1 FROM region_member_decisions d WHERE d.proposal_id = p.proposal_id) "
                "ORDER BY p.event_id"
            ),
            {"u": user},
        ).all()
        open_ids.extend(str(ref) for (ref,) in rows)
    return open_ids


def workspace_counts(project: Project, user: str) -> dict[str, JsonValue]:
    """The size of each list of `user`'s workspace."""
    built = workspace(project, user)
    return {
        "sessions": len(built.sessions),
        "open_tasks": len(built.open_tasks),
        "proposals": len(built.proposals),
        "reviews_requested": len(built.reviews_requested),
        "reviews_to_decide": len(built.reviews_to_decide),
    }


def workspace(project: Project, user: str) -> Workspace:
    """What `user` has under way on `project`."""
    project.index.sync()
    roles = roles_of(project, user)
    sessions = _sessions(project, user)
    requests = reviews(project)
    requested = [view for view in requests if view.requester == user]
    to_decide = [
        view
        for view in requests
        if view.state in _UNDECIDED
        and view.requester != user
        and role_suffices(roles, view.required_role)
    ]
    open_tasks = _open_tasks(project, sessions)
    proposals = _proposals(project, user)
    empty = not (sessions or requested or to_decide)
    return Workspace(
        user=user,
        sessions=sessions,
        open_tasks=open_tasks,
        proposals=proposals,
        reviews_requested=requested,
        reviews_to_decide=to_decide,
        roles=roles,
        notice=EMPTY_NOTICE if empty else None,
    )
