"""Baseline reproduction verdicts (slice 6, plan XP-A task 6). Stub until task 6 fills it: no
verdict exists yet, so every baseline is `pending`."""

from __future__ import annotations

from typing import Literal

from factory.services.context import Project

Verdict = Literal["reproduced", "not-reproduced", "accepted", "pending"]


def baseline_verdicts(project: Project, experiment_id: str) -> dict[str, Verdict]:
    return {}
