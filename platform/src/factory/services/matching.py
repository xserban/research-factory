"""The matching builder: which method cards fit a problem description (slice 6, plan H-B).

A computed candidate list, never a conclusion (decision 68). Invariants:
- Only effective assertions that are `stated` or `confirmed` (plus `inferred` when the caller
  widens the query) feed a match, on both sides. A stale or rejected assertion never does.
- The problem's required properties are its effective assertions on properties that apply to
  problems. A method card is a candidate when it has at least one effective assertion on a
  required key; cards without one are never read. Candidates are read in batches by card id.
- Per required property the property's rule yields satisfied, conflicting or unknown; cards are
  ordered lexicographically (`order_key`), never by a score. Nothing is compared across
  comparability groups: evidence groups are listed per card, not compared.
- `transfer` is True when no member work of the card's subject is included in this project.
- The output carries `match_key`, a hash of its inputs, so a later reader can see that they
  changed. The builder writes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.hypotheses.match import (
    Outcome,
    Value,
    match_key,
    order_key,
    row_key,
    rule_outcome,
)
from factory.model.base import StrictModel
from factory.model.cards import PropertyDef, PropertyKind
from factory.model.lineage import IDEA_ID_RE
from factory.services.cards import CardPropRow, effective_card_props, property_family
from factory.services.context import Project
from factory.services.evidence_report import group_id
from factory.services.extraction_agreement import grouped_rows
from factory.services.ideas import idea_view, resolve_idea
from factory.services.properties import resolve_property, vocabulary_version
from factory.services.references import included_works

BATCH = 200
LIMIT_MAX = 500
DEFAULT_STATUSES = ["stated", "confirmed"]
_IDEA = re.compile(IDEA_ID_RE)


class MatchRow(StrictModel):
    row_key: str
    card_id: str
    subject: str
    satisfied: list[str]
    conflicting: list[str]
    unknown: list[str]
    transfer: bool
    members_included: list[str]
    evidence_groups: list[str]


class MatchPage(StrictModel):
    match_key: str
    problem_id: str
    vocabulary_version: str
    statuses: list[str]
    rows: list[MatchRow]
    next_after: str | None
    candidates: int
    """Method cards with at least one effective assertion on a required property."""


@dataclass
class _Candidate:
    card_id: str
    subject: str
    assertion_ids: list[str]
    satisfied: list[str] = field(default_factory=list)
    conflicting: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def order(self) -> tuple[int, int, int, str]:
        return order_key(
            len(self.conflicting), len(self.satisfied), len(self.unknown), self.card_id
        )


def _refuse(field_name: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, reason)])


def _values(
    define: Callable[[str], PropertyDef | None],
    rows: Sequence[CardPropRow],
    assertions: dict[str, str],
) -> dict[str, tuple[PropertyDef, Value]]:
    """One value per property key from effective rows: the latest assertion's. Number values
    are canonical decimals; `assertions` collects the assertion id kept per key."""
    latest: dict[str, str] = {}
    for row in rows:
        if row.assertion_id > latest.get(row.property_key, ""):
            latest[row.property_key] = row.assertion_id
    out: dict[str, tuple[PropertyDef, Value]] = {}
    for key, aid in latest.items():
        defn = define(key)
        if defn is None:
            continue
        mine = [r for r in rows if r.assertion_id == aid]
        norms = sorted(r.value_norm for r in mine)
        value: Value
        if defn.kind is PropertyKind.NUMBER:
            canon = mine[0].number_canonical or mine[0].value_norm
            value = Decimal(canon)
        elif defn.kind is PropertyKind.BOOL:
            value = norms[0] == "true"
        else:
            value = tuple(norms)
        out[key] = (defn, value)
        assertions[key] = aid
    return out


def _problem(
    project: Project, problem_id: str, statuses: list[str]
) -> tuple[dict[str, tuple[PropertyDef, Value]], list[str]]:
    with project.index.connect() as conn:
        card = conn.execute(
            text("SELECT kind FROM cards WHERE card_id = :c"), {"c": problem_id}
        ).first()
        if card is None or str(card[0]) != "problem":
            raise _refuse("problem_id", "not-a-problem-card")
        keys = [
            str(r[0])
            for r in conn.execute(
                text("SELECT DISTINCT property_key FROM card_props WHERE card_id = :c"),
                {"c": problem_id},
            )
        ]
    rows = list(effective_card_props(project, keys, statuses, card_ids=[problem_id]))
    kept: dict[str, str] = {}
    values = _values(lambda k: resolve_property(project, k), rows, kept)
    required = {k: v for k, v in values.items() if v[0].applies_to in ("problem", "both")}
    return required, sorted(kept[k] for k in required)


def _candidate_ids(project: Project, family: list[str], after: str) -> list[str]:
    marks = ", ".join(f":k{i}" for i in range(len(family)))
    params: dict[str, object] = {f"k{i}": k for i, k in enumerate(family)}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT p.card_id FROM card_props p JOIN cards c ON c.card_id = p.card_id "
                f"WHERE c.kind = 'method' AND p.property_key IN ({marks}) AND p.card_id > :after "
                "ORDER BY p.card_id LIMIT :n"
            ),
            {**params, "after": after, "n": BATCH},
        ).all()
    return [str(r[0]) for r in rows]


def _subjects(project: Project, ids: Sequence[str]) -> dict[str, str]:
    marks = ", ".join(f":c{i}" for i in range(len(ids)))
    with project.index.connect() as conn:
        rows = conn.execute(
            text(f"SELECT card_id, subject FROM cards WHERE card_id IN ({marks})"),
            {f"c{i}": c for i, c in enumerate(ids)},
        ).all()
    return {str(r[0]): str(r[1]) for r in rows}


def _candidates(
    project: Project,
    required: dict[str, tuple[PropertyDef, Value]],
    statuses: list[str],
) -> list[_Candidate]:
    family = sorted(property_family(project, list(required)))
    found: list[_Candidate] = []
    cursor = ""
    while family:
        ids = _candidate_ids(project, family, cursor)
        if not ids:
            break
        cursor = ids[-1]
        by_card: dict[str, list[CardPropRow]] = {}
        for row in effective_card_props(project, list(required), statuses, card_ids=ids):
            by_card.setdefault(row.card_id, []).append(row)
        subjects = _subjects(project, list(by_card)) if by_card else {}
        for card_id in sorted(by_card):
            kept: dict[str, str] = {}
            have = _values(
                lambda k: required[k][0] if k in required else None, by_card[card_id], kept
            )
            candidate = _Candidate(card_id, subjects[card_id], sorted(kept.values()))
            for key, (defn, wanted) in sorted(required.items()):
                found_value = have.get(key)
                outcome: Outcome = rule_outcome(
                    defn, wanted, None if found_value is None else found_value[1]
                )
                getattr(candidate, outcome).append(key)
            found.append(candidate)
    return found


def subject_works(project: Project, subject: str) -> list[str]:
    """The member works of a card's subject: the work itself, or an idea's effective members."""
    if _IDEA.fullmatch(subject):
        view = idea_view(project, resolve_idea(project, subject))
        return [] if view is None else sorted(view.effective_members)
    return [subject]


def match(
    project: Project,
    problem_id: str,
    *,
    include_inferred: bool = False,
    transfer_only: bool = False,
    scope: Literal["project"] = "project",
    limit: int = 50,
    after: str | None = None,
) -> MatchPage:
    """Method cards matched against the problem description `problem_id`, one page.

    Refused, with nothing written: a card that is not a problem description (`problem_id`), a
    `limit` outside 1..500, a cursor `after` that is not a card of this result. `scope` is the
    project (regions are Later). `transfer_only` keeps cards with `transfer` set."""
    if not 1 <= limit <= LIMIT_MAX:
        raise _refuse("limit", f"between 1 and {LIMIT_MAX}")
    project.index.sync()
    statuses = DEFAULT_STATUSES + (["inferred"] if include_inferred else [])
    required, problem_assertions = _problem(project, problem_id, statuses)
    version = vocabulary_version(project)
    candidates = _candidates(project, required, statuses)
    key = match_key(
        (problem_id, problem_assertions),
        [(c.card_id, c.assertion_ids) for c in candidates],
        version,
    )
    included = set(included_works(project))
    members: dict[str, list[str]] = {}

    def member_works(c: _Candidate) -> list[str]:
        if c.subject not in members:
            members[c.subject] = subject_works(project, c.subject)
        return members[c.subject]

    shown = sorted(candidates, key=_Candidate.order)
    if transfer_only:
        shown = [c for c in shown if not set(member_works(c)) & included]
    start = 0
    if after is not None:
        position = next((i for i, c in enumerate(shown) if c.card_id == after), None)
        if position is None:
            raise _refuse("after", "not-in-result")
        start = position + 1
    window = shown[start : start + limit]
    next_after = window[-1].card_id if window and start + limit < len(shown) else None
    groups = _groups_by_work(project) if any(member_works(c) for c in window) else {}
    rows = []
    for c in window:
        works = member_works(c)
        inside = [w for w in works if w in included]
        rows.append(
            MatchRow(
                row_key=row_key(key, c.card_id),
                card_id=c.card_id,
                subject=c.subject,
                satisfied=c.satisfied,
                conflicting=c.conflicting,
                unknown=c.unknown,
                transfer=not inside,
                members_included=inside,
                evidence_groups=sorted({g for w in works for g in groups.get(w, ())}),
            )
        )
    return MatchPage(
        match_key=key,
        problem_id=problem_id,
        vocabulary_version=version,
        statuses=statuses,
        rows=rows,
        next_after=next_after,
        candidates=len(candidates),
    )


def _groups_by_work(project: Project) -> dict[str, set[str]]:
    """Evidence groups holding a final row of each work. Listed, never compared."""
    out: dict[str, set[str]] = {}
    for key, rows in grouped_rows(project).groups.items():
        gid = group_id(list(key))
        for row in rows:
            out.setdefault(row.work_id, set()).add(gid)
    return out
