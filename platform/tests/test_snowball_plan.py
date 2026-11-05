"""The protocol's `snowball_plan` section: hash, amendment and the missing-plan gap (ruling 19)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.protocol import AMENDABLE_FIELDS, SnowballPlan, protocol_version
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol, list_amendments
from factory.services.protocol_rules import SNOWBALL_PLAN_MISSING, snowball_plan_gaps
from tests.extraction_helpers import PINNED_P_ID
from tests.helpers import SourcesFor, pilot_protocol_spec, ready_protocol
from tests.test_protocol_rules import _check, _fields, _spec

PLAN = SnowballPlan(max_backward_rounds=2, max_forward_rounds=1)


def test_plan_defaults_and_bounds() -> None:
    assert PLAN.stop_when_no_new_included is True
    for bad in (
        {"max_backward_rounds": -1, "max_forward_rounds": 0},
        {"max_backward_rounds": 0, "max_forward_rounds": -1},
        {"max_backward_rounds": 0},
    ):
        with pytest.raises(ValidationError):
            SnowballPlan.model_validate(bad)


def test_snowball_plan_absent_keeps_protocol_id() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.snowball_plan is None
    assert protocol_version(spec) == PINNED_P_ID


def test_snowball_plan_changes_hash_and_is_amendable() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    with_plan = spec.model_copy(update={"snowball_plan": PLAN})
    assert protocol_version(with_plan) != PINNED_P_ID
    other = spec.model_copy(
        update={"snowball_plan": PLAN.model_copy(update={"stop_when_no_new_included": False})}
    )
    assert protocol_version(other) != protocol_version(with_plan)
    assert "snowball_plan" in AMENDABLE_FIELDS


def test_amend_declares_plan_as_other_change(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    new = old.spec.model_copy(update={"snowball_plan": PLAN})
    amend_protocol(project, agent, new, reason="declare snowballing", semantic=True, effects={})
    amendment = list_amendments(project)[-1]
    assert "snowball_plan" in amendment.other_changes
    current = current_protocol(project)
    assert current is not None and current.spec.snowball_plan == PLAN


def test_gap_when_plan_missing_in_pilot() -> None:
    spec = _spec()
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        gaps = snowball_plan_gaps(spec, mode)
        assert SNOWBALL_PLAN_MISSING == "snowball-plan-missing"
        assert "snowball-plan-missing" in [g.reason for g in gaps]
        assert [g.field for g in gaps] == ["snowball_plan"]
    assert snowball_plan_gaps(spec, RigorMode.EXPLORATORY) == []
    assert snowball_plan_gaps(_spec(snowball_plan=PLAN), RigorMode.PILOT) == []


def test_missing_plan_does_not_block_readiness() -> None:
    """The gap is for rounds and promotion (ruling 19), not for declaring the protocol ready."""
    check = _check(_spec())
    assert "snowball_plan" not in _fields(check.gaps + check.errors)
