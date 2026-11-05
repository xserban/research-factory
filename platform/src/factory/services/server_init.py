"""`factory server init`: make this root a lab server (slice 5, user flow 1).

Invariants:
- Everything is checked before anything is written, and a second run changes nothing it need not:
  it adds what is missing and refuses to change the host id.
- The first person registered is the caller, as lab `admin`; a registry with people in it gains
  nobody here.
- Only that bootstrap is open. Once the registry has people, a run needs `lab:admin` before it
  writes anything, so nobody else can reach the push allow-list.
- The `.gitignore` entries are those `factory server check` asks for, kept in one list, and they
  are in place before anything is written under `.server/`.
- The push allow-list holds only URLs the researcher stated. Nothing here reads a git remote or
  contacts one, and a run adds URLs, never removes one. With none listed, `factory commit --push`
  refuses, which is the safe state.
"""

import os
import re
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from factory.clock import Clock
from factory.config import Settings
from factory.index.lab import registry_is_empty
from factory.model.identity import ACTOR_ID_RE
from factory.model.lab import LabRole
from factory.model.screening import Channel
from factory.services.access import Permission, authorize
from factory.services.commit import PUSH_REMOTES_FILE, allowed_push_urls
from factory.services.context import Principal
from factory.services.lab import (
    init_lab,
    private_server_dir,
    read_lab,
    refuse,
    register_user,
)
from factory.services.server_check import GITIGNORED

MAX_PUSH_URL_LENGTH = 2000
_PUSH_FILE_MODE = 0o600
_PUSH_FILE_HEADER = (
    "# The URLs `factory commit --push` may push to: one per line, matched exactly.\n"
)


@dataclass(frozen=True)
class ServerInit:
    host_id: str
    admin: str | None
    """The person this run registered; None when the registry already had people."""
    push_urls: int
    """How many push URLs the allow-list holds after this run."""


def _default_host_id() -> str:
    name = socket.gethostname().split(".")[0].lower()
    if re.fullmatch(ACTOR_ID_RE, name) is None:
        raise refuse("host_id", "this machine's name is not a host id; pass --host-id")
    return name


def _ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    text = path.read_text() if path.is_file() else ""
    present = {line.strip() for line in text.splitlines()}
    missing = [entry for entry in GITIGNORED if entry not in present]
    if not missing:
        return
    joined = "\n".join(missing) + "\n"
    path.write_text(text + ("" if not text or text.endswith("\n") else "\n") + joined)


def _push_urls(urls: Iterable[str]) -> list[str]:
    """The stated URLs as the allow-list reads them, without repeats. A URL that could not match
    one line of the file, or that the file would read as a comment, is refused."""
    cleaned = [url.strip() for url in urls]
    for index, url in enumerate(cleaned):
        if not url or len(url) > MAX_PUSH_URL_LENGTH:
            raise refuse(f"push_urls.{index}", f"must be 1 to {MAX_PUSH_URL_LENGTH} characters")
        if url.startswith("#") or re.search(r"\s", url) is not None:
            raise refuse(f"push_urls.{index}", "must be one URL, with no spaces")
    return list(dict.fromkeys(cleaned))


def _add_push_urls(root: Path, urls: list[str]) -> int:
    """Create the allow-list if need be and add `urls` to it; returns how many it then holds."""
    path = root / PUSH_REMOTES_FILE
    known = allowed_push_urls(root)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = "".join(f"{url}\n" for url in urls if url not in known)
    if not text:
        lines = _PUSH_FILE_HEADER + lines
    elif not text.endswith("\n"):
        lines = "\n" + lines
    handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _PUSH_FILE_MODE)
    with os.fdopen(handle, "a", encoding="utf-8") as allow_list:
        os.fchmod(allow_list.fileno(), _PUSH_FILE_MODE)
        allow_list.write(lines)
    return len(known | set(urls))


def init_server(
    settings: Settings,
    *,
    host_id: str | None,
    push_urls: Iterable[str] = (),
    session: str,
    clock: Clock,
) -> ServerInit:
    """Create the lab registry, `<root>/.server/` with its host id and push allow-list, and the
    `.gitignore` entries.

    The host id is `host_id`, else the one already configured, else this machine's name. Refused,
    with nothing written, when it is malformed or differs from the stored one, when a push URL is
    malformed, and without `lab:admin` once the registry has people."""
    resolved = host_id or settings.host_id or _default_host_id()
    if re.fullmatch(ACTOR_ID_RE, resolved) is None:
        raise refuse("host_id", f"must match {ACTOR_ID_RE}")
    stored_path = settings.root / ".server" / "host_id"
    stored = stored_path.read_text().strip() if stored_path.is_file() else None
    if stored and stored != resolved:
        raise refuse("host_id", f"this root is already host {stored}")
    urls = _push_urls(push_urls)

    lab = init_lab(settings, session=session, clock=clock)
    with lab.writing():
        bootstrap = read_lab(lab, lambda conn: registry_is_empty(conn, lab.tables))
        if not bootstrap:
            principal = Principal.local(settings, Channel.CLI)
            authorize(None, principal, "human", Permission.LAB_ADMIN, lab=lab)
        server_dir = private_server_dir(settings.root)
        _ensure_gitignore(settings.root)
        (server_dir / "host_id").write_text(f"{resolved}\n")
        listed = _add_push_urls(settings.root, urls)
        if bootstrap:
            actor = lab.human_actor()
            register_user(lab, actor, settings.user, settings.user, None, (LabRole.ADMIN,))
    return ServerInit(resolved, settings.user if bootstrap else None, listed)
