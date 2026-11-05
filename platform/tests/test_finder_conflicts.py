"""The numeric conflict finder (slice 6, plan H-B, task 3; acceptance 6).

The evidence report is the constructed plan-E one (`pilot_inputs`) with its rows replaced by the
rows below, all in one comparability group (imagenet-1k / top-1 / 224 / none)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.services import finders
from factory.services.context import Project
from factory.services.evidence_report import assemble_report
from factory.services.finders import ConflictPage, find_conflicts
from tests.evidence_helpers import ff, frow, pilot_inputs


def _rows() -> list[Any]:
    return [
        # M1: two works, different values, different regime (epochs; distillation on one side)
        frow("rf:w1", "rk_a001", "M1", "80.0", training_epochs=ff("100"), distillation=ff(True)),
        frow("rf:w2", "rk_a002", "M1", "70.0", training_epochs=ff("300")),
        # M2: two works, 0.66% apart: within the 1% tolerance
        frow("rf:w3", "rk_b001", "M2", "75.0"),
        frow("rf:w4", "rk_b002", "M2", "75.5"),
        # M3: the second row copies the first work's number: a copy never conflicts
        frow("rf:w1", "rk_c001", "M3", "60.0"),
        frow("rf:w5", "rk_c002", "M3", "90.0", cited=True),
        # M4: one work, two different values: not a pair of works
        frow("rf:w6", "rk_d001", "M4", "50.0"),
        frow("rf:w6", "rk_d002", "M4", "40.0"),
    ]


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], None]:
    def use(rows: list[Any]) -> None:
        monkeypatch.setattr(
            finders,
            "evidence_report",
            lambda project, **kw: assemble_report(pilot_inputs(rows)),
        )

    return use


def test_conflict_lists_both_rows_and_differing_regime(
    project: Project, patched: Callable[[list[Any]], None]
) -> None:  # acceptance 6
    patched(_rows())
    page = find_conflicts(project)
    [pair] = page.conflicts
    assert (pair.method, pair.variant) == ("m1", None)
    assert (pair.row_a, pair.row_b) == ("rk_a001", "rk_a002")
    assert (pair.work_a, pair.work_b) == ("rf:w1", "rf:w2")
    assert (pair.value_a, pair.value_b) == ("80", "70")
    assert pair.relative_difference == "0.1250"
    assert pair.differs_in == ["distillation", "training_epochs"]
    assert pair.trace_ids == ("rk_a001/value", "rk_a002/value")
    assert page.groups_scanned == 1 and page.next_after is None


def test_copied_rows_never_conflict(
    project: Project, patched: Callable[[list[Any]], None]
) -> None:  # Review Focus 2
    patched(_rows())
    assert all(p.method != "m3" for p in find_conflicts(project).conflicts)


def test_within_tolerance_not_conflict(
    project: Project, patched: Callable[[list[Any]], None]
) -> None:
    patched(_rows())
    assert all(p.method != "m2" for p in find_conflicts(project).conflicts)
    patched([frow("rf:w3", "rk_b001", "M2", "75.0"), frow("rf:w4", "rk_b002", "M2", "76.0")])
    [pair] = find_conflicts(project).conflicts  # 1.3% apart
    assert pair.relative_difference == "0.0132"


def test_plan_tolerance_overrides_the_default(
    project: Project, patched: Callable[[list[Any]], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    from decimal import Decimal

    patched(_rows())
    assert finders.conflict_tolerance(project) == Decimal("0.01")  # no plan stated
    monkeypatch.setattr(finders, "conflict_tolerance", lambda _p: Decimal("0.005"))
    assert any(p.method == "m2" for p in find_conflicts(project).conflicts)  # 0.66% apart
    monkeypatch.setattr(finders, "conflict_tolerance", lambda _p: Decimal("0.5"))
    assert find_conflicts(project).conflicts == []


def test_same_work_rows_not_paired(project: Project, patched: Callable[[list[Any]], None]) -> None:
    patched(_rows())
    assert all(p.method != "m4" for p in find_conflicts(project).conflicts)


def test_group_filter_and_paging(project: Project, patched: Callable[[list[Any]], None]) -> None:
    rows = [
        *_rows(),
        frow("rf:w1", "rk_e001", "M5", "10.0"),
        frow("rf:w2", "rk_e002", "M5", "20.0"),
        frow("rf:w3", "rk_e003", "M5", "30.0"),
    ]
    patched(rows)
    full = find_conflicts(project)
    assert [(p.method, p.row_a, p.row_b) for p in full.conflicts] == [
        ("m1", "rk_a001", "rk_a002"),
        ("m5", "rk_e001", "rk_e002"),
        ("m5", "rk_e001", "rk_e003"),
        ("m5", "rk_e002", "rk_e003"),
    ]
    seen: list[tuple[str, str]] = []
    after = None
    while True:
        page = find_conflicts(project, limit=3, after=after)
        seen += [(p.row_a, p.row_b) for p in page.conflicts]
        if page.next_after is None:
            break
        after = page.next_after
    assert seen == [(p.row_a, p.row_b) for p in full.conflicts]
    gid = full.conflicts[0].group_id
    assert find_conflicts(project, group_id=gid).conflicts == full.conflicts
    assert find_conflicts(project, group_id="grp_000000000000").conflicts == []
    with pytest.raises(FactoryValidationError):
        find_conflicts(project, limit=0)


def test_no_document_text_in_output(project: Project, patched: Callable[[list[Any]], None]) -> None:
    patched(_rows())
    dumped = json.dumps(find_conflicts(project).model_dump(mode="json"))
    assert "quote" not in dumped and "Title" not in dumped
    assert isinstance(ConflictPage.model_validate_json(dumped), ConflictPage)
