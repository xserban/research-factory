"""An agent resolves a miner's disagreement under the exploratory preset, end to end (M-D)."""

# ruff: noqa: F811
import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import MinerScope
from factory.model.screening import Channel, PassLabel
from factory.modules.contract import Autonomy, PolicyKind
from factory.services.context import Project
from factory.services.extraction_agreement import extraction_agreement, resolve_extraction
from factory.services.gates import autonomy_of, effective_policy, gate_acts, gate_audit_sample
from factory.services.project import init_project
from tests.conftest import SESSION
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_calibration_helpers import SESSION_R, calibrated_world, run_calibration
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    mine_pass,
    mine_row,
    miner_actor,
)


@pytest.fixture
def project(settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch) -> Project:
    """An exploratory project. Its probe draws no hold-out split, which the pilot-shaped screening
    world needs before its calibration, so the split is drawn on first ask."""
    from factory.services import calibration
    from factory.services.seeds import split_is_drawn, split_seeds

    def drawn(project: Project) -> bool:
        if not split_is_drawn(project):
            split_seeds(project, random_seed=1)
        return True

    monkeypatch.setattr(calibration, "split_is_drawn", drawn)
    return init_project(settings, "demo", "exploratory", session=SESSION, clock=clock)


def test_agent_resolves_with_the_exploratory_preset_and_is_audited_later(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    scope = MinerScope(VISION_NAME)
    calibrated_world(project, agent, human)
    run_calibration(project)
    assert effective_policy(project, "mine.resolve").kind is PolicyKind.AGENT_AUDIT
    worked = mine_pass(
        project, miner_actor(SESSION_M1, "claude-opus-5-5"), PassLabel.A, lambda w: [mine_row()]
    )
    mine_pass(
        project,
        miner_actor(SESSION_M2, "claude-sonnet-5-5"),
        PassLabel.B,
        lambda w: [mine_row("lower" if w == worked[0] else "higher")],
    )
    [disputed] = extraction_agreement(project, human, scope=scope).disagreements
    resolver = miner_actor(SESSION_R, "claude-opus-5-5")
    event_id = resolve_extraction(
        project,
        resolver,
        disputed.work_id,
        disputed.row_key,
        disputed.field,
        "a",
        "pass A is right",
        Channel.MCP,
        scope=scope,
    )
    [act] = list(gate_acts(project, "mine.resolve"))
    assert (act.event_id, act.actor_kind) == (event_id, "agent")
    assert autonomy_of(project, act) is Autonomy.AGENT
    gate_audit_sample(project, human, "mine.resolve", random_seed=1)
    assert autonomy_of(project, act) is Autonomy.AUDITED_AGENT
    with pytest.raises(FactoryValidationError) as raised:  # the miner's own pass still cannot
        resolve_extraction(
            project,
            miner_actor(SESSION_M1, "claude-opus-5-5"),
            disputed.work_id,
            disputed.row_key,
            disputed.field,
            "b",
            "no",
            Channel.CLI,
            scope=scope,
        )
    assert raised.value.issues[0].field == "session"
