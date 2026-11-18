"""`mine.reopened`: the researcher reopens one mined unit after a selector miss (IDEA-99).

Invariants:
- It names a completed task of a registered miner version, and that task's work and pass; the
  reason is non-blank. It is the researcher's act (a human actor, relayed over MCP by a human
  actor), so the index folds no other actor's event.
- It changes no row and no task. A later reader (the extraction ledger) treats the unit as stale
  with reason `reopened` until a task created after the event completes, and the rows the unit
  held when it was recorded are stale from then on.
- Whether the task's selection fell below the fallback threshold needs the manifest, which the
  projection never reads; the service judges that before it writes.

Written by `factory.services.mine_reopen`, folded by `factory.index.mine_reopen`.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.miners import MINER_NAME_RE
from factory.model.screening import NonBlank, PassLabel
from factory.model.task import TASK_ID_RE

MAX_REASON = 500


class MineReopened(StrictModel):
    miner: str = Field(pattern=MINER_NAME_RE)
    version: int = Field(ge=1)
    work_id: str = Field(min_length=1)
    pass_label: PassLabel
    task_id: str = Field(pattern=TASK_ID_RE)
    reason: Annotated[NonBlank, Field(max_length=MAX_REASON)]
