"""Check Claude's candidate proposals and compute their tiers and coverage (plan chat T6).

Claude reads the claims digest (and, where useful, keyword hits, miner rows, the graph) and
proposes the papers that bear on a question, each with the source that proposed it and a stance.
The platform judges nothing: it validates the proposals and computes what follows from them.

Invariants:
- Read-only, no event is written. Deterministic: the same spec and proposals give the same result.
- Validated at the boundary: every issue is collected with a field path `proposals[i].<field>`
  (`mode` and `tier1_cap` for the arguments) and, when any exists, nothing is returned.
  Refused: an unknown source, stance or mode; a work that is no work of the project or is not in
  the selection (ids pass the IDEA-66 resolver); no quote for source `claims` or `keyword`; an
  anchor without a quote or a quote without an anchor; a quote that is not in the anchor's
  element of the work's pinned conversion (`chat_verify`'s check).
- Every work of the resolved selection appears exactly once, ordered by work id, with its sources
  and stances (sorted), its tier and `over_cap`. Tier 1: two or more distinct sources, or any
  `researcher` proposal; tier 2: exactly one source; tier 3: not proposed.
- In `explore` mode, when more than `tier1_cap` works are tier 1, the cap keeps the first
  `tier1_cap` by (researcher pick first, more sources first, work id) and marks the rest
  `over_cap`; they stay tier 1 and listed. `prepare` mode has no cap.
- Counts per tier, per stance (works carrying that stance; a work with both counts in both) and
  of proposals are computed from the result, never typed. `total` equals the selection size.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.chat_read import VerifyItem, chat_verify
from factory.services.context import Project
from factory.services.selection import SelectionSpec, resolve_selection_cached
from factory.services.work_ref import resolve_work_id

__all__ = [
    "TIER1_CAP",
    "Candidate",
    "CandidateInput",
    "CandidateSource",
    "Candidates",
    "Stance",
    "chat_candidates",
]

TIER1_CAP = 15
QUOTED_SOURCES = frozenset({"claims", "keyword"})


class CandidateSource(StrEnum):
    CLAIMS = "claims"
    KEYWORD = "keyword"
    MINER = "miner"
    GRAPH = "graph"
    RESEARCHER = "researcher"


class Stance(StrEnum):
    AGAINST = "against"
    FOR = "for"


@dataclass(frozen=True)
class CandidateInput:
    """One proposal. `source` and `stance` may be given as strings; they are validated."""

    work_id: str
    source: str
    stance: str
    anchor: str | None = None
    quote: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Candidate:
    """One work of the selection with what proposed it. `quotes` are `(source, stance, anchor,
    quote)` of its verified proposals that carry one."""

    work_id: str
    sources: tuple[str, ...]
    stances: tuple[str, ...]
    tier: int
    over_cap: bool
    quotes: tuple[tuple[str, str, str, str], ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Candidates:
    """The tiers of a selection (see the module invariants). `by_tier` maps tier 1, 2, 3 to the
    number of works; `by_stance` maps `against` and `for` to the number of works carrying it."""

    selection_digest: str
    mode: str
    tier1_cap: int
    candidates: tuple[Candidate, ...]
    by_tier: dict[int, int]
    by_stance: dict[str, int]
    over_cap: int
    proposals: int
    total: int


def _enum(value: str, kind: type[StrEnum]) -> bool:
    return value in {m.value for m in kind}


def chat_candidates(
    project: Project,
    spec: SelectionSpec,
    proposals: Sequence[CandidateInput],
    *,
    mode: Literal["explore", "prepare"] = "explore",
    tier1_cap: int = TIER1_CAP,
) -> Candidates:
    """Validate `proposals` against the selection of `spec` and compute tiers and coverage (see
    the module invariants). Raises `FactoryValidationError` listing every issue."""
    project.index.sync()
    issues: list[ValidationIssue] = []
    if mode not in ("explore", "prepare"):
        issues.append(ValidationIssue("mode", f"{mode}: must be explore or prepare"))
    if tier1_cap < 1:
        issues.append(ValidationIssue("tier1_cap", "must be at least 1"))
    selection = resolve_selection_cached(project, spec)
    pinned = {w.work_id: w.conversion_id for w in selection.works}

    accepted: list[tuple[str, CandidateInput]] = []
    checks: list[tuple[int, str, VerifyItem]] = []
    for i, p in enumerate(proposals):
        at = f"proposals[{i}]"
        ok = True
        if not _enum(p.source, CandidateSource):
            issues.append(ValidationIssue(f"{at}.source", f"unknown source: {p.source}"))
            ok = False
        if not _enum(p.stance, Stance):
            issues.append(ValidationIssue(f"{at}.stance", f"unknown stance: {p.stance}"))
            ok = False
        try:
            work = resolve_work_id(project, p.work_id, field=f"{at}.work_id")
        except FactoryValidationError as err:
            issues.extend(err.issues)
            continue
        if work not in pinned:
            known = _is_project_work(project, work)
            reason = "not in the selection" if known else "unknown work"
            issues.append(ValidationIssue(f"{at}.work_id", f"{work}: {reason}"))
            continue
        needs = p.source in QUOTED_SOURCES
        has_quote = bool(p.quote and p.quote.strip())
        has_anchor = bool(p.anchor and p.anchor.strip())
        if needs and not has_quote:
            issues.append(ValidationIssue(f"{at}.quote", f"a quote is required for {p.source}"))
            ok = False
        if has_quote != has_anchor:
            missing = "anchor" if has_quote else "quote"
            issues.append(ValidationIssue(f"{at}.{missing}", f"{missing} is required with its pair"))
            ok = False
        if ok and has_quote and has_anchor:
            assert p.anchor is not None and p.quote is not None
            checks.append((i, work, VerifyItem(work, p.anchor, p.quote, pinned[work])))
        if ok:
            accepted.append((work, p))
    if checks:
        for (i, _work, _item), result in zip(
            checks, chat_verify(project, [c[2] for c in checks]), strict=True
        ):
            if result.status != "accepted":
                issues.append(
                    ValidationIssue(f"proposals[{i}].quote", f"{result.status}: {result.item.anchor}")
                )
    if issues:
        raise FactoryValidationError(issues)

    sources: dict[str, set[str]] = {w: set() for w in pinned}
    stances: dict[str, set[str]] = {w: set() for w in pinned}
    quotes: dict[str, list[tuple[str, str, str, str]]] = {w: [] for w in pinned}
    notes: dict[str, list[str]] = {w: [] for w in pinned}
    for work, p in accepted:
        sources[work].add(p.source)
        stances[work].add(p.stance)
        if p.anchor and p.quote:
            quotes[work].append((p.source, p.stance, p.anchor, p.quote))
        if p.note:
            notes[work].append(p.note)

    def tier_of(work: str) -> int:
        found = sources[work]
        if len(found) >= 2 or CandidateSource.RESEARCHER.value in found:
            return 1
        return 2 if found else 3

    tiers = {w: tier_of(w) for w in pinned}
    over: set[str] = set()
    if mode == "explore":
        first = sorted(
            (w for w, t in tiers.items() if t == 1),
            key=lambda w: (
                CandidateSource.RESEARCHER.value not in sources[w],
                -len(sources[w]),
                w,
            ),
        )
        over = set(first[tier1_cap:])
    result = tuple(
        Candidate(
            w,
            tuple(sorted(sources[w])),
            tuple(sorted(stances[w])),
            tiers[w],
            w in over,
            tuple(quotes[w]),
            tuple(notes[w]),
        )
        for w in sorted(pinned)
    )
    return Candidates(
        selection_digest=selection.digest,
        mode=mode,
        tier1_cap=tier1_cap,
        candidates=result,
        by_tier={t: sum(1 for c in result if c.tier == t) for t in (1, 2, 3)},
        by_stance={s.value: sum(1 for c in result if s.value in c.stances) for s in Stance},
        over_cap=len(over),
        proposals=len(accepted),
        total=len(result),
    )


def _is_project_work(project: Project, work_id: str) -> bool:
    from sqlalchemy import text

    with project.index.connect() as conn:
        row = conn.execute(text("SELECT 1 FROM works WHERE work_id = :w"), {"w": work_id}).first()
    return row is not None
