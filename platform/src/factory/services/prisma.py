"""The PRISMA 2020 flow and the PRISMA-S search report, computed from events (R-05, flow 11).

Both are read-only. Each number is computed here from the projection and the event-derived
services; no caller can set one. Counts follow plan 5b ruling 2 and decision #38.6:

- `identified_databases`: records parsed by `search`-purpose runs, per source. Probe runs never
  count.
- `identified_other`: canonical works with no `database` provenance, each counted once, keyed by
  the highest-precedence method among their provenance (citation-chase, seed-admission,
  hand-search).
- `identified_other_detail`: the `citation-chase` works of `identified_other` by mechanism (slice
  3a, R-25): `chase-backward`, `chase-forward` (a forward snowball round is a `search_chase` round
  and counts here) and `snowball-backward`. A work counts once, under its earliest
  `citation-chase` run (by run id). A run is told apart by its query's `query.registered` refs: a
  `snw_` ref is a backward snowball round; otherwise (a `chs_` ref, or a chase recorded before
  queries named their round) the query text's `cites:` prefix is forward, any other backward.
  Empty while no work counts under `citation-chase`, so a slice-1 flow is unchanged.
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
- sum(identified_other_detail) == identified_other["citation-chase"] whenever the detail is set
"""

import json
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator
from sqlalchemy import text

from factory.clock import parse_ts
from factory.errors import FactoryError
from factory.imports.model import ImportFormat
from factory.model.base import StrictModel
from factory.model.protocol import Limit, ProtocolSpec, ScreeningStage, search_strategy_hash
from factory.model.references import Direction, Via
from factory.model.screening import ScreeningPhase
from factory.model.search import QueryKind, QueryPurpose, RunStatus
from factory.model.work import ProvenanceMethod, Work
from factory.services.agreement import Outcome, exclusion_criteria, final_outcomes
from factory.services.context import Project
from factory.services.dedup import canonical_works
from factory.services.fulltext_screening import fulltext_queue
from factory.services.fulltext_status import fulltext_status
from factory.services.protocol import current_protocol, registered_deviation, registered_import
from factory.services.search import RunSummary
from factory.services.snowball import query_yields, recorded_rounds

UNSOUGHT = "unsought"
UNCONVERTED = "unconverted"
UNSPECIFIED = "unspecified"
"""The exclusion bucket for an excluded work that cites no criterion (not expected to occur)."""

OTHER_METHODS: tuple[ProvenanceMethod, ...] = (
    ProvenanceMethod.CITATION_CHASE,
    ProvenanceMethod.SEED_ADMISSION,
    ProvenanceMethod.HAND_SEARCH,
    ProvenanceMethod.SUPPLIED,
    ProvenanceMethod.LIBRARY_IMPORT,
    ProvenanceMethod.GREY_STRUCTURED,
    ProvenanceMethod.GREY_WEBSITE,
    ProvenanceMethod.GREY_WEB_SEARCH,
    ProvenanceMethod.EXPERT_CONTACT,
)
"""Non-database methods in precedence order: a work counts under the first one it carries.
The `library-import` line is reported only once an import has been admitted (`has_admission`),
and the grey lines only once the protocol declares `grey_sources` (plan SG, PD-7), so a project
without either keeps its flow unchanged. The grey methods come last, so no existing count moves
(decision 75 item 2)."""

GREY_METHODS: frozenset[ProvenanceMethod] = frozenset(
    {
        ProvenanceMethod.GREY_STRUCTURED,
        ProvenanceMethod.GREY_WEBSITE,
        ProvenanceMethod.GREY_WEB_SEARCH,
        ProvenanceMethod.EXPERT_CONTACT,
    }
)


def reported_other_methods(project: Project, *, imports: bool) -> tuple[ProvenanceMethod, ...]:
    """The `OTHER_METHODS` lines the flow reports: `library-import` once an import is admitted,
    the grey methods once the current protocol declares `grey_sources`."""
    current = current_protocol(project)
    grey = current is not None and current.spec.grey_sources is not None
    return tuple(
        method
        for method in OTHER_METHODS
        if (imports or method is not ProvenanceMethod.LIBRARY_IMPORT)
        and (grey or method not in GREY_METHODS)
    )


CHASE_BACKWARD = "chase-backward"
CHASE_FORWARD = "chase-forward"
SNOWBALL_BACKWARD = "snowball-backward"
OTHER_DETAIL_KEYS: tuple[str, ...] = (CHASE_BACKWARD, CHASE_FORWARD, SNOWBALL_BACKWARD)
"""The mechanisms of `identified_other_detail` (slice 3a)."""
CHASE_UNATTRIBUTED = "unattributed"
"""A detail key present only when a chase run has no registered query, so no mechanism is known.
`check` reports such runs (`chase-run-unattributed`)."""


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
    identified_other_detail: dict[str, int] = Field(default_factory=dict)
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
        chased = self.identified_other.get(ProvenanceMethod.CITATION_CHASE.value, 0)
        if self.identified_other_detail and sum(self.identified_other_detail.values()) != chased:
            raise ValueError("the other-methods detail must sum to the citation-chase count")
        return self


_IMPORT_KEYS = (
    "import_id",
    "import_file_hash",
    "import_format",
    "import_parser",
    "import_parser_version",
)


class ReportRun(RunSummary):
    """A run as the PRISMA-S report lists it: `cycle_id` names the watch cycle that ran it
    (living review), None for any other run."""

    cycle_id: str | None = None


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
    runs: list[ReportRun]
    reported: int | None
    retrieved: int
    shortfall_reason: str | None
    deviation_id: str | None
    round_id: str | None = None
    """The snowball round whose query this is (slice 3a); None for any other query."""
    direction: Direction | None = None
    via: Via | None = None
    round_no: int | None = None
    new_after_dedup: int | None = None
    """For a round's query: the works new after dedup that its runs retrieved first."""
    included: int | None = None
    """For a round's query: how many of those are included at the last declared stage; None
    while any of them is pending there."""
    import_id: str | None = None
    """The import whose admission planned this query (slice 3d); None for any other query."""
    import_file_hash: str | None = None
    import_format: ImportFormat | None = None
    import_parser: str | None = None
    import_parser_version: str | None = None

    @model_serializer(mode="wrap")
    def _omit_import_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """A query that is not an import's serialises exactly as it did before imports existed."""
        data: dict[str, Any] = handler(self)
        if self.import_id is None:
            for key in _IMPORT_KEYS:
                data.pop(key, None)
        return data


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
    imports = has_admission(project)
    other = {method.value: 0 for method in reported_other_methods(project, imports=imports)}
    mechanisms = _chase_mechanisms(project)
    detail = dict.fromkeys(OTHER_DETAIL_KEYS, 0)
    canonical_with_database = 0
    excluded: dict[str, int] = {}
    included = pending = 0
    for work in canonical:
        methods = {entry.method for entry in work.provenance}
        if ProvenanceMethod.DATABASE in methods:
            canonical_with_database += 1
        else:
            method = _other_method(work)
            other[method.value] += 1
            if method is ProvenanceMethod.CITATION_CHASE:
                mechanism = mechanisms.get(_first_chase_run(work), CHASE_UNATTRIBUTED)
                detail[mechanism] = detail.get(mechanism, 0) + 1
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
        identified_other_detail=detail if other[ProvenanceMethod.CITATION_CHASE.value] else {},
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


def has_admission(project: Project) -> bool:
    """Whether any `import`-purpose query has been registered (an import has been admitted)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM queries WHERE purpose = :import LIMIT 1"),
            {"import": QueryPurpose.IMPORT.value},
        ).first()
    return row is not None


def has_full_text_plan(project: Project) -> bool:
    """Whether the current protocol declares a full-text screening plan. The full-text readers
    refuse without one, so every report path asks first (R-13)."""
    protocol = current_protocol(project)
    return protocol is not None and protocol.spec.full_text_screening is not None


def full_text_boxes(project: Project, *, only: Collection[str] | None = None) -> FullTextBoxes:
    """The full-text boxes as the events stand; never raises for a protocol with no plan.

    `only` restricts the boxes to those works (an update's), by the same rules."""
    project.index.sync()
    queue = fulltext_queue(project)
    keep = None if only is None else set(only)
    eligible = [e.work_id for e in queue.eligible if keep is None or e.work_id in keep]
    missing = [w for w in queue.not_retrieved if keep is None or w in keep]
    sought = len(eligible) + len(missing)
    reasons, attempts = _not_retrieved_reasons(project, set(missing))
    run = has_full_text_plan(project) and _has_full_text_decision(project)
    excluded: dict[str, int] = {}
    included = 0
    if run:
        stage = ScreeningStage.FULL_TEXT
        outcomes = final_outcomes(project, stage=stage)
        criteria = exclusion_criteria(project, stage=stage)
        for work in eligible:
            outcome = outcomes.get(work, Outcome.PENDING)  # an absorbed record may have none
            if outcome is Outcome.INCLUDED:
                included += 1
            elif outcome is not Outcome.PENDING:
                criterion = criteria.get(work) or UNSPECIFIED
                excluded[criterion] = excluded.get(criterion, 0) + 1
    assessed = included + sum(excluded.values())
    pending = len(eligible) - assessed
    return FullTextBoxes(
        sought=sought,
        not_retrieved=len(missing),
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
    """Whether a screening-phase full-text decision exists; calibration decisions do not count."""
    with project.index.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM decisions WHERE stage = :stage AND phase = :phase LIMIT 1"),
                {
                    "stage": ScreeningStage.FULL_TEXT.value,
                    "phase": ScreeningPhase.SCREENING.value,
                },
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
                    "registered_at FROM queries WHERE purpose NOT IN (:probe, :status) "
                    "ORDER BY query_id"
                ),
                {"probe": QueryPurpose.PROBE.value, "status": QueryPurpose.STATUS.value},
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
        # A work is new to the run that first brought it into the corpus, as `run_query` counts
        # it: a work stored only by a probe lookup is not yet in the corpus.
        first_found = conn.execute(
            text(
                "SELECT first.run_id, COUNT(*) FROM "
                "(SELECT work_id, MIN(run_id) AS run_id FROM provenance WHERE query_id NOT IN "
                "(SELECT query_id FROM queries WHERE purpose = :probe) GROUP BY work_id) AS first "
                "GROUP BY first.run_id"
            ),
            {"probe": QueryPurpose.PROBE.value},
        ).all()
        cycle_of = {
            str(run_id): str(cycle_id)
            for run_id, cycle_id in conn.execute(
                text("SELECT run_id, cycle_id FROM watch_cycle_runs")
            ).all()
        }
    new_by_run = {str(run_id): int(count) for run_id, count in first_found}
    by_query: dict[str, list[ReportRun]] = {}
    for run in runs:
        summary = _run_summary(
            dict(run), new_by_run.get(str(run["run_id"]), 0), cycle_of.get(str(run["run_id"]))
        )
        by_query.setdefault(summary.query_id, []).append(summary)

    protocol = current_protocol(project)
    rows = [
        _row(project, dict(query), by_query.get(str(query["query_id"]), [])) for query in queries
    ]
    rows = _with_imports(project, _with_rounds(project, rows))
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


def _first_chase_run(work: Work) -> str:
    return min(e.run_id for e in work.provenance if e.method is ProvenanceMethod.CITATION_CHASE)


def unattributed_chase_runs(project: Project) -> list[str]:
    """The chase runs that first found a canonical work and have no registered query, sorted."""
    mechanisms = _chase_mechanisms(project)
    return sorted(
        {
            run
            for work in canonical_works(project)
            if _other_method_applies(work) and (run := _first_chase_run(work)) not in mechanisms
        }
    )


def _other_method_applies(work: Work) -> bool:
    """Whether the work counts under `citation-chase` in the flow's other methods."""
    methods = {entry.method for entry in work.provenance}
    return (
        ProvenanceMethod.DATABASE not in methods
        and _other_method(work) is ProvenanceMethod.CITATION_CHASE
    )


def _chase_mechanisms(project: Project) -> dict[str, str]:
    """The `identified_other_detail` key of every run of a chase-purpose query, by run id."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.run_id, q.text, EXISTS (SELECT 1 FROM json_each(e.refs) j "
                "WHERE substr(j.value, 1, 4) = 'snw_') FROM runs r "
                "JOIN queries q ON q.query_id = r.query_id "
                "JOIN events e ON e.type = 'query.registered' "
                "AND json_extract(e.refs, '$[0]') = q.query_id WHERE q.purpose = :chase"
            ),
            {"chase": QueryPurpose.CHASE.value},
        ).all()
    out: dict[str, str] = {}
    for run_id, query_text, snowball in rows:
        if snowball:
            out[str(run_id)] = SNOWBALL_BACKWARD
        elif str(query_text).startswith("cites:"):
            out[str(run_id)] = CHASE_FORWARD
        else:
            out[str(run_id)] = CHASE_BACKWARD
    return out


def _other_method(work: Work) -> ProvenanceMethod:
    """The highest-precedence non-database method among a work's provenance."""
    methods = {entry.method for entry in work.provenance}
    for method in OTHER_METHODS:
        if method in methods:
            return method
    raise FactoryError(f"work {work.id} has no provenance outside the database method")


# --- Search report ---


def _run_summary(row: Mapping[str, Any], new_works: int, cycle_id: str | None) -> ReportRun:
    status = RunStatus(str(row["status"]))
    return ReportRun(
        cycle_id=cycle_id,
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


def _row(project: Project, query: Mapping[str, Any], runs: list[ReportRun]) -> SearchReportRow:
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


def _with_rounds(project: Project, rows: list[SearchReportRow]) -> list[SearchReportRow]:
    """`rows` with each snowball round's queries labelled by round and given their yield (R-23,
    R-25). A forward round's queries are those of its delegated chase round."""
    labels: dict[str, dict[str, object]] = {}
    for recorded in recorded_rounds(project):
        via = (
            Via.DOCUMENT_REFERENCE_LIST
            if recorded.direction is Direction.BACKWARD
            else Via.SOURCE_METADATA
        )
        for query_id, yielded in query_yields(project, recorded.round_id).items():
            labels[query_id] = {
                "round_id": recorded.round_id,
                "direction": recorded.direction,
                "via": via,
                "round_no": recorded.round_no,
                "new_after_dedup": yielded.new_after_dedup,
                "included": yielded.included,
            }
    return [
        row.model_copy(update=labels[row.query_id]) if row.query_id in labels else row
        for row in rows
    ]


def _with_imports(project: Project, rows: list[SearchReportRow]) -> list[SearchReportRow]:
    """`rows` with each import-purpose query labelled by its import: id, file hash, format and
    parser (R-23: the library is a recorded source)."""
    out: list[SearchReportRow] = []
    with project.index.connect() as conn:
        for row in rows:
            import_id = (
                registered_import(project, row.query_id)
                if row.purpose is QueryPurpose.IMPORT
                else None
            )
            recorded = (
                None
                if import_id is None
                else conn.execute(
                    text(
                        "SELECT file_hash, format, parser, parser_version FROM imports "
                        "WHERE import_id = :i"
                    ),
                    {"i": import_id},
                ).first()
            )
            if import_id is None or recorded is None:
                out.append(row)
                continue
            out.append(
                row.model_copy(
                    update={
                        "import_id": import_id,
                        "import_file_hash": str(recorded[0]),
                        "import_format": ImportFormat(str(recorded[1])),
                        "import_parser": str(recorded[2]),
                        "import_parser_version": str(recorded[3]),
                    }
                )
            )
    return out


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
