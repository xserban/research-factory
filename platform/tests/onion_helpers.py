"""A constructed graph for the onion tests (slice 7b, plan V-A).

Twelve works: focus F1-F3, ring 1 A1-A4, ring 2 B1-B5 (B5 is not a corpus work). Written straight
into the index tables of an empty, synced project (no rebuild is triggered), as the lineage scale
test does; the effective status of a relation is the one `relations` yields:

- `inferred` (no decision), `stated` with no resolved link (stale), `inferred` decided `reject`
  (rejected), `inferred` decided `confirm` (confirmed).

Edges: cites F1->A1, A2->F2, A1->B1, B2->A1, A2->B3, A4->B5; builds-on F3->A3 and A3->B4
(confirmed); improves-on A4->F3 (confirmed). Not counted by default: builds-on F2->B5 (inferred),
F1->B2 (stale), F3->B1 (rejected).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from factory.services.context import Project

F = [f"rf:f{i}-{i:08x}" for i in range(1, 4)]
A = [f"rf:a{i}-{i + 16:08x}" for i in range(1, 5)]
B = [f"rf:b{i}-{i + 32:08x}" for i in range(1, 6)]
ALL = [*F, *A, *B]
CORPUS = [*F, *A, *B[:4]]


def cite(src: str, dst: str) -> tuple[str, str, str, str, str | None]:
    return ("cites", src, dst, "stated", None)


def relation(
    kind: str, src: str, dst: str, status: str, decision: str | None
) -> tuple[str, str, str, str, str | None]:
    return (kind, src, dst, status, decision)


EDGES: list[tuple[str, str, str, str, str | None]] = [
    cite(F[0], A[0]),
    cite(A[1], F[1]),
    cite(A[0], B[0]),
    cite(B[1], A[0]),
    cite(A[1], B[2]),
    relation("builds-on", F[2], A[2], "inferred", "confirm"),
    relation("builds-on", A[2], B[3], "inferred", "confirm"),
    relation("improves-on", A[3], F[2], "inferred", "confirm"),
    cite(A[3], B[4]),
    relation("builds-on", F[1], B[4], "inferred", None),  # inferred
    relation("builds-on", F[0], B[1], "stated", None),  # stale: no resolved link
    relation("builds-on", F[2], B[0], "inferred", "reject"),  # rejected
]


def write_graph(
    project: Project,
    edges: Sequence[tuple[str, str, str, str, str | None]] = EDGES,
    corpus: Sequence[str] = CORPUS,
    extra_nodes: Sequence[str] = (),
) -> None:
    project.index.sync()
    nodes = sorted({*ALL, *extra_nodes})
    works: list[dict[str, Any]] = [
        {"w": w, "d": json.dumps({"title": f"Title of {w}", "dates": {"published": "2020-05-01"}})}
        for w in corpus
    ]
    cites: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    for n, (kind, src, dst, status, decision) in enumerate(edges):
        if kind == "cites":
            rex = f"rex_{n:026d}"
            cites.append(
                {
                    "id": f"cit:{rex}:1",
                    "s": src,
                    "t": dst,
                    "b": f"{rex}:1",
                    "rex": rex,
                }
            )
        else:
            lineage.append(
                {
                    "id": f"rel_{n:026d}",
                    "k": kind,
                    "s": src,
                    "t": dst,
                    "st": status,
                    "d": decision,
                }
            )
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_nodes (node_id, node_type, event_id) VALUES (:n, 'paper', 'ev')"
            ),
            [{"n": n} for n in nodes],
        )
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, :d, 'ev')"), works
        )
        if cites:
            conn.execute(
                text(
                    "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, "
                    "basis, reference_extraction_id, ordinal, live, decision, flags, event_id) "
                    "VALUES (:id, 'cites', :s, :t, 'stated', :b, :rex, 1, 1, NULL, '[]', 'ev')"
                ),
                cites,
            )
        if lineage:
            conn.execute(
                text(
                    "INSERT INTO relations (relation_id, source_work, target, edge_type, "
                    "basis_item, status, flags, decision, event_id) VALUES "
                    "(:id, :s, :t, :k, NULL, :st, '[]', :d, 'ev')"
                ),
                lineage,
            )
            conn.execute(
                text(
                    "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, "
                    "basis, live, decision, flags, event_id) SELECT relation_id, edge_type, "
                    "source_work, target, status, NULL, 1, decision, '[]', 'ev' FROM relations"
                )
            )
        conn.commit()
