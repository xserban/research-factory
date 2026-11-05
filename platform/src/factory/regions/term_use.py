"""The one region reader of the label tables: targets with a stated or confirmed application of a
promoted term (slice 3d rulings 6 and 16, plan Regions-C).

A term's applications are the live label applications whose key (or the key it was merged into)
is the term's name or an alias, restricted to the node types the term applies to. Each is
classified here, once, for the `term` region rule and for the term views:

- `confirmed`: a human applied it, it came from an import tag, or a human confirmed it;
- `stated`: an agent's application whose stored, verified quote contains the label key or any key
  of the term (re-checked at read time against the stored quote, not against the document);
- `inferred`: anything else.

Nothing here writes, imports a service or reads a layer table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.model.labels import label_key

SELECTABLE = frozenset({"stated", "confirmed"})
Status = Literal["confirmed", "stated", "inferred"]
_HUMAN_ORIGINS = frozenset({"human", "import-tag"})


@dataclass(frozen=True)
class TermApplication:
    application_id: str
    target_type: str
    target: str
    key: str
    origin: str
    status: Status


@dataclass(frozen=True)
class TermRow:
    term_id: str
    name: str
    keys: frozenset[str]
    applies_to: tuple[str, ...]
    retired: bool


def term_row(conn: Connection, term_id: str) -> TermRow | None:
    """The latest version of a term, or None for an unknown id."""
    found = conn.execute(
        text("SELECT name, applies_to, retired FROM terms WHERE term_id = :t"), {"t": term_id}
    ).first()
    if found is None:
        return None
    keys = frozenset(
        str(r[0])
        for r in conn.execute(
            text("SELECT key FROM term_aliases WHERE term_id = :t"), {"t": term_id}
        )
    )
    return TermRow(term_id, str(found[0]), keys, tuple(json.loads(str(found[1]))), bool(found[2]))


def term_applications(conn: Connection, term_id: str) -> list[TermApplication]:
    """Every live application of the term, classified, by target then id. Empty for an unknown
    term."""
    row = term_row(conn, term_id)
    if row is None:
        return []
    found = conn.execute(
        text(
            "SELECT application_id, target_type, target, key, origin, decision, quote_text "
            "FROM labels WHERE withdrawn = 0 AND COALESCE(decision, '') != 'reject' "
            "AND (key IN (SELECT key FROM term_aliases WHERE term_id = :t) "
            "OR live_key IN (SELECT key FROM term_aliases WHERE term_id = :t)) "
            "ORDER BY target_type, target, application_id"
        ),
        {"t": term_id},
    ).all()
    out: list[TermApplication] = []
    for app, target_type, target, key, origin, decision, quote in found:
        if str(target_type) not in row.applies_to:
            continue
        status: Status
        if decision == "confirm" or str(origin) in _HUMAN_ORIGINS:
            status = "confirmed"
        elif quote is not None and any(k in label_key(str(quote)) for k in row.keys):
            status = "stated"
        else:
            status = "inferred"
        out.append(
            TermApplication(str(app), str(target_type), str(target), str(key), str(origin), status)
        )
    return out


def term_targets(conn: Connection, term_id: str) -> list[tuple[str, str]]:
    """The distinct `(target type, target)` pairs with a stated or confirmed application."""
    return sorted(
        {
            (a.target_type, a.target)
            for a in term_applications(conn, term_id)
            if a.status in SELECTABLE
        }
    )


def term_has_import_tags(conn: Connection, term_id: str) -> bool:
    """Whether any live application of the term came from an import's tags."""
    return any(a.origin == "import-tag" for a in term_applications(conn, term_id))
