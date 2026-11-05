"""The marker rule and the item evidence rule of a contribution item (slice 3b, G2-B rulings 1-2).

Pure. `marker_check` compares the in-text marker tokens G1 found at an anchor with the quote an
item gives: the entry the agent names is `matched` when a marker of the quote maps to it,
`mismatch` when the quote's markers map only to other entries, `absent` when none of the anchor's
markers occurs in the quote. Only contexts whose state is `matched` map; ambiguous and unmatched
markers do not, so they can never confirm an entry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from factory.extraction.numbers import normalise_text
from factory.lineage.refs import ContextView
from factory.model.extraction import MarkerCheck, StoredField
from factory.packs.contribution import CONTRIBUTION_V1


def item_evidence(fields: Mapping[str, StoredField]) -> tuple[str, str] | None:
    """The anchor and quote of the first of the pack's `row_anchor_fields` that is present with
    both; None when no field has them (a `not-stated` item)."""
    for name in CONTRIBUTION_V1.row_anchor_fields:
        stored = fields.get(name)
        if stored is not None and stored.anchor is not None and stored.quote is not None:
            return stored.anchor, stored.quote
    return None


def marker_check(
    quote: str, anchor: str, ordinal: int, contexts: Sequence[ContextView]
) -> MarkerCheck:
    """Whether `quote`, taken from `anchor`, carries a marker that maps to entry `ordinal`.
    Tokens are compared after `normalise_text`; only matched contexts at `anchor` count."""
    haystack = normalise_text(quote)
    found = [
        c.entry
        for c in contexts
        if c.citing_anchor == anchor
        and c.state == "matched"
        and c.entry is not None
        and normalise_text(c.marker) in haystack
    ]
    if not found:
        return "absent"
    return "matched" if ordinal in found else "mismatch"
