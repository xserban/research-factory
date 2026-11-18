"""Reopen one mined unit after a selector miss (IDEA-99).

A unit completed under a miner version whose selection served too little of the paper (the
selector's headings matched under `SELECTION_FALLBACK_BELOW` of the paragraph words, and the task
was created before the fallback existed) is mined again under the same version. `reopen_unit`
records `mine.reopened`; nothing else changes. The extraction ledger then reads the unit as stale
with reason `reopened`, `mine_next` creates a fresh task of the same version (its selection goes
through `select_with_fallback`), and the rows the unit held are stale, so the fresh task's rows
replace them in every final view (`stale_extractions`), with no `supersedes` to pass.

Invariants:
- The researcher's act: a human actor (an agent relays it over MCP with the human actor); any other
  actor is refused on `actor`, with nothing written.
- The guard: the unit's latest task is a completed, closed task of that miner version, it did not
  already fall back, its selector can fall back (heading patterns; element kinds empty or
  including PARAGRAPH), and the share of paragraph words its heading patterns matched is under
  `SELECTION_FALLBACK_BELOW`. The share is the one recorded on the task, or, for a task created
  before it was recorded, `heading_share` of the selector over its pinned conversion's manifest.
- A unit reopened and not yet completed again is refused.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.mining.select import SELECTION_FALLBACK_BELOW, can_fall_back, heading_share
from factory.mining.spec import Selector
from factory.model.extraction import MinerScope
from factory.model.mine_reopen import MAX_REASON, MineReopened
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.extraction import MineBatchContent, scope_ledger
from factory.services.mining import registered_miner, registered_row
from factory.services.work_ref import resolve_work_id

__all__ = ["reopen_unit", "served_share"]


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def served_share(project: Project, content: MineBatchContent, selector: Selector) -> float | None:
    """The share of paragraph words the task's selector matched: the recorded
    `selection_matched_share`, else (a task created before it was recorded) `heading_share` of the
    miner's selector over the task's pinned conversion. The old task's stored anchors are not used:
    for a selector of tables or cells they are not paragraphs, so their paragraph share says
    nothing about the heading match, while the selector's patterns over the pinned manifest give
    the very number `select_with_fallback` would compute. None when the selector has no patterns
    or the document has no paragraph words. Read-only."""
    if content.selection_matched_share is not None:
        return content.selection_matched_share
    manifest = conversion_manifest(project, content.records[0]["conversion_id"])
    return heading_share(manifest, selector)


def reopen_unit(
    project: Project,
    actor: Actor,
    name: str,
    version: int,
    work_id: str,
    pass_label: PassLabel,
    reason: str,
) -> str:
    """Record `mine.reopened` for the unit (`work_id`, `pass_label`) of miner `(name, version)` and
    return its event id. Refused (`FactoryValidationError`, nothing written): on `actor` unless
    human; on `reason` when blank or over `MAX_REASON`; on `miner` for an unregistered version;
    on `work_id` when the unit has no completed, closed task of that version as its latest, the
    task already served every section (`selection_fallback`), its selector never falls back
    (no heading patterns, or element kinds without paragraphs), its headings
    matched `SELECTION_FALLBACK_BELOW` of the paragraph words or more (or the document has
    none), or the unit is already reopened and not yet completed again."""
    if actor.kind != "human":
        raise _refuse("actor", "reopening a mined work is the researcher's act; an agent relays it")
    if not reason.strip():
        raise _refuse("reason", "give the reason the work is mined again")
    if len(reason) > MAX_REASON:
        raise _refuse("reason", f"at most {MAX_REASON} characters")
    with project.index.exclusive():
        project.index.sync()
        spec = registered_miner(project, name, version)
        if registered_row(project, name, version) is None or spec is None:
            raise _refuse("miner", f"miner {name} version {version} is not registered")
        work_id = resolve_work_id(project, work_id)
        ledger = scope_ledger(project, MinerScope(name))
        tasks = ledger.tasks.get((work_id, pass_label), [])
        latest = tasks[-1] if tasks else None
        if latest is None or latest.status != "completed":
            raise _refuse(
                "work_id",
                f"no completed task of {name} for this work in pass {pass_label.value}"
                + ("" if latest is None else " (its latest task is not completed)"),
            )
        content = latest.content
        if not isinstance(content, MineBatchContent) or content.version != version:
            raise _refuse(
                "work_id",
                f"the unit's latest task is not a task of {name} version {version}",
            )
        with project.index.connect() as conn:
            closure = conn.execute(
                text("SELECT event_id FROM extraction_closures WHERE task_id = :t"),
                {"t": latest.task_id},
            ).first()
        if closure is None:
            raise _refuse("work_id", "the unit's latest task has no closing event")
        if any(when > str(closure[0]) for when in ledger.reopenings.get((work_id, pass_label), [])):
            raise _refuse("work_id", "this unit is already reopened and not yet completed again")
        if content.selection_fallback:
            raise _refuse("work_id", "the task already served every section (selection fallback)")
        if not can_fall_back(spec.selector):
            raise _refuse(
                "work_id",
                "the miner's selector never falls back (no heading patterns, or element kinds "
                "without paragraphs); a re-mine would serve the same selection",
            )
        share = served_share(project, content, spec.selector)
        if share is None:
            raise _refuse("work_id", "the document has no paragraph words; nothing was missed")
        if share >= SELECTION_FALLBACK_BELOW:
            raise _refuse(
                "work_id",
                f"the selection served {share:.1%} of the paragraph words, not under "
                f"{SELECTION_FALLBACK_BELOW:.0%}; a selector miss is not shown",
            )
        payload = MineReopened(
            miner=name,
            version=version,
            work_id=work_id,
            pass_label=pass_label,
            task_id=latest.task_id,
            reason=reason,
        )
        event = project.events.make("mine.reopened", payload, actor)
        project.record([event])
    return event.id
