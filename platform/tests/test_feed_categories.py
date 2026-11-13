"""The category proposal of the hub feed (plan 2026-11-13-hub-feed, part 5)."""

from __future__ import annotations

import pytest

from factory.model.work import Identifiers
from factory.services import feed_categories as fc
from factory.services.context import Project
from factory.services.work_layers import WorkLayer


def _counts(**by: int) -> dict[str, int]:
    return {k.replace("_", "."): v for k, v in by.items()}


def test_the_pilot_case_takes_three_categories_covering_ninety_five_percent() -> None:
    counts = {"cs.AI": 32, "cs.CL": 12, "cs.LG": 8, "cs.CY": 1, "cs.CV": 1, "cs.SE": 1}
    assert fc.choose_categories(counts) == ("cs.AI", "cs.CL", "cs.LG")


def test_an_even_spread_over_four_categories_takes_four_and_never_more_than_the_cap() -> None:
    even = {"a.A": 25, "b.B": 25, "c.C": 25, "d.D": 25}
    assert fc.choose_categories(even) == ("a.A", "b.B", "c.C", "d.D")
    wide = {f"x.{c}": 10 for c in "ABCDEF"}
    assert len(fc.choose_categories(wide)) == 4


def test_a_dominant_category_still_gets_the_minimum_of_two() -> None:
    assert fc.choose_categories({"cs.AI": 95, "cs.CL": 3, "cs.LG": 2}) == ("cs.AI", "cs.CL")


def test_fewer_categories_than_the_minimum_returns_what_there_is() -> None:
    assert fc.choose_categories({"cs.AI": 4}) == ("cs.AI",)
    assert fc.choose_categories({}) == ()


def test_ties_are_broken_by_name_so_equal_inputs_give_equal_proposals() -> None:
    tied = {"cs.LG": 5, "cs.AI": 5, "cs.CL": 5, "cs.MA": 5}
    assert fc.choose_categories(tied, maximum=2) == ("cs.AI", "cs.CL")
    assert fc.choose_categories(dict(reversed(tied.items())), maximum=2) == ("cs.AI", "cs.CL")


def test_the_rule_parameters_are_honoured() -> None:
    counts = {"cs.AI": 50, "cs.CL": 30, "cs.LG": 20}
    assert fc.choose_categories(counts, coverage=0.5, minimum=1) == ("cs.AI",)
    assert fc.choose_categories(counts, coverage=1.0, maximum=3) == ("cs.AI", "cs.CL", "cs.LG")


@pytest.mark.parametrize(
    ("subjects", "expected"),
    [
        (["cs.AI", "cs.LG"], "cs.AI"),
        (["Machine learning", "cs.CL"], "cs.CL"),
        (["quant-ph"], "quant-ph"),
        (["Artificial Intelligence"], None),
        ([], None),
    ],
)
def test_the_primary_category_is_the_first_valid_category_id(
    subjects: list[str], expected: str | None
) -> None:
    assert fc.primary_category(subjects) == expected


def test_a_proposal_counts_only_core_layer_works_with_an_arxiv_identifier(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.model.work import Provenance, Work
    from tests.helpers import T0

    def work(wid: str, subjects: list[str], arxiv: str | None) -> Work:
        return Work.build(
            title=f"T {wid}",
            identifiers=Identifiers(arxiv=arxiv),
            subjects=subjects,
            provenance=[
                Provenance(
                    source="arxiv",
                    run_id=project.ids.new("run"),
                    query_id=project.ids.new("qry"),
                    at=T0,
                    raw_blob="sha256:" + "0" * 64,
                )
            ],
        ).model_copy(update={"id": wid})

    works = {
        "rf:a": work("rf:a", ["cs.AI"], "http://arxiv.org/abs/2601.00001v1"),
        "rf:b": work("rf:b", ["cs.AI", "cs.LG"], "http://arxiv.org/abs/2601.00002v1"),
        "rf:c": work("rf:c", ["cs.CL"], "http://arxiv.org/abs/2601.00003v1"),
        "rf:d": work("rf:d", ["cs.CL"], None),  # not on arXiv: its subjects are not counted
        "rf:e": work("rf:e", ["cs.SE"], "http://arxiv.org/abs/2601.00005v1"),  # not core
    }
    layers = {
        w: WorkLayer(
            layer="applied" if w == "rf:e" else "core",
            source="moved",
            scheme_version=3,
            miner_layer=None,
        )
        for w in works
    }
    monkeypatch.setattr(fc, "layers_of", lambda _p: layers)
    monkeypatch.setattr(fc, "get_work", lambda _p, w: works[w])
    proposal = fc.propose_categories(project)
    assert proposal.core_works == 4 and proposal.with_category == 3
    assert proposal.categories == ("cs.AI", "cs.CL")
    assert [(s.category, s.works) for s in proposal.shares] == [("cs.AI", 2), ("cs.CL", 1)]
    assert proposal.covered == 1.0
    assert fc.propose_categories(project) == proposal  # deterministic


def test_a_project_without_core_works_proposes_nothing(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fc, "layers_of", lambda _p: {})
    proposal = fc.propose_categories(project)
    assert proposal.categories == () and proposal.with_category == 0 and proposal.covered == 0.0
