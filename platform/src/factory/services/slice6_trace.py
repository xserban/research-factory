"""Trace nodes and edges of slice 6: leads, hypotheses, designs, runs, cards, assertions,
contradictions and closed directions (plan XP-B task 7; spec acceptance 22; R-01, R-02, R-51).

Read-only SQL on the connection `services.trace` already holds.

Invariants:
- A label is made of ids, states, kinds, counts and fixed words. It never carries a lead's text, a
  hypothesis statement, a rationale, a critic's note, a conclusion, a quote, an assertion value,
  a metric value or an interval, for the researcher and an agent alike, so the same label is safe
  on both paths (R-51: `agent_trace` labels hold neither lead text nor rationale).
- Backward from a computed outcome: the evaluation act leads to the runs it used (or to the works it
  compared), a run to its metrics file and its design, a design to its hypothesis, a hypothesis to
  its reviews, registration, lead, method cards and rows, a lead to its triggers, and a row trigger
  to the slice-2 chain. Forward from a work, idea, row or card: the assertions, cards, leads and
  hypotheses that cite it.
- An edge may name something that is not a node kind of this module (a work, a row, an anchor);
  `services.trace` parses it. A reference that names no row is a missing node, never an error.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.model.cards import ASSERTION_ID_RE, CARD_ID_RE
from factory.model.directions import DIR_ID_RE
from factory.model.experiments import EXP_ID_RE, XRUN_ID_RE
from factory.model.findings import CONTRADICTION_ID_RE
from factory.model.hypotheses import HYP_ID_RE, LEAD_ID_RE
from factory.model.identity import ULID_RE

__all__ = ["KINDS", "PATTERNS", "attached", "describe", "edges"]

Key = tuple[str, str]
Ref = Key | str
Described = tuple[str, str]
KINDS = (
    "lead",
    "hypothesis",
    "hypothesis_act",
    "experiment",
    "xrun",
    "xrun_metrics",
    "card",
    "assertion",
    "contradiction",
    "direction",
)
_METRICS_RE = rf"^(xrn_{ULID_RE})/metrics$"
PATTERNS: tuple[tuple[str, str], ...] = (
    (LEAD_ID_RE, "lead"),
    (HYP_ID_RE, "hypothesis"),
    (rf"^ev_{ULID_RE}$", "hypothesis_act"),
    (EXP_ID_RE, "experiment"),
    (XRUN_ID_RE, "xrun"),
    (_METRICS_RE, "xrun_metrics"),
    (CARD_ID_RE, "card"),
    (ASSERTION_ID_RE, "assertion"),
    (CONTRADICTION_ID_RE, "contradiction"),
    (DIR_ID_RE, "direction"),
)


def _rows(conn: Connection, sql: str, **params: object) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(text(sql), params).all()]


def _column(conn: Connection, sql: str, **params: object) -> list[str]:
    return [str(r[0]) for r in _rows(conn, sql, **params)]


def describe(conn: Connection, kind: str, ident: str) -> Described | None:
    """The label and creating event of a node, or None when no row names it."""
    return _DESCRIBERS[kind](conn, ident)


def _lead(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT state, event_id, "
        "(SELECT COUNT(*) FROM lead_triggers t WHERE t.lead_id = l.lead_id) "
        "FROM leads l WHERE lead_id = :i",
        i=ident,
    )
    if not rows:
        return None
    state, event_id, triggers = rows[0]
    return f"lead {ident} · interpretation · {state}, {triggers} trigger(s)", str(event_id)


def _hypothesis_state(conn: Connection, ident: str, row: tuple[Any, ...]) -> str:
    if row[4] is not None:
        return "abandoned"
    if row[3] is not None:
        return "superseded"
    if _rows(
        conn,
        "SELECT 1 FROM hypothesis_evaluations WHERE hypothesis_id = :i AND outcome != 'incomplete'",
        i=ident,
    ):
        return "evaluated"
    if _rows(conn, "SELECT 1 FROM hypothesis_registrations WHERE hypothesis_id = :i", i=ident):
        return "registered"
    if _rows(conn, "SELECT 1 FROM hypothesis_reviews WHERE hypothesis_id = :i", i=ident):
        return "reviewed"
    return "draft"


def _hypothesis(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT h_version, kind, event_id, superseded_by, abandoned_event_id, "
        "json_extract(spec_json, '$.decision_rule.rule') FROM hypotheses WHERE hypothesis_id = :i",
        i=ident,
    )
    if not rows:
        return None
    row = rows[0]
    state = _hypothesis_state(conn, ident, row)
    return (
        f"hypothesis {ident} {row[0]} · test · {row[1]}, rule {row[5]}, state {state}",
        str(row[2]),
    )


def _act(conn: Connection, ident: str) -> Described | None:
    found = _rows(
        conn,
        "SELECT hypothesis_id, outcome, flags_json, payload_json FROM hypothesis_evaluations "
        "WHERE event_id = :i",
        i=ident,
    )
    if found:
        hyp, outcome, flags, payload = found[0]
        n = json.loads(str(payload)).get("n")
        names = ", ".join(json.loads(str(flags))) or "none"
        return f"evaluation {outcome} of {hyp} · test · {n} unit(s), flags {names}", ident
    found = _rows(
        conn,
        "SELECT hypothesis_id, h_version, recommend FROM hypothesis_reviews WHERE event_id = :i",
        i=ident,
    )
    if found:
        hyp, version, recommend = found[0]
        return f"review of {hyp} {version} · recommend {recommend}", ident
    found = _rows(
        conn,
        "SELECT hypothesis_id, h_version, policy, autonomy FROM hypothesis_registrations "
        "WHERE event_id = :i",
        i=ident,
    )
    if found:
        hyp, version, policy, autonomy = found[0]
        return f"registration of {hyp} {version} · policy {policy}, autonomy {autonomy}", ident
    return None


def _experiment(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT e_version, event_id, frozen_event_id, unlocked_event_id, superseded_by, "
        "(SELECT COUNT(*) FROM xruns x WHERE x.experiment_id = e.experiment_id) "
        "FROM experiments e WHERE experiment_id = :i",
        i=ident,
    )
    if not rows:
        return None
    version, event_id, frozen, unlocked, superseded, runs = rows[0]
    state = (
        "superseded"
        if superseded is not None
        else "unlocked"
        if unlocked is not None
        else "frozen"
        if frozen is not None
        else "draft"
    )
    return f"design {ident} {version} · test · {state}, {runs} run(s)", str(event_id)


def _xrun(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT arm, seed, split, event_id, reported_event_id, exit_status FROM xruns "
        "WHERE run_id = :i",
        i=ident,
    )
    if not rows:
        return None
    arm, seed, split, event_id, reported, exit_status = rows[0]
    state = "planned" if reported is None else ("completed" if exit_status == 0 else "failed")
    return f"run {ident} · test · arm {arm}, seed {seed}, {split}, {state}", str(event_id)


def _metrics(conn: Connection, ident: str) -> Described | None:
    run = ident.split("/", 1)[0]
    rows = _rows(
        conn,
        "SELECT results_blob, reported_event_id FROM xruns WHERE run_id = :i "
        "AND reported_event_id IS NOT NULL",
        i=run,
    )
    if not rows:
        return None
    blob, event_id = rows[0]
    return f"metrics file of {run} · stored blob {blob or '-'}", str(event_id)


def _card(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT kind, subject, event_id, "
        "(SELECT COUNT(*) FROM card_assertions a WHERE a.card_id = c.card_id "
        "AND a.superseded_by IS NULL AND a.folded = 1) FROM cards c WHERE card_id = :i",
        i=ident,
    )
    if not rows:
        return None
    kind, subject, event_id, count = rows[0]
    return f"{kind} card {ident} of {subject} · {count} assertion(s)", str(event_id)


def _assertion(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT card_id, property, status, decision, event_id FROM card_assertions "
        "WHERE assertion_id = :i",
        i=ident,
    )
    if not rows:
        return None
    card, prop, status, decision, event_id = rows[0]
    shown = decision or status
    return f"assertion {ident} of {card} · property {prop}, {shown}", str(event_id)


def _contradiction(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT ref_a, ref_b, decision, event_id FROM contradictions WHERE contradiction_id = :i",
        i=ident,
    )
    if not rows:
        return None
    a, b, decision, event_id = rows[0]
    return f"contradiction {ident} between {a} and {b} · {decision or 'undecided'}", str(event_id)


def _direction(conn: Connection, ident: str) -> Described | None:
    rows = _rows(
        conn,
        "SELECT reason, event_id FROM directions "
        "WHERE direction_id = :i AND source_kind = 'closed'",
        i=ident,
    )
    if not rows:
        return None
    return f"direction {ident} · test · closed: {rows[0][0]}", str(rows[0][1])


_DESCRIBERS = {
    "lead": _lead,
    "hypothesis": _hypothesis,
    "hypothesis_act": _act,
    "experiment": _experiment,
    "xrun": _xrun,
    "xrun_metrics": _metrics,
    "card": _card,
    "assertion": _assertion,
    "contradiction": _contradiction,
    "direction": _direction,
}


# --- Edges ---------------------------------------------------------------------------------


def edges(conn: Connection, kind: str, ident: str) -> tuple[list[Ref], list[Ref]]:
    """The upstream (derived from) and downstream (derived into) neighbours of a node."""
    return _EDGES[kind](conn, ident)


def _edges_lead(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    up: list[Ref] = [*_column(conn, "SELECT ref FROM lead_triggers WHERE lead_id = :i", i=ident)]
    up += _column(
        conn,
        "SELECT key FROM lead_keys WHERE lead_id = :i AND key LIKE 'rk\\_%' ESCAPE '\\'",
        i=ident,
    )
    down: list[Ref] = [
        ("hypothesis", h)
        for h in _column(conn, "SELECT hypothesis_id FROM hypotheses WHERE lead = :i", i=ident)
    ]
    return up, down


def _edges_hypothesis(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    up: list[Ref] = []
    lead = _column(
        conn, "SELECT lead FROM hypotheses WHERE hypothesis_id = :i AND lead IS NOT NULL", i=ident
    )
    up += [("lead", x) for x in lead]
    up += [
        ("hypothesis_act", e)
        for e in _column(
            conn,
            "SELECT event_id FROM hypothesis_reviews WHERE hypothesis_id = :i ORDER BY event_id",
            i=ident,
        )
    ]
    up += [
        ("hypothesis_act", e)
        for e in _column(
            conn, "SELECT event_id FROM hypothesis_registrations WHERE hypothesis_id = :i", i=ident
        )
    ]
    spec = _column(conn, "SELECT spec_json FROM hypotheses WHERE hypothesis_id = :i", i=ident)
    if spec:
        body = json.loads(spec[0])
        for side in ("treatment", "baseline"):
            ref = body.get(side) or {}
            up += [str(ref[k]) for k in ("card", "idea", "row_key") if ref.get(k)]
    up += [
        ("hypothesis", s)
        for s in _column(
            conn,
            "SELECT supersedes FROM hypotheses WHERE hypothesis_id = :i AND supersedes IS NOT NULL",
            i=ident,
        )
    ]
    down: list[Ref] = [
        ("experiment", e)
        for e in _column(
            conn,
            "SELECT experiment_id FROM experiments WHERE hypothesis = :i ORDER BY event_id",
            i=ident,
        )
    ]
    down += [
        ("hypothesis_act", e)
        for e in _column(
            conn,
            "SELECT event_id FROM hypothesis_evaluations WHERE hypothesis_id = :i "
            "ORDER BY event_id",
            i=ident,
        )
    ]
    down += [
        ("hypothesis", s)
        for s in _column(
            conn,
            "SELECT superseded_by FROM hypotheses WHERE hypothesis_id = :i "
            "AND superseded_by IS NOT NULL",
            i=ident,
        )
    ]
    return up, down


def _edges_act(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    evaluated = _rows(
        conn,
        "SELECT hypothesis_id, payload_json FROM hypothesis_evaluations WHERE event_id = :i",
        i=ident,
    )
    if evaluated:
        hyp, payload = evaluated[0]
        body = json.loads(str(payload))
        up: list[Ref] = [("xrun", r) for r in body.get("runs", [])]
        up += [str(w) for w in body.get("works", [])]
        if not up:
            up = [("hypothesis", str(hyp))]
        return up, [("hypothesis", str(hyp))]
    owner = _column(
        conn,
        "SELECT hypothesis_id FROM hypothesis_reviews WHERE event_id = :i UNION "
        "SELECT hypothesis_id FROM hypothesis_registrations WHERE event_id = :i",
        i=ident,
    )
    return [], [("hypothesis", h) for h in owner]


def _edges_experiment(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    up: list[Ref] = [
        ("hypothesis", h)
        for h in _column(
            conn, "SELECT hypothesis FROM experiments WHERE experiment_id = :i", i=ident
        )
    ]
    down: list[Ref] = [
        ("xrun", r)
        for r in _column(
            conn, "SELECT run_id FROM xruns WHERE experiment_id = :i ORDER BY event_id", i=ident
        )
    ]
    return up, down


def _edges_xrun(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    rows = _rows(
        conn,
        "SELECT experiment_id, reported_event_id FROM xruns WHERE run_id = :i",
        i=ident,
    )
    up: list[Ref] = []
    if rows:
        if rows[0][1] is not None:
            up.append(("xrun_metrics", f"{ident}/metrics"))
        up.append(("experiment", str(rows[0][0])))
    down: list[Ref] = [
        ("hypothesis_act", e)
        for e in _column(
            conn,
            "SELECT event_id FROM hypothesis_evaluations "
            "WHERE EXISTS (SELECT 1 FROM json_each(json_extract(payload_json, '$.runs')) "
            "WHERE value = :i) ORDER BY event_id",
            i=ident,
        )
    ]
    return up, down


def _edges_metrics(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    return [], [("xrun", ident.split("/", 1)[0])]


def _edges_card(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    up: list[Ref] = [*_column(conn, "SELECT subject FROM cards WHERE card_id = :i", i=ident)]
    down: list[Ref] = [
        ("assertion", a)
        for a in _column(
            conn,
            "SELECT assertion_id FROM card_assertions WHERE card_id = :i AND folded = 1 "
            "ORDER BY assertion_id",
            i=ident,
        )
    ]
    down += _citing(conn, ident)
    return up, down


def _edges_assertion(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    rows = _rows(
        conn,
        "SELECT card_id, basis_kind, basis_json FROM card_assertions WHERE assertion_id = :i",
        i=ident,
    )
    up: list[Ref] = []
    if rows:
        card, kind, basis = rows[0]
        up.append(("card", str(card)))
        body = {} if basis is None else json.loads(str(basis))
        if kind == "quote":
            up.append(f"{body['conversion_id']}/{body['anchor']}")
        elif kind == "row":
            up.append(str(body["row_key"]))
        elif kind == "inferred":
            up += [f"{s['conversion_id']}/{s['anchor']}" for s in body.get("supports", [])]
    return up, []


def _edges_contradiction(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    rows = _rows(
        conn,
        "SELECT ref_a, ref_b, work_a, work_b FROM contradictions WHERE contradiction_id = :i",
        i=ident,
    )
    up: list[Ref] = [str(x) for x in rows[0]] if rows else []
    return up, _citing(conn, ident)


def _edges_direction(conn: Connection, ident: str) -> tuple[list[Ref], list[Ref]]:
    up: list[Ref] = [
        k
        for k in _column(
            conn, "SELECT key FROM direction_keys WHERE direction_id = :i ORDER BY key", i=ident
        )
        if k != ident and not k.startswith("ds:")
    ]
    return up, _citing(conn, ident)


def _citing(conn: Connection, ident: str) -> list[Ref]:
    """Leads whose triggers name `ident`."""
    return [
        ("lead", lead)
        for lead in _column(
            conn,
            "SELECT DISTINCT lead_id FROM lead_triggers WHERE ref = :i ORDER BY lead_id",
            i=ident,
        )
    ]


def attached(conn: Connection, kind: str, ident: str) -> list[Ref]:
    """What cites a work, idea, row or claim, downstream: the cards about it, the assertions that
    quote it, the leads that name it and the hypotheses of those leads."""
    out: list[Ref] = [
        ("card", c)
        for c in _column(
            conn, "SELECT card_id FROM cards WHERE subject = :i ORDER BY card_id", i=ident
        )
    ]
    if kind == "work":
        out += [
            ("assertion", a)
            for a in _column(
                conn,
                "SELECT assertion_id FROM card_assertions WHERE folded = 1 "
                "AND json_extract(basis_json, '$.work_id') = :i ORDER BY assertion_id",
                i=ident,
            )
        ]
    out += _citing(conn, ident)
    out += [
        ("hypothesis", h)
        for h in _column(
            conn,
            "SELECT DISTINCT h.hypothesis_id FROM hypotheses h JOIN lead_triggers t "
            "ON t.lead_id = h.lead WHERE t.ref = :i ORDER BY h.hypothesis_id",
            i=ident,
        )
    ]
    return out


_EDGES = {
    "lead": _edges_lead,
    "hypothesis": _edges_hypothesis,
    "hypothesis_act": _edges_act,
    "experiment": _edges_experiment,
    "xrun": _edges_xrun,
    "xrun_metrics": _edges_metrics,
    "card": _edges_card,
    "assertion": _edges_assertion,
    "contradiction": _edges_contradiction,
    "direction": _edges_direction,
}
