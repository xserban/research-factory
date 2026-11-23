"""Tier plans (plan 2026-11-20-tiers-and-autonomy, contract C3).

A tier fixes the plan of stages, the caps, the limits and the protocol and report templates of a
study. Pure data: nothing here runs a stage, calls a model or writes an event.
"""

from __future__ import annotations

from factory.tiers.model import (
    Limits,
    ProtocolTemplate,
    ReportTemplate,
    StagePlan,
    TierPlan,
)
from factory.tiers.resolve import plan_for, report_label, skipped_steps

__all__ = [
    "Limits",
    "ProtocolTemplate",
    "ReportTemplate",
    "StagePlan",
    "TierPlan",
    "plan_for",
    "report_label",
    "skipped_steps",
]
