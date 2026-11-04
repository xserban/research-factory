"""The PRISMA 2020 flow and the PRISMA-S search report, computed from events (R-05, flow 11).

Both are read-only. Each number is computed here from the projection and the event-derived
services; no caller can set one. Counts follow plan 5b ruling 2 and decision #38.6:

- `identified_databases`: records parsed by `search`-purpose runs, per source. Probe runs never
  count.
- `identified_other`: canonical works with no `database` provenance, each counted once, keyed by
  the highest-precedence method among their provenance (citation-chase, seed-admission,
  hand-search).
- `duplicates_removed`: database records less the canonical works that have database provenance.
- `screened`: canonical works. The live canonical set comes from `dedup.canonical_works`, so a
  reverted merge is reflected at once.
- `excluded` / `included` / `pending`: the final outcome of each canonical work, read from
  `agreement.final_outcomes`, which gives a calibration work its human label. `excluded` is
  broken down by the criterion the work was excluded under; `pending` covers works whose
  decisions are stale under the current protocol. The report is `provisional` while pending > 0.

Invariants, enforced by `PrismaFlow`:
- sum(identified_databases) + sum(identified_other) - duplicates_removed == screened
- sum(excluded) + pending + included == screened
"""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import text

from factory.clock import parse_ts
from factory.errors import FactoryError
from factory.model.base import StrictModel
from factory.model.protocol import Limit, ProtocolSpec, ScreeningStage, search_strategy_hash
from factory.model.search import QueryKind, QueryPurpose, RunStatus
from factory.model.work import ProvenanceMethod, Work
from factory.services.agreement import Outcome, exclusion_criteria, final_outcomes
from factory.services.context import Project
from factory.services.dedup import canonical_works
from factory.services.fulltext_screening import fulltext_queue
from factory.services.fulltext_status import fulltext_status
from factory.services.protocol import current_protocol, registered_deviation
from factory.services.search import RunSummary

UNSOUGHT = "unsought"
UNCONVERTED = "unconverted"
UNSPECIFIED = "unspecified"
"""The exclusion bucket for an excluded work that cites no criterion (not expected to occur)."""

OTHER_METHODS: tuple[ProvenanceMethod, ...] = (
    ProvenanceMethod.CITATION_CHASE,
    ProvenanceMethod.SEED_ADMISSION,
    ProvenanceMethod.HAND_SEARCH,
)
"""Non-database methods in precedence order: a work counts under the first one it carries."""


class FullTextBoxes(StrictModel):
    """The full-text boxes of the flow (spec acceptance 13), all derived from events.

    `sought` is the works promoted at title/abstract; `not_retrieved` those with no converted live
    document (plan 2C ruling 3); `eligible` the rest. `not_retrieved_reasons` counts each
    not-retrieved work once, under the `"<route>: <reason>"` of its latest attempt (event order),
    `unsought` (no attempt) or `unconverted` (a live document with no conversion: run
    `factory document convert`), so its values sum to `not_retrieved`. `failed_attempts_by_route`
    counts attempts, not works: the latest reason of every route that failed for those works.

    `stage_run` is a display switch: False while the protocol declares no full-text plan or no
    full-text decision exists, when `assessed`, `included` and `excluded` are 0 and every eligible
    work is pending.

    Invariants: sought == not_retrieved + eligible; eligible == assessed + pending; assessed ==
    included + sum(excluded); provisional exactly while pending > 0.
    """

    sought: int
    not_retrieved: int
    not_retrieved_reasons: dict[str, int]
    failed_attempts_by_route: dict[str, int] = Field(default_factory=dict)
    eligible: int
    assessed: int
    excluded: dict[str, int]
    pending: int
    included: int
    stage_run: bool
    provisional: bool

    @property
    def excluded_total(self) -> int:
        return sum(self.excluded.values())

    @model_validator(mode="after")
    def _identities_hold(self) -> "FullTextBoxes":
        if self.sought != self.not_retrieved + self.eligible:
            raise ValueError("sought must equal not retrieved plus eligible")
        if sum(self.not_retrieved_reasons.values()) != self.not_retrieved:
            raise ValueError("not-retrieved reasons must count each not-retrieved work once")
        if self.eligible != self.assessed + self.pending:
            raise ValueError("eligible must equal assessed plus pending")
        if self.assessed != self.included + self.excluded_total:
            raise ValueError("assessed must equal included plus excluded")
        if self.provisional != (self.pending > 0):
            raise ValueError("full-text boxes are provisional exactly while works are pending")
        if not self.stage_run and self.assessed:
            raise ValueError("a full-text stage that has not run has assessed nothing")
        return self


NOT_RUN_BOXES = FullTextBoxes(
    sought=0,
    not_retrieved=0,
    not_retrieved_reasons={},
    eligible=0,
    assessed=0,
    excluded={},
    pending=0,
    included=0,
    stage_run=False,
    provisional=False,
)
"""The boxes of a flow built without any: nothing sought, nothing assessed."""


class PrismaFlow(StrictModel):
    """The PRISMA 2020 identification, screening and inclusion counts, all computed.

    `included` keeps its slice-1 meaning, the works included at title/abstract (and `provisional`
    follows title/abstract pending), because sum(excluded) + pending + included == screened must
    hold. The review's final inclusion is `included_in_review` (full-text included), set once the
    full-text stage has run. `full_text.not_retrieved_reasons` names `unconverted` works, which
    need `factory document convert` before they can be screened."""

    identified_databases: dict[str, int]
    identified_other: dict[str, int]
    duplicates_removed: int
    screened: int
    excluded: dict[str, int]
    pending: int
    included: int
    full_text: FullTextBoxes = Field(default_factory=lambda: NOT_RUN_BOXES)
    included_in_review: int | None = None
    provisional: bool
    protocol_id: str | None

    @property
    def excluded_total(self) -> int:
        """Works excluded under any criterion, computed once for every surface (R-05)."""
        return sum(self.excluded.values())

    @model_validator(mode="after")
    def _identities_hold(self) -> "PrismaFlow":
        identified = sum(self.identified_databases.values()) + sum(self.identified_other.values())
        if identified - self.duplicates_removed != self.screened:
            raise ValueError("identified less duplicates must equal screened")
        if self.excluded_total + self.pending + self.included != self.screened:
            raise ValueError("excluded, pending and included must sum to screened")
        if self.provisional != (self.pending > 0):
            raise ValueError("a flow is provisional exactly while works are pending")
        return self


class SearchReportRow(StrictModel):
    """One registered search (PRISMA-S): its exact text, its filters, its date, and what it
    retrieved. Probe queries are not rows."""

    query_id: str
    source: str
    interface: str
    kind: QueryKind
    text: str
    filters: dict[str, str]
    purpose: QueryPurpose
    registered_at: datetime
    runs: list[RunSummary]
    reported: int | None
    retrieved: int
    shortfall_reason: str | None
    deviation_id: str | None


class SearchReport(StrictModel):
    rows: list[SearchReportRow]
    press_review_id: str | None
    press_confirmed: bool
    limits: list[Limit]


def prisma_flow(project: Project) -> PrismaFlow:
    """The PRISMA 2020 flow of the project as the events stand now."""
    project.index.sync()
    canonical = canonical_works(project)
    outcomes = final_outcomes(project)
    criteria = exclusion_criteria(project)

    databases = _database_records(project)
    other = {method.value: 0 for method in OTHER_METHODS}
    canonical_with_database = 0
    excluded: dict[str, int] = {}
    included = pending = 0
    for work in canonical:
        methods = {entry.method for entry in work.provenance}
        if ProvenanceMethod.DATABASE in methods:
            canonical_with_database += 1
        else:
            other[_other_method(work).value] += 1
        outcome = outcomes[work.id]
        if outcome is Outcome.INCLUDED:
            included += 1
        elif outcome is Outcome.PENDING:
            pending += 1
        else:
            criterion = criteria.get(work.id) or UNSPECIFIED
            excluded[criterion] = excluded.get(criterion, 0) + 1

    protocol = current_protocol(project)
    boxes = full_text_boxes(project)
    return PrismaFlow(
        identified_databases=databases,
        identified_other=other,
        duplicates_removed=sum(databases.values()) - canonical_with_database,
        screened=len(canonical),
        excluded=dict(sorted(excluded.items())),
        pending=pending,
        included=included,
        full_text=boxes,
        included_in_review=boxes.included if boxes.stage_run else None,
        provisional=pending > 0,
        protocol_id=None if protocol is None else protocol.protocol_id,
    )


def has_full_text_plan(project: Project) -> bool:
    """Whether the current protocol declares a full-text screening plan. The full-text readers
    refuse without one, so every report path asks first (R-13)."""
    protocol = current_protocol(project)
    return protocol is not None and protocol.spec.full_text_screening is not None


def full_text_boxes(project: Project) -> FullTextBoxes:
    """The full-text boxes as the events stand; never raises for a protocol with no plan."""
    project.index.sync()
    queue = fulltext_queue(project)
    eligible = [entry.work_id for entry in queue.eligible]
    sought = len(eligible) + len(queue.not_retrieved)
    reasons, attempts = _not_retrieved_reasons(project, set(queue.not_retrieved))
    run = has_full_text_plan(project) and _has_full_text_decision(project)
    excluded: dict[str, int] = {}
    included = 0
    if run:
        stage = ScreeningStage.FULL_TEXT
        outcomes = final_outcomes(project, stage=stage)
        criteria = exclusion_criteria(project, stage=stage)
        for work in eligible:
            outcome = outcomes[work]
            if outcome is Outcome.INCLUDED:
                included += 1
            elif outcome is not Outcome.PENDING:
                criterion = criteria.get(work) or UNSPECIFIED
                excluded[criterion] = excluded.get(criterion, 0) + 1
    assessed = included + sum(excluded.values())
    pending = len(eligible) - assessed
    return FullTextBoxes(
        sought=sought,
        not_retrieved=len(queue.not_retrieved),
        not_retrieved_reasons=reasons,
        failed_attempts_by_route=attempts,
        eligible=len(eligible),
        assessed=assessed,
        excluded=dict(sorted(excluded.items())),
        pending=pending,
        included=included,
        stage_run=run,
        provisional=pending > 0,
    )


def _has_full_text_decision(project: Project) -> bool:
    with project.index.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM decisions WHERE stage = :stage LIMIT 1"),
                {"stage": ScreeningStage.FULL_TEXT.value},
            ).first()
            is not None
        )


def _not_retrieved_reasons(
    project: Project, missing: set[str]
) -> tuple[dict[str, int], dict[str, int]]:
    """(reasons, attempts) over the not-retrieved works: each work once under its latest attempt,
    and the latest failed-attempt reason of every route."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT work_id, route, outcome, reason FROM fulltext_attempts ORDER BY event_id")
        ).all()
    latest: dict[str, str] = {}
    for work_id, route, outcome, reason in rows:
        latest[str(work_id)] = f"{route}: {reason if reason is not None else outcome}"
    reasons: dict[str, int] = {}
    attempts: dict[str, int] = {}
    for entry in fulltext_status(project).works:
        if entry.work_id not in missing:
            continue
        if entry.state == "unsought":
            key = UNSOUGHT
        elif entry.state == "retrieved":
            key = UNCONVERTED
        else:
            key = latest[entry.work_id]
            for route, reason in entry.reasons.items():
                label = f"{route.value}: {reason}"
                attempts[label] = attempts.get(label, 0) + 1
        reasons[key] = reasons.get(key, 0) + 1
    return dict(sorted(reasons.items())), dict(sorted(attempts.items()))


def search_report(project: Project) -> SearchReport:
    """The PRISMA-S view of every registered search, with the press review of its strategy."""
    project.index.sync()
    with project.index.connect() as conn:
        queries = (
            conn.execute(
                text(
                    'SELECT query_id, source, interface, kind, "text", filters, purpose, '
                    "registered_at FROM queries WHERE purpose != :probe ORDER BY query_id"
                ),
                {"probe": QueryPurpose.PROBE.value},
            )
            .mappings()
            .all()
        )
        runs = (
            conn.execute(
                text(
                    "SELECT run_id, query_id, source, status, reported_count, retrieved_count, "
                    "skipped, note, resume_token FROM runs ORDER BY run_id"
                )
            )
            .mappings()
            .all()
        )
        # A work is new to the run that first found it, counted over every run (probes too), as
        # `run_query` counts it against the works already stored.
        first_found = conn.execute(
            text(
                "SELECT first.run_id, COUNT(*) FROM "
                "(SELECT work_id, MIN(run_id) AS run_id FROM provenance GROUP BY work_id) AS first "
                "GROUP BY first.run_id"
            )
        ).all()
    new_by_run = {str(run_id): int(count) for run_id, count in first_found}
    by_query: dict[str, list[RunSummary]] = {}
    for run in runs:
        summary = _run_summary(dict(run), new_by_run.get(str(run["run_id"]), 0))
        by_query.setdefault(summary.query_id, []).append(summary)

    protocol = current_protocol(project)
    rows = [
        _row(project, dict(query), by_query.get(str(query["query_id"]), [])) for query in queries
    ]
    press_id, confirmed = _press(project, None if protocol is None else protocol.spec)
    return SearchReport(
        rows=rows,
        press_review_id=press_id,
        press_confirmed=confirmed,
        limits=[] if protocol is None else list(protocol.spec.limits),
    )


# --- Database records and other methods ---


def _database_records(project: Project) -> dict[str, int]:
    """Provenance rows of `database` method written by search-purpose queries, per source."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.source, COUNT(*) FROM provenance p "
                "JOIN queries q ON q.query_id = p.query_id "
                "WHERE q.purpose = :search AND p.method = :database "
                "GROUP BY p.source ORDER BY p.source"
            ),
            {"search": QueryPurpose.SEARCH.value, "database": ProvenanceMethod.DATABASE.value},
        ).all()
    return {str(source): int(count) for source, count in rows}


def _other_method(work: Work) -> ProvenanceMethod:
    """The highest-precedence non-database method among a work's provenance."""
    methods = {entry.method for entry in work.provenance}
    for method in OTHER_METHODS:
        if method in methods:
            return method
    raise FactoryError(f"work {work.id} has no provenance outside the database method")


# --- Search report ---


def _run_summary(row: Mapping[str, Any], new_works: int) -> RunSummary:
    status = RunStatus(str(row["status"]))
    return RunSummary(
        run_id=str(row["run_id"]),
        query_id=str(row["query_id"]),
        source=str(row["source"]),
        status=status,
        reported_count=None if row["reported_count"] is None else int(str(row["reported_count"])),
        retrieved_count=int(str(row["retrieved_count"] or 0)),
        skipped=int(str(row["skipped"] or 0)),
        note=None if row["note"] is None else str(row["note"]),
        resume_token=None if row["resume_token"] is None else str(row["resume_token"]),
        new_works=new_works,
    )


def _row(project: Project, query: Mapping[str, Any], runs: list[RunSummary]) -> SearchReportRow:
    query_id = str(query["query_id"])
    reported = next((run.reported_count for run in runs if run.reported_count is not None), None)
    # A run explains its own shortfall in its note (R-23); the row carries those notes.
    shortfall = [
        run.note
        for run in runs
        if run.reported_count is not None
        and run.retrieved_count < run.reported_count
        and run.note is not None
    ]
    stored_filters: dict[str, str] = json.loads(str(query["filters"]))
    return SearchReportRow(
        query_id=query_id,
        source=str(query["source"]),
        interface=str(query["interface"]),
        kind=QueryKind(str(query["kind"])),
        text=str(query["text"]),
        filters=stored_filters,
        purpose=QueryPurpose(str(query["purpose"])),
        registered_at=parse_ts(str(query["registered_at"])),
        runs=runs,
        reported=reported,
        retrieved=sum(run.retrieved_count for run in runs),
        shortfall_reason="; ".join(shortfall) or None,
        deviation_id=registered_deviation(project, query_id),
    )


def _press(project: Project, spec: ProtocolSpec | None) -> tuple[str | None, bool]:
    """The PRESS review of the current search strategy: a confirmed one if any, else the latest."""
    if spec is None:
        return None, False
    with project.index.connect() as conn:
        reviews = conn.execute(
            text(
                "SELECT r.review_id, r.responses FROM press_reviews r "
                "JOIN protocols p ON p.protocol_id = r.protocol_id "
                "WHERE p.search_hash = :hash ORDER BY r.event_id"
            ),
            {"hash": search_strategy_hash(spec)},
        ).all()
    confirmed = [str(review) for review, responses in reviews if responses is not None]
    if confirmed:
        return confirmed[-1], True
    if reviews:
        return str(reviews[-1][0]), False
    return None, False
