"""Pure value types for the reference extraction views the lineage code reads (slice 3b, G2-B).

Invariants: frozen and carry bibliographic metadata and ordinals only, never the text of an entry
(G1 ruling 14: the index holds no entry text). `ReferenceView.entries` is ordered by ordinal.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory.model.references import Confidence, LinkState, MarkerState


@dataclass(frozen=True)
class EntryView:
    """One reference entry with its link as the projection folds it (decisions included)."""

    ordinal: int
    anchor: str
    label: str | None
    title: str | None
    first_author: str | None
    year: int | None
    doi: str | None
    arxiv: str | None
    link_state: LinkState
    link_work: str | None
    confidence: Confidence | None
    base_work: str | None = None
    """The work of the matcher's own resolution, kept when a decision rejected it."""
    candidate_works: tuple[str, ...] = ()
    """The works of an ambiguous link's candidates."""


@dataclass(frozen=True)
class ContextView:
    """One in-text marker occurrence: where it stands, its token, and the entry it maps to."""

    citing_anchor: str
    entry: int | None
    marker: str
    state: MarkerState


@dataclass(frozen=True)
class ReferenceView:
    """A reference extraction of one work: its entries and marker occurrences."""

    extraction_id: str
    work_id: str
    conversion_id: str
    entries: tuple[EntryView, ...]
    contexts: tuple[ContextView, ...]

    def entry(self, ordinal: int) -> EntryView | None:
        """The entry with this ordinal, or None."""
        for entry in self.entries:
            if entry.ordinal == ordinal:
                return entry
        return None
