"""Shared builders of the miner calibration tests: a calibrated world, a forced gate policy."""

from __future__ import annotations

from dataclasses import dataclass, replace

from factory.events.envelope import Actor
from factory.mining.spec import MinerRegime, MinerSpec, spec_to_json
from factory.model.gates import GatePolicies, GatePolicyEntry
from factory.model.protocol import ProtocolAmended, protocol_version
from factory.model.screening import Channel, PassLabel
from factory.modules.contract import PolicyKind
from factory.services.context import Project
from factory.services.miner_gold import label_miner_calibration
from factory.services.miners import draw_miner_calibration
from factory.services.mining import mine_next, mine_record, register_miner
from factory.services.protocol import current_protocol
from tests.miner_helpers import VISION_NAME, list_miner, method_vision, mine_row, miner_actor

SESSION_P = "01JZ9Q3K5M7N8P0R2S4T6V8W1J"
SESSION_C = "01JZ9Q3K5M7N8P0R2S4T6V8W1G"
SESSION_R = "01JZ9Q3K5M7N8P0R2S4T6V8W1K"
PROPOSER = miner_actor(SESSION_P, "claude-opus-5-5")
JUDGE = miner_actor(SESSION_C, "claude-sonnet-5-5")


@dataclass(frozen=True)
class Calibration:
    calibration_id: str
    works: list[str]
    spec: MinerSpec


def calibrated_world(
    project: Project, agent: Actor, human: Actor, *, size: int = 5, recall_min: float = 0.8
) -> Calibration:
    """Register `m-vision-result@1` as session P, list it, draw a sample of `size` units and
    label every unit with `mine_row()`. The pass is not run."""
    spec = replace(method_vision(), regime=MinerRegime(2, size, recall_min, 0.9))
    register_miner(project, PROPOSER, spec_to_json(spec))
    list_miner(project, agent, spec)
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=11)
    works = [u.work_id for u in drawn.units]
    for work in works:
        label_miner_calibration(
            project, human, drawn.calibration_id, work, [mine_row()], channel=Channel.CLI
        )
    return Calibration(drawn.calibration_id, works, spec)


def run_calibration(
    project: Project, *, miss: tuple[str, ...] = (), name: str = VISION_NAME, version: int = 1
) -> None:
    """The judge session runs the calibration pass; the works in `miss` are closed with no row."""
    for _ in range(50):
        batch = mine_next(project, JUDGE, name, version, PassLabel.A, calibration=True).batch
        if batch is None:
            return
        rows = [] if batch.records[0]["work_id"] in miss else [mine_row()]
        mine_record(
            project,
            JUDGE,
            batch.task_id,
            rows,
            finish=True,
            reason=None if rows else "no result",
        )
    raise AssertionError("too many tasks")


def force_gate_policy(
    project: Project, actor: Actor, gate: str, policy: PolicyKind, *, audit: bool = False
) -> None:
    """Record an amendment that sets a gate policy the readiness rules would refuse in this mode
    (for example a loosened gate in pilot), by writing the event directly."""
    current = current_protocol(project)
    assert current is not None
    entry = (
        GatePolicyEntry(gate=gate, policy=policy, fraction=0.1, minimum=1)
        if audit
        else GatePolicyEntry(gate=gate, policy=policy)
    )
    spec = current.spec.model_copy(update={"gate_policies": GatePolicies(entries=(entry,))})
    force_spec(project, actor, spec)


def force_spec(project: Project, actor: Actor, spec: object) -> None:
    """Record `spec` as the protocol by an amendment event, bypassing the readiness rules."""
    from factory.model.protocol import ProtocolSpec

    assert isinstance(spec, ProtocolSpec)
    current = current_protocol(project)
    assert current is not None
    payload = ProtocolAmended(
        amendment_id=project.ids.new("amd"),
        from_version=current.protocol_id,
        to_version=protocol_version(spec),
        spec=spec,
        reason="forced for a test",
        semantic=True,
    )
    blob = project.blobs.put_json({"forced": True})
    project.record([project.events.make("protocol.amended", payload, actor, input_blob=blob)])
