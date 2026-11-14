"""Every human gate refuses an agent and a system actor, through the gate's own service act, and
writes nothing (pilot 2, layer 1: the negative test per gate).

The test iterates the gate registry: a gate added later has no entry in `GATE_ACTS`, so
`test_every_registry_gate_has_an_act_entry` fails with the gate named, and the table gets one row.
The acts go through the service functions (not the CLI or MCP), with the smallest arguments that
reach the actor check: ids that name nothing, because an unknown id is refused after the actor
check in most services and the actor check is what is under test.

Entries marked `actor_first=False` are services that check a prerequisite before the actor (an
unknown experiment, no protocol, no schema, no calibration). With no world built they show a
refusal and an unchanged log, not the actor refusal itself; they are weak coverage and are listed
in the report of this plan.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.curation import CurationDecision
from factory.model.directions import Conditions, DirectionReason
from factory.model.drafts import AuditLabel
from factory.model.extraction import MinerScope
from factory.model.lineage import LineageDecision
from factory.model.notices import AssessmentDecision
from factory.model.project import RigorMode
from factory.model.screening import Channel
from factory.modules.contract import PolicyKind
from factory.modules.presets import preset
from factory.regions.rules import MemberType
from factory.services import (
    agreement,
    audit,
    calibration,
    card_import,
    cards,
    concepts,
    conclusions,
    directions,
    draft_audit,
    experiments,
    extraction_agreement,
    extraction_audit,
    finders,
    hypotheses,
    ideas,
    inbox,
    interpretations,
    labels,
    leads,
    manuscript_audit,
    miner_gold,
    notices,
    properties,
    protocol,
    region_adoption,
    regions,
    relations,
    terms,
    version_pairs,
    versions,
)
from factory.services import curation as curation_service
from factory.services.context import Project
from factory.services.gates import effective_policy, require_gate
from factory.services.modules.default import default_modules
from factory.services.project import init_project
from tests.helpers import SESSION

CLI = Channel.CLI
NOWHERE = Path("/nonexistent-source-project")


@dataclass(frozen=True)
class Act:
    """One attempt at a gate's act as `actor`, through the service."""

    run: Callable[[Project, Actor], object]
    actor_first: bool = True


def _weak(run: Callable[[Project, Actor], object]) -> Act:
    return Act(run, actor_first=False)


# None: the gate's pilot policy is not `human` (an agent may pass it there); the entry is checked
# by `test_entries_match_the_pilot_policy`, so it cannot go stale silently.
GATE_ACTS: dict[str, Act | None] = {
    "protocol.press_confirm": Act(lambda p, a: protocol.confirm_press(p, a, "rev_x", ["r"])),
    "dedup.version_pair": Act(
        lambda p, a: version_pairs.decide_pair(p, a, "w1", "w2", "same", "r")
    ),
    "screening.calibration_label": Act(
        lambda p, a: calibration.label_calibration(p, a, "w1", "include", None, CLI)
    ),
    "screening.resolve": _weak(
        lambda p, a: agreement.resolve_disagreement(p, a, "w1", "include", None, "r", CLI)
    ),
    "screening.audit_label": Act(
        lambda p, a: audit.audit_record(p, a, "aud_x", "w1", "include", None, CLI)
    ),
    "extraction.resolve": _weak(
        lambda p, a: extraction_agreement.resolve_extraction(p, a, "w1", "k", None, "a", "r", CLI)
    ),
    "extraction.audit_label": Act(
        lambda p, a: extraction_audit.extraction_audit_record(
            p, a, "aud_x", "w1", "k", "f", True, "n", CLI
        )
    ),
    "hypotheses.assertion_confirm": Act(
        lambda p, a: cards.decide_assertion(p, a, "asr_x", "confirm", "r")
    ),
    "cards.import": Act(lambda p, a: card_import.import_card(p, a, NOWHERE, "crd_x")),
    "reference.link_confirm": None,
    "import.resolution_confirm": None,
    "inbox.withdraw": Act(lambda p, a: inbox.withdraw_link(p, a, "itm_x", "r")),
    "inbox.prioritise": Act(lambda p, a: inbox.prioritise(p, a, "itm_x")),
    "living.notice_assess": Act(
        lambda p, a: notices.assess_notice(
            p, a, "ntc_x", AssessmentDecision.EXCLUDE, rationale="r", channel=CLI
        )
    ),
    "living.document_prefer": Act(lambda p, a: versions.prefer_document(p, a, "w1", "doc_x", "r")),
    "living.conclusion_register": Act(
        lambda p, a: conclusions.register_conclusion(p, a, "a statement", [], None)
    ),
    "lineage.relation_confirm": Act(
        lambda p, a: relations.decide_relation(p, a, "rel_x", LineageDecision.CONFIRM, "r")
    ),
    "lineage.idea_confirm": Act(
        lambda p, a: ideas.decide_idea(p, a, "ide_x", LineageDecision.CONFIRM, "r")
    ),
    "intuition.review": Act(
        lambda p, a: interpretations.review_interpretation(p, a, "int_x", "reviewed", "n", CLI)
    ),
    "intuition.source_approve": Act(
        lambda p, a: concepts.decide_concept_source(p, a, "cpt_x", "approve", "n", CLI)
    ),
    "intuition.uses_confirm": Act(
        lambda p, a: concepts.decide_concept_link(p, a, "lnk_x", "confirm", "r", CLI)
    ),
    "hypotheses.property_approve": Act(
        lambda p, a: properties.decide_property(p, a, "key", "approve", "r")
    ),
    "hypotheses.contradiction_confirm": Act(
        lambda p, a: finders.decide_contradiction(p, a, "ctr_x", "confirm", "r")
    ),
    "regions.review": Act(lambda p, a: regions.review_region(p, a, "R@x", "reviewed")),
    "regions.member_decide": Act(
        lambda p, a: regions.decide_member(p, a, "reg_x", MemberType.WORK, "w1", "add")
    ),
    "regions.link": Act(lambda p, a: regions.link_regions(p, a, "related", "R@a", "R@b")),
    "regions.adopt": Act(lambda p, a: region_adoption.adopt_region(p, a, NOWHERE, "R@x")),
    "miner.calibration_label": _weak(
        lambda p, a: miner_gold.label_miner_calibration(
            p, a, "mcl_x", "w1", [], empty=True, channel=CLI
        )
    ),
    "mine.resolve": _weak(
        lambda p, a: extraction_agreement.resolve_extraction(
            p, a, "w1", "k", None, "a", "r", CLI, scope=MinerScope("m-x")
        )
    ),
    "hypotheses.register": _weak(lambda p, a: hypotheses.register_hypothesis(p, a, "hyp_x")),
    "hypotheses.lead_decide": _weak(lambda p, a: leads.decide_lead(p, a, "led_x", "promote")),
    "labels.application_confirm": Act(
        lambda p, a: labels.decide_application(p, a, "app_x", "confirm")
    ),
    "consolidation.decide": Act(lambda p, a: labels.merge_labels(p, a, "a", "b", "r")),
    "terms.promote": Act(
        lambda p, a: terms.promote_term(
            p, a, name="term", definition="d", applies_to=[MemberType.WORK]
        )
    ),
    "experiments.freeze_unlock": _weak(lambda p, a: experiments.freeze_experiment(p, a, "exp_x")),
    "experiments.accept_baseline": _weak(
        lambda p, a: experiments.accept_baseline(p, a, "exp_x", "row", "r")
    ),
    "hypotheses.close": Act(
        lambda p, a: directions.close_direction(
            p, a, "a direction", DirectionReason.OTHER, Conditions(), ["key"]
        )
    ),
    "curation.decide": Act(
        lambda p, a: curation_service.decide_proposal(
            p, a, "cur_x", CurationDecision.ACCEPTED, rationale="r"
        )
    ),
    "writing.release": None,
    "writing.audit_label": Act(
        lambda p, a: draft_audit.record_audit(
            p, "aud_x", "vrd_x", AuditLabel.CORRECT, None, actor=a
        )
    ),
    "manuscript.citation_confirm": None,
    "manuscript.audit_label": Act(
        lambda p, a: manuscript_audit.record_audit(p, "vrd_x", AuditLabel.CORRECT, None, actor=a)
    ),
}

REGISTRY_GATES = sorted(g.gate_id for g in default_modules().gates())
PILOT_HUMAN_GATES = sorted(
    g for g in REGISTRY_GATES if preset(RigorMode.PILOT, g).kind is PolicyKind.HUMAN
)
MODES = tuple(RigorMode)


def _log(project: Project) -> dict[str, bytes]:
    """Every event file of the project, by relative path: the log byte for byte."""
    root = project.paths.events_dir
    return {
        str(f.relative_to(root)): f.read_bytes() for f in sorted(root.rglob("*")) if f.is_file()
    }


def _actor(kind: str, project: Project, agent: Actor) -> Actor:
    return agent if kind == "agent" else project.system_actor()


def test_every_registry_gate_has_an_act_entry() -> None:
    """A gate added to the registry without a row here is not covered: add its act."""
    missing = sorted(set(REGISTRY_GATES) - set(GATE_ACTS))
    assert not missing, (
        f"gate(s) {missing} are in the registry but have no entry in GATE_ACTS: add a callable "
        "that attempts the gate's act through the service (or None if its pilot policy is not "
        "human)"
    )
    stale = sorted(set(GATE_ACTS) - set(REGISTRY_GATES))
    assert not stale, f"GATE_ACTS has entries for gates that are not in the registry: {stale}"


@pytest.mark.parametrize("gate", REGISTRY_GATES)
def test_entries_match_the_pilot_policy(project: Project, gate: str) -> None:
    """An act entry exists exactly for the gates whose pilot policy is human."""
    human = effective_policy(project, gate).kind is PolicyKind.HUMAN
    assert (GATE_ACTS.get(gate) is not None) is human, (
        f"{gate}: pilot policy is "
        f"{effective_policy(project, gate).kind.value}; its GATE_ACTS entry must be "
        f"{'an Act' if human else 'None'}"
    )


@pytest.mark.parametrize("kind", ["agent", "system"])
@pytest.mark.parametrize("gate", PILOT_HUMAN_GATES)
def test_gate_act_refused_for_non_human_and_nothing_written(
    project: Project, agent: Actor, gate: str, kind: str
) -> None:
    entry = GATE_ACTS[gate]
    assert entry is not None, f"{gate} is human in pilot but GATE_ACTS has None"
    actor = _actor(kind, project, agent)
    before = _log(project)
    with pytest.raises(FactoryValidationError) as refused:
        entry.run(project, actor)
    fields = [issue.field for issue in refused.value.issues]
    assert fields, f"{gate} as {kind}: the refusal carries no issue"
    if entry.actor_first:
        assert "actor" in fields, f"{gate} as {kind}: refused on {fields}, not on `actor`"
    assert _log(project) == before, f"{gate} as {kind}: the event log changed"


@pytest.mark.parametrize("kind", ["agent", "system"])
@pytest.mark.parametrize("mode", MODES)
def test_require_gate_refuses_non_humans_at_every_human_policy(
    settings: Settings, clock: FixedClock, agent: Actor, mode: RigorMode, kind: str
) -> None:
    """In each rigor mode, at every registry gate whose effective policy is human: refused on field
    `actor`, and the log is unchanged. At a gate that is not human the same actor is not refused
    on `actor`."""
    project = init_project(settings, "demo", mode.value, session=SESSION, clock=clock)
    actor = _actor(kind, project, agent)
    before = _log(project)
    wrong: list[str] = []
    for gate in REGISTRY_GATES:
        human = effective_policy(project, gate).kind is PolicyKind.HUMAN
        try:
            require_gate(project, actor, gate)
            refused_on_actor = False
        except FactoryValidationError as exc:
            refused_on_actor = any(i.field == "actor" for i in exc.issues)
        if refused_on_actor is not human:
            wrong.append(gate)
    assert not wrong, f"{kind} in {mode.value}: wrong refusal at {wrong}"
    assert _log(project) == before
