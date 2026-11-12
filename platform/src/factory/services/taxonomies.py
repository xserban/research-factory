"""Taxonomy service: registration, reading, diff, coverage and change proposals (IDEA-50, T4).

Invariants:
- Categories are the researcher's. `register_taxonomy` is a human act and the only way a taxonomy
  version comes to exist; an agent only proposes (`propose_change`), and a proposal changes no
  taxonomy. A proposal is accepted or rejected only by a later registration that names it.
- A version is immutable and first write wins per `(name, version)`: the same digest again writes
  nothing; another digest under a registered version is refused.
- Everything computed is read from the index after a sync: the latest version, proposal status,
  coverage counts and sample draws. Nothing here is typed by an agent and coverage writes no event.
- Validation is at the boundary: invalid input raises `FactoryValidationError` (dotted fields) and
  writes nothing.
- Coverage counts never classify: a pattern is a counting aid outside the digest, a works count
  under a pattern is not a label, and works matching no pattern are a finding for the researcher.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.mining.taxonomy import (
    TaxonomyDiff,
    TaxonomySpec,
    diff,
    full_id,
    lineage_issues,
    taxonomy_digest,
    taxonomy_from_json,
    taxonomy_to_json,
    validate_taxonomy,
)
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.model.search import QueryPurpose
from factory.model.taxonomies import (
    PROPOSAL_ID_RE,
    ProposalKind,
    TaxonomyChangeProposed,
    TaxonomyRegistered,
)
from factory.model.taxonomies import ProposalRejection as RejectionEvent
from factory.services.context import Project
from factory.services.extraction import live_rows, stale_extractions
from factory.services.mining import registered_row
from factory.services.reference_layers import _scheme as _layer_scheme

# --- results ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterResult:
    """The outcome of `register_taxonomy`; `written` is False when the same digest was there."""

    name: str
    version: int
    digest: str
    written: bool


@dataclass(frozen=True)
class TaxonomyRow:
    """A registered version as the projection holds it."""

    name: str
    version: int
    digest: str
    spec_blob: str
    accepts: tuple[str, ...]
    rejects: tuple[tuple[str, str], ...]
    event_id: str


@dataclass(frozen=True)
class ProposalRow:
    """A change proposal with its status computed from later registrations: `accepted`,
    `rejected` (with `reason`) or `open`. `settled_in` is the version that settled it."""

    proposal_id: str
    taxonomy: str
    base_version: int
    kind: str
    targets: tuple[str, ...]
    draft_blob: str | None
    works: tuple[str, ...]
    rows: tuple[str, ...]
    cluster_id: str | None
    rationale: str
    status: str
    reason: str | None = None
    settled_in: int | None = None


@dataclass(frozen=True)
class CategoryCoverage:
    """Works whose pass-A quotes match a category's pattern, with seeded sample quotes."""

    category: str
    pattern: str
    works: int
    samples: tuple[str, ...]


@dataclass(frozen=True)
class DimensionCoverage:
    """Coverage of one dimension: works with quotes in its fields, per-pattern counts and the
    works matching no pattern."""

    dimension: str
    works_with_quotes: int
    categories: tuple[CategoryCoverage, ...]
    unmatched: int
    unmatched_samples: tuple[str, ...]


@dataclass(frozen=True)
class TaxonomyCoverage:
    """A computed coverage report. Counts never classify (module docstring)."""

    name: str
    version: int
    miner: str
    miner_version: int
    dimensions: tuple[DimensionCoverage, ...]


# --- reading ---------------------------------------------------------------------------------


def _refuse(field_: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, message)])


def _row(r: tuple[object, ...]) -> TaxonomyRow:
    rejects_raw = json.loads(str(r[5]))
    return TaxonomyRow(
        name=str(r[0]),
        version=int(str(r[1])),
        digest=str(r[2]),
        spec_blob=str(r[3]),
        accepts=tuple(str(a) for a in json.loads(str(r[4]))),
        rejects=tuple((str(d["proposal_id"]), str(d["reason"])) for d in rejects_raw),
        event_id=str(r[6]),
    )


_COLUMNS = "name, version, digest, spec_blob, accepts, rejects, event_id"


def taxonomy_row(project: Project, name: str, version: int) -> TaxonomyRow | None:
    """The first registration of `(name, version)`, or None."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(f"SELECT {_COLUMNS} FROM taxonomies WHERE name = :n AND version = :v"),
            {"n": name, "v": version},
        ).first()
    return None if found is None else _row(tuple(found))


def list_taxonomies(project: Project) -> list[TaxonomyRow]:
    """Every registered version, by name then version."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(f"SELECT {_COLUMNS} FROM taxonomies ORDER BY name, version")
        ).all()
    return [_row(tuple(r)) for r in found]


def registered_taxonomy(project: Project, name: str, version: int) -> TaxonomySpec | None:
    """The spec registered as `(name, version)`, or None."""
    row = taxonomy_row(project, name, version)
    return None if row is None else taxonomy_from_json(project.blobs.get_json(row.spec_blob))


def _latest_version(project: Project, name: str) -> int | None:
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT MAX(version) FROM taxonomies WHERE name = :n"), {"n": name}
        ).scalar()
    return None if found is None else int(found)


def layer_categories(project: Project, spec: TaxonomySpec) -> tuple[str, ...]:
    """The layer ids of the dimension-zero scheme `spec` names, from the recorded scheme, in the
    scheme's order; empty when `spec` has no layer-scheme dimension or the scheme is not recorded.
    These are the `layer_ids` a derived miner takes for dimension zero."""
    for dimension in spec.dimensions:
        if dimension.layer_scheme is not None:
            scheme = _layer_scheme(project, dimension.layer_scheme)
            return () if scheme is None else tuple(layer.id for layer in scheme.layers)
    return ()


def _category_ids(project: Project, spec: TaxonomySpec) -> set[str]:
    """Every full category id of `spec`, dimension zero's from its recorded scheme."""
    ids = {full_id(d.id, c.id) for d in spec.dimensions for c in d.categories}
    for dimension in spec.dimensions:
        if dimension.layer_scheme is not None:
            scheme = _layer_scheme(project, dimension.layer_scheme)
            if scheme is not None:
                ids.update(full_id(dimension.id, layer.id) for layer in scheme.layers)
    return ids


def taxonomy_diff(project: Project, name: str, a: int, b: int) -> TaxonomyDiff:
    """The computed difference from version `a` to version `b` of `name`. Refused when either
    version is not registered."""
    old = registered_taxonomy(project, name, a)
    new = registered_taxonomy(project, name, b)
    issues = [
        ValidationIssue(field_, f"{name} version {v} is not registered")
        for field_, v, spec in (("a", a, old), ("b", b, new))
        if spec is None
    ]
    if issues or old is None or new is None:
        raise FactoryValidationError(issues)
    return diff(old, new)


# --- proposals -------------------------------------------------------------------------------


def _proposal_rows(project: Project, name: str) -> list[tuple[object, ...]]:
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT proposal_id, taxonomy, base_version, kind, targets, draft_blob, works, "
                "rows, cluster_id, rationale FROM taxonomy_proposals "
                "WHERE taxonomy = :n ORDER BY proposal_id"
            ),
            {"n": name},
        ).all()
    return [tuple(r) for r in found]


def list_proposals(project: Project, name: str) -> list[ProposalRow]:
    """The proposals against taxonomy `name`, by id, each with its status: `accepted` or
    `rejected` (with the reason) when a registered version names it, else `open`. Computed."""
    project.index.sync()
    settled: dict[str, tuple[int | None, str, str | None]] = {}
    for row in list_taxonomies(project):
        if row.name != name:
            continue
        for pid in row.accepts:
            settled.setdefault(pid, (row.version, "accepted", None))
        for pid, why in row.rejects:
            settled.setdefault(pid, (row.version, "rejected", why))
    result: list[ProposalRow] = []
    for r in _proposal_rows(project, name):
        pid = str(r[0])
        version, status, reason = settled.get(pid, (None, "open", None))
        result.append(
            ProposalRow(
                proposal_id=pid,
                taxonomy=str(r[1]),
                base_version=int(str(r[2])),
                kind=str(r[3]),
                targets=tuple(str(x) for x in json.loads(str(r[4]))),
                draft_blob=None if r[5] is None else str(r[5]),
                works=tuple(str(x) for x in json.loads(str(r[6]))),
                rows=tuple(str(x) for x in json.loads(str(r[7]))),
                cluster_id=None if r[8] is None else str(r[8]),
                rationale=str(r[9]),
                status=status,
                reason=reason,
                settled_in=version,
            )
        )
    return result


def _corpus_work_ids(project: Project) -> set[str]:
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT DISTINCT work_id FROM provenance WHERE query_id NOT IN "
                "(SELECT query_id FROM queries WHERE purpose = :probe)"
            ),
            {"probe": QueryPurpose.PROBE.value},
        ).all()
    return {str(r[0]) for r in found}


def propose_change(
    project: Project,
    actor: Actor,
    *,
    taxonomy: str,
    base_version: int,
    kind: ProposalKind,
    targets: tuple[str, ...] = (),
    drafts: JsonValue | None = None,
    works: tuple[str, ...] = (),
    rows: tuple[str, ...] = (),
    cluster_id: str | None = None,
    rationale: str,
) -> str:
    """Record an agent's proposed change to `taxonomy` at `base_version`; returns the proposal id.

    Refused, with nothing written: for a non-agent actor (`actor`); a base version that is not
    registered (`base_version`); a `kind` other than `add` with no target, or a target that is
    not a full id `dimension/category` of the base version (`targets[i]`); a work that is not a
    corpus work (`works[i]`); a blank rationale. `drafts` is stored as a blob. The proposal
    changes no taxonomy; its provenance is the envelope's (model, skill, input blob)."""
    if actor.kind != "agent":
        raise _refuse("actor", "an agent proposes a taxonomy change")
    issues: list[ValidationIssue] = []
    if not rationale.strip():
        issues.append(ValidationIssue("rationale", "must not be blank"))
    spec = registered_taxonomy(project, taxonomy, base_version)
    if spec is None:
        raise FactoryValidationError(
            [*issues, ValidationIssue("base_version", f"{taxonomy} version {base_version} unknown")]
        )
    known = _category_ids(project, spec)
    if kind != "add" and not targets:
        issues.append(ValidationIssue("targets", f"a {kind} proposal names its target categories"))
    issues.extend(
        ValidationIssue(f"targets[{i}]", f"{t} is not a category of version {base_version}")
        for i, t in enumerate(targets)
        if t not in known
    )
    corpus = _corpus_work_ids(project)
    issues.extend(
        ValidationIssue(f"works[{i}]", f"{w} is not a corpus work")
        for i, w in enumerate(works)
        if w not in corpus
    )
    if issues:
        raise FactoryValidationError(issues)
    with project.index.exclusive():
        proposal_id = project.ids.new("tp")
        draft_blob = None if drafts is None else project.blobs.put_json(drafts)
        payload = TaxonomyChangeProposed(
            proposal_id=proposal_id,
            taxonomy=taxonomy,
            base_version=base_version,
            kind=kind,
            targets=targets,
            draft_blob=draft_blob,
            works=works,
            rows=rows,
            cluster_id=cluster_id,
            rationale=rationale,
        )
        body: JsonValue = json.loads(payload.model_dump_json())
        event = project.events.make(
            "taxonomy.change_proposed",
            payload,
            actor,
            refs=(proposal_id,),
            input_blob=project.blobs.put_json(body),
        )
        project.record([event])
    return proposal_id


# --- registration ----------------------------------------------------------------------------


def _settlement_issues(
    project: Project, spec: TaxonomySpec, previous: int | None
) -> list[ValidationIssue]:
    """`accepts` and `rejects` name existing proposals of this taxonomy at the previous version,
    each once."""
    named = [("accepts", i, p) for i, p in enumerate(spec.accepts)]
    named += [("rejects", i, r.proposal_id) for i, r in enumerate(spec.rejects)]
    issues: list[ValidationIssue] = []
    open_ids = {p.proposal_id: p for p in list_proposals(project, spec.name)}
    seen: set[str] = set()
    for field_, i, pid in named:
        where = f"{field_}[{i}]" if field_ == "accepts" else f"{field_}[{i}].proposal_id"
        proposal = open_ids.get(pid)
        if re.fullmatch(PROPOSAL_ID_RE, pid) is None:
            issues.append(ValidationIssue(where, "must be a proposal id"))
        elif proposal is None:
            issues.append(ValidationIssue(where, f"no proposal {pid} against {spec.name}"))
        elif proposal.base_version != previous:
            issues.append(ValidationIssue(where, f"{pid} is not a proposal on version {previous}"))
        elif proposal.status != "open":
            issues.append(ValidationIssue(where, f"{pid} is already {proposal.status}"))
        if pid in seen:
            issues.append(ValidationIssue(where, f"{pid} is named twice"))
        seen.add(pid)
    return issues


def register_taxonomy(project: Project, actor: Actor, spec_json: JsonValue) -> RegisterResult:
    """Register the taxonomy version `spec_json` describes; the spec is stored as a blob.

    Refused, with nothing written: for a non-human actor (`actor`); a spec of the wrong shape or
    meaning (`taxonomy_from_json`, `validate_taxonomy`, dotted); a `version` other than 1 or the
    latest registered plus one (`version`); lineage naming categories absent from the previous
    version; a dimension-zero `layer_scheme` that is not a recorded layer scheme version;
    `accepts` or `rejects` that name no proposal of this taxonomy on the previous version, or
    name one already settled or twice; a `(name, version)` registered with another digest. The
    same digest again writes nothing (`written` False). First write wins."""
    if actor.kind != "human":
        raise _refuse("actor", "only the researcher registers a taxonomy")
    spec = taxonomy_from_json(spec_json)
    issues = validate_taxonomy(spec)
    if issues:
        raise FactoryValidationError(issues)
    digest = taxonomy_digest(spec)
    with project.index.exclusive():
        project.index.sync()
        existing = taxonomy_row(project, spec.name, spec.version)
        if existing is not None:
            if existing.digest == digest:
                return RegisterResult(spec.name, spec.version, digest, False)
            raise _refuse(
                "version",
                f"{spec.name} version {spec.version} is registered with another digest; "
                "a change is a new version",
            )
        latest = _latest_version(project, spec.name)
        expected = 1 if latest is None else latest + 1
        if spec.version != expected:
            raise _refuse("version", f"the next version of {spec.name} is {expected}")
        previous = latest
        found: list[ValidationIssue] = []
        if previous is not None:
            before = registered_taxonomy(project, spec.name, previous)
            if before is not None:
                found.extend(lineage_issues(before, spec))
        for i, dimension in enumerate(spec.dimensions):
            if dimension.layer_scheme is not None and (
                _layer_scheme(project, dimension.layer_scheme) is None
            ):
                found.append(
                    ValidationIssue(
                        f"dimensions[{i}].layer_scheme",
                        f"layer scheme version {dimension.layer_scheme} is not recorded",
                    )
                )
        found.extend(_settlement_issues(project, spec, previous))
        if found:
            raise FactoryValidationError(found)
        payload = TaxonomyRegistered(
            name=spec.name,
            version=spec.version,
            digest=digest,
            spec_blob=project.blobs.put_json(taxonomy_to_json(spec)),
            accepts=spec.accepts,
            rejects=tuple(
                RejectionEvent(proposal_id=r.proposal_id, reason=r.reason) for r in spec.rejects
            ),
        )
        event = project.events.make(
            "taxonomy.registered", payload, actor, refs=(f"{spec.name}@{spec.version}",)
        )
        project.record([event])
    return RegisterResult(spec.name, spec.version, digest, True)


# --- coverage --------------------------------------------------------------------------------


def _quotes_by_work(
    project: Project, miner: str, names: tuple[str, ...], stale: set[str]
) -> dict[str, list[str]]:
    """Whitespace-normalised quotes of live, non-stale pass-A rows of `miner`, per work, for the
    fields in `names`."""
    found: dict[str, list[str]] = {}
    for row in live_rows(project, PassLabel.A, scope=MinerScope(miner)):
        if row.extraction_id in stale:
            continue
        for field_name, stored in row.fields.items():
            if field_name in names and stored.quote:
                found.setdefault(row.work_id, []).append(re.sub(r"\s+", " ", stored.quote))
    return found


def taxonomy_coverage(
    project: Project,
    name: str,
    version: int,
    *,
    miner: str,
    miner_version: int,
    fields: Mapping[str, tuple[str, ...]],
    seed: int = 5,
    samples: int = 2,
) -> TaxonomyCoverage:
    """Pattern coverage of taxonomy `(name, version)` over a descriptor miner's quotes. Computed,
    no event; counts never classify.

    `fields` maps a dimension id to the descriptor miner's field names read for it. Per dimension
    this reports the works with quotes, per category with a pattern the works whose live,
    non-superseded, non-stale pass-A quotes match it (case-insensitive) with up to `samples`
    quotes drawn deterministically from `seed`, and the works matching no pattern with samples.
    Dimensions without a `fields` entry, and categories without a pattern, are skipped. The miner
    version must be registered; rows are those of the miner's scope."""
    spec = registered_taxonomy(project, name, version)
    issues: list[ValidationIssue] = []
    if spec is None:
        issues.append(ValidationIssue("version", f"{name} version {version} is not registered"))
    if registered_row(project, miner, miner_version) is None:
        issues.append(ValidationIssue("miner", f"{miner} version {miner_version} not registered"))
    if samples < 0:
        issues.append(ValidationIssue("samples", "must not be negative"))
    issues.extend(
        ValidationIssue(f"fields.{d}", "names no dimension of the taxonomy")
        for d in fields
        if spec is not None and spec.dimension_named(d) is None
    )
    if issues or spec is None:
        raise FactoryValidationError(issues)
    stale = stale_extractions(project, scope=MinerScope(miner))
    reports: list[DimensionCoverage] = []
    for dimension in spec.dimensions:
        names = fields.get(dimension.id)
        if names is None:
            continue
        quotes = _quotes_by_work(project, miner, names, stale)
        works = sorted(quotes)
        joined = {w: " ".join(quotes[w]) for w in works}
        patterns = [
            (c.id, re.compile(c.pattern, re.IGNORECASE))
            for c in dimension.categories
            if c.pattern is not None
        ]
        categories: list[CategoryCoverage] = []
        for category_id, pattern in patterns:
            matched = [w for w in works if pattern.search(joined[w])]
            rng = random.Random(f"{seed}:{dimension.id}:{category_id}")
            drawn = rng.sample(matched, min(len(matched), 40))
            picked = [q for w in drawn for q in quotes[w] if pattern.search(q)][:samples]
            source = next(c.pattern for c in dimension.categories if c.id == category_id)
            categories.append(
                CategoryCoverage(category_id, source or "", len(matched), tuple(picked))
            )
        unmatched = [w for w in works if not any(p.search(joined[w]) for _, p in patterns)]
        rng = random.Random(f"{seed}:{dimension.id}:unmatched")
        shown = rng.sample(unmatched, min(len(unmatched), samples))
        reports.append(
            DimensionCoverage(
                dimension=dimension.id,
                works_with_quotes=len(works),
                categories=tuple(categories),
                unmatched=len(unmatched),
                unmatched_samples=tuple(quotes[w][0] for w in shown),
            )
        )
    return TaxonomyCoverage(name, version, miner, miner_version, tuple(reports))
