"""The protocol's `miners` section: hash, readiness rules and per-miner staleness (M-C, task 6)."""

from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import spec_to_json
from factory.model.extraction import MinerScope, Scope
from factory.model.miners import MinerUse
from factory.model.protocol import ProtocolSpec, protocol_version
from factory.model.staleness import RowRef, scope_rule, stale_rows
from factory.services.context import Project
from factory.services.mining import register_miner, require_listed
from factory.services.protocol import amend_protocol, current_protocol, list_amendments
from tests.extraction_helpers import PINNED_P_ID
from tests.helpers import SourcesFor, pilot_protocol_spec, ready_protocol
from tests.miner_helpers import VISION_NAME, vision_result

OTHER = "m-other-result"


def _use(name: str = VISION_NAME, version: int = 1, **over: object) -> MinerUse:
    base: dict[str, object] = {
        "name": name,
        "version": version,
        "dual_extract_sample": 0.5,
        "audit_fraction": 0.05,
        "audit_minimum": 50,
    }
    base.update(over)
    return MinerUse.model_validate(base)


def _current(project: Project) -> ProtocolSpec:
    protocol = current_protocol(project)
    assert protocol is not None
    return protocol.spec


def _amend(project: Project, agent: Actor, *uses: MinerUse) -> None:
    amend_protocol(
        project,
        agent,
        _current(project).model_copy(update={"miners": tuple(uses) if uses else None}),
        reason="list miners",
        semantic=True,
        effects={},
    )


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> None:
    ready_protocol(project, agent, human, mock_sources)


def _register(project: Project, agent: Actor, name: str = VISION_NAME, version: int = 1) -> None:
    register_miner(project, agent, spec_to_json(vision_result(name=name, version=version)))


def test_p_id_unchanged_without_miners() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.miners is None
    assert protocol_version(spec) == PINNED_P_ID
    listed = spec.model_copy(update={"miners": (_use(),)})
    assert protocol_version(listed) != PINNED_P_ID


def test_hash_sorts_miners_and_tracks_their_settings() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    ab = spec.model_copy(update={"miners": (_use("m-a-one"), _use("m-b-two"))})
    ba = spec.model_copy(update={"miners": (_use("m-b-two"), _use("m-a-one"))})
    assert protocol_version(ab) == protocol_version(ba)
    other = spec.model_copy(update={"miners": (_use("m-a-one", audit_minimum=60), _use("m-b-two"))})
    assert protocol_version(other) != protocol_version(ab)


def test_unregistered_miner_listed_is_error(project: Project, agent: Actor, ready: None) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        _amend(project, agent, _use())
    assert "miners.0.name" in {i.field for i in raised.value.issues}
    _register(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        _amend(project, agent, _use(version=2))  # version 2 is not registered
    assert "miners.0.name" in {i.field for i in raised.value.issues}


def test_a_miner_is_listed_once(project: Project, agent: Actor, ready: None) -> None:
    _register(project, agent)
    _register(project, agent, version=2)
    with pytest.raises(FactoryValidationError) as raised:
        _amend(project, agent, _use(version=1), _use(version=2))
    assert "miners.1.name" in {i.field for i in raised.value.issues}


def test_evidence_true_refused(project: Project, agent: Actor, ready: None) -> None:
    _register(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        _amend(project, agent, _use(evidence=True))
    assert [i.field for i in raised.value.issues] == ["miners.0.evidence"]
    assert "calibrate" in raised.value.issues[0].reason


def test_pilot_needs_a_dual_fraction(project: Project, agent: Actor, ready: None) -> None:
    _register(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        _amend(project, agent, _use(dual_extract_sample=None))
    assert "miners.0.dual_extract_sample" in {i.field for i in raised.value.issues}


def test_listing_is_required_before_mine(project: Project, agent: Actor, ready: None) -> None:
    _register(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        require_listed(project, VISION_NAME, 1)
    assert raised.value.issues[0].field == "miners"
    _amend(project, agent, _use())
    protocol, use, spec = require_listed(project, VISION_NAME, 1)
    assert use.name == VISION_NAME and spec.name == VISION_NAME
    assert protocol.spec.miners == (use,)
    with pytest.raises(FactoryValidationError) as raised:
        require_listed(project, VISION_NAME, 2)
    assert raised.value.issues[0].field == "miners"


def test_amending_a_miner_touches_other_changes_only(
    project: Project, agent: Actor, ready: None
) -> None:
    _register(project, agent)
    _amend(project, agent, _use())
    amendment = list_amendments(project)[-1]
    assert amendment.other_changes == ("miners",)
    assert amendment.extraction_stale is None and amendment.contribution_stale is None
    assert amendment.miner_stale == ()


def test_amending_one_miner_stales_only_its_rows(
    project: Project, agent: Actor, ready: None
) -> None:
    _register(project, agent)
    _register(project, agent, OTHER)
    _amend(project, agent, _use(), _use(OTHER))
    # settings change: nothing is stale
    _amend(project, agent, _use(audit_minimum=80), _use(OTHER))
    assert list_amendments(project)[-1].miner_stale == ()
    # dropping one miner stales all of its rows and none of the other's
    _amend(project, agent, _use(OTHER))
    amendment = list_amendments(project)[-1]
    assert [(m.name, m.rule.all_records) for m in amendment.miner_stale] == [(VISION_NAME, True)]
    assert scope_rule(amendment, MinerScope(VISION_NAME)) is not None
    assert scope_rule(amendment, MinerScope(OTHER)) is None
    assert scope_rule(amendment, Scope.EVIDENCE) is None
    row = RowRef(row_id="r1", fields=("value",), at="0")
    assert stale_rows([amendment], ["1"], [row], scope=MinerScope(VISION_NAME)) == ["r1"]
    assert stale_rows([amendment], ["1"], [row], scope=MinerScope(OTHER)) == []
    assert stale_rows([amendment], ["1"], [row]) == []


def test_a_new_version_stales_the_old_versions_rows(
    project: Project, agent: Actor, ready: None
) -> None:
    _register(project, agent)
    register_miner(project, agent, spec_to_json(replace(vision_result(), version=2)))
    _amend(project, agent, _use())
    _amend(project, agent, _use(version=2))
    amendment = list_amendments(project)[-1]
    assert [(m.name, m.rule.all_records) for m in amendment.miner_stale] == [(VISION_NAME, True)]
