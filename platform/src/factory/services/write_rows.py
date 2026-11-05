"""The final evidence rows a draft may rest on, by group (slice 7b, plan W-A).

Declares: `VisibleRows`, `visible_rows_by_group`. A reader of the index; it writes nothing.

Invariants:
- The rows are those the views count (`view_rows.visible_groups`): rows of corpus works that no
  retraction notice excludes, a row of a merge-absorbed work read as its primary. Ungrouped rows
  (a missing comparability key) are kept apart under no group id.
- `groups[gid]` equals the visible rows of the evidence report's group `gid`; a group with no
  visible row is absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from factory.services.call_memo import memoised
from factory.services.context import Project
from factory.services.evidence_report import group_id
from factory.services.extraction_agreement import FinalRow, GroupKey, grouped_rows
from factory.services.view_rows import visible_groups


@dataclass(frozen=True)
class VisibleRows:
    groups: dict[str, tuple[GroupKey, list[FinalRow]]] = field(default_factory=dict)
    ungrouped: list[FinalRow] = field(default_factory=list)

    def row(self, row_key: str) -> tuple[FinalRow, str | None] | None:
        """The visible final row with this key and its group id (None when ungrouped)."""
        for gid, (_, rows) in self.groups.items():
            for r in rows:
                if r.row_key == row_key:
                    return r, gid
        for r in self.ungrouped:
            if r.row_key == row_key:
                return r, None
        return None


@memoised
def visible_rows_by_group(project: Project) -> VisibleRows:
    project.index.sync()
    grouped = grouped_rows(project)
    shown, _, _ = visible_groups(project, list(grouped.groups.items()))
    loose, _, _ = visible_groups(project, [((), list(grouped.ungrouped))])
    return VisibleRows(
        groups={group_id(key): (key, rows) for key, rows in shown},
        ungrouped=loose[0][1] if loose else [],
    )
