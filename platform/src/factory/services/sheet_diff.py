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
- `sheet_diff`: arguments are matched by (stance, work, anchor); within one key, arguments with
  an equal quote (whitespace and case normalised) pair first, then the rest in the order written,
  so what is left is added or dropped. A kept pair carries both the old and the new claim and
  quote. Only a pair with an equal quote carries the old researcher rating as `suggested_rating`
  (a suggestion beside the new, still unrated argument). A pair whose quote differs is `changed`
  ("changed at the same place"): the old rating is `old_rating`, context only, never a
  suggestion. No function here writes a rating; accepting a suggestion is the researcher's own
  act, posted through the ordinary rating route as a human.
- The claims fingerprint hashes, per work, the served row keys, their versions and the quote
  text of each row (a row key is content-addressed only for keyed packs, so the quote text is
  added to catch an edited row under an unchanged key).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.sheets import SHEET_ID_RE
from factory.services import sheets as sheets_service
from factory.services.context import Project
from factory.services.selection import event_log_signature, resolve_selection_cached

__all__ = [
    "SUGGESTION_LABEL",
    "KeptArgument",
    "SheetDiff",
    "Staleness",
    "clear_staleness_cache",
    "sheet_diff",
    "sheet_staleness",
]

SUGGESTION_LABEL = (
    "Suggested from the earlier sheet; not a rating. The earlier rating is shown beside the "
    "matching argument. Nothing is written until you accept it, argument by argument."
)


_STALE_LOCK = threading.Lock()
_STALE_CACHE: dict[tuple[str, str], tuple[tuple[int, float], Staleness]] = {}


def clear_staleness_cache() -> None:
    """Forget every memoised staleness (tests; a change made without an event)."""
    with _STALE_LOCK:
        _STALE_CACHE.clear()


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
    changed: bool = False
    """True when the quote differs from the old one: no suggestion, `old_rating` is context."""
    old_rating: str | None = None
    old_note: str | None = None


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
    invariants). Read-only; refuses an unknown sheet. Memoised per (event-log signature, sheet),
    as `resolve_selection_cached` is: a page view without a new event recomputes nothing."""
    row = _row(project, sheet_id)
    key = (str(project.paths.dir), sheet_id)
    signature = event_log_signature(project)
    with _STALE_LOCK:
        hit = _STALE_CACHE.get(key)
    if hit is not None and hit[0] == signature:
        return hit[1]
    result = _staleness(project, sheet_id, row)
    with _STALE_LOCK:
        _STALE_CACHE.pop(key, None)
        _STALE_CACHE[key] = (signature, result)
        while len(_STALE_CACHE) > 64:
            del _STALE_CACHE[next(iter(_STALE_CACHE))]
    return result


def _staleness(project: Project, sheet_id: str, row: dict[str, Any]) -> Staleness:
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
    paired: dict[int, sheets_service.ArgumentView] = {}
    for i, a in enumerate(new):  # first pass: an equal quote
        pool = waiting.get((a.stance, a.work_id, a.anchor), [])
        same = next((m for m in pool if _norm(m.quote) == _norm(a.quote)), None)
        if same is not None:
            pool.remove(same)
            paired[i] = same
    for i, a in enumerate(new):  # second pass: what is left at the same place, in order
        pool = waiting.get((a.stance, a.work_id, a.anchor), [])
        if i not in paired and pool:
            paired[i] = pool.pop(0)
    added: list[sheets_service.ArgumentView] = []
    kept: list[KeptArgument] = []
    for i, a in enumerate(new):
        before = paired.get(i)
        if before is None:
            added.append(a)
            continue
        same_quote = _norm(before.quote) == _norm(a.quote)
        kept.append(
            KeptArgument(
                before,
                a,
                before.rating if same_quote else None,
                (before.rating_note or None) if same_quote else None,
                changed=not same_quote,
                old_rating=before.rating,
                old_note=before.rating_note or None,
            )
        )
    dropped = [a for a in old if any(a is m for ms in waiting.values() for m in ms)]
    return SheetDiff(old_id, new_id, tuple(added), tuple(dropped), tuple(kept))


def _norm(quote: str) -> str:
    return " ".join(quote.split()).casefold()
