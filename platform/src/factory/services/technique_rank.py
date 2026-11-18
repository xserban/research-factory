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
  on a log scale over the possible pairs: log(1 + links) / log(1 + works_a * works_b), clamped
  at 1: the two communities know each other. Earlier forms saturated: min(1, links / min(works))
  scored exactly 1.0 for 3,247 of 9,506 pilot pairs, and log(1 + links) / log(1 + min(works))
  kept the same 3,247 at 1.0 because the cap, not the linear scale, caused it. The product is
  the number of work pairs that could cite each other, so 1.0 needs a link for every such pair;
  the log keeps a few links from reading as nothing. Links are counted in both directions while
  the denominator counts unordered work pairs, so a densely cross-citing pair can reach 1.0 early;
- `evidence`: the mean over the two approaches of the share of their rows whose evidence is
  supportive (independent-test, own-ablation, own-comparison); `not-stated` counts as not
  supportive;
- `generic`: the mean idf-like value ln(N / works) / ln(N) of the two approaches (N works with a
  row in the lens), so an approach found in nearly every work scores near 0.

`twin_share` (Jaccard of the two approaches' work sets) is reported, not scored.

Every normalisation here is relative to the candidates of ONE call (`popularity` divides by the
pool maximum), so scores are comparable within one call only: the same pair scores differently
under another `min_works`, `stage` or `max_co_works`.

The composite is the weighted sum of popularity, stage, bridge and evidence, times
`0.5 + 0.5 * generic` (the generic penalty never removes more than half the score).

Gap components: `popularity` (works of the approach at the from stage over the pool maximum),
`strength` (share of those works with no row at the to stage), `bridge` (distinct citation links
between those works and the works with a row at the to stage: log(1 + links) /
log(1 + works * to-stage works), the same possible-pairs denominator as above, clamped at 1). The
composite is their weighted sum (`GAP_WEIGHTS`).

Flags (never part of the score or the order): `same-name-across-stages`;
`lookalike-across-stages` (an approach of the pair shares at least `LOOKALIKE_MIN_SHARED` name
tokens and a Jaccard of at least `LOOKALIKE_MIN` with an approach of another stage in the lens:
possibly one technique listed twice; see `lookalikes`); `shares-works-with-<id>` (the work sets of
the pair overlap by more than `TWIN_MIN` of the smaller set).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from functools import lru_cache
from math import log
from typing import Any

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.technique_graph import SUPPORTIVE, Lookalike, Score

__all__ = [
    "COMBINATION_KEYS",
    "COMBINATION_WEIGHTS",
    "DEFAULT_TOP",
    "GAP_KEYS",
    "GAP_WEIGHTS",
    "GENERIC_WORDS",
    "LOOKALIKE_MIN",
    "LOOKALIKE_MIN_SHARED",
    "QUOTE_TOP",
    "STAGE_FACTORS",
    "STAGE_ORDER",
    "TWIN_MIN",
    "bridge_norm",
    "check_limit",
    "check_rank_by",
    "check_top",
    "combination_score",
    "gap_score",
    "idf",
    "jaccard",
    "links_between",
    "lookalike_cache_info",
    "lookalike_index",
    "name_tokens",
    "stage_relation",
    "work_overlap",
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


LOOKALIKE_MIN = 0.4
"""Smallest name-token Jaccard that flags a cross-stage lookalike (0.3 in the first version, which
flagged 22 of the pilot top 50 on single generic words; raised after review)."""

LOOKALIKE_MIN_SHARED = 2
"""A lookalike also needs at least this many shared name tokens: one shared word is a topic, not
a technique."""

TWIN_MIN = 0.5
"""Two approaches whose work sets overlap by MORE than this share of the smaller set are flagged
`shares-works-with-<id>`: they describe nearly the same papers, so "not co-used" is an artefact."""

_FUNCTION_WORDS = frozenset(
    {"of", "the", "and", "for", "with", "by", "in", "on", "to", "a", "an"}
    | {"over", "from", "via", "using", "into", "at", "as", "or"}
)
GENERIC_WORDS = frozenset(
    {"model", "models", "learning", "based", "network", "networks", "neural", "language"}
    | {"analysis", "method", "methods", "approach", "framework", "system", "systems"}
    | {"using"}
)
"""Words of nearly every method name: sharing one says nothing about the same technique. `agent`
and `agents` are deliberately NOT here: they are central in the pilot corpus, and stopping them
changed no flag in the top 50 (14 flagged candidates either way; 1,531 of 9,506 pairs overall),
so the more conservative choice (more tokens, more flags) is kept."""
_STOP = _FUNCTION_WORDS | GENERIC_WORDS
_TOKEN = re.compile(r"[^\W_]+")


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def check_rank_by(kind: str, rank_by: str) -> None:
    keys = COMBINATION_KEYS if kind == "combinations" else GAP_KEYS
    if rank_by not in keys:
        raise _refuse("rank_by", f"must be one of {', '.join(keys)}")


def check_limit(limit: object) -> None:
    """`limit` is None or a positive int (not a bool)."""
    if limit is None:
        return
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise _refuse("limit", "must be a positive integer or null")


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


def bridge_norm(links: int, pairs: int) -> float:
    """log(1 + links) / log(1 + pairs), clamped to 1; `pairs` is the number of work pairs that
    could be linked. 0.0 without links or pairs."""
    if pairs < 1 or links < 1:
        return 0.0
    return min(1.0, log(1 + links) / log(1 + pairs))


def _stem(token: str) -> str:
    """Strip a trailing `ing`, `ed` or `s` when at least three characters remain (prompting,
    prompted and prompts all give prompt); `ss`, `us` and `is` endings keep their `s`."""
    if token.endswith("ing") and len(token) >= 6:
        return token[:-3]
    if token.endswith("ed") and len(token) >= 5:
        return token[:-2]
    if token.endswith("s") and len(token) >= 4 and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def name_tokens(name: str) -> frozenset[str]:
    """Casefolded, accent-folded (NFKD) alphanumeric tokens of a name, lightly stemmed. Words of
    fewer than 3 characters are dropped, except two-letter ALL-CAPS acronyms (RL, GP, AI); function
    words and generic method words are dropped before and after stemming."""
    folded = "".join(
        ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)
    )
    out: set[str] = set()
    for raw in _TOKEN.findall(folded):
        low = raw.casefold()
        if low in _STOP:
            continue
        if len(raw) == 2 and raw.isalpha() and raw.isupper():
            out.add(low)
            continue
        if len(low) < 3:
            continue
        stem = _stem(low)
        if stem not in _STOP:
            out.add(stem)
    return frozenset(out)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def work_overlap(a: Collection[str], b: Collection[str]) -> tuple[float, float]:
    """(Jaccard of two work sets, shared works over the smaller set); (0, 0) if either is empty."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0, 0.0
    both = len(sa & sb)
    return both / len(sa | sb), both / min(len(sa), len(sb))


@lru_cache(maxsize=16)
def _lookalikes(entries: tuple[tuple[str, str, str], ...]) -> tuple[Lookalike, ...]:
    toks = {i: name_tokens(name) for i, _, name in entries}
    stage = {i: st for i, st, _ in entries}
    name = {i: nm for i, _, nm in entries}
    found: list[Lookalike] = []
    for i, _, _ in entries:
        best: tuple[float, str] | None = None
        for j, _, _ in entries:
            if stage[j] == stage[i]:
                continue
            value = jaccard(toks[i], toks[j])
            if (
                value >= LOOKALIKE_MIN
                and len(toks[i] & toks[j]) >= LOOKALIKE_MIN_SHARED
                and (best is None or value > best[0])
            ):
                best = (value, j)
        if best is not None:
            value, j = best
            found.append(
                Lookalike(of=i, approach_id=j, stage=stage[j], name=name[j], jaccard=_round(value))
            )
    return tuple(found)


def lookalike_cache_info() -> Any:
    return _lookalikes.cache_info()


def lookalike_index(
    catalogue: Mapping[str, tuple[str, str, str]], ids: Iterable[str]
) -> dict[str, Lookalike]:
    """For each id, its closest lookalike among `ids` of ANOTHER stage (highest Jaccard, ties by
    id) when the name-token Jaccard is at least `LOOKALIKE_MIN` and at least
    `LOOKALIKE_MIN_SHARED` tokens are shared. Pure and deterministic; memoised on the (id, stage,
    name) entries, since it is quadratic in the number of approaches."""
    entries = tuple((i, catalogue[i][0], catalogue[i][1]) for i in sorted(set(ids)))
    return {lk.of: lk for lk in _lookalikes(entries)}


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
    twin_share: float = 0.0,
) -> Score:
    low = min(works_a, works_b)
    popularity = low / pool_max if pool_max else 0.0
    relation = stage_relation(stage_a, stage_b)
    stage = STAGE_FACTORS[relation]
    bridge = bridge_norm(links, works_a * works_b)
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
        twin_share=_round(twin_share),
    )


def gap_score(
    *,
    rank_by: str,
    works: int,
    covered: int,
    pool_max: int,
    links: int,
    to_works: int,
) -> Score:
    popularity = works / pool_max if pool_max else 0.0
    strength = 1 - covered / works if works else 0.0
    bridge = bridge_norm(links, works * to_works)
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
