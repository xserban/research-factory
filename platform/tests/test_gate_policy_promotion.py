"""Ruling 8: gate policies weaker than a stricter mode's preset are promotion gaps (review 4)."""

# ruff: noqa: F811
from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.modules.contract import PolicyKind
from factory.services.check import check
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.protocol_rules import gate_policy_gaps
from tests.gate_helpers import amend_gate_policies, entry
from tests.test_references_resolve import extraction  # noqa: F401

LINK = "reference.link_confirm"


def _codes(project: Project, mode: RigorMode | None) -> list[str]:
    return [
        f.code for f in check(project, promote_to=mode).findings if f.code.startswith("gate-policy")
    ]


def test_preset_equal_policy_is_a_gap_only_for_systematic(
    project: Project, extraction: str, human: Actor
) -> None:
    amend_gate_policies(project, human, entry(LINK, PolicyKind.AGENT_AUDIT, 0.1, 20))
    spec = current_protocol(project).spec  # type: ignore[union-attr]
    assert gate_policy_gaps(spec, RigorMode.PILOT) == []
    assert len(gate_policy_gaps(spec, RigorMode.SYSTEMATIC)) == 1
    assert _codes(project, None) == []
    assert _codes(project, RigorMode.PILOT) == []
    assert _codes(project, RigorMode.SYSTEMATIC) == ["gate-policy-below-systematic-preset"]


def test_human_entry_is_never_a_gap(project: Project, extraction: str, human: Actor) -> None:
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    assert _codes(project, RigorMode.SYSTEMATIC) == []
