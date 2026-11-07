"""Core works: the works a forward snowball round starts from (slice 8, IDEA-43).

A researcher marks a work core, or takes the mark back. The marks are human events: an agent's
`work.marked_core` changes nothing on rebuild (see `factory.index.core_works`). A positive seed's
work is core without a mark. A mark judges nothing about a work; it names where a forward round
may start. Pure value types; written by `factory.services.core_works`.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from factory.model.base import StrictModel
from factory.model.screening import NonBlank
from factory.model.work_ids import WORK_ID_RE

MAX_NOTE = 500

CoreNote = Annotated[NonBlank, Field(max_length=MAX_NOTE)]


class WorkMarkedCore(StrictModel):
    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)]
    note: CoreNote | None = None


class WorkUnmarkedCore(StrictModel):
    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)]
    note: CoreNote | None = None
