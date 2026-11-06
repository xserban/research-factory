"""Pass membership and the independence rule, written once (slice M ruling 21, decision 55).

A session joins a screening pass (table `pass_sessions`, one row per session and stage) or an
extraction pass (table `extraction_sessions`, one row per session). Surfaces ask this module
whether a session belongs to a pass, never the tables.

The users of a screening pass, U(P), are its human screeners and the principals of its agents
(slice 5 ruling 15). `pass_users` reads them; `require_outside_passes` keeps a member of either
pass of a stage from labelling, resolving or auditing at that stage of a hosted project.

Invariants:
- `memberships` and `is_pass_session` only read the index (after a sync); nothing is written.
- A human act relayed over MCP is refused to a session in any pass of any module (decision 55):
  `require_not_pass_session` takes no module.
- `shared_refusal` is pure: each module collects its own evidence of joins (screening and
  extraction both read the log, as the projection keeps one join per session), and the decision
  is this one function. Its texts are the texts of the modules before the merge.
- `users` is given to `shared_refusal` for a hosted project only: an unhosted project keeps the
  slice-1 rule, so one researcher can run both agent passes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index import screening as screening_index
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.stages import require_pass_stage

PassModule = Literal["screening", "extraction"]
TA = ScreeningStage.TITLE_ABSTRACT


@dataclass(frozen=True)
class PassMembership:
    """One pass a session joined. `scope` is set for extraction, `stage` for screening."""

    module: PassModule
    scope: str | None
    stage: str | None
    label: PassLabel


def memberships(project: Project, session: str) -> frozenset[PassMembership]:
    """Every pass `session` joined, in both modules. Syncs the index; one query per table."""
    project.index.sync()
    found: set[PassMembership] = set()
    with project.index.connect() as conn:
        screening = conn.execute(
            text("SELECT stage, pass_label FROM pass_sessions WHERE session = :session"),
            {"session": session},
        ).all()
        extraction = conn.execute(
            text("SELECT scope, pass_label FROM extraction_sessions WHERE session = :session"),
            {"session": session},
        ).all()
    for stage, label in screening:
        found.add(PassMembership("screening", None, str(stage), PassLabel(str(label))))
    for scope, label in extraction:
        found.add(PassMembership("extraction", str(scope), None, PassLabel(str(label))))
    return frozenset(found)


def is_pass_session(
    project: Project,
    session: str,
    *,
    module: PassModule | None = None,
    stage: ScreeningStage | None = None,
) -> bool:
    """Whether `session` joined a pass, of `module` (any when None) and, for screening, at `stage`
    (any when None). A `stage` restricts to screening memberships."""
    if stage is not None:
        require_pass_stage(stage)
    for member in memberships(project, session):
        if module is not None and member.module != module:
            continue
        if stage is not None and (member.module != "screening" or member.stage != stage.value):
            continue
        return True
    return False


def pass_users(project: Project, label: PassLabel, stage: ScreeningStage = TA) -> frozenset[str]:
    """U(P): the humans of pass `label` of `stage` and the principals of its agents."""
    project.index.sync()
    with project.index.connect() as conn:
        return screening_index.pass_users(conn, label.value, require_pass_stage(stage).value)


def pass_kinds(project: Project, label: PassLabel, stage: ScreeningStage = TA) -> frozenset[str]:
    """Who screens pass `label` of `stage`: `agent`, `human`, or nothing yet."""
    project.index.sync()
    with project.index.connect() as conn:
        return screening_index.pass_kinds(conn, label.value, require_pass_stage(stage).value)


def human_membership(
    project: Project, user: str, stage: ScreeningStage = TA
) -> tuple[PassLabel, str] | None:
    """The pass `user` screens in person at `stage`, and the session of that join. A person's
    every act in the pass runs in that session, whichever process makes it, since a CLI process
    mints its own: the file `events/<user>/<session>.jsonl` is appended under the project lock."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT pass_label, session FROM pass_sessions WHERE user = :user "
                "AND stage = :stage AND actor_kind = 'human' ORDER BY session LIMIT 1"
            ),
            {"user": user, "stage": require_pass_stage(stage).value},
        ).first()
    return None if row is None else (PassLabel(str(row[0])), str(row[1]))


def user_kinds(project: Project, user: str, stage: ScreeningStage = TA) -> frozenset[str]:
    """How `user` screens at `stage`: `human` in person, `agent` through an agent; empty when
    neither."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT actor_kind FROM pass_sessions "
                "WHERE user = :user AND stage = :stage"
            ),
            {"user": user, "stage": require_pass_stage(stage).value},
        ).all()
    return frozenset(str(row[0]) for row in rows)


def require_outside_passes(project: Project, user: str, stage: ScreeningStage = TA) -> None:
    """Refuse a member of either pass of `stage` on a hosted project (plan teams-C ruling 2): a
    calibration label, a resolution and an audit are by a person who joined neither."""
    if not project.is_hosted():
        return
    for label in PassLabel:
        if user in pass_users(project, label, stage):
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "user", f"this person screens pass {label.value} of {stage.value}"
                    )
                ]
            )


def shared_refusal(
    sessions: Mapping[PassLabel, set[str]],
    models: Mapping[PassLabel, set[str]],
    *,
    noun: Literal["screening", "extraction"],
    users: Mapping[PassLabel, frozenset[str]] | None = None,
) -> FactoryValidationError | None:
    """The refusal for a pass pair that is not independent, or None.

    `sessions` and `models` hold, per pass, the sessions that joined it and the models that ran
    it. A session in both passes is refused first, then a model in both, then, when `users` is
    given, a person in both. Field `passes`."""
    if sessions[PassLabel.A] & sessions[PassLabel.B]:
        if noun == "screening":
            return _refuse("a session has joined both passes; each pass needs its own session")
        return _refuse("a session has joined both extraction passes; each needs its own session")
    shared = sorted(models[PassLabel.A] & models[PassLabel.B])
    if shared:
        needs = "each pass needs its own" if noun == "screening" else "each needs its own"
        return _refuse(f"the passes share a model ({', '.join(shared)}); {needs}")
    if users is not None and users[PassLabel.A] & users[PassLabel.B]:
        return _refuse("one person screens both passes; each pass needs its own people")
    return None


def require_not_pass_session(
    project: Project,
    actor: Actor,
    channel: Channel,
    *,
    field: str = "channel",
    reason: str = "this session has joined a pass",
) -> list[ValidationIssue]:
    """Issues for a human act relayed over MCP by a session in a pass of any module; else none."""
    if channel.remote and is_pass_session(project, actor.session):
        return [ValidationIssue(field, reason)]
    return []


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])
