"""The live dashboard's state: one JSON-serialisable dict built from the index (slice 8, phase I).

Invariants:
- Read-only. Every panel calls an existing read service; nothing here opens a transaction that
  writes, and no event file is read. The index is synced by those services, never written here.
- Each panel is optional: absent data gives an empty panel, and a panel that cannot be built gives
  an empty one with a short `error` note. The state is never an error as a whole.
- Development-only view (R-20, decision 37 item 9): the whole state passes through `withhold` with
  every held-out seed's own id and stated identifiers; works are not masked. Label-derived rates
  (calibration sensitivity, false-exclusion, extraction audit error rate) are left out, and the
  search report is the agent variant (import rows collapsed before a pass opens).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import cast

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.model.screening import PassLabel
from factory.services import agent_view as agent_view_service
from factory.services import budgets as budgets_service
from factory.services import decisions as decisions_service
from factory.services import dedup as dedup_service
from factory.services import extraction as extraction_service
from factory.services import extraction_audit as extraction_audit_service
from factory.services import ledger as ledger_service
from factory.services import protocol as protocol_service
from factory.services import question as question_service
from factory.services import ranking as ranking_service
from factory.services import screening as screening_service
from factory.services import screening_check as check_service
from factory.services.context import Project
from factory.services.withholding import held_out_tokens, withhold

LEVELS = ("goal", "questions", "plan", "seeds", "probe", "protocol")

SECTIONS: tuple[tuple[str, str, dict[str, tuple[str, ...] | None]], ...] = (
    ("question", "Question", {"questions": None}),
    (
        "criteria",
        "Criteria",
        {
            "protocol": (
                "inclusion-criteria",
                "exclusion-criteria",
                "exclusion-criteria-first",
                "non-goal-exclusions",
            )
        },
    ),
    (
        "sources",
        "Sources and queries",
        {"protocol": ("sources", "language"), "probe": None, "seeds": None},
    ),
    (
        "screening",
        "Screening",
        {
            "protocol": (
                "screening-stages",
                "screening-plan",
                "setting",
                "screener-tuning",
                "model-choice",
                "ordering",
            )
        },
    ),
    (
        "extraction",
        "Extraction",
        {"protocol": ("tooling", "extraction-fields", "comparability-keys")},
    ),
    (
        "snowball",
        "Snowballing",
        {
            "protocol": (
                "backward-snowballing",
                "forward-snowballing",
                "forward-topic-filter",
            )
        },
    ),
    ("background", "Goal and plan", {"goal": None, "plan": None}),
)
"""The protocol sections of the page: which decisions (by level, and by subject where listed)
stand behind each. A decision in none of them lands in `other:<level>`."""

Panel = dict[str, JsonValue]


def dashboard_state(project: Project) -> dict[str, JsonValue]:
    """The whole dashboard state of `project`, as JSON-ready data with held-out ids withheld."""
    status = _guard(lambda: _status(project), {})
    state: dict[str, JsonValue] = {
        "meta": _meta(project, status),
        "levels": list(LEVELS),
        "sections": [[key, title] for key, title, _ in SECTIONS],
        "decisions": _guard(lambda: _decisions(project), []),
        "protocol": _guard(lambda: _protocol(project), {}),
        "question": _guard(lambda: _question(project), {}),
        "press": _guard(lambda: _press(project), []),
        "probes": _guard(lambda: _probes(project), []),
        "search": _guard(lambda: _search(project), {}),
        "dedup": _guard(lambda: _dedup(project), {}),
        "screening": _guard(lambda: _screening(project, status), {}),
        "extraction": _guard(lambda: _extraction(project), {}),
        "cost": _guard(lambda: _cost(project, status), {}),
    }
    return cast(
        dict[str, JsonValue],
        withhold(state, held_out_tokens(project, include_work_ids=False)),
    )


def _guard(build: Callable[[], JsonValue], empty: JsonValue) -> JsonValue:
    """`build()`, or `empty` (with an `error` note in a dict) when the data is absent or refused."""
    try:
        return build()
    except FactoryValidationError as exc:
        note = "; ".join(f"{i.field}: {i.reason}" for i in exc.issues)
    except Exception as exc:  # a panel must never take the page down
        note = f"{type(exc).__name__}: {exc}"
    return {"error": note[:300]} if isinstance(empty, dict) else empty


def _status(project: Project) -> JsonValue:
    return agent_view_service.status_view(project)


def _dict(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _meta(project: Project, status: JsonValue) -> JsonValue:
    data = _dict(status)
    return {
        "slug": project.paths.slug,
        "generated_at": project.clock.now().isoformat(),
        "last_event_id": project.index.last_event_id(),
        "events_total": data.get("events_total"),
        "last_event_at": data.get("last_event_at"),
        "created_at": data.get("created_at"),
        "rigor_mode": data.get("rigor_mode"),
        "stage": data.get("stage"),
    }


def _section_of(level: str, subject: str) -> str:
    for key, _, mapping in SECTIONS:
        if level in mapping:
            subjects = mapping[level]
            if subjects is None or subject in subjects:
                return key
    return f"other:{level}"


def _decisions(project: Project) -> JsonValue:
    rows: list[JsonValue] = []
    for row in decisions_service.list_decisions(project):
        view = decisions_service.view_decision(project, row.decision_id)
        data = view.model_dump(mode="json")
        data["section"] = _section_of(view.level, view.subject)
        rows.append(data)
    rows.sort(key=lambda d: (str(_dict(d).get("suggested_at")), str(_dict(d).get("decision_id"))))
    return rows


def _protocol(project: Project) -> JsonValue:
    return protocol_service.protocol_view(project).model_dump(mode="json")


def _question(project: Project) -> JsonValue:
    return question_service.question_view(project).model_dump(mode="json")


def _press(project: Project) -> JsonValue:
    """Every PRESS review with its findings and, once confirmed, the responses, from the index."""
    import json

    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT review_id, protocol_id, findings, responses, event_id "
                "FROM press_reviews ORDER BY event_id"
            )
        ).all()
    out: list[JsonValue] = []
    for review_id, protocol_id, findings, responses, event_id in rows:
        out.append(
            {
                "review_id": str(review_id),
                "protocol_id": str(protocol_id),
                "findings": json.loads(str(findings)),
                "responses": [] if responses is None else json.loads(str(responses)),
                "confirmed": responses is not None,
                "event_id": str(event_id),
            }
        )
    return out


def _probes(project: Project) -> JsonValue:
    """Probe rounds from the index: per query the reported count and the seed-recall counts of the
    development seeds only (held-out ids are withheld by the final pass)."""
    import json

    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT probe_id, query_id, source, status, reported_count, reason, payload, "
                "event_id FROM probes ORDER BY event_id"
            )
        ).all()
        queries = {
            str(q): str(t)
            for q, t in conn.execute(text("SELECT query_id, text FROM queries")).all()
        }
    rounds: dict[str, dict[str, JsonValue]] = {}
    for probe_id, query_id, source, status, count, reason, payload, event_id in rows:
        entry = rounds.setdefault(
            str(probe_id), {"probe_id": str(probe_id), "event_id": str(event_id), "queries": []}
        )
        measured = json.loads(str(payload)) if status == "measured" else {}
        row: dict[str, JsonValue] = {
            "query_id": str(query_id),
            "source": str(source),
            "failed": status != "measured",
            "reason": None if reason is None else str(reason)[:200],
            "reported_count": None if count is None else int(count),
            "text": queries.get(str(query_id), ""),
            "development_retrieved": len(measured.get("development_retrieved", [])),
            "development_tested": len(measured.get("development_tested", [])),
            "negatives_retrieved": len(measured.get("negatives_retrieved", [])),
        }
        cast(list[JsonValue], entry["queries"]).append(row)
    out: list[JsonValue] = []
    for number, entry in enumerate(rounds.values(), 1):
        entry["round"] = number
        out.append(entry)
    return out


def _search(project: Project) -> JsonValue:
    """The agent variant of the PRISMA flow and search report, plus per-source query counts."""
    view = _dict(agent_view_service.prisma_view(project))
    report = _dict(view.get("search"))
    rows = report.get("rows")
    per_source: dict[str, dict[str, int]] = {}
    complete = partial = 0
    for row in rows if isinstance(rows, list) else []:
        r = _dict(row)
        source = str(r.get("source"))
        slot = per_source.setdefault(source, {"queries": 0, "retrieved": 0})
        slot["queries"] += 1
        retrieved = r.get("retrieved")
        slot["retrieved"] += retrieved if isinstance(retrieved, int) else 0
        runs = r.get("runs")
        for run in runs if isinstance(runs, list) else []:
            status = _dict(run).get("status")
            complete += status == "complete"
            partial += status == "partial"
    flow = _dict(view.get("flow"))
    identified: dict[str, JsonValue] = {
        "databases": flow.get("identified_databases", {}),
        "other": flow.get("identified_other", {}),
        "duplicates_removed": flow.get("duplicates_removed"),
    }
    return {
        "per_source": cast(JsonValue, per_source),
        "runs_complete": complete,
        "runs_partial": partial,
        "identification": identified,
        "rows": rows if isinstance(rows, list) else [],
        "press_confirmed": report.get("press_confirmed"),
    }


def _dedup(project: Project) -> JsonValue:
    merges = dedup_service.list_merges(project, named=False)
    return {
        "merges": len(merges),
        "active": sum(1 for m in merges if m.status.value == "active"),
        "reverted": sum(1 for m in merges if m.status.value != "active"),
        "by_rule": cast(JsonValue, dict(Counter(m.rule for m in merges))),
        "records_merged": sum(m.records for m in merges),
    }


def _screening(project: Project, status: JsonValue) -> JsonValue:
    screening = _dict(_dict(status).get("screening"))
    ranking = ranking_service.latest_ranking(project, top=0)
    stops: list[JsonValue] = []
    for stop in screening_service.screening_stops(project):
        row = stop.model_dump(mode="json")
        row["progress"] = f"{stop.run} / {stop.n}"
        stops.append(row)
    passes = _dict(screening.get("passes"))
    left = _dict(passes.get(PassLabel.A.value)).get("remaining")
    checks: list[JsonValue] = []
    for summary in check_service.check_list(project):
        report = check_service.check_report(project, summary.draw_id, kind=summary.kind)
        checks.append(
            {
                "draw_id": summary.draw_id,
                "kind": summary.kind.value,
                "name": summary.name,
                "drawn": summary.drawn,
                "labelled": summary.labelled,
                "current": summary.current,
                "agreement": None if report is None else report.agreement,
                "agreement_note": None if report is None else report.agreement_note,
                "bands": []
                if report is None
                else [row.model_dump(mode="json") for row in report.rows],
                "disagreements": 0 if report is None else len(report.disagreements),
            }
        )
    calibration = _dict(screening.get("calibration"))
    return {
        "ranking": None
        if ranking is None
        else {
            "ranking_id": ranking.ranking_id,
            "model_id": ranking.model_id,
            "weights_hash": ranking.weights_hash,
            "software": ranking.software,
            "count": ranking.count,
        },
        "passes": passes,
        "full_text_passes": screening.get("full_text_passes"),
        "stops": stops,
        "records_left": left,
        "calibration": {
            "drawn": calibration.get("drawn"),
            "labelled": calibration.get("labelled"),
            "required": calibration.get("required"),
            "passed": calibration.get("passed"),
        },
        "stale_decisions": screening.get("stale_decisions"),
        "checks": checks,
    }


def _extraction(project: Project) -> JsonValue:
    units = extraction_service.unit_states(project)
    by_state = dict(Counter(unit.state for unit in units))
    out: dict[str, JsonValue] = {
        "units": len(units),
        "by_state": cast(JsonValue, by_state),
        "papers": len({unit.work_id for unit in units}),
    }
    rows = _guard(lambda: _row_count(project), None)
    out["rows"] = rows
    out["agreement"] = _guard(lambda: _agreement(project), {})
    audit = extraction_audit_service.extraction_audit_report(project)
    out["audit"] = (
        None
        if audit is None
        else {
            "audit_id": audit.audit_id,
            "sample_size": audit.sample_size,
            "labelled": audit.labelled,
            "outdated": audit.outdated,
        }
    )
    return out


def _row_count(project: Project) -> JsonValue:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM extraction_rows")).scalar_one())


def _agreement(project: Project) -> JsonValue:
    from factory.services import extraction_agreement as agreement_service

    result = agreement_service.extraction_agreement(project, project.human_actor())
    return {
        "dual_works": result.dual_works,
        "rows_aligned": result.rows_aligned,
        "overall": result.overall,
        "rates": [rate.model_dump(mode="json") for rate in result.rates],
        "unresolved": len(result.disagreements),
        "resolved": result.resolved,
        "single_extraction": len(result.single_extraction),
    }


def _cost(project: Project, status: JsonValue) -> JsonValue:
    data = _dict(status)
    budget = budgets_service.budget_status(project).model_dump(mode="json")
    ledger = ledger_service.ledger_report(project).ledger
    per_stage: Counter[str] = Counter()
    per_model: dict[str, dict[str, JsonValue]] = {}
    for agent in ledger.agents:
        for kind, count in agent.by_type.items():
            per_stage[kind.split(".")[0]] += count
        slot = per_model.setdefault(
            agent.model or "unknown",
            {"events": 0, "first": agent.first.isoformat(), "last": agent.last.isoformat()},
        )
        slot["events"] = cast(int, slot["events"]) + agent.events
        slot["first"] = min(str(slot["first"]), agent.first.isoformat())
        slot["last"] = max(str(slot["last"]), agent.last.isoformat())
    return {
        "budget": budget,
        "events_by_type": data.get("events_by_type", {}),
        "events_per_stage": cast(JsonValue, dict(per_stage)),
        "per_model": cast(JsonValue, per_model),
        "first_event_at": data.get("created_at"),
        "last_event_at": data.get("last_event_at"),
    }
