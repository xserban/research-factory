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

- Every read takes a `scope` (default evidence): rows, passes, tasks, resolutions and the open-unit
  block are those of that scope only, so a contribution unit never blocks or enters evidence
  agreement and conversely. A contribution compares the pack's `compared_fields` (statement and
  quote are never compared); grouping and independence are evidence-only.

- Rows imported from another project are accounted apart (ruling 19, R-143). A unit an import fills
  enters neither the dual nor the single works, nor any pair, so no agreement rate and no dual count
  moves. Its rows join the final rows with `origin` imported: `agreed` only when the source had two
  agreeing, independent passes, else `single`, whatever the source called them.

Everything here is read-only except `resolve_extraction`, which writes one event or nothing.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import SerializerFunctionWrapHandler, ValidationError, model_serializer
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
    MinerScope,
    ReportedIn,
    Scope,
    ScopeKey,
    StoredField,
    pack_tag,
    scope_of_pack,
    scope_of_schema_ref,
)
from factory.model.protocol import ExtractionSchema
from factory.model.screening import Channel, PassLabel
from factory.packs import NON_COMPARABLE_KEYS, FieldDef, FieldKind, Pack, UnitFamily
from factory.packs.model import Check
from factory.services.call_memo import memoised
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ExtractionRow,
    PassConfig,
    calibration_sessions_of,
    calibration_task_ids,
    filled_imports,
    import_items,
    in_dual_sample,
    is_extraction_session,
    live_rows,
    pass_config,
    require_schema,
    scope_population,
    stale_extractions,
    unit_states,
)
from factory.services.extraction import (
    _Ledger as Ledger,
)
from factory.services.extraction_verify import VALUE_FIELD
from factory.services.gates import gate_issues
from factory.services.passes import shared_refusal

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
    "SettledRow",
    "agreement_overall",
    "cell_key",
    "extraction_agreement",
    "field_disagreements",
    "final_field",
    "final_rows",
    "final_rows_restricted",
    "group_rows",
    "grouped_rows",
    "independence_counts",
    "key_value",
    "resolve_extraction",
    "settled_rows",
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
    unmatched_slots: int = 0
    overall_all_rows: float | None = None
    """`overall` with the unmatched rows counted against it (IDEA-69 (2), see `_tally`)."""
    evidence_overlap: float | None = None
    """The token-overlap threshold under which free-quote fields were compared by evidence
    overlap (IDEA-52), or None: exact. The disagreement list below is always the exact one."""
    disagreements: list[FieldDisagreement]
    """Unresolved disagreements only."""
    resolved: int
    dropped: list[DroppedItem]
    single_extraction: list[str]


class AgreementOverall(StrictModel):
    """`overall` = agreed / compared field values of the `rows_aligned` aligned rows;
    `overall_all_rows` counts the unmatched rows against it as well (IDEA-69 (2))."""

    overall: float | None
    dual: int
    single: int
    rows_aligned: int
    rows_unmatched: int
    unmatched_slots: int = 0
    overall_all_rows: float | None = None
    evidence_overlap: float | None = None
    """The evidence-overlap threshold the rates were computed under, or None (exact)."""


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
    origin: Literal["local", "imported"] = "local"

    @model_serializer(mode="wrap")
    def _local_says_nothing(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """A local row serialises as it did before imports existed."""
        out: dict[str, Any] = handler(self)
        if self.origin == "local":
            out.pop("origin", None)
        return out


GroupKey = tuple[tuple[str, str], ...]


class Grouped(StrictModel):
    groups: dict[GroupKey, list[FinalRow]]
    ungrouped: list[FinalRow]
    """Rows lacking a comparability key."""
    unresolved: list[FieldDisagreement]


class IndependenceCounts(StrictModel):
    """`imported_dual` and `imported_single` count imported rows, which are in neither of the
    others: an imported row was not mined here, whatever it reports."""

    independent: int
    copied: int
    imported_dual: int = 0
    imported_single: int = 0

    @model_serializer(mode="wrap")
    def _no_imports_say_nothing(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Counts without imports serialise as they did before imports existed."""
        out: dict[str, Any] = handler(self)
        for name in ("imported_dual", "imported_single"):
            if not out.get(name):
                out.pop(name, None)
        return out


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


NO_UNIT_TEXT = "none"
"""A unit written as this text (after normalisation) is the same as no unit (IDEA-68)."""


def carries_unit(definition: FieldDef | None) -> bool:
    """Whether a field's unit is part of its answer. An enum (`allowed`), a quote checked
    against its evidence (quote, citation, work reference by title) and a field declared
    `unitless` (anchor, work reference by entry) carry none; an undeclared field and every
    other kind (numbers included) keep comparing the unit (IDEA-68)."""
    if definition is None:
        return True
    return not (
        definition.unitless or definition.allowed or definition.check is Check.TEXT_IN_QUOTE
    )


def _unit(definition: FieldDef | None, f: StoredField) -> str:
    """The normalised unit a field is compared by: empty for a kind that carries none, and for
    an absent unit or the text `none`."""
    if not carries_unit(definition):
        return ""
    unit = normalise_text(f.unit or "")
    return "" if unit == NO_UNIT_TEXT else unit


def _normalised(definition: FieldDef | None, f: StoredField) -> tuple[str, str]:
    """The (value, unit) a field is compared and grouped by. Never the raw text of a number.
    The unit is `_unit`'s: ignored where the kind carries none, absent equal to `none`."""
    unit = _unit(definition, f)
    if definition is None:
        return normalise_text(str(f.value)), unit
    if definition.kind in (FieldKind.NUMBER, FieldKind.INTEGER) and f.canonical is not None:
        if definition.unit_family is UnitFamily.COUNT:
            return f.canonical, ""  # already scaled by its unit
        return f.canonical, unit
    if definition.kind is FieldKind.TEXT:
        return normalise_for(definition, str(f.value)), unit
    return normalise_text(str(f.value)), unit


def is_free_quote(definition: FieldDef | None) -> bool:
    """Whether a field is a free quote: text checked against its evidence, with no fixed values
    (a quote or citation field; not an enum, an anchor or a number)."""
    return (
        definition is not None
        and definition.kind is FieldKind.TEXT
        and definition.check is Check.TEXT_IN_QUOTE
        and not definition.allowed
    )


def _tokens(f: StoredField) -> frozenset[str]:
    return frozenset(normalise_text(f.quote or str(f.value)).split())


def evidence_overlaps(fa: StoredField, fb: StoredField, threshold: float) -> bool:
    """Whether two free-quote fields rest on the same evidence (IDEA-52). True when they cite the
    same anchor, or one normalised quote contains the other (the platform stores no character
    offsets, so containment is its span overlap), or the normalised token sets overlap by at
    least `threshold` (intersection over union). A field with neither a quote nor a value of
    tokens overlaps nothing but its own anchor. Pure and symmetric."""
    if fa.anchor is not None and fa.anchor == fb.anchor:
        return True
    qa = normalise_text(fa.quote or str(fa.value))
    qb = normalise_text(fb.quote or str(fb.value))
    if not qa or not qb:
        return False
    if qa in qb or qb in qa:
        return True
    ta, tb = _tokens(fa), _tokens(fb)
    return len(ta & tb) / len(ta | tb) >= threshold


def _same(
    definition: FieldDef | None,
    fa: StoredField,
    fb: StoredField,
    overlap: float | None = None,
) -> bool:
    """Plan D's rule; with `overlap` (a threshold), a free-quote field also agrees when the two
    quotes rest on the same evidence (`evidence_overlaps`). Off (None) by default."""
    if fa.reported_in is not fb.reported_in or fa.reproduced != fb.reproduced:
        return False
    if _normalised(definition, fa) == _normalised(definition, fb):
        return True
    return overlap is not None and is_free_quote(definition) and evidence_overlaps(fa, fb, overlap)


def same_field(
    definition: FieldDef | None,
    fa: StoredField,
    fb: StoredField,
    *,
    evidence_overlap: float | None = None,
) -> bool:
    """Whether two stored fields agree under plan D's rule (also the calibration score's); with
    `evidence_overlap` a threshold, free-quote fields compare by evidence overlap (IDEA-52)."""
    return _same(definition, fa, fb, evidence_overlap)


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
    scope: ScopeKey = Scope.EVIDENCE
    identity: str = VALUE_FIELD
    """The field a row disagreement shows and whose `neither` drops the row (`value` in evidence,
    the pack's first required field, `item_kind`, in contribution)."""
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
                a=_row_view(self.a, self.identity),
                b=_row_view(self.b, self.identity),
            )
        ]

    def side(self, choice: Choice) -> list[ExtractionRow]:
        return self.a if choice == "a" else self.b if choice == "b" else []


def _row_view(rows: list[ExtractionRow], identity: str) -> FieldView | None:
    if len(rows) != 1 or identity not in rows[0].fields:
        return None
    return _view(rows[0].fields[identity], rows[0].extraction_id)


@dataclass(frozen=True)
class _State:
    """The extraction state under the current protocol, read once.

    `known` is False until pass B has opened (the dual sample is unknown); `dual` and `single`
    are then empty and no work is final. `blocking` is True while a unit of the population is
    open, stale, or queued with a document to extract from."""

    scope: ScopeKey
    schema: ExtractionSchema
    pack: Pack
    configs: dict[PassLabel, PassConfig | None]
    known: bool
    dual: frozenset[str]
    single: frozenset[str]
    blocking: bool
    pairs: list[_Pair]
    imported: list[FinalRow] = field(default_factory=list)
    """The final rows of the units an import fills, by work then row key; no pair holds them."""


def _compared_fields(schema: ExtractionSchema, pack: Pack) -> Sequence[str]:
    """The fields dual extraction compares: the pack's `compared_fields` (in schema order, those
    the schema declares) when it sets them, else every declared field."""
    if pack.compared_fields is None:
        return schema.fields
    return [f for f in schema.fields if f in pack.compared_fields]


def _identity(scope: ScopeKey, pack: Pack) -> str:
    return VALUE_FIELD if scope is Scope.EVIDENCE else pack.required[0]


def _load(
    project: Project,
    scope: ScopeKey = Scope.EVIDENCE,
    works: Collection[str] | None = None,
    ledger: Ledger | None = None,
) -> _State | None:
    """`_read_state`, kept for the call when it reads the whole scope. The state is frozen and no
    reader changes its lists; a restricted read is not kept, as its `works` need not hash."""
    if works is None:
        return _whole_state(project, scope, ledger)
    return _read_state(project, scope, works, ledger)


@memoised
def _whole_state(project: Project, scope: ScopeKey, ledger: Ledger | None = None) -> _State | None:
    return _read_state(project, scope, None, ledger)


def _read_state(
    project: Project,
    scope: ScopeKey,
    works: Collection[str] | None,
    ledger: Ledger | None = None,
) -> _State | None:
    """The state of `scope`, or None without a ready protocol with a known schema and (for
    evidence) a full-text plan. With `works`, only those works of the population enter: a work's
    pairs, dual membership and settlement depend on that work alone, so the pairs equal the
    unrestricted ones for the same works (the per-group accessors of `evidence_groups` rely on
    it)."""
    project.index.sync()
    try:
        _, schema, pack = require_schema(project, scope=scope)
        population = scope_population(project, scope)
    except FactoryValidationError:
        return None
    if works is not None:
        wanted = set(works)
        population = [w for w in population if w in wanted]
    filled = filled_imports(project, scope, ledger=ledger)
    imported = _imported_finals(project, filled, population, schema, pack)
    population = [w for w in population if w not in filled]
    configs = {label: pass_config(project, label, scope=scope) for label in PassLabel}
    b_config = configs[PassLabel.B]
    known = configs[PassLabel.A] is not None and b_config is not None
    dual: frozenset[str] = frozenset()
    if b_config is not None:
        dual = frozenset(
            w for w in population if in_dual_sample(b_config.seed, w, schema.dual_extract_sample)
        )
    single = frozenset(population) - dual if b_config is not None else frozenset()
    states = unit_states(project, scope=scope, ledger=ledger)
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
    for row in _eligible_rows(project, set(population), scope, ledger):
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
            scope=scope,
            identity=_identity(scope, pack),
        )
        for work, key in keys
    ]
    resolutions = _resolutions(project, scope)
    for pair in pairs:
        if pair.aligned:
            pair.compared = _compare(pack, _compared_fields(schema, pack), pair.a[0], pair.b[0])
        _settle(pair, schema, pack, resolutions)
    return _State(scope, schema, pack, configs, known, dual, single, blocking, pairs, imported)


def _imported_finals(
    project: Project,
    filled: Mapping[str, list[ExtractionRow]],
    population: Sequence[str],
    schema: ExtractionSchema,
    pack: Pack,
) -> list[FinalRow]:
    """The final rows of the imported units of works in `population`. A row counts as agreed only
    on the fold's `dual`, computed from the passes the event names; one lacking a field the pack
    requires is left out, as `_final` leaves out a local one."""
    if not filled:
        return []
    items = import_items(project)
    out: list[FinalRow] = []
    for work in population:
        for row in filled.get(work, ()):
            item = items.get(row.extraction_id)
            fields = {
                name: final_field(row.fields[name], row.extraction_id)
                for name in schema.fields
                if name in row.fields
            }
            if any(name not in fields for name in pack.required):
                continue
            out.append(
                FinalRow(
                    work_id=row.work_id,
                    document_id=row.document_id,
                    conversion_id=row.conversion_id,
                    row_key=row.row_key,
                    status="agreed" if item is not None and item.dual else "single",
                    fields=fields,
                    independent=False,
                    origin="imported",
                )
            )
    return sorted(out, key=lambda r: (r.work_id, r.row_key))


def _finals(state: _State) -> list[FinalRow]:
    """The final rows of `state`, mined and imported, by work then row key."""
    mined = [p.final for p in state.pairs if p.final is not None]
    if not state.imported:
        return mined
    return sorted([*mined, *state.imported], key=lambda r: (r.work_id, r.row_key))


def _eligible_rows(
    project: Project,
    population: set[str],
    scope: ScopeKey = Scope.EVIDENCE,
    ledger: Ledger | None = None,
) -> list[ExtractionRow]:
    """The rows agreement and final rows may use: live (not superseded), not stale, and of a
    work still in the scope's population. The one place these exclusions are made."""
    stale = stale_extractions(project, scope=scope, ledger=ledger)
    return [
        row
        for row in live_rows(project, scope=scope)
        if row.work_id in population and row.extraction_id not in stale
    ]


def _resolutions(
    project: Project, scope: ScopeKey = Scope.EVIDENCE
) -> dict[tuple[str, str, str], _Resolution]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, row_key, field, choice, event_id FROM extraction_resolutions "
                "WHERE scope = :scope"
            ),
            {"scope": scope.value},
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
    if choices.get(pair.identity) == "neither":
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
        independent=pair.scope is Scope.EVIDENCE
        and value is not None
        and value.reported_in is ReportedIn.OWN,
    )


# --- Agreement ---


@dataclass(frozen=True)
class _Tally:
    rates: list[GroupRate]
    overall: float | None
    rows_aligned: int
    rows_unmatched: int
    unmatched_slots: int
    overall_all_rows: float | None


def _present(rows: Sequence[ExtractionRow], names: Collection[str]) -> int:
    """The compared field values present over `rows`."""
    return sum(name in row.fields for row in rows for name in names)


def _unmatched(state: _State, names: Collection[str]) -> tuple[int, int]:
    """The unmatched slots and the compared field values they hold (IDEA-69 (2)).

    Per dual work, the non-aligned row keys are split by pass; the work holds as many slots as
    the larger side has keys (two passes that chose different categories fill one slot, not two)
    and as many compared values as the larger side's rows hold. None of them agrees."""
    sides: dict[str, tuple[list[ExtractionRow], list[ExtractionRow], list[int]]] = {}
    for pair in state.pairs:
        if not pair.dual or pair.aligned:
            continue
        a, b, keys = sides.setdefault(pair.work_id, ([], [], [0, 0]))
        a.extend(pair.a)
        b.extend(pair.b)
        keys[0] += bool(pair.a)
        keys[1] += bool(pair.b)
    slots = sum(max(keys) for _, _, keys in sides.values())
    values = sum(max(_present(a, names), _present(b, names)) for a, b, _ in sides.values())
    return slots, values


def _tally(state: _State, evidence_overlap: float | None = None) -> _Tally:
    """Per-group and overall agreement over the compared fields of aligned rows (with
    `evidence_overlap`, a free-quote field also agrees when its quotes rest on the same
    evidence, IDEA-52; the exact comparison otherwise), and the row counts: aligned pairs, and
    row keys of dual works that do not align (one pass only, or a pass holding the key twice).
    `overall_all_rows` adds the compared values of the unmatched slots (`_unmatched`) to the
    denominator: a row only one pass wrote never agrees."""
    groups: dict[str, list[int]] = {}
    compared_fields = set(_compared_fields(state.schema, state.pack))
    for definition in state.pack.fields:
        if definition.name in compared_fields:
            groups.setdefault(definition.group, [0, 0])
    for pair in state.pairs:
        for name, disagreement in pair.compared:
            found = state.pack.field(name)
            counts = groups.setdefault(found.group if found else "other", [0, 0])
            counts[0] += 1
            agreed_here = disagreement is None
            if not agreed_here and evidence_overlap is not None and pair.aligned:
                fa, fb = pair.a[0].fields.get(name), pair.b[0].fields.get(name)
                agreed_here = (
                    fa is not None and fb is not None and _same(found, fa, fb, evidence_overlap)
                )
            counts[1] += agreed_here
    rates = [
        GroupRate(group=g, compared=c, agreed=a, rate=a / c if c else None)
        for g, (c, a) in groups.items()
    ]
    compared = sum(r.compared for r in rates)
    agreed = sum(r.agreed for r in rates)
    slots, missed = _unmatched(state, compared_fields)
    return _Tally(
        rates=rates,
        overall=agreed / compared if compared else None,
        rows_aligned=sum(p.aligned for p in state.pairs),
        rows_unmatched=sum(p.dual and not p.aligned for p in state.pairs),
        unmatched_slots=slots,
        overall_all_rows=agreed / (compared + missed) if compared + missed else None,
    )


def agreement_overall(
    project: Project,
    *,
    scope: ScopeKey = Scope.EVIDENCE,
    evidence_overlap: float | None = None,
    ledger: Ledger | None = None,
) -> AgreementOverall:
    """Overall agreement, the dual and single work counts and the row counts. Read-only, needs
    no actor and never raises.

    `overall` = agreed / compared field values, where a compared field value is one declared
    field present in either row of an aligned pair (`rows_aligned` pairs of current, live,
    non-stale rows of dual works); unmatched rows (`rows_unmatched`) are not in its denominator,
    but are in `overall_all_rows`'s (IDEA-69 (2)).
    `overall` is None while a unit is open or stale, before both passes opened, or when nothing
    is compared. `dual` and `single` are 0 until pass B has opened. It does not check session or
    model independence; `extraction_agreement` does."""
    try:
        state = _load(project, scope, ledger=ledger)
    except FactoryValidationError:
        state = None
    if state is None:
        return AgreementOverall(overall=None, dual=0, single=0, rows_aligned=0, rows_unmatched=0)
    tally = _tally(state, evidence_overlap)
    withheld = state.blocking or not state.known
    return AgreementOverall(
        overall=None if withheld else tally.overall,
        dual=len(state.dual),
        single=len(state.single),
        rows_aligned=tally.rows_aligned,
        rows_unmatched=tally.rows_unmatched,
        unmatched_slots=tally.unmatched_slots,
        overall_all_rows=None if withheld else tally.overall_all_rows,
        evidence_overlap=evidence_overlap,
    )


def extraction_agreement(
    project: Project,
    actor: Actor,
    *,
    scope: ScopeKey = Scope.EVIDENCE,
    evidence_overlap: float | None = None,
) -> ExtractionAgreement:
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
    require_schema(project, scope=scope)
    state = _load(project, scope)
    if state is None:
        raise FactoryValidationError([ValidationIssue("protocol", "no full-text plan")])
    for label in PassLabel:
        if state.configs[label] is None:
            raise _refuse(f"extraction pass {label.value} has not been opened")
    views = _pass_views(project, state)
    _refuse_shared(project, views, scope)
    if state.blocking:
        raise _refuse(
            "extraction units are still open, stale or queued; agreement waits until both "
            "passes finish"
        )
    tally = _tally(state, evidence_overlap)
    return ExtractionAgreement(
        passes=views,
        dual_works=len(state.dual),
        rows_aligned=tally.rows_aligned,
        rows_unmatched=tally.rows_unmatched,
        rates=tally.rates,
        overall=tally.overall,
        unmatched_slots=tally.unmatched_slots,
        overall_all_rows=tally.overall_all_rows,
        evidence_overlap=evidence_overlap,
        disagreements=[d for p in state.pairs for d in p.open],
        resolved=sum(p.resolved for p in state.pairs),
        dropped=[d for p in state.pairs for d in p.dropped],
        single_extraction=sorted(state.single),
    )


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])


def _pass_views(project: Project, state: _State) -> list[ExtractionPassView]:
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT session, pass_label, model FROM extraction_sessions "
                "WHERE scope = :scope ORDER BY session"
            ),
            {"scope": state.scope.value},
        ).all()
    apart = calibration_sessions_of(project, state.scope)
    joined = [row for row in found if str(row[0]) not in apart]
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


def _refuse_shared(
    project: Project, views: list[ExtractionPassView], scope: ScopeKey = Scope.EVIDENCE
) -> None:
    """Refuse when one session joined both passes or the passes share a model. Joins are read
    from the log: the projection keeps the first join of a session only. A pass's models are
    those of its joins and of the actors that recorded its rows, so a session that changed to
    the other pass's model after joining is caught."""
    joins: dict[PassLabel, set[str]] = {label: set() for label in PassLabel}
    models: dict[PassLabel, set[str]] = {label: set() for label in PassLabel}
    apart = calibration_sessions_of(project, scope)
    apart_tasks = calibration_task_ids(project, scope)
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type == "extraction.pass_joined":
            payload = ExtractionPassJoined.model_validate(event.payload)
            if scope_of_pack(payload.pack) != scope or payload.session in apart:
                continue
            joins[payload.pass_label].add(payload.session)
            models[payload.pass_label].add(payload.model)
        elif (
            event.type == "extraction.recorded"
            and event.actor.model is not None
            and scope_of_schema_ref(str(event.payload["schema_ref"])) == scope
            and str(event.payload["task_id"]) not in apart_tasks
        ):
            label = PassLabel(str(event.payload["pass_label"]))
            models[label].add(event.actor.model)
    for view in views:
        models[view.pass_label].update(view.models)
    refusal = shared_refusal(joins, models, noun="extraction")
    if refusal is not None:
        raise refusal


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
    *,
    scope: ScopeKey = Scope.EVIDENCE,
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
    Re-resolving a disagreement replaces the earlier choice (last write wins). A contribution
    resolution carries `pack: contribution`; an evidence one carries none, as before."""
    with project.index.exclusive():
        project.index.sync()
        protocol, schema, pack = require_schema(project, scope=scope)
        issues: list[ValidationIssue] = []
        issues.extend(
            gate_issues(
                project,
                actor,
                "mine.resolve" if isinstance(scope, MinerScope) else "extraction.resolve",
                channel=channel,
                agent_text="disagreements are resolved by a human",
            )
        )
        if isinstance(scope, MinerScope):
            from factory.services.miner_independence import resolve_issues  # imports mining

            issues.extend(resolve_issues(project, actor, scope.name, channel))
        if issues:
            raise FactoryValidationError(issues)
        state = _load(project, scope)
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
                pack=pack_tag(scope),
            )
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(map(str, e["loc"])) or "item", str(e["msg"]))
                    for e in exc.errors()
                ]
            ) from exc
        event = project.events.make(
            "extraction.resolved",
            payload,
            actor,
            input_blob=(
                project.blobs.put_json(payload.model_dump(mode="json"))
                if actor.kind == "agent"
                else None
            ),
        )
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
        if choice == "neither" and required and field_name != pair.identity:
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


def final_rows(
    project: Project, *, scope: ScopeKey = Scope.EVIDENCE, ledger: Ledger | None = None
) -> list[FinalRow]:
    """The final rows, by work then row key: agreed and resolved rows of the dual sample and the
    pass A rows of single-extraction works. A row with an unresolved disagreement, and every row
    before pass B has opened, is left out. Read-only; empty without a schema."""
    state = _load(project, scope, ledger=ledger)
    return [] if state is None else _finals(state)


@dataclass(frozen=True)
class SettledRow:
    """A final row with every live row of its pair: what a source project offers (M-E)."""

    final: FinalRow
    extraction_ids: tuple[str, ...]


def settled_rows(
    project: Project, *, scope: ScopeKey
) -> tuple[list[SettledRow], frozenset[tuple[str, str]]]:
    """The final rows of `scope` with the rows behind each, and the `(work_id, row_key)` of the
    rows a human dropped (`neither`). Read-only; both are empty without a schema."""
    state = _load(project, scope)
    if state is None:
        return [], frozenset()
    settled = [
        SettledRow(p.final, tuple(sorted(r.extraction_id for r in (*p.a, *p.b))))
        for p in state.pairs
        if p.final is not None
    ]
    return settled, frozenset((p.work_id, p.row_key) for p in state.pairs if p.row_dropped)


def final_rows_restricted(
    project: Project, works: Collection[str], *, scope: ScopeKey = Scope.EVIDENCE
) -> list[FinalRow]:
    """`final_rows` of the given works only; equal to the filter of `final_rows` by work."""
    state = _load(project, scope, works)
    return [] if state is None else _finals(state)


def cell_key(
    definition: FieldDef | None, value: str, unit: str | None, canonical: str | None
) -> str:
    """The normalised value a stored key cell contributes to a group key (as `key_value`)."""
    stored = StoredField(
        value=value, unit=unit, canonical=canonical, reported_in=ReportedIn.OWN, copy_marker=False
    )
    text_value, norm_unit = _normalised(definition, stored)
    return f"{text_value} {norm_unit}" if norm_unit else text_value


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
    grouped = group_rows(_finals(state), state.pack, keys)
    return grouped.model_copy(update={"unresolved": [d for p in state.pairs for d in p.open]})


def independence_counts(rows: Iterable[FinalRow]) -> IndependenceCounts:
    """How many rows report an own result and how many a copied one (effectively cited value).
    A row without a `value` field counts in neither. An imported row counts in neither either, but
    in `imported_dual` when the source had two agreeing passes, else in `imported_single`."""
    independent = copied = imported_dual = imported_single = 0
    for row in rows:
        if row.origin == "imported":
            if row.status == "agreed":
                imported_dual += 1
            else:
                imported_single += 1
        elif row.independent:
            independent += 1
        elif VALUE_FIELD in row.fields:
            copied += 1
    return IndependenceCounts(
        independent=independent,
        copied=copied,
        imported_dual=imported_dual,
        imported_single=imported_single,
    )
