"""Review fixes of M-D: a version's result survives a newer listing, the independence of the
sessions across versions, agent admission, and the sample floor."""

# ruff: noqa: F811, F401
from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import MinerRegime, spec_to_json
from factory.model.screening import Channel, PassLabel
from factory.services.check import check
from factory.services.context import Project
from factory.services.methods import methods_report, render_methods
from factory.services.miner_gold import label_miner_calibration
from factory.services.miner_report import miner_calibration_report
from factory.services.miners import (
    MinerState,
    draw_miner_calibration,
    miner_state,
    retire_miner,
)
from factory.services.mining import mine_next, mine_record, register_miner
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening import relayed_extraction_label
from tests.extraction_helpers import (
    _both,
    _new_document_version,
    ext_a,
    ext_b,
    screened,
    world,
)
from tests.miner_calibration_helpers import (
    JUDGE,
    PROPOSER,
    calibrated_world,
    run_calibration,
)
from tests.miner_helpers import VISION_NAME, mine_pass, mine_row, miner_actor, use

SESSION_X = "01JZ9Q3K5M7N8P0R2S4T6V8W2A"
SESSION_Y = "01JZ9Q3K5M7N8P0R2S4T6V8W2B"
A, B = PassLabel.A, PassLabel.B


def _list(project: Project, actor: Actor, spec: object) -> None:
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        actor,
        current.spec.model_copy(update={"miners": (use(spec),)}),  # type: ignore[arg-type]
        reason="list the next version",
        semantic=True,
        effects={},
    )


def _v2(project: Project, agent: Actor, spec: object) -> object:
    v2 = replace(spec, version=2)  # type: ignore[type-var]
    register_miner(project, PROPOSER, spec_to_json(v2))
    _list(project, agent, v2)
    return v2


# --- 1: a version's result is its own ---


def test_listing_a_new_version_keeps_the_failed_result(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    run_calibration(project, miss=tuple(cal.works[:2]))
    assert miner_state(project, VISION_NAME, 1) is MinerState.FAILED
    _v2(project, agent, cal.spec)
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.closed == 5 and report.passed is False
    assert report.score is not None and report.score.recall == pytest.approx(0.6)
    assert miner_state(project, VISION_NAME, 1) is MinerState.FAILED
    codes = [f.code for f in check(project).findings]
    assert codes.count("miner-calibration-failed") == 1
    [one, two] = methods_report(project).miners
    assert (one.version, one.state, one.calibration) == (1, "failed", "failed")
    assert one.recall == pytest.approx(0.6) and two.version == 2


def test_a_calibrated_version_stays_calibrated_when_its_rows_go_stale(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    run_calibration(project)
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED
    _new_document_version(project, cal.works[0])  # a new conversion of a calibrated unit
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.passed is True


def test_a_retired_version_is_not_admitted_in_methods(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    _admit_evidence(project, human)
    retire_miner(project, agent, VISION_NAME, 1, "replaced")
    entry = methods_report(project).miners[0]
    assert entry.evidence is False
    assert "Admitted as evidence." not in render_methods(methods_report(project))


def _admit_evidence(project: Project, actor: Actor) -> None:
    current = current_protocol(project)
    assert current is not None
    uses = tuple(u.model_copy(update={"evidence": True}) for u in current.spec.miners or ())
    amend_protocol(
        project,
        actor,
        current.spec.model_copy(update={"miners": uses}),
        reason="admit the miner as evidence",
        semantic=True,
        effects={},
    )


# --- 2: gold relayers and judges across versions ---


def _relay_gold(project: Project, human: Actor, cal_id: str, work: str, session: str) -> None:
    relay = human.model_copy(update={"session": session})
    label_miner_calibration(project, relay, cal_id, work, [mine_row()], channel=Channel.MCP)


def test_a_gold_relay_is_an_extraction_label_relay(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    assert not relayed_extraction_label(project, SESSION_X)
    _relay_gold(project, human, cal.calibration_id, cal.works[0], SESSION_X)
    assert relayed_extraction_label(project, SESSION_X)


def test_a_gold_relayer_cannot_mine_or_judge_any_version(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    _relay_gold(project, human, cal.calibration_id, cal.works[0], SESSION_X)
    relayer = miner_actor(SESSION_X, "claude-haiku-5")
    with pytest.raises(FactoryValidationError):
        mine_next(project, relayer, VISION_NAME, 1, A)  # production of the same version
    _v2(project, agent, cal.spec)
    with pytest.raises(FactoryValidationError):
        mine_next(project, relayer, VISION_NAME, 2, A)  # production of the next version
    draw_miner_calibration(project, human, VISION_NAME, 2, random_seed=11)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, relayer, VISION_NAME, 2, A, calibration=True)  # judging the next
    assert raised.value.issues[0].field == "session"


def test_a_label_session_of_an_earlier_version_cannot_judge_or_produce_the_next(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """The independence check reads label sessions by miner name (not only this calibration)."""
    from factory.services.miner_independence import label_sessions

    cal = calibrated_world(project, agent, human)
    _relay_gold(project, human, cal.calibration_id, cal.works[0], SESSION_X)
    _v2(project, agent, cal.spec)
    assert SESSION_X in label_sessions(project, VISION_NAME)
    # the independence rules themselves (the pass join refuses the session first, so ask them)
    from factory.services.miner_independence import (
        require_calibration_pass,
        require_production_pass,
    )

    relayer = miner_actor(SESSION_X, "claude-haiku-5")
    with pytest.raises(FactoryValidationError):
        require_production_pass(project, relayer, VISION_NAME)
    draw_miner_calibration(project, human, VISION_NAME, 2, random_seed=11)
    with pytest.raises(FactoryValidationError):
        require_calibration_pass(project, relayer, VISION_NAME, 2, A)


def test_a_judge_may_share_a_model_with_pass_b_in_either_order(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    producer_a = miner_actor(SESSION_Y, "claude-haiku-5")
    producer_b = miner_actor(SESSION_X, JUDGE.model or "")  # the judge's model, pass B first
    mine_next(project, producer_a, VISION_NAME, 1, A)
    mine_next(project, producer_b, VISION_NAME, 1, B)
    batch = mine_next(project, JUDGE, VISION_NAME, 1, A, calibration=True).batch
    assert batch is not None


def test_a_released_calibration_claim_still_marks_the_session(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    from factory.services.miner_independence import calibration_sessions
    from factory.services.tasks import release_task

    calibrated_world(project, agent, human)
    batch = mine_next(project, JUDGE, VISION_NAME, 1, A, calibration=True).batch
    assert batch is not None
    release_task(project, JUDGE, batch.task_id, "stepping away")
    assert JUDGE.session in calibration_sessions(project, VISION_NAME)
    with pytest.raises(FactoryValidationError):
        mine_next(project, JUDGE, VISION_NAME, 1, A)  # still no production for the judge
