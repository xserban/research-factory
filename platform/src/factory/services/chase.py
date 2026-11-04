"""Citation chasing: platform-built rounds of OpenAlex citation queries from the included works.

A round names its directions and the included works it chases from (the `INCLUDED` outcomes that
carry an OpenAlex id). The platform builds the query texts (`chase_queries`) and records them in
`chase.round_started` before any query runs, so the round is the only authority for a chase text.
Works with no OpenAlex id are reported as unchasable and named in no query.

`search_chase` validates everything before it writes: pending works, the chasable works, the
directions, every query's source fit, and the protocol gate for the first query (with the round's
own texts waived). A refusal writes nothing. Only then is the round recorded, each query
registered naming the round (its `query.registered` refs end with the `chs_` id, which links the
runs to the round) and run; a source error in one run does not stop the others.
"""

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.chase import CHASE_CHUNK, ChaseDirection, ChaseRoundStarted
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items
from factory.services.context import Project
from factory.services.protocol import search_authorization
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


def search_chase(
    project: Project,
    actor: Actor,
    directions: Sequence[ChaseDirection],
    *,
    sources: Mapping[str, SourceFactory],
) -> ChaseSummary:
    """Record a chase round from the included works and run its queries.

    Writes nothing if the round does not fit: the pending count must be zero, at least one work
    must be chasable, the directions must be distinct and non-empty, every query must fit its
    source, and the protocol must authorise the first query with the round's texts waived.

    The round is recorded before any query runs (R-24): a failure in a run leaves a round
    without its runs, and a retry is a new round.
    """
    if not directions or len(set(directions)) != len(directions):
        raise FactoryValidationError(
            [ValidationIssue("directions", "name one or two distinct directions")]
        )
    with project.index.exclusive():
        project.index.sync()
        issues = _pending_issues(project)
        chasable, unchasable = chase_sources(project)
        if not chasable:
            issues.append(ValidationIssue("works", "no works to chase"))
        if issues:
            raise FactoryValidationError(issues)

        openalex = {work.id: work.identifiers.openalex for work in list_works(project)}
        texts = chase_queries(directions, [str(openalex[work]) for work in chasable])
        specs = [
            QuerySpec(
                source=_CHASE_SOURCE,
                kind=QueryKind.FILTER,
                text=text,
                purpose=QueryPurpose.CHASE,
            )
            for text in texts
        ]
        issues = [issue for spec in specs for issue in query_issues(project, spec, sources)]
        # Authorisation is checked for the first spec only: every gate except the planned-query
        # waiver is text-independent, and the waiver holds for every text since all are pending.
        issues += search_authorization(
            project, specs[0], deviation_id=None, pending_round_texts=texts
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
            queries=tuple(texts),
        )
        input_blob = (
            project.blobs.put_json({"directions": [d.value for d in ordered]})
            if actor.kind == "agent"
            else None
        )
        before, _ = corpus_size(project)
        project.record(
            [
                project.events.make(
                    "chase.round_started",
                    payload,
                    actor,
                    refs=(round_id,),
                    input_blob=input_blob,
                )
            ]
        )

    query_ids = [
        register_query(project, actor, spec, sources=sources, round_id=round_id) for spec in specs
    ]
    runs = [run_query(project, query_id, sources=sources, actor=actor) for query_id in query_ids]
    after, _ = corpus_size(project)
    return ChaseSummary(
        round_id=round_id,
        directions=list(ordered),
        from_works=list(chasable),
        unchasable=list(unchasable),
        runs=runs,
        new_works=after - before,
    )


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
