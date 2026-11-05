"""Time-oriented views: the record timeline of one comparability group and the horizon activity
series (slice 7b, plan V-B, tasks 3 and 4; spec rulings 6 and 7).

Declares: `timeline_view`, `horizon_view` (the latter below), `VIEW_VERSION`. Read-only.

Invariants (timeline):
- One group, one value unit (and metric and resolution where the group key does not fix them):
  nothing is compared across groups or units. A group whose direction is unknown, conflicting or
  unparseable has no timeline, only a notice (evidence-report ruling 5).
- A row's date is the publication year of its work (`dates.published`); rows of undated works are
  listed by work id, never dated by a guess. Copied rows are never records or frontier points.
- Rows are those of corpus works (`view_corpus.corpus_among`: PRISMA's corpus minus absorbed works,
  role-blind) that no retraction notice excludes; rows of a work with a correction pending are
  left out of the records and frontiers, as the evidence report leaves them out of its frontiers.
- Trace ids are `rk_.../value`; no quote or document text is carried.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from factory.model.views import RecordPoint, TimelineView, UnitTimeline, ViewNotice
from factory.packs import Pack, ReportSpec
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.evidence_groups import key_and_rows
from factory.services.evidence_report import (
    cost_value,
    group_direction,
    metric_of,
    numeric_value,
    plain_decimal,
    report_spec,
)
from factory.services.extraction import require_schema
from factory.services.extraction_agreement import FinalRow, key_value
from factory.services.notices import work_states
from factory.services.view_corpus import corpus_among, years_of
from factory.services.views import view_meta
from factory.views.timeline import DatedPoint, records, yearly_frontiers

VIEW_VERSION = 1

_DIRECTION_TEXT = {
    "unknown": "The metric direction is neither declared nor known to the pack; "
    "this group has no timeline.",
    "conflict": "The declared metric direction is inconsistent; this group has no timeline.",
    "unparseable": "A declared metric direction is not a boolean; this group has no timeline.",
}


def timeline_view(project: Project, group_id: str) -> TimelineView:
    """The records and per-year frontiers of group `group_id`; an unknown id is refused (field
    `group_id`)."""
    with entering():
        return _timeline(project, group_id)


def _timeline(project: Project, group_id: str) -> TimelineView:
    project.index.sync()
    as_of = project.index.head()  # once, before any read: the view describes this position
    key, all_rows = key_and_rows(project, group_id)
    _, schema, pack = require_schema(project)  # key_and_rows found the group: a schema exists
    spec = report_spec(pack)
    rows, pending = _kept(project, all_rows)
    notices: list[ViewNotice] = []
    direction, status = group_direction(key, rows, pack, spec)
    units: dict[str, UnitTimeline] = {}
    undated: list[str] = []
    if not rows:
        notices.append(
            ViewNotice(
                code="group-empty",
                text="No row of this group belongs to a corpus work that is not excluded.",
            )
        )
    elif status not in ("declared", "pack-default") or direction is None:
        notices.append(ViewNotice(code=f"direction-{status}", text=_DIRECTION_TEXT[status]))
    else:
        axes = [
            a
            for a in spec.frontier_costs
            if a not in spec.speed_fields and pack.field(a) is not None and a in schema.fields
        ]
        with project.index.connect() as conn:
            years = years_of(conn, sorted({r.work_id for r in rows}))
        undated = sorted({r.work_id for r in rows if r.work_id not in years})
        units, skipped = _units(rows, pending, years, dict(key), pack, spec, axes, direction)
        if skipped:
            notices.append(
                ViewNotice(
                    code="value-not-numeric",
                    text=f"{skipped} independent row(s) have no numeric value and are not plotted.",
                )
            )
    if pending:
        notices.append(
            ViewNotice(
                code="correction-pending",
                text=f"Rows of {len(pending)} work(s) with a correction pending are left out of "
                "the records and frontiers.",
            )
        )
    return TimelineView(
        meta=view_meta(
            project,
            "timeline",
            VIEW_VERSION,
            {"group_id": group_id, "rows": "independent rows of dated corpus works"},
            notices=notices,
            as_of=as_of,
        ),
        group_id=group_id,
        key=list(key),
        direction=status,
        higher_is_better=direction if status in ("declared", "pack-default") else None,
        units=units,
        undated=undated,
    )


def _kept(project: Project, rows: Sequence[FinalRow]) -> tuple[list[FinalRow], frozenset[str]]:
    """The rows of corpus works without a retraction notice, and the works among them with a
    correction pending."""
    with project.index.connect() as conn:
        corpus = corpus_among(conn, sorted({r.work_id for r in rows}))
    states = work_states(project)
    excluded = {w for w, s in states.items() if s.synthesis == "excluded"}
    pending = frozenset(w for w, s in states.items() if s.flag == "correction-pending")
    kept = [r for r in rows if r.work_id in corpus and r.work_id not in excluded]
    return kept, frozenset(r.work_id for r in kept) & pending


def _units(
    rows: Sequence[FinalRow],
    pending: frozenset[str],
    years: dict[str, int],
    key: dict[str, str],
    pack: Pack,
    spec: ReportSpec,
    axes: Sequence[str],
    higher_is_better: bool,
) -> tuple[dict[str, UnitTimeline], int]:
    by_metric = "metric" not in key
    by_resolution = "input_resolution" not in key
    buckets: dict[str, tuple[str | None, str | None, str | None, list[DatedPoint]]] = {}
    skipped = 0
    for row in rows:
        if not row.independent or row.work_id in pending:
            continue
        field = row.fields[spec.value_field]
        value = numeric_value(field)
        if value is None:
            skipped += 1
            continue
        metric = metric_of(row, pack) if by_metric else None
        res_field = row.fields.get("input_resolution")
        resolution = (
            key_value(pack.field("input_resolution"), res_field)
            if by_resolution and res_field is not None
            else None
        )
        label = _label(field.unit, metric, resolution)
        point = DatedPoint(
            trace_id=f"{row.row_key}/{spec.value_field}",
            work_id=row.work_id,
            row_key=row.row_key,
            year=years.get(row.work_id),
            value=value,
            unit=field.unit or "",
            costs=_costs(row, pack, axes),
            independent=True,
        )
        buckets.setdefault(label, (field.unit, metric, resolution, []))[3].append(point)
    units: dict[str, UnitTimeline] = {}
    for label in sorted(buckets):
        unit, metric, resolution, points = buckets[label]
        units[label] = UnitTimeline(
            unit=unit,
            metric=metric or None,
            resolution=resolution,
            records=[
                RecordPoint(
                    trace_id=p.trace_id,
                    work_id=p.work_id,
                    row_key=p.row_key,
                    year=p.year or 0,
                    value=plain_decimal(p.value),
                )
                for p in records(points, higher_is_better)
            ],
            frontiers=yearly_frontiers(points, higher_is_better, axes),
        )
    return units, skipped


def _label(unit: str | None, metric: str | None, resolution: str | None) -> str:
    parts = [f"unit {unit}" if unit else "no unit"]
    if metric:
        parts.append(f"metric {metric}")
    if resolution:
        parts.append(f"resolution {resolution}")
    return "; ".join(parts)


def _costs(row: FinalRow, pack: Pack, axes: Sequence[str]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for axis in axes:
        field = row.fields.get(axis)
        definition = pack.field(axis)
        if field is None or definition is None:
            continue
        amount = cost_value(field, definition.unit_family)
        if amount is not None and amount > 0:
            out[axis] = amount
    return out
