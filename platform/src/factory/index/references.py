"""Projection of reference extraction, resolution, decisions and snowball rounds (slice 3a).

`reference_extractions` keeps every extraction; `live` is 1 for the latest extraction of a work in
event order and 0 for earlier ones, so a later extraction supersedes the links of an earlier one.
`reference_entries` holds the parsed fields and `entry_sha256` per entry; there is no text column
(ruling 14). `reference_links` holds one row per resolved entry: the `base_*` columns are the
resolution as recorded, and `state`, `work_id` and `confidence` fold the latest binding decision
(`confirm` makes the link resolved with confidence `confirmed`, `reject` makes it unresolved);
`decision`/`confirmed_by` name that binding decision and `proposal` the latest proposal, which
never changes the state. `reference_decisions` keeps the latest decision per entry and kind, so a
decision recorded before its link is folded when the link arrives. A `reference.resolved` event's
`carried` decisions enter `reference_decisions` as the binding decisions of the new extraction,
under the human's own event id. A `clear` is the latest binding decision of its entry and folds
to none: the link reads as recorded. A `reference.re_resolved` event replaces the recorded
resolution of named links of a live extraction, keeping the extraction id, then folds their
decisions again. It is all or nothing: an unknown or superseded extraction, a link that is absent
or not `re_resolvable`, or a carried decision that does not match a human's recorded one changes
nothing.

`reason` is the recorded resolution's reason and is not folded: an unresolved link made so by a
`reject` keeps the reason of its base resolution, which is NULL when the base was not unresolved.
Readers derive "rejected" from `decision = 'reject'`, never from `reason`.

`citation_contexts` keeps each marker occurrence in recorded order; `reference_context_sets` marks
the extraction whose contexts are recorded. `snowball_rounds`, `snowball_queries` and
`snowball_candidates` keep each round, its query texts in order and its candidates, with
`cited_by_included` derived as the number of distinct source works citing the candidate.

Reference layers (cited items grouped by normalised title): `reference_layer_schemes` keeps the
researcher's scheme per version (`layers` is canonical JSON), first write wins; only a human
actor's `reference.layer_scheme_recorded` is folded. `reference_layers` keeps an agent's layer per
(item_key, stage, actor, scheme_version), last write wins; only an agent actor's
`reference.layer_assigned` is folded. `reference_layer_labels` keeps the researcher's own label per
(item_key, scheme_version), last write wins; only a human actor's
`reference.layer_labelled` is folded. An event that fails the actor guard or its
payload validation changes nothing. Neither the scheme version nor the layer is checked against a
recorded scheme here: the service refuses unknown ones at the boundary, and an event naming one
is stored.

Handlers are total: an event naming an unknown extraction is stored, never refused. Extractions,
entries, links, context sets, rounds, queries and candidates are first-write-wins per key; a
decision replaces the earlier one of its kind for the entry (last write wins).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue, ValidationError
from sqlalchemy import Column, Float, Index, Integer, MetaData, String, Table, and_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.references import (
    BINDING_DECISIONS,
    CarriedDecision,
    CitationContextsRecorded,
    Confidence,
    Decision,
    LayerAssigned,
    LayerLabelled,
    LayerSchemeRecorded,
    LinkState,
    ReferenceExtracted,
    ReferenceReResolved,
    ReferenceResolutionDecided,
    ReferenceResolved,
    SnowballRoundStarted,
    re_resolvable,
)

BINDING = "binding"
PROPOSAL = "proposal"


@dataclass(frozen=True)
class ReferenceTables:
    extractions: Table
    entries: Table
    links: Table
    decisions: Table
    context_sets: Table
    contexts: Table
    rounds: Table
    queries: Table
    candidates: Table
    layer_schemes: Table
    layers: Table
    layer_labels: Table


def reference_tables(metadata: MetaData) -> ReferenceTables:
    extractions = Table(
        "reference_extractions",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("document_id", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("parser", String, nullable=False),
        Column("parser_version", String, nullable=False),
        Column("entry_anchors", String, nullable=False),
        Column("source_quality", String, nullable=False),
        Column("flags", String, nullable=False),
        Column("marker_count", Integer, nullable=False),
        Column("bbl_status", String, nullable=False),
        Column("bbl_archive", String),
        Column("bbl_count", Integer),
        Column("event_id", String, nullable=False),
        Column("live", Integer, nullable=False),
        Index("ix_reference_extractions_work", "work_id"),
    )
    entries = Table(
        "reference_entries",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("anchor", String, nullable=False),
        Column("label", String),
        Column("entry_sha256", String, nullable=False),
        Column("doi", String),
        Column("arxiv", String),
        Column("url", String),
        Column("year", Integer),
        Column("first_author", String),
        Column("title", String),
        Column("venue", String),
    )
    links = Table(
        "reference_links",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("state", String, nullable=False),
        Column("work_id", String),
        Column("confidence", String),
        Column("base_state", String, nullable=False),
        Column("base_work_id", String),
        Column("base_confidence", String),
        Column("method", String),
        Column("score", Float),
        Column("candidates", String, nullable=False),
        Column("source_blob", String),
        Column("reason", String),
        Column("matcher_version", String, nullable=False),
        Column("decision", String),
        Column("confirmed_by", String),
        Column("proposal", String),
        Column("no_source_record", Integer, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_reference_links_work", "work_id"),
    )
    decisions = Table(
        "reference_decisions",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("kind", String, primary_key=True),
        Column("decision", String, nullable=False),
        Column("work_id", String),
        Column("confirmed_by", String),
        Column("event_id", String, nullable=False),
    )
    context_sets = Table(
        "reference_context_sets",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
    )
    contexts = Table(
        "citation_contexts",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("position", Integer, primary_key=True),
        Column("citing_anchor", String, nullable=False),
        Column("entry", Integer),
        Column("marker", String, nullable=False),
        Column("method", String, nullable=False),
        Column("state", String, nullable=False),
    )
    rounds = Table(
        "snowball_rounds",
        metadata,
        Column("round_id", String, primary_key=True),
        Column("direction", String, nullable=False),
        Column("via", String, nullable=False),
        Column("round_no", Integer, nullable=False),
        Column("rule", String, nullable=False),
        Column("chase_round_id", String),
        Column("sources", String, nullable=False),
        Column("extraction_ids", String, nullable=False),
        Column("unextracted", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("selection", String),
    )
    queries = Table(
        "snowball_queries",
        metadata,
        Column("round_id", String, primary_key=True),
        Column("position", Integer, primary_key=True),
        Column("query", String, nullable=False),
    )
    candidates = Table(
        "snowball_candidates",
        metadata,
        Column("round_id", String, primary_key=True),
        Column("work_key", String, primary_key=True),
        Column("cited_by_included", Integer, nullable=False),
        Column("cited_by", String, nullable=False),
        Column("no_source_record", Integer, nullable=False),
    )
    layer_schemes = Table(
        "reference_layer_schemes",
        metadata,
        Column("version", Integer, primary_key=True),
        Column("layers", String, nullable=False),
        Column("precursor_before_year", Integer, nullable=True),
        Column("inner_sample", String, nullable=True),
        Column("event_id", String, nullable=False),
    )
    layers = Table(
        "reference_layers",
        metadata,
        Column("item_key", String, primary_key=True),
        Column("stage", String, primary_key=True),
        Column("actor", String, primary_key=True),
        Column("scheme_version", Integer, primary_key=True),
        Column("layer", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_reference_layers_item_key", "item_key"),
    )
    layer_labels = Table(
        "reference_layer_labels",
        metadata,
        Column("item_key", String, primary_key=True),
        Column("scheme_version", Integer, primary_key=True),
        Column("layer", String, nullable=False),
        Column("actor", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return ReferenceTables(
        extractions,
        entries,
        links,
        decisions,
        context_sets,
        contexts,
        rounds,
        queries,
        candidates,
        layer_schemes,
        layers,
        layer_labels,
    )


def reference_handlers(t: ReferenceTables) -> dict[str, Handler]:
    return {
        "reference.extracted": _extracted(t),
        "citation.contexts_recorded": _contexts(t),
        "reference.resolved": _resolved(t),
        "reference.re_resolved": _re_resolved(t),
        "reference.resolution_decided": _decided(t),
        "snowball.round_started": _round_started(t),
        "reference.layer_scheme_recorded": _layer_scheme_recorded(t),
        "reference.layer_assigned": _layer_assigned(t),
        "reference.layer_labelled": _layer_labelled(t),
    }


def _json(value: JsonValue) -> str:
    return canonical_json(value).decode()


def _extracted(t: ReferenceTables) -> Handler:
    def extracted(conn: Connection, event: Event) -> None:
        p = ReferenceExtracted.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.extractions)
            .values(
                extraction_id=p.extraction_id,
                work_id=p.work_id,
                document_id=p.document_id,
                conversion_id=p.conversion_id,
                parser=p.parser,
                parser_version=p.parser_version,
                entry_anchors=p.entry_anchors,
                source_quality=p.source_quality.value,
                flags=_json(list(p.flags)),
                marker_count=p.marker_count,
                bbl_status=p.bbl.status,
                bbl_archive=p.bbl.archive_blob,
                bbl_count=p.bbl.bbl_count,
                event_id=event.id,
                live=1,
            )
            .on_conflict_do_nothing(index_elements=["extraction_id"])
        )
        if inserted.rowcount == 0:
            return
        conn.execute(
            update(t.extractions)
            .where(
                and_(
                    t.extractions.c.work_id == p.work_id,
                    t.extractions.c.extraction_id != p.extraction_id,
                )
            )
            .values(live=0)
        )
        for e in p.entries:
            conn.execute(
                sqlite_insert(t.entries)
                .values(
                    extraction_id=p.extraction_id,
                    ordinal=e.ordinal,
                    anchor=e.anchor,
                    label=e.label,
                    entry_sha256=e.entry_sha256,
                    doi=e.doi,
                    arxiv=e.arxiv,
                    url=e.url,
                    year=e.year,
                    first_author=e.first_author,
                    title=e.title,
                    venue=e.venue,
                )
                .on_conflict_do_nothing(index_elements=["extraction_id", "ordinal"])
            )

    return extracted


def _contexts(t: ReferenceTables) -> Handler:
    def contexts(conn: Connection, event: Event) -> None:
        p = CitationContextsRecorded.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.context_sets)
            .values(extraction_id=p.extraction_id, event_id=event.id)
            .on_conflict_do_nothing(index_elements=["extraction_id"])
        )
        if inserted.rowcount == 0:
            return
        for position, c in enumerate(p.contexts):
            conn.execute(
                sqlite_insert(t.contexts)
                .values(
                    extraction_id=p.extraction_id,
                    position=position,
                    citing_anchor=c.citing_anchor,
                    entry=c.entry,
                    marker=c.marker,
                    method=c.method,
                    state=c.state,
                )
                .on_conflict_do_nothing(index_elements=["extraction_id", "position"])
            )

    return contexts


def _resolved(t: ReferenceTables) -> Handler:
    def resolved(conn: Connection, event: Event) -> None:
        p = ReferenceResolved.model_validate(event.payload)
        for r in p.resolutions:
            confidence = None if r.confidence is None else r.confidence.value
            inserted = conn.execute(
                sqlite_insert(t.links)
                .values(
                    extraction_id=p.extraction_id,
                    ordinal=r.ordinal,
                    state=r.state.value,
                    work_id=r.work_id,
                    confidence=confidence,
                    base_state=r.state.value,
                    base_work_id=r.work_id,
                    base_confidence=confidence,
                    method=r.method,
                    score=r.score,
                    candidates=_json([c.model_dump(mode="json") for c in r.candidates]),
                    source_blob=r.source_blob,
                    reason=r.reason,
                    matcher_version=p.matcher_version,
                    no_source_record=1 if r.no_source_record else 0,
                    event_id=event.id,
                )
                .on_conflict_do_nothing(index_elements=["extraction_id", "ordinal"])
            )
            if inserted.rowcount:
                _fold(conn, t, p.extraction_id, r.ordinal)
        for c in p.carried:
            conn.execute(
                sqlite_insert(t.decisions)
                .values(
                    extraction_id=p.extraction_id,
                    ordinal=c.ordinal,
                    kind=BINDING,
                    decision=c.decision.value,
                    work_id=c.work_id,
                    confirmed_by="human",
                    event_id=c.decided_event,
                )
                .on_conflict_do_nothing(index_elements=["extraction_id", "ordinal", "kind"])
            )
            _fold(conn, t, p.extraction_id, c.ordinal)

    return resolved


def _carried_recorded(conn: Connection, t: ReferenceTables, c: CarriedDecision) -> bool:
    """Whether `c` is a human's binding decision as recorded on its source entry."""
    d = t.decisions.c
    row = conn.execute(
        select(d.decision, d.work_id).where(
            and_(
                d.extraction_id == c.from_extraction,
                d.ordinal == c.from_ordinal,
                d.kind == BINDING,
                d.confirmed_by == "human",
                d.event_id == c.decided_event,
            )
        )
    ).first()
    return row is not None and row[0] == c.decision.value and row[1] == c.work_id


def _re_resolve_allowed(conn: Connection, t: ReferenceTables, p: ReferenceReResolved) -> bool:
    """The guards of `reference.re_resolved`; every one holds, or the event folds to nothing."""
    live = conn.execute(
        select(t.extractions.c.live).where(t.extractions.c.extraction_id == p.extraction_id)
    ).scalar()
    if live != 1:
        return False
    for r in p.resolutions:
        link = conn.execute(
            select(
                t.links.c.reason,
                t.links.c.matcher_version,
                t.links.c.decision,
                t.links.c.proposal,
            ).where(
                and_(t.links.c.extraction_id == p.extraction_id, t.links.c.ordinal == r.ordinal)
            )
        ).first()
        if link is None or not re_resolvable(
            reason=link[0],
            link_matcher=link[1],
            matcher=p.matcher_version,
            decision=link[2],
            proposal=link[3],
        ):
            return False
    return all(_carried_recorded(conn, t, c) for c in p.carried)


def _re_resolved(t: ReferenceTables) -> Handler:
    def re_resolved(conn: Connection, event: Event) -> None:
        p = ReferenceReResolved.model_validate(event.payload)
        if not _re_resolve_allowed(conn, t, p):
            return
        for r in p.resolutions:
            confidence = None if r.confidence is None else r.confidence.value
            conn.execute(
                update(t.links)
                .where(
                    and_(t.links.c.extraction_id == p.extraction_id, t.links.c.ordinal == r.ordinal)
                )
                .values(
                    base_state=r.state.value,
                    base_work_id=r.work_id,
                    base_confidence=confidence,
                    method=r.method,
                    score=r.score,
                    candidates=_json([c.model_dump(mode="json") for c in r.candidates]),
                    source_blob=r.source_blob,
                    reason=r.reason,
                    matcher_version=p.matcher_version,
                    no_source_record=1 if r.no_source_record else 0,
                    event_id=event.id,
                )
            )
        for c in p.carried:
            conn.execute(
                sqlite_insert(t.decisions)
                .values(
                    extraction_id=p.extraction_id,
                    ordinal=c.ordinal,
                    kind=BINDING,
                    decision=c.decision.value,
                    work_id=c.work_id,
                    confirmed_by="human",
                    event_id=c.decided_event,
                )
                .on_conflict_do_nothing(index_elements=["extraction_id", "ordinal", "kind"])
            )
        for r in p.resolutions:
            _fold(conn, t, p.extraction_id, r.ordinal)

    return re_resolved


def _decided(t: ReferenceTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        p = ReferenceResolutionDecided.model_validate(event.payload)
        kind = BINDING if p.decision in BINDING_DECISIONS else PROPOSAL
        values = {
            "decision": p.decision.value,
            "work_id": p.work_id,
            "confirmed_by": p.confirmed_by,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.decisions)
            .values(extraction_id=p.extraction_id, ordinal=p.ordinal, kind=kind, **values)
            .on_conflict_do_update(index_elements=["extraction_id", "ordinal", "kind"], set_=values)
        )
        _fold(conn, t, p.extraction_id, p.ordinal)

    return decided


def _fold(conn: Connection, t: ReferenceTables, extraction_id: str, ordinal: int) -> None:
    """Recompute a link's live state from its recorded resolution and its latest decisions."""
    link = conn.execute(
        select(t.links.c.base_state, t.links.c.base_work_id, t.links.c.base_confidence).where(
            and_(t.links.c.extraction_id == extraction_id, t.links.c.ordinal == ordinal)
        )
    ).first()
    if link is None:
        return
    rows = conn.execute(
        select(
            t.decisions.c.kind,
            t.decisions.c.decision,
            t.decisions.c.work_id,
            t.decisions.c.confirmed_by,
        ).where(
            and_(t.decisions.c.extraction_id == extraction_id, t.decisions.c.ordinal == ordinal)
        )
    ).all()
    by_kind = {str(row[0]): row for row in rows}
    state, work_id, confidence = link[0], link[1], link[2]
    decision = confirmed_by = None
    binding = by_kind.get(BINDING)
    if binding is not None and binding[1] != Decision.CLEAR.value:
        decision, confirmed_by = binding[1], binding[3]
        if decision == Decision.CONFIRM.value:
            state, work_id = LinkState.RESOLVED.value, binding[2]
            confidence = Confidence.CONFIRMED.value
        else:
            state, work_id, confidence = LinkState.UNRESOLVED.value, None, None
    proposal = by_kind.get(PROPOSAL)
    conn.execute(
        update(t.links)
        .where(and_(t.links.c.extraction_id == extraction_id, t.links.c.ordinal == ordinal))
        .values(
            state=state,
            work_id=work_id,
            confidence=confidence,
            decision=decision,
            confirmed_by=confirmed_by,
            proposal=None if proposal is None else proposal[1],
        )
    )


def _round_started(t: ReferenceTables) -> Handler:
    def round_started(conn: Connection, event: Event) -> None:
        p = SnowballRoundStarted.model_validate(event.payload)
        rule = p.rule if isinstance(p.rule, str) else _json(p.rule.model_dump(mode="json"))
        inserted = conn.execute(
            sqlite_insert(t.rounds)
            .values(
                round_id=p.round_id,
                direction=p.direction.value,
                via=p.via.value,
                round_no=p.round_no,
                rule=rule,
                chase_round_id=p.chase_round_id,
                sources=_json(list(p.sources)),
                extraction_ids=_json(list(p.extraction_ids)),
                unextracted=_json([u.model_dump(mode="json") for u in p.unextracted]),
                event_id=event.id,
                selection=(
                    None if p.selection is None else _json(p.selection.model_dump(mode="json"))
                ),
            )
            .on_conflict_do_nothing(index_elements=["round_id"])
        )
        if inserted.rowcount == 0:
            return
        for position, query in enumerate(p.queries):
            conn.execute(
                sqlite_insert(t.queries)
                .values(round_id=p.round_id, position=position, query=query)
                .on_conflict_do_nothing(index_elements=["round_id", "position"])
            )
        for c in p.candidates:
            conn.execute(
                sqlite_insert(t.candidates)
                .values(
                    round_id=p.round_id,
                    work_key=c.work_key,
                    cited_by_included=len({citer.work_id for citer in c.cited_by}),
                    cited_by=_json([citer.model_dump(mode="json") for citer in c.cited_by]),
                    no_source_record=1 if c.no_source_record else 0,
                )
                .on_conflict_do_nothing(index_elements=["round_id", "work_key"])
            )

    return round_started


def _layer_scheme_recorded(t: ReferenceTables) -> Handler:
    def layer_scheme_recorded(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        try:
            p = LayerSchemeRecorded.model_validate(event.payload)
        except ValidationError:
            return
        conn.execute(
            sqlite_insert(t.layer_schemes)
            .values(
                version=p.version,
                layers=_json([layer.model_dump(mode="json") for layer in p.layers]),
                precursor_before_year=p.precursor_before_year,
                inner_sample=(
                    None
                    if p.inner_sample is None
                    else _json(p.inner_sample.model_dump(mode="json"))
                ),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["version"])
        )

    return layer_scheme_recorded


def _layer_assigned(t: ReferenceTables) -> Handler:
    def layer_assigned(conn: Connection, event: Event) -> None:
        if event.actor.kind != "agent":
            return
        try:
            p = LayerAssigned.model_validate(event.payload)
        except ValidationError:
            return
        values = {
            "item_key": p.item_key,
            "stage": p.stage,
            "actor": event.actor.id,
            "scheme_version": p.scheme_version,
            "layer": p.layer,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.layers)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["item_key", "stage", "actor", "scheme_version"], set_=values
            )
        )

    return layer_assigned


def _layer_labelled(t: ReferenceTables) -> Handler:
    def layer_labelled(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        try:
            p = LayerLabelled.model_validate(event.payload)
        except ValidationError:
            return
        values = {
            "item_key": p.item_key,
            "scheme_version": p.scheme_version,
            "layer": p.layer,
            "actor": event.actor.id,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.layer_labels)
            .values(**values)
            .on_conflict_do_update(index_elements=["item_key", "scheme_version"], set_=values)
        )

    return layer_labelled
