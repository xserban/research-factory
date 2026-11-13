"""The arXiv categories a project's feed should follow, proposed from its core layer (plan
2026-11-13-hub-feed, part 5). Computed from the works, never typed; a proposal changes nothing:
only the researcher's `feed configure` (a human act) writes `feed.configured`.

Rule (researcher, 2026-11-13): take the primary category of each core-layer work that has an
arXiv identifier, order the categories by count, and take them from the top until they cover
`coverage` of those works, at least `minimum` and at most `maximum` categories.

Invariants:
- Only works with an arXiv identifier count: other sources put free-text topics in `subjects`.
- The primary category is the first subject that is a valid category id.
- Ties in count are broken by category name, so equal inputs give an equal proposal.
- The proposal states its basis (core works, those with an arXiv category, the achieved
  coverage), so a thin basis is visible.
- Read-only.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

from factory.model.base import StrictModel
from factory.model.feed import FEED_CATEGORY_RE
from factory.services.context import Project
from factory.services.search import get_work
from factory.services.work_layers import layers_of

COVERAGE = 0.9
MINIMUM = 2
MAXIMUM = 4
_CATEGORY = re.compile(FEED_CATEGORY_RE)


class CategoryShare(StrictModel):
    category: str
    works: int
    share: float
    """The share of the core works that have an arXiv category."""


class CategoryProposal(StrictModel):
    categories: tuple[str, ...]
    shares: tuple[CategoryShare, ...]
    """Every category seen, most common first (the proposal is a prefix of it)."""
    core_works: int
    with_category: int
    covered: float
    """The share of the works with a category that the proposed categories cover."""
    coverage: float
    minimum: int
    maximum: int


def primary_category(subjects: Iterable[str]) -> str | None:
    """The first subject that is a valid category id, if any."""
    return next((s for s in subjects if _CATEGORY.fullmatch(s)), None)


def choose_categories(
    counts: Mapping[str, int],
    *,
    coverage: float = COVERAGE,
    minimum: int = MINIMUM,
    maximum: int = MAXIMUM,
) -> tuple[str, ...]:
    """From the most common category down, until `coverage` of all works is covered, never fewer
    than `minimum` (while there are that many) nor more than `maximum`."""
    total = sum(counts.values())
    ordered = sorted(counts, key=lambda c: (-counts[c], c))
    chosen: list[str] = []
    covered = 0
    for category in ordered:
        if len(chosen) >= maximum:
            break
        if len(chosen) >= minimum and covered >= coverage * total:
            break
        chosen.append(category)
        covered += counts[category]
    return tuple(chosen)


def propose_categories(
    project: Project,
    *,
    coverage: float = COVERAGE,
    minimum: int = MINIMUM,
    maximum: int = MAXIMUM,
) -> CategoryProposal:
    """The proposal for `project`, from the works whose current layer is `core`."""
    core = sorted(work for work, found in layers_of(project).items() if found.layer == "core")
    counts: Counter[str] = Counter()
    for work_id in core:
        work = get_work(project, work_id)
        if work is None or not work.identifiers.arxiv:
            continue
        category = primary_category(work.subjects)
        if category is not None:
            counts[category] += 1
    total = sum(counts.values())
    chosen = choose_categories(counts, coverage=coverage, minimum=minimum, maximum=maximum)
    ordered = sorted(counts, key=lambda c: (-counts[c], c))
    return CategoryProposal(
        categories=chosen,
        shares=tuple(
            CategoryShare(category=c, works=counts[c], share=counts[c] / total) for c in ordered
        ),
        core_works=len(core),
        with_category=total,
        covered=(sum(counts[c] for c in chosen) / total) if total else 0.0,
        coverage=coverage,
        minimum=minimum,
        maximum=maximum,
    )
