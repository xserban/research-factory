"""Who can pass each agent-weakenable gate, per rigor preset: the table is the test.

`EXPECTED` is data: a change of a preset, a floor or a service rule shows as a diff of this table.
The columns are the outcomes for an AGENT actor (a session other than the proposer's); the human
actor is the control and passes every gate in every preset. Each gate is probed through the
function its service calls, with no world beyond an initialised project:

- `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock` (no MCP tool, CLI
  only): `hypothesis_gates.may_pass` (leads.decide_lead
  and hypotheses.register_hypothesis call it after their own checks);
- `mine.resolve`, `writing.release`: `gates.gate_issues` (resolve_extraction) and
  `gates.require_gate` (release_draft);
- `reference.link_confirm`, `import.resolution_confirm`: `reference_resolve.confirmer_ruling`, the
  function decide_reference and decide_import share, given an unconfirmed link with a recorded
  proposal by another session, which is the case a second agent may decide;
- `manuscript.citation_confirm`: `manuscript_resolve.decide_citation`, which refuses a non-human
  whatever the policy (the gate's own policy would allow an agent under audit; the service does
  not).

These are attribution and platform refusal on the MCP path, not authentication: the CLI always
writes a human actor (see the tutorial concept "Who is the human in the log").
"""

from __future__ import annotations

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.manuscripts import CitationDecision
from factory.model.project import RigorMode
from factory.model.references import LinkState
from factory.modules.contract import PolicyKind
from factory.modules.presets import preset
from factory.services.context import Project
from factory.services.gates import effective_policy, gate_issues, require_gate
from factory.services.hypothesis_gates import may_pass
from factory.services.manuscript_resolve import decide_citation
from factory.services.project import init_project
from factory.services.reference_resolve import confirmer_ruling
from tests.helpers import SESSION
from tests.test_protocol_rules import _check, _fields, _spec

E, P, S = RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC
MODES = (E, P, S)

# gate -> (exploratory, pilot, systematic): may an agent pass it?
EXPECTED: dict[str, tuple[bool, bool, bool]] = {
    "hypotheses.lead_decide": (True, False, False),
    "hypotheses.register": (True, False, False),
    "experiments.freeze_unlock": (True, False, False),
    "mine.resolve": (True, False, False),
    "reference.link_confirm": (False, True, False),
    "import.resolution_confirm": (False, True, False),
    "manuscript.citation_confirm": (False, False, False),
    "writing.release": (True, True, False),
}

# The preset policy kind behind each row (`human` where the agent column is False for policy).
PRESET_KIND: dict[str, tuple[str, str, str]] = {
    "hypotheses.lead_decide": ("agent", "human", "human"),
    "hypotheses.register": ("agent", "human", "human"),
    "experiments.freeze_unlock": ("agent", "human", "human"),
    "mine.resolve": ("agent_audit", "human", "human"),
    "reference.link_confirm": ("human", "agent_audit", "human"),
    "import.resolution_confirm": ("human", "agent_audit", "human"),
    "manuscript.citation_confirm": ("human", "agent_audit", "human"),
    "writing.release": ("agent", "agent", "human"),
}

PROPOSER = "01JZ9Q3K5M7N8P0R2S4T6V8W99"  # a session that is neither actor's


def _mode_project(settings: Settings, clock: FixedClock, mode: RigorMode) -> Project:
    return init_project(settings, "demo", mode.value, session=SESSION, clock=clock)


def _passes(project: Project, actor: Actor, gate: str) -> bool:
    """Whether `actor` clears `gate` by the function the gate's service uses (module docstring)."""
    if gate in ("hypotheses.lead_decide", "hypotheses.register", "experiments.freeze_unlock"):
        return may_pass(project, actor, gate, proposer_sessions={PROPOSER}).ok  # type: ignore[arg-type]
    if gate == "mine.resolve":
        return not gate_issues(project, actor, gate)
    if gate in ("reference.link_confirm", "import.resolution_confirm"):
        _, issues = confirmer_ruling(
            actor,
            gate_id=gate,
            policy=effective_policy(project, gate),
            base_state=LinkState.UNCONFIRMED,
            confirmed_by=None,
            has_proposal=True,
            deciding_sessions={PROPOSER},
        )
        return not issues
    if gate == "manuscript.citation_confirm":
        try:
            decide_citation(project, "mnu_x", "k", CitationDecision.CONFIRM, actor=actor)
        except FactoryValidationError as exc:
            return not any(i.field == "actor" for i in exc.issues)
        return True
    assert gate == "writing.release"
    try:
        require_gate(project, actor, gate)
    except FactoryValidationError:
        return False
    return True


def test_expected_table_covers_the_presets_that_weaken_a_gate() -> None:
    """Every gate a preset weakens is a row here, and each row's preset kind is the real one."""
    weakened = {g for m in MODES for g in _presets(m)}
    assert weakened <= set(EXPECTED), sorted(weakened - set(EXPECTED))
    for gate, kinds in PRESET_KIND.items():
        assert tuple(preset(m, gate).kind.value for m in MODES) == kinds, gate


def _presets(mode: RigorMode) -> list[str]:
    from factory.modules.presets import PRESETS

    return list(PRESETS[mode])


@pytest.mark.parametrize("gate", sorted(EXPECTED))
@pytest.mark.parametrize("mode", MODES, ids=lambda m: m.value)
def test_agent_outcome_per_preset(
    settings: Settings, clock: FixedClock, agent: Actor, mode: RigorMode, gate: str
) -> None:
    project = _mode_project(settings, clock, mode)
    assert _passes(project, agent, gate) is EXPECTED[gate][MODES.index(mode)], (gate, mode.value)


@pytest.mark.parametrize("gate", sorted(EXPECTED))
@pytest.mark.parametrize("mode", MODES, ids=lambda m: m.value)
def test_human_control_passes_everywhere(
    settings: Settings, clock: FixedClock, human: Actor, mode: RigorMode, gate: str
) -> None:
    project = _mode_project(settings, clock, mode)
    assert _passes(project, human, gate) is True, (gate, mode.value)


def test_policy_below_a_gates_floor_is_refused_in_every_mode() -> None:
    """A `gate_policies` entry below the floor is a protocol error in every mode: `agent` on an
    `agent_audit` gate, and any weakening of a floor-human gate."""
    floors = {
        "reference.link_confirm": PolicyKind.AGENT,  # floor agent_audit
        "screening.resolve": PolicyKind.AGENT,  # floor human
        "hypotheses.close": PolicyKind.AGENT_AUDIT,  # floor human
    }
    from factory.model.gates import GatePolicies, GatePolicyEntry

    for mode in MODES:
        for gate, kind in floors.items():
            extra = {"fraction": 0.1, "minimum": 20} if kind is PolicyKind.AGENT_AUDIT else {}
            spec = _spec(
                gate_policies=GatePolicies(
                    entries=(
                        GatePolicyEntry.model_validate({"gate": gate, "policy": kind, **extra}),
                    )
                )
            )
            assert _fields(_check(spec, mode).errors) == ["gate_policies.entries.0.policy"], (
                gate,
                mode.value,
            )


def _reviewed_hypothesis(project: Project, human: Actor) -> str:
    """A draft over a card trigger, reviewed `register` by a critic session: the state in which
    only the gate stands between the draft and registration."""
    from factory.services.hypotheses import draft_hypothesis
    from factory.services.hypothesis_review import record_review, review_next
    from tests.hypothesis_helpers import (
        CRITIC,
        DRAFTER,
        card_trigger,
        exploratory_card,
        make_spec,
        promoted_lead,
    )
    from tests.test_hypothesis_review import verdict

    lead = promoted_lead(project, human, card_trigger(exploratory_card(project, human)))
    hid, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=lead))
    served = review_next(project, CRITIC)
    assert served is not None
    record_review(project, CRITIC, served.task_id, verdict())
    return hid


def test_pilot_refuses_an_agent_registration_and_accepts_the_human(
    settings: Settings, clock: FixedClock, human: Actor
) -> None:
    """Through `register_hypothesis` itself: the refusal is on field `actor`, nothing is written."""
    from factory.services.hypotheses import hypothesis_view, register_hypothesis
    from tests.hypothesis_helpers import OTHER

    project = _mode_project(settings, clock, P)
    hid = _reviewed_hypothesis(project, human)
    before = project.index.head()
    with pytest.raises(FactoryValidationError) as refused:
        register_hypothesis(project, OTHER, hid)
    assert [i.field for i in refused.value.issues] == ["actor"]
    assert project.index.head() == before
    register_hypothesis(project, human, hid)
    view = hypothesis_view(project, hid)
    assert view is not None and view.state == "registered" and view.autonomy == "human"
