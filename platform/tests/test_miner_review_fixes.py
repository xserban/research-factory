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
