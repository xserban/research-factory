"""Projection of the property vocabulary, cards and their assertions (slice 6, plan H-A).

`properties` keeps every definition ever proposed, one row per proposal event. `state` is
`proposed` until a human decides: `approved`, or `rejected`. Approving a definition of a key makes
the key's earlier approved definition `superseded`; a human rejection with no proposal pending
withdraws the key's live approved definition. `decision_event_id` is the deciding event, which
is how a service sees that a definition changed after an assertion was made.
`property_merges` keeps every merge and unmerge of a key; the latest one per `from_key` governs.

`card_assertions` keeps every assertion with `superseded_by` (NULL while live) and the latest human
decision. `card_props` is the matching projection: one row per value (a set contributes one per
member) of each live assertion; a superseded assertion leaves it, a human decision sets its
`status` (`confirmed` or `rejected`).

Only a decision, merge or unmerge whose actor is a human is folded (defence in depth: no service
writes one for another actor, R-51). Handlers are total: an event naming an unknown key or
assertion changes nothing, never raises. Cards and assertions are first-write-wins per id.
Staleness is not stored: it depends on the extraction ledger, the library and the vocabulary,
which change without an assertion event, so services compute it on read.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, and_, delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.cards import (
    AssertionDecided,
    BasisKind,
    CardAsserted,
    CardCreated,
    CardImported,
    PropertyDecided,
    PropertyMerged,
    PropertyProposed,
    PropertyUnmerged,
)

MERGED = "merged"
UNMERGED = "unmerged"


@dataclass(frozen=True)
class CardTables:
    properties: Table
    merges: Table
    cards: Table
    assertions: Table
    props: Table


def card_tables(metadata: MetaData) -> CardTables:
    properties = Table(
        "properties",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("key", String, nullable=False),
        Column("definition_json", String, nullable=False),
        Column("state", String, nullable=False),
        Column("supersedes", String),
        Column("decision_event_id", String),
        Index("ix_properties_key", "key"),
    )
    merges = Table(
        "property_merges",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("from_key", String, nullable=False),
        Column("into_key", String, nullable=False),
        Index("ix_property_merges_from", "from_key"),
    )
    cards = Table(
        "cards",
        metadata,
        Column("card_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("subject", String, nullable=False),
        Column("owner", String, nullable=False),
        Column("imported_from", String),
        Column("event_id", String, nullable=False),
        Index("ix_cards_subject", "kind", "subject"),
    )
    assertions = Table(
        "card_assertions",
        metadata,
        Column("assertion_id", String, primary_key=True),
        Column("card_id", String, nullable=False),
        Column("property", String, nullable=False),
        Column("value_json", String, nullable=False),
        Column("unit", String),
        Column("canonical", String),
        Column("basis_kind", String, nullable=False),
        Column("basis_json", String),
        Column("status", String, nullable=False),
        Column("vocabulary_version", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("folded", Integer, nullable=False),
        Column("decision", String),
        Column("decision_event_id", String),
        Column("event_id", String, nullable=False),
        Index("ix_card_assertions_card", "card_id", "property"),
    )
    props = Table(
        "card_props",
        metadata,
        Column("assertion_id", String, primary_key=True),
        Column("value_norm", String, primary_key=True),
        Column("card_id", String, nullable=False),
        Column("property_key", String, nullable=False),
        Column("number_canonical", String),
        Column("status", String, nullable=False),
        Index("ix_card_props_key", "property_key", "value_norm"),
        Index("ix_card_props_card", "card_id"),
    )
    return CardTables(properties, merges, cards, assertions, props)


def card_handlers(t: CardTables) -> dict[str, Handler]:
    return {
        "vocabulary.property_proposed": _proposed(t),
        "vocabulary.property_decided": _decided(t),
        "vocabulary.property_merged": _merge_handler(t, MERGED),
        "vocabulary.property_unmerged": _merge_handler(t, UNMERGED),
        "card.created": _card_created(t),
        "card.asserted": _asserted(t),
        "card.assertion_decided": _assertion_decided(t),
        "card.imported": _imported(t),
    }


def value_norms(payload: CardAsserted) -> list[str]:
    """The normalised values an assertion contributes to `card_props`, sorted and unique: each
    member of a set, `true` / `false` for a bool, a number's canonical value, else the value."""
    value = payload.value
    if isinstance(value, bool):
        return ["true" if value else "false"]
    if isinstance(value, tuple):
        return sorted(set(value))
    return [payload.canonical if payload.canonical is not None else value]


def _proposed(t: CardTables) -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = PropertyProposed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.properties)
            .values(
                event_id=event.id,
                key=p.definition.key,
                definition_json=canonical_json(p.definition.model_dump(mode="json")).decode(),
                state="proposed",
                supersedes=p.supersedes,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return proposed


def _latest(conn: Connection, t: CardTables, key: str, state: str) -> str | None:
    row = conn.execute(
        select(t.properties.c.event_id)
        .where(and_(t.properties.c.key == key, t.properties.c.state == state))
        .order_by(t.properties.c.event_id.desc())
        .limit(1)
    ).first()
    return None if row is None else str(row[0])


def _decided(t: CardTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = PropertyDecided.model_validate(event.payload)
        pending = _latest(conn, t, p.key, "proposed")
        if p.decision == "approve":
            if pending is None:
                return
            conn.execute(
                update(t.properties)
                .where(and_(t.properties.c.key == p.key, t.properties.c.state == "approved"))
                .values(state="superseded")
            )
            conn.execute(
                update(t.properties)
                .where(t.properties.c.event_id == pending)
                .values(state="approved", decision_event_id=event.id)
            )
            return
        target = pending if pending is not None else _latest(conn, t, p.key, "approved")
        if target is not None:
            conn.execute(
                update(t.properties)
                .where(t.properties.c.event_id == target)
                .values(state="rejected", decision_event_id=event.id)
            )

    return decided


def _merge_handler(t: CardTables, kind: str) -> Handler:
    def merged(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = (PropertyMerged if kind == MERGED else PropertyUnmerged).model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.merges)
            .values(event_id=event.id, kind=kind, from_key=p.from_key, into_key=p.into)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return merged


def _card_created(t: CardTables) -> Handler:
    def created(conn: Connection, event: Event) -> None:
        p = CardCreated.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.cards)
            .values(
                card_id=p.card_id,
                kind=p.kind,
                subject=p.subject,
                owner=p.owner,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["card_id"])
        )

    return created


def _asserted(t: CardTables) -> Handler:
    def asserted(conn: Connection, event: Event) -> None:
        p = CardAsserted.model_validate(event.payload)
        # Only a human states a property as the researcher (the service refuses the rest): a
        # hand-written agent event claiming it is kept, visibly unfolded, and changes nothing else.
        folded = not (p.basis_kind is BasisKind.RESEARCHER and event.actor.kind != "human")
        inserted = conn.execute(
            sqlite_insert(t.assertions)
            .values(
                assertion_id=p.assertion_id,
                card_id=p.card_id,
                property=p.property,
                value_json=canonical_json(
                    p.value if not isinstance(p.value, tuple) else list(p.value)
                ).decode(),
                unit=p.unit,
                canonical=p.canonical,
                basis_kind=p.basis_kind.value,
                basis_json=None
                if p.basis is None
                else canonical_json(p.basis.model_dump(mode="json")).decode(),
                status=p.status,
                vocabulary_version=p.vocabulary_version,
                supersedes=p.supersedes,
                folded=int(folded),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["assertion_id"])
        )
        if not inserted.rowcount or not folded:
            return
        for norm in value_norms(p):
            conn.execute(
                sqlite_insert(t.props)
                .values(
                    assertion_id=p.assertion_id,
                    value_norm=norm,
                    card_id=p.card_id,
                    property_key=p.property,
                    number_canonical=p.canonical,
                    status=p.status,
                )
                .on_conflict_do_nothing(index_elements=["assertion_id", "value_norm"])
            )
        if p.supersedes is not None:
            conn.execute(
                update(t.assertions)
                .where(
                    and_(
                        t.assertions.c.assertion_id == p.supersedes,
                        t.assertions.c.superseded_by.is_(None),
                    )
                )
                .values(superseded_by=p.assertion_id)
            )
            conn.execute(delete(t.props).where(t.props.c.assertion_id == p.supersedes))

    return asserted


def _assertion_decided(t: CardTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = AssertionDecided.model_validate(event.payload)
        conn.execute(
            update(t.assertions)
            .where(t.assertions.c.assertion_id == p.assertion_id)
            .values(decision=p.decision, decision_event_id=event.id)
        )
        conn.execute(
            update(t.props)
            .where(t.props.c.assertion_id == p.assertion_id)
            .values(status="confirmed" if p.decision == "confirm" else "rejected")
        )

    return decided


def _imported(t: CardTables) -> Handler:
    """`card.imported` marks a card as imported from another project. Only a human's folds, and
    only onto a card that exists and carries no mark yet."""

    def imported(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = CardImported.model_validate(event.payload)
        conn.execute(
            update(t.cards)
            .where(and_(t.cards.c.card_id == p.card_id, t.cards.c.imported_from.is_(None)))
            .values(imported_from=f"{p.source_project}:{p.source_card_id}")
        )

    return imported
