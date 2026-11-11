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

from collections import defaultdict

from rapidfuzz import fuzz, process
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

    titles = {work.id: normalize_title(work.title) for work in works}
    # token_sort_ratio is `ratio` over token-sorted strings; sorting once here, not per comparison,
    # lets rapidfuzz prune by length against the cutoff (the scores are identical).
    sorted_titles = {wid: " ".join(sorted(title.split())) for wid, title in titles.items()}
    eligible = [work for work in works if len(titles[work.id].split()) >= MIN_TOKENS]
    by_year: dict[int | None, list[Work]] = defaultdict(list)
    for work in eligible:
        by_year[work.dates.year].append(work)

    found: dict[frozenset[str], PairCandidate] = {}

    def compare(left: list[Work], right: list[Work]) -> None:
        """Score each left title against all right titles in one rapidfuzz call (in C)."""
        choices = [sorted_titles[w.id] for w in right]
        for a in left:
            hits = process.extract(
                sorted_titles[a.id],
                choices,
                scorer=fuzz.ratio,
                score_cutoff=TITLE_SCORE,
                limit=None,
            )
            for _, score, index in hits:
                b = right[index]
                key = frozenset({a.id, b.id})
                if a.id == b.id or key in found or key in excluded:
                    continue
                found[key] = _candidate(a, b, float(score), BASIS_TITLE)

    # Years differ by at most YEAR_GAP: each year against itself and the next YEAR_GAP years; a
    # work with no year against every eligible work.
    for year, bucket in by_year.items():
        if year is None:
            compare(bucket, eligible)
            continue
        window = [w for gap in range(YEAR_GAP + 1) for w in by_year.get(year + gap, [])]
        compare(bucket, window)

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
