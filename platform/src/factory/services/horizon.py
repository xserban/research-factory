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

from factory.model.views import (
    HorizonView,
    RecordPoint,
    TimelineView,
    UnitTimeline,
    ViewNotice,
)
from factory.packs import Pack, ReportSpec
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.evidence_groups import key_and_rows
from factory.services.evidence_report import (
    cost_value,
    group_direction,
    group_id,
    metric_of,
    numeric_value,
    plain_decimal,
    report_spec,
)
from factory.services.extraction import require_schema
from factory.services.extraction_agreement import FinalRow, GroupKey, grouped_rows, key_value
from factory.services.ideas import confirmed_ideas
from factory.services.notices import work_states
from factory.services.references import included_works
from factory.services.relations import relation_years
from factory.services.view_corpus import (
    corpus_among,
    horizon_notice,
    search_horizon,
    years_of,
)
from factory.services.views import view_meta
from factory.views.timeline import DatedPoint, records, yearly_frontiers

VIEW_VERSION = 1
HORIZON_MAX_IDEAS = 200
HORIZON_MAX_GROUPS = 200

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
    notices.append(horizon_notice(search_horizon(project)))
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


def _visible(project: Project, works: Sequence[str]) -> tuple[set[str], frozenset[str]]:
    """Of `works`, those in the corpus (minus absorbed) that no retraction notice excludes, and
    those among them with a correction pending."""
    with project.index.connect() as conn:
        corpus = corpus_among(conn, sorted(set(works)))
    states = work_states(project)
    excluded = {w for w, s in states.items() if s.synthesis == "excluded"}
    pending = frozenset(w for w, s in states.items() if s.flag == "correction-pending")
    keep = corpus - excluded
    return keep, frozenset(keep) & pending


def _kept(project: Project, rows: Sequence[FinalRow]) -> tuple[list[FinalRow], frozenset[str]]:
    """The rows of corpus works without a retraction notice, and the works among them with a
    correction pending."""
    keep, pending = _visible(project, [r.work_id for r in rows])
    return [r for r in rows if r.work_id in keep], pending


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


def horizon_view(project: Project) -> HorizonView:
    """Activity per year: included works per confirmed idea, new confirmed ideas, new stated or
    confirmed lineage edges, records per group (see the module docstring)."""
    with entering():
        return _horizon(project)


def _horizon(project: Project) -> HorizonView:
    project.index.sync()
    as_of = project.index.head()
    notices: list[ViewNotice] = []
    included = set(included_works(project))
    ideas = confirmed_ideas(project)
    listed = ideas[:HORIZON_MAX_IDEAS]
    grouped = grouped_rows(project)
    ordered = sorted(
        grouped.groups.items(), key=lambda kv: (-len({r.work_id for r in kv[1]}), kv[0])
    )
    shown_groups = ordered[:HORIZON_MAX_GROUPS]
    wanted = {m for i in listed for m in i.effective_members} | {i.origin for i in listed}
    group_works = {r.work_id for _, rows in shown_groups for r in rows}
    with project.index.connect() as conn:
        corpus = corpus_among(conn, sorted(wanted | included))
        years = years_of(conn, sorted(wanted | group_works))
    members_ok = included & corpus
    undated = {"idea_members": 0, "new_ideas": 0, "new_edges": 0}
    idea_members: dict[str, dict[int, int]] = {}
    new_ideas: dict[int, list[str]] = {}
    for idea in listed:
        per_year: dict[int, int] = {}
        for work in idea.effective_members:
            if work not in members_ok:
                continue
            if work in years:
                per_year[years[work]] = per_year.get(years[work], 0) + 1
            else:
                undated["idea_members"] += 1
        idea_members[idea.idea_id] = dict(sorted(per_year.items()))
        if idea.origin in years:
            new_ideas.setdefault(years[idea.origin], []).append(idea.idea_id)
        else:
            undated["new_ideas"] += 1
    new_edges: dict[int, int] = {}
    for year, count in relation_years(project).items():
        if year is None:
            undated["new_edges"] += count
        else:
            new_edges[int(year)] = count
    group_records = _group_records(project, shown_groups, years)
    keys = [set(per) for per in idea_members.values()] + [set(new_ideas), set(new_edges)]
    keys += [set(per) for per in group_records.values()]
    horizon = search_horizon(project)
    notices.append(horizon_notice(horizon))
    if not ideas and not new_edges and not group_records:
        notices.append(
            ViewNotice(
                code="horizon-empty",
                text="No confirmed idea, lineage edge or record timeline exists yet; the "
                "series are empty.",
            )
        )
    truncated = len(listed) < len(ideas) or len(shown_groups) < len(ordered)
    return HorizonView(
        meta=view_meta(
            project,
            "horizon",
            VIEW_VERSION,
            {
                "series": "included works per idea, new ideas, new stated or confirmed edges, "
                "records per group; by publication year",
                "max_ideas": HORIZON_MAX_IDEAS,
                "max_groups": HORIZON_MAX_GROUPS,
            },
            truncated=truncated,
            notices=notices,
            as_of=as_of,
        ),
        years=sorted(set().union(*keys)) if keys else [],
        idea_members={i: idea_members[i] for i in sorted(idea_members)},
        new_ideas={y: sorted(new_ideas[y]) for y in sorted(new_ideas)},
        new_edges=dict(sorted(new_edges.items())),
        group_records=group_records,
        undated=undated,
        horizon=horizon,
        total_ideas=len(ideas),
        total_groups=len(ordered),
    )


def _group_records(
    project: Project, groups: Sequence[tuple[GroupKey, list[FinalRow]]], years: dict[str, int]
) -> dict[str, dict[int, int]]:
    """Records per year for each group with a timeline (a known direction): counts only."""
    if not groups:
        return {}
    _, _, pack = require_schema(project)
    spec = report_spec(pack)
    keep, pending = _visible(project, [r.work_id for _, rows in groups for r in rows])
    out: dict[str, dict[int, int]] = {}
    for key, all_rows in groups:
        rows = [r for r in all_rows if r.work_id in keep]
        direction, status = group_direction(key, rows, pack, spec)
        if not rows or status not in ("declared", "pack-default") or direction is None:
            continue
        units, _ = _units(rows, pending, years, dict(key), pack, spec, [], direction)
        per_year: dict[int, int] = {}
        for unit in units.values():
            for record in unit.records:
                per_year[record.year] = per_year.get(record.year, 0) + 1
        if per_year:
            out[group_id(key)] = dict(sorted(per_year.items()))
    return dict(sorted(out.items()))
