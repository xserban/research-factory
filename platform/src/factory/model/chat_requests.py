"""Requests for a headless spar or ask (plan spar-night N3).

A request is the researcher's order: what to spar or ask, over which selection. A headless run of
the stage `spar` or `ask` takes the oldest open request of its kind and answers it with a sheet or
an answer that names the request. The request is a human act; taking it is an agent act (the run's
session); neither judges anything.

Invariants:
- `kind` is `spar` (a hypothesis, a `mode`) or `ask` (a question, no mode). A spar has `hypothesis`
  and no `question`; an ask has `question` and no `hypothesis`, and no `mode`.
- `parent` names an earlier sheet or answer this follows up. A Prepare spar whose parent is a sheet
  with its section against closed asks for the case for of that sheet, from a session that wrote no
  argument of it (`sheets` enforces the split).
- State is never stored: it is derived (`services/chat_requests.py`): open, taken (by a run that is
  still open), done (a result names the request) or failed (the run ended with no result).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

REQUEST_ID_RE = rf"^chr_{ULID_RE}$"
PARENT_RE = rf"^(ans|sht)_{ULID_RE}$"
RUN_ID_RE = rf"^rnr_{ULID_RE}$"
TEXT_MAX = 2000
NOTE_MAX = 600

ChatKind = Literal["spar", "ask"]
ChatMode = Literal["explore", "prepare"]


class ChatRequested(StrictModel):
    request_id: str = Field(pattern=REQUEST_ID_RE)
    kind: ChatKind
    selection: dict[str, JsonValue]
    hypothesis: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    question: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    mode: ChatMode | None = None
    parent: str | None = Field(default=None, pattern=PARENT_RE)
    note: str | None = Field(default=None, max_length=NOTE_MAX)

    @model_validator(mode="after")
    def _shape(self) -> ChatRequested:
        if self.kind == "spar":
            if self.hypothesis is None or self.question is not None or self.mode is None:
                raise ValueError("a spar has a hypothesis and a mode, and no question")
        elif self.question is None or self.hypothesis is not None or self.mode is not None:
            raise ValueError("an ask has a question, and no hypothesis or mode")
        return self


class ChatRequestTaken(StrictModel):
    request_id: str = Field(pattern=REQUEST_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)
