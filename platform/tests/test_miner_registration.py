"""`miner.registered`: validation, recording, idempotence and replay (M-C, task 6)."""

from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mining.compile import miner_digest
from factory.mining.spec import MinerField, Unverified, spec_to_json
from factory.model.miners import MinerRegistered
from factory.services.context import Project
from factory.services.mining import (
    register_miner,
    registered_miner,
    registered_miners,
    registered_row,
)
from tests.miner_helpers import VISION_NAME, vision_result


def _events(project: Project) -> list[str]:
    return [e.type for e in read_all(project.paths.events_dir, project.catalog)]


def test_register_validates_and_records(project: Project, agent: Actor) -> None:
    spec = vision_result()
    got = register_miner(project, agent, spec_to_json(spec))
    assert got.name == VISION_NAME and got.version == 1
    assert got.digest == miner_digest(spec) and got.proposer_kind == "agent"
    assert got.miner_id.startswith("mnr_")
    events = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "miner.registered"
    ]
    assert len(events) == 1
    assert events[0].input_blob is not None and events[0].actor.model == agent.model
    assert events[0].refs == (got.miner_id,)
    assert registered_miner(project, VISION_NAME, 1) == spec
    row = registered_row(project, VISION_NAME, 1)
    assert row is not None and row.digest == got.digest and row.proposer_kind == "agent"
    assert [r.name for r in registered_miners(project)] == [VISION_NAME]
    assert registered_miner(project, VISION_NAME, 2) is None


def test_a_human_may_register_and_a_system_actor_may_not(project: Project, human: Actor) -> None:
    got = register_miner(project, human, spec_to_json(vision_result()))
    assert got.proposer_kind == "human"
    with pytest.raises(FactoryValidationError) as raised:
        register_miner(project, project.system_actor(), spec_to_json(vision_result(version=2)))
    assert raised.value.issues[0].field == "actor"


def test_invalid_specs_write_nothing(project: Project, agent: Actor) -> None:
    before = _events(project)
    free = replace(
        vision_result(), fields=(*vision_result().fields, MinerField("note", "x", Unverified()))
    )
    for bad in (free, vision_result(name="ml-benchmark"), vision_result(row_key_fields=())):
        with pytest.raises(FactoryValidationError):
            register_miner(project, agent, spec_to_json(bad))
    with pytest.raises(FactoryValidationError) as raised:
        register_miner(project, agent, {"name": "m-x"})
    assert {"version", "selector.population", "fields"} <= {i.field for i in raised.value.issues}
    assert _events(project) == before


def test_same_digest_is_idempotent(project: Project, agent: Actor) -> None:
    first = register_miner(project, agent, spec_to_json(vision_result()))
    count = _events(project).count("miner.registered")
    prose_only = replace(vision_result(), rationale="other words, same miner")
    again = register_miner(project, agent, spec_to_json(prose_only))
    assert again == first and isinstance(again, MinerRegistered)
    assert _events(project).count("miner.registered") == count == 1


def test_different_digest_same_version_refused(project: Project, agent: Actor) -> None:
    register_miner(project, agent, spec_to_json(vision_result()))
    changed = replace(vision_result(), procedure="rf-other")
    with pytest.raises(FactoryValidationError) as raised:
        register_miner(project, agent, spec_to_json(changed))
    assert raised.value.issues[0].field == "version"
    assert _events(project).count("miner.registered") == 1
    # a new version is fine, and both stay registered
    register_miner(project, agent, spec_to_json(replace(changed, version=2)))
    assert [(r.name, r.version) for r in registered_miners(project)] == [
        (VISION_NAME, 1),
        (VISION_NAME, 2),
    ]


def test_the_registration_replays(project: Project, agent: Actor) -> None:
    got = register_miner(project, agent, spec_to_json(vision_result()))
    project.index.rebuild()
    row = registered_row(project, VISION_NAME, 1)
    assert row is not None and row.miner_id == got.miner_id and row.spec_blob == got.spec_blob
