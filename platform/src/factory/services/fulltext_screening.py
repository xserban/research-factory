"""Which works the full-text stage screens: promoted works with a converted live document.

A work is *eligible* when its title/abstract final outcome is INCLUDED and it has a default
conversion (`default_conversion`: the first live document in route order, at its latest conversion
by event order). A promoted work with no conversion is *not retrieved* for screening; it is never
queued and is counted as such (plan 2C ruling 3).

Invariants:
- Read-only: nothing is written; the index is synced before it is read.
- `eligible` is sorted by work id and `not_retrieved` is sorted; together they are exactly the
  promoted works.
- The conversion named for a work is the one current at call time. A batch pins it when the task
  is created (`screening._enqueue`); a later conversion never changes a queued task.
"""

from factory.model.base import StrictModel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.call_memo import memoised
from factory.services.context import Project
from factory.services.document_read import default_conversion


class EligibleWork(StrictModel):
    """A work the full-text stage screens, with the document and conversion it is read from."""

    work_id: str
    document_id: str
    conversion_id: str


class FulltextQueue(StrictModel):
    """The promoted works split by whether a converted document exists for them."""

    eligible: list[EligibleWork]
    not_retrieved: list[str]


@memoised
def fulltext_queue(project: Project) -> FulltextQueue:
    """Every promoted work as eligible (converted) or not retrieved (no conversion)."""
    project.index.sync()
    promoted = sorted(w for w, o in final_outcomes(project).items() if o is Outcome.INCLUDED)
    eligible: list[EligibleWork] = []
    missing: list[str] = []
    for work_id in promoted:
        chosen = default_conversion(project, work_id)
        if chosen is None:
            missing.append(work_id)
        else:
            eligible.append(
                EligibleWork(
                    work_id=work_id,
                    document_id=chosen.document_id,
                    conversion_id=chosen.conversion_id,
                )
            )
    return FulltextQueue(eligible=eligible, not_retrieved=missing)
