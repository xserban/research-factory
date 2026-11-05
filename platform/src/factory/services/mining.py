"""Registered miners: registration, populations and the generic mine path (slice M, M-C).

Invariants:
- Everything here reads the index after a sync; only registration and the extraction engine's own
  writes append events.
- A population is computed by the platform from the log, in work-id order, and streamed: a
  generator yields `(work_id, conversion_id)` of works that have a default conversion, truncated at
  the selector's `max_units`.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import text

from factory.mining.spec import Population, Selector
from factory.model.protocol import ScreeningStage
from factory.model.search import QueryPurpose
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.references import current_extraction, included_works

__all__ = ["population", "population_works"]

_BATCH = 500


def _outcome_works(project: Project, stage: ScreeningStage) -> Iterator[str]:
    outcomes = final_outcomes(project, stage=stage)
    yield from sorted(w for w, o in outcomes.items() if o is Outcome.INCLUDED)


def _corpus_works(project: Project) -> Iterator[str]:
    with project.index.connect() as conn:
        result = conn.execute(
            text(
                "SELECT DISTINCT work_id FROM provenance WHERE query_id NOT IN "
                "(SELECT query_id FROM queries WHERE purpose = :probe) ORDER BY work_id"
            ),
            {"probe": QueryPurpose.PROBE.value},
        )
        while rows := result.fetchmany(_BATCH):
            for row in rows:
                yield str(row[0])


def population_works(project: Project, which: Population) -> Iterator[str]:
    """The works of a named population, in work-id order (before any conversion filter)."""
    project.index.sync()
    if which is Population.INCLUDED_FINAL:
        yield from included_works(project)
    elif which is Population.INCLUDED_TA:
        yield from _outcome_works(project, ScreeningStage.TITLE_ABSTRACT)
    elif which is Population.INCLUDED_FT:
        yield from _outcome_works(project, ScreeningStage.FULL_TEXT)
    elif which is Population.WITH_REFERENCES:
        for work in included_works(project):
            if current_extraction(project, work) is not None:
                yield work
    else:
        yield from _corpus_works(project)


def population(project: Project, selector: Selector) -> Iterator[tuple[str, str]]:
    """`(work_id, conversion_id)` of the works of the selector's population that have a default
    conversion, in work-id order, at most `selector.max_units` of them (works without a conversion
    are skipped and do not count towards the bound)."""
    emitted = 0
    for work in population_works(project, selector.population):
        if selector.max_units is not None and emitted >= selector.max_units:
            return
        conversion = default_conversion(project, work)
        if conversion is None:
            continue
        emitted += 1
        yield work, conversion.conversion_id
