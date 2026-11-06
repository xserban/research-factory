"""Which channel a human act may come by (slice 5 ruling 11). Pure reads on a fold's connection.

The services refuse what these rules bar, and the folds of the acts apply the same rules, so a
hand-written event that fails one changes nothing, on rebuild too.

Invariants:
- `elicit` is a person answering over an authenticated connection: a human actor with a credential.
- In `systematic`, a relay over a remote connection or on a hosted project is barred. A relay on
  stdio on an unhosted project stays as decision 37 left it (acceptance 1).
- Neither rule can touch an old log: no event before this slice has `channel = elicit`, a credential
  or a host.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.events.envelope import Actor
from factory.index.project import latest_host
from factory.model.project import RigorMode
from factory.model.screening import Channel


def elicit_forged(actor: Actor, channel: Channel) -> bool:
    return channel is Channel.ELICIT and (actor.kind != "human" or actor.credential is None)


def relay_barred(conn: Connection, actor: Actor, channel: Channel) -> bool:
    if channel is not Channel.MCP:
        return False
    if actor.credential is None and latest_host(conn) is None:
        return False
    row = conn.execute(text("SELECT rigor_mode FROM project LIMIT 1")).first()
    return row is not None and str(row[0]) == RigorMode.SYSTEMATIC.value


def sign_off_counts(conn: Connection, actor: Actor, channel: Channel) -> bool:
    """Whether a fold takes a sign-off or an audit label that came by `channel`."""
    return not elicit_forged(actor, channel) and not relay_barred(conn, actor, channel)
