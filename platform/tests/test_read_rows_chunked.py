"""`live_rows` reads rows above SQLite's variable limit (plan V-B review, C1a)."""

from __future__ import annotations

from sqlalchemy import text

from factory.model.extraction import Scope
from factory.services.context import Project
from factory.services.extraction import live_rows

ROWS = 33_000  # above the 32,766 bound variables of one statement


def test_live_rows_above_the_variable_limit(project: Project) -> None:
    project.index.sync()
    heads = [
        {
            "e": f"ext_{i:08d}",
            "w": f"rf:w{i % 50}",
            "k": f"rk_{i:012x}",
        }
        for i in range(ROWS)
    ]
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO extraction_rows (extraction_id, scope, pack, work_id, pass_label, "
                "task_id, protocol_id, schema_ref, document_id, conversion_id, row_key, event_id) "
                "VALUES (:e, 'evidence', 'ml-benchmark', :w, 'A', 'tsk_1', 'P@1', "
                "'ml-benchmark@1', 'doc_1', 'cnv_1', :k, 'ev')"
            ),
            heads,
        )
        conn.execute(
            text(
                "INSERT INTO extraction_fields (extraction_id, field, value, reported_in, "
                "copy_marker, reproduced) VALUES (:e, 'task', 'x', 'own', 0, 0)"
            ),
            [{"e": h["e"]} for h in heads],
        )
        conn.commit()
    rows = live_rows(project, scope=Scope.EVIDENCE)
    assert len(rows) == ROWS
    assert all(r.fields["task"].value == "x" for r in rows)
