"""Deduplication cascade (pure).

The same paper arrives from four sources, and PRISMA requires the number removed. Merges are
**reversible** — the dedup map records what was absorbed into what and on which rule — so a
bad merge can be undone without re-running the search.

The two error directions are not symmetric, and the threshold is set accordingly:

- a **false split** (one paper kept twice) is noticed at screening;
- a **false merge** (two papers unified) silently deletes a paper, and nothing downstream can
  detect it — the corpus is simply missing something and says nothing.

So this module is deliberately tuned to prefer the error screening will catch.

The researcher's pair decisions enter as `joined` (merge) and `blocked` (never merge) pairs.
Invariant: a joined pair is merged unless a block spans it, directly or through a third work;
a block always wins.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from factory.model.dedup_keys import first_surname, strong_keys, title_bucket_key
from factory.model.work import Work, WorkType
from factory.model.work_ids import normalize_title

TITLE_SIMILARITY_THRESHOLD = 92.0
YEAR_WINDOW = 1

_strong_keys = strong_keys  # the private names before they were shared; kept as aliases


@dataclass(slots=True)
class CascadeMerge:
    """One merge, recorded so it can be reversed."""

    primary: str
    absorbed: list[str] = field(default_factory=list)
    rule: str = ""
    records: int = 1
    """How many input records folded into this work.

    Distinct from `len(absorbed)`: identity is content-derived, so two records of the same DOI
    already share an id and absorb nothing, while still being two records for PRISMA.
    """


@dataclass(slots=True)
class DedupResult:
    works: list[Work]
    merges: list[CascadeMerge]
    input_count: int = 0

    @property
    def removed(self) -> int:
        """The PRISMA 'duplicate records removed before screening' count.

        Derived from records in minus works out, which is the arithmetic PRISMA actually
        asks for. Counting absorbed ids instead would undercount every duplicate pair that
        already shared an identity.
        """
        return self.input_count - len(self.works)


class _Union:
    """Union-find over work ids, remembering which rule joined each pair.

    Each root carries the set of its members, so a join can be refused when a blocked pair
    spans the two components. Refusing at union time (rather than filtering afterwards) is
    what makes blocking transitive: if `a` and `c` are joined and `b` is blocked from `a`,
    `b` can no longer reach `a` through `c` either.
    """

    def __init__(self, blocked: frozenset[frozenset[str]]) -> None:
        self._parent: dict[str, str] = {}
        self._members: dict[str, set[str]] = {}
        self._blocked_with: dict[str, set[str]] = defaultdict(set)
        for pair in blocked:
            first, second = tuple(pair)
            self._blocked_with[first].add(second)
            self._blocked_with[second].add(first)
        self.rules: dict[tuple[str, str], str] = {}

    def add(self, item: str) -> None:
        if item not in self._parent:
            self._parent[item] = item
            self._members[item] = {item}

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:  # path compression
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str, rule: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if len(self._members[ra]) > len(self._members[rb]):
            ra, rb = rb, ra  # ra is now the smaller component
        # Scan the smaller side against the larger one; a blocked pair spanning them refuses
        # the join outright.
        if any(self._blocked_with[x] & self._members[rb] for x in self._members[ra]):
            return
        self._parent[ra] = rb
        self._members[rb] |= self._members.pop(ra)
        pair = (a, b) if a <= b else (b, a)
        self.rules[pair] = rule


def _rank(work: Work) -> tuple[int, int, int, str]:
    """Sort key choosing the primary record of a merge group.

    A published version outranks a preprint: it is the citable record, and the version most
    readers will reach. Beyond that, prefer whichever record carries more identifiers and more
    abstract, then fall back to the id so the choice is deterministic.
    """
    is_preprint = work.type is WorkType.PREPRINT
    identifier_count = sum(1 for v in work.identifiers.model_dump().values() if v is not None)
    return (int(is_preprint), -identifier_count, -len(work.abstract or ""), work.id)


def merge_works(group: list[Work]) -> Work:
    """Fold a group into one record, keeping every identifier and every provenance entry."""
    ordered = sorted(group, key=_rank)
    primary, others = ordered[0], ordered[1:]

    # Fill the primary's empty identifiers from the others. Collected as a dict and applied in
    # one `model_copy`, because `Identifiers` is frozen.
    primary_ids = primary.identifiers.model_dump()
    filled: dict[str, str] = {}
    for other in others:
        for field_name, value in other.identifiers.model_dump().items():
            if value is not None and primary_ids[field_name] is None and field_name not in filled:
                filled[field_name] = value
    identifiers = primary.identifiers.model_copy(update=filled)

    # Ordered by discovery, not by which record happened to win the primary slot: PRISMA
    # attributes a record to the pass that found it first, and that must not depend on an
    # unrelated ranking decision.
    provenance = []
    seen: set[tuple[str, str, str]] = set()
    for entry in sorted(
        (e for work in ordered for e in work.provenance),
        key=lambda e: (e.at, e.source, e.run_id),
    ):
        if (key := (entry.source, entry.run_id, entry.query_id)) not in seen:
            seen.add(key)
            provenance.append(entry)

    # Records sharing the primary's id (same content identity) absorb and supersede nothing:
    # they are extra records for PRISMA, which `provenance` already carries.
    absorbed_ids = {o.id for o in others} - {primary.id}
    primary_is_preprint = primary.type is WorkType.PREPRINT
    superseded = {
        o.id for o in others if o.type is WorkType.PREPRINT and not primary_is_preprint
    } - {primary.id}

    return primary.model_copy(
        update={
            "identifiers": identifiers,
            "provenance": provenance,
            "absorbed": sorted({*primary.absorbed, *absorbed_ids}),
            "supersedes": sorted({*primary.supersedes, *superseded}),
            "abstract": primary.abstract or next((o.abstract for o in others if o.abstract), None),
            "cited_by_count": max(
                (w.cited_by_count for w in ordered if w.cited_by_count is not None), default=None
            ),
            "retracted": any(w.retracted for w in ordered),
        }
    )


def dedup(
    works: list[Work],
    *,
    blocked: frozenset[frozenset[str]] = frozenset(),
    joined: frozenset[frozenset[str]] = frozenset(),
    aliases: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> DedupResult:
    """Merge duplicates across the corpus, returning the survivors and a reversible map.

    `blocked` holds pairs of work ids that must never end up in the same group, e.g. a merge a
    human reverted. The block holds even when the pair is reachable through a third record.
    `aliases` maps a work id to extra exact-match keys (the published identifiers a version link
    attached to it), which join works by identifier like their own keys. `joined` holds pairs the
    researcher ruled to be the same work: each pair whose two works are both present is merged
    with rule `version-pair` after the identifier stages and before the title stage, unless a
    block refuses it (a block always wins). `progress`, when given,
    is called with `(works compared, total)` as the title comparison advances; it changes nothing.
    """
    extra = aliases or {}
    union = _Union(blocked)
    by_id = {w.id: w for w in works}
    for work in works:
        union.add(work.id)

    # Stage 1-2: exact identifier matches.
    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for work in works:
        for key in [*strong_keys(work), *extra.get(work.id, ())]:
            by_key[key].append(work.id)
    for (kind, _), ids in by_key.items():
        for other in ids[1:]:
            union.union(ids[0], other, f"identifier:{kind}")

    # The researcher's "same work" rulings; `union` refuses any join across a blocked pair.
    for pair in sorted(tuple(sorted(p)) for p in joined if len(p) == 2):
        if pair[0] in by_id and pair[1] in by_id:
            union.union(pair[0], pair[1], "version-pair")

    # Stage 3-4: title similarity, blocked by year so this stays tractable.
    by_year: dict[int | None, list[Work]] = defaultdict(list)
    for work in works:
        by_year[work.dates.year].append(work)

    titles = {w.id: normalize_title(w.title) for w in works}
    compared = 0
    for year, bucket in by_year.items():
        candidates = list(bucket)
        if year is not None:
            for offset in range(1, YEAR_WINDOW + 1):
                candidates += by_year.get(year + offset, [])
        for i, left in enumerate(bucket):
            compared += 1
            if progress is not None:
                progress(compared, len(works))
            for right in candidates[i + 1 :]:
                if left.id == right.id or union.find(left.id) == union.find(right.id):
                    continue
                score = fuzz.token_sort_ratio(titles[left.id], titles[right.id])
                if score < TITLE_SIMILARITY_THRESHOLD:
                    continue
                # Title alone is not enough: distinct papers share titles, and a false merge
                # is the unrecoverable error. Require the first author to agree too.
                if first_surname(left) and first_surname(left) == first_surname(right):
                    union.union(left.id, right.id, f"title+author:{score:.0f}")

    groups: dict[str, list[Work]] = defaultdict(list)
    for work in works:
        groups[union.find(work.id)].append(work)

    survivors: list[Work] = []
    merges: list[CascadeMerge] = []
    for members in groups.values():
        if len(members) == 1:
            survivors.append(members[0])
            continue
        merged = merge_works(members)
        survivors.append(merged)
        rules = {
            rule
            for (a, b), rule in union.rules.items()
            if a in by_id and b in by_id and union.find(a) == union.find(merged.id)
        }
        merges.append(
            CascadeMerge(
                primary=merged.id,
                absorbed=sorted({m.id for m in members if m.id != merged.id}),
                rule=", ".join(sorted(rules)) or "identity",
                records=len(members),
            )
        )

    survivors.sort(key=lambda w: w.id)
    merges.sort(key=lambda m: m.primary)
    return DedupResult(works=survivors, merges=merges, input_count=len(works))


def cascade_match(
    new: Work,
    candidates: list[Work],
    blocked: frozenset[frozenset[str]] = frozenset(),
    *,
    joined: frozenset[frozenset[str]] = frozenset(),
) -> CascadeMerge | None:
    """The merge `new` joins when the cascade runs over `new` and `candidates`, or None.

    The group is the one containing `new`; it is reported only when it absorbs another work.
    """
    result = dedup(
        [new, *[c for c in candidates if c.id != new.id]], blocked=blocked, joined=joined
    )
    for merge in result.merges:
        if merge.absorbed and new.id in (merge.primary, *merge.absorbed):
            return merge
    return None


__all__ = [
    "TITLE_SIMILARITY_THRESHOLD",
    "YEAR_WINDOW",
    "CascadeMerge",
    "DedupResult",
    "cascade_match",
    "dedup",
    "merge_works",
    "normalize_title",
    "strong_keys",
    "title_bucket_key",
]
