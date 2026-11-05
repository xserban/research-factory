"""Projection of external manuscripts (slice 7b, plan W-C).

`manuscripts` keeps one row per manuscript, `manuscript_sentences` its sentences by position and
hash, `manuscript_citations` what each key resolves to and `manuscript_closures` the units the
platform closed. Nothing here holds a manuscript's text, and nothing here reads the library: the
library is git-ignored, so a rebuild on another computer folds the same rows without it.

An act is folded only when it is consistent with what the services enforce; an event that fails
this stays in the log and changes nothing (no service writes one, so it was written by hand):
- A manuscript is folded from a human, for a fresh id.
- A segmentation is folded from the system, for a known manuscript with none yet, under the
  segmenter its `manuscript.added` names.
- A resolution is folded from the system, for a key a sentence of the manuscript cites, naming a
  stored work when it names one; a fuzzy match resolves only through a human's decision, so a
  `title-fuzzy` resolution with none changes nothing. It replaces the key's row and lifts the key's
  closures, which the same call writes anew. On a key a human decided it can only lift closures:
  it folds when it agrees with the decision, and changes no row.
- A decision is folded from a human, for a proposed citation with no decision.
- A closure is folded from the system, for a key the sentence cites, with no closure yet, when the
  citation agrees with the reason: `citation-unresolved` for an unresolved key, any other for the
  resolved work it names.

Handlers are total: an event naming an unknown manuscript changes nothing, never raises. A fold is
atomic: its writes run in a savepoint, so a failure half way leaves nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    select,
    update,
)
from sqlalchemy import text as sql
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.manuscripts import (
    CitationDecided,
    CitationDecision,
    CitationMethod,
    CitationResolved,
    CitationState,
    CloseReason,
    ManuscriptAdded,
    ManuscriptSegmented,
    UnitClosed,
)


@dataclass(frozen=True)
class ManuscriptTables:
    manuscripts: Table
    sentences: Table
    citations: Table
    closures: Table


def manuscript_tables(metadata: MetaData) -> ManuscriptTables:
    manuscripts = Table(
        "manuscripts",
        metadata,
        Column("manuscript_id", String, primary_key=True),
        Column("library_hash", String, nullable=False),
        Column("format", String, nullable=False),
        Column("bib_hash", String),
        Column("bib_format", String),
        Column("label", String, nullable=False),
        Column("segmenter", Integer, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_manuscripts_hash", "library_hash"),
    )
    sentences = Table(
        "manuscript_sentences",
        metadata,
        Column("manuscript_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("char_start", Integer, nullable=False),
        Column("char_end", Integer, nullable=False),
        Column("sha256", String, nullable=False),
        Column("keys", String, nullable=False),
    )
    citations = Table(
        "manuscript_citations",
        metadata,
        Column("manuscript_id", String, primary_key=True),
        Column("key", String, primary_key=True),
        Column("work_id", String),
        Column("method", String, nullable=False),
        Column("score", Float),
        Column("state", String, nullable=False),
        Column("decision", String),
        Column("event_id", String, nullable=False),
    )
    closures = Table(
        "manuscript_closures",
        metadata,
        Column("manuscript_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("key", String, primary_key=True),
        Column("work_id", String),
        Column("reason", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return ManuscriptTables(manuscripts, sentences, citations, closures)


def manuscript_handlers(t: ManuscriptTables, blobs: BlobStore | None = None) -> dict[str, Handler]:
    return {
        "manuscript.added": _total(_added(t)),
        "manuscript.segmented": _total(_segmented(t)),
        "manuscript.citation_resolved": _total(_citation_resolved(t)),
        "manuscript.citation_decided": _total(_citation_decided(t)),
        "manuscript.unit_closed": _total(_unit_closed(t)),
    }


def _total(handler: Handler) -> Handler:
    """A handler that cannot raise on what a log holds (the log may be edited by hand, and a
    rebuild must still finish) and folds all of an event or nothing."""

    def total(conn: Connection, event: Event) -> None:
        try:
            with conn.begin_nested():
                handler(conn, event)
        except (
            ValueError,
            ArithmeticError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
            FactoryError,
            SQLAlchemyError,
        ):
            return

    return total


def _added(t: ManuscriptTables) -> Handler:
    def added(conn: Connection, event: Event) -> None:
        p = ManuscriptAdded.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        known = select(t.manuscripts.c.manuscript_id).where(
            t.manuscripts.c.manuscript_id == p.manuscript_id
        )
        if conn.execute(known).first():
            return
        conn.execute(
            t.manuscripts.insert().values(
                manuscript_id=p.manuscript_id,
                library_hash=p.library_hash,
                format=p.format.value,
                bib_hash=p.bib_hash,
                bib_format=None if p.bib_format is None else p.bib_format.value,
                label=p.label,
                segmenter=p.segmenter,
                event_id=event.id,
            )
        )

    return added


def _segmented(t: ManuscriptTables) -> Handler:
    def segmented(conn: Connection, event: Event) -> None:
        p = ManuscriptSegmented.model_validate(event.payload)
        if event.actor.kind != "system":
            return
        row = conn.execute(
            select(t.manuscripts.c.segmenter).where(
                t.manuscripts.c.manuscript_id == p.manuscript_id
            )
        ).first()
        if row is None or row[0] != p.segmenter:
            return
        done = select(t.sentences.c.ordinal).where(t.sentences.c.manuscript_id == p.manuscript_id)
        if conn.execute(done.limit(1)).first():
            return
        for s in p.sentences:
            conn.execute(
                t.sentences.insert().values(
                    manuscript_id=p.manuscript_id,
                    ordinal=s.ordinal,
                    char_start=s.start,
                    char_end=s.end,
                    sha256=s.sha256,
                    keys=json.dumps(s.keys),
                )
            )

    return segmented


def _cites(conn: Connection, manuscript_id: str, key: str, ordinal: int | None = None) -> bool:
    """Whether a sentence of the manuscript (the one at `ordinal`, when given) cites `key`."""
    return (
        conn.execute(
            sql(
                "SELECT 1 FROM manuscript_sentences s, json_each(s.keys) j "
                "WHERE s.manuscript_id = :m AND j.value = :k "
                "AND (:o IS NULL OR s.ordinal = :o) LIMIT 1"
            ),
            {"m": manuscript_id, "k": key, "o": ordinal},
        ).first()
        is not None
    )


def _citation(
    t: ManuscriptTables, conn: Connection, manuscript_id: str, key: str
) -> tuple[str, str | None, str | None] | None:
    """The state, work and decision of a key's citation."""
    c = t.citations.c
    row = conn.execute(
        select(c.state, c.work_id, c.decision).where(c.manuscript_id == manuscript_id, c.key == key)
    ).first()
    return None if row is None else (str(row[0]), row[1], row[2])


def _lift_closures(t: ManuscriptTables, conn: Connection, manuscript_id: str, key: str) -> None:
    c = t.closures.c
    conn.execute(delete(t.closures).where(c.manuscript_id == manuscript_id, c.key == key))


def _citation_resolved(t: ManuscriptTables) -> Handler:
    def resolved(conn: Connection, event: Event) -> None:
        p = CitationResolved.model_validate(event.payload)
        if event.actor.kind != "system" or not _cites(conn, p.manuscript_id, p.key):
            return
        row = _citation(t, conn, p.manuscript_id, p.key)
        if row is not None and row[2] is not None:
            if row[:2] == (p.state.value, p.work_id):
                _lift_closures(t, conn, p.manuscript_id, p.key)
            return
        if p.state is CitationState.RESOLVED and p.method is CitationMethod.TITLE_FUZZY:
            return
        if (
            p.work_id is not None
            and not conn.execute(
                sql("SELECT 1 FROM works WHERE work_id = :w"), {"w": p.work_id}
            ).first()
        ):
            return
        c = t.citations.c
        conn.execute(delete(t.citations).where(c.manuscript_id == p.manuscript_id, c.key == p.key))
        conn.execute(
            t.citations.insert().values(
                manuscript_id=p.manuscript_id,
                key=p.key,
                work_id=p.work_id,
                method=p.method.value,
                score=p.score,
                state=p.state.value,
                decision=None,
                event_id=event.id,
            )
        )
        _lift_closures(t, conn, p.manuscript_id, p.key)

    return resolved


def _citation_decided(t: ManuscriptTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        p = CitationDecided.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        row = _citation(t, conn, p.manuscript_id, p.key)
        if row is None or row[0] != CitationState.PROPOSED.value or row[2] is not None:
            return
        confirmed = p.decision is CitationDecision.CONFIRM
        c = t.citations.c
        conn.execute(
            update(t.citations)
            .where(c.manuscript_id == p.manuscript_id, c.key == p.key)
            .values(
                state=(CitationState.RESOLVED if confirmed else CitationState.UNRESOLVED).value,
                work_id=row[1] if confirmed else None,
                decision=p.decision.value,
                event_id=event.id,
            )
        )
        _lift_closures(t, conn, p.manuscript_id, p.key)

    return decided


def _unit_closed(t: ManuscriptTables) -> Handler:
    def closed(conn: Connection, event: Event) -> None:
        p = UnitClosed.model_validate(event.payload)
        if event.actor.kind != "system" or not _cites(conn, p.manuscript_id, p.key, p.ordinal):
            return
        row = _citation(t, conn, p.manuscript_id, p.key)
        if row is None:
            return
        state = CitationState(str(row[0]))
        if p.reason is CloseReason.CITATION_UNRESOLVED:
            if state is not CitationState.UNRESOLVED:
                return
        elif state is not CitationState.RESOLVED or row[1] != p.work_id:
            return
        c = t.closures.c
        known = select(c.reason).where(
            c.manuscript_id == p.manuscript_id, c.ordinal == p.ordinal, c.key == p.key
        )
        if conn.execute(known).first():
            return
        conn.execute(
            t.closures.insert().values(
                manuscript_id=p.manuscript_id,
                ordinal=p.ordinal,
                key=p.key,
                work_id=p.work_id,
                reason=p.reason.value,
                event_id=event.id,
            )
        )

    return closed
