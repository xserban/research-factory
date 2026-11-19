"""A rebuildable keyword index of passages over the pinned conversions (plan chat T3b).

The index is a SIDECAR SQLite file at `<project>/.cache/passage_index.sqlite`. It is derived from
the canonical Markdown blobs and is never authoritative: it may be deleted at any time and the next
`ensure_indexed` rebuilds it. It is not the events index, which only the projector writes.

Invariants:
- Only the pinned (default) conversion of each work in the selection is indexed; the rows of any
  other conversion of those works are removed, so a search never reads a superseded conversion.
- A conversion is re-indexed when its `markdown_hash`, `CHUNKER_VERSION` or the work title differs
  from the `conversions` marker row held; otherwise its rows are reused unchanged. The marker row
  is written for every indexed conversion, also one with no indexed passage, so such a conversion
  is not re-cut on every call. Marker rows of other conversions of a work are removed with them.
- Passages whose section kind is related or back are not indexed (appendices are, tagged);
  they are counted in `IndexReport.excluded_passages` (for the conversions indexed in that
  call only).
- Rows are a pure function of the Markdown, the chunker and the work title at index time.
- The sidecar's layout carries `SCHEMA_VERSION` in SQLite's `user_version`. A sidecar of another
  version has this module's tables (`passages`, `passages_fts`, `conversions`) dropped and
  recreated on open, so a schema change never breaks an existing sidecar; tables of other
  modules are left alone.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from factory.canonical import canonical_json
from factory.document.passages import SectionKind, cut_passages
from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.context import Project
from factory.services.conversions import conversion_of
from factory.services.search import get_work
from factory.services.selection import SelectedWork

__all__ = [
    "CHUNKER_VERSION",
    "SCHEMA_VERSION",
    "TARGET_WORDS",
    "UNINDEXED_KINDS",
    "IndexReport",
    "ensure_indexed",
    "index_path",
    "open_index",
]

TARGET_WORDS = 250
_TITLE_SEP = " \u203a "  # joins title and section path
MIN_WORDS = 30
UNINDEXED_KINDS = frozenset({SectionKind.RELATED, SectionKind.BACK})
"""Appendices are indexed, tagged: they hold ablations and extended results (researcher,
2026-11-18)."""
CHUNKER_VERSION = f"4:target_words={TARGET_WORDS}:min_words={MIN_WORDS}"
"""Bumped when the passage cutter or its target size changes; forces a re-index."""

SCHEMA_VERSION = 3
"""Bumped when the sidecar tables change shape; an older sidecar's tables are recreated."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversions(
    conversion_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    markdown_hash TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passages(
    conversion_id TEXT NOT NULL,
    work_id TEXT NOT NULL,
    passage_id TEXT NOT NULL,
    anchors_json TEXT NOT NULL,
    section_path_json TEXT NOT NULL,
    section_kind TEXT NOT NULL,
    text TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    markdown_hash TEXT NOT NULL,
    PRIMARY KEY (conversion_id, passage_id)
);
CREATE INDEX IF NOT EXISTS passages_work ON passages(work_id);
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    title_path, text, tokenize='porter'
);
"""


@dataclass(frozen=True)
class IndexReport:
    """Conversions indexed now, reused as they were, and the passage rows removed."""

    indexed: int
    reused: int
    removed: int
    excluded_passages: int = 0


def index_path(project: Project) -> Path:
    """Where the sidecar lives (it need not exist)."""
    return project.paths.dir / ".cache" / "passage_index.sqlite"


@contextmanager
def open_index(project: Project) -> Iterator[sqlite3.Connection]:
    """The sidecar connection, created with its schema when absent."""
    path = index_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            conn.executescript(
                "DROP TABLE IF EXISTS passages_fts; DROP TABLE IF EXISTS passages;"
                " DROP TABLE IF EXISTS conversions;"
                f" PRAGMA user_version = {SCHEMA_VERSION};"
            )
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _delete(conn: sqlite3.Connection, where: str, params: tuple[str, ...]) -> int:
    rowids = [r[0] for r in conn.execute(f"SELECT rowid FROM passages WHERE {where}", params)]
    conn.executemany("DELETE FROM passages_fts WHERE rowid = ?", [(r,) for r in rowids])
    conn.execute(f"DELETE FROM passages WHERE {where}", params)
    return len(rowids)


def ensure_indexed(project: Project, works: Sequence[SelectedWork]) -> IndexReport:
    """Bring the sidecar in line with the pinned conversions of `works` (see the module
    invariants). Writes only the sidecar."""
    indexed = reused = removed = excluded = 0
    with open_index(project) as conn:
        for work in works:
            conversion = conversion_of(project, work.conversion_id)
            if conversion is None:
                raise FactoryValidationError(
                    [ValidationIssue("conversion_id", f"{work.conversion_id}: unknown conversion")]
                )
            removed += _delete(
                conn,
                "work_id = ? AND conversion_id <> ?",
                (work.work_id, work.conversion_id),
            )
            conn.execute(
                "DELETE FROM conversions WHERE work_id = ? AND conversion_id <> ?",
                (work.work_id, work.conversion_id),
            )
            record = get_work(project, work.work_id)
            title = "" if record is None else record.title
            held = conn.execute(
                "SELECT markdown_hash, chunker_version, title FROM conversions "
                "WHERE conversion_id = ?",
                (work.conversion_id,),
            ).fetchall()
            if held == [(conversion.markdown_hash, CHUNKER_VERSION, title)]:
                reused += 1
                continue
            removed += _delete(conn, "conversion_id = ?", (work.conversion_id,))
            markdown = project.library.get(conversion.markdown_hash).decode("utf-8")
            conn.execute(
                "INSERT OR REPLACE INTO conversions VALUES (?, ?, ?, ?, ?)",
                (
                    work.conversion_id,
                    work.work_id,
                    conversion.markdown_hash,
                    CHUNKER_VERSION,
                    title,
                ),
            )
            for passage in cut_passages(markdown, target_words=TARGET_WORDS):
                if passage.section_kind in UNINDEXED_KINDS:
                    excluded += 1
                    continue
                cursor = conn.execute(
                    "INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        work.conversion_id,
                        work.work_id,
                        passage.passage_id,
                        canonical_json(list(passage.anchors)).decode("utf-8"),
                        canonical_json(list(passage.section_path)).decode("utf-8"),
                        passage.section_kind.value,
                        passage.text,
                        CHUNKER_VERSION,
                        conversion.markdown_hash,
                    ),
                )
                title_path = _TITLE_SEP.join([title, *passage.section_path])
                conn.execute(
                    "INSERT INTO passages_fts(rowid, title_path, text) VALUES (?, ?, ?)",
                    (cursor.lastrowid, title_path, passage.text),
                )
            indexed += 1
    return IndexReport(indexed, reused, removed, excluded)
