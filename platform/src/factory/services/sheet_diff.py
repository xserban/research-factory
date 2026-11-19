"""Living sheets (spar night N7): when a sheet is stale, and what a re-spar changed.

Everything here is computed from the folded rows and the papers as they are now; nothing writes
an event and nothing calls a model. The researcher decides what to do with it (ruling 8).

Invariants:
- `sheet_staleness`: a sheet is stale when its selection now resolves to another digest (papers
  added or removed, or their stored text changed) or when the claims rows served for a paper of
  the selection differ from those served when the sheet opened (`sheets.claims_fingerprint`,
  recorded in `sheet.opened`). A sheet opened before the fingerprint existed has its claims left
  unchecked (`claims_checked` False), never called stale on a guess. An unresolvable selection
  gives `stale` None with the reason.
- `sheet_diff`: arguments are matched by (stance, work, anchor); equal keys pair in the order
  written, so the rest are added or dropped. A kept argument carries the old researcher rating
  only as `suggested_rating`: a suggestion shown beside the new, still unrated argument. No
  function here writes a rating; accepting a suggestion is the researcher's own act, posted
  through the ordinary rating route as a human.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.sheets import SHEET_ID_RE
from factory.services import sheets as sheets_service
from factory.services.context import Project
from factory.services.selection import resolve_selection_cached

__all__ = [
    "SUGGESTION_LABEL",
    "KeptArgument",
    "SheetDiff",
    "Staleness",
    "sheet_diff",
    "sheet_staleness",
]

SUGGESTION_LABEL = (
    "Suggested from the earlier sheet; not a rating. The earlier rating is shown beside the "
    "matching argument. Nothing is written until you accept it, argument by argument."
)


@dataclass(frozen=True)
class Staleness:
    stale: bool | None
    """True, False, or None when the selection cannot be resolved."""
    reasons: tuple[str, ...]
    works_added: tuple[str, ...]
    works_removed: tuple[str, ...]
    rows_changed: tuple[str, ...]
    """Works whose served claims rows differ from those at opening."""
    claims_checked: bool
    """False when the sheet recorded no claims fingerprint (an older sheet)."""


@dataclass(frozen=True)
class KeptArgument:
    old: sheets_service.ArgumentView
    new: sheets_service.ArgumentView
    suggested_rating: str | None
    suggested_note: str | None


@dataclass(frozen=True)
class SheetDiff:
    old_id: str
    new_id: str
    added: tuple[sheets_service.ArgumentView, ...]
    dropped: tuple[sheets_service.ArgumentView, ...]
    kept: tuple[KeptArgument, ...]
    suggestion_label: str = SUGGESTION_LABEL

    @property
    def counts(self) -> dict[str, int]:
        return {"added": len(self.added), "dropped": len(self.dropped), "kept": len(self.kept)}


def _issue(field_name: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, message)])


def _row(project: Project, sheet_id: str) -> dict[str, Any]:
    import re

    if re.fullmatch(SHEET_ID_RE, sheet_id) is None:
        raise _issue("sheet_id", f"{sheet_id}: not a sheet id")
    project.index.sync()
    row = sheets_service._sheet_row(project, sheet_id)
    if row is None:
        raise _issue("sheet_id", f"{sheet_id}: no such sheet")
    return row


def sheet_staleness(project: Project, sheet_id: str) -> Staleness:
    """Whether `sheet_id` no longer matches today's papers and claims, and why (see the module
    invariants). Read-only; refuses an unknown sheet."""
    row = _row(project, sheet_id)
    try:
        spec = sheets_service._spec_of(json.loads(row["selection"]))
        current = resolve_selection_cached(project, spec)
    except (FactoryValidationError, ValueError):
        return Staleness(
            None, ("the selection can no longer be resolved",), (), (), (), claims_checked=False
        )
    with project.index.connect() as conn:
        stored = {
            str(w)
            for (w,) in conn.execute(
                text("SELECT work_id FROM sheet_candidates WHERE sheet_id = :s"), {"s": sheet_id}
            ).all()
        }
    now = {w.work_id for w in current.works}
    added, removed = tuple(sorted(now - stored)), tuple(sorted(stored - now))
    reasons: list[str] = []
    if added:
        reasons.append(f"{len(added)} paper(s) added to the selection since the sheet opened")
    if removed:
        reasons.append(f"{len(removed)} paper(s) removed from the selection since it opened")
    if current.digest != row["selection_digest"] and not (added or removed):
        reasons.append("the selection digest changed (the papers' stored text or settings)")
    changed: tuple[str, ...] = ()
    checked = row["claims_fingerprint"] is not None
    if checked:
        was: dict[str, str] = json.loads(row["claims_fingerprint"])
        kept = [w for w in sorted(was) if w in now]
        fresh = sheets_service.claims_fingerprint(project, kept)
        changed = tuple(w for w in kept if fresh[w] != was[w])
        if changed:
            reasons.append(f"claims rows changed for {len(changed)} paper(s) since it opened")
    return Staleness(bool(reasons), tuple(reasons), added, removed, changed, checked)


def sheet_diff(project: Project, old_id: str, new_id: str) -> SheetDiff:
    """The arguments of `new_id` against those of `old_id`: added, dropped and kept (see the
    module invariants). Read-only; refuses an unknown sheet."""
    _row(project, old_id)
    _row(project, new_id)
    old = sheets_service.view_sheet(project, old_id).arguments
    new = sheets_service.view_sheet(project, new_id).arguments
    waiting: dict[tuple[str, str, str], list[sheets_service.ArgumentView]] = {}
    for a in old:
        waiting.setdefault((a.stance, a.work_id, a.anchor), []).append(a)
    added: list[sheets_service.ArgumentView] = []
    kept: list[KeptArgument] = []
    for a in new:
        matches = waiting.get((a.stance, a.work_id, a.anchor))
        if matches:
            before = matches.pop(0)
            kept.append(KeptArgument(before, a, before.rating, before.rating_note or None))
        else:
            added.append(a)
    dropped = [a for a in old if any(a is m for ms in waiting.values() for m in ms)]
    return SheetDiff(old_id, new_id, tuple(added), tuple(dropped), tuple(kept))
