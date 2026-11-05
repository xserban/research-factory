"""Scoring a calibration pass against gold, and the miner state it decides (M-D, task 5)."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.events.envelope import Actor
from factory.mining.compile import compile_miner
from factory.mining.score import score
from factory.mining.spec import MinerRegime
from factory.model.extraction import FieldInput, StoredField
from factory.model.miner_calibration import GoldRow
from factory.model.screening import Channel, PassLabel
from factory.services.check import check
from factory.services.context import Project
from factory.services.miner_gold import label_miner_calibration
from factory.services.miner_report import miner_calibration_report
from factory.services.miners import (
    MinerState,
    draw_miner_calibration,
    miner_state,
    retire_miner,
)
from factory.services.mining import mine_next, mine_record, register_miner
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import (
    VISION_NAME,
    list_miner,
    method_vision,
    mine_row,
    miner_actor,
    vision_result,
)

A = PassLabel.A
PACK = compile_miner(vision_result())
SESSION_C = "01JZ9Q3K5M7N8P0R2S4T6V8W1G"
SESSION_P = "01JZ9Q3K5M7N8P0R2S4T6V8W1J"


def _field(value: str, **over: object) -> StoredField:
    base: dict[str, object] = {"value": value, "quote": value, "copy_marker": False}
    base.update(over)
    return StoredField.model_validate(base)


def _row(key: str, metric: str = "Lorem", value: str = "1", direction: str = "higher") -> GoldRow:
    return GoldRow(
        row_key=key,
        fields={
            "metric": _field(metric),
            "value": _field(value, canonical=value),
            "direction": _field(direction),
        },
    )


GOLD = {"w1": (_row("rk_000000000001"),), "w2": (_row("rk_000000000002", "Ipsum", "2"),)}


def test_perfect_agent_scores_one() -> None:
    result = score(GOLD, GOLD, PACK)
    assert (result.recall, result.field_agreement, result.precision) == (1.0, 1.0, 1.0)
    assert (result.gold_rows, result.agent_rows, result.matched) == (2, 2, 2)


def test_missing_row_lowers_recall() -> None:
    result = score(GOLD, {"w1": GOLD["w1"]}, PACK)
    assert result.recall == 0.5 and result.field_agreement == 1.0 and result.precision == 1.0


def test_value_mismatch_lowers_agreement() -> None:
    agent = {"w1": (_row("rk_000000000001", direction="lower"),), "w2": GOLD["w2"]}
    result = score(GOLD, agent, PACK)
    assert result.recall == 1.0
    assert result.field_agreement == pytest.approx(5 / 6)  # 3 compared fields x 2 rows, 1 differs


def test_omitted_field_disagrees() -> None:
    thin = GoldRow(row_key="rk_000000000001", fields={"metric": _field("Lorem")})
    result = score({"w1": GOLD["w1"]}, {"w1": (thin,)}, PACK)
    assert result.field_agreement == pytest.approx(1 / 3)


def test_extra_row_lowers_precision_only() -> None:
    extra = (*GOLD["w1"], _row("rk_00000000000f", "Other", "9"))
    result = score(GOLD, {"w1": extra, "w2": GOLD["w2"]}, PACK)
    assert result.recall == 1.0 and result.field_agreement == 1.0
    assert result.precision == pytest.approx(2 / 3)


@pytest.mark.parametrize("field_name", ["metric", "value", "direction"])
def test_a_single_gold_mutation_moves_the_score(field_name: str) -> None:
    """Scores are computed, never typed: changing one gold value changes the score."""
    base = score(GOLD, GOLD, PACK).field_agreement
    row = GOLD["w1"][0]
    fields = dict(row.fields)
    fields[field_name] = _field("changed", canonical="7" if field_name == "value" else None)
    mutated = {**GOLD, "w1": (GoldRow(row_key=row.row_key, fields=fields),)}
    assert score(mutated, GOLD, PACK).field_agreement != base


def test_empty_denominators_are_none() -> None:
    result = score({"w1": ()}, {}, PACK)
    assert result.recall is None and result.field_agreement is None and result.precision is None
    assert result.verification_rate is None


def test_verification_rate_is_verified_over_submitted() -> None:
    assert score(GOLD, GOLD, PACK, verified=3, submitted=4).verification_rate == 0.75
    assert score(GOLD, GOLD, PACK, verified=0, submitted=0).verification_rate is None


# --- the service: report and state ---


def _calibrated_world(
    project: Project, agent: Actor, human: Actor, *, recall_min: float = 0.8
) -> tuple[str, list[str]]:
    spec = replace(method_vision(), regime=MinerRegime(2, 5, recall_min, 0.9))
    register_miner(project, miner_actor(SESSION_P, "claude-opus-5-5"), spec_dict(spec))
    list_miner(project, agent, spec)
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=11)
    works = [u.work_id for u in drawn.units]
    for work in works:
        label_miner_calibration(
            project, human, drawn.calibration_id, work, [mine_row()], channel=Channel.CLI
        )
    return drawn.calibration_id, works


def spec_dict(spec: object) -> object:
    from factory.mining.spec import spec_to_json

    return spec_to_json(spec)  # type: ignore[arg-type]


def _run(project: Project, rows_for: dict[str, list]) -> None:  # type: ignore[type-arg]
    judge = miner_actor(SESSION_C, "claude-sonnet-5-5")
    for _ in range(20):
        batch = mine_next(project, judge, VISION_NAME, 1, A, calibration=True).batch
        if batch is None:
            return
        rows = rows_for.get(batch.records[0]["work_id"], [mine_row()])
        mine_record(
            project, judge, batch.task_id, rows, finish=True, reason=None if rows else "none"
        )


def test_state_follows_the_calibration(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _calibrated_world(project, agent, human)
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATING
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.score is None and report.passed is None
    assert (report.units, report.labelled, report.closed) == (5, 5, 0)
    _run(project, {})
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.score is not None and report.passed is True
    assert report.score.recall == 1.0 and report.score.verification_rate == 1.0
    assert cal and works


def test_score_withheld_until_complete(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    spec = replace(method_vision(), regime=MinerRegime(2, 5, 0.8, 0.9))
    register_miner(project, miner_actor(SESSION_P, "claude-opus-5-5"), spec_dict(spec))  # type: ignore[arg-type]
    list_miner(project, agent, spec)
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=11)
    works = [u.work_id for u in drawn.units]
    # one unit unlabelled: the agent finishes everything, the score still waits
    for work in works[:-1]:
        label_miner_calibration(
            project, human, drawn.calibration_id, work, [mine_row()], channel=Channel.CLI
        )
    _run(project, {})
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.score is None and report.passed is None
    assert (report.labelled, report.closed) == (4, 5)
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATING
    label_miner_calibration(
        project, human, drawn.calibration_id, works[-1], [mine_row()], channel=Channel.CLI
    )
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED


def test_state_failed_below_threshold(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _, works = _calibrated_world(project, agent, human)
    _run(project, {works[0]: [], works[1]: []})  # two of five gold records missed: recall 0.6
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.score is not None
    assert report.score.recall == pytest.approx(0.6) and report.passed is False
    assert miner_state(project, VISION_NAME, 1) is MinerState.FAILED
    retire_miner(project, agent, VISION_NAME, 1, "failed its calibration")
    assert miner_state(project, VISION_NAME, 1) is MinerState.RETIRED  # kept and reported


def test_check_reports_a_failed_miner_by_name_only(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _, works = _calibrated_world(project, agent, human)
    _run(project, {works[0]: [], works[1]: []})
    found = [f for f in check(project).findings if f.code == "miner-calibration-failed"]
    assert len(found) == 1 and found[0].severity == "warning"
    assert found[0].message == f"miner {VISION_NAME} version 1 failed its calibration"
    retire_miner(project, agent, VISION_NAME, 1, "failed")
    again = [f for f in check(project).findings if f.code == "miner-calibration-failed"]
    assert len(again) == 1  # a retired miner stays reported (R-52)


def test_check_is_silent_about_a_calibrated_miner(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _calibrated_world(project, agent, human)
    _run(project, {})
    codes = {f.code for f in check(project).findings}
    assert "miner-calibration-failed" not in codes and "miner-uncalibrated-evidence" not in codes


def test_floor_overrides_lower_declared_threshold(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """A miner that declares recall_min 0.1 still needs the pilot floor of 0.8."""
    _, works = _calibrated_world(project, agent, human, recall_min=0.1)
    _run(project, {works[0]: [], works[1]: []})
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.thresholds == (0.8, 0.9)
    assert report.score is not None and report.score.recall == pytest.approx(0.6)
    assert report.passed is False


def test_report_replays(project: Project, agent: Actor, human: Actor, world: list[str]) -> None:
    _calibrated_world(project, agent, human)
    _run(project, {})
    before = miner_calibration_report(project, VISION_NAME, 1)
    project.index.rebuild()
    assert miner_calibration_report(project, VISION_NAME, 1) == before


_ = FieldInput
