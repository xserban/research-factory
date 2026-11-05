"""Projection of drafts, their sections and sentences (slice 7b, plan W-A).

`drafts` keeps one row per draft with the outline it is pinned to; `draft_sections` its sections;
`draft_sentences` every recorded sentence with its author, session and model, `superseded_by` and
`withdrawn`; `sentence_supports`, `sentence_flags` and `sentence_stats` the supports, the stored
flags and the stat values read at write time. Status, staleness and eligibility are computed on
read, never stored.

An act is folded only when it is consistent with what the services enforce; an event that fails
this stays in the log and changes nothing (no service writes one, so it was written by hand):
- A draft is folded for a fresh id from a human or an agent, with an outline blob whose content
  hashes to the `outline_ref` (when the blob store is at hand). A repin is folded likewise, for
  a known draft.
- A sentence is folded for a known draft and section, a fresh id, an `author` equal to the
  actor's kind (human or agent), exactly one sentence, the class's structural rules (a claim has a
  support, a synthesis a stat or group support, a structural or interpretive sentence no number, a
  structural one no citation), and a `supersedes` that names a live sentence of the same section.
  What the supports are worth (eligibility, numbers, flags) is decided at write time by the
  service and recomputed on read; it cannot be known here.
- A withdrawal is folded for a live sentence; a reorder only when `order` is a permutation of the
  section's live sentences.

Handlers are total: an event naming an unknown draft or sentence changes nothing, never raises.
Rows are first-write-wins per id.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.extraction.numbers import numbers_in
from factory.index.projection import Handler
from factory.model.drafts import (
    DraftCreated,
    DraftOutlineRepinned,
    DraftReordered,
    OutlineSection,
    SentenceClass,
    SentenceRecorded,
    SentenceWithdrawn,
    SupportKind,
    outline_id_of,
)
from factory.writing.checks import citation_matches, is_single_sentence

ORDER_STEP = 10
"""Sentences are ordered by an integer with gaps, so a later sentence can slot between two."""


@dataclass(frozen=True)
class DraftTables:
    drafts: Table
    sections: Table
    sentences: Table
    supports: Table
    flags: Table
    stats: Table


def draft_tables(metadata: MetaData) -> DraftTables:
    drafts = Table(
        "drafts",
        metadata,
        Column("draft_id", String, primary_key=True),
        Column("title", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("outline_ref", String, nullable=False),
        Column("outline_blob", String, nullable=False),
        Column("creator_session", String, nullable=False),
        Column("creator_kind", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    sections = Table(
        "draft_sections",
        metadata,
        Column("draft_id", String, primary_key=True),
        Column("section_id", String, primary_key=True),
        Column("ord", Integer, nullable=False),
        Column("heading", String, nullable=False),
        Column("outline_section", String),
    )
    sentences = Table(
        "draft_sentences",
        metadata,
        Column("sentence_id", String, primary_key=True),
        Column("draft_id", String, nullable=False),
        Column("section_id", String, nullable=False),
        Column("ord", Integer, nullable=False),
        Column("cls", String, nullable=False),
        Column("text", String, nullable=False),
        Column("author", String, nullable=False),
        Column("session", String, nullable=False),
        Column("model", String),
        Column("task_id", String),
        Column("stats_version", Integer, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("withdrawn", Integer, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_draft_sentences_draft", "draft_id", "section_id", "ord"),
    )
    supports = Table(
        "sentence_supports",
        metadata,
        Column("sentence_id", String, primary_key=True),
        Column("position", Integer, primary_key=True),
        Column("kind", String, nullable=False),
        Column("ref", String, nullable=False),
        Index("ix_sentence_supports_ref", "kind", "ref"),
    )
    flags = Table(
        "sentence_flags",
        metadata,
        Column("sentence_id", String, primary_key=True),
        Column("flag", String, primary_key=True),
    )
    stats = Table(
        "sentence_stats",
        metadata,
        Column("sentence_id", String, primary_key=True),
        Column("stat", String, primary_key=True),
        Column("value", Integer, nullable=False),
    )
    return DraftTables(drafts, sections, sentences, supports, flags, stats)


def draft_handlers(t: DraftTables, blobs: BlobStore | None = None) -> dict[str, Handler]:
    return {
        "draft.created": _total(_created(t, blobs)),
        "draft.outline_repinned": _total(_repinned(t, blobs)),
        "draft.sentence_recorded": _total(_recorded(t)),
        "draft.sentence_withdrawn": _total(_withdrawn(t)),
        "draft.reordered": _total(_reordered(t)),
    }


def _total(handler: Handler) -> Handler:
    """A handler that cannot raise on what a log holds (the log may be edited by hand, and a
    rebuild must still finish)."""

    def total(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (ValueError, ArithmeticError, KeyError, TypeError, AttributeError, IndexError):
            return

    return total


def _writes(event: Event) -> bool:
    return event.actor.kind in ("human", "agent")


def _outline_matches(blobs: BlobStore | None, ref: str, blob: str) -> bool:
    """Whether the blob holds an outline whose scope and sections hash to `ref`. Without a blob
    store the check cannot be made and is skipped."""
    if blobs is None:
        return True
    try:
        data = blobs.get_json(blob)
    except (FactoryError, OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    scope, sections = data.get("scope"), data.get("sections")
    if not isinstance(scope, dict) or not isinstance(sections, list):
        return False
    parsed = [OutlineSection.model_validate(s) for s in sections]
    return outline_id_of(scope, parsed) == ref and data.get("outline_id") == ref


def _created(t: DraftTables, blobs: BlobStore | None) -> Handler:
    def created(conn: Connection, event: Event) -> None:
        p = DraftCreated.model_validate(event.payload)
        if not _writes(event) or not _outline_matches(blobs, p.outline_ref, p.outline_blob):
            return
        if conn.execute(
            select(t.drafts.c.draft_id).where(t.drafts.c.draft_id == p.draft_id)
        ).first():
            return
        conn.execute(
            t.drafts.insert().values(
                draft_id=p.draft_id,
                title=p.title,
                kind=p.kind.value,
                outline_ref=p.outline_ref,
                outline_blob=p.outline_blob,
                creator_session=event.actor.session,
                creator_kind=event.actor.kind,
                event_id=event.id,
            )
        )
        for i, s in enumerate(p.sections):
            conn.execute(
                t.sections.insert().values(
                    draft_id=p.draft_id,
                    section_id=s.section_id,
                    ord=i,
                    heading=s.heading,
                    outline_section=s.outline_section,
                )
            )

    return created


def _repinned(t: DraftTables, blobs: BlobStore | None) -> Handler:
    def repinned(conn: Connection, event: Event) -> None:
        p = DraftOutlineRepinned.model_validate(event.payload)
        if not _writes(event) or not _outline_matches(blobs, p.outline_ref, p.outline_blob):
            return
        conn.execute(
            update(t.drafts)
            .where(t.drafts.c.draft_id == p.draft_id)
            .values(outline_ref=p.outline_ref, outline_blob=p.outline_blob)
        )

    return repinned


def _structural_ok(p: SentenceRecorded) -> bool:
    """The class rules that need nothing but the sentence."""
    kinds = {s.kind for s in p.supports}
    if p.cls is SentenceClass.CLAIM and not p.supports:
        return False
    if p.cls is SentenceClass.SYNTHESIS and not kinds & {SupportKind.STAT, SupportKind.GROUP}:
        return False
    if p.cls in (SentenceClass.STRUCTURAL, SentenceClass.INTERPRETIVE) and numbers_in(p.text):
        return False
    if p.cls is SentenceClass.STRUCTURAL and citation_matches(p.text):
        return False
    return is_single_sentence(p.text)


def _recorded(t: DraftTables) -> Handler:
    def recorded(conn: Connection, event: Event) -> None:
        p = SentenceRecorded.model_validate(event.payload)
        if not _writes(event) or p.author != event.actor.kind or not _structural_ok(p):
            return
        if not conn.execute(
            select(t.sections.c.section_id).where(
                t.sections.c.draft_id == p.draft_id, t.sections.c.section_id == p.section_id
            )
        ).first():
            return
        if conn.execute(
            select(t.sentences.c.sentence_id).where(t.sentences.c.sentence_id == p.sentence_id)
        ).first():
            return
        if p.supersedes is not None:
            old = conn.execute(
                select(t.sentences.c.sentence_id).where(
                    t.sentences.c.sentence_id == p.supersedes,
                    t.sentences.c.draft_id == p.draft_id,
                    t.sentences.c.section_id == p.section_id,
                    t.sentences.c.superseded_by.is_(None),
                    t.sentences.c.withdrawn == 0,
                )
            ).first()
            if old is None:
                return
            conn.execute(
                update(t.sentences)
                .where(t.sentences.c.sentence_id == p.supersedes)
                .values(superseded_by=p.sentence_id)
            )
        conn.execute(
            t.sentences.insert().values(
                sentence_id=p.sentence_id,
                draft_id=p.draft_id,
                section_id=p.section_id,
                ord=p.order,
                cls=p.cls.value,
                text=p.text,
                author=p.author,
                session=event.actor.session,
                model=event.actor.model,
                task_id=p.task_id,
                stats_version=p.stats_version,
                supersedes=p.supersedes,
                superseded_by=None,
                withdrawn=0,
                event_id=event.id,
            )
        )
        for i, s in enumerate(p.supports):
            conn.execute(
                t.supports.insert().values(
                    sentence_id=p.sentence_id, position=i, kind=s.kind.value, ref=s.ref
                )
            )
        for flag in dict.fromkeys(p.flags):
            conn.execute(
                sqlite_insert(t.flags)
                .values(sentence_id=p.sentence_id, flag=flag.value)
                .on_conflict_do_nothing()
            )
        for stat, value in p.stat_values.items():
            conn.execute(t.stats.insert().values(sentence_id=p.sentence_id, stat=stat, value=value))

    return recorded


def _withdrawn(t: DraftTables) -> Handler:
    def withdrawn(conn: Connection, event: Event) -> None:
        p = SentenceWithdrawn.model_validate(event.payload)
        if not _writes(event):
            return
        conn.execute(
            update(t.sentences)
            .where(
                t.sentences.c.sentence_id == p.sentence_id,
                t.sentences.c.superseded_by.is_(None),
                t.sentences.c.withdrawn == 0,
            )
            .values(withdrawn=1)
        )

    return withdrawn


def _reordered(t: DraftTables) -> Handler:
    def reordered(conn: Connection, event: Event) -> None:
        p = DraftReordered.model_validate(event.payload)
        if not _writes(event):
            return
        live = {
            str(r[0])
            for r in conn.execute(
                select(t.sentences.c.sentence_id).where(
                    t.sentences.c.draft_id == p.draft_id,
                    t.sentences.c.section_id == p.section_id,
                    t.sentences.c.superseded_by.is_(None),
                    t.sentences.c.withdrawn == 0,
                )
            )
        }
        if not live or set(p.order) != live:
            return
        for i, sentence_id in enumerate(p.order):
            conn.execute(
                update(t.sentences)
                .where(t.sentences.c.sentence_id == sentence_id)
                .values(ord=(i + 1) * ORDER_STEP)
            )

    return reordered
