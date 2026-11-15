"""MeSH descriptor suggestions from a probe's PubMed title sample (IDEA-77 b).

A pure count over the sampled records' MeSH headings: a descriptor is suggested when at least one
sampled record carries it, the query text does not already contain it, and it is not a MeSH check
tag (population or design labels such as `Humans` or `Female`, which describe nearly every
record). The order is by number of records descending, then by descriptor, so the same sample
always gives the same list. No model, no network: this only reads what the sample already
returned. The list is a suggestion for the researcher to select from; it is never applied to a
query and nothing here writes an event.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from factory.model.probe import MeshSuggestion

DEFAULT_LIMIT = 20

CHECK_TAGS: frozenset[str] = frozenset(
    name.casefold()
    for name in (
        "Humans",
        "Animals",
        "Male",
        "Female",
        "Adult",
        "Aged",
        "Aged, 80 and over",
        "Middle Aged",
        "Young Adult",
        "Adolescent",
        "Child",
        "Child, Preschool",
        "Infant",
        "Infant, Newborn",
        "Pregnancy",
        "Mice",
        "Rats",
    )
)
"""MeSH check tags, compared case-insensitively. Fixed list, no inference."""


def mesh_suggestions(
    sampled: Iterable[Sequence[str]], query_text: str, *, limit: int = DEFAULT_LIMIT
) -> tuple[MeshSuggestion, ...]:
    """The MeSH descriptors of `sampled` (one sequence of descriptors per record), most common first.

    `sampled` counts only records that carry at least one heading in `MeshSuggestion.sampled`. A
    descriptor repeated inside one record counts once. Descriptors whose text occurs in
    `query_text` (case-insensitive) and check tags are left out.
    """
    headed = [tuple(dict.fromkeys(record)) for record in sampled if record]
    counts: Counter[str] = Counter(name for record in headed for name in record)
    query = query_text.casefold()
    rows = [
        (name, n)
        for name, n in counts.items()
        if name.casefold() not in CHECK_TAGS and name.casefold() not in query
    ]
    rows.sort(key=lambda row: (-row[1], row[0].casefold(), row[0]))
    return tuple(
        MeshSuggestion(descriptor=name, records=n, sampled=len(headed)) for name, n in rows[:limit]
    )
