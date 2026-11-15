"""The gate table of slice M, written out, against the registry and the resolved policy (pilot 2,
layer 1: the floor test).

The table below is copied from `docs/specs/slice-M-modules.md` ("Gate inventory and presets" and
the ruling 4 table of later slices): floor, then exploratory, pilot and systematic. It is
independent of `presets.py` and of `test_gate_presets.EXPECTED`, so a change to a preset that the
spec does not allow fails here. A gate added to the registry without a row fails
`test_every_registry_gate_is_in_the_table`; the row is a decision, not a copy of the code.
"""

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.model.project import RigorMode
from factory.modules.contract import GatePolicy, PolicyKind
from factory.services.context import Project
from factory.services.gates import effective_policy
from factory.services.modules.default import default_modules
from factory.services.project import init_project
from tests.helpers import SESSION

H = GatePolicy(PolicyKind.HUMAN)
A = GatePolicy(PolicyKind.AGENT)
AA = GatePolicy(PolicyKind.AGENT_AUDIT, 0.1, 20)
Row = tuple[PolicyKind, GatePolicy, GatePolicy, GatePolicy]  # floor, exploratory, pilot, systematic

_HUMAN_ROW: Row = (PolicyKind.HUMAN, H, H, H)
_LINK_ROW: Row = (PolicyKind.AGENT_AUDIT, H, AA, H)

SLICE_M_TABLE: dict[str, Row] = {
    # slice M, gate inventory
    "protocol.press_confirm": _HUMAN_ROW,
    "screening.calibration_label": _HUMAN_ROW,
    "screening.resolve": _HUMAN_ROW,
    "screening.audit_label": _HUMAN_ROW,
    "extraction.resolve": _HUMAN_ROW,
    "extraction.audit_label": _HUMAN_ROW,
    "reference.link_confirm": _LINK_ROW,
    "lineage.relation_confirm": _HUMAN_ROW,
    "lineage.idea_confirm": _HUMAN_ROW,
    "intuition.review": _HUMAN_ROW,
    "intuition.source_approve": _HUMAN_ROW,
    "intuition.uses_confirm": _HUMAN_ROW,
    "miner.calibration_label": _HUMAN_ROW,
    "mine.resolve": (PolicyKind.AGENT, AA, H, H),
    # ruling 4, gates of later slices
    "import.resolution_confirm": _LINK_ROW,
    "regions.review": _HUMAN_ROW,
    "regions.member_decide": _HUMAN_ROW,
    "labels.application_confirm": _HUMAN_ROW,
    "consolidation.decide": _HUMAN_ROW,
    "terms.promote": _HUMAN_ROW,
    "inbox.withdraw": _HUMAN_ROW,
    "living.notice_assess": _HUMAN_ROW,
    "living.document_prefer": _HUMAN_ROW,
    "living.conclusion_register": _HUMAN_ROW,
    "hypotheses.lead_decide": (PolicyKind.AGENT, A, H, H),
    "hypotheses.register": (PolicyKind.AGENT, A, H, H),
    "experiments.freeze_unlock": (PolicyKind.AGENT, A, H, H),
    "experiments.accept_baseline": _HUMAN_ROW,
    "hypotheses.property_approve": _HUMAN_ROW,
    "hypotheses.assertion_confirm": _HUMAN_ROW,
    "hypotheses.contradiction_confirm": _HUMAN_ROW,
    "hypotheses.close": _HUMAN_ROW,
    "writing.release": (PolicyKind.AGENT, A, A, H),
    "writing.audit_label": _HUMAN_ROW,
    "manuscript.audit_label": _HUMAN_ROW,
    "manuscript.citation_confirm": _LINK_ROW,
}

DECLARED_AFTER_SLICE_M: frozenset[str] = frozenset(
    {
        "dedup.version_pair",
        "cards.import",
        "inbox.prioritise",
        "regions.link",
        "regions.adopt",
        "curation.decide",
    }
)
"""Gates the slice-M tables do not list. Each is a human decision with a human floor in every mode
(the same row as the Decided human gates); a gate moves out of this set into the table above, or
stays here, by a decision of the researcher, never by editing the code to match."""

MODES = tuple(RigorMode)
REGISTRY_GATES = sorted(g.gate_id for g in default_modules().gates())


def _row(gate: str) -> Row:
    if gate in SLICE_M_TABLE:
        return SLICE_M_TABLE[gate]
    return _HUMAN_ROW


def test_every_registry_gate_is_in_the_table() -> None:
    """A new gate fails here until it is given a row (or listed as declared after slice M)."""
    known = set(SLICE_M_TABLE) | DECLARED_AFTER_SLICE_M
    missing = sorted(set(REGISTRY_GATES) - known)
    assert not missing, (
        f"gate(s) {missing} are in the registry but not in the slice-M table of this test: "
        "add a row with the floor and the policy in each mode"
    )
    stale = sorted(known - set(REGISTRY_GATES))
    assert not stale, f"table rows for gates that the registry no longer declares: {stale}"
    assert not set(SLICE_M_TABLE) & DECLARED_AFTER_SLICE_M


@pytest.mark.parametrize("gate", REGISTRY_GATES)
def test_registry_floor_equals_the_table(gate: str) -> None:
    assert default_modules().gate(gate).floor is _row(gate)[0]


@pytest.mark.parametrize("gate", REGISTRY_GATES)
@pytest.mark.parametrize("mode", MODES)
def test_resolved_policy_in_each_mode_equals_the_table(
    settings: Settings, clock: FixedClock, gate: str, mode: RigorMode
) -> None:
    """The policy a project of `mode` resolves for the gate (no protocol entry: the preset)."""
    project: Project = init_project(settings, "demo", mode.value, session=SESSION, clock=clock)
    _, exploratory, pilot, systematic = _row(gate)
    expected = {
        RigorMode.EXPLORATORY: exploratory,
        RigorMode.PILOT: pilot,
        RigorMode.SYSTEMATIC: systematic,
    }[mode]
    assert effective_policy(project, gate) == expected, f"{gate} in {mode.value}"
