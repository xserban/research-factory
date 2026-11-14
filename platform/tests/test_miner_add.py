"""One command adds a miner: validate, register, list in the protocol, name its page (IDEA-51)."""

# ruff: noqa: F811
from typing import Any

import pytest
from pydantic import JsonValue

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import spec_to_json
from factory.services.context import Project
from factory.services.miner_add import add_miner
from factory.services.miners import MinerState, miner_state
from factory.services.mining import miner_listing, register_miner, registered_miner
from factory.services.protocol import current_protocol
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import VISION_NAME, method_vision


def _doc(**use: Any) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {"spec": spec_to_json(method_vision())}
    if use:
        body["use"] = use
    body["reason"] = "add the vision miner"
    return body


def _events(project: Project) -> int:
    from factory.events.reader import read_all

    return len(read_all(project.paths.events_dir, project.catalog))


def test_adds_registers_lists_and_names_the_page(
    project: Project, human: Actor, world: list[str]
) -> None:
    result = add_miner(project, human, _doc(dual_extract_sample=0.5))
    assert (result.name, result.version) == (VISION_NAME, 1)
    assert result.registered and result.listed
    assert result.page == f"miners/{VISION_NAME}.html"
    assert result.hub_page == f"/p/{project.paths.slug}/miners/{VISION_NAME}.html"
    assert registered_miner(project, VISION_NAME, 1) is not None
    protocol = current_protocol(project)
    assert protocol is not None
    uses = [u for u in protocol.spec.miners or () if u.name == VISION_NAME]
    assert len(uses) == 1 and uses[0].dual_extract_sample == 0.5 and not uses[0].evidence
    assert [m.listed for m in miner_listing(project)] == [True]
    assert miner_state(project, VISION_NAME, 1) is MinerState.REGISTERED


def test_a_bare_spec_is_accepted_with_defaults(
    project: Project, human: Actor, world: list[str]
) -> None:
    result = add_miner(project, human, spec_to_json(method_vision()))
    assert result.registered and result.listed


def test_again_writes_nothing(project: Project, human: Actor, world: list[str]) -> None:
    add_miner(project, human, _doc())
    before = _events(project)
    result = add_miner(project, human, _doc())
    assert not result.registered and not result.listed
    assert _events(project) == before


def test_registered_but_unlisted_gets_listed(
    project: Project, human: Actor, world: list[str]
) -> None:
    register_miner(project, human, spec_to_json(method_vision()))
    result = add_miner(project, human, _doc())
    assert not result.registered and result.listed


def test_an_invalid_spec_writes_nothing(project: Project, human: Actor, world: list[str]) -> None:
    body = _doc()
    spec = body["spec"]
    assert isinstance(spec, dict)
    spec["row_key_fields"] = []
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        add_miner(project, human, body)
    assert any(i.field.startswith("row_key_fields") for i in raised.value.issues)
    assert _events(project) == before


def test_a_bad_use_writes_nothing(project: Project, human: Actor, world: list[str]) -> None:
    before = _events(project)
    for use in ({"dual_extract_sample": 3}, {"nope": 1}, {"evidence": True}):
        with pytest.raises(FactoryValidationError) as raised:
            add_miner(project, human, _doc(**use))
        assert raised.value.issues[0].field.startswith("use")
    assert _events(project) == before


def test_a_missing_spec_is_refused(project: Project, human: Actor, world: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        add_miner(project, human, {"use": {}})
    assert raised.value.issues[0].field == "spec"


def test_check_only_validates_and_writes_nothing(
    project: Project, human: Actor, world: list[str]
) -> None:
    before = _events(project)
    result = add_miner(project, human, _doc(), check_only=True)
    assert result.registered and result.listed  # what would happen
    assert result.checked_only
    assert _events(project) == before
    assert registered_miner(project, VISION_NAME, 1) is None


def test_a_system_actor_is_refused(project: Project, human: Actor, world: list[str]) -> None:
    system = Actor(kind="system", id="platform", user="platform", session=human.session)
    with pytest.raises(FactoryValidationError) as raised:
        add_miner(project, system, _doc())
    assert raised.value.issues[0].field == "actor"
