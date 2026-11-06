"""What waits at intake: imports to confirm and admit, files to attach, documents, inbox links.

Counts only, read from the index; nothing is written and the library is not read beyond a file's
existence. With `agent`, the import counts cover the development part (or every record of an import
not split), so no count moves with the held-out part (decision 43): an import blocked only by a
held-out record reads as ready, and the admission's own refusal tells the researcher. An import is
ready while an admission would plan a record, so one described after a first admission counts.
"""

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import text

from factory.imports.model import ImportRole, ParseOutcome
from factory.model.references import LinkState
from factory.services.context import Project
from factory.services.document_convert import unconverted_documents
from factory.services.import_admit import planned_ordinals
from factory.services.import_attach import attachments_waiting
from factory.services.imports import development_ordinals, list_imports, pending_descriptions

_OPEN_STATES = (LinkState.UNCONFIRMED.value, LinkState.AMBIGUOUS.value)


@dataclass(frozen=True)
class IntakeCounts:
    """Records to confirm; imports ready to admit; files to attach; documents to convert; open
    inbox links."""

    confirmation: int
    admission: int
    attachments: int
    unconverted: int
    inbox: int


def intake_counts(project: Project, *, agent: bool) -> IntakeCounts:
    """The intake counts of `project`, as the researcher reads them or, with `agent`, an agent."""
    project.index.sync()
    listings = list_imports(project)
    shown: dict[str, set[int] | None] = {
        listing.row.import_id: (
            set(development_ordinals(project, listing.row.import_id)) if agent else None
        )
        for listing in listings
    }
    states = _link_states(project)
    confirmation = 0
    admission = 0
    for listing in listings:
        import_id = listing.row.import_id
        ordinals = shown[import_id]
        rows = [
            state
            for ordinal, state in states.get(import_id, [])
            if ordinals is None or ordinal in ordinals
        ]
        waiting = sum(1 for state in rows if state in _OPEN_STATES)
        confirmation += waiting
        if (
            listing.row.role is ImportRole.CORPUS
            and rows
            and not waiting
            and all(state is not None for state in rows)
            and not _counted(pending_descriptions(project, import_id), ordinals)
            and _counted(planned_ordinals(project, import_id), ordinals)
        ):
            admission += 1
    return IntakeCounts(
        confirmation=confirmation,
        admission=admission,
        attachments=attachments_waiting(project, shown),
        unconverted=unconverted_documents(project),
        inbox=_open_inbox(project),
    )


def _counted(found: Collection[int], ordinals: set[int] | None) -> bool:
    """Whether `found` holds a record the reader may count."""
    return bool(found) if ordinals is None else not ordinals.isdisjoint(found)


def _link_states(project: Project) -> dict[str, list[tuple[int, str | None]]]:
    """Each import's well-formed records as (ordinal, link state)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT import_id, ordinal, link_state FROM import_records "
                "WHERE outcome != :malformed"
            ),
            {"malformed": ParseOutcome.MALFORMED.value},
        ).all()
    found: dict[str, list[tuple[int, str | None]]] = {}
    for import_id, ordinal, state in rows:
        found.setdefault(str(import_id), []).append(
            (int(ordinal), None if state is None else str(state))
        )
    return found


def _open_inbox(project: Project) -> int:
    with project.index.connect() as conn:
        found = conn.execute(text("SELECT COUNT(*) FROM inbox_items WHERE status = 'open'"))
        return int(found.scalar_one())
