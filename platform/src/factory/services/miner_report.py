"""The calibration report of a miner version, computed on read (slice M ruling 16; R-05).

Invariants:
- Nothing is stored: the score is a function of the gold labels, the calibration pass's rows and
  the pack; the thresholds are the declared ones raised to the platform floors of the project's
  rigor mode.
- The score reads the calibration's own tasks and rows, never the schema the miner is listed under
  now and never staleness: a version's result is fixed once every unit is labelled and closed.
- A score exists only when every unit of the sample is labelled and its calibration task is
  closed; before that the report counts units and nothing else.
- A sample smaller than the mode's floor (pilot 5, systematic 10) cannot pass, whatever the score:
  the draw is capped at the units left, and a population drained by production would otherwise let
  one matching unit calibrate a miner. It fails closed, and the report says why.
- A calibration with no gold row or no matched row has an undefined rate and does not pass
  (fail closed).
- The report is for the researcher (CLI, methods): no agent surface returns it.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory.events.reader import read_all
from factory.mining.calibration import SAMPLE_FLOOR, thresholds
from factory.mining.compile import compile_miner
from factory.mining.score import CalibrationScore, score
from factory.model.extraction import MinerScope
from factory.services.context import Project
from factory.services.extraction import (
    ExtractionRow,
    calibration_first_closed,
    live_rows,
)
from factory.services.gates import rigor_mode
from factory.services.miner_gold import calibration_labels
from factory.services.miners import calibration_of
from factory.services.mining import registered_miner

__all__ = ["MinerCalibrationReport", "calibration_passed", "miner_calibration_report"]


@dataclass(frozen=True)
class MinerCalibrationReport:
    calibration_id: str
    units: int
    labelled: int
    closed: int
    score: CalibrationScore | None
    thresholds: tuple[float, float]
    passed: bool | None
    reason: str | None = None
    """Why the calibration cannot pass whatever the score (a sample below the mode's floor)."""


def _submitted(project: Project, tasks: frozenset[str]) -> tuple[int, int]:
    """`(verified, submitted)` rows of the calibration pass: the rows recorded, and the rows of the
    distinct calls that recorded them or had every row rejected (each such event carries its
    call's input)."""
    verified = 0
    blobs: set[str] = set()
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.payload.get("task_id") not in tasks:
            continue
        if event.type == "extraction.recorded":
            verified += 1
        if event.type in ("extraction.recorded", "extraction.rejected") and event.input_blob:
            blobs.add(event.input_blob)
    submitted = 0
    for blob in blobs:
        body = project.blobs.get_json(blob)
        rows = body.get("rows") if isinstance(body, dict) else None
        submitted += len(rows) if isinstance(rows, list) else 0
    return verified, submitted


def miner_calibration_report(
    project: Project, name: str, version: int
) -> MinerCalibrationReport | None:
    """The report of the calibration drawn for `(name, version)`, or None when none is drawn."""
    calibration = calibration_of(project, name, version)
    spec = registered_miner(project, name, version)
    if calibration is None or spec is None:
        return None
    scope = MinerScope(name)
    labels = calibration_labels(project, calibration.calibration_id)
    first = calibration_first_closed(project, scope, calibration.calibration_id)
    closed = len(first)
    units = len(calibration.units)
    limits = thresholds(rigor_mode(project), spec.regime)
    floor = SAMPLE_FLOOR[rigor_mode(project)]
    short = (
        f"the sample holds {units} units, fewer than the {floor} units the floor requires"
        if units < floor
        else None
    )
    complete = len(labels) == units and closed == units
    if not complete:
        return MinerCalibrationReport(
            calibration.calibration_id,
            units,
            len(labels),
            closed,
            None,
            limits,
            None if short is None else False,
            short,
        )
    tasks = frozenset(first.values())  # each unit is scored from its first closed task
    agent: dict[str, list[ExtractionRow]] = {}
    for row in live_rows(project, scope=scope, calibration=True):
        if row.task_id in tasks:
            agent.setdefault(row.work_id, []).append(row)
    verified, submitted = _submitted(project, tasks)
    result = score(labels, agent, compile_miner(spec), verified=verified, submitted=submitted)
    passed = (
        short is None
        and result.recall is not None
        and result.field_agreement is not None
        and result.recall >= limits[0]
        and result.field_agreement >= limits[1]
    )
    return MinerCalibrationReport(
        calibration.calibration_id, units, len(labels), closed, result, limits, passed, short
    )


def calibration_passed(project: Project, name: str, version: int) -> bool | None:
    """Whether the version's calibration passed: None while it is incomplete or not drawn."""
    report = miner_calibration_report(project, name, version)
    return None if report is None else report.passed
