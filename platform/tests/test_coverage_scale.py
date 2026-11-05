"""Scale of the coverage map and the group accessors on real stored rows (plan V-B, C1c).

The real screened world and the real extraction passes give every included work two agreed rows
(pass A and B, through events). The stored rows of each work are then multiplied in the index
tables (new extraction ids and row keys, identical fields and the same task, document and
protocol), so everything downstream is the real path: the ledger, staleness, agreement, final rows,
grouping, the corpus check, the notice states and the view. What is timed is `coverage_view`,
`group_index` and `horizon_view` on that many rows; the figures are printed and the cost per row is
extrapolated to 2*10^5 rows (acceptance 17 asks for 5 s; the test bound is the measured order of
magnitude, not that figure).
"""

# ruff: noqa: F811

from __future__ import annotations

import time

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.evidence_groups import group_index
from factory.services.extraction_agreement import final_rows
from factory.services.horizon import horizon_view
from factory.services.view_coverage import coverage_view
from tests.contribution_helpers import ctr_a, ctr_b, ext_a  # noqa: F401
from tests.extraction_helpers import screened  # noqa: F401
from tests.views_b_helpers import acc, declared, ext_b, run_both  # noqa: F401

pytestmark = pytest.mark.slow

COPIES = 400  # per stored row: 12 works x 2 passes x 400 = 9,600 live rows
TARGET_ROWS = 200_000
LIMIT_SECONDS = 120.0


def _multiply(project: Project, copies: int) -> int:
    with project.index.connect() as conn:
        heads = conn.execute(text("SELECT * FROM extraction_rows")).mappings().all()
        fields = conn.execute(text("SELECT * FROM extraction_fields")).mappings().all()
        by_row: dict[str, list[dict[str, object]]] = {}
        for f in fields:
            by_row.setdefault(str(f["extraction_id"]), []).append(dict(f))
        new_heads: list[dict[str, object]] = []
        new_fields: list[dict[str, object]] = []
        for k in range(1, copies + 1):
            for h in heads:
                ident = f"{h['extraction_id']}_{k:05d}"
                new_heads.append(
                    {**h, "extraction_id": ident, "row_key": f"{h['row_key']}{k:05d}"[-24:]}
                )
                new_fields += [
                    {**f, "extraction_id": ident} for f in by_row[str(h["extraction_id"])]
                ]
        cols = list(heads[0].keys())
        conn.execute(
            text(
                f"INSERT INTO extraction_rows ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)})"
            ),
            new_heads,
        )
        fcols = list(fields[0].keys())
        conn.execute(
            text(
                f"INSERT INTO extraction_fields ({', '.join(fcols)}) "
                f"VALUES ({', '.join(':' + c for c in fcols)})"
            ),
            new_fields,
        )
        conn.commit()
        return len(heads) * (copies + 1)


def test_real_path_cost(project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]) -> None:
    run_both(project, ext_a, ext_b, lambda _w: [acc("2")])
    rows = _multiply(project, COPIES)
    started = time.perf_counter()
    groups = group_index(project)
    t_index = time.perf_counter() - started
    started = time.perf_counter()
    view = coverage_view(project)
    t_cov = time.perf_counter() - started
    started = time.perf_counter()
    horizon_view(project)
    t_hor = time.perf_counter() - started
    finals = len(final_rows(project))
    assert finals > 0 and groups and view.cells
    per_row = max(t_index, t_cov, t_hor) / rows
    print(
        f"SCALE rows={rows} final={finals} group_index={t_index:.2f}s coverage={t_cov:.2f}s "
        f"horizon={t_hor:.2f}s extrapolated_{TARGET_ROWS}_rows={per_row * TARGET_ROWS:.0f}s"
    )
    assert max(t_index, t_cov, t_hor) < LIMIT_SECONDS
