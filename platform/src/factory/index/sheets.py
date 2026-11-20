"""Projection of argument sheets (plan chat T7).

Tables: `sheets` (one row per opened sheet, with its section state), `sheet_candidates` (the
candidates table as computed when the sheet opened), `sheet_arguments` and `sheet_ratings` (the
latest rating of an argument) and `sheet_balances` (every balance the researcher recorded; the
latest is the sheet's balance).

An event is folded only when it is consistent with what `services/sheets.py` enforces; one that
fails stays in the log and changes nothing (no service writes one, so it was written by hand):
- an argument needs an opened sheet and an agent actor; an argument against needs the section
  against open; one for needs the section against closed and the section for open; in `prepare`
  mode an argument has a session, and the session of an argument for has recorded none against;
  an argument is of a work among the sheet's candidates (its quote and claim row key are checked
  by the service only; the fold cannot read the conversions or the miner rows);
- a section closes once, `for` only after `against`;
- a rating needs a human actor and a folded argument of that sheet;
- a balance needs a human actor and a sheet whose two sections are closed;
- a lead may cite a sheet (`sheet_lead_problem`) only if it is a `prepare` sheet with both sections
  closed and a balance; `index/hypotheses.py` folds no lead that cites another.

Handlers are total: a failure at any point folds nothing and never raises, on rebuild too.
"""

from __future__ import annotations

import json

from sqlalchemy import Boolean, Column, Index, Integer, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.errors import FactoryError
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.sheets import (
    SheetArgumentRated,
    SheetArgumentRecorded,
    SheetBalanceRecorded,
    SheetOpened,
    SheetSectionClosed,
)


class SheetTables:
    def __init__(
        self,
        sheets: Table,
        candidates: Table,
        arguments: Table,
        ratings: Table,
        balances: Table,
    ) -> None:
        self.sheets = sheets
        self.candidates = candidates
        self.arguments = arguments
        self.ratings = ratings
        self.balances = balances


def sheet_tables(metadata: MetaData) -> SheetTables:
    sheets = Table(
        "sheets",
        metadata,
        Column("sheet_id", String, primary_key=True),
        Column("hypothesis", String, nullable=False),
        Column("mode", String, nullable=False),
        Column("selection", String, nullable=False),
        Column("selection_digest", String, nullable=False),
        Column("candidates_digest", String, nullable=False),
        Column("tier1_cap", Integer, nullable=False),
        Column("supersedes", String),
        Column("request_id", String),
        Column("for_request_id", String),
        Column("respar_of", String),
        Column("claims_fingerprint", String),
        Column("against_closed", Boolean, nullable=False),
        Column("for_closed", Boolean, nullable=False),
        Column("session", String),
        Column("actor", String, nullable=False),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    candidates = Table(
        "sheet_candidates",
        metadata,
        Column("sheet_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("tier", Integer, nullable=False),
        Column("sources", String, nullable=False),
        Column("stances", String, nullable=False),
        Column("over_cap", Boolean, nullable=False),
    )
    arguments = Table(
        "sheet_arguments",
        metadata,
        Column("argument_id", String, primary_key=True),
        Column("sheet_id", String, nullable=False),
        Column("stance", String, nullable=False),
        Column("work_id", String, nullable=False),
        Column("anchor", String, nullable=False),
        Column("quote", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("markdown_hash", String, nullable=False),
        Column("claim", String, nullable=False),
        Column("claim_row_key", String),
        Column("claim_row_version", Integer),
        Column("strength", String, nullable=False),
        Column("session", String),
        Column("actor", String, nullable=False),
        Column("model", String),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_sheet_arguments_sheet", "sheet_id", "stance"),
    )
    ratings = Table(
        "sheet_ratings",
        metadata,
        Column("argument_id", String, primary_key=True),
        Column("sheet_id", String, nullable=False),
        Column("rating", String, nullable=False),
        Column("note", String, nullable=False),
        Column("actor", String, nullable=False),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    balances = Table(
        "sheet_balances",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("sheet_id", String, nullable=False),
        Column("text", String, nullable=False),
        Column("lean", String),
        Column("note", String),
        Column("actor", String, nullable=False),
        Column("ts", String, nullable=False),
        Index("ix_sheet_balances_sheet", "sheet_id", "event_id"),
    )
    return SheetTables(sheets, candidates, arguments, ratings, balances)


def sheet_handlers(tables: SheetTables) -> dict[str, Handler]:
    def opened(conn: Connection, event: Event) -> None:
        payload = SheetOpened.model_validate(event.payload)
        if event.actor.kind != "agent":
            return
        if payload.supersedes is not None and not _exists(conn, payload.supersedes):
            return
        if payload.respar_of is not None and not _exists(conn, payload.respar_of):
            return
        conn.execute(
            sqlite_insert(tables.sheets)
            .values(
                sheet_id=payload.sheet_id,
                hypothesis=payload.hypothesis,
                mode=payload.mode,
                selection=canonical_json(payload.selection).decode(),
                selection_digest=payload.selection_digest,
                candidates_digest=payload.candidates_digest,
                tier1_cap=payload.tier1_cap,
                supersedes=payload.supersedes,
                request_id=payload.request_id,
                respar_of=payload.respar_of,
                claims_fingerprint=(
                    None
                    if payload.claims_fingerprint is None
                    else json.dumps(
                        payload.claims_fingerprint, sort_keys=True, separators=(",", ":")
                    )
                ),
                against_closed=False,
                for_closed=False,
                session=event.actor.session,
                actor=event.actor.id,
                ts=format_ts(event.ts),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["sheet_id"])
        )
        for c in payload.candidates:
            conn.execute(
                sqlite_insert(tables.candidates)
                .values(
                    sheet_id=payload.sheet_id,
                    work_id=c.work_id,
                    tier=c.tier,
                    sources=",".join(c.sources),
                    stances=",".join(c.stances),
                    over_cap=c.over_cap,
                )
                .on_conflict_do_nothing(index_elements=["sheet_id", "work_id"])
            )

    def argument(conn: Connection, event: Event) -> None:
        payload = SheetArgumentRecorded.model_validate(event.payload)
        if event.actor.kind != "agent":
            return
        sheet = conn.execute(
            text("SELECT mode, against_closed, for_closed FROM sheets WHERE sheet_id = :s"),
            {"s": payload.sheet_id},
        ).first()
        if sheet is None:
            return
        in_sheet = conn.execute(
            text("SELECT 1 FROM sheet_candidates WHERE sheet_id = :s AND work_id = :w"),
            {"s": payload.sheet_id, "w": payload.work_id},
        ).first()
        if in_sheet is None:
            return
        mode, against_closed, for_closed = str(sheet[0]), bool(sheet[1]), bool(sheet[2])
        if mode == "prepare" and event.actor.session is None:
            return  # the split of the two sections cannot be shown without a session
        if payload.stance == "against" and against_closed:
            return
        if payload.stance == "for":
            if not against_closed or for_closed:
                return
            if mode == "prepare" and (
                event.actor.session is None
                or _wrote_against(conn, payload.sheet_id, event.actor.session)
            ):
                return
        conn.execute(
            sqlite_insert(tables.arguments)
            .values(
                argument_id=payload.argument_id,
                sheet_id=payload.sheet_id,
                stance=payload.stance,
                work_id=payload.work_id,
                anchor=payload.anchor,
                quote=payload.quote,
                conversion_id=payload.conversion_id,
                markdown_hash=payload.markdown_hash,
                claim=payload.claim,
                claim_row_key=payload.claim_row_key,
                claim_row_version=payload.claim_row_version,
                strength=payload.strength,
                session=event.actor.session,
                actor=event.actor.id,
                model=event.actor.model,
                ts=format_ts(event.ts),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["argument_id"])
        )

    def closed(conn: Connection, event: Event) -> None:
        payload = SheetSectionClosed.model_validate(event.payload)
        if event.actor.kind != "agent":
            return
        sheet = conn.execute(
            text("SELECT against_closed, for_closed FROM sheets WHERE sheet_id = :s"),
            {"s": payload.sheet_id},
        ).first()
        if sheet is None:
            return
        against_closed, for_closed = bool(sheet[0]), bool(sheet[1])
        if payload.section == "against" and not against_closed:
            conn.execute(
                text("UPDATE sheets SET against_closed = 1 WHERE sheet_id = :s"),
                {"s": payload.sheet_id},
            )
        elif payload.section == "for" and against_closed and not for_closed:
            conn.execute(
                text("UPDATE sheets SET for_closed = 1, for_request_id = :r WHERE sheet_id = :s"),
                {"s": payload.sheet_id, "r": payload.request_id},
            )

    def rated(conn: Connection, event: Event) -> None:
        payload = SheetArgumentRated.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        found = conn.execute(
            text("SELECT 1 FROM sheet_arguments WHERE argument_id = :a AND sheet_id = :s"),
            {"a": payload.argument_id, "s": payload.sheet_id},
        ).first()
        if found is None:
            return
        values = {
            "sheet_id": payload.sheet_id,
            "rating": payload.rating,
            "note": payload.note,
            "actor": event.actor.id,
            "ts": format_ts(event.ts),
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(tables.ratings)
            .values(argument_id=payload.argument_id, **values)
            .on_conflict_do_update(index_elements=["argument_id"], set_=values)
        )

    def balanced(conn: Connection, event: Event) -> None:
        payload = SheetBalanceRecorded.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        sheet = conn.execute(
            text("SELECT against_closed, for_closed FROM sheets WHERE sheet_id = :s"),
            {"s": payload.sheet_id},
        ).first()
        if sheet is None or not (bool(sheet[0]) and bool(sheet[1])):
            return
        conn.execute(
            sqlite_insert(tables.balances)
            .values(
                event_id=event.id,
                sheet_id=payload.sheet_id,
                text=payload.text,
                lean=payload.lean,
                note=payload.note,
                actor=event.actor.id,
                ts=format_ts(event.ts),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
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
        "sheet.opened": total(opened),
        "sheet.argument_recorded": total(argument),
        "sheet.section_closed": total(closed),
        "sheet.argument_rated": total(rated),
        "sheet.balance_recorded": total(balanced),
    }


def _exists(conn: Connection, sheet_id: str) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM sheets WHERE sheet_id = :s"), {"s": sheet_id}).first()
        is not None
    )


def _wrote_against(conn: Connection, sheet_id: str, session: str | None) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM sheet_arguments WHERE sheet_id = :s AND stance = 'against' "
                "AND session = :x LIMIT 1"
            ),
            {"s": sheet_id, "x": session},
        ).first()
        is not None
    )


def sheet_lead_problem(conn: Connection, sheet_id: str) -> str | None:
    """Why a lead may not cite the sheet, or None when it may (decision 143): it must exist, be a
    `prepare` sheet, have both sections closed and carry a balance the researcher recorded. The
    service refuses with this text; the lead projection folds no lead for which it is not None."""
    row = conn.execute(
        text("SELECT mode, against_closed, for_closed FROM sheets WHERE sheet_id = :s"),
        {"s": sheet_id},
    ).first()
    if row is None:
        return "unknown"
    if str(row[0]) != "prepare":
        return "a lead may cite only a sheet run in prepare mode"
    if not (bool(row[1]) and bool(row[2])):
        return "a lead may cite a sheet only once both sections are closed"
    balanced = conn.execute(
        text("SELECT 1 FROM sheet_balances WHERE sheet_id = :s LIMIT 1"), {"s": sheet_id}
    ).first()
    if balanced is None:
        return "a lead may cite a sheet only after the researcher has recorded its balance"
    return None
