"""A calibration freezes once every unit is labelled and closed (M-D, ruling 16; R-52)."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import spec_to_json
from factory.model.screening import Channel, PassLabel
from factory.services.check import check
from factory.services.context import Project
from factory.services.methods import methods_report
from factory.services.miner_gold import calibration_frozen, label_miner_calibration
from factory.services.miner_report import miner_calibration_report
from factory.services.miners import MinerState, calibration_of, miner_state
from factory.services.mining import mine_next, register_miner
from factory.services.protocol import amend_protocol, current_protocol
from tests.extraction_helpers import (  # noqa: F401
    _both,
    _new_document_version,
    ext_a,
    ext_b,
    screened,
    world,
)
from tests.miner_calibration_helpers import JUDGE, PROPOSER, calibrated_world, run_calibration
from tests.miner_helpers import VISION_NAME, mine_row, use

A = PassLabel.A


def _failed(project: Project, agent: Actor, human: Actor):  # type: ignore[no-untyped-def]
    cal = calibrated_world(project, agent, human)
    run_calibration(project, miss=tuple(cal.works[:2]))
    assert miner_state(project, VISION_NAME, 1) is MinerState.FAILED
    return cal


def _list(project: Project, actor: Actor, spec: object) -> None:
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        actor,
        current.spec.model_copy(update={"miners": (use(spec),)}),  # type: ignore[arg-type]
        reason="list a version",
        semantic=True,
        effects={},
    )


def _still_failed(project: Project) -> None:
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.passed is False and report.closed == 5
    assert report.score is not None and report.score.recall == pytest.approx(0.6)
    assert miner_state(project, VISION_NAME, 1) is MinerState.FAILED
    assert [f.code for f in check(project).findings].count("miner-calibration-failed") == 1
    assert methods_report(project).miners[0].calibration == "failed"


def test_relisting_the_failed_version_does_not_reopen_its_calibration(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = _failed(project, agent, human)
    v2 = replace(cal.spec, version=2)
    register_miner(project, PROPOSER, spec_to_json(v2))
    _list(project, agent, v2)
    _list(project, agent, cal.spec)  # an agent lists version 1 again
    run_calibration(project)  # the judge tries again, now with every record
    batch = mine_next(project, JUDGE, VISION_NAME, 1, A, calibration=True).batch
    assert batch is None
    _still_failed(project)


def test_a_new_document_version_does_not_reopen_a_scored_calibration(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = _failed(project, agent, human)
    _new_document_version(project, cal.works[0])
    assert mine_next(project, JUDGE, VISION_NAME, 1, A, calibration=True).batch is None
    _still_failed(project)


def test_a_passed_version_is_not_served_again_after_a_new_document_version(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    run_calibration(project)
    _new_document_version(project, cal.works[0])
    assert mine_next(project, JUDGE, VISION_NAME, 1, A, calibration=True).batch is None
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED


def test_a_gold_relabel_after_scoring_is_refused(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = _failed(project, agent, human)
    frozen = calibration_of(project, VISION_NAME, 1)
    assert frozen is not None and calibration_frozen(project, frozen)
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(
            project,
            human,
            cal.calibration_id,
            cal.works[0],
            [mine_row("lower")],
            channel=Channel.CLI,
        )
    assert raised.value.issues[0].field == "calibration"
    _still_failed(project)


def test_labelling_stays_open_until_every_unit_is_labelled_and_closed(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    stored = calibration_of(project, VISION_NAME, 1)
    assert stored is not None and not calibration_frozen(project, stored)
    label_miner_calibration(  # a relabel before the pass has finished is still allowed
        project, human, cal.calibration_id, cal.works[0], [mine_row("lower")], channel=Channel.CLI
    )
    run_calibration(project)
    assert calibration_frozen(project, stored)


def test_a_failed_result_survives_every_path_and_a_rebuild(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = _failed(project, agent, human)
    v2 = replace(cal.spec, version=2)
    register_miner(project, PROPOSER, spec_to_json(v2))
    _list(project, agent, v2)
    _list(project, agent, cal.spec)
    _new_document_version(project, cal.works[1])
    run_calibration(project)
    with pytest.raises(FactoryValidationError):
        label_miner_calibration(
            project,
            human,
            cal.calibration_id,
            cal.works[1],
            [mine_row("lower")],
            channel=Channel.CLI,
        )
    _still_failed(project)
    project.index.rebuild()  # the freeze is read from the log, so a rebuild agrees
    stored = calibration_of(project, VISION_NAME, 1)
    assert stored is not None and calibration_frozen(project, stored)
    _still_failed(project)


def test_a_closed_unit_is_not_mined_again_before_the_freeze(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """One unit is still unlabelled, so the calibration is open; its closed units stay closed."""
    from factory.mining.spec import MinerRegime
    from factory.services.miners import draw_miner_calibration
    from tests.miner_helpers import list_miner, method_vision

    spec = replace(method_vision(), regime=MinerRegime(2, 5, 0.8, 0.9))
    register_miner(project, PROPOSER, spec_to_json(spec))
    list_miner(project, agent, spec)
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=11)
    for unit in drawn.units[:-1]:
        label_miner_calibration(
            project, human, drawn.calibration_id, unit.work_id, [mine_row()], channel=Channel.CLI
        )
    run_calibration(project)
    stored = calibration_of(project, VISION_NAME, 1)
    assert stored is not None and not calibration_frozen(project, stored)
    _new_document_version(project, drawn.units[0].work_id)
    assert mine_next(project, JUDGE, VISION_NAME, 1, A, calibration=True).batch is None


def test_a_scored_calibration_writes_nothing_for_a_new_session(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    from factory.events.reader import read_all
    from tests.miner_helpers import miner_actor

    _failed(project, agent, human)
    before = len(read_all(project.paths.events_dir, project.catalog))
    fresh = miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W2E", "claude-haiku-5")
    assert mine_next(project, fresh, VISION_NAME, 1, A, calibration=True).batch is None
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
