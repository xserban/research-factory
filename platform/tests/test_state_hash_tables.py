"""Guard: every projection table is classified for the state hash.

A table added after the base projection must be in `OMITTED_WHEN_EMPTY`, or an old log's hash
changes (it hashes the name of every non-omitted table even when empty). The base tables are
`HASHED_ALWAYS`; the rest of the schema is `NON_STATE_TABLES` or `OMITTED_WHEN_EMPTY`.
"""

from sqlalchemy import Column, Integer, MetaData, Table

from factory.index.default import default_projection
from factory.index.index import HASHED_ALWAYS, NON_STATE_TABLES, OMITTED_WHEN_EMPTY


def problems(tables: set[str]) -> list[str]:
    out: list[str] = []
    for name in sorted(tables - NON_STATE_TABLES):
        a, b = name in HASHED_ALWAYS, name in OMITTED_WHEN_EMPTY
        if not a and not b:
            out.append(
                f"table {name!r} is in neither HASHED_ALWAYS nor OMITTED_WHEN_EMPTY: add it to "
                "OMITTED_WHEN_EMPTY unless it must change old hashes, which needs a decision"
            )
        if a and b:
            out.append(f"table {name!r} is in both HASHED_ALWAYS and OMITTED_WHEN_EMPTY")
    for name in sorted(OMITTED_WHEN_EMPTY - tables):
        out.append(f"OMITTED_WHEN_EMPTY names {name!r}, which is not a table of the schema")
    for name in sorted(HASHED_ALWAYS - tables):
        out.append(f"HASHED_ALWAYS names {name!r}, which is not a table of the schema")
    return out


def test_every_table_is_classified() -> None:
    tables = set(default_projection().metadata.tables)
    assert problems(tables) == []


def test_guard_fails_for_an_unlisted_table() -> None:
    metadata = MetaData()
    Table("dummy_new_table", metadata, Column("id", Integer, primary_key=True))
    found = problems(set(default_projection().metadata.tables) | set(metadata.tables))
    assert len(found) == 1
    assert "dummy_new_table" in found[0] and "add it to OMITTED_WHEN_EMPTY" in found[0]


def test_guard_fails_for_a_missing_table() -> None:
    tables = set(default_projection().metadata.tables) - {"sheets"}
    assert any("'sheets'" in p and "not a table" in p for p in problems(tables))


def test_the_lists_are_disjoint() -> None:
    assert not (HASHED_ALWAYS & OMITTED_WHEN_EMPTY)
    assert not (HASHED_ALWAYS & NON_STATE_TABLES)
