"""Agreement of the two extraction passes, human resolution, final and grouped rows (R-46).

Rows of the two passes align on `row_key` (ruling 10). For an aligned pair each declared field is
compared, never its anchor, quote or cell: text by the pack's normaliser, numbers by canonical
value and (except for count fields, whose canonical value is already scaled) unit, booleans
equal, and `reported_in` and `reproduced` equal. A field in one row only is `missing`; a row in
one pass only, or a row key that a pass holds twice, is a `row` disagreement and no row is picked.

Invariants:
- Only live rows enter: superseded rows, stale rows (`stale_extractions`) and rows of works no
  longer in `extraction_population` never do. A work enters only once its units are current:
  pass A, and pass B too for a work of the dual sample (recorded seed and current fraction).
- Agreement counts are computed from the rows, never supplied; `agreement_overall` and
  `extraction_agreement` share one computation.
- A disagreement is resolved only by a human's `extraction.resolved` (choice `a`, `b` or
  `neither`; no value is typed), recorded after every row it covers (by event ID); a resolution
  older than one of those rows no longer applies. An unresolved disagreement keeps its row out of
  the final rows. A field resolution and a whole-row `a`/`b` both cover a field; the later wins.
  A whole-row `neither` drops the row.
- A final field is effectively `cited` when the agent declared it cited or the platform found a
  citation marker (ruling 8); a row is independent when its `value` field is effectively own.
- Group keys are the schema's comparability keys (the pack's defaults when none are declared), in
  that order, never `NON_COMPARABLE_KEYS` (decision 42 item 3, acceptance 12a).

Everything here is read-only except `resolve_extraction`, which writes one event or nothing.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.extraction.numbers import normalise_for, normalise_text
from factory.index.extraction import WHOLE_ROW
from factory.model.base import StrictModel
from factory.model.extraction import (
    ExtractionPassJoined,
    ExtractionResolved,
    ReportedIn,
    StoredField,
)
from factory.model.protocol import ExtractionSchema
from factory.model.screening import Channel, PassLabel
from factory.packs import NON_COMPARABLE_KEYS, FieldDef, FieldKind, Pack, UnitFamily
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ExtractionRow,
    PassConfig,
    extraction_population,
    in_dual_sample,
    is_extraction_session,
    live_rows,
    pass_config,
    require_schema,
    stale_extractions,
    unit_states,
)
from factory.services.extraction_verify import VALUE_FIELD

__all__ = [
    "NON_COMPARABLE_KEYS",
    "AgreementOverall",
    "DroppedItem",
    "ExtractionAgreement",
    "ExtractionPassView",
    "FieldDisagreement",
    "FieldView",
    "FinalField",
    "FinalRow",
    "GroupKey",
    "GroupRate",
    "Grouped",
    "IndependenceCounts",
    "agreement_overall",
    "extraction_agreement",
    "field_disagreements",
    "final_field",
    "final_rows",
    "group_rows",
    "grouped_rows",
    "independence_counts",
    "key_value",
    "resolve_extraction",
]


Choice = Literal["a", "b", "neither"]


# --- Views ---


class FieldView(StrictModel):
    """One pass's field as a disagreement shows it."""

    value: str | bool
    unit: str | None
    canonical: str | None
    anchor: str | None
    cell: str | None
    quote: str | None
    reported_in: ReportedIn
    reproduced: bool
    extraction_id: str


class FieldDisagreement(StrictModel):
    """A field (or, `field` None, a whole row) on which the passes differ. For a `row`
    disagreement `a` and `b` show the `value` field of the pass's row, or None when the pass has
    no row there or holds the row key twice."""

    work_id: str
    row_key: str
    field: str | None
    kind: Literal["value", "missing", "row"]
    a: FieldView | None
    b: FieldView | None


class GroupRate(StrictModel):
    """Agreement in one pack group over the compared field values of aligned rows."""

    group: str
    compared: int
    agreed: int
    rate: float | None


class ExtractionPassView(StrictModel):
    """What a pass recorded when it opened, and who served it."""

    pass_label: PassLabel
    seed: int
    field_order: str
    sessions: list[str]
    models: list[str]


class DroppedItem(StrictModel):
    """A field, or a whole row (`field` None), that a human's `neither` dropped."""

    work_id: str
    row_key: str
    field: str | None


class ExtractionAgreement(StrictModel):
    passes: list[ExtractionPassView]
    dual_works: int
    rows_aligned: int
    rows_unmatched: int
    rates: list[GroupRate]
    overall: float | None
    disagreements: list[FieldDisagreement]
    """Unresolved disagreements only."""
    resolved: int
    dropped: list[DroppedItem]
    single_extraction: list[str]


class AgreementOverall(StrictModel):
    """`overall` = agreed / compared field values of the `rows_aligned` aligned rows."""

    overall: float | None
    dual: int
    single: int
    rows_aligned: int
    rows_unmatched: int


class FinalField(StrictModel):
    """A final field: the verified field of the chosen pass, `reported_in` effective."""

    value: str | bool
    unit: str | None
    canonical: str | None
    anchor: str | None
    cell: str | None
    quote: str | None
    reported_in: ReportedIn
    copy_marker: bool
    reproduced: bool
    cited_work: str | None
    extraction_id: str


class FinalRow(StrictModel):
    work_id: str
    document_id: str
    conversion_id: str
    row_key: str
    status: Literal["agreed", "resolved", "single"]
    fields: dict[str, FinalField]
    independent: bool


GroupKey = tuple[tuple[str, str], ...]


class Grouped(StrictModel):
    groups: dict[GroupKey, list[FinalRow]]
    ungrouped: list[FinalRow]
    """Rows lacking a comparability key."""
    unresolved: list[FieldDisagreement]


class IndependenceCounts(StrictModel):
    independent: int
    copied: int


# --- Pure comparison ---


def _view(f: StoredField, extraction_id: str) -> FieldView:
    return FieldView(
        value=f.value if isinstance(f.value, bool) else str(f.value),
        unit=f.unit,
        canonical=f.canonical,
        anchor=f.anchor,
        cell=f.cell,
        quote=f.quote,
        reported_in=f.reported_in,
        reproduced=f.reproduced,
        extraction_id=extraction_id,
    )


def _normalised(definition: FieldDef | None, f: StoredField) -> tuple[str, str]:
    """The (value, unit) a field is compared and grouped by. Never the raw text of a number."""
    unit = normalise_text(f.unit or "")
    if definition is None:
        return normalise_text(str(f.value)), unit
    if definition.kind in (FieldKind.NUMBER, FieldKind.INTEGER) and f.canonical is not None:
        if definition.unit_family is UnitFamily.COUNT:
            return f.canonical, ""  # already scaled by its unit
        return f.canonical, unit
    if definition.kind is FieldKind.TEXT:
        return normalise_for(definition, str(f.value)), unit
    return normalise_text(str(f.value)), unit


def _same(definition: FieldDef | None, fa: StoredField, fb: StoredField) -> bool:
    return (
        fa.reported_in is fb.reported_in
        and fa.reproduced == fb.reproduced
        and _normalised(definition, fa) == _normalised(definition, fb)
    )


def _compare(
    pack: Pack, fields: Sequence[str], a: ExtractionRow, b: ExtractionRow
) -> list[tuple[str, FieldDisagreement | None]]:
    """Each declared field present in either row, with its disagreement or None, in `fields`
    order."""
    out: list[tuple[str, FieldDisagreement | None]] = []
    for name in fields:
        fa, fb = a.fields.get(name), b.fields.get(name)
        if fa is None and fb is None:
            continue
        if fa is not None and fb is not None and _same(pack.field(name), fa, fb):
            out.append((name, None))
            continue
        out.append(
            (
                name,
                FieldDisagreement(
                    work_id=a.work_id,
                    row_key=a.row_key,
                    field=name,
                    kind="value" if fa is not None and fb is not None else "missing",
                    a=None if fa is None else _view(fa, a.extraction_id),
                    b=None if fb is None else _view(fb, b.extraction_id),
                ),
            )
        )
    return out


def field_disagreements(
    pack: Pack, fields: Sequence[str], a: ExtractionRow, b: ExtractionRow
) -> list[FieldDisagreement]:
    """The disagreements of two aligned rows over the declared `fields`. Pure."""
    return [d for _, d in _compare(pack, fields, a, b) if d is not None]


def final_field(f: StoredField, extraction_id: str) -> FinalField:
    """The final form of a verified field: effectively cited when declared cited or when the
    platform found a citation marker (ruling 8)."""
    cited = f.reported_in is ReportedIn.CITED or f.copy_marker
    return FinalField(
        value=f.value if isinstance(f.value, bool) else str(f.value),
        unit=f.unit,
        canonical=f.canonical,
        anchor=f.anchor,
        cell=f.cell,
        quote=f.quote,
        reported_in=ReportedIn.CITED if cited else ReportedIn.OWN,
        copy_marker=f.copy_marker,
        reproduced=f.reproduced,
        cited_work=f.cited_work,
        extraction_id=extraction_id,
    )


# --- State ---


@dataclass(frozen=True)
class _Resolution:
    choice: Choice
    event_id: str


@dataclass
class _Pair:
    """One row key of one work: the live rows of each pass there and what the comparison and the
    resolutions make of it."""

    work_id: str
    row_key: str
    a: list[ExtractionRow]
    b: list[ExtractionRow]
    dual: bool
    compared: list[tuple[str, FieldDisagreement | None]] = field(default_factory=list)
    open: list[FieldDisagreement] = field(default_factory=list)
    resolved: int = 0
    dropped: list[DroppedItem] = field(default_factory=list)
    final: FinalRow | None = None
    row_dropped: bool = False
    """A human's `neither` on the whole row or on its `value` field drops the row."""

    @property
    def aligned(self) -> bool:
        return self.dual and len(self.a) == 1 and len(self.b) == 1

    @property
    def disagreements(self) -> list[FieldDisagreement]:
        if self.aligned:
            return [d for _, d in self.compared if d is not None]
        if not self.dual and len(self.a) == 1:
            return []
        return [
            FieldDisagreement(
                work_id=self.work_id,
                row_key=self.row_key,
                field=None,
                kind="row",
                a=_row_view(self.a),
                b=_row_view(self.b),
            )
        ]

    def side(self, choice: Choice) -> list[ExtractionRow]:
        return self.a if choice == "a" else self.b if choice == "b" else []


def _row_view(rows: list[ExtractionRow]) -> FieldView | None:
    if len(rows) != 1 or VALUE_FIELD not in rows[0].fields:
        return None
    return _view(rows[0].fields[VALUE_FIELD], rows[0].extraction_id)


@dataclass(frozen=True)
class _State:
    """The extraction state under the current protocol, read once.

    `known` is False until pass B has opened (the dual sample is unknown); `dual` and `single`
    are then empty and no work is final. `blocking` is True while a unit of the population is
    open, stale, or queued with a document to extract from."""

    schema: ExtractionSchema
    pack: Pack
    configs: dict[PassLabel, PassConfig | None]
    known: bool
    dual: frozenset[str]
    single: frozenset[str]
    blocking: bool
    pairs: list[_Pair]


def _load(project: Project) -> _State | None:
    """The state, or None without a ready protocol with a known schema and a full-text plan."""
    project.index.sync()
    try:
        _, schema, pack = require_schema(project)
        population = extraction_population(project)
    except FactoryValidationError:
        return None
    configs = {label: pass_config(project, label) for label in PassLabel}
    b_config = configs[PassLabel.B]
    known = configs[PassLabel.A] is not None and b_config is not None
    dual: frozenset[str] = frozenset()
    if b_config is not None:
        dual = frozenset(
            w for w in population if in_dual_sample(b_config.seed, w, schema.dual_extract_sample)
        )
    single = frozenset(population) - dual if b_config is not None else frozenset()
    states = unit_states(project)
    current = {(s.work_id, s.pass_label) for s in states if s.state == "current"}
    blocking = any(
        s.state in ("open", "stale")
        or (s.state == "queued" and default_conversion(project, s.work_id) is not None)
        for s in states
    )
    ready = (
        {w for w in dual if (w, PassLabel.A) in current and (w, PassLabel.B) in current}
        | {w for w in single if (w, PassLabel.A) in current}
        if known
        else set()
    )
    rows: dict[tuple[str, PassLabel, str], list[ExtractionRow]] = {}
    for row in _eligible_rows(project, set(population)):
        if row.work_id not in ready or (row.work_id in single and row.pass_label is PassLabel.B):
            continue
        rows.setdefault((row.work_id, row.pass_label, row.row_key), []).append(row)
    keys = sorted({(work, key) for work, _, key in rows})
    pairs = [
        _Pair(
            work_id=work,
            row_key=key,
            a=rows.get((work, PassLabel.A, key), []),
            b=rows.get((work, PassLabel.B, key), []),
            dual=work in dual,
        )
        for work, key in keys
    ]
    resolutions = _resolutions(project)
    for pair in pairs:
        if pair.aligned:
            pair.compared = _compare(pack, schema.fields, pair.a[0], pair.b[0])
        _settle(pair, schema, pack, resolutions)
    return _State(schema, pack, configs, known, dual, single, blocking, pairs)


def _eligible_rows(project: Project, population: set[str]) -> list[ExtractionRow]:
    """The rows agreement and final rows may use: live (not superseded), not stale, and of a
    work still in `extraction_population`. The one place these exclusions are made."""
    stale = stale_extractions(project)
    return [
        row
        for row in live_rows(project)
        if row.work_id in population and row.extraction_id not in stale
    ]


def _resolutions(project: Project) -> dict[tuple[str, str, str], _Resolution]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, row_key, field, choice, event_id FROM extraction_resolutions "
                "WHERE scope = 'evidence'"
            )
        ).all()
    out: dict[tuple[str, str, str], _Resolution] = {}
    for work, key, name, choice, event_id in rows:
        if choice in ("a", "b", "neither"):
            out[(str(work), str(key), str(name))] = _Resolution(choice, str(event_id))
    return out


def _settle(
    pair: _Pair,
    schema: ExtractionSchema,
    pack: Pack,
    resolutions: dict[tuple[str, str, str], _Resolution],
) -> None:
    """Apply the resolutions that still apply (recorded after every row of the pair) and build
    the final row when nothing stays unresolved. A `neither` on the whole row or on `value`
    drops the row. A row that would lack a pack-required field is never final: a resolved one
    keeps its disagreements open (the resolution refusals make this unreachable)."""
    newest = max((r.event_id for r in (*pair.a, *pair.b)), default="")

    def applicable(name: str) -> _Resolution | None:
        found = resolutions.get((pair.work_id, pair.row_key, name))
        return found if found is not None and found.event_id > newest else None

    def drop_row() -> None:
        pair.resolved = len(disagreements)
        pair.row_dropped = True
        pair.dropped.append(DroppedItem(work_id=pair.work_id, row_key=pair.row_key, field=None))

    disagreements = pair.disagreements
    if not disagreements:
        status: Literal["agreed", "single"] = "agreed" if pair.dual else "single"
        pair.final = _final(pair, pair.a[0], {}, status, schema, pack)
        return
    whole = applicable(WHOLE_ROW)
    if whole is not None and whole.choice == "neither":
        drop_row()
        return
    if not pair.aligned:  # a row disagreement: only a whole-row choice of a single row settles it
        chosen = None if whole is None else pair.side(whole.choice)
        final = (
            None
            if not chosen or len(chosen) != 1
            else _final(pair, chosen[0], {}, "resolved", schema, pack)
        )
        if final is None:
            pair.open = disagreements
            return
        pair.resolved = 1
        pair.final = final
        return
    choices: dict[str, Choice] = {}
    pending: list[FieldDisagreement] = []
    for d in disagreements:
        assert d.field is not None
        candidates = [r for r in (applicable(d.field), whole) if r is not None]
        if not candidates:
            pending.append(d)
            continue
        choices[d.field] = max(candidates, key=lambda r: r.event_id).choice
    if choices.get(VALUE_FIELD) == "neither":
        drop_row()
        return
    pair.open = pending
    if pending:
        pair.resolved = len(choices)
        return
    final = _final(pair, pair.a[0], choices, "resolved", schema, pack)
    if final is None:
        pair.open = disagreements
        return
    pair.resolved = len(choices)
    pair.final = final
    pair.dropped.extend(
        DroppedItem(work_id=pair.work_id, row_key=pair.row_key, field=name)
        for name, choice in choices.items()
        if choice == "neither"
    )


def _final(
    pair: _Pair,
    base: ExtractionRow,
    choices: dict[str, Choice],
    status: Literal["agreed", "resolved", "single"],
    schema: ExtractionSchema,
    pack: Pack,
) -> FinalRow | None:
    """The final row: each declared field of `base`, or of the pass a human chose for it. None
    when it would lack a field the pack requires."""
    fields: dict[str, FinalField] = {}
    for name in schema.fields:
        source = base
        choice = choices.get(name)
        if choice is not None:
            chosen = pair.side(choice)
            if not chosen:
                continue  # neither: dropped
            source = chosen[0]
        stored = source.fields.get(name)
        if stored is not None:
            fields[name] = final_field(stored, source.extraction_id)
    if any(name not in fields for name in pack.required):
        return None
    value = fields.get(VALUE_FIELD)
    return FinalRow(
        work_id=pair.work_id,
        document_id=base.document_id,
        conversion_id=base.conversion_id,
        row_key=pair.row_key,
        status=status,
        fields=fields,
        independent=value is not None and value.reported_in is ReportedIn.OWN,
    )


# --- Agreement ---


@dataclass(frozen=True)
class _Tally:
    rates: list[GroupRate]
    overall: float | None
    rows_aligned: int
    rows_unmatched: int


def _tally(state: _State) -> _Tally:
    """Per-group and overall agreement over the compared fields of aligned rows, and the row
    counts: aligned pairs, and row keys of dual works that do not align (one pass only, or a
    pass holding the key twice)."""
    groups: dict[str, list[int]] = {}
    for definition in state.pack.fields:
        if definition.name in state.schema.fields:
            groups.setdefault(definition.group, [0, 0])
    for pair in state.pairs:
        for name, disagreement in pair.compared:
            found = state.pack.field(name)
            counts = groups.setdefault(found.group if found else "other", [0, 0])
            counts[0] += 1
            counts[1] += disagreement is None
    rates = [
        GroupRate(group=g, compared=c, agreed=a, rate=a / c if c else None)
        for g, (c, a) in groups.items()
    ]
    compared = sum(r.compared for r in rates)
    agreed = sum(r.agreed for r in rates)
    return _Tally(
        rates=rates,
        overall=agreed / compared if compared else None,
        rows_aligned=sum(p.aligned for p in state.pairs),
        rows_unmatched=sum(p.dual and not p.aligned for p in state.pairs),
    )


def agreement_overall(project: Project) -> AgreementOverall:
    """Overall agreement, the dual and single work counts and the row counts. Read-only, needs
    no actor and never raises.

    `overall` = agreed / compared field values, where a compared field value is one declared
    field present in either row of an aligned pair (`rows_aligned` pairs of current, live,
    non-stale rows of dual works); unmatched rows (`rows_unmatched`) are not in the denominator.
    `overall` is None while a unit is open or stale, before both passes opened, or when nothing
    is compared. `dual` and `single` are 0 until pass B has opened. It does not check session or
    model independence; `extraction_agreement` does."""
    try:
        state = _load(project)
    except FactoryValidationError:
        state = None
    if state is None:
        return AgreementOverall(overall=None, dual=0, single=0, rows_aligned=0, rows_unmatched=0)
    tally = _tally(state)
    return AgreementOverall(
        overall=None if state.blocking or not state.known else tally.overall,
        dual=len(state.dual),
        single=len(state.single),
        rows_aligned=tally.rows_aligned,
        rows_unmatched=tally.rows_unmatched,
    )


def extraction_agreement(project: Project, actor: Actor) -> ExtractionAgreement:
    """The agreement of the two extraction passes, with the unresolved disagreements (both
    fields shown), the resolved and dropped items and the single-extraction works. Read-only.

    Refused, with nothing written: to a session that joined an extraction pass (`session`);
    without a ready schema (as `require_schema`); and on `passes` while either pass is unopened,
    when one session joined both passes or the passes share a model, or while any unit is open,
    stale, or queued with a document to extract from (decision 37 items 1, 7, 15)."""
    project.index.sync()
    if is_extraction_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session extracts; it cannot read the agreement")]
        )
    require_schema(project)
    state = _load(project)
    if state is None:
        raise FactoryValidationError([ValidationIssue("protocol", "no full-text plan")])
    for label in PassLabel:
        if state.configs[label] is None:
            raise _refuse(f"extraction pass {label.value} has not been opened")
    views = _pass_views(project, state)
    _refuse_shared(project, views)
    if state.blocking:
        raise _refuse(
            "extraction units are still open, stale or queued; agreement waits until both "
            "passes finish"
        )
    tally = _tally(state)
    return ExtractionAgreement(
        passes=views,
        dual_works=len(state.dual),
        rows_aligned=tally.rows_aligned,
        rows_unmatched=tally.rows_unmatched,
        rates=tally.rates,
        overall=tally.overall,
        disagreements=[d for p in state.pairs for d in p.open],
        resolved=sum(p.resolved for p in state.pairs),
        dropped=[d for p in state.pairs for d in p.dropped],
        single_extraction=sorted(state.single),
    )


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])


def _pass_views(project: Project, state: _State) -> list[ExtractionPassView]:
    with project.index.connect() as conn:
        joined = conn.execute(
            text(
                "SELECT session, pass_label, model FROM extraction_sessions "
                "WHERE scope = 'evidence' ORDER BY session"
            )
        ).all()
    views: list[ExtractionPassView] = []
    for label in PassLabel:
        config = state.configs[label]
        assert config is not None
        mine = [(str(s), str(m)) for s, lbl, m in joined if str(lbl) == label.value]
        views.append(
            ExtractionPassView(
                pass_label=label,
                seed=config.seed,
                field_order=config.field_order,
                sessions=[s for s, _ in mine],
                models=sorted({m for _, m in mine}),
            )
        )
    return views


def _refuse_shared(project: Project, views: list[ExtractionPassView]) -> None:
    """Refuse when one session joined both passes or the passes share a model. Joins are read
    from the log: the projection keeps the first join of a session only. A pass's models are
    those of its joins and of the actors that recorded its rows, so a session that changed to
    the other pass's model after joining is caught."""
    joins: dict[str, set[PassLabel]] = {}
    models: dict[PassLabel, set[str]] = {label: set() for label in PassLabel}
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type == "extraction.pass_joined":
            payload = ExtractionPassJoined.model_validate(event.payload)
            joins.setdefault(payload.session, set()).add(payload.pass_label)
            models[payload.pass_label].add(payload.model)
        elif event.type == "extraction.recorded" and event.actor.model is not None:
            label = PassLabel(str(event.payload["pass_label"]))
            models[label].add(event.actor.model)
    for view in views:
        models[view.pass_label].update(view.models)
    if any(len(labels) > 1 for labels in joins.values()):
        raise _refuse("a session has joined both extraction passes; each needs its own session")
    shared = sorted(models[PassLabel.A] & models[PassLabel.B])
    if shared:
        raise _refuse(f"the passes share a model ({', '.join(shared)}); each needs its own")


# --- Resolution ---


def resolve_extraction(
    project: Project,
    actor: Actor,
    work_id: str,
    row_key: str,
    field: str | None,
    choice: Choice,
    reason: str,
    channel: Channel,
) -> str:
    """Record a human's choice on a disagreement and return the event id (ruling 10).

    `field` None resolves the whole row: `a` or `b` takes that pass's row, `neither` drops it. A
    field choice takes that pass's field, or drops the field on `neither`. Refused, with nothing
    written: for an actor that is not a human (`actor`); an MCP-relayed choice from a session
    that joined an extraction pass (`channel`); a row key of the work with no current
    disagreement (`row_key`); a field not declared, not in disagreement in that row, given for
    a row disagreement, or given for a row a `neither` already drops, where it would have no
    effect (`field`); a pass that has no single row there, a `neither` on a pack-required field
    other than `value`, or a pass lacking a pack-required field chosen (`choice`: drop the row
    instead); a blank reason (`reason`). A `neither` on `value` drops the whole row.
    Re-resolving a disagreement replaces the earlier choice (last write wins)."""
    with project.index.exclusive():
        project.index.sync()
        protocol, schema, pack = require_schema(project)
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "disagreements are resolved by a human"))
        if channel is Channel.MCP and is_extraction_session(project, actor.session):
            issues.append(ValidationIssue("channel", "this session has joined an extraction pass"))
        if issues:
            raise FactoryValidationError(issues)
        state = _load(project)
        pairs = [] if state is None else state.pairs
        pair = next((p for p in pairs if (p.work_id, p.row_key) == (work_id, row_key)), None)
        disagreements = [] if pair is None else pair.disagreements
        if pair is None or not disagreements:
            raise FactoryValidationError(
                [ValidationIssue("row_key", "is not a row of this work with a disagreement")]
            )
        _check_target(pair, disagreements, schema, pack, field, choice)
        try:
            payload = ExtractionResolved(
                work_id=work_id,
                row_key=row_key,
                field=field,
                choice=choice,
                reason=reason,
                channel=channel,
                protocol_id=protocol.protocol_id,
            )
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(map(str, e["loc"])) or "item", str(e["msg"]))
                    for e in exc.errors()
                ]
            ) from exc
        event = project.events.make("extraction.resolved", payload, actor)
        project.record([event])
    return event.id


def _check_target(
    pair: _Pair,
    disagreements: list[FieldDisagreement],
    schema: ExtractionSchema,
    pack: Pack,
    field_name: str | None,
    choice: Choice,
) -> None:
    drop_instead = FactoryValidationError(
        [ValidationIssue("choice", "the pack requires this field; drop the row instead")]
    )
    if field_name is not None:
        if field_name not in schema.fields:
            raise FactoryValidationError(
                [ValidationIssue("field", "is not a field of the extraction schema")]
            )
        if not pair.aligned:
            raise FactoryValidationError(
                [ValidationIssue("field", "a row disagreement is resolved for the whole row")]
            )
        if field_name not in {d.field for d in disagreements}:
            raise FactoryValidationError(
                [ValidationIssue("field", "the passes do not disagree on this field")]
            )
        if pair.row_dropped:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "field",
                        "a neither already drops this row; only a whole-row choice changes it",
                    )
                ]
            )
        required = field_name in pack.required
        if choice == "neither" and required and field_name != VALUE_FIELD:
            raise drop_instead
    if choice != "neither":
        chosen = pair.side(choice)
        targets = pack.required if field_name is None else (field_name,)
        if len(chosen) == 1 and any(
            t in pack.required and t not in chosen[0].fields for t in targets
        ):
            raise drop_instead
    if choice != "neither" and len(pair.side(choice)) != 1:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "choice",
                    f"pass {choice.upper()} has no single row here; choose another pass or neither",
                )
            ]
        )


# --- Final and grouped rows ---


def final_rows(project: Project) -> list[FinalRow]:
    """The final rows, by work then row key: agreed and resolved rows of the dual sample and the
    pass A rows of single-extraction works. A row with an unresolved disagreement, and every row
    before pass B has opened, is left out. Read-only; empty without a schema."""
    state = _load(project)
    if state is None:
        return []
    return [p.final for p in state.pairs if p.final is not None]


def key_value(definition: FieldDef | None, f: FinalField) -> str:
    """The normalised value a final field contributes to a group key (as `group_rows` keys it):
    a number's canonical value (with its unit unless a count), text by the pack's normaliser."""
    return _key_value(definition, f)


def _key_value(definition: FieldDef | None, f: FinalField) -> str:
    stored = StoredField(
        value=f.value,
        unit=f.unit,
        canonical=f.canonical,
        reported_in=ReportedIn.OWN,
        copy_marker=False,
    )
    value, unit = _normalised(definition, stored)
    return f"{value} {unit}" if unit else value


def group_rows(rows: Iterable[FinalRow], pack: Pack, keys: Sequence[str]) -> Grouped:
    """Group `rows` by the values of `keys` (normalised as in agreement; `NON_COMPARABLE_KEYS`
    left out), keys in the given order. A row lacking a key is ungrouped. Groups are in order of
    first appearance and never ranked. Pure."""
    used = [k for k in keys if k not in NON_COMPARABLE_KEYS]
    groups: dict[GroupKey, list[FinalRow]] = {}
    ungrouped: list[FinalRow] = []
    for row in rows:
        if any(k not in row.fields for k in used):
            ungrouped.append(row)
            continue
        key = tuple((k, _key_value(pack.field(k), row.fields[k])) for k in used)
        groups.setdefault(key, []).append(row)
    return Grouped(groups=groups, ungrouped=ungrouped, unresolved=[])


def grouped_rows(project: Project) -> Grouped:
    """The final rows grouped by the schema's comparability keys (the pack's defaults when none
    are declared), with the unresolved disagreements. Read-only; empty without a schema."""
    state = _load(project)
    if state is None:
        return Grouped(groups={}, ungrouped=[], unresolved=[])
    keys = state.schema.comparability_keys or state.pack.default_comparability_keys
    grouped = group_rows((p.final for p in state.pairs if p.final is not None), state.pack, keys)
    return grouped.model_copy(update={"unresolved": [d for p in state.pairs for d in p.open]})


def independence_counts(rows: Iterable[FinalRow]) -> IndependenceCounts:
    """How many rows report an own result and how many a copied one (effectively cited value).
    A row without a `value` field counts in neither."""
    independent = copied = 0
    for row in rows:
        if row.independent:
            independent += 1
        elif VALUE_FIELD in row.fields:
            copied += 1
    return IndependenceCounts(independent=independent, copied=copied)
