"""Lead statistics: counts of leads and the hypotheses they led to (job J2, task 5).

Invariants: read-only; every figure is computed by SQL on the lead, hypothesis, review,
registration and evaluation tables, once per call (no `list_leads` re-read of every row, no
`prior_for`); nothing is typed. A project with no lead gives zeros, never an error. Rates carry
their denominators (`recorded`, `decided`) and are None without one. The hypothesis state follows
`services.hypotheses`: abandoned, superseded, evaluated, registered, reviewed (an eligible review
of the current version; the plan's distinct-model rule is not applied here), else draft. The lead
text is never read (R-51). The source of a lead is the family of the miner scopes of its `item`
triggers.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection

from sqlalchemy import text

from factory.model.lead_engine import LeadStats, OldestLead
from factory.services.context import Project

__all__ = ["LEAD_STATES", "OLDEST", "lead_stats", "scope_source"]

LEAD_STATES = ("open", "promoted", "parked", "discarded")
HYPOTHESIS_STATES = (
    "draft",
    "reviewed",
    "registered",
    "evaluated",
    "abandoned",
    "superseded",
)
OLDEST = 10
"""Undecided leads listed, oldest first."""


def scope_source(scopes: Collection[str]) -> str:
    """The source label of a lead from the extraction scopes its `item` triggers cite: `technique`
    (`m-tech-*` miners), `claims` (`m-claims`), `other-miner`, `rows` (evidence or contribution
    scope), `none` (no known item) or `mixed` (more than one family)."""
    families: set[str] = set()
    for scope in scopes:
        if scope.startswith("m-tech-"):
            families.add("technique")
        elif scope == "m-claims":
            families.add("claims")
        elif scope in ("evidence", "contribution"):
            families.add("rows")
        else:
            families.add("other-miner")
    if not families:
        return "none"
    return next(iter(families)) if len(families) == 1 else "mixed"


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def lead_stats(project: Project) -> LeadStats:
    """The statistics of the project's leads and hypotheses (see the module invariants)."""
    project.index.sync()
    with project.index.connect() as conn:
        by_state = {s: 0 for s in LEAD_STATES}
        for state, n in conn.execute(text("SELECT state, COUNT(*) FROM leads GROUP BY state")):
            by_state[str(state)] = int(n)
        reasons = Counter[str]()
        for reason, n in conn.execute(
            text(
                "SELECT COALESCE(reason, 'none'), COUNT(*) FROM leads "
                "WHERE state = 'discarded' GROUP BY 1"
            )
        ):
            reasons[str(reason)] = int(n)
        kinds = {
            str(k): int(n)
            for k, n in conn.execute(
                text(
                    "SELECT kind, COUNT(DISTINCT lead_id) FROM lead_triggers "
                    "GROUP BY kind ORDER BY kind"
                )
            )
        }
        scopes: dict[str, set[str]] = defaultdict(set)
        for lead, scope in conn.execute(
            text(
                "SELECT t.lead_id, r.scope FROM lead_triggers t JOIN extraction_rows r "
                "ON r.extraction_id = t.ref WHERE t.kind = 'item'"
            )
        ):
            scopes[str(lead)].add(str(scope))
        leads = conn.execute(
            text(
                "SELECT l.lead_id, l.state, l.framework, l.event_id, "
                "(SELECT COUNT(*) FROM lead_triggers t WHERE t.lead_id = l.lead_id) "
                "FROM leads l ORDER BY l.event_id, l.lead_id"
            )
        ).all()
        hyps = conn.execute(
            text(
                "SELECT h.abandoned_event_id IS NOT NULL, h.superseded_by IS NOT NULL, "
                "h.conclusion_event_id IS NOT NULL, "
                "EXISTS (SELECT 1 FROM hypothesis_evaluations e "
                "WHERE e.hypothesis_id = h.hypothesis_id), "
                "EXISTS (SELECT 1 FROM hypothesis_registrations r "
                "WHERE r.hypothesis_id = h.hypothesis_id), "
                "EXISTS (SELECT 1 FROM hypothesis_reviews v WHERE v.hypothesis_id = "
                "h.hypothesis_id AND v.h_version = h.h_version AND v.eligible = 1) "
                "FROM hypotheses h"
            )
        ).all()
        reviews = {
            str(k): int(n)
            for k, n in conn.execute(
                text(
                    "SELECT recommend, COUNT(*) FROM hypothesis_reviews "
                    "GROUP BY recommend ORDER BY recommend"
                )
            )
        }
        outcomes = {
            str(k): int(n)
            for k, n in conn.execute(
                text(
                    "SELECT outcome, COUNT(*) FROM hypothesis_evaluations e WHERE e.event_id = "
                    "(SELECT MAX(x.event_id) FROM hypothesis_evaluations x "
                    "WHERE x.hypothesis_id = e.hypothesis_id) GROUP BY outcome ORDER BY outcome"
                )
            )
        }
    recorded = sum(by_state.values())
    decided = recorded - by_state["open"]
    by_source: dict[str, dict[str, int]] = {}
    for lead_id, state, *_ in leads:
        label = scope_source(scopes.get(str(lead_id), ()))
        row = by_source.setdefault(label, {"recorded": 0, **{s: 0 for s in LEAD_STATES}})
        row["recorded"] += 1
        row[str(state)] += 1
    h_states = {s: 0 for s in HYPOTHESIS_STATES}
    for abandoned, superseded, _concluded, evaluated, registered, reviewed in hyps:
        state = (
            "abandoned"
            if abandoned
            else "superseded"
            if superseded
            else "evaluated"
            if evaluated
            else "registered"
            if registered
            else "reviewed"
            if reviewed
            else "draft"
        )
        h_states[state] += 1
    oldest = tuple(
        OldestLead(
            lead_id=str(lead_id),
            framework=None if framework is None else str(framework),
            triggers=int(n),
            source=scope_source(scopes.get(str(lead_id), ())),
            event_id=str(event_id),
        )
        for lead_id, state, framework, event_id, n in leads
        if state == "open"
    )[:OLDEST]
    return LeadStats(
        recorded=recorded,
        by_state=by_state,
        decided=decided,
        promotion_rate=_rate(by_state["promoted"], recorded),
        decided_promotion_rate=_rate(by_state["promoted"], decided),
        discard_reasons=dict(sorted(reasons.items())),
        by_trigger_kind=kinds,
        by_source=dict(sorted(by_source.items())),
        hypotheses_drafted=len(hyps),
        hypotheses_by_state=h_states,
        hypotheses_registered=sum(1 for h in hyps if h[4]),
        hypotheses_closed={
            "abandoned": sum(1 for h in hyps if h[0]),
            "concluded": sum(1 for h in hyps if h[2]),
        },
        reviews=sum(reviews.values()),
        reviews_by_recommendation=reviews,
        outcomes=outcomes,
        oldest_undecided=oldest,
    )
