"""Scale of the coverage map's own work (plan V-B, task 2).

The evidence fold (`grouped_rows`, plan D) is linear in the rows and is not under test here: it is
replaced by 2*10^5 synthetic final rows over 2*10^4 works, 10^3 groups and 10^3 methods. What is
timed is everything the view adds: the corpus check in SQL over 2*10^4 works with provenance, the
notice states, the tallies and the cut. The corpus has provenance rows and the view's lists are
non-empty and cut at their bounds.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import text

from factory.model.extraction import ReportedIn
from factory.services import view_coverage
from factory.services.extraction_agreement import FinalField, FinalRow, Grouped
from factory.services.view_coverage import coverage_view
from tests.helpers import Project

pytestmark = pytest.mark.slow

WORKS = 20_000
ROWS = 200_000
GROUPS = 1_000
METHODS = 1_000
LIMIT_SECONDS = 5.0


def _w(i: int) -> str:
    return f"rf:s{i}-{i:08x}"


def _field(value: str) -> FinalField:
    return FinalField(
        value=value,
        unit=None,
        canonical=None,
        anchor=None,
        cell=None,
        quote=None,
        reported_in=ReportedIn.OWN,
        copy_marker=False,
        reproduced=False,
        cited_work=None,
        extraction_id="ext_1",
    )


def test_coverage_scale(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    project.index.sync()
    nodes = [{"n": _w(i)} for i in range(WORKS)]
    with project.index.connect() as conn:
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:n, '{}', 'e')"), nodes
        )
        conn.execute(
            text(
                "INSERT INTO provenance (work_id, run_id, query_id, source, method, raw_blob, at) "
                "VALUES (:n, 'run_x', 'qry_x', 's', 'm', 'b', '2026-01-01T00:00:00+00:00')"
            ),
            nodes,
        )
        conn.commit()
    groups: dict[tuple[tuple[str, str], ...], list[FinalRow]] = {}
    for i in range(ROWS):
        key = (("task", f"t{i % GROUPS}"),)
        groups.setdefault(key, []).append(
            FinalRow(
                work_id=_w(i % WORKS),
                document_id="doc_1",
                conversion_id="cnv_1",
                row_key=f"rk_{i:012x}",
                status="agreed",
                fields={"method_name": _field(f"m{i % METHODS}"), "value": _field("1")},
                independent=i % 5 != 0,
            )
        )
    monkeypatch.setattr(
        view_coverage,
        "grouped_rows",
        lambda _p: Grouped(groups=groups, ungrouped=[], unresolved=[]),
    )
    monkeypatch.setattr(view_coverage, "VIEW_MAX_GROUPS", 200)
    started = time.perf_counter()
    view = coverage_view(project)
    elapsed = time.perf_counter() - started
    assert elapsed < LIMIT_SECONDS, elapsed
    assert view.total_groups == GROUPS and len(view.groups) == 200 and view.meta.truncated
    assert view.total_methods == METHODS and len(view.methods) == 500
    total = sum(c.independent + c.copied for by in view.cells.values() for c in by.values())
    assert total > 0
