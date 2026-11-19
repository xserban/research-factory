"""Argument sheets: events of the papers chat in Spar mode (plan chat T7, section 4.6).

A sheet records a hypothesis, the candidates computed over a selection, and the arguments against
and for it. Each argument names a work, an anchor and a quote that was verified against the pinned
conversion when it was recorded, and carries the strength its writer gave it, which is a
judgement, never a count. The researcher may rate an argument afterwards.

Invariants:
- Nothing is edited: a revised sheet is a new sheet that names the earlier one in `supersedes`.
- The candidates table in `SheetOpened` is computed by `chat_candidates`, never typed; the counts
  are those of that table.
- The sections are ordered: arguments against are recorded first; the section for opens only
  after the section against is closed (`SheetSectionClosed`). In `prepare` mode a session that
  recorded an argument against records none for.
- A rating is a human act (`SheetArgumentRated`); the latest rating of an argument stands.
- The balance of a sheet is the researcher's (`SheetBalanceRecorded`, human actor only), written
  once both sections are closed; the latest stands and earlier ones are history. No agent writes,
  computes or suggests it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from factory.model.base import StrictModel
from factory.model.chat_requests import REQUEST_ID_RE
from factory.model.identity import ULID_RE

SHEET_ID_RE = rf"^sht_{ULID_RE}$"
ARGUMENT_ID_RE = rf"^arg_{ULID_RE}$"
SHA256_HEX_RE = r"^[0-9a-f]{64}$"
HYPOTHESIS_MAX = 2000
CLAIM_MAX = 600
NOTE_MAX = 600
BALANCE_MAX = 4000
BALANCE_NOTE_MAX = 1000

Mode = Literal["explore", "prepare"]
Section = Literal["against", "for"]
Strength = Literal["strong", "moderate", "weak"]
Rating = Literal["sound", "weak", "wrong"]
Lean = Literal["against", "mixed", "for", "undecided"]


class SheetCandidate(StrictModel):
    """One work of the selection as `chat_candidates` computed it."""

    work_id: str
    tier: int = Field(ge=1, le=3)
    sources: tuple[str, ...]
    stances: tuple[str, ...]
    over_cap: bool = False


class SheetOpened(StrictModel):
    sheet_id: str = Field(pattern=SHEET_ID_RE)
    hypothesis: str = Field(min_length=1, max_length=HYPOTHESIS_MAX)
    mode: Mode
    selection: dict[str, JsonValue]
    """The selection spec the candidates were computed over."""
    selection_digest: str
    candidates_digest: str = Field(pattern=SHA256_HEX_RE)
    candidates: tuple[SheetCandidate, ...]
    tier1_cap: int = Field(ge=1)
    supersedes: str | None = Field(default=None, pattern=SHEET_ID_RE)
    request_id: str | None = Field(default=None, pattern=REQUEST_ID_RE)
    """The chat request this sheet answers (`chat.requested`), when a headless run opened it."""


class SheetArgumentRecorded(StrictModel):
    argument_id: str = Field(pattern=ARGUMENT_ID_RE)
    sheet_id: str = Field(pattern=SHEET_ID_RE)
    stance: Section
    work_id: str
    anchor: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    conversion_id: str
    markdown_hash: str
    claim: str = Field(min_length=1, max_length=CLAIM_MAX)
    claim_row_key: str | None = None
    """The m-claims row the argument rests on, when it rests on one."""
    claim_row_version: int | None = None
    """The miner version the row key was served from (the listed one, or an older fallback)."""
    strength: Strength
    """The writer's judgement of how strongly the quote bears on the hypothesis."""


class SheetSectionClosed(StrictModel):
    sheet_id: str = Field(pattern=SHEET_ID_RE)
    section: Section
    request_id: str | None = Field(default=None, pattern=REQUEST_ID_RE)
    """The chat request this closing answers: the case for of a Prepare follow-up request."""


class SheetArgumentRated(StrictModel):
    argument_id: str = Field(pattern=ARGUMENT_ID_RE)
    sheet_id: str = Field(pattern=SHEET_ID_RE)
    rating: Rating
    note: str = Field(default="", max_length=NOTE_MAX)


class SheetBalanceRecorded(StrictModel):
    """The researcher's own weighing of a sheet whose two sections are closed."""

    sheet_id: str = Field(pattern=SHEET_ID_RE)
    text: str = Field(min_length=1, max_length=BALANCE_MAX)
    lean: Lean | None = None
    note: str | None = Field(default=None, max_length=BALANCE_NOTE_MAX)
    """What further evidence would be needed, in the researcher's words."""
