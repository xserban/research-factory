"""Projection of the failed-directions registry (slice 6, plan XP-B task 6; spec ruling 27; R-52,
R-124).

`directions` keeps one row per failed direction with its reason and the conditions it failed
under; `direction_keys` the keys it is searchable by. A row is never removed.

Rows are derived in the same fold as the event that makes a direction fail, after the base handler
of that event ran, and only if the base handler folded it (so an event that fails its own guards
makes no row):
- `hypothesis.evaluated` with a refuted or inconclusive outcome: source `hypothesis`, id the
  hypothesis id; reason `below-baseline` when a superiority hypothesis is refuted with a negative
  mean. A later failing evaluation of the same hypothesis replaces the reason and conditions of
  that row; a later success leaves it ("failed here").
- `hypothesis.abandoned`: source `hypothesis`, the abandon reason (budget exhaustion reads as
  `compute-budget-exhausted`). A superseded draft is not a failure and makes no row.
- `lead.decided` with `discard`: source `lead`, reason `discarded-lead`.
- `baseline.evaluated` with a verdict other than `reproduced`: source `baseline`, id
  `<experiment>:<row key>`.
- `direction.closed` from a human, once per `dir_` id and only with keys that name something the
  project holds: source `closed`, id the `dir_` id.

Handlers are total: an event that does not validate or names something unknown changes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, Index, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.experiments import design_of
from factory.index.projection import Handler, chain
from factory.model.directions import Conditions, DirectionClosed, DirectionReason
from factory.model.experiments import BaselineEvaluated
from factory.model.hypotheses import (
    HypothesisAbandoned,
    HypothesisEvaluated,
    HypothesisSpec,
    LeadDecided,
    MethodRef,
)

_ABANDON = {
    "no-runnable-code": DirectionReason.NO_RUNNABLE_CODE,
    "budget-exhausted": DirectionReason.BUDGET_EXHAUSTED,
    "infeasible": DirectionReason.INFEASIBLE,
    "data-unavailable": DirectionReason.DATA_UNAVAILABLE,
    "other": DirectionReason.OTHER,
}


@dataclass(frozen=True)
class DirectionTables:
    directions: Table
    keys: Table


def direction_tables(metadata: MetaData) -> DirectionTables:
    directions = Table(
        "directions",
        metadata,
        Column("direction_id", String, primary_key=True),
        Column("source_kind", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("conditions_json", String, nullable=False),
        Column("text", String),
        Column("event_id", String, nullable=False),
    )
    keys = Table(
        "direction_keys",
        metadata,
        Column("direction_id", String, primary_key=True),
        Column("key", String, primary_key=True),
        Index("ix_direction_keys_key", "key"),
    )
    return DirectionTables(directions, keys)


def _put(
    conn: Connection,
    t: DirectionTables,
    *,
    direction_id: str,
    source_kind: str,
    reason: DirectionReason,
    conditions: Conditions,
    keys: set[str],
    event_id: str,
    note: str | None = None,
    replace: bool = False,
) -> None:
    values = {
        "direction_id": direction_id,
        "source_kind": source_kind,
        "reason": reason.value,
        "conditions_json": canonical_json(conditions.model_dump(mode="json")).decode(),
        "text": note,
        "event_id": event_id,
    }
    statement = sqlite_insert(t.directions).values(**values)
    if replace:
        statement = statement.on_conflict_do_update(
            index_elements=["direction_id"],
            set_={k: v for k, v in values.items() if k not in ("direction_id", "source_kind")},
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=["direction_id"])
    conn.execute(statement)
    for key in sorted(keys):
        conn.execute(
            sqlite_insert(t.keys)
            .values(direction_id=direction_id, key=key)
            .on_conflict_do_nothing(index_elements=["direction_id", "key"])
        )


# --- Keys and conditions read from the other projections ---------------------------------------


def _card_keys(conn: Connection, card_id: str) -> set[str]:
    keys = {card_id}
    subject = conn.execute(
        text("SELECT subject FROM cards WHERE card_id = :c"), {"c": card_id}
    ).scalar()
    keys.update(
        str(p)
        for p in conn.execute(
            text("SELECT DISTINCT property_key FROM card_props WHERE card_id = :c"), {"c": card_id}
        ).scalars()
    )
    if subject is not None:
        keys.add(str(subject))
        if str(subject).startswith("ida_"):
            keys.add(_resolved_idea(conn, str(subject)))
    return keys


def _resolved_idea(conn: Connection, idea_id: str) -> str:
    seen: set[str] = set()
    current = idea_id
    while current not in seen:
        seen.add(current)
        row = conn.execute(
            text("SELECT merged_into FROM ideas WHERE idea_id = :i"), {"i": current}
        ).first()
        if row is None or row[0] is None:
            break
        current = str(row[0])
    return current


def _ref_keys(conn: Connection, ref: MethodRef) -> set[str]:
    keys: set[str] = set()
    if ref.card is not None:
        keys |= _card_keys(conn, ref.card)
    if ref.idea is not None:
        keys |= {ref.idea, _resolved_idea(conn, ref.idea)}
    if ref.row_key is not None:
        keys.add(ref.row_key)
    return keys


def _lead_key_set(conn: Connection, lead_id: str) -> set[str]:
    return {
        str(k)
        for k in conn.execute(
            text("SELECT key FROM lead_keys WHERE lead_id = :l"), {"l": lead_id}
        ).scalars()
    }


def _experiment_row(conn: Connection, hypothesis_id: str) -> Any:
    return conn.execute(
        text(
            "SELECT experiment_id, e_version, design_json FROM experiments "
            "WHERE hypothesis = :h ORDER BY (superseded_by IS NULL) DESC, event_id DESC LIMIT 1"
        ),
        {"h": hypothesis_id},
    ).first()


def hypothesis_conditions_and_keys(
    conn: Connection, hypothesis_id: str
) -> tuple[Conditions, set[str]]:
    """The conditions a hypothesis failed under and the keys it is searchable by."""
    hyp = conn.execute(
        text("SELECT spec_json, drafter_model FROM hypotheses WHERE hypothesis_id = :h"),
        {"h": hypothesis_id},
    ).first()
    if hyp is None:
        raise KeyError(hypothesis_id)
    spec = HypothesisSpec.model_validate(json.loads(str(hyp[0])))
    keys = {hypothesis_id} | _ref_keys(conn, spec.treatment) | _ref_keys(conn, spec.baseline)
    if spec.lead is not None:
        keys |= {spec.lead} | _lead_key_set(conn, spec.lead)
    models = {str(hyp[1])} if hyp[1] is not None else set()
    models.update(
        str(m)
        for m in conn.execute(
            text(
                "SELECT DISTINCT critic_model FROM hypothesis_reviews "
                "WHERE hypothesis_id = :h AND critic_model IS NOT NULL"
            ),
            {"h": hypothesis_id},
        ).scalars()
    )
    e_version = None
    datasets: tuple[str, ...] = ()
    hours: str | None = None
    commit = None
    exp = _experiment_row(conn, hypothesis_id)
    if exp is not None:
        design = design_of(exp[2])
        e_version = str(exp[1])
        datasets = tuple(sorted({d.name for d in design.datasets}))
        commit = design.code.commit
        keys |= {str(exp[0])} | {f"ds:{d}" for d in datasets}
        used = sum(
            (
                Decimal(str(h))
                for h in conn.execute(
                    text(
                        "SELECT gpu_hours FROM xruns WHERE experiment_id = :e "
                        "AND gpu_hours IS NOT NULL"
                    ),
                    {"e": str(exp[0])},
                ).scalars()
            ),
            Decimal(0),
        )
        hours = "0" if used == 0 else format(used.normalize(), "f")
    conditions = Conditions(
        e_version=e_version,
        datasets=datasets,
        gpu_hours_used=hours,
        models=tuple(sorted(models)),
        code_commit=commit,
    )
    return conditions, keys


_ID_TABLES: dict[str, tuple[str, str]] = {
    "mcd_": ("cards", "card_id"),
    "pbd_": ("cards", "card_id"),
    "ida_": ("ideas", "idea_id"),
    "led_": ("leads", "lead_id"),
    "hyp_": ("hypotheses", "hypothesis_id"),
    "exp_": ("experiments", "experiment_id"),
    "rf:": ("works", "work_id"),
    "dir_": ("directions", "direction_id"),
    "rk_": ("extraction_rows", "row_key"),
}


def key_known(conn: Connection, key: str) -> bool:
    """Whether a key names something the project holds: an id of a card, idea, lead, hypothesis,
    design, work or direction, an extracted row, a vocabulary property, or `ds:<name>` of a
    design's dataset. Read by the fold and the service alike."""
    for prefix, (table, column) in _ID_TABLES.items():
        if key.startswith(prefix):
            sql = f"SELECT 1 FROM {table} WHERE {column} = :k LIMIT 1"
            return conn.execute(text(sql), {"k": key}).first() is not None
    if key.startswith("ds:"):
        found = conn.execute(
            text(
                "SELECT 1 FROM experiments WHERE EXISTS (SELECT 1 FROM "
                "json_each(json_extract(design_json, '$.datasets')) "
                "WHERE json_extract(value, '$.name') = :n) LIMIT 1"
            ),
            {"n": key[3:]},
        ).first()
        return found is not None
    found = conn.execute(
        text("SELECT 1 FROM properties WHERE key = :k LIMIT 1"), {"k": key}
    ).first()
    return found is not None


# --- Handlers ---------------------------------------------------------------------------------


def _total(handler: Handler) -> Handler:
    def run(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (ValueError, ArithmeticError, KeyError, TypeError, AttributeError, IndexError):
            return

    return run


def _after_evaluated(t: DirectionTables) -> Handler:
    def evaluated(conn: Connection, event: Event) -> None:
        p = HypothesisEvaluated.model_validate(event.payload)
        folded = conn.execute(
            text("SELECT 1 FROM hypothesis_evaluations WHERE event_id = :e"), {"e": event.id}
        ).first()
        if folded is None or p.outcome not in ("refuted", "inconclusive"):
            return
        reason = DirectionReason(p.outcome)
        spec_json = conn.execute(
            text("SELECT spec_json FROM hypotheses WHERE hypothesis_id = :h"),
            {"h": p.hypothesis_id},
        ).scalar()
        spec = HypothesisSpec.model_validate(json.loads(str(spec_json)))
        if (
            p.outcome == "refuted"
            and spec.decision_rule.rule == "superiority"
            and p.mean is not None
            and Decimal(p.mean) < 0
        ):
            reason = DirectionReason.BELOW_BASELINE
        conditions, keys = hypothesis_conditions_and_keys(conn, p.hypothesis_id)
        _put(
            conn,
            t,
            direction_id=p.hypothesis_id,
            source_kind="hypothesis",
            reason=reason,
            conditions=conditions,
            keys=keys,
            event_id=event.id,
            replace=True,
        )

    return _total(evaluated)


def _after_abandoned(t: DirectionTables) -> Handler:
    def abandoned(conn: Connection, event: Event) -> None:
        p = HypothesisAbandoned.model_validate(event.payload)
        folded = conn.execute(
            text("SELECT 1 FROM hypotheses WHERE hypothesis_id = :h AND abandoned_event_id = :e"),
            {"h": p.hypothesis_id, "e": event.id},
        ).first()
        if folded is None:
            return
        conditions, keys = hypothesis_conditions_and_keys(conn, p.hypothesis_id)
        _put(
            conn,
            t,
            direction_id=p.hypothesis_id,
            source_kind="hypothesis",
            reason=_ABANDON[p.reason.value],
            conditions=conditions,
            keys=keys,
            event_id=event.id,
            replace=True,
        )

    return _total(abandoned)


def _after_lead_decided(t: DirectionTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        p = LeadDecided.model_validate(event.payload)
        folded = conn.execute(
            text(
                "SELECT 1 FROM leads WHERE lead_id = :l AND decision_event_id = :e "
                "AND decision = 'discard'"
            ),
            {"l": p.lead_id, "e": event.id},
        ).first()
        if folded is None:
            return
        _put(
            conn,
            t,
            direction_id=p.lead_id,
            source_kind="lead",
            reason=DirectionReason.DISCARDED_LEAD,
            conditions=Conditions(),
            keys={p.lead_id} | _lead_key_set(conn, p.lead_id),
            event_id=event.id,
        )

    return _total(decided)


def _after_baseline(t: DirectionTables) -> Handler:
    def evaluated(conn: Connection, event: Event) -> None:
        p = BaselineEvaluated.model_validate(event.payload)
        folded = conn.execute(
            text(
                "SELECT 1 FROM baseline_evaluations WHERE experiment_id = :e AND row_key = :r "
                "AND event_id = :v AND verdict != 'reproduced'"
            ),
            {"e": p.experiment_id, "r": p.row_key, "v": event.id},
        ).first()
        if folded is None:
            return
        exp = conn.execute(
            text(
                "SELECT e_version, design_json, hypothesis FROM experiments "
                "WHERE experiment_id = :e"
            ),
            {"e": p.experiment_id},
        ).first()
        if exp is None:
            return
        design = design_of(exp[1])
        datasets = tuple(sorted({d.name for d in design.datasets}))
        used = sum(
            (
                Decimal(str(h))
                for h in conn.execute(
                    text(
                        "SELECT gpu_hours FROM xruns WHERE experiment_id = :e "
                        "AND gpu_hours IS NOT NULL"
                    ),
                    {"e": p.experiment_id},
                ).scalars()
            ),
            Decimal(0),
        )
        conditions, keys = hypothesis_conditions_and_keys(conn, str(exp[2]))
        keys |= {p.row_key, p.experiment_id} | {f"ds:{d}" for d in datasets}
        work = conn.execute(
            text("SELECT work_id FROM extraction_rows WHERE row_key = :r LIMIT 1"),
            {"r": p.row_key},
        ).scalar()
        if work is not None:
            keys.add(str(work))
        _put(
            conn,
            t,
            direction_id=f"{p.experiment_id}:{p.row_key}",
            source_kind="baseline",
            reason=DirectionReason.BASELINE_NOT_REPRODUCED,
            conditions=conditions.model_copy(
                update={
                    "e_version": str(exp[0]),
                    "datasets": datasets,
                    "gpu_hours_used": "0" if used == 0 else format(used.normalize(), "f"),
                    "code_commit": design.code.commit,
                }
            ),
            keys=keys,
            event_id=event.id,
        )

    return _total(evaluated)


def _closed(t: DirectionTables) -> Handler:
    def closed(conn: Connection, event: Event) -> None:
        p = DirectionClosed.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        taken = conn.execute(
            text("SELECT 1 FROM directions WHERE direction_id = :d"), {"d": p.direction_id}
        ).first()
        if taken is not None or not all(key_known(conn, k) for k in p.keys):
            return  # a dir_ id is written once; every key names something the project holds
        _put(
            conn,
            t,
            direction_id=p.direction_id,
            source_kind="closed",
            reason=p.reason,
            conditions=p.conditions,
            keys=set(p.keys) | {p.direction_id},
            event_id=event.id,
            note=p.text,
        )

    return _total(closed)


def direction_handlers(t: DirectionTables) -> dict[str, Handler]:
    return {"direction.closed": _closed(t)}


def derived_handlers(t: DirectionTables) -> dict[str, Handler]:
    """Handlers to chain after the base handler of each event type."""
    return {
        "hypothesis.evaluated": _after_evaluated(t),
        "hypothesis.abandoned": _after_abandoned(t),
        "lead.decided": _after_lead_decided(t),
        "baseline.evaluated": _after_baseline(t),
    }


def chain_derived(handlers: dict[str, Handler], t: DirectionTables) -> None:
    for event_type, handler in derived_handlers(t).items():
        handlers[event_type] = chain(handlers[event_type], handler)
