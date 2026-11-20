"""Projection of answers of the papers chat in Ask mode (plan spar-night N2).

Tables: `answers` (one row per recorded answer), `answer_sentences` (its sentences, by index) and
`answer_ratings` (the latest rating per answer and sentence; sentence -1 is the answer as a whole).

An event is folded only when it is consistent with what `services/answers.py` enforces; one that
fails stays in the log and changes nothing (no service writes one, so it was written by hand):
- an answer needs an agent actor, a selection digest that matches the recorded (work, conversion)
  pairs, a parent that is a folded answer or sheet when one is named, at least one sentence or an
  `unanswered` note, and sentences each of a work among the pairs, on the conversion listed for it;
- a rating needs a human actor, a folded answer and, when a sentence is named, that sentence.
  (Quotes are checked by the service only; the fold cannot read the conversions.)

Handlers are total: a failure at any point folds nothing and never raises, on rebuild too.
"""

from __future__ import annotations

import hashlib

from pydantic import JsonValue
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.errors import FactoryError
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.answers import AnswerRated, AnswerRecorded

WHOLE = -1
"""The `sentence` value of a rating of the answer as a whole."""


class AnswerTables:
    def __init__(self, answers: Table, sentences: Table, ratings: Table) -> None:
        self.answers = answers
        self.sentences = sentences
        self.ratings = ratings


def answer_tables(metadata: MetaData) -> AnswerTables:
    answers = Table(
        "answers",
        metadata,
        Column("answer_id", String, primary_key=True),
        Column("question", String, nullable=False),
        Column("mode", String, nullable=False),
        Column("selection", String, nullable=False),
        Column("selection_digest", String, nullable=False),
        Column("parent", String),
        Column("request_id", String),
        Column("unanswered", String),
        Column("sentence_count", Integer, nullable=False),
        Column("session", String),
        Column("actor", String, nullable=False),
        Column("model", String),
        Column("skill", String),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    sentences = Table(
        "answer_sentences",
        metadata,
        Column("answer_id", String, primary_key=True),
        Column("idx", Integer, primary_key=True),
        Column("text", String, nullable=False),
        Column("work_id", String, nullable=False),
        Column("anchor", String, nullable=False),
        Column("quote", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("markdown_hash", String, nullable=False),
        Index("ix_answer_sentences_work", "work_id"),
    )
    ratings = Table(
        "answer_ratings",
        metadata,
        Column("answer_id", String, primary_key=True),
        Column("sentence", Integer, primary_key=True),
        Column("rating", String, nullable=False),
        Column("note", String, nullable=False),
        Column("actor", String, nullable=False),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return AnswerTables(answers, sentences, ratings)


def selection_digest_of(pairs: list[JsonValue], closed: bool = False) -> str:
    """The digest `services/selection.py` gives a selection of these (work, conversion) pairs. A
    closed selection (`closed` true in its spec) hashes `{"closed": true, "works": pairs}`, so it
    differs from an open selection that resolves to the same pairs."""
    body: JsonValue = {"closed": True, "works": pairs} if closed else pairs
    return hashlib.sha256(canonical_json(body)).hexdigest()


def answer_handlers(tables: AnswerTables) -> dict[str, Handler]:
    def recorded(conn: Connection, event: Event) -> None:
        payload = AnswerRecorded.model_validate(event.payload)
        if event.actor.kind != "agent":
            return
        pairs: list[JsonValue] = [[w.work_id, w.conversion_id] for w in payload.selection_works]
        if (
            selection_digest_of(pairs, payload.selection.get("closed") is True)
            != payload.selection_digest
        ):
            return
        if not payload.sentences and not (payload.unanswered or "").strip():
            return
        if payload.parent is not None and not _parent_exists(conn, payload.parent):
            return
        pinned = {w.work_id: w.conversion_id for w in payload.selection_works}
        for s in payload.sentences:
            if pinned.get(s.work_id) != s.conversion_id:
                return
        conn.execute(
            sqlite_insert(tables.answers)
            .values(
                answer_id=payload.answer_id,
                question=payload.question,
                mode=payload.mode,
                selection=canonical_json(payload.selection).decode(),
                selection_digest=payload.selection_digest,
                parent=payload.parent,
                request_id=payload.request_id,
                unanswered=payload.unanswered,
                sentence_count=len(payload.sentences),
                session=event.actor.session,
                actor=event.actor.id,
                model=event.actor.model,
                skill=event.actor.skill,
                ts=format_ts(event.ts),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["answer_id"])
        )
        for i, s in enumerate(payload.sentences):
            conn.execute(
                sqlite_insert(tables.sentences)
                .values(
                    answer_id=payload.answer_id,
                    idx=i,
                    text=s.text,
                    work_id=s.work_id,
                    anchor=s.anchor,
                    quote=s.quote,
                    conversion_id=s.conversion_id,
                    markdown_hash=s.markdown_hash,
                )
                .on_conflict_do_nothing(index_elements=["answer_id", "idx"])
            )

    def rated(conn: Connection, event: Event) -> None:
        payload = AnswerRated.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        found = conn.execute(
            text("SELECT sentence_count FROM answers WHERE answer_id = :a"),
            {"a": payload.answer_id},
        ).first()
        if found is None:
            return
        if payload.sentence is not None and payload.sentence >= int(found[0]):
            return
        sentence = WHOLE if payload.sentence is None else payload.sentence
        values = {
            "rating": payload.rating,
            "note": payload.note,
            "actor": event.actor.id,
            "ts": format_ts(event.ts),
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(tables.ratings)
            .values(answer_id=payload.answer_id, sentence=sentence, **values)
            .on_conflict_do_update(index_elements=["answer_id", "sentence"], set_=values)
        )

    def total(fold: Handler) -> Handler:
        def run(conn: Connection, event: Event) -> None:
            try:
                with conn.begin_nested():
                    fold(conn, event)
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                FactoryError,
                SQLAlchemyError,
            ):
                return

        return run

    return {
        "chat.answer_recorded": total(recorded),
        "chat.answer_rated": total(rated),
    }


def _parent_exists(conn: Connection, parent: str) -> bool:
    table, column = (
        ("answers", "answer_id") if parent.startswith("ans_") else ("sheets", "sheet_id")
    )
    return (
        conn.execute(text(f"SELECT 1 FROM {table} WHERE {column} = :p"), {"p": parent}).first()
        is not None
    )
