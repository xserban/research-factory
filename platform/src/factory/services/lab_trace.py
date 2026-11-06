"""The trace node of an adoption (deploy-C): `adp:<document id>`, the adopting project's document.

Read-only. The node names the source project, document and attempt, and, when the principal may
read the source project, the source attempt's route and outcome, read from its index (nothing is
written there). A source that is gone or unreadable is named and left undescribed: the trace shows
a broken link rather than hiding it.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryError
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import IdGenerator
from factory.services.context import Project, open_project

__all__ = ["ADOPTION_KIND", "ADOPTION_PATTERN", "adoption_key", "describe", "edges"]

ADOPTION_KIND = "adoption"
ADOPTION_PATTERN = (rf"^adp:({DOCUMENT_ID_RE[1:-1]})$", ADOPTION_KIND)

Key = tuple[str, str]


def adoption_key(document_id: str) -> str:
    return f"adp:{document_id}"


def _source_attempt(project: Project, slug: str, attempt_id: str) -> str:
    from factory.services.lab_library import may_read_project

    try:
        source = open_project(
            project.settings,
            slug,
            session=IdGenerator(project.clock).ulid(),
            clock=project.clock,
            principal=project.principal,
        )
        if not may_read_project(source, project.principal):
            return "source unreadable"
        source.index.sync()
        with source.index.connect() as conn:
            row = conn.execute(
                text("SELECT route, outcome FROM fulltext_attempts WHERE attempt_id = :a"),
                {"a": attempt_id},
            ).first()
    except FactoryError:
        return "source missing"
    return "source attempt missing" if row is None else f"source attempt {row[0]}: {row[1]}"


def describe(project: Project, conn: Connection, ident: str) -> tuple[str, str] | None:
    """`(label, event_id)` of the adoption of document `ident` (`adp:doc_...`), or None."""
    document_id = ident.removeprefix("adp:")
    row = conn.execute(
        text(
            "SELECT source_project, source_doc, source_attempt, event_id FROM fulltext_adoptions "
            "WHERE document_id = :d"
        ),
        {"d": document_id},
    ).first()
    if row is None:
        return None
    slug, source_doc, source_attempt, event_id = (str(v) for v in row)
    found = _source_attempt(project, slug, source_attempt)
    label = f"adopted from {slug}: {source_doc}, attempt {source_attempt} ({found})"
    return label, event_id


def edges(conn: Connection, ident: str) -> tuple[list[Key], list[Key]]:
    """An adoption leads down to the document it created and has no upstream node here: its source
    lives in another project and is named in the label."""
    document_id = ident.removeprefix("adp:")
    known = conn.execute(
        text("SELECT 1 FROM fulltext_adoptions WHERE document_id = :d"), {"d": document_id}
    ).first()
    return [], [] if known is None else [("document", document_id)]
