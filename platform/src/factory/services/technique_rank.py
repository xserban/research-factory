"""Ranking of technique combination and gap candidates (IDEA-78, ranking step).

Pure arithmetic over plain data; no index, no events, no model. The same inputs give the same
order. A score orders a list of hypotheses to check; it is not a probability, not a measure of
novelty and not evidence, and every score is returned with its components and weights.

Combination components, each in 0..1:

- `popularity`: min(works_a, works_b) over the largest such value among the candidates, so a pair
  needs two established approaches (a one-off partner gives a low value);
- `stage`: the stage relation of the two approaches in the lifecycle order below
  (`STAGE_FACTORS`: adjacent stages 1.0, same stage 0.6, distant 0.3, unordered 0.3);
- `bridge`: distinct live resolved `cites` links between the two work sets (either direction),
  on a log scale: log(1 + links) / log(1 + min(works_a, works_b)), capped at 1: the two
  communities know each other. The first version, min(1, links / min(works)), saturated: on the
  pilot corpus 3,247 of 9,506 pairs scored exactly 1.0 and could no longer be told apart;
- `evidence`: the mean over the two approaches of the share of their rows whose evidence is
  supportive (independent-test, own-ablation, own-comparison); `not-stated` counts as not
  supportive;
- `generic`: the mean idf-like value ln(N / works) / ln(N) of the two approaches (N works with a
  row in the lens), so an approach found in nearly every work scores near 0.

The composite is the weighted sum of popularity, stage, bridge and evidence, times
`0.5 + 0.5 * generic` (the generic penalty never removes more than half the score).

Gap components: `popularity` (works of the approach at the from stage over the pool maximum),
`strength` (share of those works with no row at the to stage), `bridge` (distinct citation links
between those works and the works with a row at the to stage: log(1 + links) / log(1 + number of
those works), capped at 1). The composite is their weighted sum (`GAP_WEIGHTS`).

Flags (never part of the score): `same-name-across-stages` and `lookalike-across-stages` (an
approach of the pair has a name-token Jaccard of at least `LOOKALIKE_MIN` with an approach of
another stage in the lens: possibly one technique listed twice; see `lookalikes`).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from math import log

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.technique_graph import SUPPORTIVE, Lookalike, Score

__all__ = [
    "COMBINATION_KEYS",
    "COMBINATION_WEIGHTS",
    "DEFAULT_TOP",
    "GAP_KEYS",
    "GAP_WEIGHTS",
    "LOOKALIKE_MIN",
    "QUOTE_TOP",
    "STAGE_FACTORS",
    "STAGE_ORDER",
    "bridge_norm",
    "check_rank_by",
    "check_top",
    "combination_score",
    "gap_score",
    "idf",
    "jaccard",
    "links_between",
    "lookalike_index",
    "name_tokens",
    "stage_relation",
]

STAGE_ORDER: tuple[str, ...] = (
    "literature-review",
    "ideation-hypothesis",
    "experiment-design",
    "implementation-execution",
    "data-analysis",
    "paper-writing",
    "review-verification",
)
"""The lifecycle order of the stage taxonomies `t-tech-<stage>` (the order of the `m-stages`
miner as laid out in `site_lifecycle.STAGES`: a layout order a research cycle usually runs, not a
causal claim). `other` and any stage not listed are unordered."""

STAGE_FACTORS: dict[str, float] = {"adjacent": 1.0, "same": 0.6, "distant": 0.3, "unordered": 0.3}
"""v1 heuristic: a pair from neighbouring stages is a plausible hand-off between steps of one
cycle; a same-stage pair is more often two substitutes; a distant or unordered pair is least
likely to be one method. Reported, not tuned."""

COMBINATION_WEIGHTS: dict[str, float] = {
    "popularity": 0.35,
    "stage": 0.15,
    "bridge": 0.30,
    "evidence": 0.20,
}
"""v1 heuristic, not fitted to any outcome. Popularity and bridge carry most of the weight:
two established approaches whose communities already cite each other are the cheapest pair to
check; stage and evidence refine the order. They sum to 1."""

GAP_WEIGHTS: dict[str, float] = {"popularity": 0.40, "strength": 0.35, "bridge": 0.25}
"""v1 heuristic: how established the approach is, how completely its users miss the to stage, and
whether they already cite works that reach it. They sum to 1."""

COMBINATION_KEYS: tuple[str, ...] = (
    "composite",
    "popularity",
    "stage",
    "bridge",
    "evidence",
    "generic",
)
GAP_KEYS: tuple[str, ...] = ("composite", "popularity", "strength", "bridge")
DEFAULT_TOP = 50
QUOTE_TOP = 5
"""Candidates that carry one verbatim quote per side."""


LOOKALIKE_MIN = 0.3
"""Smallest name-token Jaccard that flags a cross-stage lookalike (researcher ruling 2026-11-18)."""

_STOP = frozenset(
    [
        "of",
        "the",
        "and",
        "for",
        "with",
        "by",
        "in",
        "on",
        "to",
        "a",
        "an",
        "over",
        "from",
        "via",
        "using",
        "into",
        "at",
        "as",
        "or",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]+")


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def check_rank_by(kind: str, rank_by: str) -> None:
    keys = COMBINATION_KEYS if kind == "combinations" else GAP_KEYS
    if rank_by not in keys:
        raise _refuse("rank_by", f"must be one of {', '.join(keys)}")


def check_top(top: int | None) -> None:
    if top is not None and top < 1:
        raise _refuse("top", "must be at least 1")


def stage_relation(a: str, b: str) -> str:
    """`same`, `adjacent` (neighbours in STAGE_ORDER), `distant` or `unordered`."""
    if a == b:
        return "same"
    if a not in STAGE_ORDER or b not in STAGE_ORDER:
        return "unordered"
    return "adjacent" if abs(STAGE_ORDER.index(a) - STAGE_ORDER.index(b)) == 1 else "distant"


def idf(works: int, total: int) -> float:
    """ln(total / works) / ln(total), in 0..1; 1.0 when the corpus is too small to say."""
    if total <= 1 or works < 1:
        return 1.0
    return max(0.0, min(1.0, log(total / works) / log(total)))


def links_between(
    out: Mapping[str, Collection[str]], left: Collection[str], right: Collection[str]
) -> int:
    """Distinct (source, target) links with one end in `left` and the other in `right`, either
    direction; a link between two works of both sets counts once."""
    seen: set[tuple[str, str]] = set()
    for src in left:
        for dst in out.get(src, ()):
            if dst in right and dst != src:
                seen.add((src, dst))
    for src in right:
        for dst in out.get(src, ()):
            if dst in left and dst != src:
                seen.add((src, dst))
    return len(seen)


def bridge_norm(links: int, works: int) -> float:
    """log(1 + links) / log(1 + works), capped at 1; 0.0 without works."""
    if works < 1 or links < 1:
        return 0.0
    return min(1.0, log(1 + links) / log(1 + works))


def name_tokens(name: str) -> frozenset[str]:
    """Lower-cased alphanumeric tokens of a name, short words (under 3 characters) and stop words
    dropped."""
    return frozenset(t for t in _TOKEN.findall(name.lower()) if len(t) >= 3 and t not in _STOP)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def lookalike_index(
    catalogue: Mapping[str, tuple[str, str, str]], ids: Iterable[str]
) -> dict[str, Lookalike]:
    """For each id, its closest lookalike among `ids` of ANOTHER stage (highest Jaccard, ties by
    id), when at least `LOOKALIKE_MIN`. Pure and deterministic."""
    pool = sorted(set(ids))
    toks = {i: name_tokens(catalogue[i][1]) for i in pool}
    found: dict[str, Lookalike] = {}
    for i in pool:
        best: tuple[float, str] | None = None
        for j in pool:
            if catalogue[j][0] == catalogue[i][0]:
                continue
            value = jaccard(toks[i], toks[j])
            if value >= LOOKALIKE_MIN and (best is None or value > best[0]):
                best = (value, j)
        if best is not None:
            value, j = best
            found[i] = Lookalike(
                of=i,
                approach_id=j,
                stage=catalogue[j][0],
                name=catalogue[j][1],
                jaccard=_round(value),
            )
    return found


def adjacency(cites: Iterable[tuple[str, str, str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for src, dst, _ in cites:
        out[src].add(dst)
    return dict(out)


def supportive_share(evidence: Iterable[str | None]) -> float:
    levels = list(evidence)
    if not levels:
        return 0.0
    return sum(1 for e in levels if e in SUPPORTIVE) / len(levels)


def _round(x: float) -> float:
    return round(x, 12)


def combination_score(
    *,
    rank_by: str,
    works_a: int,
    works_b: int,
    pool_max: int,
    stage_a: str,
    stage_b: str,
    links: int,
    evidence_a: float,
    evidence_b: float,
    total_works: int,
    flags: tuple[str, ...] = (),
    lookalikes: tuple[Lookalike, ...] = (),
) -> Score:
    low = min(works_a, works_b)
    popularity = low / pool_max if pool_max else 0.0
    relation = stage_relation(stage_a, stage_b)
    stage = STAGE_FACTORS[relation]
    bridge = bridge_norm(links, low)
    evidence = (evidence_a + evidence_b) / 2
    generic = (idf(works_a, total_works) + idf(works_b, total_works)) / 2
    w = COMBINATION_WEIGHTS
    base = (
        w["popularity"] * popularity
        + w["stage"] * stage
        + w["bridge"] * bridge
        + w["evidence"] * evidence
    )
    composite = _round(base * (0.5 + 0.5 * generic))
    values = {
        "composite": composite,
        "popularity": popularity,
        "stage": stage,
        "bridge": bridge,
        "evidence": evidence,
        "generic": generic,
    }
    return Score(
        rank_by=rank_by,
        value=_round(values[rank_by]),
        popularity=_round(popularity),
        popularity_raw=low,
        stage=stage,
        stage_relation=relation,
        bridge=_round(bridge),
        bridge_links=links,
        evidence=_round(evidence),
        generic=_round(generic),
        composite=composite,
        weights=dict(w),
        flags=flags,
        lookalikes=lookalikes,
    )


def gap_score(
    *,
    rank_by: str,
    works: int,
    covered: int,
    pool_max: int,
    links: int,
) -> Score:
    popularity = works / pool_max if pool_max else 0.0
    strength = 1 - covered / works if works else 0.0
    bridge = bridge_norm(links, works)
    w = GAP_WEIGHTS
    composite = _round(
        w["popularity"] * popularity + w["strength"] * strength + w["bridge"] * bridge
    )
    values = {
        "composite": composite,
        "popularity": popularity,
        "strength": strength,
        "bridge": bridge,
    }
    return Score(
        rank_by=rank_by,
        value=_round(values[rank_by]),
        popularity=_round(popularity),
        popularity_raw=works,
        strength=_round(strength),
        bridge=_round(bridge),
        bridge_links=links,
        composite=composite,
        weights=dict(w),
    )
