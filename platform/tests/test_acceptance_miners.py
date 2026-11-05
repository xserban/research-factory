"""Acceptance of slice M plan M-D: an agent-authored miner from registration to evidence (slow).

The fixture is the pilot-shaped synthetic world of the miner tests (twelve included works with
hand-written conversions), not pilot data: five units are calibrated, the other seven mined."""

# ruff: noqa: F811
import pytest

from factory.events.envelope import Actor
from factory.model.extraction import MinerScope
from factory.model.screening import Channel, PassLabel
from factory.services.check import check
from factory.services.context import Project
from factory.services.extraction_agreement import (
    extraction_agreement,
    final_rows,
    resolve_extraction,
)
from factory.services.extraction_audit import (
    audit_evidence,
    extraction_audit_record,
    extraction_audit_report,
    extraction_audit_sample,
)
from factory.services.methods import agent_methods, methods_report, render_methods
from factory.services.miner_report import miner_calibration_report
from factory.services.miners import MinerState, miner_state, proposer, retire_miner
from factory.services.protocol import amend_protocol, current_protocol
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_calibration_helpers import (
    PROPOSER,
    calibrated_world,
    run_calibration,
)
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    mine_pass,
    mine_row,
    miner_actor,
)

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

SCOPE = MinerScope(VISION_NAME)


def _admit(project: Project, actor: Actor) -> None:
    current = current_protocol(project)
    assert current is not None
    uses = tuple(u.model_copy(update={"evidence": True}) for u in current.spec.miners or ())
    amend_protocol(
        project,
        actor,
        current.spec.model_copy(update={"miners": uses}),
        reason="admit the calibrated miner as evidence",
        semantic=True,
        effects={},
    )


def test_vision_result_miner_end_to_end(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    # session P proposes the miner; the researcher lists it, draws and labels the sample
    cal = calibrated_world(project, agent, human)
    assert proposer(project, VISION_NAME, 1).session == PROPOSER.session
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATING
    # session C, not P, runs the calibration pass; the score passes
    run_calibration(project)
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.passed is True
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED
    # the researcher admits the miner as evidence by amendment
    _admit(project, human)
    # sessions A and B run the production passes on the units outside the sample
    worked = mine_pass(
        project, miner_actor(SESSION_M1, "claude-opus-5-5"), PassLabel.A, lambda w: [mine_row()]
    )
    assert len(worked) == len(world) - len(cal.works)
    mine_pass(
        project,
        miner_actor(SESSION_M2, "claude-sonnet-5-5"),
        PassLabel.B,
        lambda w: [mine_row("lower" if w == worked[0] else "higher")],
    )
    # the human resolves the one disagreement, then audits the agreed values
    [disputed] = extraction_agreement(project, human, scope=SCOPE).disagreements
    resolve_extraction(
        project,
        human,
        disputed.work_id,
        disputed.row_key,
        disputed.field,
        "a",
        "pass A is right",
        Channel.CLI,
        scope=SCOPE,
    )
    assert len(final_rows(project, scope=SCOPE)) == len(worked)
    drawn = extraction_audit_sample(project, human, scope=SCOPE, random_seed=3)
    for item in audit_evidence(project, human, drawn.audit_id, Channel.CLI):
        extraction_audit_record(
            project,
            human,
            drawn.audit_id,
            item.item.work_id,
            item.item.row_key,
            item.item.field,
            True,
            "",
            Channel.CLI,
        )
    audit = extraction_audit_report(project, scope=SCOPE)
    assert audit is not None and audit.labelled == len(drawn.items)
    # check shows no miner error; the statement reports the miner, its score and proposer kind
    findings = check(project).findings
    assert not [f for f in findings if f.code.startswith("miner-") and f.severity == "error"]
    assert "miner-calibration-failed" not in {f.code for f in findings}
    full = methods_report(project)
    [entry] = full.miners
    assert (entry.state, entry.proposer_kind, entry.evidence) == ("calibrated", "agent", True)
    assert entry.recall == 1.0 and entry.field_agreement == 1.0
    text = render_methods(full)
    assert f"Miner {VISION_NAME} version 1 (proposed by agent): calibrated." in text
    assert "record recall 1.000" in text and "Admitted as evidence." in text
    # the agent view reports the state and the evidence flag, never a score
    view, withheld = agent_methods(project, full)
    agent_text = render_methods(view, withheld=withheld)
    assert "calibrated" in agent_text and "record recall" not in agent_text


def test_a_failed_miner_is_retired_and_still_reported(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    run_calibration(project, miss=tuple(cal.works[:3]))  # the miner misses three gold records
    report = miner_calibration_report(project, VISION_NAME, 1)
    assert report is not None and report.passed is False
    assert miner_state(project, VISION_NAME, 1) is MinerState.FAILED
    codes = {f.code: f.severity for f in check(project).findings}
    assert codes["miner-calibration-failed"] == "warning"
    retire_miner(project, agent, VISION_NAME, 1, "recall below the floor")
    assert miner_state(project, VISION_NAME, 1) is MinerState.RETIRED
    assert "miner-calibration-failed" in {f.code for f in check(project).findings}
    text = render_methods(methods_report(project))
    head = f"Miner {VISION_NAME} version 1 (proposed by agent)"
    assert f"{head}: retired (calibration failed)." in text
    assert "record recall 0.400" in text and "Not admitted as evidence." in text
