"""Seeds: added by identifier, looked up through probe-purpose queries, kept out of the corpus.

After the lookups, `split_seeds` draws the recorded hold-out split of the positives. Agents see
negatives and development positives only (`agent_seeds`); `all_seeds` is the human view, and
`seed_check` and `seed_recall` report retrieval of the positives after search.

`admit_seed` is the human act that looks up an explained positive miss whose planned route is
`seed-admission`, by its identifier, as a seed-purpose query. It records `seed.admitted` whether or
not a work was found (see `factory.index.chase.admitted_works`).

`add_seeds` checks each spec on its own. A valid spec gets its next id for its kind (`SEED01`,
`NEG01`) and a `seed.added` event, then one probe-purpose lookup, whose outcome is recorded as
`seed.resolved` or `seed.unresolved`. A spec that is invalid, or duplicates an earlier seed in
any form, writes nothing and is reported. Probe lookups leave their works outside the corpus
(see `services.search.list_works`).
"""

import json
import random
import secrets
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.chase import admitted_works
from factory.model.base import StrictModel
from factory.model.chase import SeedAdmitted
from factory.model.project import RigorMode
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.seed import (
    SPLIT_PROCEDURE,
    SeedAdded,
    SeedKind,
    SeedMissExplained,
    SeedResolved,
    SeedSpec,
    SeedSplitDrawn,
    SeedUnresolved,
)
from factory.model.work import Provenance, ProvenanceMethod, Work
from factory.model.work_ids import arxiv_id_from_doi
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.results import BatchResult, ItemError
from factory.services.search import (
    RunSummary,
    get_work,
    list_works,
    query_issues,
    register_query,
    run_query,
)
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


def _lookup_query(spec: SeedSpec, purpose: QueryPurpose = QueryPurpose.PROBE) -> QuerySpec:
    """The query that finds a seed: arXiv by id where one is known, else OpenAlex by DOI or id.

    `purpose` is PROBE for the add-time lookup and SEED for an admission. The source adapters map
    SEED to the `seed-admission` provenance method.
    """
    keys = spec.identity_keys()
    if "arxiv" in keys:
        return QuerySpec(
            source="arxiv",
            kind=QueryKind.ID_LIST,
            text=keys["arxiv"],
            purpose=purpose,
        )
    if "doi" in keys:
        return QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text=f"doi:{keys['doi']}",
            purpose=purpose,
        )
    return QuerySpec(
        source="openalex",
        kind=QueryKind.FILTER,
        text=f"openalex:{keys['openalex']}",
        purpose=purpose,
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
    keys = spec.identity_keys()
    if not keys:
        return [ValidationIssue("identifier", "give at least one of doi, arxiv or openalex")]
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


# --- Hold-out split, views and the post-search seed check (R-20, R-24) ---


class SeedRole(StrEnum):
    """A seed's part in the hold-out. `late` positives were added after the split and count as
    development. `unsplit` covers negatives and every seed before the split was drawn."""

    DEVELOPMENT = "development"
    HELD_OUT = "held-out"
    LATE = "late"
    UNSPLIT = "unsplit"


class SeedSplit(StrictModel):
    random_seed: int
    development: list[str]
    held_out: list[str]


class SeedView(StrictModel):
    """What an agent may see of a seed: never a held-out one."""

    seed_id: str
    kind: SeedKind
    cite: str
    why: str
    work_id: str | None
    late: bool


class SeedRecord(StrictModel):
    """The human view of a seed, with its identifiers, outcome and role."""

    seed_id: str
    kind: SeedKind
    cite: str
    why: str
    doi: str | None
    arxiv: str | None
    openalex: str | None
    work_id: str | None
    unresolved_reason: str | None
    role: SeedRole


class SeedCheck(StrictModel):
    seed_id: str
    role: SeedRole
    status: Literal["retrieved", "explained", "missing"]
    matched_work: str | None
    found_by_search: bool = False


class SeedRecall(StrictModel):
    """Recall counts only seeds a search found (decision 54); `*_admitted` counts retrieved seeds
    that only a human admission put in the corpus."""

    development: float | None
    held_out: float | None
    development_admitted: int = 0
    held_out_admitted: int = 0


class _Seed(StrictModel):
    seed_id: str
    spec: SeedSpec
    work_id: str | None
    unresolved_reason: str | None


class _Split(StrictModel):
    random_seed: int
    development: list[str]
    held_out: list[str]


_DEVELOPMENT_ROLES = frozenset({SeedRole.DEVELOPMENT, SeedRole.LATE})
_SPLIT_MINIMUM = {RigorMode.SYSTEMATIC: 5}


def draw_split(
    positives: Sequence[tuple[str, int | None]], random_seed: int
) -> tuple[list[str], list[str]]:
    """Split positives into (development, held_out), reproducibly from `random_seed`.

    Positives are sorted by (undated last, year, id) and cut into consecutive groups of three.
    One `random.Random(random_seed)` sends one member of every group of three or two to held-out
    (`rng.choice`); a group of one stays in development. Both lists are returned sorted.
    """
    ordered = sorted(positives, key=lambda item: (item[1] is None, item[1] or 0, item[0]))
    rng = random.Random(random_seed)
    development: list[str] = []
    held_out: list[str] = []
    for start in range(0, len(ordered), 3):
        group = [seed_id for seed_id, _ in ordered[start : start + 3]]
        if len(group) == 1:
            development.extend(group)
            continue
        chosen = rng.choice(group)
        held_out.append(chosen)
        development.extend(seed_id for seed_id in group if seed_id != chosen)
    return sorted(development), sorted(held_out)


def split_seeds(project: Project, *, random_seed: int | None = None) -> SeedSplit:
    """Draw and record the hold-out split of the positive seeds (written by the system actor).

    Refused when the split was already drawn, when a positive is unresolved, or when there are
    fewer than three positives (five in a systematic project). The default seed is 32 random bits.
    """
    seed = secrets.randbits(32) if random_seed is None else random_seed
    with project.index.exclusive():
        issues: list[ValidationIssue] = []
        if not 0 <= seed < 2**32:
            issues.append(ValidationIssue("random_seed", "must be an integer from 0 to 2**32 - 1"))
        if _split(project) is not None:
            issues.append(ValidationIssue("split", "already drawn"))
        mode = _rigor_mode(project)
        positives = [s for s in _load_seeds(project) if s.spec.kind is SeedKind.POSITIVE]
        if any(s.work_id is None for s in positives):
            issues.append(ValidationIssue("seeds", "resolve every positive seed before the split"))
        needed = _SPLIT_MINIMUM.get(mode, 3)
        if len(positives) < needed:
            issues.append(
                ValidationIssue("seeds", f"{mode.value} needs at least {needed} positive seeds")
            )
        if issues:
            raise FactoryValidationError(issues)

        years = [
            (s.seed_id, _work_year(project, s.work_id)) for s in positives if s.work_id is not None
        ]
        development, held_out = draw_split(years, seed)
        payload = SeedSplitDrawn(
            random_seed=seed,
            procedure=SPLIT_PROCEDURE,
            development=tuple(development),
            held_out=tuple(held_out),
        )
        project.record([project.events.make("seed.split_drawn", payload, project.system_actor())])
    return SeedSplit(random_seed=seed, development=development, held_out=held_out)


def explain_seed_miss(
    project: Project,
    actor: Actor,
    seed_id: str,
    reason: str,
    route: ProvenanceMethod,
) -> None:
    """Record why a positive seed was not retrieved, and the admission route planned for it.

    Validation messages name the field, never the seed, so a held-out id is not echoed back.
    """
    with project.index.exclusive():
        positive_ids = {s.seed_id for s in _load_seeds(project) if s.spec.kind is SeedKind.POSITIVE}
        issues: list[ValidationIssue] = []
        if seed_id not in positive_ids:
            issues.append(ValidationIssue("seed_id", "not a positive seed"))
        if route is ProvenanceMethod.DATABASE:
            issues.append(ValidationIssue("route", "an admission route, not the database search"))
        if not reason.strip():
            issues.append(ValidationIssue("reason", "must not be empty"))
        if issues:
            raise FactoryValidationError(issues)
        payload = SeedMissExplained(seed_id=seed_id, reason=reason, route=route)
        input_blob = (
            project.blobs.put_json({"seed_id": seed_id, "reason": reason, "route": route.value})
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "seed.miss_explained",
                    payload,
                    actor,
                    refs=(seed_id,),
                    input_blob=input_blob,
                )
            ]
        )


def admit_seed(
    project: Project,
    actor: Actor,
    seed_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    deviation_id: str | None = None,
) -> SeedAdmitted:
    """Look up an explained seed-admission miss by its identifier, and record the outcome.

    A human act. The seed must be a positive whose miss was explained with route
    `seed-admission`, and must be neither retrieved nor already admitted. The lookup is a
    seed-purpose query, gated like any other: `deviation_id` names a recorded deviation when the
    protocol does not plan it. `seed.admitted` is written whether or not a work was found;
    `work_id` is the run's first work, or None. A lookup that failed without finding a work
    records nothing, so the seed can be retried.

    Validation happens before anything is written. Messages name the field, never the seed.
    """
    # Imported here: the protocol service reads seeds, which read this module.
    from factory.services import protocol as protocol_service

    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "seed admission is a human act")])
    with project.index.exclusive():
        project.index.sync()
        seed = next((s for s in _load_seeds(project) if s.seed_id == seed_id), None)
        if seed is None or seed.spec.kind is not SeedKind.POSITIVE:
            raise FactoryValidationError([ValidationIssue("seed_id", "not a positive seed")])
        issues = _admission_state_issues(project, seed)
        query = _lookup_query(seed.spec, QueryPurpose.SEED)
        issues += query_issues(project, query, sources)
        issues += protocol_service.search_authorization(project, query, deviation_id=deviation_id)
        if issues:
            raise FactoryValidationError(issues)

    query_id = register_query(project, actor, query, sources=sources, deviation_id=deviation_id)
    run = run_query(project, query_id, sources=sources, actor=actor)
    works = _run_works(project, run.run_id)
    if not works and run.status is not RunStatus.COMPLETE:
        raise FactoryValidationError(
            [ValidationIssue("lookup", f"lookup {run.status.value}; no admission recorded")]
        )
    admitted = SeedAdmitted(
        seed_id=seed_id,
        run_id=run.run_id,
        work_id=works[0] if works else None,
    )
    with project.index.exclusive():
        project.index.sync()
        if seed_id in _admitted(project):
            raise FactoryValidationError([ValidationIssue("seed_id", "already admitted")])
        project.record([project.events.make("seed.admitted", admitted, actor, refs=(seed_id,))])
    return admitted


def _admission_state_issues(project: Project, seed: _Seed) -> list[ValidationIssue]:
    """Why a positive seed may not be admitted now: unexplained, retrieved or already admitted."""
    issues: list[ValidationIssue] = []
    if _explained_route(project, seed.seed_id) is not ProvenanceMethod.SEED_ADMISSION:
        issues.append(ValidationIssue("seed_id", "not explained as a seed-admission miss"))
    if seed.seed_id in _admitted(project):
        issues.append(ValidationIssue("seed_id", "already admitted"))
    if _status_of(seed_check(project), seed.seed_id) == "retrieved":
        issues.append(ValidationIssue("seed_id", "already retrieved"))
    return issues


def _status_of(checks: list[SeedCheck], seed_id: str) -> str | None:
    return next((check.status for check in checks if check.seed_id == seed_id), None)


def _explained_route(project: Project, seed_id: str) -> ProvenanceMethod | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT route FROM seed_explanations WHERE seed_id = :seed"),
            {"seed": seed_id},
        ).one_or_none()
    return None if row is None else ProvenanceMethod(str(row[0]))


def _admitted(project: Project) -> dict[str, str | None]:
    """Every admitted seed with the work its lookup found (None when it found none)."""
    with project.index.connect() as conn:
        return admitted_works(conn)


def admitted_seed_count(project: Project) -> int:
    """How many seeds have a recorded admission (found or not)."""
    return len(_admitted(project))


def agent_seeds(project: Project) -> list[SeedView]:
    """The seeds an agent may use: every seed before the split, then negatives and development
    and late positives. Held-out seeds are never returned."""
    seeds = _load_seeds(project)
    roles = _roles(seeds, _split(project))
    return [
        SeedView(
            seed_id=seed.seed_id,
            kind=seed.spec.kind,
            cite=seed.spec.cite,
            why=seed.spec.why,
            work_id=seed.work_id,
            late=roles[seed.seed_id] is SeedRole.LATE,
        )
        for seed in seeds
        if roles[seed.seed_id] is not SeedRole.HELD_OUT
    ]


def all_seeds(project: Project) -> list[SeedRecord]:
    """The human view: every seed, held-out ones included, with its role."""
    seeds = _load_seeds(project)
    roles = _roles(seeds, _split(project))
    return [
        SeedRecord(
            seed_id=seed.seed_id,
            kind=seed.spec.kind,
            cite=seed.spec.cite,
            why=seed.spec.why,
            doi=seed.spec.doi,
            arxiv=seed.spec.arxiv,
            openalex=seed.spec.openalex,
            work_id=seed.work_id,
            unresolved_reason=seed.unresolved_reason,
            role=roles[seed.seed_id],
        )
        for seed in seeds
    ]


def seed_check(project: Project) -> list[SeedCheck]:
    """Each positive seed against the corpus: retrieved, explained (a miss with a recorded
    reason, admitted or not), or missing. A seed is retrieved when a corpus work shares its work
    id, the work its admission found, its DOI, or its arXiv id (a DataCite arXiv DOI counts as its
    arXiv id on either side)."""
    seeds = _load_seeds(project)
    roles = _roles(seeds, _split(project))
    corpus = list_works(project)
    by_id = {work.id: work for work in corpus}
    groups = _merge_groups(project)
    explained = _explained_ids(project)
    admitted = _admitted(project)
    checks: list[SeedCheck] = []
    for seed in seeds:
        if seed.spec.kind is not SeedKind.POSITIVE:
            continue
        found = seed.work_id if seed.work_id is not None else admitted.get(seed.seed_id)
        matched = _matching_work(seed, corpus, found)
        if matched is not None:
            status: Literal["retrieved", "explained", "missing"] = "retrieved"
        elif seed.seed_id in explained:
            status = "explained"
        else:
            status = "missing"
        checks.append(
            SeedCheck(
                seed_id=seed.seed_id,
                role=roles[seed.seed_id],
                status=status,
                matched_work=matched,
                found_by_search=matched is not None
                and any(
                    _searched(by_id[wid].provenance)
                    for wid in groups.get(matched, (matched,))
                    if wid in by_id
                ),
            )
        )
    return checks


def _searched(provenance: Sequence[Provenance]) -> bool:
    """Whether a work was found by a search: any provenance other than a seed admission. The
    corpus listing already drops probe-query provenance."""
    return any(row.method is not ProvenanceMethod.SEED_ADMISSION for row in provenance)


def _merge_groups(project: Project) -> dict[str, tuple[str, ...]]:
    """Every member of an active dedup merge group, keyed by each member."""
    groups: dict[str, tuple[str, ...]] = {}
    for merge in active_merges(project):
        members = (merge.primary, *merge.absorbed)
        for member in members:
            groups[member] = members
    return groups


def seed_recall(project: Project) -> SeedRecall:
    """Seeds found by search over total, per role: development (late positives included) and
    held-out. A seed a human admitted after an explained miss is retrieved but is not a search
    find, so it is excluded from the figure and counted in `*_admitted`. A figure is None when
    its role holds no positive seed."""
    checks = seed_check(project)
    development = [c for c in checks if c.role in _DEVELOPMENT_ROLES]
    held_out = [c for c in checks if c.role is SeedRole.HELD_OUT]
    return SeedRecall(
        development=_recall(development),
        held_out=_recall(held_out),
        development_admitted=_admitted_count(development),
        held_out_admitted=_admitted_count(held_out),
    )


def _recall(checks: list[SeedCheck]) -> float | None:
    if not checks:
        return None
    return sum(1 for check in checks if check.found_by_search) / len(checks)


def _admitted_count(checks: list[SeedCheck]) -> int:
    return sum(1 for c in checks if c.status == "retrieved" and not c.found_by_search)


def _roles(seeds: list[_Seed], split: _Split | None) -> dict[str, SeedRole]:
    roles: dict[str, SeedRole] = {}
    for seed in seeds:
        if split is None or seed.spec.kind is SeedKind.NEGATIVE:
            roles[seed.seed_id] = SeedRole.UNSPLIT
        elif seed.seed_id in split.held_out:
            roles[seed.seed_id] = SeedRole.HELD_OUT
        elif seed.seed_id in split.development:
            roles[seed.seed_id] = SeedRole.DEVELOPMENT
        else:
            roles[seed.seed_id] = SeedRole.LATE
    return roles


def _matching_work(seed: _Seed, corpus: list[Work], found: str | None) -> str | None:
    """The corpus work that is the seed: the one `found` names, else one sharing its DOI or arXiv
    id. `found` is the work the seed's lookup or admission resolved to, if any."""
    keys = seed.spec.identity_keys()
    for work in corpus:
        if found is not None and work.id == found:
            return work.id
        if "doi" in keys and work.identifiers.doi == keys["doi"]:
            return work.id
        if "arxiv" in keys and _work_arxiv(work) == keys["arxiv"]:
            return work.id
    return None


def _work_arxiv(work: Work) -> str | None:
    if work.identifiers.arxiv:
        return work.identifiers.arxiv
    return arxiv_id_from_doi(work.identifiers.doi) if work.identifiers.doi else None


def _work_year(project: Project, work_id: str | None) -> int | None:
    if work_id is None:
        return None
    work = get_work(project, work_id)
    return work.dates.year if work is not None else None


def _load_seeds(project: Project) -> list[_Seed]:
    """Every added seed in id order, with its first outcome."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT seed_id, spec, work_id, unresolved_reason FROM seeds ORDER BY seed_id")
        ).all()
    return [
        _Seed(
            seed_id=str(seed_id),
            spec=SeedSpec.model_validate_json(str(spec)),
            work_id=None if work_id is None else str(work_id),
            unresolved_reason=None if reason is None else str(reason),
        )
        for seed_id, spec, work_id, reason in rows
    ]


def split_is_drawn(project: Project) -> bool:
    """Whether the hold-out split has been recorded for this project."""
    return _split(project) is not None


def _split(project: Project) -> _Split | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT random_seed, development, held_out FROM seed_split")
        ).one_or_none()
    if row is None:
        return None
    random_seed, development, held_out = row
    return _Split(
        random_seed=int(random_seed),
        development=_string_list(development),
        held_out=_string_list(held_out),
    )


def _string_list(stored: Any) -> list[str]:
    values = json.loads(str(stored))
    return [str(value) for value in values]


def _explained_ids(project: Project) -> set[str]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT seed_id FROM seed_explanations")).all()
    return {str(row[0]) for row in rows}


def _rigor_mode(project: Project) -> RigorMode:
    project.index.sync()
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT rigor_mode FROM project WHERE slug = :slug"),
            {"slug": project.paths.slug},
        ).scalar_one()
    return RigorMode(str(value))
