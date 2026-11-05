"""Evidence admission, the `mine.resolve` policy, builder reads and methods (M-D, task 6)."""

# ruff: noqa: F811
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.model.extraction import MinerScope
from factory.model.project import RigorMode
from factory.model.screening import Channel, PassLabel
from factory.modules.contract import Autonomy, PolicyKind
from factory.modules.presets import preset
from factory.services import check as check_module
from factory.services.check import check
from factory.services.context import Project
from factory.services.extraction_agreement import extraction_agreement, resolve_extraction
from factory.services.gates import autonomy_of, effective_policy, gate_acts, gate_audit_sample
from factory.services.methods import agent_methods, methods_report, render_methods
from factory.services.miners import MinerState, miner_state, retire_miner
from factory.services.modules.default import default_modules
from factory.services.protocol import amend_protocol, current_protocol, list_amendments
from tests.cli_helpers import _env
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.helpers import install_skill, open_session
from tests.miner_calibration_helpers import (
    PROPOSER,
    SESSION_P,
    SESSION_R,
    calibrated_world,
    force_gate_policy,
    force_spec,
    run_calibration,
)
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    mine_pass,
    mine_row,
    miner_actor,
    use,
)

SCOPE = MinerScope(VISION_NAME)


def _set_evidence(project: Project, actor: Actor, value: bool = True) -> object:
    current = current_protocol(project)
    assert current is not None
    uses = tuple(u.model_copy(update={"evidence": value}) for u in current.spec.miners or ())
    return amend_protocol(
        project,
        actor,
        current.spec.model_copy(update={"miners": uses}),
        reason="admit the miner as evidence",
        semantic=True,
        effects={},
    )


def test_evidence_true_refused_until_calibrated(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    with pytest.raises(FactoryValidationError) as raised:
        _set_evidence(project, agent)  # registered and listed, not calibrated
    assert [i.field for i in raised.value.issues] == ["miners.0.evidence"]
    run_calibration(project)
    assert miner_state(project, VISION_NAME, 1) is MinerState.CALIBRATED
    _set_evidence(project, agent)  # now allowed


def test_a_failed_or_retired_miner_cannot_be_admitted(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    run_calibration(project, miss=tuple(cal.works[:2]))  # recall 0.6: failed
    assert miner_state(project, VISION_NAME, 1) is MinerState.FAILED
    with pytest.raises(FactoryValidationError):
        _set_evidence(project, agent)


def test_retiring_a_calibrated_miner_blocks_a_later_admission(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    retire_miner(project, agent, VISION_NAME, 1, "replaced")
    with pytest.raises(FactoryValidationError):
        _set_evidence(project, agent)


def test_evidence_true_allowed_after_pass_by_amendment(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    result = _set_evidence(project, agent)
    assert result.stale_rules == [] and not result.prose_only  # type: ignore[attr-defined]
    amended = list_amendments(project)[-1]
    assert amended.other_changes == ("miners",)
    assert amended.changes == () and amended.stale_rules == ()
    assert all(not s.rule.all_records for s in amended.miner_stale)
    assert amended.extraction_stale is None and amended.contribution_stale is None
    current = current_protocol(project)
    assert current is not None and current.spec.miners is not None
    assert current.spec.miners[0].evidence is True


# --- mine.resolve ---


def test_mine_resolve_floor_and_presets() -> None:
    gate = default_modules().gate("mine.resolve")
    assert gate.floor is PolicyKind.AGENT
    assert preset(RigorMode.EXPLORATORY, "mine.resolve").kind is PolicyKind.AGENT_AUDIT
    assert preset(RigorMode.PILOT, "mine.resolve").kind is PolicyKind.HUMAN
    assert preset(RigorMode.SYSTEMATIC, "mine.resolve").kind is PolicyKind.HUMAN
    # the other resolution gate keeps its floor
    assert default_modules().gate("extraction.resolve").floor is PolicyKind.HUMAN


def _disputed(project: Project, agent: Actor, human: Actor) -> tuple[str, str, Actor, Actor]:
    """Two production passes that disagree on one field; returns the work, the row key and the
    two pass actors."""
    calibrated_world(project, agent, human)
    run_calibration(project)
    mina = miner_actor(SESSION_M1, "claude-opus-5-5")
    minb = miner_actor(SESSION_M2, "claude-sonnet-5-5")
    worked = mine_pass(project, mina, PassLabel.A, lambda w: [mine_row()])
    mine_pass(
        project, minb, PassLabel.B, lambda w: [mine_row("lower" if w == worked[0] else "higher")]
    )
    disputed = extraction_agreement(project, human, scope=SCOPE).disagreements[0]
    return disputed.work_id, disputed.row_key, mina, minb


def _resolver() -> Actor:
    return miner_actor(SESSION_R, "claude-opus-5-5")


def _resolve(project: Project, actor: Actor, work: str, key: str, channel: Channel) -> str:
    return resolve_extraction(
        project, actor, work, key, "direction", "a", "pass A is right", channel, scope=SCOPE
    )


def test_pilot_keeps_resolution_with_the_human(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    work, key, _, _ = _disputed(project, agent, human)
    assert effective_policy(project, "mine.resolve").kind is PolicyKind.HUMAN
    with pytest.raises(FactoryValidationError) as raised:
        _resolve(project, _resolver(), work, key, Channel.MCP)
    assert raised.value.issues[0].field == "actor"
    assert list(gate_acts(project, "mine.resolve")) == []


def test_agent_resolution_under_exploratory_preset_is_audited_agent(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    work, key, _, _ = _disputed(project, agent, human)
    # the exploratory preset, set on this project as an amendment the pilot rules would not allow
    force_gate_policy(project, agent, "mine.resolve", PolicyKind.AGENT_AUDIT, audit=True)
    event_id = _resolve(project, _resolver(), work, key, Channel.MCP)
    [act] = list(gate_acts(project, "mine.resolve"))
    assert act.event_id == event_id and act.actor_kind == "agent"
    assert autonomy_of(project, act) is Autonomy.AGENT  # until a human audits the gate
    gate_audit_sample(project, human, "mine.resolve", random_seed=1)
    assert autonomy_of(project, act) is Autonomy.AUDITED_AGENT


def test_proposer_cannot_resolve(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    work, key, _, _ = _disputed(project, agent, human)
    force_gate_policy(project, agent, "mine.resolve", PolicyKind.AGENT)
    before = len(list(gate_acts(project, "mine.resolve")))
    with pytest.raises(FactoryValidationError) as raised:
        _resolve(project, PROPOSER, work, key, Channel.MCP)  # the registering session
    assert raised.value.issues[0].field == "session"
    relayed = Actor(kind="human", id="obd", user="obd", session=SESSION_P)
    with pytest.raises(FactoryValidationError) as raised:
        _resolve(project, relayed, work, key, Channel.MCP)  # a human act it relays
    assert raised.value.issues[0].field == "session"
    assert len(list(gate_acts(project, "mine.resolve"))) == before


def test_a_session_of_either_pass_cannot_resolve(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    work, key, mina, minb = _disputed(project, agent, human)
    force_gate_policy(project, agent, "mine.resolve", PolicyKind.AGENT)
    for actor in (mina, minb):
        with pytest.raises(FactoryValidationError) as raised:
            _resolve(project, actor, work, key, Channel.CLI)  # not the relay rule: the pass rule
        assert [i.field for i in raised.value.issues] == ["session"]
        with pytest.raises(FactoryValidationError):
            _resolve(project, actor, work, key, Channel.MCP)
    assert list(gate_acts(project, "mine.resolve")) == []


def test_a_human_still_resolves_at_the_terminal(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    work, key, _, _ = _disputed(project, agent, human)
    _resolve(project, human, work, key, Channel.CLI)
    assert len(list(gate_acts(project, "mine.resolve"))) == 1


# --- builders, checks and methods ---


def test_version_unread_finding(
    project: Project, agent: Actor, human: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calibrated_world(project, agent, human)
    assert "miner-version-unread" not in {f.code for f in check(project).findings}  # no rows yet
    run_calibration(project)  # calibration rows are not production rows
    assert "miner-version-unread" not in {f.code for f in check(project).findings}
    mine_pass(
        project, miner_actor(SESSION_M1, "claude-opus-5-5"), PassLabel.A, lambda w: [mine_row()]
    )
    found = [f for f in check(project).findings if f.code == "miner-version-unread"]
    assert len(found) == 1 and found[0].severity == "warning"
    assert found[0].message == f"miner {VISION_NAME} version 1 has rows no builder reads"

    real = default_modules()

    class Reading:
        def read_miners(self) -> frozenset[tuple[str, int]]:
            return frozenset({(VISION_NAME, 1)})

        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

    monkeypatch.setattr(check_module, "default_modules", lambda: Reading())
    assert "miner-version-unread" not in {f.code for f in check(project).findings}


def test_the_evidence_builder_reads_no_registered_miner() -> None:
    assert default_modules().module("evidence").spec.reads.miners == ()
    assert default_modules().read_miners() == frozenset()
    assert default_modules().owner_of_check("miner-version-unread") == "mining"


def test_uncalibrated_evidence_is_an_error_in_a_hand_edited_log(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    current = current_protocol(project)
    assert current is not None
    forced = current.spec.model_copy(update={"miners": (use(evidence=True),)})
    force_spec(project, agent, forced)  # what the tools refuse, written to the log directly
    found = [f for f in check(project).findings if f.code == "miner-uncalibrated-evidence"]
    assert len(found) == 1 and found[0].severity == "error"
    assert "calibrating" in found[0].message and "recall" not in found[0].message


def test_methods_lists_failed_and_retired(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal = calibrated_world(project, agent, human)
    run_calibration(project, miss=tuple(cal.works[:2]))
    report = methods_report(project)
    [entry] = report.miners
    assert (entry.name, entry.version, entry.state) == (VISION_NAME, 1, "failed")
    assert entry.proposer_kind == "agent" and entry.evidence is False
    assert entry.recall == pytest.approx(0.6)
    text = render_methods(report)
    assert f"Miner {VISION_NAME} version 1 (proposed by agent): failed." in text
    assert "record recall 0.600" in text
    retire_miner(project, agent, VISION_NAME, 1, "failed its calibration")
    after = render_methods(methods_report(project))
    assert (
        f"Miner {VISION_NAME} version 1 (proposed by agent): retired (calibration failed)." in after
    )
    assert methods_report(project).miners[0].calibration == "failed"


def test_agent_methods_withhold_scores(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    calibrated_world(project, agent, human)
    run_calibration(project)
    full = methods_report(project)
    assert full.miners[0].recall == 1.0
    agent_view, withheld = agent_methods(project, full)
    assert "miner_scores" in withheld
    blanked = agent_view.miners[0]
    assert (blanked.recall, blanked.field_agreement, blanked.precision) == (None, None, None)
    assert blanked.verification_rate is None and blanked.state == "calibrated"
    text = render_methods(agent_view, withheld=withheld)
    assert "withheld from the agent view" in text and "record recall" not in text


def test_methods_without_miners_is_unchanged(project: Project, world: list[str]) -> None:
    report = methods_report(project)
    assert report.miners == []
    assert "Registered miners" not in render_methods(report)


AGENT = {"role": "resolver", "model": "claude-opus-5-5", "skill": "rf-extract"}


async def _call(
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    session: str,
    tool: str,
    **args: Any,
) -> dict[str, Any]:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)
    async with open_session(settings, clock) as client:
        return await client.call(tool, project="demo", **AGENT, **args)


@pytest.mark.anyio
async def test_mcp_agent_resolution_follows_the_policy(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    work, key, _, _ = _disputed(project, agent, human)
    ask = {"miner": VISION_NAME}
    refused = await _call(settings, clock, monkeypatch, SESSION_R, "mine_disagreements", **ask)
    assert refused["ok"] is False and refused["errors"][0]["field"] == "miner"  # a human gate
    force_gate_policy(project, agent, "mine.resolve", PolicyKind.AGENT)
    listed = await _call(settings, clock, monkeypatch, SESSION_R, "mine_disagreements", **ask)
    assert listed["ok"] is True, listed
    [item] = listed["data"]["disagreements"]
    assert (item["work_id"], item["row_key"]) == (work, key)
    assert "rate" not in str(listed) and "overall" not in str(listed)
    args = {**ask, "work_id": work, "row_key": key, "field": "direction", "reason": "A is right"}
    mine = await _call(settings, clock, monkeypatch, SESSION_P, "mine_resolve", choice="a", **args)
    assert mine["ok"] is False and mine["errors"][0]["field"] == "session"  # the proposer
    bad = await _call(settings, clock, monkeypatch, SESSION_R, "mine_resolve", choice="x", **args)
    assert bad["ok"] is False and bad["errors"][0]["field"] == "choice"
    assert list(gate_acts(project, "mine.resolve")) == []
    done = await _call(settings, clock, monkeypatch, SESSION_R, "mine_resolve", choice="a", **args)
    assert done["ok"] is True, done
    assert len(list(gate_acts(project, "mine.resolve"))) == 1


runner = CliRunner()


def _cli(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_cli_agreement_resolution_audit_and_report_of_a_miner(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    work, key, _, _ = _disputed(project, agent, human)
    code, out, err = _cli(settings.root, "mine", "agreement", VISION_NAME)
    assert code == 0 and work in out and key in out, err
    code, out, err = _cli(
        settings.root,
        *("mine", "resolve", VISION_NAME, work, key),
        *("--choice", "a", "--reason", "A is right", "--field", "direction"),
    )
    assert code == 0 and "resolved" in out, err
    code, out, err = _cli(settings.root, "mine", "audit", "sample", VISION_NAME)
    assert code == 0 and out.startswith("audit xau_"), err
    audit = out.split()[1].rstrip(":")
    code, out, err = _cli(settings.root, "mine", "audit", "report", VISION_NAME)
    assert code == 0 and "audit" in out.lower(), err
    assert audit
    code, out, err = _cli(settings.root, "miner", "calibrate", "report", VISION_NAME, "1")
    assert code == 0 and "calibrated" in out and "record recall 1.000" in out, err
    assert "result: passed" in out
    code, out, _ = _cli(settings.root, "mine", "audit", "report", "m-nothing")
    assert code != 0 or "no audit" in out
