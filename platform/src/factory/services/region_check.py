"""Findings about regions (slice 3d, plan Regions-B, task 4).

A region selects and asserts nothing about any paper, so every finding is advisory (a warning in
every rigour mode). Findings carry ids and counts only, never a name, a rule or document text.

Invariants:
- A region withheld from agents (it reaches an import's `all` part or a barred query purpose) is
  never evaluated here and contributes no drift or link finding, so a report that an agent reads
  carries no live count of it.
- A project with no region has no finding.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory.services.context import Project
from factory.services.regions import (
    agent_region_state,
    focus_slot_missing,
    pending_proposals,
    region_ids,
    region_withheld,
    subregion_violations,
)

__all__ = ["RegionFinding", "region_findings"]


@dataclass(frozen=True)
class RegionFinding:
    code: str
    refs: tuple[str, ...]
    message: str


def region_findings(project: Project) -> list[RegionFinding]:
    """The region findings in report order: unreviewed, drift, subregion violations, foci whose
    slot the question dropped, open member proposals."""
    ids = region_ids(project)
    if not ids:
        return []
    found: list[RegionFinding] = []
    states = [agent_region_state(project, rid) for rid in ids]
    unreviewed = [s.region_id for s in states if s.review_state == "unreviewed"]
    if unreviewed:
        found.append(
            RegionFinding(
                "region-unreviewed",
                tuple(unreviewed),
                f"{len(unreviewed)} region(s) without a version a human has reviewed",
            )
        )
    drifted = [s for s in states if s.drift_added or s.drift_removed]
    if drifted:
        added = sum(s.drift_added for s in drifted)
        removed = sum(s.drift_removed for s in drifted)
        found.append(
            RegionFinding(
                "region-drift",
                tuple(s.region_id for s in drifted),
                f"{len(drifted)} region(s) have drifted from their latest version "
                f"({added} member(s) added, {removed} removed since the snapshots)",
            )
        )
    withheld = {rid for rid in ids if region_withheld(project, rid)}
    violated = [
        (link, child)
        for link, child, parent in subregion_violations(project)
        if child not in withheld and parent not in withheld
    ]
    if violated:
        found.append(
            RegionFinding(
                "region-subregion-violated",
                tuple(link for link, _ in violated),
                f"{len(violated)} subregion-of link(s) no longer hold on the latest versions",
            )
        )
    missing = focus_slot_missing(project)
    if missing:
        found.append(
            RegionFinding(
                "region-focus-slot-missing",
                tuple(missing),
                f"{len(missing)} focus region(s) name a slot the current question dropped",
            )
        )
    pending = {rid: len(pending_proposals(project, rid)) for rid in ids}
    waiting = [rid for rid, n in pending.items() if n]
    if waiting:
        found.append(
            RegionFinding(
                "region-member-proposal-pending",
                tuple(waiting),
                f"{sum(pending.values())} member proposal(s) await a human decision",
            )
        )
    return found
