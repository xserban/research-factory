"""The `hypotheses` hub payload (page "Hypotheses") and the researcher's acts on it: the hypothesis
engine v1 (lead candidates, queue, statistics, leads, hypotheses and their reviews).

Invariants:
- `build` is pure over its `HubContext`: it reads the project through the engine's own read
  functions (`lead_queue`, which takes the candidates from the derived `lead_cache`; `lead_stats`;
  `list_leads`; `list_hypotheses`), writes nothing and calls no model or network. Every count is
  computed here, never typed; the same project gives the same payload.
- Nothing an agent proposed is evidence: every candidate, lead and hypothesis is a proposal, and
  the payload carries the exploratory notice the engine prints (R-87). The platform never states
  novelty: the wording of a candidate is the engine's.
- Lists are capped (`QUEUE_CAP`, `LEAD_CAP`, `HYPOTHESIS_CAP`) with the exact totals beside them.
  Sessions and the proposer's identity are never put in the payload.
- The acts are the researcher's human decisions that already exist as service functions:
  `leads.decide_lead` (promote, park, discard), `hypotheses.register_hypothesis` and
  `hypotheses.abandon_hypothesis`. Each validates its body first and writes nothing on invalid
  input; the service refuses an agent at a human gate and applies the proposer separation. The hub
  supplies the human actor; the page offers the buttons in the served hub only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.hypotheses import DEFAULT_SERVES_RQ, AbandonReason, DiscardReason
from factory.model.lead_engine import NOTICE, QueueItem
from factory.services import hypotheses as hypotheses_service
from factory.services import leads as leads_service
from factory.services.context import Project
from factory.services.hypothesis_gates import effective_plan, gate_policy, project_mode
from factory.services.lead_queue import lead_queue
from factory.services.lead_stats import lead_stats

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

__all__ = ["ACTS", "abandon_act", "build", "decide_lead_act", "register_act"]

QUEUE_CAP: Final = 20
LEAD_CAP: Final = 30
HYPOTHESIS_CAP: Final = 40
QUOTE_CAP: Final = 3
WORK_CAP: Final = 5
PRIOR_CAP: Final = 5
LEAD_STATES: Final = ("open", "promoted", "parked", "discarded")
HYPOTHESIS_STATES: Final = (
    "draft",
    "reviewed",
    "registered",
    "evaluated",
    "superseded",
    "abandoned",
)
RUN_HINT: Final = "rf-hypothesis-engine"

MEASURE_LABELS: Final[dict[str, str]] = {
    "support": "works behind it",
    "independence": "distinct works",
    "verification": "quotes verified",
    "supportive_share": "supportive share",
    "overlap": "works that already state it",
    "diversity": "difference from promoted leads",
    "prior_hits": "earlier leads or hypotheses sharing a row",
    "narrow_prior_hits": "narrow prior hits",
    "broad_prior_hits": "broad prior hits",
    "score": "source score",
    "basis": "rows still live",
}

METHODS: Final[dict[str, str]] = {
    "page": (
        "The hypothesis engine turns exploratory observations from the corpus products into "
        "leads, and promoted leads into hypotheses a critic reviews. Everything an agent "
        "proposes here is a proposal, never evidence (R-87)."
    ),
    "stages": (
        "One box per stage of the engine. The counts are read from the recorded leads, "
        "hypotheses and reviews and from the candidate scan; a stage shows what is missing "
        "when it has nothing. Critique and the novelty check are done in a session and leave a "
        "record only through the leads' prior hits and the critic's review of a draft."
    ),
    "grounding": (
        "What the engine can draw observations from: the technique landscape (challenges, "
        "combinations, gaps) and the limitation rows of the claims miner, both from exploratory "
        "pass-A rows, plus the lineage the project holds. Counts are the numbers of "
        "observations each source produced before the cap."
    ),
    "queue": (
        "Candidates (observations) and open leads, each with measures computed from recorded "
        "rows and ordered by the printed rule. The platform never decides which observation is "
        "better; a measure is comparable only with the others of the same list. Candidates "
        "come from a derived cache that is rebuilt when the project changes."
    ),
    "leads": (
        "Leads are short notes tied to rows that resolve. An agent proposes a lead; only you "
        "promote, park or discard it, and a later decision supersedes the earlier one. "
        "Nothing is deleted."
    ),
    "hypotheses": (
        "Hypotheses are drafted from promoted leads. The state is computed from the events. A "
        "gate is passed when its condition holds now: an independent review recommends "
        "registering the current version, the registration is recorded, a literature "
        "hypothesis has no cut-off flag, and an evaluation exists."
    ),
    "stats": (
        "Counts computed from the lead, hypothesis, review and registration tables. A promotion "
        "share is a use figure, not a quality figure."
    ),
}


# ---------------------------------------------------------------- the payload


def _pct_text(value: float | None) -> str:
    return "none" if value is None else f"{round(100 * value)}%"


def _measure_text(name: str, item: QueueItem) -> str | None:
    m = item.measures
    value: str
    if name == "support":
        value = str(m.support)
    elif name == "independence":
        value = str(m.independence)
    elif name == "verification":
        value = f"{m.verification.verified} of {m.verification.total}"
    elif name == "supportive_share":
        value = _pct_text(m.supportive_share)
    elif name == "overlap":
        value = "not computed" if m.overlap is None else str(m.overlap)
    elif name == "diversity":
        value = _pct_text(m.diversity)
    elif name == "prior_hits":
        value = str(m.prior_hits)
    elif name == "narrow_prior_hits":
        value = str(m.narrow_prior_hits)
    elif name == "broad_prior_hits":
        value = str(m.broad_prior_hits)
    elif name == "score":
        value = f"{m.score:.2f}"
    elif name == "basis":
        value = m.basis
    else:
        return None
    return f"{MEASURE_LABELS.get(name, name)}: {value}"


def _entry(item: QueueItem, order_by: tuple[str, ...]) -> dict[str, Any]:
    """One queue entry as the page shows it: the measures, why it stands where it does and, for a
    candidate, its observation with the quotes it rests on."""
    m = item.measures
    out: dict[str, Any] = {
        "entry_id": item.entry_id,
        "kind": item.kind,
        "source": item.source,
        "rank": item.rank,
        "flags": list(item.flags),
        "stale_refs": len(item.stale_refs),
        "why": [t for t in (_measure_text(n, item) for n in order_by) if t],
        "measures": {
            "support": m.support,
            "independence": m.independence,
            "verified": m.verification.verified,
            "verification_total": m.verification.total,
            "supportive_share": m.supportive_share,
            "overlap": m.overlap,
            "diversity": m.diversity,
            "diversity_vs": m.diversity_vs,
            "prior_hits": m.prior_hits,
            "narrow_prior_hits": m.narrow_prior_hits,
            "broad_prior_hits": m.broad_prior_hits,
            "closed_direction_hit": m.closed_direction_hit,
            "score": m.score,
            "basis": m.basis,
        },
        "prior": [
            {"kind": h.kind, "id": h.id, "detail": h.detail, "items": len(h.shared_items)}
            for h in item.prior[:PRIOR_CAP]
        ],
        "prior_total": len(item.prior),
        "recorded_as": None
        if item.recorded_as is None
        else {"lead_id": item.recorded_as.lead_id, "state": item.recorded_as.state},
    }
    c = item.candidate
    if c is not None:
        out["observation"] = c.observation
        out["approaches"] = list(c.approaches)
        out["works"] = [{"work_id": w.work_id, "title": w.title} for w in c.works[:WORK_CAP]]
        out["works_total"] = c.works_total
        out["quotes"] = [
            {
                "role": q.role,
                "work_id": q.work_id,
                "quote": q.quote,
                "anchor": q.anchor,
                "described_as": q.described_as,
            }
            for q in c.quotes[:QUOTE_CAP]
        ]
        out["quotes_total"] = len(c.quotes)
        out["triggers"] = len(c.triggers)
        out["trigger_note"] = c.trigger_note
        out["target_stages"] = list(c.target_stages)
        out["miners"] = list(c.miners)
    return out


def _lineage(project: Project) -> dict[str, int]:
    """Relations and ideas the project holds (lineage), counted from the index."""
    with project.index.connect() as conn:
        relations = conn.execute(
            text("SELECT COUNT(*) FROM relations WHERE status IN ('stated', 'confirmed')")
        ).scalar_one()
        ideas = conn.execute(text("SELECT COUNT(*) FROM ideas")).scalar_one()
    return {"relations": int(relations), "ideas": int(ideas)}


def _leads(project: Project, metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    views = leads_service.list_leads(project)
    by_state: dict[str, list[dict[str, Any]]] = {s: [] for s in LEAD_STATES}
    totals = dict.fromkeys(LEAD_STATES, 0)
    for v in sorted(views, key=lambda x: x.lead_id, reverse=True):
        totals[v.state] += 1
        if len(by_state[v.state]) >= LEAD_CAP:
            continue
        kinds: dict[str, int] = {}
        for t in v.triggers:
            kinds[str(t.kind)] = kinds.get(str(t.kind), 0) + 1
        by_state[v.state].append(
            {
                "lead_id": v.lead_id,
                "text": v.text,
                "framework": v.framework,
                "serves_rq": v.serves_rq,
                "state": v.state,
                "triggers": len(v.triggers),
                "trigger_kinds": dict(sorted(kinds.items())),
                "works": [t.ref for t in v.triggers if str(t.kind) == "work"][:WORK_CAP],
                "prior_total": v.prior_total,
                "decision": v.decision,
                "reason": v.reason,
                "note": v.note,
                "entry": metrics.get(v.lead_id),
            }
        )
    return {"by_state": by_state, "totals": totals, "cap": LEAD_CAP}


def _reviews(project: Project) -> dict[str, list[dict[str, Any]]]:
    """Every recorded review of every hypothesis (eligible or not), oldest first."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT hypothesis_id, h_version, recommend, items_json, critic_model, eligible "
                "FROM hypothesis_reviews ORDER BY event_id"
            )
        ).all()
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        items: dict[str, str] = json.loads(str(r.items_json))
        out.setdefault(str(r.hypothesis_id), []).append(
            {
                "h_version": str(r.h_version),
                "recommend": str(r.recommend),
                "failed": sorted(k for k, v in items.items() if v == "fail"),
                "critic_model": None if r.critic_model is None else str(r.critic_model),
                "eligible": bool(r.eligible),
            }
        )
    return out


def _gates(
    view: hypotheses_service.HypothesisView, reviews: list[dict[str, Any]], *, review_required: bool
) -> list[dict[str, str]]:
    """The gates of one hypothesis, each `pass`, `fail`, `pending` or `n/a`, with a short why."""
    if view.state in ("abandoned", "superseded"):
        return [{"id": "closed", "label": view.state, "status": "n/a", "detail": ""}]
    mine = [r for r in reviews if r["h_version"] == view.h_version and r["eligible"]]
    if mine:
        last = mine[-1]
        if last["recommend"] == "register":
            review = {"status": "pass", "detail": "an independent review recommends registering"}
        else:
            failed = ", ".join(last["failed"])
            review = {
                "status": "fail",
                "detail": f"the latest review says {last['recommend']}"
                + (f"; failed: {failed}" if failed else ""),
            }
    else:
        review = {
            "status": "pending",
            "detail": "no independent review of this version yet"
            + ("" if review_required else " (optional in this mode)"),
        }
    registered = view.registration is not None
    gates = [
        {"id": "review", "label": "Independent review", **review},
        {
            "id": "registration",
            "label": "Registered",
            "status": "pass" if registered else "pending",
            "detail": f"by a {view.autonomy}" if registered and view.autonomy else "",
        },
    ]
    if view.spec.kind == "literature":
        gates.append(
            {
                "id": "cutoff",
                "label": "Model cut-off",
                "status": "fail" if view.flags else "pass",
                "detail": ", ".join(view.flags),
            }
        )
    gates.append(
        {
            "id": "evaluation",
            "label": "Evaluated",
            "status": "pass" if view.state == "evaluated" else "pending",
            "detail": "",
        }
    )
    return gates


DEFAULT_RQ_ID = "default"
DEFAULT_RQ_LABEL = ", ".join(DEFAULT_SERVES_RQ) + " (default)"


def rq_groups(project: Project) -> list[dict[str, Any]]:
    """Leads and hypotheses counted by the question they serve. An item without the field is
    grouped under `default`, labelled "RQ4, RQ5 (default)"; the default group is always listed
    and comes first, the others follow sorted by id."""
    counts: dict[str, dict[str, int]] = {DEFAULT_RQ_ID: {"leads": 0, "hypotheses": 0}}
    for lead in leads_service.list_leads(project):
        key = lead.serves_rq or DEFAULT_RQ_ID
        counts.setdefault(key, {"leads": 0, "hypotheses": 0})["leads"] += 1
    for hyp in hypotheses_service.list_hypotheses(project):
        key = hyp.serves_rq or DEFAULT_RQ_ID
        counts.setdefault(key, {"leads": 0, "hypotheses": 0})["hypotheses"] += 1
    order = [DEFAULT_RQ_ID, *sorted(k for k in counts if k != DEFAULT_RQ_ID)]
    return [
        {
            "id": k,
            "label": DEFAULT_RQ_LABEL if k == DEFAULT_RQ_ID else k,
            **counts[k],
        }
        for k in order
    ]


def _hypotheses(project: Project) -> dict[str, Any]:
    views = hypotheses_service.list_hypotheses(project)
    reviews = _reviews(project)
    required = project_mode(project).value != "exploratory"
    totals = dict.fromkeys(HYPOTHESIS_STATES, 0)
    shown: list[dict[str, Any]] = []
    for v in sorted(views, key=lambda x: x.hypothesis_id, reverse=True):
        totals[v.state] = totals.get(v.state, 0) + 1
        if len(shown) >= HYPOTHESIS_CAP:
            continue
        mine = reviews.get(v.hypothesis_id, [])
        shown.append(
            {
                "hypothesis_id": v.hypothesis_id,
                "h_version": v.h_version,
                "state": v.state,
                "kind": v.spec.kind,
                "statement": v.spec.statement,
                "falsifier": v.falsifier,
                "treatment": v.spec.treatment.name,
                "baseline": v.spec.baseline.name,
                "metric": v.spec.metric.name,
                "lead": v.spec.lead,
                "serves_rq": v.serves_rq,
                "flags": list(v.flags),
                "autonomy": v.autonomy,
                "reviews": len([r for r in mine if r["eligible"]]),
                "reviews_ignored": len([r for r in mine if not r["eligible"]]),
                "last_review": next((r for r in reversed(mine) if r["eligible"]), None),
                "gates": _gates(v, mine, review_required=required),
                "abandon_reason": v.abandon_reason,
                "conclusion": v.conclusion,
            }
        )
    return {"items": shown, "totals": totals, "total": len(views), "cap": HYPOTHESIS_CAP}


def _stages(
    stats: Any, grounding: dict[str, Any], queue: dict[str, Any], hyp: dict[str, Any]
) -> list[dict[str, Any]]:
    """The seven stages with a count and, where it is empty, what is missing and what makes it."""
    cands = grounding["total"]
    prior_leads = sum(1 for e in queue["items"] if e["prior_total"])

    def stage(
        sid: str, label: str, count: int | None, unit: str, missing: str | None, made_by: str
    ) -> dict[str, Any]:
        state = "session" if count is None else "done" if count else "empty"
        return {
            "id": sid,
            "label": label,
            "count": count,
            "unit": unit,
            "state": state,
            "missing": missing if state == "empty" else None,
            "made_by": made_by,
        }

    return [
        stage(
            "grounding",
            "Grounding",
            cands,
            "observations",
            grounding["missing"],
            "the technique miners and the claims miner, read with the claims digest",
        ),
        stage(
            "leads",
            "Leads",
            stats.recorded,
            "leads",
            "no lead is recorded yet",
            "a session running the skill writes leads from the observations you tick",
        ),
        stage(
            "critique",
            "Critique",
            None,
            "",
            None,
            "the session checks its own candidates before showing them; nothing is recorded",
        ),
        stage(
            "prior",
            "Overlap and prior check",
            prior_leads,
            "entries with a prior hit",
            "no listed entry shares a row with an earlier lead, hypothesis or closed direction",
            "computed for every entry of the queue from the recorded leads and directions",
        ),
        stage(
            "ordering",
            "Ordering",
            len(queue["items"]) + len(queue["leads_open"]),
            "ordered entries",
            "nothing to order until observations or open leads exist",
            "computed by the platform from the measures; you choose the order",
        ),
        stage(
            "drafting",
            "Drafting",
            hyp["total"],
            "hypotheses",
            "no hypothesis is drafted; a draft starts from a promoted lead",
            "a session drafts a hypothesis from each lead you promote",
        ),
        stage(
            "review",
            "Review",
            stats.reviews,
            "reviews",
            "no independent review is recorded; a fresh session reviews each draft",
            "a fresh session reviews each draft; you then register or abandon it",
        ),
    ]


class _Scan:
    """The queue and its candidate call, as the payload needs them."""

    def __init__(self, project: Project) -> None:
        from factory.services.lead_candidates import lead_candidates

        found = lead_candidates(project)
        self.queue = lead_queue(project, candidates=found, top=QUEUE_CAP)
        self.totals = found.totals
        self.skipped = found.skipped
        self.miners = found.miners
        self.absence_only_works = found.absence_only_works


def _grounding(scan: _Scan, lineage: dict[str, int]) -> dict[str, Any]:
    totals: dict[str, int] = dict(scan.totals)
    sources = [{"id": k, "total": v} for k, v in totals.items()]
    total = sum(totals.values())
    skipped = [{"id": s.candidate_id, "reason": s.reason} for s in scan.skipped]
    missing: str | None = None
    if not scan.miners:
        missing = "no technique or claims miner has rows; mine the core layer first"
    elif not total:
        missing = "the miners listed give no observation under these settings"
    return {
        "total": total,
        "sources": sources,
        "skipped": skipped,
        "miners": list(scan.miners),
        "absence_only_works": scan.absence_only_works,
        "lineage": lineage,
        "missing": missing,
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `hypotheses` page."""
    project = ctx.project
    scan = _Scan(project)
    queue = scan.queue
    stats = lead_stats(project)
    order = tuple(queue.order_by)
    items = [_entry(i, order) for i in queue.items]
    open_leads = [_entry(i, order) for i in queue.leads]
    metrics = {e["entry_id"]: e for e in open_leads}
    lineage = _lineage(project)
    grounding = _grounding(scan, lineage)
    leads = _leads(project, metrics)
    hyp = _hypotheses(project)
    queue_block = {
        "order_by": list(order),
        "order_rule": queue.order_rule,
        "comparability": queue.comparability,
        "items": items,
        "leads_open": open_leads,
        "total_candidates": queue.total_candidates,
        "shown": len(items),
        "cap": QUEUE_CAP,
        "excluded": len(queue.excluded),
    }
    plan = effective_plan(project)
    return {
        "ready": True,
        "methods": dict(METHODS),
        "notice": NOTICE,
        "skill": RUN_HINT,
        "mode": project_mode(project).value,
        "gates": {
            "lead_decide": gate_policy(project, "hypotheses.lead_decide").kind.value,
            "register": gate_policy(project, "hypotheses.register").kind.value,
            "min_seeds": plan.min_seeds,
        },
        "stages": _stages(stats, grounding, queue_block, hyp),
        "grounding": grounding,
        "queue": queue_block,
        "leads": leads,
        "hypotheses": hyp,
        "rq": rq_groups(project),
        "stats": {
            "recorded": stats.recorded,
            "by_state": dict(stats.by_state),
            "decided": stats.decided,
            "promotion_rate": stats.promotion_rate,
            "decided_promotion_rate": stats.decided_promotion_rate,
            "discard_reasons": dict(stats.discard_reasons),
            "by_source": {k: dict(v) for k, v in stats.by_source.items()},
            "hypotheses_drafted": stats.hypotheses_drafted,
            "hypotheses_by_state": dict(stats.hypotheses_by_state),
            "hypotheses_registered": stats.hypotheses_registered,
            "reviews": stats.reviews,
            "reviews_by_recommendation": dict(stats.reviews_by_recommendation),
            "outcomes": dict(stats.outcomes),
        },
        "empty": not (grounding["total"] or stats.recorded or hyp["total"] or stats.reviews),
        "discard_reasons": [r.value for r in DiscardReason],
        "abandon_reasons": [r.value for r in AbandonReason],
    }


# ---------------------------------------------------------------- the researcher's acts


def _need(body: dict[str, Any], key: str, issues: list[ValidationIssue]) -> str:
    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    issues.append(ValidationIssue(key, "required"))
    return ""


def _optional(body: dict[str, Any], key: str, issues: list[ValidationIssue]) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        issues.append(ValidationIssue(key, "must be text"))
        return None
    return value


def _allowed(body: dict[str, Any], keys: tuple[str, ...], issues: list[ValidationIssue]) -> None:
    issues.extend(ValidationIssue(k, "not accepted") for k in sorted(set(body) - set(keys)))


def decide_lead_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Promote, park or discard a lead (`leads.decide_lead`). `body`: `lead_id`, `decision`
    (`promote`, `park`, `discard`), `reason` (a discard only) and `note`. Raises
    `FactoryValidationError`, nothing written, for a bad body or what the service refuses."""
    issues: list[ValidationIssue] = []
    _allowed(body, ("lead_id", "decision", "reason", "note"), issues)
    lead_id = _need(body, "lead_id", issues)
    decision = _need(body, "decision", issues)
    reason_text = _optional(body, "reason", issues)
    note = _optional(body, "note", issues)
    if decision and decision not in ("promote", "park", "discard"):
        issues.append(ValidationIssue("decision", "must be promote, park or discard"))
    reason: DiscardReason | None = None
    if reason_text:
        try:
            reason = DiscardReason(reason_text)
        except ValueError:
            issues.append(ValidationIssue("reason", "not a known discard reason"))
    if issues:
        raise FactoryValidationError(issues)
    event_id = leads_service.decide_lead(
        project,
        actor,
        lead_id,
        decision,  # type: ignore[arg-type]
        reason,
        note,
    )
    return {"lead_id": lead_id, "decision": decision, "event_id": event_id}


def register_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Register a reviewed hypothesis (`hypotheses.register_hypothesis`, the researcher's gate).
    `body`: `hypothesis_id` only."""
    issues: list[ValidationIssue] = []
    _allowed(body, ("hypothesis_id",), issues)
    hypothesis_id = _need(body, "hypothesis_id", issues)
    if issues:
        raise FactoryValidationError(issues)
    event_id = hypotheses_service.register_hypothesis(project, actor, hypothesis_id)
    return {"hypothesis_id": hypothesis_id, "event_id": event_id}


def abandon_act(project: Project, actor: Actor, body: dict[str, Any]) -> dict[str, object]:
    """Abandon a hypothesis (`hypotheses.abandon_hypothesis`). `body`: `hypothesis_id`, `reason`
    and `note` (all required)."""
    issues: list[ValidationIssue] = []
    _allowed(body, ("hypothesis_id", "reason", "note"), issues)
    hypothesis_id = _need(body, "hypothesis_id", issues)
    reason_text = _need(body, "reason", issues)
    note = _need(body, "note", issues)
    reason: AbandonReason | None = None
    if reason_text:
        try:
            reason = AbandonReason(reason_text)
        except ValueError:
            issues.append(ValidationIssue("reason", "not a known abandon reason"))
    if issues or reason is None:
        raise FactoryValidationError(issues)
    event_id = hypotheses_service.abandon_hypothesis(project, actor, hypothesis_id, reason, note)
    return {"hypothesis_id": hypothesis_id, "event_id": event_id}


def _decide_command(body: dict[str, Any]) -> str | None:
    decision = body.get("decision")
    return f"cli:leads {decision}" if decision in ("promote", "park", "discard") else None


ACTS: Final[
    dict[
        str,
        tuple[
            Callable[[dict[str, Any]], str | None],
            Callable[[Project, Actor, dict[str, Any]], dict[str, object]],
        ],
    ]
] = {
    "/ui/act/lead-decide": (_decide_command, decide_lead_act),
    "/ui/act/hypothesis-register": (lambda _b: "cli:hypotheses register", register_act),
    "/ui/act/hypothesis-abandon": (lambda _b: "cli:hypotheses abandon", abandon_act),
}
"""Route -> (the CLI command a request is authorised as, or None for a bad body; the act)."""
