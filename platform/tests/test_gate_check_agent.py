"""The agent's `check` does not carry the gate audit result (M-B review, finding 1)."""

# ruff: noqa: F811
import pytest

from factory.events.envelope import Actor
from factory.model.screening import Channel
from factory.services.check import agent_check, check
from factory.services.context import Project
from factory.services.gates import gate_audit_record, gate_audit_sample
from tests.test_gate_audit import _second_agent_confirms
from tests.test_references_resolve import extraction  # noqa: F401

LINK = "reference.link_confirm"


def _codes(report: object) -> list[tuple[str, str]]:
    return [(f.code, f.message) for f in report.findings]  # type: ignore[attr-defined]


@pytest.mark.parametrize("correct", [True, False])
def test_agent_view_is_the_same_whatever_the_label(
    project: Project, extraction: str, agent: Actor, human: Actor, correct: bool
) -> None:
    _second_agent_confirms(project, extraction, agent)
    sampled = gate_audit_sample(project, human, LINK, random_seed=4)
    gate_audit_record(
        project, human, sampled.audit_id, sampled.act_event_ids[0], correct, "n", Channel.CLI
    )
    human_codes = [c for c, _ in _codes(check(project))]
    assert ("gate-audit-error-high" in human_codes) is (not correct)
    seen = _codes(agent_check(project))
    assert "gate-audit-error-high" not in [c for c, _ in seen]
    markers = [m for c, m in seen if c == "gate-audit-reported"]
    assert markers == ["a gate audit is labelled; its result is reported to the researcher"]
    if not correct:  # the only difference between the two runs is absent from the agent's view
        assert all("0." not in m and "ceiling" not in m for _, m in seen if "gate" in m)


def test_no_marker_before_a_label(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _second_agent_confirms(project, extraction, agent)
    gate_audit_sample(project, human, LINK, random_seed=4)
    assert "gate-audit-reported" not in [c for c, _ in _codes(agent_check(project))]


def test_unlabelled_message_for_agents_carries_no_count(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterator

    from factory.services import gates
    from factory.services.gates import GateAct

    seen: list[str] = []
    for size in (2, 60):
        acts = [GateAct(LINK, "ev_" + f"{i:026d}", "agent", "S", None) for i in range(size)]

        def fake(project: Project, gate_id: str, acts: list[GateAct] = acts) -> Iterator[GateAct]:
            if gate_id == LINK:
                yield from acts

        monkeypatch.setattr(gates, "gate_acts", fake)
        gate_audit_sample(project, human, LINK, random_seed=size)
        human_text = [
            f.message for f in check(project).findings if f.code == "gate-audit-unlabelled"
        ]
        assert human_text and any(ch.isdigit() for ch in human_text[0])
        seen += [m for c, m in _codes(agent_check(project)) if c == "gate-audit-unlabelled"]
    assert len(seen) == 2 and seen[0] == seen[1]
    assert not any(ch.isdigit() for ch in seen[0])
