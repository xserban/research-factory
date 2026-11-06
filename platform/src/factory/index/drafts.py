"""Projection of drafts, their sections and sentences (slice 7b, plan W-A).

`drafts` keeps one row per draft with the outline it is pinned to; `draft_sections` its sections;
`draft_sentences` every recorded sentence with its author, session and model, `superseded_by` and
`withdrawn`; `sentence_supports`, `sentence_flags` and `sentence_stats` the supports, the stored
flags and the stat values read at write time; `sentence_verdicts` the verdicts, `draft_audits` and
`draft_audit_items` the samples and their labels, `draft_releases` the releases (plan W-B). Status,
staleness and eligibility are computed on read, never stored.

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
- No sentence is folded from a session (or a human) that verified a sentence of the draft.
- A verdict is folded for a live claim or synthesis sentence that has no verdict, from a human or
  an agent of the skill `rf-verify`, who wrote no sentence of the draft, with a model other than
  the writer's in `systematic`, and whose `input_blob` is the unit of that sentence with the
  substrings of ruling 3 in it (`writing.verdicts`).
- An audit sample is folded from the system actor when one is due, for the very verdicts the seed
  draws from the population at that point of the log; a label from a human, for a sampled verdict.
- A release is folded from a human or an agent named in `released_by`, for a draft with live
  sentences that `counts` adds up to, under the `writing.release` policy in force at that point of
  the log and the actor it allows. `counts` has only status keys and no negative value, and its
  unchecked and flagged figures are those the verdicts and audit labels give, less what `stale`
  may have taken. Outside `exploratory` no draw may be due and every verdict of the latest draw,
  live or not, must be labelled, and `counts` show no stale sentence; in `systematic` the actor is
  the human reviewer of record, `counts` show nothing flagged or unchecked, and the labels of that
  draw are under the ceiling.
  Whether a sentence is really stale is computed on read and cannot be known here, so a release
  that claims no stale sentence is taken at its word on that one count.
- A withdrawal is folded for a live sentence; a reorder only when `order` is a permutation of the
  section's live sentences.

Handlers are total: an event naming an unknown draft or sentence changes nothing, never raises.
Rows are first-write-wins per id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Actor, Event
from factory.extraction.numbers import numbers_in
from factory.index.hypotheses import policy_of
from factory.index.projection import Handler
from factory.model.drafts import (
    DRAFT_AUDIT_FRACTION,
    DRAFT_AUDIT_MINIMUM,
    DRAFT_VERIFY_ERROR_CEILING,
    SENTENCE_STATUSES,
    AuditLabel,
    DraftAuditDrawn,
    DraftAudited,
    DraftCreated,
    DraftOutlineRepinned,
    DraftReleased,
    DraftReordered,
    OutlineSection,
    SentenceClass,
    SentenceRecorded,
    SentenceVerified,
    SentenceWithdrawn,
    SupportKind,
    Verdict,
    outline_id_of,
)
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolSpec, ReviewerRole
from factory.modules.contract import PolicyKind
from factory.quality.stats import audit_size, draw_uniform
from factory.writing.checks import citation_matches, is_single_sentence
from factory.writing.verdicts import verdict_issues

ORDER_STEP = 10
"""Sentences are ordered by an integer with gaps, so a later sentence can slot between two."""
VERIFY_SKILL = "rf-verify@"
"""An agent's verdict is written under this skill (plan W-B, Global Constraints)."""
CLAIM_BEARING = (SentenceClass.CLAIM.value, SentenceClass.SYNTHESIS.value)
RELEASE_GATE = "writing.release"


@dataclass(frozen=True)
class DraftTables:
    drafts: Table
    sections: Table
    sentences: Table
    supports: Table
    flags: Table
    stats: Table
    verdicts: Table
    audits: Table
    audit_items: Table
    releases: Table
    protocols: Table
    project: Table


def draft_tables(metadata: MetaData, protocols: Table, project: Table) -> DraftTables:
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
    verdicts = Table(
        "sentence_verdicts",
        metadata,
        Column("verdict_id", String, primary_key=True),
        Column("sentence_id", String, nullable=False),
        Column("draft_id", String, nullable=False),
        Column("verdict", String, nullable=False),
        Column("session", String, nullable=False),
        Column("model", String),
        Column("event_id", String, nullable=False),
        Index("ix_sentence_verdicts_sentence", "sentence_id"),
        Index("ix_sentence_verdicts_draft", "draft_id"),
    )
    audits = Table(
        "draft_audits",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("draft_id", String, nullable=False),
        Column("seed", Integer, nullable=False),
        Column("population", Integer, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_draft_audits_draft", "draft_id"),
    )
    audit_items = Table(
        "draft_audit_items",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("verdict_id", String, primary_key=True),
        Column("label", String),
        Column("channel", String),
        Column("event_id", String),
    )
    releases = Table(
        "draft_releases",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("draft_id", String, nullable=False),
        Column("as_of", String, nullable=False),
        Column("policy", String, nullable=False),
        Column("released_by", String, nullable=False),
        Column("actor_kind", String, nullable=False),
        Column("counts", String, nullable=False),
        Index("ix_draft_releases_draft", "draft_id"),
    )
    return DraftTables(
        drafts,
        sections,
        sentences,
        supports,
        flags,
        stats,
        verdicts,
        audits,
        audit_items,
        releases,
        protocols,
        project,
    )


def draft_handlers(t: DraftTables, blobs: BlobStore | None = None) -> dict[str, Handler]:
    return {
        "draft.created": _total(_created(t, blobs)),
        "draft.outline_repinned": _total(_repinned(t, blobs)),
        "draft.sentence_recorded": _total(_recorded(t)),
        "draft.sentence_withdrawn": _total(_withdrawn(t)),
        "draft.reordered": _total(_reordered(t)),
        "draft.verified": _total(_verified(t, blobs)),
        "draft.audit_drawn": _total(_audit_drawn(t)),
        "draft.audited": _total(_audited(t)),
        "draft.released": _total(_released(t)),
    }


def _total(handler: Handler) -> Handler:
    """A handler that cannot raise on what a log holds (the log may be edited by hand, and a
    rebuild must still finish) and folds all of an event or nothing: its writes run in a savepoint
    of the transaction the index holds, so a failure half way leaves no partial fold."""

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


def identities(actor: Actor) -> frozenset[str]:
    """What identifies the person or session behind an act: the session and, as a human's sessions
    change with each command, the human's id."""
    if actor.kind == "human":
        return frozenset({actor.session, f"human:{actor.id}"})
    return frozenset({actor.session})


def _acted(conn: Connection, table: str, draft_id: str) -> frozenset[str]:
    rows = conn.execute(
        text(
            "SELECT t.session, e.actor_kind, e.actor_id "
            f"FROM {table} t JOIN events e ON e.id = t.event_id WHERE t.draft_id = :d"
        ),
        {"d": draft_id},
    ).all()
    return frozenset(
        {str(r[0]) for r in rows} | {f"human:{r[2]}" for r in rows if str(r[1]) == "human"}
    )


def writers_of(conn: Connection, draft_id: str) -> frozenset[str]:
    """The `identities` of everyone who recorded a sentence of the draft, superseded or not."""
    return _acted(conn, "draft_sentences", draft_id)


def verifiers_of(conn: Connection, draft_id: str) -> frozenset[str]:
    """The `identities` of everyone with a verdict on a sentence of the draft."""
    return _acted(conn, "sentence_verdicts", draft_id)


_SUPPORTED_LIVE = (
    "FROM sentence_verdicts v JOIN draft_sentences s ON s.sentence_id = v.sentence_id "
    "WHERE v.draft_id = :d AND v.verdict = :supported "
    "AND s.superseded_by IS NULL AND s.withdrawn = 0"
)


def audit_population(conn: Connection, draft_id: str) -> list[str]:
    """The `supported` verdicts of the draft's live sentences no sample has drawn, sorted."""
    rows = conn.execute(
        text(
            f"SELECT v.verdict_id {_SUPPORTED_LIVE} AND v.verdict_id NOT IN "
            "(SELECT verdict_id FROM draft_audit_items) ORDER BY v.verdict_id"
        ),
        {"d": draft_id, "supported": Verdict.SUPPORTED.value},
    ).all()
    return [str(r[0]) for r in rows]


def audit_due(conn: Connection, draft_id: str) -> bool:
    """Whether a new draw is due: a live `supported` verdict is newer than the last draw (any such
    verdict when none was drawn), or no verdict of the last draw is live while a verdict waits, so
    that nobody is trapped behind a sample whose sentences are all gone."""
    last = conn.execute(
        text("SELECT MAX(event_id) FROM draft_audits WHERE draft_id = :d"), {"d": draft_id}
    ).scalar()
    newest = conn.execute(
        text(f"SELECT MAX(v.event_id) {_SUPPORTED_LIVE}"),
        {"d": draft_id, "supported": Verdict.SUPPORTED.value},
    ).scalar()
    if newest is not None and (last is None or str(newest) > str(last)):
        return True
    if last is None:
        return False
    alive = conn.execute(
        text(
            "SELECT 1 FROM draft_audit_items i JOIN draft_audits a ON a.audit_id = i.audit_id "
            "JOIN sentence_verdicts v ON v.verdict_id = i.verdict_id "
            "JOIN draft_sentences s ON s.sentence_id = v.sentence_id "
            "WHERE a.event_id = :e AND s.superseded_by IS NULL AND s.withdrawn = 0 LIMIT 1"
        ),
        {"e": str(last)},
    ).first()
    return alive is None and bool(audit_population(conn, draft_id))


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
        if identities(event.actor) & verifiers_of(conn, p.draft_id):
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


def _mode(conn: Connection, t: DraftTables) -> RigorMode:
    row = conn.execute(select(t.project.c.rigor_mode).limit(1)).first()
    return RigorMode(str(row[0])) if row else RigorMode.PILOT


def _unit_spans(
    blobs: BlobStore, event: Event, sentence_id: str, sentence: str
) -> dict[str, list[str]] | None:
    """The spans by support of the unit the verdict names as its input; None when the event names
    no unit of this sentence."""
    if event.input_blob is None:
        return None
    try:
        unit = blobs.get_json(event.input_blob)
    except (FactoryError, OSError, ValueError):
        return None
    if not isinstance(unit, dict):
        return None
    if unit.get("sentence_id") != sentence_id or unit.get("text") != sentence:
        return None
    supports = unit.get("supports")
    if not isinstance(supports, list):
        return None
    spans: dict[str, list[str]] = {}
    for support in supports:
        if not isinstance(support, dict):
            continue
        ref, said = support.get("ref"), support.get("spans")
        if isinstance(ref, str) and isinstance(said, list):
            spans[ref] = [str(s) for s in said]
    return spans


def _verified(t: DraftTables, blobs: BlobStore | None) -> Handler:
    def verified(conn: Connection, event: Event) -> None:
        p = SentenceVerified.model_validate(event.payload)
        if not _writes(event):
            return
        if event.actor.kind == "agent" and not str(event.actor.skill).startswith(VERIFY_SKILL):
            return
        sentence = conn.execute(
            select(
                t.sentences.c.draft_id,
                t.sentences.c.cls,
                t.sentences.c.text,
                t.sentences.c.model,
            ).where(
                t.sentences.c.sentence_id == p.sentence_id,
                t.sentences.c.superseded_by.is_(None),
                t.sentences.c.withdrawn == 0,
            )
        ).first()
        if sentence is None or sentence[1] not in CLAIM_BEARING:
            return
        draft_id, body, model = str(sentence[0]), str(sentence[2]), sentence[3]
        if conn.execute(
            select(t.verdicts.c.verdict_id).where(
                (t.verdicts.c.sentence_id == p.sentence_id)
                | (t.verdicts.c.verdict_id == p.verdict_id)
            )
        ).first():
            return
        if identities(event.actor) & writers_of(conn, draft_id):
            return
        if (
            _mode(conn, t) is RigorMode.SYSTEMATIC
            and model is not None
            and model == event.actor.model
        ):
            return
        # Without a blob store (a bare projection) the unit cannot be read: the sentence's own
        # rules are still checked, a substring against itself.
        spans = (
            {s.ref: [s.substring] for s in p.support_spans}
            if blobs is None
            else _unit_spans(blobs, event, p.sentence_id, body)
        )
        if spans is None or verdict_issues(
            p.verdict, p.sentence_span, p.support_spans, sentence=body, spans_by_ref=spans
        ):
            return
        conn.execute(
            t.verdicts.insert().values(
                verdict_id=p.verdict_id,
                sentence_id=p.sentence_id,
                draft_id=draft_id,
                verdict=p.verdict.value,
                session=event.actor.session,
                model=event.actor.model,
                event_id=event.id,
            )
        )

    return verified


def _audit_drawn(t: DraftTables) -> Handler:
    def drawn(conn: Connection, event: Event) -> None:
        p = DraftAuditDrawn.model_validate(event.payload)
        if event.actor.kind != "system" or not audit_due(conn, p.draft_id):
            return
        if conn.execute(
            select(t.audits.c.audit_id).where(t.audits.c.audit_id == p.audit_id)
        ).first():
            return
        population = audit_population(conn, p.draft_id)
        size = audit_size(len(population), DRAFT_AUDIT_FRACTION, DRAFT_AUDIT_MINIMUM)
        if p.population != len(population) or p.verdict_ids != draw_uniform(
            population, size, p.seed, key=str
        ):
            return
        conn.execute(
            t.audits.insert().values(
                audit_id=p.audit_id,
                draft_id=p.draft_id,
                seed=p.seed,
                population=p.population,
                event_id=event.id,
            )
        )
        for verdict_id in p.verdict_ids:
            conn.execute(t.audit_items.insert().values(audit_id=p.audit_id, verdict_id=verdict_id))

    return drawn


def _audited(t: DraftTables) -> Handler:
    def audited(conn: Connection, event: Event) -> None:
        p = DraftAudited.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        conn.execute(
            update(t.audit_items)
            .where(
                t.audit_items.c.audit_id == p.audit_id,
                t.audit_items.c.verdict_id == p.verdict_id,
            )
            .values(label=p.label.value, channel=p.channel.value, event_id=event.id)
        )

    return audited


def audit_labels(conn: Connection, draft_id: str, *, latest: bool = False) -> list[str | None]:
    """The label of each sampled verdict of the draft, None when unlabelled; with `latest`, only of
    the latest draw, its sentences live or not, which is what the release gate reads: a sentence
    leaves the rate through a new draw of its revision, never by being withdrawn."""
    where = (
        " AND a.event_id = (SELECT MAX(event_id) FROM draft_audits WHERE draft_id = :d)"
        if latest
        else ""
    )
    rows = conn.execute(
        text(
            "SELECT i.label FROM draft_audit_items i JOIN draft_audits a "
            f"ON a.audit_id = i.audit_id WHERE a.draft_id = :d{where}"
        ),
        {"d": draft_id},
    ).all()
    return [None if r[0] is None else str(r[0]) for r in rows]


def _is_reviewer_of_record(conn: Connection, t: DraftTables, actor: Actor) -> bool:
    row = conn.execute(
        select(t.protocols.c.spec).order_by(t.protocols.c.event_id.desc()).limit(1)
    ).first()
    if row is None or actor.kind != "human":
        return False
    reviewers = ProtocolSpec.model_validate_json(str(row[0])).screening.reviewers
    return any(r.role is ReviewerRole.REVIEWER_OF_RECORD and r.actor == actor.id for r in reviewers)


def _open_counts(conn: Connection, draft_id: str) -> dict[str, int]:
    """The unchecked and flagged sentences the verdicts and audit labels give, before staleness:
    a live claim-bearing sentence with no verdict, and one whose verdict is not `supported` or
    whose latest label is `incorrect`."""
    rows = conn.execute(
        text(
            "SELECT v.verdict, EXISTS (SELECT 1 FROM draft_audit_items i "
            "WHERE i.verdict_id = v.verdict_id AND i.label = :wrong) "
            "FROM draft_sentences s LEFT JOIN sentence_verdicts v "
            "ON v.sentence_id = s.sentence_id WHERE s.draft_id = :d "
            "AND s.superseded_by IS NULL AND s.withdrawn = 0 AND s.cls IN (:claim, :synthesis)"
        ),
        {
            "d": draft_id,
            "wrong": AuditLabel.INCORRECT.value,
            "claim": CLAIM_BEARING[0],
            "synthesis": CLAIM_BEARING[1],
        },
    ).all()
    unchecked = sum(1 for r in rows if r[0] is None)
    flagged = sum(1 for r in rows if r[0] is not None and (r[0] != Verdict.SUPPORTED.value or r[1]))
    return {"unchecked": unchecked, "flagged": flagged}


def _counts_hold(conn: Connection, p: DraftReleased) -> bool:
    """Whether `counts` can be what the service read. A stale sentence leaves the count it would
    otherwise be in, which cannot be known here, so with no stale sentence the figures are exact."""
    if set(p.counts) - set(SENTENCE_STATUSES) or min(p.counts.values(), default=0) < 0:
        return False
    stale = p.counts.get("stale", 0)
    return all(
        known - stale <= p.counts.get(status, 0) <= known
        for status, known in _open_counts(conn, p.draft_id).items()
    )


def _release_holds(conn: Connection, t: DraftTables, event: Event, p: DraftReleased) -> bool:
    """What a release must satisfy that the log alone can tell (see the module docstring)."""
    if not _counts_hold(conn, p):
        return False
    live = conn.execute(
        text(
            "SELECT COUNT(*) FROM draft_sentences WHERE draft_id = :d "
            "AND superseded_by IS NULL AND withdrawn = 0"
        ),
        {"d": p.draft_id},
    ).scalar_one()
    if not live or sum(p.counts.values()) != live or not p.as_of < event.id:
        return False
    policy = policy_of(conn, t.protocols, t.project, RELEASE_GATE)
    if p.policy is not policy or (policy is PolicyKind.HUMAN and event.actor.kind != "human"):
        return False
    mode = _mode(conn, t)
    if mode is RigorMode.EXPLORATORY:
        return True
    labels = audit_labels(conn, p.draft_id, latest=True)
    if not labels or None in labels or audit_due(conn, p.draft_id) or p.counts.get("stale", 0):
        return False
    if mode is RigorMode.PILOT:
        return True
    wrong = sum(1 for x in labels if x == AuditLabel.INCORRECT.value)
    return (
        _is_reviewer_of_record(conn, t, event.actor)
        and not p.counts.get("flagged", 0)
        and not p.counts.get("unchecked", 0)
        and wrong / len(labels) <= DRAFT_VERIFY_ERROR_CEILING
    )


def _released(t: DraftTables) -> Handler:
    def released(conn: Connection, event: Event) -> None:
        p = DraftReleased.model_validate(event.payload)
        if not _writes(event) or p.released_by != event.actor.id:
            return
        if not _release_holds(conn, t, event, p):
            return
        conn.execute(
            t.releases.insert().values(
                event_id=event.id,
                draft_id=p.draft_id,
                as_of=p.as_of,
                policy=p.policy.value,
                released_by=p.released_by,
                actor_kind=event.actor.kind,
                counts=json.dumps(p.counts, sort_keys=True),
            )
        )

    return released


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
