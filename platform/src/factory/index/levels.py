"""The autonomy level the folds can see, with no table or column (lane L14).

The gate-policy folds (`index.hypotheses.policy_of`) read the rigor preset and the protocol; under
a non-attended level they must also read the autonomy profile. The level lives in the first
`project.created` event, so the fold reads it from the log through a reader attached to the
`project` table's `info`, and no state hash changes.

Invariants:
- The reader returns `attended` while no `project.created` exists, and a legacy event (no
  `autonomy_level`) gives `attended`: today's result.
- Once found, the level is fixed (the first event wins, as in the `project` table).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from factory.events.catalog import EventCatalog
from factory.events.reader import read_typed
from factory.index.hypotheses import LEVEL_READER_KEY
from factory.index.projection import Projection
from factory.model.levels import AutonomyLevel
from factory.model.project import ProjectCreated


def level_reader(events_dir: Path, catalog: EventCatalog) -> Callable[[], AutonomyLevel]:
    """A reader of the level of the first `project.created` in `events_dir`, cached once found."""
    found: list[AutonomyLevel] = []

    def read() -> AutonomyLevel:
        if found:
            return found[0]
        for event in read_typed(events_dir, catalog, ("project.created",)):
            found.append(ProjectCreated.model_validate(event.payload).autonomy_level)
            return found[0]
        return AutonomyLevel.ATTENDED

    return read


def attach_level_reader(projection: Projection, events_dir: Path, catalog: EventCatalog) -> None:
    """Let the folds of `projection` see the project's autonomy level."""
    projection.metadata.tables["project"].info[LEVEL_READER_KEY] = level_reader(events_dir, catalog)
