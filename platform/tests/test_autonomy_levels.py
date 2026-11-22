"""Autonomy profiles, the supervised pins, the trust ledger and the deferred review queue
(plan 2026-11-20-tiers-and-autonomy, contracts C4 to C6). The level is injected through the
`services.project.project_levels` seam (lane L1 owns the real reader); `attended` is the
default and must change nothing."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.levels import AutonomyLevel
from factory.model.project import RigorMode
from factory.model.screening import Channel
from factory.modules import autonomy
from factory.modules.autonomy import lower_bound, profile, resolve_policy
from factory.modules.contract import GatePolicy, PolicyKind
from factory.modules.presets import AGENT, HUMAN, LINK_AUDIT, preset
from factory.services import deferred_review, gate_trust, gates
from factory.services import project as project_service
from factory.services.context import Project
from factory.services.gate_trust import trust_state
from factory.services.gates import GateAct, effective_policy
from factory.services.human_queue import Gate, human_queue

LINK = "reference.link_confirm"
A1 = "ev_" + "0" * 25 + "1"
A2 = "ev_" + "0" * 25 + "2"
S, P, E = RigorMode.SYSTEMATIC, RigorMode.PILOT, RigorMode.EXPLORATORY


def _level(monkeypatch: pytest.MonkeyPatch, level: AutonomyLevel) -> None:
    monkeypatch.setattr(
        project_service,
        "project_levels",
        lambda project: SimpleNamespace(autonomy_level=level, tier=None, rigor_mode=None),
        raising=False,
    )


def _acts(monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> None:
    acts = [GateAct(LINK, i, "agent", "S", None) for i in ids]

    def fake(project: Project, gate_id: str) -> Iterator[GateAct]:
        if gate_id == LINK:
            yield from acts

    for module in (gates, gate_trust, deferred_review):
        monkeypatch.setattr(module, "gate_acts", fake)


# --- the lattice -------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [E, P, S])
def test_attended_has_the_empty_profile_and_keeps_the_entry(mode: RigorMode) -> None:
    assert profile(AutonomyLevel.ATTENDED, mode) == {}
    weak = GatePolicy(PolicyKind.AGENT)
    assert resolve_policy(AutonomyLevel.ATTENDED, mode, "hypotheses.register", weak) == weak
    assert resolve_policy(AutonomyLevel.ATTENDED, mode, "hypotheses.register", None) == preset(
        mode, "hypotheses.register"
    )


def test_supervised_lowers_exactly_the_agent_audit_gates() -> None:
    gates_ = autonomy.SUPERVISED_AUDIT_GATES
    assert gates_ == {
        "mine.resolve",
        "reference.link_confirm",
        "import.resolution_confirm",
        "manuscript.citation_confirm",
    }
    found = profile(AutonomyLevel.SUPERVISED, S)
    assert set(found) == gates_ and all(p == LINK_AUDIT for p in found.values())
    assert "hypotheses.register" not in found  # never lowered to `agent`


def test_supervised_never_raises_a_weaker_preset() -> None:
    assert profile(AutonomyLevel.SUPERVISED, E)["mine.resolve"] == preset(E, "mine.resolve")


def test_a_protocol_cannot_go_below_the_profile() -> None:
    assert resolve_policy(AutonomyLevel.SUPERVISED, S, LINK, AGENT) == LINK_AUDIT
    assert resolve_policy(AutonomyLevel.SUPERVISED, S, LINK, HUMAN) == HUMAN


def test_autonomous_floor_lowers_and_is_a_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    assert autonomy.AUTONOMOUS_FLOOR == {}  # shipped empty until decision D3
    assert profile(AutonomyLevel.AUTONOMOUS, S) == profile(AutonomyLevel.SUPERVISED, S)
    monkeypatch.setattr(autonomy, "AUTONOMOUS_FLOOR", {"hypotheses.lead_decide": LINK_AUDIT})
    assert lower_bound(AutonomyLevel.AUTONOMOUS, S, "hypotheses.lead_decide") == LINK_AUDIT
    assert (
        resolve_policy(AutonomyLevel.AUTONOMOUS, S, "hypotheses.lead_decide", AGENT) == LINK_AUDIT
    )
    assert lower_bound(AutonomyLevel.SUPERVISED, S, "hypotheses.lead_decide") == HUMAN


# --- the project reader ------------------------------------------------------------------


def test_effective_policy_is_unchanged_under_attended(project: Project) -> None:
    assert effective_policy(project, LINK) == preset(P, LINK)
    assert effective_policy(project, "hypotheses.register") == HUMAN


def test_supervised_project_reads_the_profile(
    settings: object, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _level(monkeypatch, AutonomyLevel.SUPERVISED)
    assert effective_policy(project, "mine.resolve") == LINK_AUDIT  # pilot preset is human
    assert effective_policy(project, "hypotheses.register") == HUMAN


# --- trust ledger ------------------------------------------------------------------------


def test_trust_state_thresholds() -> None:
    assert trust_state(0, 0) == "ok"
    assert trust_state(20, 1) == "ok"  # 5%: not above
    assert trust_state(20, 2) == "watch"  # 10%: above 5%, not above 10%
    assert trust_state(19, 1) == "ok"  # above 5% but under 20 audited
    assert trust_state(20, 3) == "pause"
    assert trust_state(2, 1) == "pause"  # pause has no minimum


def test_ledger_counts_human_and_agent_labels_apart(
    project: Project,
    human: Actor,
    agent_other: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _level(monkeypatch, AutonomyLevel.SUPERVISED)
    _acts(monkeypatch, [A1, A2])
    drawn = gates.gate_audit_sample_platform(project, LINK)
    assert len(drawn.act_event_ids) == 2
    first, second = drawn.act_event_ids
    gates.gate_audit_record_agent(project, agent_other, drawn.audit_id, first, False, "x")
    [row] = gate_trust.trust_ledger(project)
    assert (row.closed_by_agent, row.audited, row.overturned) == (2, 0, 0)
    assert (row.agent_audited, row.agent_overturned) == (1, 1) and row.state == "ok"
    gates.gate_audit_record(project, human, drawn.audit_id, first, False, "no", Channel.CLI)
    gates.gate_audit_record(project, human, drawn.audit_id, second, True, None, Channel.CLI)
    [row] = gate_trust.trust_ledger(project)
    assert (row.audited, row.overturned, row.overturn_rate, row.state) == (2, 1, 0.5, "pause")


def test_platform_draw_and_agent_label_are_refused_under_attended(
    project: Project, agent_other: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acts(monkeypatch, [A1])
    with pytest.raises(FactoryValidationError):
        gates.gate_audit_sample_platform(project, LINK)
    with pytest.raises(FactoryValidationError):
        gates.gate_audit_record_agent(project, agent_other, "gau_x", A1, True, None)


def test_agent_cannot_label_a_human_drawn_sample(
    project: Project, human: Actor, agent_other: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _level(monkeypatch, AutonomyLevel.SUPERVISED)
    _acts(monkeypatch, [A1])
    drawn = gates.gate_audit_sample(project, human, LINK, random_seed=1)
    with pytest.raises(FactoryValidationError) as raised:
        gates.gate_audit_record_agent(project, agent_other, drawn.audit_id, A1, True, None)
    assert [i.field for i in raised.value.issues] == ["audit_id"]


# --- deferred review ---------------------------------------------------------------------


def test_queue_is_unchanged_under_attended(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acts(monkeypatch, [A1])
    gates.gate_audit_sample(project, human, LINK, random_seed=1)
    assert deferred_review.deferred_items(project) == ()
    assert all(i.gate is not Gate.DEFERRED_REVIEW for i in human_queue(project).items)


def test_item_appears_and_a_human_decides_it(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _level(monkeypatch, AutonomyLevel.SUPERVISED)
    _acts(monkeypatch, [A1])
    drawn = gates.gate_audit_sample_platform(project, LINK)
    [item] = deferred_review.deferred_items(project)
    assert (item.gate_id, item.act_event_id, item.trust_state) == (LINK, A1, "watch")
    [queued] = [i for i in human_queue(project).items if i.gate is Gate.DEFERRED_REVIEW]
    assert queued.count == 1
    deferred_review.decide_deferred(
        project, human, drawn.audit_id, A1, "overturn", "wrong", Channel.CLI
    )
    assert deferred_review.deferred_items(project) == ()
    [row] = gate_trust.trust_ledger(project)
    assert (row.audited, row.overturned) == (1, 1)


def test_a_non_human_decide_is_refused_and_writes_nothing(
    project: Project, agent_other: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.events.reader import read_all

    _level(monkeypatch, AutonomyLevel.SUPERVISED)
    _acts(monkeypatch, [A1])
    drawn = gates.gate_audit_sample_platform(project, LINK)
    before = len(read_all(project.paths.events_dir, project.catalog))
    for actor in (agent_other, project.system_actor()):
        with pytest.raises(FactoryValidationError) as raised:
            deferred_review.decide_deferred(
                project, actor, drawn.audit_id, A1, "correct", None, Channel.CLI
            )
        assert "actor" in [i.field for i in raised.value.issues]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_the_cli_acts_have_access_rows() -> None:
    from factory.services.access import TOOL_PERMISSIONS, Permission

    assert TOOL_PERMISSIONS["cli:review deferred decide"] is Permission.HUMAN_LABEL
    assert TOOL_PERMISSIONS["cli:review deferred list"] is Permission.PROJECT_READ


# --- finding I2: the agent audit is wired ------------------------------------------------


def test_agent_audit_gate_with_no_audit_drawn_is_not_ok(
    project: Project, agent_other: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent acts at an agent_audit gate with no sample drawn are `watch` (reason named), not
    `ok`; a drawn but unlabelled sample is `watch` too; any label (agent or human) lifts it."""
    _level(monkeypatch, AutonomyLevel.SUPERVISED)
    _acts(monkeypatch, [A1, A2])
    [row] = gate_trust.trust_ledger(project)
    assert row.state == "watch" and row.reason == "no audit drawn"
    drawn = gates.gate_audit_sample_platform(project, LINK)
    [row] = gate_trust.trust_ledger(project)
    assert row.state == "watch" and row.reason == "audit drawn, nothing labelled yet"
    first = drawn.act_event_ids[0]
    gates.gate_audit_record_agent(project, agent_other, drawn.audit_id, first, True, None)
    [row] = gate_trust.trust_ledger(project)
    assert row.state == "ok" and row.reason is None


def test_pending_audit_items_lists_platform_drawn_unlabelled_acts(
    project: Project, agent_other: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _level(monkeypatch, AutonomyLevel.SUPERVISED)
    _acts(monkeypatch, [A1, A2])
    assert gate_trust.pending_audit_items(project) == ()
    drawn = gates.gate_audit_sample_platform(project, LINK)
    pending = gate_trust.pending_audit_items(project)
    assert {i.act_event_id for i in pending} == set(drawn.act_event_ids)
    assert {i.audit_id for i in pending} == {drawn.audit_id}
    gates.gate_audit_record_agent(
        project, agent_other, drawn.audit_id, drawn.act_event_ids[0], True, None
    )
    left = gate_trust.pending_audit_items(project)
    assert [i.act_event_id for i in left] == [drawn.act_event_ids[1]]


def test_the_audit_stage_alone_may_label() -> None:
    from factory.services.runner import STAGES

    for stage, spec in STAGES.items():
        has = "mcp__factory__gate_audit_label" in spec.tools
        assert has == (stage == "conduct-audit"), stage
