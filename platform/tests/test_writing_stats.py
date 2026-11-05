"""The closed stat registry (slice 7b, plan W-A, task 2; ruling 3)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.model.drafts import SentenceClass, parse_support
from factory.services.context import Project
from factory.services.horizon import timeline_view
from factory.services.lineage import no_stated_base
from factory.services.prisma import prisma_flow
from factory.services.references import included_works
from factory.services.supports import resolve_supports
from factory.writing.stats import PRISMA_FIELDS, STAT_KINDS, STATS_VERSION, compute_stat
from tests.contribution_helpers import ctr_a, ctr_b, ext_a, screened  # noqa: F401
from tests.views_b_helpers import ext_b  # noqa: F401
from tests.writing_helpers import WWorld, ww  # noqa: F401


def gid_of(project: Project, ww: WWorld, work: int) -> str:
    got = resolve_supports(project, [parse_support(ww.cell(work))], cls=SentenceClass.CLAIM)[0]
    return got.group_ids[0]


def test_registry_is_closed_and_versioned() -> None:
    assert STATS_VERSION == 1
    assert STAT_KINDS == (
        "group-independent",
        "group-rows",
        "group-works",
        "idea-members",
        "ideas-confirmed",
        "included-works",
        "not-stated-count",
        "prisma",
        "records",
    )


def test_group_counts_equal_hand_counts(project: Project, ww: WWorld) -> None:
    low, high = gid_of(project, ww, 0), gid_of(project, ww, 4)
    assert low != high
    assert compute_stat(project, "group-works", [low]) == 4
    assert compute_stat(project, "group-rows", [low]) == 4
    assert compute_stat(project, "group-independent", [low]) == 3  # one copied row
    assert compute_stat(project, "group-works", [high]) == 2
    assert compute_stat(project, "group-independent", [high]) == 2


def test_idea_and_corpus_counts(project: Project, ww: WWorld) -> None:
    assert compute_stat(project, "idea-members", [ww.idea]) == 2
    assert compute_stat(project, "ideas-confirmed", []) == 1
    assert compute_stat(project, "included-works", []) == len(included_works(project)) > 0


def test_prisma_fields(project: Project, ww: WWorld) -> None:
    flow = prisma_flow(project)
    assert compute_stat(project, "prisma", ["screened"]) == flow.screened
    assert compute_stat(project, "prisma", ["included"]) == flow.included
    assert flow.included_in_review is not None
    assert compute_stat(project, "prisma", ["included_in_review"]) == flow.included_in_review
    assert compute_stat(project, "prisma", ["excluded_total"]) == flow.excluded_total
    assert set(PRISMA_FIELDS) >= {"screened", "included", "pending"}


def test_records_per_year(project: Project, ww: WWorld) -> None:
    low = gid_of(project, ww, 0)
    view = timeline_view(project, low)
    expected = sum(1 for u in view.units.values() for r in u.records if r.year == 2020)
    assert expected == 2  # the two independent rows of the best value in the first year
    assert compute_stat(project, "records", [low, "2020"]) == expected
    assert compute_stat(project, "records", [low, "1999"]) == 0


def test_not_stated_count(project: Project, ww: WWorld) -> None:
    assert compute_stat(project, "not-stated-count", []) == len(no_stated_base(project).not_stated)


@pytest.mark.parametrize(
    ("kind", "args"),
    [
        ("no-such-kind", []),
        ("group-works", []),
        ("group-works", ["grp_ffffffffffff"]),
        ("group-rows", ["a", "b"]),
        ("idea-members", ["ida_01JZ9Q3K5M7N8P0R2S4T6V8W99"]),
        ("ideas-confirmed", ["x"]),
        ("prisma", ["no_such_field"]),
        ("records", ["grp_ffffffffffff", "2020"]),
    ],
)
def test_unknown_stat_is_refused(project: Project, ww: WWorld, kind: str, args: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        compute_stat(project, kind, args)
    assert caught.value.issues[0].field == "supports"
    assert "unknown" in caught.value.issues[0].reason


def test_records_need_a_year(project: Project, ww: WWorld) -> None:
    low = gid_of(project, ww, 0)
    with pytest.raises(FactoryValidationError):
        compute_stat(project, "records", [low, "next-year"])
