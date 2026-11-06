"""Findings about regions (slice 3d, plan Regions-B, task 4).

A region selects and asserts nothing about any paper, so every finding is advisory (a warning in
every rigour mode). Findings carry ids and counts only, never a name, a rule or document text.

Invariants:
- The researcher's report (the default) covers every region. In the agent view (`AGENT_VIEW`, set
  by `agent_check`) a region withheld from agents (it reaches an import's `all` part or a barred
  query purpose) is never evaluated and contributes no drift or link finding, and the drift
  totals are computed without it, so an agent reads no live count of it (decision 43).
- A project with no region and no adoption has no finding.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from factory.services.context import Project
from factory.services.region_adoption import adoption_outdated
from factory.services.regions import (
    agent_region_state,
    focus_slot_missing,
    pending_proposals,
    region_ids,
    region_state,
    region_withheld,
    subregion_violations,
)

__all__ = ["AGENT_VIEW", "RegionFinding", "region_findings"]

AGENT_VIEW: ContextVar[bool] = ContextVar("region_check_agent_view", default=False)


@dataclass(frozen=True)
class RegionFinding:
    code: str
    refs: tuple[str, ...]
    message: str


def region_findings(project: Project) -> list[RegionFinding]:
    """The region findings in report order: unreviewed, drift, subregion violations, foci whose
    slot the question dropped, open member proposals. Outdated adoptions come first."""
    ids = region_ids(project)
    found: list[RegionFinding] = []
    outdated = adoption_outdated(project)
    if outdated:
        found.append(
            RegionFinding(
                "region-adoption-outdated",
                tuple(adopted for adopted, _ in outdated),
                f"{len(outdated)} adopted region version(s) have a newer reviewed version "
                "in their source project",
            )
        )
    if not ids:
        return found
    agent = AGENT_VIEW.get()
    states = [
        agent_region_state(project, rid) if agent else region_state(project, rid) for rid in ids
    ]
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
    withheld = {rid for rid in ids if region_withheld(project, rid)} if agent else set()
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
