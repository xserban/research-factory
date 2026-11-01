"""Seeds: added by identifier, looked up through probe-purpose queries, kept out of the corpus.

`add_seeds` checks each spec on its own. A valid spec gets its next id for its kind (`SEED01`,
`NEG01`) and a `seed.added` event, then one probe-purpose lookup, whose outcome is recorded as
`seed.resolved` or `seed.unresolved`. A spec that is invalid, or duplicates an earlier seed in
any form, writes nothing and is reported. Probe lookups leave their works outside the corpus
(see `services.search.list_works`).
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import text

from factory.errors import ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.seed import SeedAdded, SeedKind, SeedResolved, SeedSpec, SeedUnresolved
from factory.services.context import Project
from factory.services.results import BatchResult, ItemError
from factory.services.search import RunSummary, register_query, run_query
from factory.sources.registry import SourceFactory


class SeedOutcome(StrictModel):
    """The lookup result of one written seed: the work it resolved to, or why it did not."""

    seed_id: str
    work_id: str | None
    reason: str | None


_KIND_PREFIX = {SeedKind.POSITIVE: "SEED", SeedKind.NEGATIVE: "NEG"}
_IDENTITY_FIELDS = ("arxiv", "doi", "openalex")


def add_seeds(
    project: Project,
    actor: Actor,
    specs: Sequence[SeedSpec],
    *,
    sources: Mapping[str, SourceFactory],
) -> BatchResult[SeedOutcome]:
    """Add each valid seed in order and look it up. Invalid or duplicate specs write nothing.

    The write lock covers each seed's id assignment, duplicate check and `seed.added` write, so
    two callers cannot take the same id. It is released before the lookup, which fetches.
    """
    written: list[SeedOutcome] = []
    rejected: list[ItemError] = []
    for index, spec in enumerate(specs):
        with project.index.exclusive():
            project.index.sync()
            existing = _existing_seeds(project)
            issues = _spec_issues(spec, existing)
            if issues:
                rejected.append(ItemError(index=index, issues=issues))
                continue
            seed_id = _next_id(spec.kind, [seed_id for seed_id, _ in existing])
            # An agent's seed keeps its validated input, so what the agent stated can be audited.
            input_blob = (
                project.blobs.put_json(spec.model_dump(mode="json"))
                if actor.kind == "agent"
                else None
            )
            project.record(
                [
                    project.events.make(
                        "seed.added",
                        SeedAdded(seed_id=seed_id, spec=spec),
                        actor,
                        refs=(seed_id,),
                        input_blob=input_blob,
                    )
                ]
            )
        written.append(_lookup(project, actor, seed_id, spec, input_blob, sources=sources))
    return BatchResult[SeedOutcome](written=written, rejected=rejected)


def _lookup(
    project: Project,
    actor: Actor,
    seed_id: str,
    spec: SeedSpec,
    input_blob: str | None,
    *,
    sources: Mapping[str, SourceFactory],
) -> SeedOutcome:
    """One probe-purpose query for the seed, and the outcome it yields."""
    query_id = register_query(project, actor, _lookup_query(spec), sources=sources)
    run = run_query(project, query_id, sources=sources, actor=actor)
    works = _run_works(project, run.run_id)
    if run.status is not RunStatus.COMPLETE:
        reason = run.note or f"lookup {run.status.value}"
        return _unresolved(project, actor, seed_id, run, reason, input_blob)
    if not works:
        return _unresolved(project, actor, seed_id, run, f"not found in {run.source}", input_blob)
    if len(works) > 1:
        return _unresolved(
            project, actor, seed_id, run, f"ambiguous: {len(works)} records", input_blob
        )
    project.record(
        [
            project.events.make(
                "seed.resolved",
                SeedResolved(seed_id=seed_id, work_id=works[0], run_id=run.run_id),
                actor,
                refs=(seed_id,),
                input_blob=input_blob,
            )
        ]
    )
    return SeedOutcome(seed_id=seed_id, work_id=works[0], reason=None)


def _unresolved(
    project: Project,
    actor: Actor,
    seed_id: str,
    run: RunSummary,
    reason: str,
    input_blob: str | None,
) -> SeedOutcome:
    project.record(
        [
            project.events.make(
                "seed.unresolved",
                SeedUnresolved(seed_id=seed_id, run_id=run.run_id, reason=reason),
                actor,
                refs=(seed_id,),
                input_blob=input_blob,
            )
        ]
    )
    return SeedOutcome(seed_id=seed_id, work_id=None, reason=reason)


def _lookup_query(spec: SeedSpec) -> QuerySpec:
    """The probe that finds a seed: arXiv by id where one is known, else OpenAlex by DOI or id."""
    keys = spec.identity_keys()
    if "arxiv" in keys:
        return QuerySpec(
            source="arxiv",
            kind=QueryKind.ID_LIST,
            text=keys["arxiv"],
            purpose=QueryPurpose.PROBE,
        )
    if "doi" in keys:
        return QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text=f"doi:{keys['doi']}",
            purpose=QueryPurpose.PROBE,
        )
    return QuerySpec(
        source="openalex",
        kind=QueryKind.FILTER,
        text=f"openalex:{keys['openalex']}",
        purpose=QueryPurpose.PROBE,
    )


def _run_works(project: Project, run_id: str) -> list[str]:
    """The distinct works a run's provenance names, sorted."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT work_id FROM provenance WHERE run_id = :run ORDER BY work_id"),
            {"run": run_id},
        ).all()
    return [str(row[0]) for row in rows]


def _existing_seeds(project: Project) -> list[tuple[str, SeedSpec]]:
    """Every added seed, in id order, as its id and stated spec."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT seed_id, spec FROM seeds ORDER BY seed_id")).all()
    return [(str(seed_id), SeedSpec.model_validate_json(str(spec))) for seed_id, spec in rows]


def _spec_issues(spec: SeedSpec, existing: list[tuple[str, SeedSpec]]) -> list[ValidationIssue]:
    """Problems with one spec on its own, then duplicates of seeds already held.

    A spec built without the model's own checks is still refused here: the identifier is what
    the lookup needs, and a seed without one could never resolve.
    """
    if not spec.identity_keys():
        return [ValidationIssue("identifier", "give at least one of doi, arxiv or openalex")]
    keys = spec.identity_keys()
    for field in _IDENTITY_FIELDS:
        if field not in keys:
            continue
        for seed_id, other in existing:
            if other.identity_keys().get(field) == keys[field]:
                return [ValidationIssue(field, f"duplicate of {seed_id}")]
    return []


def _next_id(kind: SeedKind, taken: list[str]) -> str:
    """The next id for the kind, at least two digits, after every id already taken for it."""
    prefix = _KIND_PREFIX[kind]
    numbers = [int(seed_id[len(prefix) :]) for seed_id in taken if seed_id.startswith(prefix)]
    number = max(numbers, default=0) + 1
    return f"{prefix}{number:02d}"
