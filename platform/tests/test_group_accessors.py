"""Per-group accessors equal the evidence grouping (plan V-B, task 1; review focus 1 and 4)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import ReportedIn
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.evidence_groups import (
    final_rows_for,
    group_index,
    rows_of_group,
)
from factory.services.evidence_report import evidence_report, group_id
from factory.services.extraction_agreement import (
    final_rows,
    grouped_rows,
    independence_counts,
)
from tests.evidence_helpers import run_pass
from tests.extraction_helpers import ext_a, ext_b, screened  # noqa: F401
from tests.views_b_helpers import acc, declared, run_both  # noqa: F401


def _world(project: Project, ext_a: Actor, ext_b: Actor, works: list[str]) -> None:
    def rows_for(work: str) -> list:  # type: ignore[type-arg]
        i = works.index(work)
        if i % 3 == 0:
            return [acc("2", task="detection", metric="High", up=None)]
        if i % 3 == 1:
            return [acc("2", reported_in=ReportedIn.CITED)]
        return [acc("1")]

    run_both(project, ext_a, ext_b, rows_for)


def test_group_accessors_equal_grouped_rows(
    project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]
) -> None:  # Review Focus 1
    _world(project, ext_a, ext_b, declared)
    g = grouped_rows(project)
    assert len(g.groups) == 2
    index = group_index(project)
    assert {s.group_id for s in index} == {group_id(k) for k in g.groups}
    for key, rows in g.groups.items():
        assert rows_of_group(project, group_id(key)) == rows
    for s in index:
        rows = rows_of_group(project, s.group_id)
        counts = independence_counts(rows)
        assert (s.rows, s.independent, s.copied) == (len(rows), counts.independent, counts.copied)
        assert s.works == len({r.work_id for r in rows})
    assert [s.key for s in index] == sorted(s.key for s in index)


def test_final_rows_for_equals_filter(
    project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]
) -> None:
    _world(project, ext_a, ext_b, declared)
    chosen = declared[1:7:2]
    expected = [r for r in final_rows(project) if r.work_id in set(chosen)]
    assert expected
    assert final_rows_for(project, chosen) == expected
    assert final_rows_for(project, []) == []


def test_unknown_group_rejected(
    project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]
) -> None:
    _world(project, ext_a, ext_b, declared)
    with pytest.raises(FactoryValidationError) as err:
        rows_of_group(project, "grp_000000000000")
    assert err.value.issues[0].field == "group_id"


def test_fresh_project_has_no_groups(project: Project) -> None:
    assert group_index(project) == []
    with pytest.raises(FactoryValidationError):
        rows_of_group(project, "grp_000000000000")


def test_accessors_survive_a_rebuild(
    project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]
) -> None:
    _world(project, ext_a, ext_b, declared)
    before = group_index(project)
    project.index.rebuild()
    assert group_index(project) == before


def test_evidence_report_unchanged(
    project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]
) -> None:  # Review Focus 4
    """The report reads `grouped_rows`; the accessors add no state to it (byte-identical dump
    before and after calling them; the pinned dump for the pilot rows is in test_evidence_*)."""
    _world(project, ext_a, ext_b, declared)
    before = evidence_report(project).model_dump_json()
    for s in group_index(project):
        rows_of_group(project, s.group_id)
    assert evidence_report(project).model_dump_json() == before
    assert PassLabel.A and run_pass  # imports used by sibling worlds


def test_phantom_key_from_cells_of_different_passes_is_unknown(
    project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]
) -> None:
    """Pass A reads task `classification`, pass B `detection`: the scan sees a `detection` key,
    but no final row has it (the disagreement is open), so no such group exists."""
    first = declared[0]
    run_pass(project, ext_a, PassLabel.A, lambda w: [acc("1")] if w == first else [])
    run_pass(
        project, ext_b, PassLabel.B, lambda w: [acc("1", task="detection")] if w == first else []
    )
    assert group_index(project) == []
    phantom = group_id(
        (
            ("task", "detection"),
            ("dataset", "lorem ipsum"),
            ("split", "val"),
            ("metric", "low"),
        )
    )
    with pytest.raises(FactoryValidationError) as err:
        rows_of_group(project, phantom)
    assert err.value.issues[0].field == "group_id"
