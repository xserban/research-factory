"""A small evidence world for the V-B view tests (real events; dates patched where a test says so).

`declared` takes the screened full-text world (12 included works, all published 2020-01-01) and
declares an extraction schema that adds `params` and `higher_is_better`. `acc` builds a row;
`run_both` records the same rows in both passes, so every row is `agreed`.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput, ReportedIn
from factory.model.screening import PassLabel
from factory.services.context import Project
from tests.evidence_helpers import run_pass
from tests.extraction_helpers import FIELDS, _declare, _r, screened  # noqa: F401

VB_FIELDS = (*FIELDS, "params", "higher_is_better")
RowsFor = Callable[[str], list[ExtractedRowInput]]


def acc(
    value: str = "1",
    *,
    task: str = "classification",
    params: str | None = None,
    reported_in: ReportedIn = ReportedIn.OWN,
    metric: str = "Low",
    up: bool | None = True,
) -> ExtractedRowInput:
    """A row of the fixture document: its table holds only the numbers 1 (cell `t1.r3.c2`) and 2
    (`t1.r3.c3`) and the metric names `Low` and `High`, so `value` and `params` are one of those."""
    cell = {"1": "t1.r3.c2", "2": "t1.r3.c3"}[value]
    extra: dict[str, FieldInput] = {
        "metric": FieldInput(
            value=metric, anchor="t1.r2.c2" if metric == "Low" else "t1.r2.c3", quote=metric
        )
    }
    if params is not None:
        pcell = {"1": "t1.r3.c2", "2": "t1.r3.c3"}[params]
        extra["params"] = FieldInput(value=params, unit="M", anchor="t1", cell=pcell, quote=params)
    if up is not None:
        extra["higher_is_better"] = FieldInput(value=up)
    return _r(value, cell, unit="%", task=task, reported_in=reported_in, **extra)


def run_both(project: Project, ext_a: Actor, ext_b: Actor, rows_for: RowsFor) -> None:
    run_pass(project, ext_a, PassLabel.A, rows_for)
    run_pass(project, ext_b, PassLabel.B, rows_for)


def set_year(project: Project, work_id: str, published: str | None) -> None:
    """Change a work's published date in the projection (the screened world dates all of them
    2020-01-01). The fold of the view reads this column only."""
    with project.index.connect() as conn:
        if published is None:
            sql = (
                "UPDATE works SET data = json_remove(data, '$.dates.published') WHERE work_id = :w"
            )
            conn.execute(text(sql), {"w": work_id})
        else:
            sql = (
                "UPDATE works SET data = json_set(data, '$.dates.published', :d) WHERE work_id = :w"
            )
            conn.execute(text(sql), {"w": work_id, "d": published})
        conn.commit()


@pytest.fixture
def declared(project: Project, agent: Actor, screened: list[str]) -> list[str]:  # noqa: F811
    _declare(project, agent, fields=VB_FIELDS)
    return screened
