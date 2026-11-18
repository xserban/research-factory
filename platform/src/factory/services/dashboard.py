"""The live dashboard's state: one JSON-serialisable dict built from the index (slice 8, phase I).

Invariants:
- Read-only, but for deleting expired ephemeral progress files (`.progress/`, never events). Every
  panel calls an existing read service; nothing here opens a transaction that writes, and no event
  file is read. The index is synced by those services, never written here.
- Each panel is optional: absent data gives an empty panel, and a panel that cannot be built gives
  an empty one with a short `error` note. The state is never an error as a whole.
- The feed panel (`feed`) is None without a feed configuration. Its runs are read with
  `reconcile=False`, so an open run whose process is gone shows as `lost?` and nothing is written.
  Each part of it is read on its own: a part that raises a `FactoryError` is `unavailable`.
- Development-only view (R-20, decision 37 item 9): the whole state passes through `withhold` with
  every held-out seed's own id and stated identifiers; works are not masked. Label-derived rates
  (calibration sensitivity, false-exclusion, extraction audit error rate) are left out, and the
  search report is the agent variant (import rows collapsed before a pass opens).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services import agent_view as agent_view_service
from factory.services import agreement as agreement_service
from factory.services import budgets as budgets_service
from factory.services import conversion_coverage as conversion_coverage_service
from factory.services import decisions as decisions_service
from factory.services import dedup as dedup_service
from factory.services import extraction as extraction_service
from factory.services import extraction_audit as extraction_audit_service
from factory.services import feed as feed_service
from factory.services import feed_read as feed_read_service
from factory.services import ledger as ledger_service
from factory.services import miner_info as miner_info_service
from factory.services import mining as mining_service
from factory.services import pipeline as pipeline_service
from factory.services import progress as progress_service
from factory.services import protocol as protocol_service
from factory.services import question as question_service
from factory.services import ranking as ranking_service
from factory.services import resume as resume_service
from factory.services import runner as runner_service
from factory.services import screening as screening_service
from factory.services import screening_check as check_service
from factory.services import site as site_service
from factory.services import site_progress
from factory.services import work_queue as work_queue_service
from factory.services.call_memo import entering
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
    """The whole dashboard state of `project`, as JSON-ready data with held-out ids withheld.

    Built inside one index snapshot, so live screeners do not make each read queue on the lock.
    """
    with project.index.snapshot(), entering():
        return _dashboard_state(project)


DASHBOARD_PARTS: Final = 17
"""The `_guard`ed parts `_dashboard_state` builds, in order: the steps of its build progress."""


def _dashboard_state(project: Project) -> dict[str, JsonValue]:
    _DONE.set(0)
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
        "screening_live": _guard(lambda: _live_raw(project), {}),
        "extraction": _guard(lambda: _extraction(project), {}),
        "conversion": _guard(lambda: _conversion(project), {}),
        "miners": _guard(lambda: _miners(project), []),
        "products": _guard(lambda: _products(project), []),
        "cost": _guard(lambda: _cost(project, status), {}),
        "progress": _guard(lambda: cast(JsonValue, progress_service.progress_list(project)), []),
        "feed": _guard(lambda: _feed(project), {"error": UNAVAILABLE}),
    }
    live = state["screening_live"]
    if isinstance(live, dict) and "error" not in live:
        screening = state["screening"]
        live["remaining"] = screening.get("records_left") if isinstance(screening, dict) else None
    return cast(
        dict[str, JsonValue],
        withhold(state, held_out_tokens(project, include_work_ids=False)),
    )


def screening_live(project: Project) -> dict[str, JsonValue]:
    """The live screening panel alone, withheld like the whole state (the light endpoint)."""
    with project.index.snapshot():
        panel = _guard(lambda: _live_raw(project), {})
    return cast(
        dict[str, JsonValue],
        withhold(panel, held_out_tokens(project, include_work_ids=False)),
    )


_DONE: ContextVar[int] = ContextVar("dashboard_parts_done", default=0)
_DEPTH: ContextVar[int] = ContextVar("dashboard_guard_depth", default=0)


def _guard(build: Callable[[], JsonValue], empty: JsonValue) -> JsonValue:
    """`build()`, or `empty` (with an `error` note in a dict) when the data is absent or refused.
    Each call is one step of the build progress (`site_progress`; a no-op outside a site build)."""
    _DEPTH.set(_DEPTH.get() + 1)
    try:
        return build()
    except FactoryValidationError as exc:
        note = "; ".join(f"{i.field}: {i.reason}" for i in exc.issues)
    except Exception as exc:  # a panel must never take the page down
        note = f"{type(exc).__name__}: {exc}"
    finally:
        _DEPTH.set(_DEPTH.get() - 1)
        if _DEPTH.get() == 0:  # only the top-level parts are steps; some parts guard inner reads
            _DONE.set(_DONE.get() + 1)
            site_progress.report(min(_DONE.get(), DASHBOARD_PARTS), DASHBOARD_PARTS, "sections")
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
        "cannot_assess": _part(lambda: _cannot_assess(project)),
    }


def _cannot_assess(project: Project) -> JsonValue:
    """The unresolved full-text cannot-assess works with each pass's decision and the read and
    resolve commands (IDEA-67); empty without a full-text plan. Read-only; it blocks nothing."""
    protocol = protocol_service.current_protocol(project)
    if protocol is None or protocol.spec.full_text_screening is None:
        return []
    queue = agreement_service.cannot_assess_queue(project, stage=ScreeningStage.FULL_TEXT)
    return [item.model_dump(mode="json") for item in queue]


FEED_TOP = 5
FEED_ACTIVITY = timedelta(days=7)
UNAVAILABLE = "unavailable"


def _part(build: Callable[[], JsonValue]) -> JsonValue:
    """`build()`, or the word `unavailable` when a read refuses with a `FactoryError`."""
    try:
        return build()
    except FactoryError:
        return UNAVAILABLE


def _feed(project: Project) -> JsonValue:
    """The feed and work-queue panel, or None when the project has no feed configuration."""
    config = feed_service.current_config(project)
    if config is None:
        return None
    now = project.clock.now()
    return {
        "categories": list(config.categories),
        "shown_per_cycle": config.shown_per_cycle,
        "interval_days": config.interval_days,
        "fetch": _part(lambda: _feed_fetch(project, config.interval_days, now)),
        "ranking": _part(lambda: _feed_ranking(project)),
        "top": _part(lambda: _feed_top(project, now)),
        "queue": _part(lambda: _feed_queue(project)),
        "run": _part(lambda: _feed_run(project)),
        "interrupted": _interrupted(project),
    }


def _interrupted(project: Project) -> JsonValue:
    """The counts of interrupted work per category (`resume.interrupted`, read-only), or the word
    `unavailable` when the read fails."""
    try:
        found = resume_service.interrupted(project)
    except Exception:  # a panel must never take the page down
        return UNAVAILABLE
    return {
        "clean": found.is_clean,
        "runs": len(found.runs),
        "pipelines": len(found.pipelines),
        "leases": sum(lease.count for lease in found.leases),
        "passes": len(found.passes),
        "resolve": found.automatic.resolve,
        "fetch": found.automatic.fetch,
        "convert": found.automatic.convert,
        "limit_runs": [
            {
                "stage": run.stage,
                "reset": run.limit_reset_at or run.limit_reset_text,
                "estimated": run.limit_reset_estimated,
            }
            for run in found.runs
            if run.kind == "limit"
        ],
        "details": _interrupted_details(found),
    }


def _interrupted_details(found: resume_service.Interrupted) -> list[JsonValue]:
    """One line per interrupted run, pipeline, expired lease kind and stale pass, so the panel
    names the work and not only the counts (IDEA-63 item 2)."""
    rows: list[tuple[str, str, str]] = []
    rows += [("run", r.run_id, f"{r.stage}, {r.kind}") for r in found.runs]
    rows += [
        ("pipeline", p.pipeline_id, f"{p.kind}, left: {', '.join(p.stages_left) or 'none'}")
        for p in found.pipelines
    ]
    rows += [("lease", lease.kind, f"{lease.count} expired") for lease in found.leases]
    rows += [
        (
            "pass",
            f"{s.module} {s.label}",
            f"{s.stage or s.scope or 'all'}, {s.pending} pending",
        )
        for s in found.passes
    ]
    return [{"category": c, "id": i, "text": t} for c, i, t in rows]


def _feed_fetch(project: Project, interval_days: int, now: datetime) -> JsonValue:
    """The last complete fetch window, the next due day and whether a run is due now."""
    project.index.sync()
    status = feed_service.feed_status(project, today=now.date())
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT window_from, window_to FROM feed_fetches WHERE complete = 1 "
                "ORDER BY event_id DESC LIMIT 1"
            )
        ).first()
    last_to = status.last_complete_window_to
    return {
        "last_window_from": None if row is None else str(row[0]),
        "last_window_to": None if row is None else str(row[1]),
        "next_due": None
        if last_to is None
        else (last_to + timedelta(days=interval_days)).isoformat(),
        "due": status.due,
    }


def _feed_ranking(project: Project) -> JsonValue:
    """The latest ranking's shown and exploration counts, as the ranking recorded them."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT ranking_id, shown FROM feed_rankings ORDER BY event_id DESC LIMIT 1")
        ).first()
    if row is None:
        return {"ranking_id": None, "shown": 0, "explore": 0}
    shown = json.loads(str(row[1]))
    return {
        "ranking_id": str(row[0]),
        "shown": len(shown),
        "explore": sum(1 for item in shown if item.get("explore") is True),
    }


def _feed_activity(project: Project, now: datetime) -> tuple[Counter[str], Counter[str]]:
    """Reactions and sends per entry within the last `FEED_ACTIVITY`, by event time."""
    project.index.sync()
    with project.index.connect() as conn:
        reacted = conn.execute(
            text(
                "SELECT r.entry_id, ev.ts FROM feed_reactions r "
                "JOIN events ev ON ev.id = r.event_id"
            )
        ).all()
        sent = conn.execute(
            text("SELECT s.entry_id, ev.ts FROM feed_sends s JOIN events ev ON ev.id = s.event_id")
        ).all()
    since = now - FEED_ACTIVITY

    def within(rows: list[tuple[object, ...]]) -> Counter[str]:
        counts: Counter[str] = Counter()
        for entry_id, ts in rows:
            stamp = _parse_ts(str(ts))
            if stamp is not None and since <= stamp <= now:
                counts[str(entry_id)] += 1
        return counts

    return within(list(reacted)), within(list(sent))


def _feed_top(project: Project, now: datetime) -> JsonValue:
    """The top shown titles with score, reaction, sent state and 7-day reaction and add counts."""
    listing = feed_read_service.feed_list(project, top=FEED_TOP)
    reactions, adds = _feed_activity(project, now)
    return [
        {
            "entry_id": item.entry_id,
            "title": item.title,
            "score": item.score,
            "reaction": None if item.reaction is None else item.reaction.value,
            "sent": item.sent,
            "reactions_7d": reactions.get(item.entry_id, 0),
            "adds_7d": adds.get(item.entry_id, 0),
        }
        for item in listing.items
    ]


def _feed_queue(project: Project) -> JsonValue:
    """Added papers per stage and the open units per task kind."""
    queue = work_queue_service.queue(project)
    stages: Counter[str] = Counter(item.stage for item in queue.items)
    return {
        "added": len(queue.items),
        "stages": cast(JsonValue, dict(stages)),
        "pending": cast(JsonValue, queue.pending),
    }


def _feed_run(project: Project) -> JsonValue:
    """The last runner run (stage, outcome, finished time) and whether a run or pipeline is open.
    Read with `reconcile=False`, so nothing is written."""
    last: JsonValue = None
    views = runner_service.run_status(project, reconcile=False, limit=1)
    if views:
        view = views[0]
        with project.index.connect() as conn:
            finished = conn.execute(
                text(
                    "SELECT ev.ts FROM runner_runs r "
                    "LEFT JOIN events ev ON ev.id = r.finished_event_id WHERE r.run_id = :r"
                ),
                {"r": view.run_id},
            ).first()
        last = {
            "stage": view.stage,
            "outcome": view.status,
            "finished_at": None if finished is None or finished[0] is None else str(finished[0]),
        }
    pipelines = pipeline_service.pipeline_status(project, limit=1)
    return {
        "last": last,
        "run_open": runner_service.has_open_run(project),
        "pipeline_open": any(p.status == "running" for p in pipelines),
    }


RECENT_LIMIT = 50
SESSION_WINDOW = timedelta(minutes=60)
ACTIVE_WITHIN = timedelta(minutes=3)
_QUOTE_CAP = 200
_RATIONALE_CAP = 160
_CRITERION_ID = re.compile(r"[A-Za-z]+\d+")


def _clip(value: object, cap: int) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned if len(cleaned) <= cap else cleaned[: cap - 1] + "\u2026"


def _bare_criterion(value: object) -> str | None:
    if not value:
        return None
    found = _CRITERION_ID.search(str(value))
    return found.group(0) if found else str(value)


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


_LIVE_SQL = (
    "SELECT d.decision_id, d.work_id, d.pass_label, d.verdict, d.score, d.criterion, d.quote, "
    "d.rationale, d.protocol_id, d.superseded_by, e.ts, e.session, e.actor_id, "
    "json_extract(w.data, '$.title') AS title "
    "FROM decisions d JOIN events e ON e.id = d.event_id "
    "LEFT JOIN works w ON w.work_id = d.work_id "
    "WHERE d.stage = :stage AND d.phase = :phase ORDER BY d.event_id DESC LIMIT :limit"
)


def _live_raw(project: Project) -> JsonValue:
    """Title/abstract screening-phase decisions as the index holds them: the latest 50 live ones
    under the current protocol lineage, per-session rates over the last hour, live totals and the
    stop rules. Read-only; `remaining` is filled by the caller when the full state is built."""
    project.index.sync()
    current = protocol_service.current_protocol(project)
    lineage = (
        protocol_service.lineage_through(project, current.protocol_id) if current else frozenset()
    )
    now = project.clock.now()
    with project.index.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                text(_LIVE_SQL),
                {"stage": ScreeningStage.TITLE_ABSTRACT.value, "phase": "screening", "limit": 3000},
            )
            .mappings()
            .all()
        ]
    live = [r for r in rows if r["superseded_by"] is None and r["protocol_id"] in lineage]
    recent = [
        {
            "decision_id": r["decision_id"],
            "ts": r["ts"],
            "pass": r["pass_label"],
            "session": str(r["session"])[-8:],
            "actor": r["actor_id"],
            "title": r["title"],
            "verdict": r["verdict"],
            "score": r["score"],
            "criterion": _bare_criterion(r["criterion"]),
            "quote": _clip(r["quote"], _QUOTE_CAP),
            "rationale": _clip(r["rationale"], _RATIONALE_CAP),
        }
        for r in live[:RECENT_LIMIT]
    ]
    spans: dict[str, list[tuple[datetime, str]]] = {}
    actors: dict[str, str] = {}
    for r in rows:
        stamp = _parse_ts(str(r["ts"]))
        if stamp is not None and now - stamp <= SESSION_WINDOW:
            spans.setdefault(str(r["session"]), []).append((stamp, str(r["verdict"])))
            actors.setdefault(str(r["session"]), str(r["actor_id"]))
    sessions: list[dict[str, JsonValue]] = []
    for session, items in spans.items():
        times = [t for t, _ in items]
        first, last = min(times), max(times)
        span = max((last - first).total_seconds(), 1.0)
        sessions.append(
            {
                "session": session[-8:],
                "actor": actors[session],
                "decisions": len(items),
                "includes": sum(1 for _, v in items if v == "include"),
                "last_at": last.isoformat(),
                "rate_per_minute": round(len(items) / span * 60, 2) if len(items) > 1 else None,
                "active": now - last < ACTIVE_WITHIN,
            }
        )
    sessions.sort(key=lambda x: str(x["last_at"]), reverse=True)
    totals: dict[str, dict[str, int]] = {}
    for r in live:
        slot = totals.setdefault(str(r["pass_label"]), {})
        slot[str(r["verdict"])] = slot.get(str(r["verdict"]), 0) + 1
    stops: list[JsonValue] = []
    for stop in screening_service.screening_stops(project):
        row = stop.model_dump(mode="json")
        row["progress"] = f"{stop.run} / {stop.n}"
        stops.append(row)
    return {
        "recent": cast(JsonValue, recent),
        "sessions": cast(JsonValue, sessions),
        "totals": cast(JsonValue, totals),
        "stops": stops,
        "remaining": None,
        "any_active": any(bool(s["active"]) for s in sessions),
    }


def _conversion(project: Project) -> JsonValue:
    return cast(JsonValue, conversion_coverage_service.panel(project))


def _miners(project: Project) -> JsonValue:
    """Every listed miner's units and rows, with its spec and use described. Agreement is left
    out: computing it for every miner takes tens of seconds on a full project, so it belongs to
    the hub's Miners product."""
    out: list[JsonValue] = []
    for s in mining_service.mine_status(project, with_agreement=False):
        row = s.model_dump(mode="json")
        row["detail"] = miner_info_service.miner_detail(project, s.name, s.version)
        out.append(cast(JsonValue, row))
    return out


def _products(project: Project) -> JsonValue:
    """Every product of the site hub with its build time and staleness (no product is built)."""
    return [cast(JsonValue, s.model_dump(mode="json")) for s in site_service.status(project)]


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
