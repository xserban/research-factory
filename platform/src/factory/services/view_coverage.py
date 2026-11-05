"""The coverage map: normalised method x comparability group, counts only (slice 7b, plan V-B,
task 2; spec ruling 5).

Declares: `coverage_view`, `VIEW_MAX_GROUPS`, `VIEW_VERSION`. (The plan names this module
`services/coverage.py`; that name is taken by the import-coverage builder.) Read-only; it writes no
event, table or file.

Invariants:
- A cell holds three integers (own rows, copied rows, works) and never a value; no number or rank
  crosses groups. Variants are not separate rows: a method is its `method_name` normalised as the
  pack does, whatever its `variant`.
- The rows are the final rows of `grouped_rows` (the grouping of the evidence report) of corpus
  works (`view_corpus.corpus_among`: PRISMA's corpus minus works an active merge absorbs, role-blind
  as PRISMA counts it), without the works a retraction notice excludes (the evidence report's
  default). Group and method totals are computed over all of them; only the lists are cut, at
  `VIEW_MAX_GROUPS` groups and `VIEW_MAX_NODES` methods, ordered by (works descending, id).
- The ideas matrix counts, per confirmed idea (ids only, no names), the rows its member works'
  live, final, non-stale contribution `result` items link by `result_row`; a row linked twice
  counts once. It is empty, with the notice `idea-links-none`, when no such link exists.
- Both variants (researcher, agent) are the same view: every source here is already what an agent
  may read (the evidence grouping, notice states, confirmed ideas, contribution items); the
  agent tool adds the pass-session and role-blind guards.
"""

from __future__ import annotations

from factory.errors import FactoryValidationError
from factory.extraction.numbers import normalise_for, normalise_text
from factory.model.views import CoverageCell, CoverageView, GroupSummary, ViewNotice
from factory.packs import FieldDef
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.contributions import final_items
from factory.services.evidence_groups import summarise
from factory.services.extraction import require_schema
from factory.services.extraction_agreement import FinalRow, GroupKey, grouped_rows
from factory.services.ideas import confirmed_ideas
from factory.services.notices import work_states
from factory.services.onion import VIEW_MAX_NODES
from factory.services.view_corpus import corpus_among, horizon_notice, search_horizon
from factory.services.views import view_meta

VIEW_VERSION = 1
VIEW_MAX_GROUPS = 200


def coverage_view(project: Project) -> CoverageView:
    """Build the coverage map (see the module docstring)."""
    with entering():
        return _build(project)


def _build(project: Project) -> CoverageView:
    project.index.sync()
    as_of = project.index.head()  # once, before any read: the view describes this position
    notices: list[ViewNotice] = []
    groups = _shown_groups(project)
    pack_method = _method_definition(project)
    cells: dict[str, dict[str, _Tally]] = {}
    row_group: dict[tuple[str, str], tuple[str, FinalRow]] = {}
    summaries: list[GroupSummary] = []
    for key, rows in groups:
        summary = summarise(key, rows)
        summaries.append(summary)
        for row in rows:
            row_group[(row.work_id, row.row_key)] = (summary.group_id, row)
            method = _method(row, pack_method)
            cells.setdefault(method, {}).setdefault(summary.group_id, _Tally()).add(row)
    notices.append(horizon_notice(search_horizon(project)))
    if not summaries:
        notices.append(
            ViewNotice(
                code="coverage-empty",
                text="No final evidence row of a corpus work exists yet; the map is empty.",
            )
        )
    summaries.sort(key=lambda s: (-s.works, s.group_id))
    methods = sorted(
        cells, key=lambda m: (-len({w for t in cells[m].values() for w in t.works}), m)
    )
    shown_groups = summaries[:VIEW_MAX_GROUPS]
    shown_methods = methods[:VIEW_MAX_NODES]
    keep = {g.group_id for g in shown_groups}
    idea_ids, idea_cells = _idea_cells(project, row_group)
    if not idea_ids:
        notices.append(
            ViewNotice(
                code="idea-links-none",
                text="No confirmed idea has a member with a result item linked to an evidence "
                "row; the ideas matrix is empty.",
            )
        )
    shown_ideas = idea_ids[:VIEW_MAX_NODES]
    truncated = (
        len(shown_groups) < len(summaries)
        or len(shown_methods) < len(methods)
        or len(shown_ideas) < len(idea_ids)
    )
    return CoverageView(
        meta=view_meta(
            project,
            "coverage",
            VIEW_VERSION,
            {
                "rows": "final evidence rows of corpus works, without notice-excluded works",
                "max_groups": VIEW_MAX_GROUPS,
                "max_methods": VIEW_MAX_NODES,
            },
            truncated=truncated,
            notices=notices,
            as_of=as_of,
        ),
        groups=shown_groups,
        methods=shown_methods,
        cells={
            m: {g: cells[m][g].cell() for g in sorted(cells[m]) if g in keep} for m in shown_methods
        },
        ideas=shown_ideas,
        idea_cells={
            i: {g: idea_cells[i][g].cell() for g in sorted(idea_cells[i]) if g in keep}
            for i in shown_ideas
        },
        total_groups=len(summaries),
        total_methods=len(methods),
        total_ideas=len(idea_ids),
    )


class _Tally:
    def __init__(self) -> None:
        self.independent = 0
        self.copied = 0
        self.works: set[str] = set()

    def add(self, row: FinalRow) -> None:
        if row.independent:
            self.independent += 1
        elif "value" in row.fields:
            self.copied += 1
        self.works.add(row.work_id)

    def cell(self) -> CoverageCell:
        return CoverageCell(independent=self.independent, copied=self.copied, works=len(self.works))


def _shown_groups(project: Project) -> list[tuple[GroupKey, list[FinalRow]]]:
    """The groups of `grouped_rows` restricted to corpus works that no notice excludes; a group
    left without rows is dropped."""
    grouped = grouped_rows(project)
    works = sorted({r.work_id for rows in grouped.groups.values() for r in rows})
    if not works:
        return []
    with project.index.connect() as conn:
        corpus = corpus_among(conn, works)
    excluded = {w for w, s in work_states(project).items() if s.synthesis == "excluded"}
    keep = corpus - excluded
    out = [
        (k, [r for r in rows if r.work_id in keep]) for k, rows in sorted(grouped.groups.items())
    ]
    return [(k, rows) for k, rows in out if rows]


def _method_definition(project: Project) -> FieldDef | None:
    try:
        _, _, pack = require_schema(project)
    except FactoryValidationError:
        return None
    return pack.field("method_name")


def _method(row: FinalRow, definition: FieldDef | None) -> str:
    field = row.fields.get("method_name")
    if field is None:
        return "(unnamed)"
    if definition is None:
        return normalise_text(str(field.value))
    return normalise_for(definition, str(field.value))


def _idea_cells(
    project: Project, row_group: dict[tuple[str, str], tuple[str, FinalRow]]
) -> tuple[list[str], dict[str, dict[str, _Tally]]]:
    """Confirmed ideas with at least one linked row, and their per-group tallies."""
    if not row_group:
        return [], {}
    links: dict[str, set[str]] = {}
    for item in final_items(project):
        if item.item_kind == "result" and item.result_row and item.live and not item.stale:
            links.setdefault(item.work_id, set()).add(item.result_row)
    if not links:
        return [], {}
    out: dict[str, dict[str, _Tally]] = {}
    for idea in confirmed_ideas(project):
        seen: set[tuple[str, str]] = set()
        for work in idea.effective_members:
            for key in sorted(links.get(work, ())):
                found = row_group.get((work, key))
                if found is None or (work, key) in seen:
                    continue
                seen.add((work, key))
                gid, row = found
                out.setdefault(idea.idea_id, {}).setdefault(gid, _Tally()).add(row)
    return sorted(out), out


__all__ = ["VIEW_MAX_GROUPS", "VIEW_VERSION", "coverage_view"]
