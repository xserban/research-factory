"""Pass membership and the independence rule, written once (slice M ruling 21, decision 55).

A session joins a screening pass (table `pass_sessions`, one row per session and stage) or an
extraction pass (table `extraction_sessions`, one row per session). Surfaces ask this module
whether a session belongs to a pass, never the tables.

Invariants:
- `memberships` and `is_pass_session` only read the index (after a sync); nothing is written.
- A human act relayed over MCP is refused to a session in any pass of any module (decision 55):
  `require_not_pass_session` takes no module.
- `shared_refusal` is pure: each module collects its own evidence of joins (screening and
  extraction both read the log, as the projection keeps one join per session), and the decision
  is this one function. Its texts are the texts of the modules before the merge.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project

PassModule = Literal["screening", "extraction"]


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
    for member in memberships(project, session):
        if module is not None and member.module != module:
            continue
        if stage is not None and (member.module != "screening" or member.stage != stage.value):
            continue
        return True
    return False


def shared_refusal(
    sessions: Mapping[PassLabel, set[str]],
    models: Mapping[PassLabel, set[str]],
    *,
    noun: Literal["screening", "extraction"],
) -> FactoryValidationError | None:
    """The refusal for a pass pair that is not independent, or None.

    `sessions` and `models` hold, per pass, the sessions that joined it and the models that ran
    it. A session in both passes is refused first, then a model in both. Field `passes`."""
    if sessions[PassLabel.A] & sessions[PassLabel.B]:
        if noun == "screening":
            return _refuse("a session has joined both passes; each pass needs its own session")
        return _refuse("a session has joined both extraction passes; each needs its own session")
    shared = sorted(models[PassLabel.A] & models[PassLabel.B])
    if shared:
        needs = "each pass needs its own" if noun == "screening" else "each needs its own"
        return _refuse(f"the passes share a model ({', '.join(shared)}); {needs}")
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
    if channel is Channel.MCP and is_pass_session(project, actor.session):
        return [ValidationIssue(field, reason)]
    return []


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])
