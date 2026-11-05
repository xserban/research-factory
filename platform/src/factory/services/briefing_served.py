"""Reads of the served context packs (slice 7b, plan V-C, ruling 4; R-133).

Declares: `served_for`, `stale_sessions`. Apart from `services/briefing.py` because `check` reads
them and the briefing reads `check`. Read-only.

Invariant: a session is stale when its last served pack was built before a change and the session
wrote an agent event after that change. A change is a protocol amendment or an event that can
change the included set; the log does not say which decisions did, so every decision, resolution
and merge counts, and the finding is advisory.
"""

from __future__ import annotations

from sqlalchemy import bindparam, text

from factory.model.views import ServedRow
from factory.services.context import Project

STALE_AFTER = (
    "protocol.amended",
    "screening.decision_recorded",
    "screening.disagreement_resolved",
    "dedup.merged",
    "dedup.reverted",
)


def served_for(project: Project, session: str) -> list[ServedRow]:
    """The packs `session` received, in serving order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT session, blob, audience, as_of, event_id FROM briefings_served "
                "WHERE session = :s ORDER BY event_id"
            ),
            {"s": session},
        ).all()
    return [
        ServedRow(session=str(s), blob=str(b), audience=str(a), as_of=str(o), event_id=str(e))
        for s, b, a, o, e in rows
    ]


def stale_sessions(project: Project) -> list[str]:
    """The sessions whose last served pack predates a change they then wrote after, sorted."""
    project.index.sync()
    statement = text(
        "WITH last AS (SELECT session, MAX(event_id) AS served FROM briefings_served "
        "GROUP BY session), "
        "pack AS (SELECT b.session, b.as_of FROM briefings_served b JOIN last l "
        "ON l.session = b.session AND l.served = b.event_id) "
        "SELECT p.session FROM pack p WHERE EXISTS (SELECT 1 FROM events a "
        "WHERE a.session = p.session AND a.actor_kind = 'agent' AND a.id > "
        "(SELECT MIN(c.id) FROM events c WHERE c.type IN :changes AND c.id > p.as_of)) "
        "ORDER BY p.session"
    ).bindparams(bindparam("changes", expanding=True))
    with project.index.connect() as conn:
        return [str(r[0]) for r in conn.execute(statement, {"changes": list(STALE_AFTER)})]
