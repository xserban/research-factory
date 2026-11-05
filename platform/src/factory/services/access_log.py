"""The server access log (slice 5 ruling 12; plan ruling 5).

Reads and refusals are not research facts and write no event. They leave one line in
`<root>/.server/access/<YYYY-MM-DD>.jsonl`, git-ignored, append-only, mode 0600.

Invariants:
- A line never carries an argument value: only who, which tool, which project, the outcome, and the
  names of the fields at fault. `AccessEntry` refuses a field that does not read as a name.
- `audited` writes nothing on a root with no `.server/`, so a personal machine gains no private
  directory its `.gitignore` does not know about.
- `prune` removes only files whose whole name is a date older than the term.
"""

import os
import pwd
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_serializer, field_validator

from factory.canonical import canonical_json
from factory.clock import Clock, format_ts
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE
from factory.services.context import Principal
from factory.services.lab import private_server_dir, refuse

DEFAULT_KEEP_DAYS = 365
MAX_KEEP_DAYS = 36500
_MAX_FIELDS = 100
_FIELD_RE = r"^[A-Za-z0-9_.\[\]-]{1,200}$"
_LOG_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})\.jsonl")
_LOG_MODE = 0o600
_DIR_MODE = 0o700

Outcome = Literal["ok", "refused", "error"]
FieldName = Annotated[str, Field(pattern=_FIELD_RE)]


class AccessEntry(StrictModel):
    """One call. `principal` is None when no credential could be resolved; `os_login` is set only
    by the CLI's admin commands (slice 5, "Principal and actor")."""

    ts: datetime
    principal: str | None
    credential: str | None
    session: str | None
    channel: str
    tool: str = Field(min_length=1, max_length=200)
    project: str | None
    outcome: Outcome
    fields: tuple[FieldName, ...] = Field(default=(), max_length=_MAX_FIELDS)
    os_login: str | None = None

    @field_validator("ts")
    @classmethod
    def _ts_is_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("ts must be a UTC timestamp")
        return value

    @field_serializer("ts", when_used="json")
    def _serialize_ts(self, value: datetime) -> str:
        return format_ts(value)


def field_names(issues: Iterable[ValidationIssue]) -> tuple[str, ...]:
    """The issues' fields fit for a line, in order and without repeats. A field that does not read
    as a name is dropped, not logged."""
    names = dict.fromkeys(i.field for i in issues if re.fullmatch(_FIELD_RE, i.field))
    return tuple(names)[:_MAX_FIELDS]


def _access_dir(root: Path) -> Path:
    path = private_server_dir(root) / "access"
    path.mkdir(mode=_DIR_MODE, exist_ok=True)
    return path


class AccessLog:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, entry: AccessEntry) -> None:
        """Append one line to the file of the entry's UTC date, and fsync it."""
        data: dict[str, JsonValue] = entry.model_dump(mode="json")
        if data["os_login"] is None:
            del data["os_login"]
        path = _access_dir(self._root) / f"{entry.ts.date().isoformat()}.jsonl"
        handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _LOG_MODE)
        with os.fdopen(handle, "ab") as log:
            os.fchmod(log.fileno(), _LOG_MODE)
            log.write(canonical_json(data) + b"\n")
            log.flush()
            os.fsync(log.fileno())


def prune(root: Path, keep_days: int = DEFAULT_KEEP_DAYS, *, now: datetime | None = None) -> int:
    """Remove the daily files older than `keep_days`; returns how many were removed."""
    if type(keep_days) is not int or not 1 <= keep_days <= MAX_KEEP_DAYS:
        raise refuse("keep_days", f"must be a whole number from 1 to {MAX_KEEP_DAYS}")
    directory = root / ".server" / "access"
    if not directory.is_dir():
        return 0
    oldest = (now or datetime.now(UTC)).date() - timedelta(days=keep_days)
    removed = 0
    for path in directory.iterdir():
        match = _LOG_NAME.fullmatch(path.name)
        if match is None:
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if day < oldest:
            path.unlink()
            removed += 1
    return removed


def os_login() -> str:
    """The login of this process, from the system and not the environment."""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return str(os.getuid())


def stated_admin(settings: Settings, as_user: str | None) -> Settings:
    """The settings an admin command acts under. On a server the login is often a service account,
    so an admin who is not the login says who they are with `--as`; a user taken from the
    environment alone does not do (slice 5, "Principal and actor")."""
    if as_user is None:
        if settings.user != os_login():
            raise refuse("as", "the acting user is not the OS login; state it with --as")
        return settings
    if re.fullmatch(ACTOR_ID_RE, as_user) is None:
        raise refuse("as", f"must match {ACTOR_ID_RE}")
    return settings.model_copy(update={"user": as_user})


@contextmanager
def audited(
    settings: Settings,
    principal: Principal,
    *,
    session: str,
    clock: Clock,
    tool: str,
    project: str | None = None,
    login: str | None = None,
) -> Iterator[None]:
    """Leave one line for the call in the block: `ok`, `refused` when a permission was missing,
    else `error`. The exception goes on to the caller."""

    def write(outcome: Outcome, fields: tuple[str, ...] = ()) -> None:
        if not (settings.root / ".server").is_dir():
            return
        AccessLog(settings.root).write(
            AccessEntry(
                ts=clock.now().astimezone(UTC),
                principal=principal.user,
                credential=principal.credential,
                session=session,
                channel=principal.channel.value,
                tool=tool,
                project=project,
                outcome=outcome,
                fields=fields,
                os_login=login,
            )
        )

    try:
        yield
    except FactoryValidationError as exc:
        refused = any(issue.field == "permission" for issue in exc.issues)
        write("refused" if refused else "error", field_names(exc.issues))
        raise
    except Exception:
        write("error")
        raise
    write("ok")
