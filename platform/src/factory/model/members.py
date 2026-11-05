"""Project roles and the events that grant them (slice 5 ruling 9).

Grants live in the project's own log, so that log alone is enough for its trace and credit. Pure:
`services/members.py` decides when an event is written, `index/members.py` when one counts.
"""

from enum import StrEnum

from factory.model.base import StrictModel
from factory.model.lab import Reason, UserId


class ProjectRole(StrEnum):
    OWNER = "owner"
    MAINTAINER = "maintainer"
    CONTRIBUTOR = "contributor"
    SCREENER = "screener"
    OBSERVER = "observer"


HUMAN_PASS_ROLES = frozenset({ProjectRole.OWNER, ProjectRole.MAINTAINER, ProjectRole.SCREENER})
"""The roles that hold `pass:join-human`. `services/access.py` decides; the fold cannot import a
service, so it reads this set, and `ROLE_PERMISSIONS` must agree with it."""


class MemberGranted(StrictModel):
    user: UserId
    role: ProjectRole
    reason: Reason


class MemberRevoked(StrictModel):
    user: UserId
    role: ProjectRole
    reason: Reason
