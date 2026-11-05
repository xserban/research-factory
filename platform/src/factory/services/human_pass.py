"""What a person may see and run while they screen a pass (slice 5 rulings 15 and 20, R-110).

A human pass is served the agent view whatever the person's role, and two screeners do not see each
other's decisions before reconciliation. A pass session is held to that by session (decision 43).
A person's CLI process mints a new session each time, and their own agents read in sessions of
their own, so here the rule follows the person.

A person is *blind* at a stage while:
- they screen it in person, and its passes have not finished; or
- the project is hosted, they screen it in person or through an agent, and its passes have not
  finished or a disagreement is still open. Off a hosted project the screener may be the only
  person there is, so they read the disagreements once the passes finish, and resolve them.

Invariants:
- Reading only: nothing here writes an event.
- A blind person runs only `MEMBER_COMMANDS` at the CLI, and is refused what a pass session is
  refused over MCP. Deny by default, so a command added later is closed to them.
- An unhosted project with agent passes only is untouched: one researcher can run both passes and
  read the reports from a third session, as in slice 1.
- Withholding here is for a person inside a pass only. A researcher outside the passes reads
  everything their role allows.
"""

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.members import ProjectRole
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import passes_settled
from factory.services.context import Principal, Project
from factory.services.members import roles_of
from factory.services.passes import human_membership, user_kinds

MEMBER_COMMANDS = frozenset(
    {
        "calibrate draw",
        "calibrate label",
        "document read",
        "rebuild",
        "screen join",
        "screen next",
        "screen record",
    }
)
"""What a blind person may run. Calibration stays open because off a hosted project the screener
may be the only labeller (it shows no decision); a hosted project refuses a pass member there."""

_STAGES = (ScreeningStage.TITLE_ABSTRACT, ScreeningStage.FULL_TEXT)


def full_view_allowed(project: Project, principal: Principal) -> bool:
    """Whether the role reads the full view (ruling 20): `owner` or `maintainer`.

    teams-C's own small version: teams-B defines the same function in `services/access.py`, and on
    merge this one gives way to it. Screening in a pass is `blind_stage`'s matter, not this one's.
    """
    return bool(roles_of(project, principal.user) & {ProjectRole.OWNER, ProjectRole.MAINTAINER})


def blind_stage(project: Project, user: str) -> ScreeningStage | None:
    """The first stage at which `user` is blind, or None."""
    hosted: bool | None = None
    for stage in _STAGES:
        kinds = user_kinds(project, user, stage)
        if not kinds:
            continue
        if hosted is None:
            hosted = project.is_hosted()
        if "human" not in kinds and not hosted:
            continue
        if not passes_settled(project, stage=stage, reconciled=hosted):
            return stage
    return None


def served_agent_view(project: Project, principal: Principal) -> bool:
    """Whether a person is served the agent view: inside a pass whatever the role, else by role."""
    if blind_stage(project, principal.user) is not None:
        return True
    return not full_view_allowed(project, principal)


def require_command_allowed(project: Project, command: str) -> None:
    """Refuse a CLI command a blind person may not run. `command` is its path, as in `screen next`.
    An allowed command is let through unasked, so `rebuild` can run on an index that needs it."""
    if command in MEMBER_COMMANDS:
        return
    stage = blind_stage(project, project.principal.user)
    if stage is not None:
        raise FactoryValidationError(
            [ValidationIssue("user", f"you screen {stage.value}: wait until its passes finish")]
        )


def refuse_blind_reader(project: Project, user: str) -> None:
    """Refuse a read by the session of a blind person, which is not itself in a pass."""
    if blind_stage(project, user) is not None:
        raise FactoryValidationError(
            [ValidationIssue("user", "this person screens a pass and cannot use this tool")]
        )


def pass_actor(project: Project, stage: ScreeningStage) -> tuple[Actor, PassLabel]:
    """The person's actor in their pass of `stage`, under the session of their join, and the pass.
    Refused on field `pass` until they have joined."""
    actor = project.human_actor()
    membership = human_membership(project, actor.user, stage)
    if membership is None:
        raise FactoryValidationError(
            [ValidationIssue("pass", "join a pass first: factory screen join --pass A|B")]
        )
    label, session = membership
    return actor.model_copy(update={"session": session}), label
