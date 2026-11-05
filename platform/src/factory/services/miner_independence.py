"""Who may run a miner's calibration pass, and who may not (slice M ruling 16; R-51).

Invariants:
- The proposer is never the evaluator: the session that registered a miner version, a session that
  relayed a gold label of its calibration and a session of a production pass of the miner may not
  serve the calibration pass; a session that served calibration tasks may not serve a production
  pass of that miner.
- A refusal is neutral: it names the field `session` and says the session cannot serve this pass,
  never which rule applied, a count, a threshold or a score (decision 43).
- Everything here reads the index (after a sync); nothing is written.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.mining import registered_row
from factory.services.passes import is_pass_session, memberships
from factory.services.protocol import current_protocol

__all__ = [
    "calibration_sessions",
    "label_sessions",
    "require_calibration_pass",
    "require_production_pass",
    "resolve_issues",
]

_REFUSED = "this session cannot serve this pass"


def calibration_sessions(project: Project, name: str) -> set[str]:
    """The sessions that claimed a calibration task of miner `name` (any calibration)."""
    project.index.sync()
    with project.index.connect() as conn:
        drawn = conn.execute(
            text("SELECT 1 FROM miner_calibrations WHERE name = :n LIMIT 1"), {"n": name}
        ).first()
        if drawn is None:
            return set()
        rows = conn.execute(
            text("SELECT claim_session, content_blob FROM tasks WHERE claim_session IS NOT NULL")
        ).all()
    found: set[str] = set()
    for session, blob in rows:
        content = project.blobs.get_json(str(blob))
        if (
            isinstance(content, dict)
            and content.get("miner") == name
            and content.get("calibration_id") is not None
        ):
            found.add(str(session))
    return found


def label_sessions(project: Project, calibration_id: str) -> set[str]:
    """The sessions that recorded a gold label of the calibration (every one, superseded or not)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT session FROM miner_calibration_label_sessions WHERE calibration_id = :c"),
            {"c": calibration_id},
        ).all()
    return {str(row[0]) for row in rows}


def _joined_miner(project: Project, session: str, name: str) -> bool:
    return any(m.module == "extraction" and m.scope == name for m in memberships(project, session))


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def require_calibration_pass(
    project: Project, actor: Actor, name: str, version: int, label: PassLabel
) -> str:
    """The id of the open calibration of `(name, version)` when `actor` may serve its pass.

    Refused on field `pass` for pass B, `calibration` when none is drawn, and `session` as the
    module docstring says."""
    if label is not PassLabel.A:
        raise _refuse("pass", "a calibration is one pass")
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT calibration_id FROM miner_calibrations "
                "WHERE name = :n AND version = :v ORDER BY event_id LIMIT 1"
            ),
            {"n": name, "v": version},
        ).one_or_none()
    if row is None:
        raise _refuse("calibration", "no calibration is drawn for this miner version")
    calibration_id = str(row[0])
    registered = registered_row(project, name, version)
    session = actor.session
    own = calibration_sessions(project, name)
    if (
        (registered is not None and session == registered.proposer_session)
        or session in label_sessions(project, calibration_id)
        or (_joined_miner(project, session, name) and session not in own)
    ):
        raise _refuse("session", _REFUSED)
    return calibration_id


def require_production_pass(project: Project, actor: Actor, name: str) -> None:
    """Refuse (field `session`) a production pass to a session that served calibration tasks of
    miner `name`."""
    if actor.session in calibration_sessions(project, name):
        raise _refuse("session", _REFUSED)


def resolve_issues(
    project: Project, actor: Actor, name: str, channel: Channel
) -> list[ValidationIssue]:
    """Why `actor` may not resolve a disagreement of miner `name` beyond the gate's own policy
    (gate `mine.resolve`): an agent proposer's session, whether it acts as an agent or relays a
    human act over MCP, and an agent in any pass. Field `session`, neutral text."""
    protocol = current_protocol(project)
    use = None
    if protocol is not None:
        use = next((u for u in protocol.spec.miners or () if u.name == name), None)
    registered = None if use is None else registered_row(project, name, use.version)
    issues: list[ValidationIssue] = []
    relayed = actor.kind != "human" or channel is Channel.MCP
    if (
        registered is not None
        and registered.proposer_kind == "agent"
        and relayed
        and actor.session == registered.proposer_session
    ):
        issues.append(ValidationIssue("session", _REFUSED))
    if actor.kind != "human" and is_pass_session(project, actor.session):
        issues.append(ValidationIssue("session", _REFUSED))
    return issues
