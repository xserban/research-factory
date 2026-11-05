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
from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, ActorKind
from factory.mining.compile import compile_miner, miner_digest
from factory.mining.spec import MinerSpec, Population, Selector, spec_from_json, spec_to_json
from factory.mining.validate import validate_miner
from factory.model.miners import MinerRegistered, MinerUse
from factory.model.protocol import ExtractionSchema, ProtocolStatus, ScreeningStage
from factory.model.search import QueryPurpose
from factory.packs import Pack
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.protocol import ProtocolVersion, current_protocol, miner_extraction_schema
from factory.services.references import current_extraction, included_works

__all__ = [
    "MinerRow",
    "miner_population",
    "miner_schema",
    "population",
    "population_works",
    "register_miner",
    "registered_miner",
    "registered_miners",
    "registered_row",
    "require_listed",
]

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


# --- Registration and the protocol listing ---


@dataclass(frozen=True)
class MinerRow:
    """A registered `(name, version)` as the projection holds it."""

    miner_id: str
    name: str
    version: int
    digest: str
    spec_blob: str
    proposer_kind: ActorKind
    event_id: str


def registered_row(project: Project, name: str, version: int) -> MinerRow | None:
    """The first registration of `(name, version)` in this project, or None."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT miner_id, digest, spec_blob, registered_by_kind, event_id FROM miners "
                "WHERE name = :n AND version = :v"
            ),
            {"n": name, "v": version},
        ).one_or_none()
    if row is None:
        return None
    kind = str(row[3])
    return MinerRow(
        miner_id=str(row[0]),
        name=name,
        version=version,
        digest=str(row[1]),
        spec_blob=str(row[2]),
        proposer_kind="human" if kind == "human" else "agent" if kind == "agent" else "system",
        event_id=str(row[4]),
    )


def registered_miner(project: Project, name: str, version: int) -> MinerSpec | None:
    """The spec registered as `(name, version)`, or None."""
    row = registered_row(project, name, version)
    return None if row is None else spec_from_json(project.blobs.get_json(row.spec_blob))


def register_miner(project: Project, actor: Actor, spec_json: JsonValue) -> MinerRegistered:
    """Register a miner from its JSON spec; the spec is validated and recorded as a blob.

    Refused, with nothing written: for a system actor (`actor`); a spec of the wrong shape or
    meaning (the issues of `spec_from_json` and `validate_miner`, dotted); a `(name, version)` that
    exists with another digest (`version`: a change is a new version). Registering the same spec
    again writes nothing and returns the earlier registration."""
    if actor.kind == "system":
        raise FactoryValidationError(
            [ValidationIssue("actor", "an agent or a human registers a miner")]
        )
    spec = spec_from_json(spec_json)
    issues = validate_miner(spec)
    if issues:
        raise FactoryValidationError(issues)
    digest = miner_digest(spec)
    with project.index.exclusive():
        project.index.sync()
        existing = registered_row(project, spec.name, spec.version)
        if existing is not None:
            if existing.digest != digest:
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            "version",
                            f"{spec.name} version {spec.version} is registered with another "
                            "digest; a change is a new version",
                        )
                    ]
                )
            return MinerRegistered(
                miner_id=existing.miner_id,
                name=existing.name,
                version=existing.version,
                digest=existing.digest,
                spec_blob=existing.spec_blob,
                proposer_kind=existing.proposer_kind,
            )
        body = spec_to_json(spec)
        payload = MinerRegistered(
            miner_id=project.ids.new("mnr"),
            name=spec.name,
            version=spec.version,
            digest=digest,
            spec_blob=project.blobs.put_json(body),
            proposer_kind=actor.kind,
        )
        event = project.events.make(
            "miner.registered",
            payload,
            actor,
            refs=(payload.miner_id,),
            input_blob=project.blobs.put_json(body) if actor.kind == "agent" else None,
        )
        project.record([event])
    return payload


def registered_miners(project: Project) -> list[MinerRow]:
    """Every registered miner version, by name then version."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT name, version FROM miners ORDER BY name, version")).all()
    found = [registered_row(project, str(n), int(v)) for n, v in rows]
    return [r for r in found if r is not None]


def require_listed(
    project: Project, name: str, version: int
) -> tuple[ProtocolVersion, MinerUse, MinerSpec]:
    """The ready protocol, the use that lists `(name, version)` and the registered spec. Raises on
    field `protocol` when the protocol is not ready and on field `miners` when the protocol does not
    list that version or the miner is not registered (pre-registration, I7)."""
    protocol = current_protocol(project)
    if protocol is None or protocol.status is not ProtocolStatus.READY:
        raise FactoryValidationError(
            [ValidationIssue("protocol", "the protocol is not ready; record it ready first")]
        )
    use = next(
        (u for u in protocol.spec.miners or () if (u.name, u.version) == (name, version)), None
    )
    spec = registered_miner(project, name, version)
    if use is None or spec is None:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "miners",
                    f"miner {name} version {version} is not listed in the protocol; register it "
                    "and amend the protocol's miners section first",
                )
            ]
        )
    return protocol, use, spec


def _listed(project: Project, name: str) -> tuple[ProtocolVersion, MinerUse, MinerSpec]:
    protocol = current_protocol(project)
    use = (
        None
        if protocol is None
        else next((u for u in protocol.spec.miners or () if u.name == name), None)
    )
    if use is None:
        if protocol is None or protocol.status is not ProtocolStatus.READY:
            raise FactoryValidationError(
                [ValidationIssue("protocol", "the protocol is not ready; record it ready first")]
            )
        raise FactoryValidationError(
            [ValidationIssue("miners", f"miner {name} is not listed in the protocol")]
        )
    return require_listed(project, name, use.version)


def miner_schema(project: Project, name: str) -> tuple[ProtocolVersion, ExtractionSchema, Pack]:
    """The ready protocol, the schema and the pack of the listed miner `name` (the version the
    protocol lists). Raises as `require_listed`. The schema declares every field of the miner."""
    protocol, use, spec = _listed(project, name)
    schema = miner_extraction_schema(use, tuple(f.name for f in spec.fields))
    return protocol, schema, compile_miner(spec)


def miner_population(project: Project, name: str) -> list[str]:
    """The works the listed miner `name` mines, in work-id order (its selector's population)."""
    _, _, spec = _listed(project, name)
    return [work for work, _ in population(project, spec.selector)]
