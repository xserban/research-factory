"""Events of the agentic spar, engine v2 (plan spar-night N6, IDEA-101).

A v2 spar is one chat request (`chat.requested`, `engine: v2`) worked by separate headless role
sessions, one `claude -p` process each: searcher, one reader per tier-1 paper, a writer of the case
against, a different writer of the case for, a critic and a coverage sweep. The platform sequences
them (`services/spar_v2.py`); nothing here judges.

Invariants:
- `spar.role_started` is a system event written by the coordinator when it starts a role run. It is
  the assignment: which request, which role, which paper (readers only). It is never written by an
  agent or a human; the fold ignores a hand-written one.
- `spar.reading_recorded`, `sheet.argument_checked` and `spar.coverage_recorded` are agent events
  written by the run that holds the matching role. A check is the critic's reading of one argument
  against its full paragraph; it is never a rating, and a rating stays a human act
  (`sheet.argument_rated`).
- Counts in an event (sections read, papers examined) are computed at the service boundary, never
  typed by the agent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.chat_requests import REQUEST_ID_RE, RUN_ID_RE
from factory.model.identity import ULID_RE

SPAR_ROLES = ("search", "read", "against", "for", "critic", "cover")
SparRole = Literal["search", "read", "against", "for", "critic", "cover"]
ReadingStance = Literal["against", "for", "neither"]
CheckVerdict = Literal["holds", "overreaches", "misread"]

ARGUMENT_ID_RE = rf"^arg_{ULID_RE}$"
SHEET_ID_RE = rf"^sht_{ULID_RE}$"
WHY_MAX = 600
REASON_MAX = 600
NOTE_MAX = 1000


class SparRoleStarted(StrictModel):
    """A role run started for a request (system actor)."""

    request_id: str = Field(pattern=REQUEST_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)
    role: SparRole
    work_id: str | None = None
    """The paper a reader reads; none for any other role."""


class ReadingItem(StrictModel):
    """One passage a reader found relevant, verified when the reading was recorded."""

    anchor: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    stance: ReadingStance
    """The reader's proposed stance toward the hypothesis: a proposal, not a rating."""
    why: str = Field(min_length=1, max_length=WHY_MAX)


class SparReadingRecorded(StrictModel):
    request_id: str = Field(pattern=REQUEST_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)
    work_id: str
    items: tuple[ReadingItem, ...]
    sections_read: tuple[str, ...]
    """Section anchors the reader says it read, each checked to be a section of the paper."""
    sections_total: int = Field(ge=0)
    """The sections of the pinned conversion, computed."""
    conversion_id: str
    markdown_hash: str
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class ArgumentCheck(StrictModel):
    argument_id: str = Field(pattern=ARGUMENT_ID_RE)
    verdict: CheckVerdict
    reason: str = Field(min_length=1, max_length=REASON_MAX)


class SheetArgumentChecked(StrictModel):
    """The critic's check of one argument: quote against its full paragraph. Not a rating."""

    argument_id: str = Field(pattern=ARGUMENT_ID_RE)
    sheet_id: str = Field(pattern=SHEET_ID_RE)
    request_id: str = Field(pattern=REQUEST_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)
    verdict: CheckVerdict
    reason: str = Field(min_length=1, max_length=REASON_MAX)


class FlaggedWork(StrictModel):
    work_id: str
    reason: str = Field(min_length=1, max_length=WHY_MAX)


class SparCoverageRecorded(StrictModel):
    """The coverage sweep over the papers no source proposed."""

    request_id: str = Field(pattern=REQUEST_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)
    sheet_id: str = Field(pattern=SHEET_ID_RE)
    examined: tuple[str, ...]
    flagged: tuple[FlaggedWork, ...]
    unproposed_total: int = Field(ge=0)
    """Papers of the selection no source proposed (tier 3), computed."""
    not_examined: int = Field(ge=0)
    """`unproposed_total` less the examined, computed."""
    note: str | None = Field(default=None, max_length=NOTE_MAX)
