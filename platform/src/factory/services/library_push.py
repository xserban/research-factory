"""Moving literature to a lab server: the receiving side and the pushing client (deploy-C, Task 4).

Invariants:
- A blob is stored only if its bytes hash to the ref it was sent under; a mismatch stores nothing.
- A person may send a blob if they hold `lab:admin`, or hold `work:run` on a project whose events
  reference the hash. Whoever may not send it is told only that the permission is not held, so a
  hash is not an oracle for what the lab holds. The events arrive before the bytes (the project is
  pulled through git first), so the reference exists when the blob is checked.
- The client sends nothing it cannot verify: a local blob that does not hash to its ref is reported
  failed and never sent. The token is never put in a report or a message.
- Outbound requests go through the guard of `factory.sources.guard`: https to public addresses.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import httpx

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.events.library import LabLibrary
from factory.index.library import referenced_hashes
from factory.model.identity import BLOB_REF_RE, IdGenerator
from factory.model.screening import Channel
from factory.services.access import Permission, authorize, not_held
from factory.services.context import Principal, list_projects, open_project
from factory.services.lab import open_lab
from factory.sources.guard import client_hook

MAX_BLOB_BYTES = 128 * 1024 * 1024
"""The largest blob the endpoint takes; a larger body is refused unread past this."""
_REF = re.compile(BLOB_REF_RE)
TIMEOUT_SECONDS = 120.0


def _principal(user: str, credential: str | None) -> Principal:
    return Principal(user=user, credential=credential, channel=Channel.MCP)


def may_send(settings: Settings, clock: Clock, user: str, credential: str | None, ref: str) -> bool:
    """Whether `user` may send (or ask after) the blob `ref`, as described above."""
    session = IdGenerator(clock).ulid()
    lab = open_lab(settings, session=session, clock=clock)
    principal = _principal(user, credential)
    try:
        authorize(None, principal, "human", Permission.LAB_ADMIN, lab=lab)
        return True
    except FactoryValidationError:
        pass
    for slug in list_projects(settings):
        try:
            project = open_project(
                settings, slug, session=session, clock=clock, principal=principal
            )
            project.index.sync()
            if ref not in referenced_hashes(project.index):
                continue
            authorize(project, principal, "human", Permission.WORK_RUN, lab=lab)
            return True
        except FactoryError:
            continue
    return False


def blob_present(
    settings: Settings, clock: Clock, user: str, credential: str | None, ref: str
) -> bool:
    """Whether the lab library holds `ref`; False, whatever the reason, for a person who may not
    send it."""
    if _REF.fullmatch(ref) is None or not may_send(settings, clock, user, credential, ref):
        return False
    return LabLibrary(settings.root).exists(ref)


def receive_blob(
    settings: Settings,
    clock: Clock,
    user: str,
    credential: str | None,
    ref: str,
    data: bytes,
) -> Literal["stored", "present"]:
    """Store `data` in the lab library under `ref`. Refused with nothing written (fields `ref`,
    `permission`, `sha256`, `body`): a malformed ref, a person who may not send it, a body past the
    limit, bytes that do not hash to the ref."""
    if _REF.fullmatch(ref) is None:
        raise FactoryValidationError([ValidationIssue("ref", "must be sha256:<64 hex digits>")])
    if not may_send(settings, clock, user, credential, ref):
        raise not_held(Permission.WORK_RUN)
    if len(data) > MAX_BLOB_BYTES:
        raise FactoryValidationError([ValidationIssue("body", "too large")])
    if f"sha256:{hashlib.sha256(data).hexdigest()}" != ref:
        raise FactoryValidationError([ValidationIssue("sha256", "the bytes do not match the ref")])
    lab = LabLibrary(settings.root)
    present = lab.exists(ref)
    if not present:
        lab.directory.mkdir(parents=True, exist_ok=True)
        lab.put_verified(ref, data)
    return "present" if present else "stored"


@dataclass(frozen=True)
class PushReport:
    """What a push did: blobs sent, blobs the server already held, and refs that failed (a local
    copy missing or corrupt, a refusal, a transport error)."""

    sent: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)


def _url(server_url: str, ref: str) -> str:
    return f"{server_url.rstrip('/')}/library/sha256/{ref.removeprefix('sha256:')}"


def push_client(timeout: float = TIMEOUT_SECONDS) -> httpx.Client:
    """The default client of a push: the outbound guard on every request and redirect."""
    return httpx.Client(timeout=timeout, event_hooks={"request": [client_hook()]})


def push_library(
    settings: Settings,
    slug: str,
    server_url: str,
    token: str,
    *,
    clock: Clock,
    client: httpx.Client | None = None,
    progress: Callable[[str], None] | None = None,
) -> PushReport:
    """Send the project's referenced library blobs to `server_url`: HEAD first, then PUT what the
    server lacks. A failure of one blob does not stop the rest. `client` is for callers that bring
    their own transport (it is not guarded); the default is `push_client()`."""
    session = IdGenerator(clock).ulid()
    project = open_project(settings, slug, session=session, clock=clock)
    project.index.sync()
    refs = sorted(referenced_hashes(project.index))
    headers = {"Authorization": f"Bearer {token}"}
    http = client or push_client()
    sent = skipped = 0
    failed: list[str] = []
    try:
        for ref in refs:
            try:
                data = project.library.get(ref)
            except (BlobNotFoundError, BlobIntegrityError, OSError):
                failed.append(ref)
                continue
            try:
                head = http.head(_url(server_url, ref), headers=headers)
                if head.status_code == 200:
                    skipped += 1
                    continue
                put = http.put(_url(server_url, ref), content=data, headers=headers)
            except httpx.HTTPError:
                failed.append(ref)
                continue
            if put.status_code in (200, 201):
                sent += 1
                if progress is not None:
                    progress(ref)
            else:
                failed.append(ref)
    finally:
        if client is None:
            http.close()
    return PushReport(sent=sent, skipped=skipped, failed=failed)
