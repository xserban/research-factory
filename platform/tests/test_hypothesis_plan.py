"""The `hypothesis_plan` section and the hypothesis gate policies (slice 6, plan H-C task 2)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.gates import GatePolicies
from factory.model.hypothesis_plan import HypothesisPlan
from factory.model.project import RigorMode
from factory.model.protocol import protocol_version
from factory.modules.contract import PolicyKind
from factory.modules.presets import preset
from factory.services.context import Project
from factory.services.extraction import stale_extractions
from factory.services.hypothesis_gates import effective_plan, gate_policy, may_pass
from factory.services.project import init_project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.protocol_rules import other_changes
from factory.services.screening import stale_screening_decisions
from tests.gate_helpers import entry
from tests.helpers import S2, SESSION
from tests.hypothesis_helpers import CRITIC, DRAFTER, OTHER
from tests.screening_helpers import _check, _fields
from tests.test_protocol_model import _spec as model_spec
from tests.test_protocol_rules import _spec
from tests.test_references_resolve import extraction  # noqa: F401

P_ID = "P@ac674dc2"
GATES = ("hypotheses.lead_decide", "hypotheses.register", "experiments.freeze_unlock")
"""Slice 6 ruling 14: the gates an exploratory agent may pass; `accept_baseline` is human."""


def test_p_id_unchanged_without_hypothesis_plan() -> None:  # Review Focus 5
    assert protocol_version(model_spec()) == P_ID
    assert protocol_version(model_spec(hypothesis_plan=None)) == P_ID


def test_p_id_changes_with_plan() -> None:
    plan = HypothesisPlan(min_seeds=4)
    assert protocol_version(model_spec(hypothesis_plan=plan)) != P_ID
    other = HypothesisPlan(min_seeds=5)
    assert protocol_version(model_spec(hypothesis_plan=plan)) != protocol_version(
        model_spec(hypothesis_plan=other)
    )


def test_plan_errors_are_located() -> None:
    check = _check(_spec(hypothesis_plan=HypothesisPlan(min_seeds=1, test_access_limit=0)))
    assert _fields(check.errors) == [
        "hypothesis_plan.min_seeds",
        "hypothesis_plan.test_access_limit",
    ]
    assert _check(_spec(hypothesis_plan=HypothesisPlan(min_seeds=2))).errors == []


@pytest.mark.parametrize("gate", [*GATES, "experiments.accept_baseline"])
@pytest.mark.parametrize("mode", list(RigorMode))
def test_defaults_follow_mode_table(gate: str, mode: RigorMode) -> None:
    agent_gate = mode is RigorMode.EXPLORATORY and gate != "experiments.accept_baseline"
    assert preset(mode, gate).kind is (PolicyKind.AGENT if agent_gate else PolicyKind.HUMAN)


@pytest.mark.parametrize(
    ("mode", "seeds", "lead", "distinct"),
    [("exploratory", 2, False, False), ("pilot", 3, True, False), ("systematic", 5, True, True)],
)
def test_plan_defaults_by_mode(
    settings: Settings, clock: FixedClock, mode: str, seeds: int, lead: bool, distinct: bool
) -> None:
    project = init_project(settings, "demo", mode, session=SESSION, clock=clock)
    plan = effective_plan(project)
    assert (plan.min_seeds, plan.require_lead, plan.critic_distinct_model) == (
        seeds,
        lead,
        distinct,
    )
    assert (plan.confidence, plan.test_access_limit, plan.conflict_tolerance) == (
        "0.95",
        1,
        "0.01",
    )


def test_stated_plan_fields_are_kept(project: Project, extraction: str, human: Actor) -> None:
    current = current_protocol(project)
    assert current is not None
    plan = HypothesisPlan(min_seeds=7, require_lead=True, critic_distinct_model=True)
    amend_protocol(
        project,
        human,
        current.spec.model_copy(update={"hypothesis_plan": plan}),
        reason="state the hypothesis plan",
        semantic=True,
        effects={},
    )
    got = effective_plan(project)
    assert (got.min_seeds, got.require_lead, got.critic_distinct_model) == (7, True, True)


def test_systematic_agent_gate_is_refused() -> None:
    """Slice M ruling 8: below the mode's preset is an error in systematic, a gap in pilot."""
    spec = _spec(
        gate_policies=GatePolicies(entries=(entry("hypotheses.lead_decide", PolicyKind.AGENT),))
    )
    assert "gate_policies.entries.0.policy" in _fields(_check(spec, RigorMode.SYSTEMATIC).errors)
    assert "gate_policies.entries.0.policy" in _fields(_check(spec, RigorMode.PILOT).gaps)
    assert _check(spec, RigorMode.EXPLORATORY).errors == []


def test_unknown_gate_policy_name_is_refused() -> None:
    spec = _spec(
        gate_policies=GatePolicies(entries=(entry("hypotheses.nothing", PolicyKind.HUMAN),))
    )
    assert "gate_policies.entries.0.gate" in _fields(_check(spec).errors)


def test_may_pass_refuses_proposer_session_under_agent(
    explore_project: Project, human: Actor
) -> None:
    project = explore_project
    assert gate_policy(project, "hypotheses.register").kind is PolicyKind.AGENT
    refused = may_pass(project, DRAFTER, "hypotheses.register", proposer_sessions={SESSION})
    assert (refused.ok, refused.field) == (False, "session")
    assert refused.reason == "the proposer cannot pass gate hypotheses.register"
    ok = may_pass(project, CRITIC, "hypotheses.register", proposer_sessions={SESSION, S2 + "x"})
    assert (ok.ok, ok.autonomy) == (True, "agent")
    # a human is also excluded when the policy is `agent`: the gate is the other session's
    assert not may_pass(project, human, "hypotheses.register", proposer_sessions={SESSION}).ok


def test_may_pass_human_only_under_human(project: Project, human: Actor) -> None:
    refused = may_pass(project, OTHER, "hypotheses.register", proposer_sessions=set())
    assert (refused.ok, refused.field) == (False, None)
    assert refused.reason == "gate hypotheses.register is human: an agent cannot pass it"
    ok = may_pass(project, human, "hypotheses.register", proposer_sessions={SESSION})
    assert (ok.ok, ok.autonomy) == (True, "human")


def test_amendment_of_plan_stales_nothing(project: Project, extraction: str, human: Actor) -> None:
    before = (stale_screening_decisions(project), stale_extractions(project))
    current = current_protocol(project)
    assert current is not None
    new = current.spec.model_copy(update={"hypothesis_plan": HypothesisPlan(min_seeds=4)})
    assert other_changes(current.spec, new) == ["hypothesis_plan"]
    result = amend_protocol(project, human, new, reason="plan", semantic=True, effects={})
    assert result.to_version != result.from_version and result.stale_rules == []
    assert (stale_screening_decisions(project), stale_extractions(project)) == before


@pytest.mark.parametrize(
    ("mode", "plan", "fields"),
    [
        (
            RigorMode.SYSTEMATIC,
            {"critic_distinct_model": False},
            ["hypothesis_plan.critic_distinct_model"],
        ),
        (RigorMode.SYSTEMATIC, {"require_lead": False}, ["hypothesis_plan.require_lead"]),
        (RigorMode.PILOT, {"require_lead": False}, ["hypothesis_plan.require_lead"]),
        (RigorMode.PILOT, {"critic_distinct_model": False}, []),
        (RigorMode.EXPLORATORY, {"require_lead": False, "critic_distinct_model": False}, []),
        (RigorMode.SYSTEMATIC, {"require_lead": True, "critic_distinct_model": True}, []),
    ],
)
def test_plan_cannot_switch_off_the_independence_rules(
    mode: RigorMode, plan: dict[str, bool], fields: list[str]
) -> None:  # the proposer cannot amend the rules away (slice M ruling 8)
    check = _check(_spec(hypothesis_plan=HypothesisPlan(**plan)), mode)
    assert [f for f in _fields(check.errors) if f.startswith("hypothesis_plan")] == fields
