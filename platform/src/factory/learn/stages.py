"""The tutorial stages, in lifecycle order (ids from `services/site_catalog.STAGE_IDS`).

The nine stages are those of the run map on the hub Platform page ("How it works"). `cross`
(status, budget, check, trace) is not a stage; it is in the concepts.
"""

from factory.learn.model import StageCard
from factory.learn.stages_early import ACQUIRE, FRAME, GATHER, SCREEN
from factory.learn.stages_late import DEVELOP, EXTRACT, MAINTAIN, UNDERSTAND, WRITE

STAGES: tuple[StageCard, ...] = (
    FRAME,
    GATHER,
    SCREEN,
    ACQUIRE,
    EXTRACT,
    UNDERSTAND,
    DEVELOP,
    WRITE,
    MAINTAIN,
)


def stage_card(stage_id: str) -> StageCard | None:
    """The card with this id, or None."""
    return next((s for s in STAGES if s.id == stage_id), None)
