"""Argument sheets: open, argue, close a section, rate, view (plan chat T7, section 4.6).

A sheet is the recorded result of a Spar session: the hypothesis, the candidates computed over a
selection (`chat_candidates`), and the arguments against and for. The platform judges nothing: the
agent writes the arguments and gives each a strength; the platform verifies every quote, enforces
the order of the sections and computes the coverage.

Invariants:
- Written only by an agent session (`sheet.opened`, `sheet.argument_recorded`,
  `sheet.section_closed`), each event with the session's model, skill and an `input_blob`; the
  rating (`sheet.argument_rated`) only by a human. A refusal writes nothing and reports every
  issue together, located as `arguments[i].<field>`, `proposals[i].<field>` or a plain field.
- Opening a sheet runs `chat_candidates` over the proposals: the candidates table, its digest and
  its counts are computed, never typed. The input blob holds the proposals and the full table.
- An argument names a work of the sheet's selection, an anchor and a quote that `chat_verify`
  accepts in the conversation the selection pins; the selection must still resolve to the digest
  recorded when the sheet opened, else the sheet is stale and a new one is opened. The verified
  conversion id and markdown hash are recorded with the argument. A claim row key, when given,
  must be a row of the listed m-claims miner for that work.
- Order: arguments against are recorded while the section against is open; the section for takes
  arguments only after the section against is closed, and in `prepare` mode only from a session
  that recorded none against. A section closes once; `for` only after `against`.
- Coverage is computed from the folded rows (`view_sheet`): works per tier and per source, works
  with arguments per stance, tier-1 works without any argument, ratings. Strength is labelled as
  the writer's judgement; nothing here states a balance.
- Held-out handling is that of the tools that call this module (scrub of every reply).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, get_args

from sqlalchemy import text

from factory.canonical import canonical_json
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.mining.spec import Population
from factory.model.sheets import (
    ARGUMENT_ID_RE,
    CLAIM_MAX,
    HYPOTHESIS_MAX,
    NOTE_MAX,
    SHEET_ID_RE,
    Mode,
    Rating,
    Section,
    SheetArgumentRated,
    SheetArgumentRecorded,
    SheetCandidate,
    SheetOpened,
    SheetSectionClosed,
    Strength,
)
from factory.services.chat_candidates import (
    TIER1_CAP,
    CandidateInput,
    Candidates,
    chat_candidates,
)
from factory.services.chat_read import VerifyItem, chat_verify
from factory.services.context import Project
from factory.services.paper_profile import listed_miner_versions, load_miner_work_rows
from factory.services.selection import SelectionSpec, resolve_selection_cached
from factory.services.work_ref import resolve_work_id

__all__ = [
    "BALANCE_LABEL",
    "ArgumentInput",
    "ArgumentView",
    "SheetCoverage",
    "SheetInfo",
    "SheetView",
    "close_section",
    "list_sheets",
    "open_sheet",
    "rate_argument",
    "record_arguments",
    "view_sheet",
]

CLAIMS_MINER = "m-claims"
BALANCE_LABEL = (
    "Counts, tiers and coverage are computed. A strength is the writer's judgement of how strongly "
    "a verified quote bears on the hypothesis; a rating is the researcher's. A verified quote "
    "is not a verified reading. No balance is stated."
)


@dataclass(frozen=True)
class ArgumentInput:
    """One argument as an agent proposes it; `stance` and `strength` are validated."""

    stance: str
    work_id: str
    anchor: str
    quote: str
    claim: str
    strength: str
    claim_row_key: str | None = None


@dataclass(frozen=True)
class SheetInfo:
    sheet_id: str
    hypothesis: str
    mode: str
    selection_digest: str
    candidates_digest: str
    against_closed: bool
    for_closed: bool
    supersedes: str | None
    arguments: int
    actor: str
    session: str | None
    ts: str


@dataclass(frozen=True)
class ArgumentView:
    argument_id: str
    stance: str
    work_id: str
    anchor: str
    quote: str
    claim: str
    claim_row_key: str | None
    strength: str
    conversion_id: str
    markdown_hash: str
    actor: str
    model: str | None
    rating: str | None
    rating_note: str | None


@dataclass(frozen=True)
class SheetCoverage:
    """Computed from the folded rows, never typed."""

    total: int
    by_tier: dict[int, int]
    by_source: dict[str, int]
    over_cap: int
    arguments: dict[str, int]
    works_argued: dict[str, int]
    by_strength: dict[str, int]
    ratings: dict[str, int]
    unrated: int
    tier1_unargued: tuple[str, ...]
    works_without_claims_source: int


@dataclass(frozen=True)
class SheetView:
    info: SheetInfo
    arguments: tuple[ArgumentView, ...]
    coverage: SheetCoverage
    balance_label: str = BALANCE_LABEL
    selection: dict[str, Any] = field(default_factory=dict)


def _issue(field_name: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, message)])


def _require_agent(actor: Actor) -> None:
    if actor.kind != "agent":
        raise _issue("actor", "an agent session records a sheet")


def _spec_of(raw: dict[str, Any]) -> SelectionSpec:
    return SelectionSpec(
        layers=list(raw.get("layers", [])),
        include=list(raw.get("include", [])),
        exclude=list(raw.get("exclude", [])),
        population=Population(raw.get("population", Population.INCLUDED_FT.value)),
    )


def _sheet_row(project: Project, sheet_id: str) -> dict[str, Any] | None:
    with project.index.connect() as conn:
        row = (
            conn.execute(text("SELECT * FROM sheets WHERE sheet_id = :s"), {"s": sheet_id})
            .mappings()
            .first()
        )
    return None if row is None else dict(row)


def _digest(candidates: Candidates) -> tuple[str, tuple[SheetCandidate, ...]]:
    table = tuple(
        SheetCandidate(
            work_id=c.work_id,
            tier=c.tier,
            sources=tuple(c.sources),
            stances=tuple(c.stances),
            over_cap=c.over_cap,
        )
        for c in candidates.candidates
    )
    body = canonical_json([c.model_dump(mode="json") for c in table])
    return hashlib.sha256(body).hexdigest(), table


def open_sheet(
    project: Project,
    actor: Actor,
    hypothesis: str,
    spec: SelectionSpec,
    proposals: Sequence[CandidateInput],
    *,
    mode: Mode = "explore",
    tier1_cap: int = TIER1_CAP,
    supersedes: str | None = None,
) -> SheetOpened:
    """Open a sheet over the selection of `spec`: run `chat_candidates` on `proposals` and record
    the computed table. Raises `FactoryValidationError` (nothing written) for a system or human
    actor, an empty or over-long hypothesis, a `supersedes` that is no sheet, or any issue of the
    candidates check."""
    _require_agent(actor)
    issues: list[ValidationIssue] = []
    hypothesis = hypothesis.strip()
    if not hypothesis or len(hypothesis) > HYPOTHESIS_MAX:
        issues.append(
            ValidationIssue("hypothesis", f"a hypothesis has 1 to {HYPOTHESIS_MAX} characters")
        )
    project.index.sync()
    if supersedes is not None and _sheet_row(project, supersedes) is None:
        issues.append(ValidationIssue("supersedes", f"{supersedes}: no such sheet"))
    if issues:
        raise FactoryValidationError(issues)
    result = chat_candidates(project, spec, proposals, mode=mode, tier1_cap=tier1_cap)
    digest, table = _digest(result)
    sheet_id = project.ids.new("sht")
    payload = SheetOpened(
        sheet_id=sheet_id,
        hypothesis=hypothesis,
        mode=mode,
        selection=spec.model_dump(mode="json"),
        selection_digest=result.selection_digest,
        candidates_digest=digest,
        candidates=table,
        tier1_cap=tier1_cap,
        supersedes=supersedes,
    )
    blob = project.blobs.put_json(
        {
            "sheet_id": sheet_id,
            "hypothesis": hypothesis,
            "proposals": [{k: v for k, v in vars(p).items() if v is not None} for p in proposals],
            "candidates": [
                {
                    "work_id": c.work_id,
                    "tier": c.tier,
                    "sources": list(c.sources),
                    "stances": list(c.stances),
                    "over_cap": c.over_cap,
                    "quotes": [list(q) for q in c.quotes],
                    "notes": list(c.notes),
                }
                for c in result.candidates
            ],
        }
    )
    with project.index.exclusive():
        event = project.events.make(
            "sheet.opened", payload, actor, refs=(sheet_id,), input_blob=blob
        )
        project.record([event])
    return payload


def _state_issues(
    row: dict[str, Any], stance: str, session: str | None, wrote_against: bool
) -> list[ValidationIssue]:
    if stance == "against" and row["against_closed"]:
        return [ValidationIssue("stance", "the section against is closed")]
    if stance == "for":
        if not row["against_closed"]:
            return [ValidationIssue("stance", "close the section against before the case for")]
        if row["for_closed"]:
            return [ValidationIssue("stance", "the section for is closed")]
        if row["mode"] == "prepare" and wrote_against:
            return [
                ValidationIssue(
                    "session",
                    "in prepare mode the case for is written by a session that wrote no argument "
                    "against",
                )
            ]
    return []


def _wrote_against(project: Project, sheet_id: str, session: str | None) -> bool:
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM sheet_arguments WHERE sheet_id = :s AND stance = 'against' "
                    "AND session = :x LIMIT 1"
                ),
                {"s": sheet_id, "x": session},
            ).first()
            is not None
        )


def record_arguments(
    project: Project, actor: Actor, sheet_id: str, arguments: Sequence[ArgumentInput]
) -> list[SheetArgumentRecorded]:
    """Record the arguments of one section of a sheet, all or none (see the module invariants).
    Every argument of a call has the same stance."""
    _require_agent(actor)
    project.index.sync()
    row = _sheet_row(project, sheet_id)
    if row is None:
        raise _issue("sheet_id", f"{sheet_id}: no such sheet")
    if not arguments:
        raise _issue("arguments", "give at least one argument")
    issues: list[ValidationIssue] = []
    stances = {a.stance for a in arguments}
    if len(stances) > 1:
        issues.append(ValidationIssue("arguments", "one call records one section"))
    stance = arguments[0].stance
    if stance not in get_args(Section):
        issues.append(ValidationIssue("arguments[0].stance", f"{stance}: must be against or for"))
    else:
        issues.extend(
            _state_issues(
                row, stance, actor.session, _wrote_against(project, sheet_id, actor.session)
            )
        )
    selection = resolve_selection_cached(project, _spec_of(_loads(row["selection"])))
    if selection.digest != row["selection_digest"]:
        issues.append(
            ValidationIssue(
                "sheet_id", "the selection changed since the sheet opened; open a new sheet"
            )
        )
    pinned = {w.work_id: w.conversion_id for w in selection.works}
    with project.index.connect() as conn:
        in_sheet = {
            str(w)
            for (w,) in conn.execute(
                text("SELECT work_id FROM sheet_candidates WHERE sheet_id = :s"),
                {"s": sheet_id},
            )
        }
    claim_keys: dict[str, set[str]] = {}
    checks: list[tuple[int, str]] = []
    for i, a in enumerate(arguments):
        at = f"arguments[{i}]"
        if a.stance != stance:
            continue
        if a.strength not in get_args(Strength):
            issues.append(
                ValidationIssue(f"{at}.strength", f"{a.strength}: must be strong, moderate or weak")
            )
        claim = a.claim.strip()
        if not claim or len(claim) > CLAIM_MAX:
            issues.append(
                ValidationIssue(f"{at}.claim", f"a claim has 1 to {CLAIM_MAX} characters")
            )
        if not a.anchor.strip():
            issues.append(ValidationIssue(f"{at}.anchor", "is required"))
        if not a.quote.strip():
            issues.append(ValidationIssue(f"{at}.quote", "is required"))
        try:
            work = resolve_work_id(project, a.work_id, field=f"{at}.work_id")
        except FactoryValidationError as err:
            issues.extend(err.issues)
            continue
        if work not in in_sheet or work not in pinned:
            issues.append(ValidationIssue(f"{at}.work_id", f"{work}: not in the sheet's selection"))
            continue
        if a.claim_row_key:
            if work not in claim_keys:
                claim_keys[work] = _claim_keys(project, work)
            if a.claim_row_key not in claim_keys[work]:
                issues.append(
                    ValidationIssue(
                        f"{at}.claim_row_key", f"{a.claim_row_key}: no {CLAIMS_MINER} row of {work}"
                    )
                )
        if a.anchor.strip() and a.quote.strip():
            checks.append((i, work))
    verdicts: dict[int, Any] = {}
    if checks:
        items = [
            VerifyItem(work, arguments[i].anchor, arguments[i].quote, pinned[work])
            for i, work in checks
        ]
        for (i, _work), verdict in zip(checks, chat_verify(project, items), strict=True):
            verdicts[i] = verdict
            if verdict.status != "accepted":
                issues.append(
                    ValidationIssue(
                        f"arguments[{i}].quote", f"{verdict.status}: {verdict.item.anchor}"
                    )
                )
    if issues:
        raise FactoryValidationError(issues)
    blob = project.blobs.put_json(
        {
            "sheet_id": sheet_id,
            "verified": [
                {
                    "work_id": v.item.work_id,
                    "anchor": v.item.anchor,
                    "quote": v.item.quote,
                    "status": v.status,
                    "conversion_id": v.conversion_id,
                    "markdown_hash": v.markdown_hash,
                }
                for v in verdicts.values()
            ],
        }
    )
    recorded: list[SheetArgumentRecorded] = []
    with project.index.exclusive():
        row = _sheet_row(project, sheet_id)  # re-read under the lock: sections may have moved
        assert row is not None
        late = _state_issues(
            row, stance, actor.session, _wrote_against(project, sheet_id, actor.session)
        )
        if late:
            raise FactoryValidationError(late)
        events = []
        for i, a in enumerate(arguments):
            verdict = verdicts[i]
            payload = SheetArgumentRecorded(
                argument_id=project.ids.new("arg"),
                sheet_id=sheet_id,
                stance=a.stance,
                work_id=verdict.item.work_id,
                anchor=a.anchor.strip(),
                quote=a.quote,
                conversion_id=str(verdict.conversion_id),
                markdown_hash=str(verdict.markdown_hash),
                claim=a.claim.strip(),
                claim_row_key=a.claim_row_key or None,
                strength=a.strength,
            )
            recorded.append(payload)
            events.append(
                project.events.make(
                    "sheet.argument_recorded",
                    payload,
                    actor,
                    refs=(payload.argument_id, sheet_id),
                    input_blob=blob,
                )
            )
        project.record(events)
    return recorded


def _loads(raw: str) -> dict[str, Any]:
    import json

    value = json.loads(raw)
    assert isinstance(value, dict)
    return value


def _claim_keys(project: Project, work_id: str) -> set[str]:
    version = dict(listed_miner_versions(project)).get(CLAIMS_MINER)
    if version is None:
        return set()
    rows, _ = load_miner_work_rows(project, CLAIMS_MINER, version, [work_id])
    return {r.row_key for r in rows.get(work_id, [])}


def close_section(
    project: Project, actor: Actor, sheet_id: str, section: str
) -> SheetSectionClosed:
    """Close a section of a sheet: `against` once, then `for` once. Refused (nothing written) for
    a non-agent actor, an unknown sheet or section, a section already closed, and `for` before
    `against` is closed."""
    _require_agent(actor)
    if section not in get_args(Section):
        raise _issue("section", f"{section}: must be against or for")
    payload = SheetSectionClosed(sheet_id=sheet_id, section=section)
    with project.index.exclusive():
        project.index.sync()
        row = _sheet_row(project, sheet_id)
        if row is None:
            raise _issue("sheet_id", f"{sheet_id}: no such sheet")
        if section == "against" and row["against_closed"]:
            raise _issue("section", "the section against is already closed")
        if section == "for" and not row["against_closed"]:
            raise _issue("section", "close the section against first")
        if section == "for" and row["for_closed"]:
            raise _issue("section", "the section for is already closed")
        blob = project.blobs.put_json({"sheet_id": sheet_id, "closed": section})
        project.record(
            [
                project.events.make(
                    "sheet.section_closed", payload, actor, refs=(sheet_id,), input_blob=blob
                )
            ]
        )
    return payload


def rate_argument(
    project: Project, actor: Actor, argument_id: str, rating: str, note: str = ""
) -> SheetArgumentRated:
    """The researcher's rating of one folded argument (sound, weak or wrong); the latest rating
    stands. Refused for anyone but a human."""
    if actor.kind != "human":
        raise _issue("actor", "a rating is the researcher's act")
    if rating not in get_args(Rating):
        raise _issue("rating", f"{rating}: must be sound, weak or wrong")
    if len(note) > NOTE_MAX:
        raise _issue("note", f"a note has at most {NOTE_MAX} characters")
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT sheet_id FROM sheet_arguments WHERE argument_id = :a"),
            {"a": argument_id},
        ).first()
    if found is None:
        raise _issue("argument_id", f"{argument_id}: no such argument")
    payload = SheetArgumentRated(
        argument_id=argument_id,
        sheet_id=str(found[0]),
        rating=rating,
        note=note,
    )
    with project.index.exclusive():
        project.record(
            [project.events.make("sheet.argument_rated", payload, actor, refs=(argument_id,))]
        )
    return payload


def list_sheets(project: Project) -> list[SheetInfo]:
    """Every sheet, oldest first."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT s.*, (SELECT COUNT(*) FROM sheet_arguments a "
                    "WHERE a.sheet_id = s.sheet_id) AS n FROM sheets s ORDER BY s.event_id"
                )
            )
            .mappings()
            .all()
        )
    return [_info(dict(r), int(r["n"])) for r in rows]


def _info(row: dict[str, Any], arguments: int) -> SheetInfo:
    return SheetInfo(
        sheet_id=row["sheet_id"],
        hypothesis=row["hypothesis"],
        mode=row["mode"],
        selection_digest=row["selection_digest"],
        candidates_digest=row["candidates_digest"],
        against_closed=bool(row["against_closed"]),
        for_closed=bool(row["for_closed"]),
        supersedes=row["supersedes"],
        arguments=arguments,
        actor=row["actor"],
        session=row["session"],
        ts=row["ts"],
    )


def view_sheet(project: Project, sheet_id: str) -> SheetView:
    """One sheet with its arguments and its computed coverage. Read-only."""
    if not _matches(SHEET_ID_RE, sheet_id):
        raise _issue("sheet_id", f"{sheet_id}: not a sheet id")
    project.index.sync()
    row = _sheet_row(project, sheet_id)
    if row is None:
        raise _issue("sheet_id", f"{sheet_id}: no such sheet")
    with project.index.connect() as conn:
        found = (
            conn.execute(
                text(
                    "SELECT a.*, r.rating AS rating, r.note AS rating_note FROM sheet_arguments a "
                    "LEFT JOIN sheet_ratings r ON r.argument_id = a.argument_id "
                    "WHERE a.sheet_id = :s ORDER BY a.event_id"
                ),
                {"s": sheet_id},
            )
            .mappings()
            .all()
        )
        cands = (
            conn.execute(
                text("SELECT * FROM sheet_candidates WHERE sheet_id = :s ORDER BY work_id"),
                {"s": sheet_id},
            )
            .mappings()
            .all()
        )
    arguments = tuple(
        ArgumentView(
            argument_id=a["argument_id"],
            stance=a["stance"],
            work_id=a["work_id"],
            anchor=a["anchor"],
            quote=a["quote"],
            claim=a["claim"],
            claim_row_key=a["claim_row_key"],
            strength=a["strength"],
            conversion_id=a["conversion_id"],
            markdown_hash=a["markdown_hash"],
            actor=a["actor"],
            model=a["model"],
            rating=a["rating"],
            rating_note=a["rating_note"],
        )
        for a in found
    )
    argued = {a.work_id for a in arguments}
    sources: Counter[str] = Counter()
    for c in cands:
        sources.update({s for s in str(c["sources"]).split(",") if s})
    coverage = SheetCoverage(
        total=len(cands),
        by_tier={t: sum(1 for c in cands if c["tier"] == t) for t in (1, 2, 3)},
        by_source=dict(sorted(sources.items())),
        over_cap=sum(1 for c in cands if c["over_cap"]),
        arguments={s: sum(1 for a in arguments if a.stance == s) for s in ("against", "for")},
        works_argued={
            s: len({a.work_id for a in arguments if a.stance == s}) for s in ("against", "for")
        },
        by_strength={s: sum(1 for a in arguments if a.strength == s) for s in get_args(Strength)},
        ratings={r: sum(1 for a in arguments if a.rating == r) for r in get_args(Rating)},
        unrated=sum(1 for a in arguments if a.rating is None),
        tier1_unargued=tuple(
            c["work_id"] for c in cands if c["tier"] == 1 and c["work_id"] not in argued
        ),
        works_without_claims_source=sum(
            1 for c in cands if "claims" not in str(c["sources"]).split(",")
        ),
    )
    return SheetView(
        _info(row, len(arguments)), arguments, coverage, selection=_loads(row["selection"])
    )


def _matches(pattern: str, value: str) -> bool:
    import re

    return re.fullmatch(pattern, value) is not None


_ = ARGUMENT_ID_RE  # exported pattern kept for callers that validate ids
