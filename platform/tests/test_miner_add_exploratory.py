"""Replacing an exploratory miner use with a new version keeps it exploratory."""

# ruff: noqa: F811
from pydantic import JsonValue

from factory.events.envelope import Actor
from factory.mining.spec import spec_to_json
from factory.model.miners import MinerUse
from factory.services.context import Project
from factory.services.miner_add import _differences, add_miner
from factory.services.protocol import amend_protocol, current_protocol
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import VISION_NAME, method_vision


def test_differences_tolerates_a_key_missing_on_one_side() -> None:
    old = MinerUse(name="m-x", version=1, exploratory=True)
    new = MinerUse(name="m-x", version=2)
    assert "exploratory True -> None" in _differences(old, new)


def test_replacing_an_exploratory_use_carries_the_flag_over(
    project: Project, human: Actor, world: list[str]
) -> None:
    first: dict[str, JsonValue] = {"spec": spec_to_json(method_vision())}
    add_miner(project, human, first)
    protocol = current_protocol(project)
    assert protocol is not None
    uses = tuple(
        u.model_copy(update={"exploratory": True}) if u.name == VISION_NAME else u
        for u in protocol.spec.miners or ()
    )
    amend_protocol(
        project,
        human,
        protocol.spec.model_copy(update={"miners": uses}),
        reason="declare the miner exploratory",
        semantic=True,
        effects={},
    )
    v2: dict[str, JsonValue] = {"spec": spec_to_json(method_vision(version=2))}
    result = add_miner(project, human, v2)
    assert result.replaced_version == 1
    after = current_protocol(project)
    assert after is not None
    (use,) = [u for u in after.spec.miners or () if u.name == VISION_NAME]
    assert use.version == 2 and use.exploratory
