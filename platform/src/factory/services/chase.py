"""Citation chasing: platform-built rounds of OpenAlex citation queries from the included works.

A round names its directions and the included works it chases from (the `INCLUDED` outcomes that
carry an OpenAlex id). The platform builds the query texts (`chase_queries`) and records them in
`chase.round_started` before any query runs, so the round is the only authority for a chase text.
Works with no OpenAlex id are reported as unchasable and named in no query.

`search_chase` is `start_chase` (validate and build the round's event, writing nothing), the
recording of that event, and `run_chase`; a forward snowball round uses the two steps to record
the chase round together with its own ledger entry. `search_chase` validates everything before
it writes: pending works, the chasable works, the
directions, every query's source fit, and the protocol gate for the first query (with the round's
own texts waived). A refusal writes nothing. Only then is the round recorded, each query
registered naming the round (its `query.registered` refs end with the `chs_` id, which links the
runs to the round) and run; a source error in one run does not stop the others.

Under a protocol `snowball_plan` every forward chase round counts against `max_forward_rounds`,
whichever tool starts it (a forward snowball round delegates to a chase round, so counting the
chase rounds counts both); past the maximum it is refused as `snowball_round` refuses it. A
backward chase is a source-metadata comparison (`snowball_compare`) and is not limited.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_SEARCH
from factory.model.chase import CHASE_CHUNK, ChaseDirection, ChaseRoundStarted
from factory.model.references import FORWARD_ROUND_RE
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.services.agreement import Outcome, final_outcomes
from factory.services.budgets import require_for
from factory.services.calibration import calibration_items
from factory.services.context import Project
from factory.services.progress import track
from factory.services.protocol import current_protocol, search_authorization
from factory.services.search import (
    RunSummary,
    corpus_size,
    list_works,
    query_issues,
    register_query,
    run_query,
)
from factory.sources.registry import SourceFactory

_CHASE_SOURCE = "openalex"


class ChaseSummary(StrictModel):
    """What one `search_chase` call recorded. `new_works` is the corpus growth it caused."""

    round_id: str
    directions: list[ChaseDirection]
    from_works: list[str]
    unchasable: list[str]
    runs: list[RunSummary]
    new_works: int


def chase_sources(project: Project) -> tuple[list[str], list[str]]:
    """The included works, split into those with an OpenAlex id and those without, each sorted.

    Calibration works labelled include are chased too: they are includes in `final_outcomes`,
    although `_pending_issues` leaves calibration works out of its pending count.
    """
    outcomes = final_outcomes(project)
    included = {work for work, outcome in outcomes.items() if outcome is Outcome.INCLUDED}
    chasable: list[str] = []
    unchasable: list[str] = []
    for work in list_works(project):
        if work.id not in included:
            continue
        if work.identifiers.openalex is None:
            unchasable.append(work.id)
        else:
            chasable.append(work.id)
    return sorted(chasable), sorted(unchasable)


def chase_queries(directions: Sequence[ChaseDirection], openalex_ids: Sequence[str]) -> list[str]:
    """The OpenAlex filter texts that chase the given works, one run of chunks per direction.

    Directions are taken in `BACKWARD`, `FORWARD` order whatever order they are given in. Each
    text holds at most `CHASE_CHUNK` sorted ids joined by `|`. Backward: works the sources cite
    (`cited_by:`); forward: works citing the sources (`cites:`).
    """
    ids = sorted(openalex_ids)
    texts: list[str] = []
    for direction in (ChaseDirection.BACKWARD, ChaseDirection.FORWARD):
        if direction not in directions:
            continue
        prefix = "cited_by" if direction is ChaseDirection.BACKWARD else "cites"
        for start in range(0, len(ids), CHASE_CHUNK):
            chunk = ids[start : start + CHASE_CHUNK]
            texts.append(f"{prefix}:{'|'.join(chunk)}")
    return texts


def chase_rounds(project: Project) -> list[ChaseRoundStarted]:
    """Every recorded chase round, in recording order, rebuilt from the index projection."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT round_id, directions, from_works, unchasable FROM chase_rounds")
        ).all()
        queries: dict[str, list[str]] = {}
        for round_id, query in conn.execute(
            text("SELECT round_id, query FROM chase_queries ORDER BY round_id, position")
        ).all():
            queries.setdefault(str(round_id), []).append(str(query))
    return [
        ChaseRoundStarted(
            round_id=str(round_id),
            directions=tuple(ChaseDirection(d) for d in _strings(directions)),
            from_works=tuple(_strings(from_works)),
            unchasable=tuple(_strings(unchasable)),
            queries=tuple(queries.get(str(round_id), [])),
        )
        for round_id, directions, from_works, unchasable in rows
    ]


def forward_chase_rounds(project: Project) -> list[str]:
    """The ids of the recorded chase rounds with a forward direction, in recording order."""
    return [r.round_id for r in chase_rounds(project) if ChaseDirection.FORWARD in r.directions]


def round_limit_issue(round_no: int, maximum: int, direction: str) -> ValidationIssue:
    """The refusal of a round past the plan's maximum for its direction."""
    return ValidationIssue(
        "round_no", f"round {round_no} exceeds the plan's maximum of {maximum} {direction} rounds"
    )


def _forward_limit_issues(
    project: Project, directions: Sequence[ChaseDirection]
) -> list[ValidationIssue]:
    """One issue when a forward chase would pass the protocol's `max_forward_rounds`."""
    protocol = current_protocol(project)
    plan = None if protocol is None else protocol.spec.snowball_plan
    if plan is None or ChaseDirection.FORWARD not in directions:
        return []
    round_no = len(forward_chase_rounds(project)) + 1
    if round_no <= plan.max_forward_rounds:
        return []
    return [round_limit_issue(round_no, plan.max_forward_rounds, ChaseDirection.FORWARD.value)]


@dataclass(frozen=True)
class ChaseStart:
    """A validated chase round, not yet recorded: its payload, its specs (in query order) and
    the `chase.round_started` event that records it."""

    payload: ChaseRoundStarted
    specs: list[QuerySpec]
    event: Event


def search_chase(
    project: Project,
    actor: Actor,
    directions: Sequence[ChaseDirection],
    *,
    sources: Mapping[str, SourceFactory],
    from_works: Sequence[str] | None = None,
) -> ChaseSummary:
    """Record a chase round from the included works (or `from_works`, see `start_chase`) and run
    its queries.

    Writes nothing if the round does not fit (see `start_chase`). The round is recorded before
    any query runs (R-24): a failure in a run leaves a round without its runs, and a retry is a
    new round.
    """
    with project.index.exclusive():
        require_for(project, actor, REQUESTS_SEARCH)
        start = start_chase(project, actor, directions, sources=sources, from_works=from_works)
        before, _ = corpus_size(project)
        project.record([start.event])
    runs = run_chase(project, actor, start, sources=sources)
    after, _ = corpus_size(project)
    return ChaseSummary(
        round_id=start.payload.round_id,
        directions=list(start.payload.directions),
        from_works=list(start.payload.from_works),
        unchasable=list(start.payload.unchasable),
        runs=runs,
        new_works=after - before,
    )


def start_chase(
    project: Project,
    actor: Actor,
    directions: Sequence[ChaseDirection],
    *,
    sources: Mapping[str, SourceFactory],
    from_works: Sequence[str] | None = None,
    texts: Sequence[str] | None = None,
    extra_sources: Sequence[str] = (),
) -> ChaseStart:
    """Validate a chase round and build its event, writing nothing; the caller holds
    `project.index.exclusive()` and records `event` (with any events of its own).

    Refused when the directions are not one or two distinct ones, any ordinary work is pending,
    a forward round would pass the `snowball_plan` maximum, no work is chasable, any query does
    not fit its source, or the protocol does not authorise the first query with the round's texts
    waived. `from_works`, when given, names the included
    works to chase from instead of all of them: it must be a non-empty subset of the
    `chase_sources` works; those without an OpenAlex id are listed unchasable.

    `extra_sources` names corpus works that may be chased although they are not included (a
    forward round from core works takes the seeds' works). `texts`, forward rounds only, replaces
    the platform-built texts with the given ones, each a `FORWARD_ROUND_RE` text: a capped forward
    round names the citing works it took (`openalex:` texts), or carries a topic filter. The round
    still records the texts, so it remains the only authority for them.
    """
    if not directions or len(set(directions)) != len(directions):
        raise FactoryValidationError(
            [ValidationIssue("directions", "name one or two distinct directions")]
        )
    project.index.sync()
    issues = _pending_issues(project) + _forward_limit_issues(project, directions)
    chasable, unchasable = chase_sources(project)
    if extra_sources:
        held = {w.id: w.identifiers.openalex for w in list_works(project)}
        for extra in sorted(set(extra_sources) - set(chasable) - set(unchasable)):
            if extra in held:
                (chasable if held[extra] else unchasable).append(extra)
        chasable, unchasable = sorted(chasable), sorted(unchasable)
    if texts is not None:
        if list(directions) != [ChaseDirection.FORWARD]:
            issues.append(ValidationIssue("texts", "given texts are for a forward round only"))
        bad = [t for t in texts if FORWARD_ROUND_RE.fullmatch(t) is None]
        if bad or not texts:
            issues.append(ValidationIssue("texts", "a forward round's texts fit FORWARD_ROUND_RE"))
    if from_works is not None:
        given = set(from_works)
        outside = sorted(given - set(chasable) - set(unchasable))
        if outside or not given:
            issues.append(
                ValidationIssue(
                    "from_works",
                    "name included works only"
                    + (f"; not included: {', '.join(outside)}" if outside else ""),
                )
            )
        chasable = [w for w in chasable if w in given]
        unchasable = [w for w in unchasable if w in given]
    if not chasable:
        issues.append(ValidationIssue("works", "no works to chase"))
    if issues:
        raise FactoryValidationError(issues)
    openalex = {work.id: work.identifiers.openalex for work in list_works(project)}
    round_texts = (
        list(texts)
        if texts is not None
        else chase_queries(directions, [str(openalex[work]) for work in chasable])
    )
    specs = [
        QuerySpec(source=_CHASE_SOURCE, kind=QueryKind.FILTER, text=t, purpose=QueryPurpose.CHASE)
        for t in round_texts
    ]
    issues = [issue for spec in specs for issue in query_issues(project, spec, sources)]
    # Authorisation is checked for the first spec only: every gate except the planned-query
    # waiver is text-independent, and the waiver holds for every text since all are pending.
    issues += search_authorization(
        project, specs[0], deviation_id=None, pending_round_texts=round_texts
    )
    if issues:
        raise FactoryValidationError(issues)

    ordered = tuple(d for d in ChaseDirection if d in directions)
    round_id = project.ids.new("chs")
    payload = ChaseRoundStarted(
        round_id=round_id,
        directions=ordered,
        from_works=tuple(chasable),
        unchasable=tuple(unchasable),
        queries=tuple(round_texts),
    )
    directions_value: list[JsonValue] = [d.value for d in ordered]
    request: dict[str, JsonValue] = {"directions": directions_value}
    if from_works is not None:
        given_value: list[JsonValue] = [w for w in sorted(set(from_works))]
        request["from_works"] = given_value
    input_blob = project.blobs.put_json(request) if actor.kind == "agent" else None
    event = project.events.make(
        "chase.round_started", payload, actor, refs=(round_id,), input_blob=input_blob
    )
    return ChaseStart(payload=payload, specs=specs, event=event)


def run_chase(
    project: Project, actor: Actor, start: ChaseStart, *, sources: Mapping[str, SourceFactory]
) -> list[RunSummary]:
    """Register each query of a recorded chase round, naming the round (its `query.registered`
    refs end with the `chs_` id, which links the runs to the round), then run them in order; a
    source error in one run does not stop the others."""
    round_id = start.payload.round_id
    query_ids = [
        register_query(project, actor, spec, sources=sources, round_id=round_id)
        for spec in start.specs
    ]
    runs: list[RunSummary] = []
    with track(
        project, "snowball", "chase queries", unit="queries", total=len(query_ids)
    ) as reporter:
        for query_id in query_ids:
            runs.append(run_query(project, query_id, sources=sources, actor=actor))
            reporter.update(len(runs))
    return runs


def _pending_issues(project: Project) -> list[ValidationIssue]:
    """One issue when any ordinary (non-calibration) work has no final outcome yet."""
    calibration = set(calibration_items(project))
    pending = sum(
        1
        for work, outcome in final_outcomes(project).items()
        if outcome is Outcome.PENDING and work not in calibration
    )
    if pending == 0:
        return []
    return [ValidationIssue("screening", f"{pending} works still pending")]


def _strings(stored: object) -> list[str]:
    return [str(item) for item in json.loads(str(stored))]
