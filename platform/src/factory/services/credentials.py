"""Personal access tokens (slice 5 ruling 7; plan ruling 4).

The lab log says a credential exists, for whom and until when. The secret lives elsewhere: only its
SHA-256, in `<root>/.server/credentials.sqlite`, a git-ignored file of mode 0600 outside the event
model. A credential is valid when the log and the store agree.

Invariants:
- A token is returned once, by `issue_token`. Neither it nor its hash enters an event, a blob, a
  log line or the lab index.
- The hash is stored before the event and removed if the event fails, so a credential the log
  names always has a hash; a hash with no event verifies nothing.
- `verify_token` reads every stored hash and compares each in constant time, and answers None
  for every kind of failure, so a caller cannot tell an unknown token from a revoked one.
"""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Connection

from factory.clock import parse_ts
from factory.events.envelope import Actor
from factory.index import lab as lab_index
from factory.model.lab import (
    DEFAULT_TOKEN_DAYS,
    MAX_TOKEN_DAYS,
    CredentialIssued,
    CredentialRevoked,
)
from factory.services.lab import (
    Lab,
    payload_of,
    private_server_dir,
    read_lab,
    refuse,
    require_admin,
)

TOKEN_PREFIX = "rf_pat_"
_TOKEN_RE = re.compile(rf"{TOKEN_PREFIX}[A-Za-z0-9_-]{{43}}")
_TOKEN_BYTES = 32
_STORE_MODE = 0o600


@dataclass(frozen=True)
class IssuedToken:
    credential_id: str
    token: str
    expires: datetime


@dataclass(frozen=True)
class VerifiedCredential:
    credential_id: str
    user: str


@dataclass(frozen=True)
class CredentialRecord:
    """A credential as the log has it: never its secret."""

    credential_id: str
    user: str
    kind: str
    issued_at: datetime
    expires: datetime
    revoked: bool


def _store_path(root: Path) -> Path:
    """The secret store, created with mode 0600 before SQLite opens it, so it is never readable by
    others, not even empty. SQLite gives its journal the mode of the database."""
    path = private_server_dir(root) / "credentials.sqlite"
    handle = os.open(path, os.O_CREAT | os.O_RDWR, _STORE_MODE)
    try:
        os.fchmod(handle, _STORE_MODE)
    finally:
        os.close(handle)
    return path


def _connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(_store_path(root))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS token_hashes"
        "(credential_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL)"
    )
    return conn


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _store_hash(root: Path, credential_id: str, digest: str) -> None:
    with closing(_connect(root)) as conn, conn:
        conn.execute("INSERT INTO token_hashes VALUES (?, ?)", (credential_id, digest))


def _forget_hash(root: Path, credential_id: str) -> None:
    with closing(_connect(root)) as conn, conn:
        conn.execute("DELETE FROM token_hashes WHERE credential_id = ?", (credential_id,))


def _credential_for(root: Path, digest: str) -> str | None:
    """The credential whose hash is `digest`. Every row is compared, a match or not."""
    with closing(_connect(root)) as conn:
        rows = conn.execute("SELECT credential_id, sha256 FROM token_hashes").fetchall()
    found: str | None = None
    for credential_id, stored in rows:
        if hmac.compare_digest(str(stored).encode(), digest.encode()):
            found = str(credential_id)
    return found


def issue_token(
    lab: Lab, actor: Actor, user: str, *, days: int = DEFAULT_TOKEN_DAYS
) -> IssuedToken:
    """Issue a token to an active user; the only place the token is ever seen. `days` runs from 1
    to `MAX_TOKEN_DAYS`. Refused to anyone but an active admin."""
    if type(days) is not int or not 1 <= days <= MAX_TOKEN_DAYS:
        raise refuse("days", f"must be a whole number from 1 to {MAX_TOKEN_DAYS}")
    token = TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    with lab.writing():
        with lab.index.connect() as conn:
            require_admin(lab, conn, actor)
            if not lab_index.is_active(conn, lab.tables, user):
                raise refuse("user", f"no active user {user!r}")
        credential_id = lab.ids.new("crd")
        expires = lab.clock.now() + timedelta(days=days)
        payload = payload_of(
            CredentialIssued,
            credential_id=credential_id,
            user=user,
            kind="token",
            expires=expires,
        )
        event = lab.events.make("credential.issued", payload, actor)
        _store_hash(lab.settings.root, credential_id, _hash(token))
        try:
            lab.record([event])
        except BaseException:
            _forget_hash(lab.settings.root, credential_id)
            raise
    return IssuedToken(credential_id, token, expires)


def verify_token(lab: Lab, token: str, now: datetime) -> VerifiedCredential | None:
    """The credential and user of `token`; None when it is unknown, expired or revoked, or its
    user is inactive."""
    if _TOKEN_RE.fullmatch(token) is None:
        return None
    credential_id = _credential_for(lab.settings.root, _hash(token))
    if credential_id is None:
        return None

    def read(conn: Connection) -> VerifiedCredential | None:
        credentials = lab.tables["credentials"]
        row = conn.execute(
            select(credentials.c.user, credentials.c.expires, credentials.c.revoked_at).where(
                credentials.c.credential_id == credential_id
            )
        ).first()
        if row is None or row.revoked_at is not None or now >= parse_ts(str(row.expires)):
            return None
        user = str(row.user)
        if not lab_index.is_active(conn, lab.tables, user):
            return None
        return VerifiedCredential(credential_id, user)

    return read_lab(lab, read)


def revoke(lab: Lab, actor: Actor, credential_id: str, reason: str) -> None:
    """Revoke a credential for good. Refused to anyone but an active admin."""
    payload = payload_of(CredentialRevoked, credential_id=credential_id, reason=reason)
    with lab.writing():
        with lab.index.connect() as conn:
            require_admin(lab, conn, actor)
            if not lab_index.credential_exists(conn, lab.tables, credential_id):
                raise refuse("credential_id", "no such credential")
            if lab_index.is_revoked(conn, lab.tables, credential_id):
                raise refuse("credential_id", "already revoked")
        lab.record([lab.events.make("credential.revoked", payload, actor)])


def list_credentials(lab: Lab, user: str | None = None) -> list[CredentialRecord]:
    """Credentials by id, of one user or of everyone."""

    def read(conn: Connection) -> list[CredentialRecord]:
        credentials = lab.tables["credentials"]
        query = select(credentials).order_by(credentials.c.credential_id)
        if user is not None:
            query = query.where(credentials.c.user == user)
        return [
            CredentialRecord(
                credential_id=str(row.credential_id),
                user=str(row.user),
                kind=str(row.kind),
                issued_at=parse_ts(str(row.issued_at)),
                expires=parse_ts(str(row.expires)),
                revoked=row.revoked_at is not None,
            )
            for row in conn.execute(query)
        ]

    return read_lab(lab, read)
