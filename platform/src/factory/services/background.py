"""Works kept as background: a flag derived from an exclusion, never a verdict (IDEA-47).

Pure seam. The caller passes the criterion ids the protocol declares as background (the
declaration itself needs a protocol model change, see the IDEA-47 entry in docs/backlog.md) and
the criterion each excluded work was excluded under (`agreement.exclusion_criteria`). With no
declared id nothing is background, and no count here changes `included` or `excluded`."""

from collections.abc import Collection, Mapping


def background_works(
    criteria: Mapping[str, str | None], criterion_ids: Collection[str]
) -> dict[str, str]:
    """Work id to criterion id, for the excluded works whose criterion is declared background."""
    declared = set(criterion_ids)
    return {w: c for w, c in sorted(criteria.items()) if c is not None and c in declared}


def background_counts(
    excluded: Mapping[str, int], criterion_ids: Collection[str]
) -> dict[str, int]:
    """The part of a PRISMA `excluded` mapping (criterion to count) that is background: a subset,
    so `sum(excluded.values())` is untouched."""
    declared = set(criterion_ids)
    return {c: n for c, n in sorted(excluded.items()) if c in declared}
