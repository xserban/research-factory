"""The default focus is the corpus minus absorbed works, as PRISMA counts it (plan V-A)."""

# ruff: noqa: F811

from __future__ import annotations

from factory.services.lineage import confirmed_ideas_of
from factory.services.onion import onion_view
from tests.region_helpers import RWorld, merge_works, region_project, screened  # noqa: F401


def _ring0(w: RWorld) -> list[str]:
    return [n.work_id for n in onion_view(w.project).rings[0].nodes]


def test_merging_two_included_works_leaves_one_in_ring_zero(region_project: RWorld) -> None:
    w = region_project
    before = _ring0(w)
    assert sorted(before) == sorted(w.included)
    keep, absorbed = w.included[0], w.included[1]
    merge_works(w.project, keep, absorbed)
    after = _ring0(w)
    assert len(after) == len(before) - 1
    assert absorbed not in after and keep in after  # left out, not mapped to the primary


def test_included_work_absorbed_into_a_non_included_one_leaves_ring_zero(
    region_project: RWorld,
) -> None:
    w = region_project
    absorbed = w.included[0]
    merge_works(w.project, w.extra, absorbed)  # the primary is a corpus work that is not included
    after = _ring0(w)
    assert absorbed not in after and w.extra not in after
    assert len(after) == len(w.included) - 1


def test_ideas_of_an_absorbed_listed_id_is_empty(region_project: RWorld) -> None:
    w = region_project
    merge_works(w.project, w.included[1], w.included[0])
    with w.project.index.connect() as conn:
        found = confirmed_ideas_of(w.project, conn, [w.included[0]])
    assert found == {}
