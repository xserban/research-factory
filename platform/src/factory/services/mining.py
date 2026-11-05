"""Registered miners: registration, populations and the generic mine path (slice M, M-C).

Invariants:
- Everything here reads the index after a sync; only registration and the extraction engine's own
  writes append events.
- A population is computed by the platform from the log, in work-id order, and streamed: a
  generator yields `(work_id, conversion_id)` of works that have a default conversion, truncated at
  the selector's `max_units`.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, ActorKind
from factory.mining.compile import compile_miner, miner_digest
from factory.mining.kinds import close_checks, kind_checks
from factory.mining.select import selected_anchors
from factory.mining.spec import (
    AnchorKindRef,
    CitationKind,
    EnumKind,
    IntegerKind,
    MinerSpec,
    NumberKind,
    Population,
    QuoteKind,
    Selector,
    Unverified,
    WorkRefKind,
    spec_from_json,
    spec_to_json,
)
from factory.mining.validate import validate_miner
from factory.model.base import StrictModel
from factory.model.extraction import ExtractedRowInput, MinerScope
from factory.model.miners import ImportedFrom, MinerRegistered, MinerUse
from factory.model.protocol import ExtractionSchema, ProtocolStatus, ScreeningStage
from factory.model.screening import PassLabel
from factory.model.search import QueryPurpose
from factory.packs import Pack
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ExtractBatchContent,
    ExtractNext,
    ExtractResult,
    MineBatchContent,
    filled_imports,
    live_rows,
    next_unit,
    record_unit,
    stale_extractions,
    unit_states,
)
from factory.services.extraction_agreement import agreement_overall
from factory.services.passes import memberships
from factory.services.protocol import ProtocolVersion, current_protocol, miner_extraction_schema
from factory.services.references import current_extraction, included_works
from factory.services.stages import is_mine_kind
from factory.services.tasks import get_task, task_content

__all__ = [
    "MINE_INSTRUCTIONS",
    "MineStatus",
    "MinerListing",
    "MinerRow",
    "calibration_sample",
    "mine_next",
    "mine_record",
    "mine_status",
    "miner_listing",
    "miner_population",
    "miner_schema",
    "population",
    "population_works",
    "register_miner",
    "registered_miner",
    "registered_miners",
    "registered_row",
    "require_listed",
    "require_not_retired",
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
    proposer_session: str = ""
    retired: bool = False


def registered_row(project: Project, name: str, version: int) -> MinerRow | None:
    """The first registration of `(name, version)` in this project, or None."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT miner_id, digest, spec_blob, registered_by_kind, event_id, "
                "proposer_session, retired FROM miners "
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
        proposer_session=str(row[5]),
        retired=bool(row[6]),
    )


def registered_miner(project: Project, name: str, version: int) -> MinerSpec | None:
    """The spec registered as `(name, version)`, or None."""
    row = registered_row(project, name, version)
    return None if row is None else spec_from_json(project.blobs.get_json(row.spec_blob))


def register_miner(
    project: Project,
    actor: Actor,
    spec_json: JsonValue,
    *,
    imported_from: ImportedFrom | None = None,
) -> MinerRegistered:
    """Register a miner from its JSON spec; the spec is validated and recorded as a blob.
    `imported_from` records the project it was copied from (M-E); it must name this spec's digest
    (`digest`).

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
    if imported_from is not None and imported_from.digest != digest:
        raise FactoryValidationError(
            [ValidationIssue("digest", "the source registers another digest of this miner")]
        )
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
            imported_from=imported_from,
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


def require_not_retired(project: Project, name: str, version: int) -> None:
    """Refuse (field `miner`) a task or record of a retired miner version (R-52); its rows stay."""
    row = registered_row(project, name, version)
    if row is not None and row.retired:
        raise FactoryValidationError(
            [ValidationIssue("miner", f"miner {name} version {version} is retired")]
        )


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


def calibration_sample(project: Project, name: str) -> set[str]:
    """The works drawn into any calibration of miner `name` (they are never production units)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT u.work_id FROM miner_calibration_units u JOIN miner_calibrations c "
                "ON c.calibration_id = u.calibration_id WHERE c.name = :n"
            ),
            {"n": name},
        ).all()
    return {str(row[0]) for row in rows}


def miner_population(project: Project, name: str) -> list[str]:
    """The works the listed miner `name` mines in production, in work-id order: its selector's
    population less the units drawn into a calibration (M-D ruling 2: a calibration unit is never
    mined by a production pass, so no resolution can have fixed it)."""
    _, _, spec = _listed(project, name)
    apart = calibration_sample(project, name)
    return [work for work, _ in population(project, spec.selector) if work not in apart]


# --- The generic mine path ---

MINE_INSTRUCTIONS = (
    "Mine the records this miner's specification defines from the pinned document. Read it with "
    "document_read, at the listed anchors first. For every field give the value as printed, its "
    "anchor and the verbatim quote that contains it; a field of kind enum, citation, anchor or "
    "work_ref follows the rule listed for it. Never compute, round or convert a value, and leave "
    "out a field the document does not state."
)


def _kind_note(kind: object) -> str:
    """The rule an agent follows for one field kind, as a fixed sentence."""
    if isinstance(kind, NumberKind):
        units = ", ".join(u or "none" for u in kind.units) or "any"
        return f"number ({kind.unit_family.value}); unit one of: {units}; the value is in its quote"
    if isinstance(kind, IntegerKind):
        return "integer; the value is in its quote"
    if isinstance(kind, EnumKind):
        return (
            "enum: "
            + " | ".join(kind.values)
            + "; give a verbatim quote and its anchor as evidence"
        )
    if isinstance(kind, CitationKind):
        return "citation: the text appears in its quote and the quote holds a citation marker"
    if isinstance(kind, AnchorKindRef):
        return "anchor: an anchor id of kind " + ", ".join(k.value for k in kind.kinds)
    if isinstance(kind, WorkRefKind):
        if kind.by == "entry":
            return "work_ref: the ordinal of an entry of the work's reference list"
        return "work_ref: the title of a corpus work; its quote states the year"
    if isinstance(kind, QuoteKind):
        return "quote: the text appears in its quote"
    assert isinstance(kind, Unverified)
    return "free text"


def mine_next(
    project: Project,
    actor: Actor,
    name: str,
    version: int,
    label: PassLabel,
    *,
    calibration: bool = False,
) -> ExtractNext:
    """Serve the next task of pass `label` of the listed miner `(name, version)`: `next_unit` with
    the miner's scope and a content hook that adds the miner, its digest, the anchors its selector
    selects in the pinned conversion and the rule of each field kind (ids and fixed sentences, never
    document text).

    With `calibration` the pass is the miner's calibration pass (always pass A): it serves only the
    units of the version's drawn calibration, its tasks carry the calibration id, and its rows are
    read apart from the production run. Refused on field `session` (a neutral text) to the
    proposer's session, to a session that relayed a gold label and to a session of a production
    pass; a production call is refused likewise to a session that served calibration tasks. Field
    `calibration` when none is drawn, field `pass` for a calibration pass B.

    Refused, with nothing written, on field `miners` until the protocol lists that registered
    version, and as `next_unit` refuses otherwise."""
    _, _, spec = require_listed(project, name, version)
    require_not_retired(project, name, version)
    calibration_id: str | None = None
    if calibration:
        from factory.services.miner_independence import require_calibration_pass

        calibration_id = require_calibration_pass(project, actor, name, version, label)
        from factory.services.miner_gold import calibration_frozen
        from factory.services.miners import calibration_by_id

        drawn = calibration_by_id(project, calibration_id)
        if drawn is not None and calibration_frozen(project, drawn):
            return ExtractNext(batch=None, blocked=[], remaining=0)  # scored: nothing is served
    else:
        from factory.services.miner_independence import require_production_pass

        require_production_pass(project, actor, name)
    digest = miner_digest(spec)
    notes = {f.name: _kind_note(f.kind) for f in spec.fields}
    described = {f.name: f.description for f in spec.fields if f.description}

    def content(proj: Project, base: ExtractBatchContent) -> ExtractBatchContent:
        conversion = base.records[0]["conversion_id"]
        anchors = selected_anchors(conversion_manifest(proj, conversion), spec.selector)
        return MineBatchContent(
            **{**base.model_dump(), "instructions": MINE_INSTRUCTIONS},
            miner=name,
            version=version,
            digest=digest,
            anchors=anchors,
            calibration_id=calibration_id,
            field_kinds=notes,
            descriptions=described,
        )

    return next_unit(
        project,
        actor,
        label,
        scope=MinerScope(name),
        content=content,
        calibration_id=calibration_id,
    )


def mine_record(
    project: Project,
    actor: Actor,
    task_id: str,
    rows: Sequence[ExtractedRowInput],
    *,
    finish: bool = False,
    reason: str | None = None,
    supersedes: Mapping[int, str] | None = None,
) -> ExtractResult:
    """Record rows for a held miner task and close the unit on `finish`: `record_unit` with the
    compiled pack's verification, the miner's kind checks and its closing rule. Refused on `task_id`
    for a task that is not a miner task and on `miners` when the protocol no longer lists the
    miner version the task was served for. Claims are always empty."""
    task = get_task(project, task_id)
    content = None if task is None else task_content(project, task)
    miner = content.get("miner") if isinstance(content, dict) else None
    version = content.get("version") if isinstance(content, dict) else None
    if task is None or not is_mine_kind(task.kind) or not isinstance(miner, str):
        raise FactoryValidationError(
            [ValidationIssue("task_id", "not a miner task; evidence uses extract_record")]
        )
    _, _, spec = require_listed(project, miner, version if isinstance(version, int) else 0)
    require_not_retired(project, miner, version if isinstance(version, int) else 0)
    return record_unit(
        project,
        actor,
        task_id,
        rows,
        finish=finish,
        reason=reason,
        supersedes=supersedes,
        extra_check=kind_checks(spec),
        close_check=close_checks(spec),
    )


class MinerListing(StrictModel):
    """A registered miner version and whether the current protocol lists it."""

    name: str
    version: int
    digest: str
    proposer_kind: str
    listed: bool


def miner_listing(project: Project) -> list[MinerListing]:
    """Every registered miner version, by name then version, with whether it is listed."""
    protocol = current_protocol(project)
    listed = (
        {(u.name, u.version) for u in protocol.spec.miners or ()} if protocol is not None else set()
    )
    return [
        MinerListing(
            name=r.name,
            version=r.version,
            digest=r.digest,
            proposer_kind=r.proposer_kind,
            listed=(r.name, r.version) in listed,
        )
        for r in registered_miners(project)
    ]


class MineStatus(StrictModel):
    """One listed miner's units by state and its live rows. `agreement` is the overall agreement
    of its two passes (None for agents, before both passes finish, or when nothing is compared)."""

    name: str
    version: int
    digest: str
    units: int
    open: int
    closed: int
    rows: int
    stale: int
    agreement: float | None


def mine_status(
    project: Project, *, session: str | None = None, with_agreement: bool = True
) -> list[MineStatus]:
    """The status of every miner the current protocol lists, by name. A session that joined a miner
    pass sees that miner only, and only the units of its own pass; `with_agreement` False leaves
    the agreement out (agent views carry no rate)."""
    protocol = current_protocol(project)
    if protocol is None:
        return []
    own: tuple[str, PassLabel] | None = None
    if session is not None:
        for member in memberships(project, session):
            if (
                member.module == "extraction"
                and member.scope is not None
                and member.scope.startswith("m-")
            ):
                own = (member.scope, member.label)
    if session is not None and own is None and memberships(project, session):
        return []  # a screening or evidence pass session sees no miner's status
    out: list[MineStatus] = []
    for use in sorted(protocol.spec.miners or (), key=lambda u: u.name):
        if own is not None and own[0] != use.name:
            continue
        spec = registered_miner(project, use.name, use.version)
        if spec is None:
            continue
        scope = MinerScope(use.name)
        states = [
            s for s in unit_states(project, scope=scope) if own is None or s.pass_label == own[1]
        ]
        stale = stale_extractions(project, scope=scope)
        live = [r for r in live_rows(project, scope=scope) if r.extraction_id not in stale]
        imported = 0 if own is not None else sum(map(len, filled_imports(project, scope).values()))
        agreement = (
            agreement_overall(project, scope=scope).overall
            if with_agreement and own is None
            else None
        )
        out.append(
            MineStatus(
                name=use.name,
                version=use.version,
                digest=miner_digest(spec),
                units=len(states),
                open=sum(s.state in ("open", "queued") for s in states),
                closed=sum(s.state == "current" for s in states),
                rows=len([r for r in live if own is None or r.pass_label == own[1]]) + imported,
                stale=sum(s.state == "stale" for s in states),
                agreement=agreement,
            )
        )
    return out
