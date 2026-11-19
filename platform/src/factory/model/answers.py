"""Answers of the papers chat in Ask mode (plan spar-night N2).

An answer is the recorded result of an Ask session: a question, the selection it was asked over,
and sentences, each resting on one verified quote of one paper. The platform judges nothing: the
agent writes the sentences; the platform verifies every quote against the pinned conversion. The
researcher may rate the whole answer or one sentence.

Invariants:
- Nothing is edited: a follow-up is a new answer that names the earlier answer or sheet in
  `parent`.
- Every sentence carries a quote verified when the answer was recorded, with the conversion id and
  markdown hash it was verified against; there is no unsupported sentence. What the papers do not
  answer is said in `unanswered`, outside the sentences.
- `selection_works` lists the (work, conversion) pairs the selection resolved to; its digest is
  `selection_digest`. A sentence is of a work among them, on the conversion listed for it.
- A rating is a human act (`AnswerRated`); the latest rating per (answer, sentence) stands, and a
  rating without a sentence rates the answer as a whole.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

ANSWER_ID_RE = rf"^ans_{ULID_RE}$"
SHEET_ID_RE = rf"^sht_{ULID_RE}$"
PARENT_RE = rf"^(ans|sht)_{ULID_RE}$"
SHA256_HEX_RE = r"^[0-9a-f]{64}$"
QUESTION_MAX = 2000
SENTENCE_MAX = 600
UNANSWERED_MAX = 1000
NOTE_MAX = 600

AnswerMode = Literal["ask"]
AnswerRating = Literal["sound", "weak", "wrong"]


class AnswerSentence(StrictModel):
    """One sentence of an answer with the quote that supports it."""

    text: str = Field(min_length=1, max_length=SENTENCE_MAX)
    work_id: str
    anchor: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    conversion_id: str
    markdown_hash: str


class SelectionWork(StrictModel):
    """One work of the resolved selection with the conversion a chat reads."""

    work_id: str
    conversion_id: str


class AnswerRecorded(StrictModel):
    answer_id: str = Field(pattern=ANSWER_ID_RE)
    question: str = Field(min_length=1, max_length=QUESTION_MAX)
    mode: AnswerMode = "ask"
    selection: dict[str, JsonValue]
    """The selection spec the answer was asked over."""
    selection_digest: str = Field(pattern=SHA256_HEX_RE)
    selection_works: tuple[SelectionWork, ...]
    parent: str | None = Field(default=None, pattern=PARENT_RE)
    sentences: tuple[AnswerSentence, ...]
    unanswered: str | None = Field(default=None, max_length=UNANSWERED_MAX)
    """What the papers of the selection do not answer, when they do not."""


class AnswerRated(StrictModel):
    answer_id: str = Field(pattern=ANSWER_ID_RE)
    sentence: int | None = Field(default=None, ge=0)
    """The 0-based sentence index; None rates the answer as a whole."""
    rating: AnswerRating
    note: str = Field(default="", max_length=NOTE_MAX)
