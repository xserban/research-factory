"""Hosting: one writer per hosted project (slice 5 rulings 2 and 19).

`project.hosted` names the host; from then on `EventWriter` refuses any machine whose
`Settings.host_id` differs. An unhosted project has no host and no host check.

Invariants:
- Only a person hosts a project (lab administration; agents never hold it). The fold enforces the
  same rule, so a hand-written event of any other actor changes nothing.
- `previous_host` comes from the fold, never from the caller.
"""

import re

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.hosting import ProjectHosted
from factory.model.identity import ACTOR_ID_RE
from factory.services.context import Project, hosted_by


def current_host(project: Project) -> str | None:
    """The host named by the last folded `project.hosted`; None for an unhosted project."""
    return hosted_by(project.index)


def host_project(project: Project, actor: Actor, host_id: str) -> str:
    """Record that `host_id` is the project's only writer; returns the event id.

    Refused, with nothing written: an actor who is not a person (`actor`); a malformed host, or the
    host already named (`host_id`). A machine other than the current host is refused by the host
    check itself (`host`), so only the current host can move a project."""
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "only a person hosts a project")])
    if re.fullmatch(ACTOR_ID_RE, host_id) is None:
        raise FactoryValidationError([ValidationIssue("host_id", f"must match {ACTOR_ID_RE}")])
    with project.writing():
        previous = current_host(project)
        if previous == host_id:
            raise FactoryValidationError(
                [ValidationIssue("host_id", f"project is already hosted by {host_id}")]
            )
        payload = ProjectHosted(host_id=host_id, previous_host=previous)
        event = project.events.make("project.hosted", payload, actor)
        project.record([event])
    return event.id
