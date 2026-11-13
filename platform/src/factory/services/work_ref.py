"""The shared work-id resolver at every input that names a work (IDEA-66).

Invariants:
- An id stored as given is itself. Otherwise an id whose NFC form equals that of exactly one
  stored id names that id, and the stored spelling is returned: events always carry the stored
  spelling, and no stored id is ever rewritten.
- An id whose NFC form matches several stored ids is refused (`FactoryValidationError` on the
  caller's field): matching never merges two works.
- An id that matches nothing is returned unchanged, so the caller refuses it as before.
- The matching rule is `model.work_ids.nfc_matches` (pure); this module adds the lookup in the
  index and the refusal. It writes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.work_ids import nfc_matches
from factory.services.context import Project


def stored_spelling(work_id: str, stored: Iterable[str], *, field: str = "work_id") -> str:
    """`work_id` spelled as `stored` holds it (see the module invariants)."""
    matches = nfc_matches(work_id, stored)
    if len(matches) > 1:
        raise FactoryValidationError(
            [ValidationIssue(field, f"matches several works by NFC form: {', '.join(matches)}")]
        )
    return matches[0] if matches else work_id


def resolve_work_id(project: Project, work_id: str, *, field: str = "work_id") -> str:
    """`work_id` spelled as the project's index stores it (every work row, merged or not).

    The caller holds a synced index. An exact id costs one lookup; only a miss scans the ids.
    """
    with project.index.connect() as conn:
        exact = conn.execute(
            text("SELECT 1 FROM works WHERE work_id = :w"), {"w": work_id}
        ).first()
        if exact is not None:
            return work_id
        ids = [str(row[0]) for row in conn.execute(text("SELECT work_id FROM works"))]
    return stored_spelling(work_id, ids, field=field)


def resolve_work_ids(
    project: Project, work_ids: Iterable[str], *, field: str = "work_ids"
) -> list[str]:
    """`resolve_work_id` of each id, in order."""
    return [resolve_work_id(project, w, field=field) for w in work_ids]
