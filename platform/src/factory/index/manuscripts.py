"""Projection of external manuscripts (slice 7b, plan W-C).

`manuscripts` keeps one row per manuscript, `manuscript_sentences` its sentences by position and
hash. Nothing here holds a manuscript's text, and nothing here reads the library: the library is
git-ignored, so a rebuild on another computer folds the same rows without it.

An act is folded only when it is consistent with what the services enforce; an event that fails
this stays in the log and changes nothing (no service writes one, so it was written by hand):
- A manuscript is folded from a human, for a fresh id.
- A segmentation is folded from the system, for a known manuscript with none yet, under the
  segmenter its `manuscript.added` names.

Handlers are total: an event naming an unknown manuscript changes nothing, never raises. A fold is
atomic: its writes run in a savepoint, so a failure half way leaves nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.manuscripts import ManuscriptAdded, ManuscriptSegmented


@dataclass(frozen=True)
class ManuscriptTables:
    manuscripts: Table
    sentences: Table


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
    return ManuscriptTables(manuscripts, sentences)


def manuscript_handlers(t: ManuscriptTables, blobs: BlobStore | None = None) -> dict[str, Handler]:
    return {
        "manuscript.added": _total(_added(t)),
        "manuscript.segmented": _total(_segmented(t)),
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
