"""Version-pair candidates and the researcher's ruling on them (IDEA-56, decision 117).

Declares: `PairCandidate`, `candidates`, `decide_pair`. The only writer of `dedup.pair_decided`.

Invariants:
- `candidates` is read-only and proposes only; nothing is ever merged without a human ruling.
- A candidate pair is of two canonical works, sorted by id, not blocked and not decided (any row in
  `dedup_pair_decisions` excludes it; a later ruling is made with `decide_pair` directly).
- First-author agreement is not required; shared author surnames are shown as evidence only.
- `decide_pair` refuses, writing nothing, for a non-human actor, an unknown or absorbed work, or
  two identical works. The gate is `dedup.version_pair` (floor human in every mode).
- After the event is recorded the reconciliation runs, so the merge (or its reversal) is applied
  at once and stays through later runs.
"""

from __future__ import annotations

from itertools import combinations

from rapidfuzz import fuzz
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.dedup import PairDecided, PairDecision
from factory.model.work import Work
from factory.model.work_ids import normalize_title
from factory.services.context import Project
from factory.services.dedup import active_merges, blocked_pairs, canonical_works, dedup_run
from factory.services.gates import require_gate
from factory.services.search import list_works
from factory.services.versions import link_conflicts

GATE = "dedup.version_pair"
TITLE_SCORE = 95.0
MIN_TOKENS = 4
YEAR_GAP = 2
_BLOCK_TOKENS = 3

BASIS_TITLE = "title"
BASIS_LINK = "version-link"


class PairCandidate(StrictModel):
    """One candidate version pair with the evidence shown to the researcher."""

    work_a: str
    work_b: str
    title_a: str
    title_b: str
    year_a: int | None
    year_b: int | None
    score: float
    shared_surnames: list[str]
    basis: str
    identifiers_a: str
    identifiers_b: str


def _surnames(work: Work) -> set[str]:
    out: set[str] = set()
    for author in work.authors:
        tokens = normalize_title(author.name).split() if author.name else []
        if tokens:
            out.add(tokens[-1])
    return out


def _identifiers(work: Work) -> str:
    ids = work.identifiers
    parts = [
        f"{kind}:{value}"
        for kind, value in (
            ("doi", ids.doi),
            ("arxiv", ids.arxiv),
            ("pmid", ids.pmid),
            ("pmcid", ids.pmcid),
            ("openalex", ids.openalex),
            ("s2", ids.s2),
        )
        if value
    ]
    return ", ".join(parts)


def _title_score(a: Work, b: Work) -> float:
    return float(fuzz.token_sort_ratio(normalize_title(a.title), normalize_title(b.title)))


def _years_close(a: Work, b: Work) -> bool:
    ya, yb = a.dates.year, b.dates.year
    return ya is None or yb is None or abs(ya - yb) <= YEAR_GAP


def _decided_pairs(project: Project) -> frozenset[frozenset[str]]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT work_a, work_b FROM dedup_pair_decisions")).all()
    return frozenset(frozenset({str(a), str(b)}) for a, b in rows)


def _candidate(a: Work, b: Work, score: float, basis: str) -> PairCandidate:
    first, second = (a, b) if a.id < b.id else (b, a)
    return PairCandidate(
        work_a=first.id,
        work_b=second.id,
        title_a=first.title,
        title_b=second.title,
        year_a=first.dates.year,
        year_b=second.dates.year,
        score=score,
        shared_surnames=sorted(_surnames(first) & _surnames(second)),
        basis=basis,
        identifiers_a=_identifiers(first),
        identifiers_b=_identifiers(second),
    )


def candidates(project: Project, *, limit: int | None = None) -> list[PairCandidate]:
    """Candidate version pairs among canonical works, best first. Writes nothing."""
    works = canonical_works(project)
    by_id = {work.id: work for work in works}
    excluded = blocked_pairs(project) | _decided_pairs(project)

    tokens = {work.id: normalize_title(work.title).split() for work in works}
    buckets: dict[str, list[str]] = {}
    for work in works:
        for token in set(tokens[work.id][:_BLOCK_TOKENS]):
            buckets.setdefault(token, []).append(work.id)

    seen: set[frozenset[str]] = set()
    found: dict[frozenset[str], PairCandidate] = {}
    for members in buckets.values():
        for id_a, id_b in combinations(sorted(members), 2):
            key = frozenset({id_a, id_b})
            if key in seen:
                continue
            seen.add(key)
            if key in excluded:
                continue
            a, b = by_id[id_a], by_id[id_b]
            if min(len(tokens[id_a]), len(tokens[id_b])) < MIN_TOKENS or not _years_close(a, b):
                continue
            score = _title_score(a, b)
            if score >= TITLE_SCORE:
                found[key] = _candidate(a, b, score, BASIS_TITLE)

    for conflict in link_conflicts(project):
        key = frozenset({conflict.work_id, conflict.other_work_id})
        if key in found or key in excluded or len(key) != 2:
            continue
        if conflict.work_id not in by_id or conflict.other_work_id not in by_id:
            continue
        a, b = by_id[conflict.work_id], by_id[conflict.other_work_id]
        found[key] = _candidate(a, b, _title_score(a, b), BASIS_LINK)

    ordered = sorted(found.values(), key=lambda c: (-c.score, c.work_a, c.work_b))
    return ordered if limit is None else ordered[: max(limit, 0)]


def decide_pair(
    project: Project,
    actor: Actor,
    work_a: str,
    work_b: str,
    decision: PairDecision | str,
    rationale: str,
) -> str:
    """Record the researcher's ruling on a pair and apply it at once; returns the event id."""
    first, second = sorted((work_a, work_b))
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        issues.append(ValidationIssue("actor", "a version pair is ruled on by the researcher"))
    try:
        ruling = PairDecision(decision)
    except ValueError:
        ruling = None
        issues.append(ValidationIssue("decision", "must be 'same' or 'different'"))
    clean = rationale.strip()
    if not clean:
        issues.append(ValidationIssue("rationale", "must not be empty"))
    if first == second:
        issues.append(ValidationIssue("work_b", "the two works are the same work"))

    known = {work.id: work for work in list_works(project)}
    primary_of = {
        absorbed: merge.primary for merge in active_merges(project) for absorbed in merge.absorbed
    }
    for field, wid in (("work_a", first), ("work_b", second)):
        if wid not in known:
            issues.append(ValidationIssue(field, f"unknown work {wid}"))
        elif wid in primary_of:
            issues.append(
                ValidationIssue(field, f"{wid} is absorbed; rule on its primary {primary_of[wid]}")
            )
    if issues or ruling is None:
        raise FactoryValidationError(issues)

    require_gate(project, actor, GATE)

    a, b = known[first], known[second]
    basis, score = BASIS_TITLE, _title_score(a, b)
    if any({c.work_id, c.other_work_id} == {first, second} for c in link_conflicts(project)):
        basis = BASIS_LINK
    payload = PairDecided(
        work_a=first,
        work_b=second,
        decision=ruling,
        rationale=clean,
        basis=basis,
        score=score,
    )
    with project.writing():  # minted under the lock, so on a hosted project it sorts last
        event = project.events.make("dedup.pair_decided", payload, actor)
        project.record([event])
    dedup_run(project)
    return event.id
