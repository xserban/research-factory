"""Finders: numeric conflicts, claim contradictions and gaps (slice 6, plan H-B).

Computed candidates for a reader to weigh, never conclusions (decision 68). Invariants:
- Builders are read-only and deterministic. Their outputs carry ids, counts, canonical values
  and stored quotes only, never document text beyond a stored quote.
- A numeric conflict is a pair of independent rows of one normalised method and variant in one
  comparability group, from different works, whose values differ by more than the tolerance
  against the larger magnitude. A copied row is never independent, so it never conflicts with the
  row it copies. Nothing is compared across groups.
- A claim contradiction is proposed by an agent from two live refs of different works and decided
  only by a human, never from the session that proposed it; until then it is `inferred`. It
  never alters the evidence report.
- Conflicts are derived group by group from the evidence report's `method_conflicts`, in the order
  `(group_id, method, row_a, row_b)`.
"""

from __future__ import annotations

import hashlib
import itertools
from collections import Counter
from collections.abc import Collection, Iterator, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.extraction.numbers import normalise_text, parse_printed
from factory.model.base import StrictModel
from factory.model.cards import PropertyKind
from factory.model.findings import (
    MAX_RATIONALE,
    ContradictionDecided,
    ContradictionInput,
    ContradictionProposed,
)
from factory.packs import NON_COMPARABLE_KEYS
from factory.services.cards import effective_card_props, property_family
from factory.services.context import Project
from factory.services.contributions import contribution_item
from factory.services.evidence_report import EvidenceRow, evidence_report
from factory.services.extraction import require_schema
from factory.services.extraction_agreement import final_rows, key_value
from factory.services.matching import subject_works
from factory.services.properties import resolve_property
from factory.services.protocol import current_protocol
from factory.services.references import included_works

CONFLICT_RELATIVE_TOLERANCE = Decimal("0.01")
"""Relative tolerance against the larger magnitude (ruling 4); `hypothesis_plan.conflict_tolerance`
overrides it once plan H-C adds that section."""
LIMIT_MAX = 500
_PLACES = Decimal("0.0001")


class ConflictPair(StrictModel):
    group_id: str
    method: str
    variant: str | None
    row_a: str
    row_b: str
    work_a: str
    work_b: str
    value_a: str
    value_b: str
    relative_difference: str
    differs_in: list[str]
    trace_ids: tuple[str, str]


class ConflictPage(StrictModel):
    conflicts: list[ConflictPair]
    groups_scanned: int
    next_after: str | None


def _refuse(field_name: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, reason)])


def _number(row: EvidenceRow) -> Decimal | None:
    cell = row.value
    if isinstance(cell.value, bool):
        return None
    try:
        d = Decimal(cell.canonical) if cell.canonical is not None else parse_printed(cell.value)
    except InvalidOperation:
        return None
    return d if d is not None and d.is_finite() else None


def _differs(a: EvidenceRow, b: EvidenceRow) -> list[str]:
    keys = set(a.regime) | set(b.regime)
    return sorted(k for k in keys if a.regime.get(k) != b.regime.get(k))


def _cursor(pair: ConflictPair) -> str:
    return f"{pair.group_id}:{pair.method}:{pair.row_a}:{pair.row_b}"


def _cursor_key(after: str) -> tuple[str, str, str, str]:
    head, _, rest = after.partition(":")
    parts = rest.rsplit(":", 2)
    if not head or len(parts) != 3:
        raise _refuse("after", "malformed")
    return head, parts[0], parts[1], parts[2]


def find_conflicts(
    project: Project,
    *,
    group_id: str | None = None,
    limit: int = 50,
    after: str | None = None,
) -> ConflictPage:
    """Numeric conflicts in the evidence report, one page after the cursor `after`.

    `groups_scanned` counts the groups with a method conflict that the call examined. Refused,
    with nothing written: a `limit` outside 1..500, a malformed cursor."""
    if not 1 <= limit <= LIMIT_MAX:
        raise _refuse("limit", f"between 1 and {LIMIT_MAX}")
    start = None if after is None else _cursor_key(after)
    report = agent_evidence(evidence_report(project))
    found: list[ConflictPair] = []
    scanned = 0
    for group in sorted(report.groups, key=lambda g: g.group_id):
        if group_id is not None and group.group_id != group_id:
            continue
        if not group.method_conflicts:
            continue
        scanned += 1
        by_key = {(r.row_key, r.work_id): r for r in group.rows if r.independent}
        for conflict in group.method_conflicts:
            wanted = set(conflict.rows)
            members = [r for r in by_key.values() if r.row_key in wanted]
            for a, b in itertools.combinations(sorted(members, key=lambda r: r.row_key), 2):
                pair = _pair(group.group_id, conflict.method, conflict.variant, a, b)
                if pair is not None:
                    found.append(pair)
    found.sort(key=lambda p: (p.group_id, p.method, p.row_a, p.row_b))
    if start is not None:
        found = [p for p in found if (p.group_id, p.method, p.row_a, p.row_b) > start]
    window = found[:limit]
    more = len(found) > limit
    return ConflictPage(
        conflicts=window,
        groups_scanned=scanned,
        next_after=_cursor(window[-1]) if window and more else None,
    )


def _pair(
    gid: str, method: str, variant: str | None, a: EvidenceRow, b: EvidenceRow
) -> ConflictPair | None:
    if a.work_id == b.work_id:
        return None
    if normalise_text(a.value.unit or "") != normalise_text(b.value.unit or ""):
        return None
    na, nb = _number(a), _number(b)
    if na is None or nb is None:
        return None
    larger = max(abs(na), abs(nb))
    if larger == 0:
        return None
    relative = abs(na - nb) / larger
    if relative <= CONFLICT_RELATIVE_TOLERANCE:
        return None
    return ConflictPair(
        group_id=gid,
        method=method,
        variant=variant,
        row_a=a.row_key,
        row_b=b.row_key,
        work_a=a.work_id,
        work_b=b.work_id,
        value_a=format(na.normalize(), "f"),
        value_b=format(nb.normalize(), "f"),
        relative_difference=str(relative.quantize(_PLACES, rounding=ROUND_HALF_UP)),
        differs_in=_differs(a, b),
        trace_ids=(a.value.trace_id, b.value.trace_id),
    )


# --- Claim contradictions ---

ContradictionState = Literal["inferred", "confirmed", "rejected", "stale"]
PAGE = 500


class ContradictionView(StrictModel):
    contradiction_id: str
    ref_a: str
    ref_b: str
    work_a: str
    work_b: str
    state: ContradictionState
    event_id: str


class _Ref(StrictModel):
    work_id: str
    quote: str
    live: bool


def _lookup(project: Project, ref: str) -> _Ref | None:
    """The work, stored quote and liveness of a claim or contribution item; None when `ref` names
    no such row or the row carries no quote."""
    if ref.startswith("clm_"):
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT work_id, quote, superseded_by FROM extraction_claims "
                    "WHERE claim_id = :c"
                ),
                {"c": ref},
            ).first()
        if row is None:
            return None
        return _Ref(work_id=str(row[0]), quote=str(row[1]), live=row[2] is None)
    item = contribution_item(project, ref)
    if item is None or not item.quote:
        return None
    return _Ref(work_id=item.work_id, quote=item.quote, live=item.live)


def propose_contradiction(
    project: Project, actor: Actor, item: ContradictionInput
) -> tuple[str, bool]:
    """Propose that two refs contradict each other; returns (contradiction id, written). The
    same unordered pair is idempotent: the first proposal's id is returned and nothing written.

    Refused, with nothing written: an actor that is not an agent or a human (`actor`); the same
    ref twice (`ref_b`: `same-ref`); a ref that names no claim or quoted contribution item
    (`ref_a` / `ref_b`: `ref-unknown`); a ref a later row supersedes (`ref_a` / `ref_b`:
    `ref-not-live`); two refs of one work (`ref_b`: `same-work`)."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human proposes a contradiction")
    if item.ref_a == item.ref_b:
        raise _refuse("ref_b", "same-ref")
    ref_a, ref_b = sorted((item.ref_a, item.ref_b))
    with project.index.exclusive():
        project.index.sync()
        found = {r: _lookup(project, r) for r in (item.ref_a, item.ref_b)}
        named = (("ref_a", item.ref_a), ("ref_b", item.ref_b))
        issues = [ValidationIssue(n, "ref-unknown") for n, r in named if found[r] is None]
        if issues:
            raise FactoryValidationError(issues)
        known = {r: v for r, v in found.items() if v is not None}
        a, b = known[ref_a], known[ref_b]
        issues = [ValidationIssue(n, "ref-not-live") for n, r in named if not known[r].live]
        if not issues and a.work_id == b.work_id:
            issues = [ValidationIssue("ref_b", "same-work")]
        if issues:
            raise FactoryValidationError(issues)
        with project.index.connect() as conn:
            existing = conn.execute(
                text("SELECT contradiction_id FROM contradictions WHERE ref_a = :a AND ref_b = :b"),
                {"a": ref_a, "b": ref_b},
            ).first()
        if existing is not None:
            return str(existing[0]), False
        contradiction_id = project.ids.new("ctr")
        payload = ContradictionProposed(
            contradiction_id=contradiction_id,
            ref_a=ref_a,
            ref_b=ref_b,
            work_a=a.work_id,
            work_b=b.work_id,
            quote_a=a.quote,
            quote_b=b.quote,
            note=item.note,
        )
        input_blob = (
            project.blobs.put_json(item.model_dump(mode="json")) if actor.kind == "agent" else None
        )
        project.record(
            [
                project.events.make(
                    "contradiction.proposed",
                    payload,
                    actor,
                    refs=[contradiction_id, ref_a, ref_b],
                    input_blob=input_blob,
                )
            ]
        )
    return contradiction_id, True


def decide_contradiction(
    project: Project,
    actor: Actor,
    contradiction_id: str,
    decision: Literal["confirm", "reject"],
    rationale: str,
) -> str:
    """Record a human decision on a contradiction and return the event id. Refused, with nothing
    written: a non-human actor (`actor`: `human-only`); the session that proposed it (`actor`:
    `proposer-session`); an unknown id (`contradiction_id`); a blank or long rationale."""
    if actor.kind != "human":  # gate hypotheses.contradiction_confirm (slice-M gate, floor human)
        raise _refuse("actor", "human-only")
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT e.session FROM contradictions c JOIN events e ON e.id = c.event_id "
                    "WHERE c.contradiction_id = :c"
                ),
                {"c": contradiction_id},
            ).first()
        issues: list[ValidationIssue] = []
        if row is None:
            issues.append(ValidationIssue("contradiction_id", "unknown"))
        elif str(row[0]) == actor.session:
            issues.append(ValidationIssue("actor", "proposer-session"))
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state the reason for the decision"))
        elif len(rationale) > MAX_RATIONALE:
            issues.append(ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "contradiction.decided",
            ContradictionDecided(
                contradiction_id=contradiction_id, decision=decision, rationale=rationale
            ),
            actor,
            refs=[contradiction_id],
        )
        project.record([event])
        return event.id


def _state(project: Project, row: Any) -> ContradictionState:
    if row.decision == "reject":
        return "rejected"
    for ref in (row.ref_a, row.ref_b):
        found = _lookup(project, str(ref))
        if found is None or not found.live:
            return "stale"
    return "confirmed" if row.decision == "confirm" else "inferred"


def list_contradictions(
    project: Project,
    *,
    states: Collection[str] = ("confirmed",),
    limit: int = PAGE,
    after: str | None = None,
) -> list[ContradictionView]:
    """Contradictions by id whose state is in `states`, one page after the cursor `after`.
    `inferred`: proposed and undecided; `confirmed` / `rejected`: the latest human decision;
    `stale`: not rejected and a ref is no longer live. Reads page in SQL."""
    project.index.sync()
    out: list[ContradictionView] = []
    cursor = after or ""
    while True:
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT contradiction_id, ref_a, ref_b, work_a, work_b, decision, event_id "
                    "FROM contradictions WHERE contradiction_id > :after "
                    "ORDER BY contradiction_id LIMIT :n"
                ),
                {"after": cursor, "n": PAGE},
            ).all()
        for row in rows:
            cursor = str(row.contradiction_id)
            state = _state(project, row)
            if state in states:
                out.append(
                    ContradictionView(
                        contradiction_id=cursor,
                        ref_a=str(row.ref_a),
                        ref_b=str(row.ref_b),
                        work_a=str(row.work_a),
                        work_b=str(row.work_b),
                        state=state,
                        event_id=str(row.event_id),
                    )
                )
                if len(out) == limit:
                    return out
        if len(rows) < PAGE:
            return out


# --- Gaps ---

GAP_MAX_CELLS = 10_000
GAP_BUILDER_VERSION = "1"
GAP_STATEMENT = (
    "Not found in this corpus (protocol {protocol}, {works} included works, last search "
    "{search}); absence here is not absence in the literature."
)
GapAxis = str


class GapCell(StrictModel):
    row: str
    column: str
    count: int


class CorpusDefinition(StrictModel):
    protocol_id: str | None
    last_search: str | None
    included_works: int


class GapReport(StrictModel):
    rows_axis: str
    columns_axis: str
    filters: dict[str, str]
    cells: int
    empty: list[GapCell]
    filled: int
    corpus: CorpusDefinition
    statement: str
    gap_key: str


def _corpus(project: Project) -> CorpusDefinition:
    protocol = current_protocol(project)
    with project.index.connect() as conn:
        last = conn.execute(
            text("SELECT max(coalesce(finished_at, started_at)) FROM runs")
        ).scalar()
    return CorpusDefinition(
        protocol_id=None if protocol is None else protocol.protocol_id,
        last_search=None if last is None else str(last)[:10],
        included_works=len(included_works(project)),
    )


def _grid_refusal(size: int) -> FactoryValidationError:
    return _refuse("filters", f"grid-too-large ({size} cells, limit {GAP_MAX_CELLS}); add a filter")


def _evidence_filter_sql(filters: Mapping[str, str]) -> tuple[str, dict[str, str]]:
    """An `AND EXISTS ...` clause per filter, on the raw case-folded stored value (an upper-bound
    approximation of the normalised comparison the aggregation makes)."""
    sql, params = "", {}
    for i, (name, value) in enumerate(sorted(filters.items())):
        sql += (
            " AND EXISTS (SELECT 1 FROM extraction_fields g WHERE g.extraction_id = "
            f"r.extraction_id AND g.field = :fk{i} AND lower(g.value) = lower(:fv{i}))"
        )
        params[f"fk{i}"], params[f"fv{i}"] = name, value
    return sql, params


def _distinct_evidence(project: Project, field_name: str, filters: Mapping[str, str]) -> int:
    clause, params = _evidence_filter_sql(filters)
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(DISTINCT lower(f.value)) FROM extraction_fields f "
                    "JOIN extraction_rows r ON r.extraction_id = f.extraction_id "
                    "WHERE r.scope = 'evidence' AND r.superseded_by IS NULL AND f.field = :field"
                    + clause
                ),
                {"field": field_name, **params},
            ).scalar()
            or 0
        )


def _count_method_cards(project: Project) -> int:
    with project.index.connect() as conn:
        return int(
            conn.execute(text("SELECT COUNT(*) FROM cards WHERE kind = 'method'")).scalar() or 0
        )


def _distinct_values(project: Project, keys: Collection[str]) -> int:
    marks = ", ".join(f":k{i}" for i in range(len(keys)))
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(DISTINCT value_norm) FROM card_props "
                    f"WHERE property_key IN ({marks})"
                ),
                {f"k{i}": k for i, k in enumerate(sorted(keys))},
            ).scalar()
            or 0
        )


def _method_cards(project: Project) -> Iterator[str]:
    after = ""
    while True:
        with project.index.connect() as conn:
            ids = [
                str(r[0])
                for r in conn.execute(
                    text(
                        "SELECT card_id FROM cards WHERE kind = 'method' AND card_id > :a "
                        "ORDER BY card_id LIMIT :n"
                    ),
                    {"a": after, "n": PAGE},
                )
            ]
        yield from ids
        if len(ids) < PAGE:
            return
        after = ids[-1]


def find_gaps(
    project: Project,
    *,
    rows_axis: GapAxis,
    columns_axis: str,
    filters: Mapping[str, str] | None = None,
) -> GapReport:
    """Empty cells of a method x condition grid: a computed candidate, never a conclusion.

    Rows are normalised method names of the final rows (`method`) or method cards (`card`).
    Columns are one declared comparability key of the evidence schema, or (for cards) a property
    key. A cell counts final independent rows (a copied row fills nothing), or the effective
    stated or confirmed assertions of a card on a value. The grid size is bounded by
    `GAP_MAX_CELLS` and checked, from SQL distinct counts, before any row is read. Refused, with
    nothing written: an axis that is not one of these (`rows_axis`, `columns_axis`); a filter on
    a key that is not a declared comparability key, or with a property column (`filters`); a
    grid above the bound (`filters`: `grid-too-large`)."""
    wanted = dict(filters or {})
    if rows_axis not in ("method", "card"):
        raise _refuse("rows_axis", "unknown-axis")
    if columns_axis.startswith("pr:"):
        return _card_gaps(project, rows_axis, columns_axis, wanted)
    protocol, schema, pack = require_schema(project)
    keys = [
        k
        for k in (schema.comparability_keys or pack.default_comparability_keys)
        if k not in NON_COMPARABLE_KEYS
    ]
    if columns_axis not in keys:
        raise _refuse("columns_axis", "unknown-axis")
    for name in wanted:
        if name not in keys:
            raise _refuse("filters", f"{name}: not-a-comparability-key")
    cards = _count_method_cards(project) if rows_axis == "card" else None
    row_count = cards if cards is not None else _distinct_evidence(project, "method_name", wanted)
    size = row_count * _distinct_evidence(project, columns_axis, wanted)
    if size > GAP_MAX_CELLS:
        raise _grid_refusal(size)
    column_def = pack.field(columns_axis)
    owner: dict[str, list[str]] = {}
    if rows_axis == "card":
        for card_id, subject in _method_card_subjects(project):
            for work in subject_works(project, subject):
                owner.setdefault(work, []).append(card_id)
    universe_rows: set[str] = set()
    universe_cols: set[str] = set()
    counts: Counter[tuple[str, str]] = Counter()
    for row in final_rows(project):
        if columns_axis not in row.fields or (
            rows_axis == "method" and "method_name" not in row.fields
        ):
            continue
        if any(
            name not in row.fields
            or normalise_text(key_value(pack.field(name), row.fields[name]))
            != normalise_text(value)
            for name, value in wanted.items()
        ):
            continue
        column = key_value(column_def, row.fields[columns_axis])
        names = (
            [normalise_text(str(row.fields["method_name"].value))]
            if rows_axis == "method"
            else owner.get(row.work_id, [])
        )
        universe_cols.add(column)
        for name in names:
            universe_rows.add(name)
            if row.independent:
                counts[(name, column)] += 1
    if rows_axis == "card":
        universe_rows = {c for c, _ in _method_card_subjects(project)}
    return _report(
        project,
        protocol.protocol_id,
        rows_axis,
        columns_axis,
        wanted,
        sorted(universe_rows),
        sorted(universe_cols),
        counts,
    )


def _method_card_subjects(project: Project) -> Iterator[tuple[str, str]]:
    for card_id in _method_cards(project):
        with project.index.connect() as conn:
            row = conn.execute(
                text("SELECT subject FROM cards WHERE card_id = :c"), {"c": card_id}
            ).first()
        assert row is not None
        yield card_id, str(row[0])


def _card_gaps(project: Project, rows_axis: str, key: str, filters: Mapping[str, str]) -> GapReport:
    defn = resolve_property(project, key)
    if rows_axis != "card" or defn is None:
        raise _refuse("columns_axis", "unknown-axis")
    if filters:
        raise _refuse("filters", "not-applicable-to-a-property-column")
    cards = _count_method_cards(project)
    listed = (
        list(defn.allowed)
        if defn.allowed
        else (["false", "true"] if defn.kind is PropertyKind.BOOL else None)
    )
    values = (
        len(listed)
        if listed is not None
        else _distinct_values(project, property_family(project, [key]))
    )
    if cards * values > GAP_MAX_CELLS:
        raise _grid_refusal(cards * values)
    counts: Counter[tuple[str, str]] = Counter()
    seen: set[str] = set()
    for prop in effective_card_props(project, [key], ["stated", "confirmed"]):
        if prop.card_kind == "method":
            counts[(prop.card_id, prop.value_norm)] += 1
            seen.add(prop.value_norm)
    columns = sorted(listed if listed is not None else seen)
    protocol = current_protocol(project)
    return _report(
        project,
        None if protocol is None else protocol.protocol_id,
        rows_axis,
        key,
        {},
        sorted(c for c, _ in _method_card_subjects(project)),
        columns,
        counts,
    )


def _report(
    project: Project,
    protocol_id: str | None,
    rows_axis: str,
    columns_axis: str,
    filters: Mapping[str, str],
    rows: Sequence[str],
    columns: Sequence[str],
    counts: Mapping[tuple[str, str], int],
) -> GapReport:
    size = len(rows) * len(columns)
    if size > GAP_MAX_CELLS:
        raise _grid_refusal(size)
    empty = [
        GapCell(row=r, column=c, count=0) for r in rows for c in columns if (r, c) not in counts
    ]
    corpus = _corpus(project)
    body: JsonValue = {
        "builder": GAP_BUILDER_VERSION,
        "axes": [rows_axis, columns_axis],
        "filters": dict(sorted(filters.items())),
        "protocol": protocol_id,
        "last_search": corpus.last_search,
        "included": corpus.included_works,
        "empty": [[c.row, c.column] for c in empty],
        "filled": size - len(empty),
    }
    return GapReport(
        rows_axis=rows_axis,
        columns_axis=columns_axis,
        filters=dict(filters),
        cells=size,
        empty=empty,
        filled=size - len(empty),
        corpus=corpus.model_copy(update={"protocol_id": protocol_id}),
        statement=GAP_STATEMENT.format(
            protocol=protocol_id or "none",
            works=corpus.included_works,
            search=corpus.last_search or "none",
        ),
        gap_key=hashlib.sha256(canonical_json(body)).hexdigest()[:16],
    )
