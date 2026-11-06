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
  resolved work it names, and no verdict stands on the unit.
- A verdict is folded from an agent of the skill `rf-verify`, for a unit that is live at that point
  of the log and has no verdict, with a span inside the sentence and a conversion of the cited
  work, when its `input_blob` is that unit. Whether the quote is in the conversion cannot be known
  here: the conversion is in the library, which a rebuild may not have. The service checks it.
- A flag is folded likewise, for an uncited sentence with no flag.
- An audit sample is folded from the system when one is due, for the very verdicts the seed draws
  from the population at that point of the log; a label from a human, for a sampled verdict.

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
from factory.index.drafts import VERIFY_SKILL
from factory.index.projection import Handler
from factory.model.drafts import DRAFT_AUDIT_FRACTION, DRAFT_AUDIT_MINIMUM, Verdict
from factory.model.manuscripts import (
    CitationDecided,
    CitationDecision,
    CitationMethod,
    CitationResolved,
    CitationState,
    CloseReason,
    ManuscriptAdded,
    ManuscriptAuditDrawn,
    ManuscriptAudited,
    ManuscriptSegmented,
    ManuscriptVerified,
    UnitClosed,
)
from factory.quality.stats import audit_size, draw_uniform


@dataclass(frozen=True)
class ManuscriptTables:
    manuscripts: Table
    sentences: Table
    citations: Table
    closures: Table
    verdicts: Table
    flags: Table
    audits: Table
    audit_items: Table


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
    verdicts = Table(
        "manuscript_verdicts",
        metadata,
        Column("verdict_id", String, primary_key=True),
        Column("manuscript_id", String, nullable=False),
        Column("ordinal", Integer, nullable=False),
        Column("work_id", String, nullable=False),
        Column("verdict", String, nullable=False),
        Column("span_start", Integer),
        Column("span_end", Integer),
        Column("anchor", String),
        Column("quote", String),
        Column("conversion_id", String, nullable=False),
        Column("note", String),
        Column("session", String, nullable=False),
        Column("model", String),
        Column("event_id", String, nullable=False),
        Index("ix_manuscript_verdicts_unit", "manuscript_id", "ordinal", "work_id", unique=True),
    )
    flags = Table(
        "manuscript_flags",
        metadata,
        Column("manuscript_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("verdict_id", String, nullable=False),
        Column("note", String),
        Column("session", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    audits = Table(
        "manuscript_audits",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("manuscript_id", String, nullable=False),
        Column("seed", Integer, nullable=False),
        Column("population", Integer, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_manuscript_audits_manuscript", "manuscript_id"),
    )
    audit_items = Table(
        "manuscript_audit_items",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("verdict_id", String, primary_key=True),
        Column("label", String),
        Column("channel", String),
        Column("event_id", String),
    )
    return ManuscriptTables(
        manuscripts, sentences, citations, closures, verdicts, flags, audits, audit_items
    )


def manuscript_handlers(t: ManuscriptTables, blobs: BlobStore | None = None) -> dict[str, Handler]:
    return {
        "manuscript.added": _total(_added(t)),
        "manuscript.segmented": _total(_segmented(t)),
        "manuscript.citation_resolved": _total(_citation_resolved(t)),
        "manuscript.citation_decided": _total(_citation_decided(t)),
        "manuscript.unit_closed": _total(_unit_closed(t)),
        "manuscript.verified": _total(_verified(t, blobs)),
        "manuscript.audit_drawn": _total(_audit_drawn(t)),
        "manuscript.audited": _total(_audited(t)),
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


def _has_verdict(
    t: ManuscriptTables, conn: Connection, manuscript_id: str, ordinal: int, work_id: str
) -> bool:
    c = t.verdicts.c
    found = select(c.verdict_id).where(
        c.manuscript_id == manuscript_id, c.ordinal == ordinal, c.work_id == work_id
    )
    return conn.execute(found).first() is not None


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
        if p.work_id is not None and _has_verdict(t, conn, p.manuscript_id, p.ordinal, p.work_id):
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


def _names_unit(blobs: BlobStore | None, event: Event, p: ManuscriptVerified) -> bool:
    """Whether the event's `input_blob` is the unit the payload names. Without a blob store (a bare
    projection) the check cannot be made and is skipped."""
    if blobs is None:
        return True
    if event.input_blob is None:
        return False
    try:
        unit = blobs.get_json(event.input_blob)
    except (FactoryError, OSError, ValueError):
        return False
    if not isinstance(unit, dict):
        return False
    return (
        unit.get("manuscript_id") == p.manuscript_id
        and unit.get("ordinal") == p.ordinal
        and unit.get("work_id") == p.work_id
        and unit.get("conversion_id") == p.conversion_id
    )


def _held_task(conn: Connection, event: Event) -> bool:
    """Whether the event's `input_blob` is the content of a task its actor's session holds. The
    service writes a verdict before the task completes, so every service verdict passes."""
    return (
        conn.execute(
            sql(
                "SELECT 1 FROM tasks WHERE content_blob = :b AND status = 'claimed' "
                "AND claim_session = :s"
            ),
            {"b": event.input_blob, "s": event.actor.session},
        ).first()
        is not None
    )


def _unit_is_live(
    t: ManuscriptTables, conn: Connection, p: ManuscriptVerified, keys: list[str]
) -> bool:
    """Whether a key of the sentence resolves to the work and no closure stands on it."""
    assert p.work_id is not None
    for key in keys:
        row = _citation(t, conn, p.manuscript_id, key)
        if row is None or row[:2] != (CitationState.RESOLVED.value, p.work_id):
            continue
        c = t.closures.c
        closed = select(c.reason).where(
            c.manuscript_id == p.manuscript_id, c.ordinal == p.ordinal, c.key == key
        )
        if conn.execute(closed).first() is None:
            return True
    return False


def _converts(conn: Connection, conversion_id: str | None, work_id: str | None) -> bool:
    return (
        conn.execute(
            sql(
                "SELECT 1 FROM document_conversions c JOIN fulltext_documents d "
                "ON d.document_id = c.document_id WHERE c.conversion_id = :c AND d.work_id = :w"
            ),
            {"c": conversion_id, "w": work_id},
        ).first()
        is not None
    )


def _id_is_fresh(t: ManuscriptTables, conn: Connection, verdict_id: str) -> bool:
    return (
        conn.execute(
            select(t.verdicts.c.verdict_id).where(t.verdicts.c.verdict_id == verdict_id)
        ).first()
        is None
        and conn.execute(
            select(t.flags.c.verdict_id).where(t.flags.c.verdict_id == verdict_id)
        ).first()
        is None
    )


def _fold_flag(t: ManuscriptTables, conn: Connection, event: Event, p: ManuscriptVerified) -> None:
    c = t.flags.c
    known = select(c.ordinal).where(c.manuscript_id == p.manuscript_id, c.ordinal == p.ordinal)
    if conn.execute(known).first():
        return
    conn.execute(
        t.flags.insert().values(
            manuscript_id=p.manuscript_id,
            ordinal=p.ordinal,
            verdict_id=p.verdict_id,
            note=p.note,
            session=event.actor.session,
            event_id=event.id,
        )
    )


def _verified(t: ManuscriptTables, blobs: BlobStore | None) -> Handler:
    def verified(conn: Connection, event: Event) -> None:
        p = ManuscriptVerified.model_validate(event.payload)
        if event.actor.kind != "agent" or not str(event.actor.skill).startswith(VERIFY_SKILL):
            return
        s = t.sentences.c
        sentence = conn.execute(
            select(s.char_start, s.char_end, s["keys"]).where(
                s.manuscript_id == p.manuscript_id, s.ordinal == p.ordinal
            )
        ).first()
        if sentence is None or not _id_is_fresh(t, conn, p.verdict_id):
            return
        if not _names_unit(blobs, event, p):
            return
        keys = [str(k) for k in json.loads(str(sentence[2]))]
        if p.uncited_flag:
            if not keys:
                _fold_flag(t, conn, event, p)
            return
        if p.work_id is None or p.verdict is None:
            return
        if blobs is not None and not _held_task(conn, event):
            return
        length = int(sentence[1]) - int(sentence[0])
        if p.sentence_span is not None and p.sentence_span[1] > length:
            return
        if not _unit_is_live(t, conn, p, keys) or not _converts(conn, p.conversion_id, p.work_id):
            return
        if _has_verdict(t, conn, p.manuscript_id, p.ordinal, p.work_id):
            return
        span = (None, None) if p.sentence_span is None else p.sentence_span
        conn.execute(
            t.verdicts.insert().values(
                verdict_id=p.verdict_id,
                manuscript_id=p.manuscript_id,
                ordinal=p.ordinal,
                work_id=p.work_id,
                verdict=p.verdict.value,
                span_start=span[0],
                span_end=span[1],
                anchor=p.anchor,
                quote=p.quote,
                conversion_id=p.conversion_id,
                note=p.note,
                session=event.actor.session,
                model=event.actor.model,
                event_id=event.id,
            )
        )

    return verified


def audit_population(conn: Connection, manuscript_id: str) -> list[str]:
    """The `supported` verdicts of the manuscript no sample has drawn, sorted."""
    rows = conn.execute(
        sql(
            "SELECT verdict_id FROM manuscript_verdicts WHERE manuscript_id = :m "
            "AND verdict = :supported AND verdict_id NOT IN "
            "(SELECT verdict_id FROM manuscript_audit_items) ORDER BY verdict_id"
        ),
        {"m": manuscript_id, "supported": Verdict.SUPPORTED.value},
    ).all()
    return [str(r[0]) for r in rows]


def audit_due(conn: Connection, manuscript_id: str) -> bool:
    """Whether a `supported` verdict is newer than the last draw (any such when none was drawn)."""
    last = conn.execute(
        sql("SELECT MAX(event_id) FROM manuscript_audits WHERE manuscript_id = :m"),
        {"m": manuscript_id},
    ).scalar()
    newest = conn.execute(
        sql(
            "SELECT MAX(event_id) FROM manuscript_verdicts "
            "WHERE manuscript_id = :m AND verdict = :supported"
        ),
        {"m": manuscript_id, "supported": Verdict.SUPPORTED.value},
    ).scalar()
    return newest is not None and (last is None or str(newest) > str(last))


def _audit_drawn(t: ManuscriptTables) -> Handler:
    def drawn(conn: Connection, event: Event) -> None:
        p = ManuscriptAuditDrawn.model_validate(event.payload)
        if event.actor.kind != "system" or not audit_due(conn, p.manuscript_id):
            return
        known = select(t.audits.c.audit_id).where(t.audits.c.audit_id == p.audit_id)
        if conn.execute(known).first():
            return
        population = audit_population(conn, p.manuscript_id)
        size = audit_size(len(population), DRAFT_AUDIT_FRACTION, DRAFT_AUDIT_MINIMUM)
        if p.population != len(population) or p.verdict_ids != draw_uniform(
            population, size, p.seed, key=str
        ):
            return
        conn.execute(
            t.audits.insert().values(
                audit_id=p.audit_id,
                manuscript_id=p.manuscript_id,
                seed=p.seed,
                population=p.population,
                event_id=event.id,
            )
        )
        for verdict_id in p.verdict_ids:
            conn.execute(t.audit_items.insert().values(audit_id=p.audit_id, verdict_id=verdict_id))

    return drawn


def _audited(t: ManuscriptTables) -> Handler:
    def audited(conn: Connection, event: Event) -> None:
        p = ManuscriptAudited.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        c = t.audit_items.c
        conn.execute(
            update(t.audit_items)
            .where(c.audit_id == p.audit_id, c.verdict_id == p.verdict_id)
            .values(label=p.label.value, channel=p.channel.value, event_id=event.id)
        )

    return audited
