"""Passage vectors for meaning-based search (IDEA-102, decision 140 proposed).

The vectors live in the passage sidecar (`passage_index`), in their own table
`passage_vectors(conversion_id, passage_id, model_key, dim, vector)`. A local embedding model is
computation, not judgement (precedent: the ranker, decision 116): it orders passages and never
includes, excludes or drops one. The platform downloads nothing and calls no remote model.

Invariants:
- `model_key` is `<model id>@<first 16 chars of the weights hash>/chunker<CHUNKER_VERSION>`. A
  vector is used only under the key it was made with; another key (other weights, other chunker)
  forces a re-embed, and vectors of other keys are removed by `ensure_embedded`.
- `ensure_embedded` embeds only the indexed passages of the pinned conversions of the selection
  that lack a vector for the current key; it is incremental and commits after every batch of
  `BATCH` passages, so an interrupted run resumes where it stopped. It removes the vectors of
  conversions that are no longer pinned, of passages that are no longer indexed, and of other keys.
- A passage longer than one embedding window (`embedding_windows`) is stored as the normalised
  mean of the normalised vectors of its windows. Every stored vector is a unit vector (float32).
- The table has its own schema version (`passage_vectors_meta`); another version drops and
  recreates only this table, never the passage index tables.
- Search is exact cosine over the selection's passages; there is no threshold and nothing is
  dropped. numpy is imported lazily (extra `ranker`); without it search refuses with the
  `ranker_unavailable` remedy.
- Only the sidecar is written, never an event.
"""

from __future__ import annotations

import sqlite3
from array import array
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from factory.document.passages import embedding_windows
from factory.services.context import Project
from factory.services.passage_index import CHUNKER_VERSION, ensure_indexed, open_index
from factory.services.ranking_model import Embedder, Specter2Embedder, ranker_unavailable
from factory.services.selection import SelectedWork

__all__ = [
    "BATCH",
    "VECTORS_SCHEMA_VERSION",
    "EmbedReport",
    "count_missing",
    "count_passages",
    "default_embedder",
    "ensure_embedded",
    "model_key",
    "vector_ranking",
]

BATCH = 64
VECTORS_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS passage_vectors_meta(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS passage_vectors(
    conversion_id TEXT NOT NULL,
    passage_id TEXT NOT NULL,
    model_key TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (conversion_id, passage_id, model_key)
);
"""


@dataclass(frozen=True)
class EmbedReport:
    """Passages embedded now, already embedded, vectors removed, and passages still lacking one
    (non-zero only when `limit` stopped the run)."""

    embedded: int
    reused: int
    removed: int
    missing: int
    model_key: str


def default_embedder() -> Embedder:
    """SPECTER2 from FACTORY_RANKER_MODEL; refuses (`ranker_unavailable`) when not supplied."""
    return Specter2Embedder()


def model_key(embedder: Embedder) -> str:
    return f"{embedder.model_id}@{embedder.weights_hash[:16]}/chunker{CHUNKER_VERSION}"


def _prepare(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS passage_vectors_meta(version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM passage_vectors_meta").fetchone()
    if row is None or row[0] != VECTORS_SCHEMA_VERSION:
        conn.execute("DROP TABLE IF EXISTS passage_vectors")
        conn.execute("DELETE FROM passage_vectors_meta")
        conn.execute("INSERT INTO passage_vectors_meta VALUES (?)", (VECTORS_SCHEMA_VERSION,))
    conn.executescript(_SCHEMA)


def _normalised(vector: Sequence[float]) -> list[float]:
    norm = sum(x * x for x in vector) ** 0.5
    return [x / norm for x in vector] if norm > 0 else list(vector)


def _passage_vector(windows: Sequence[Sequence[float]]) -> list[float]:
    """The normalised mean of the normalised window vectors."""
    units = [_normalised(w) for w in windows]
    mean = [sum(col) / len(units) for col in zip(*units, strict=True)]
    return _normalised(mean)


def _pinned(works: Sequence[SelectedWork]) -> list[str]:
    return [w.conversion_id for w in works]


def _missing_rows(
    conn: sqlite3.Connection, pinned: Sequence[str], key: str
) -> list[tuple[str, str, str]]:
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS vpinned(conversion_id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM vpinned")
    conn.executemany("INSERT INTO vpinned VALUES (?)", [(c,) for c in pinned])
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT p.conversion_id, p.passage_id, p.text FROM passages p "
            "WHERE p.conversion_id IN (SELECT conversion_id FROM vpinned) "
            "AND NOT EXISTS (SELECT 1 FROM passage_vectors v WHERE v.conversion_id = "
            "p.conversion_id AND v.passage_id = p.passage_id AND v.model_key = ?) "
            "ORDER BY p.conversion_id, p.passage_id",
            (key,),
        )
    ]


def count_missing(project: Project, works: Sequence[SelectedWork], key: str) -> int:
    """How many indexed passages of the pinned conversions of `works` lack a vector under `key`.
    The passage index must be current (`ensure_indexed`)."""
    with open_index(project) as conn:
        _prepare(conn)
        return len(_missing_rows(conn, _pinned(works), key))


def count_passages(project: Project, works: Sequence[SelectedWork]) -> int:
    """How many passages are indexed for the pinned conversions of `works`."""
    with open_index(project) as conn:
        marks = ",".join("?" * len(works))
        row = conn.execute(
            f"SELECT COUNT(*) FROM passages WHERE conversion_id IN ({marks})", _pinned(works)
        ).fetchone()
    return int(row[0])


def ensure_embedded(
    project: Project,
    works: Sequence[SelectedWork],
    embedder: Embedder,
    *,
    limit: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> EmbedReport:
    """Bring the vectors in line with the pinned conversions of `works` (module invariants).
    `limit` caps the passages embedded in this call; `progress(done, total)` is called after each
    committed batch. Indexes the works first."""
    ensure_indexed(project, works)
    key = model_key(embedder)
    pinned = _pinned(works)
    embedded = removed = 0
    with open_index(project) as conn:
        _prepare(conn)
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS vpinned(conversion_id TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM vpinned")
        conn.executemany("INSERT INTO vpinned VALUES (?)", [(c,) for c in pinned])
        before = conn.total_changes
        conn.execute(
            "DELETE FROM passage_vectors WHERE model_key <> ? "
            "OR NOT EXISTS (SELECT 1 FROM passages p WHERE p.conversion_id = "
            "passage_vectors.conversion_id AND p.passage_id = passage_vectors.passage_id)",
            (key,),
        )
        removed = conn.total_changes - before
        conn.commit()
        todo = _missing_rows(conn, pinned, key)
        total = len(todo)
        reused = conn.execute(
            "SELECT COUNT(*) FROM passage_vectors WHERE model_key = ? "
            "AND conversion_id IN (SELECT conversion_id FROM vpinned)",
            (key,),
        ).fetchone()[0]
        if limit is not None:
            todo = todo[:limit]
        for start in range(0, len(todo), BATCH):
            batch = todo[start : start + BATCH]
            windows = [embedding_windows(text) for _, _, text in batch]
            flat = [w for ws in windows for w in ws]
            vectors = embedder.embed(flat)
            offset = 0
            rows: list[tuple[str, str, str, int, bytes]] = []
            for (conv, pid, _), ws in zip(batch, windows, strict=True):
                vec = _passage_vector(vectors[offset : offset + len(ws)])
                offset += len(ws)
                rows.append((conv, pid, key, len(vec), array("f", vec).tobytes()))
            conn.executemany("INSERT OR REPLACE INTO passage_vectors VALUES (?, ?, ?, ?, ?)", rows)
            conn.commit()
            embedded += len(batch)
            if progress is not None:
                progress(embedded, len(todo))
    return EmbedReport(embedded, reused, removed, total - embedded, key)


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:
        raise ranker_unavailable("numpy is not installed") from exc
    return numpy


def vector_ranking(
    project: Project,
    works: Sequence[SelectedWork],
    query: str,
    embedder: Embedder,
    *,
    kinds: Collection[str] | None,
    k: int,
) -> list[tuple[str, str]]:
    """The `k` best (conversion_id, passage_id) pairs of the selection for `query`, best first, by
    exact cosine; ties break by conversion id then passage id. Only passages holding a vector under
    the embedder's key take part (see `count_missing`)."""
    np = _numpy()
    key = model_key(embedder)
    with open_index(project) as conn:
        _prepare(conn)
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS vpinned(conversion_id TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM vpinned")
        conn.executemany("INSERT INTO vpinned VALUES (?)", [(c,) for c in _pinned(works)])
        rows = conn.execute(
            "SELECT v.conversion_id, v.passage_id, v.dim, v.vector, p.section_kind "
            "FROM passage_vectors v JOIN passages p ON p.conversion_id = v.conversion_id "
            "AND p.passage_id = v.passage_id "
            "WHERE v.model_key = ? AND v.conversion_id IN (SELECT conversion_id FROM vpinned) "
            "ORDER BY v.conversion_id, v.passage_id",
            (key,),
        ).fetchall()
    wanted = None if kinds is None else {str(x) for x in kinds}
    rows = [r for r in rows if wanted is None or r[4] in wanted]
    if not rows:
        return []
    query_vec = np.asarray(embedder.embed([query])[0], dtype=np.float32)
    norm = float(np.linalg.norm(query_vec))
    if norm > 0:
        query_vec = query_vec / norm
    matrix = np.stack([np.frombuffer(r[3], dtype=np.float32) for r in rows])
    scores = matrix @ query_vec
    order = np.argsort(-scores, kind="stable")[:k]  # rows are already in id order: stable ties
    return [(rows[int(i)][0], rows[int(i)][1]) for i in order]
