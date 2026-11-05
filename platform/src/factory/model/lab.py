"""The lab registry's value types and event payloads (slice 5 rulings 6 and 9).

People span projects, so they live in a log of their own under `<root>/lab/`. This module is pure:
it bounds every field at the model boundary. `services/lab.py` decides when an event is written,
and `index/lab.py` when one counts.

Invariants:
- No address and no secret here: an email is stored only as the SHA-256 of its lower-cased form.
- `lab_roles` is never empty and never repeats a role.
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator

from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE, ULID_RE

LAB_SLUG = "lab"
"""The envelope `project` of the lab log, so no project may take this slug (plan ruling 1)."""

MAX_NAME_LENGTH = 200
MAX_REASON_LENGTH = 2000
MAX_IDENTITY_LENGTH = 512
SHA256_HEX_RE = r"^[0-9a-f]{64}$"
CREDENTIAL_ID_RE = rf"^crd_{ULID_RE}$"
DEFAULT_TOKEN_DAYS = 90
MAX_TOKEN_DAYS = 365


class LabRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


def _distinct(roles: tuple[LabRole, ...]) -> tuple[LabRole, ...]:
    if len(set(roles)) != len(roles):
        raise ValueError("lab_roles must not repeat a role")
    return roles


UserId = Annotated[str, Field(pattern=ACTOR_ID_RE)]
LabRoles = Annotated[tuple[LabRole, ...], Field(min_length=1), AfterValidator(_distinct)]
Reason = Annotated[str, Field(min_length=1, max_length=MAX_REASON_LENGTH)]
IdentityPart = Annotated[str, Field(min_length=1, max_length=MAX_IDENTITY_LENGTH)]


class UserRegistered(StrictModel):
    user: UserId
    display_name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    email_hash: str | None = Field(default=None, pattern=SHA256_HEX_RE)
    lab_roles: LabRoles


class IdentityLinked(StrictModel):
    """The `subject` of an external provider `issuer` is this user (ruling 7)."""

    user: UserId
    issuer: IdentityPart
    subject: IdentityPart


class UserDeactivated(StrictModel):
    user: UserId
    reason: Reason


class UserReactivated(StrictModel):
    user: UserId
    reason: Reason


class LabRoleSet(StrictModel):
    user: UserId
    lab_roles: LabRoles


class CredentialIssued(StrictModel):
    """A credential exists. It carries no secret and no hash: those stay in the secret store."""

    credential_id: str = Field(pattern=CREDENTIAL_ID_RE)
    user: UserId
    kind: Literal["token"]
    expires: datetime

    @field_validator("expires")
    @classmethod
    def _expires_is_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("expires must be a UTC timestamp")
        return value


class CredentialRevoked(StrictModel):
    credential_id: str = Field(pattern=CREDENTIAL_ID_RE)
    reason: Reason
