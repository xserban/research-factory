"""The contribution ledger's values and the event that confirms it (slice 5 ruling 16, R-112).

Pure: `services/ledger.py` folds the log into these rows, and `index/ledger.py` decides when a
confirmation counts. `ledger` is the contribution ledger; slice 6's evidence-versus-reproduction
ledger is `benchmark_ledger` (decision 75).

Invariants:
- Nothing here is typed by a person or an agent: every count is computed from events (R-05).
- `CREDIT_MAP_V1` is versioned. Changing a row means a new `MAP_VERSION`, which marks every earlier
  confirmation stale.
- An event type the map does not name has no role and is listed as unmapped, never guessed.
- `ledger.confirmed` is a statement about the ledger, not a contribution to it, so it is outside
  the rows, the unmapped list and the hash: a confirmation must not stale itself.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.lab import Reason, UserId
from factory.model.screening import Channel

MAP_VERSION = "credit-map@1"
LEDGER_CONFIRMED = "ledger.confirmed"
LEDGER_HASH_RE = r"^sha256:[0-9a-f]{64}$"
MAP_VERSION_RE = r"^credit-map@[0-9]{1,6}$"


class CreditRole(StrEnum):
    """The 14 CRediT roles. The map produces only some of them; the rest stay for later maps."""

    CONCEPTUALIZATION = "Conceptualization"
    DATA_CURATION = "Data curation"
    FORMAL_ANALYSIS = "Formal analysis"
    FUNDING_ACQUISITION = "Funding acquisition"
    INVESTIGATION = "Investigation"
    METHODOLOGY = "Methodology"
    PROJECT_ADMINISTRATION = "Project administration"
    RESOURCES = "Resources"
    SOFTWARE = "Software"
    SUPERVISION = "Supervision"
    VALIDATION = "Validation"
    VISUALIZATION = "Visualization"
    WRITING_ORIGINAL_DRAFT = "Writing – original draft"  # noqa: RUF001
    WRITING_REVIEW_EDITING = "Writing – review & editing"  # noqa: RUF001


CREDIT_MAP_V1: tuple[tuple[str, CreditRole | None], ...] = (
    ("question.", CreditRole.CONCEPTUALIZATION),
    ("seed.", CreditRole.METHODOLOGY),
    ("probe.", CreditRole.METHODOLOGY),
    ("protocol.", CreditRole.METHODOLOGY),
    ("hypothesis.", CreditRole.METHODOLOGY),
    ("experiment.", CreditRole.METHODOLOGY),
    ("query.", CreditRole.INVESTIGATION),
    ("search.", CreditRole.INVESTIGATION),
    ("chase.", CreditRole.INVESTIGATION),
    ("snowball.", CreditRole.INVESTIGATION),
    ("screening.decision_recorded", CreditRole.INVESTIGATION),
    ("extraction.recorded", CreditRole.INVESTIGATION),
    ("extraction.claim_recorded", CreditRole.INVESTIGATION),
    ("reference.extracted", CreditRole.INVESTIGATION),
    ("xrun.reported", CreditRole.INVESTIGATION),
    ("inbox.link_added", CreditRole.INVESTIGATION),
    ("dedup.", CreditRole.DATA_CURATION),
    ("fulltext.", CreditRole.DATA_CURATION),
    ("document.", CreditRole.DATA_CURATION),
    ("reference.resolved", CreditRole.DATA_CURATION),
    ("region.", CreditRole.DATA_CURATION),
    ("label.", CreditRole.DATA_CURATION),
    ("term.", CreditRole.DATA_CURATION),
    ("watch.", CreditRole.DATA_CURATION),
    ("notice.assessed", CreditRole.DATA_CURATION),
    ("calibration.labelled", CreditRole.VALIDATION),
    ("audit.labelled", CreditRole.VALIDATION),
    ("extraction.audit_labelled", CreditRole.VALIDATION),
    ("screening.disagreement_resolved", CreditRole.VALIDATION),
    ("extraction.resolved", CreditRole.VALIDATION),
    ("reference.resolution_decided", CreditRole.VALIDATION),
    ("draft.verified", CreditRole.VALIDATION),
    ("draft.audited", CreditRole.VALIDATION),
    ("draft.sentence_recorded", CreditRole.WRITING_ORIGINAL_DRAFT),
    ("review.decided", CreditRole.SUPERVISION),
    ("member.", CreditRole.SUPERVISION),
    ("budget.set", CreditRole.SUPERVISION),
    ("task.", None),
    ("project.", None),
    ("screening.pass_", None),
    ("extraction.pass_", None),
)
"""Event type prefix to CRediT role, plan ruling 1 and slice-5 reconciliation item 4. The longest
matching prefix wins. A row with no role is a known type that credits nobody."""

PEOPLE_ONLY: frozenset[CreditRole] = frozenset({CreditRole.SUPERVISION})
"""Roles an agent's event never takes (ruling 1): an agent supervises nothing."""


def map_entry(event_type: str) -> tuple[str, CreditRole | None] | None:
    """The map's row for `event_type` (the longest matching prefix), or None when it is unmapped."""
    matches = [row for row in CREDIT_MAP_V1 if event_type.startswith(row[0])]
    return max(matches, key=lambda row: len(row[0]), default=None)


class PersonRow(StrictModel):
    """One person in one CRediT role."""

    user: str
    role: CreditRole
    events: int
    by_type: dict[str, int]
    first: datetime
    last: datetime


class AgentRow(StrictModel):
    """One agent role, model and skill under its delegating user, with the CRediT role its events
    would map to; `role` is None for events of no role. Never part of the CRediT table."""

    user: str
    agent_role: str
    model: str | None
    skill: str | None
    role: CreditRole | None
    events: int
    by_type: dict[str, int]
    first: datetime
    last: datetime


class Ledger(StrictModel):
    people: list[PersonRow]
    agents: list[AgentRow]
    unmapped: dict[str, int]
    map_version: str
    ledger_hash: str

    @property
    def named(self) -> list[str]:
        """Everyone the statements name: each person, and each user an agent worked for."""
        return sorted({row.user for row in self.people} | {row.user for row in self.agents})


class LedgerConfirmed(StrictModel):
    """A person's confirmation of their entry, pinned to the ledger they read. `reason` is set only
    when an owner confirms for a deactivated user, who can no longer do it."""

    user: UserId
    ledger_hash: str = Field(pattern=LEDGER_HASH_RE)
    map_version: str = Field(pattern=MAP_VERSION_RE)
    channel: Channel
    reason: Reason | None = None


class Confirmation(StrictModel):
    """The latest confirmation of one person; `current` when it pins the ledger as it stands."""

    ledger_hash: str
    current: bool


class LedgerReport(StrictModel):
    """The ledger with its confirmations; `notice` says why it is empty on a fresh project."""

    ledger: Ledger
    confirmations: dict[str, Confirmation]
    notice: str | None
