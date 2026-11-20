"""Hand-written (forged) events against the projectors' guards (test-strength audit).

No service writes an event that a projector refuses to fold, so each guard is dead code to a
service-driven test: removing it breaks nothing. Here the event is appended through the real log by
hand. Every case asserts that the fold changes nothing but the `events` tables, that
`index.rebuild()` gives the state hash `sync()` reached, and (a control) that the same event written
as the right actor does fold, so a refusal is not a side effect of a malformed fixture.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import gzip
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.mining.compile import miner_digest
from factory.mining.spec import spec_to_json
from factory.model.base import StrictModel
from factory.model.gate_audit import GateAuditLabelled, GateAuditSampled
from factory.model.hypotheses import (
    AbandonReason,
    HypothesisAbandoned,
    HypothesisConcluded,
    HypothesisDrafted,
    HypothesisRegistered,
    HypothesisReviewed,
    LeadDecided,
    LeadRecorded,
    ModelCutoffDeclared,
    Trigger,
    TriggerKind,
    hypothesis_version,
)
from factory.model.labels import (
    ConsolidationDecided,
    ConsolidationPassCompleted,
    ConsolidationPassStarted,
    ConsolidationProposed,
    LabelApplicationDecided,
    LabelApplied,
    LabelMerged,
    LabelUnmerged,
    LabelWithdrawn,
    TermPromoted,
    TermRetired,
    TermRevised,
    label_key,
)
from factory.model.miner_calibration import (
    CalibrationUnit,
    MinerCalibrationDrawn,
    MinerCalibrationLabelled,
)
from factory.model.miners import MinerRegistered
from factory.model.regions import (
    RegionLinked,
    RegionMemberDecided,
    RegionReviewed,
    RegionSnapshotTaken,
)
from factory.model.screening import Channel
from factory.modules.contract import PolicyKind
from factory.regions.rules import MemberType
from factory.services.context import Project
from factory.services.hypotheses import (
    abandon_hypothesis,
    conclude_hypothesis,
    draft_hypothesis,
    register_hypothesis,
)
from factory.services.hypothesis_review import record_review, review_next
from factory.services.leads import record_lead
from tests.evaluation_helpers import REFUTED, report_runs, unlocked
from tests.experiment_helpers import XW, xw
from tests.helpers import S2, SESSION
from tests.hypothesis_helpers import (
    CRITIC,
    DRAFTER,
    HW,
    LEAD_AUTHOR,
    OTHER,
    card_trigger,
    exploratory_card,
    gw,
    hw,
    lead_input,
    make_spec,
)
from tests.miner_helpers import method_vision
from tests.test_hypothesis_review import verdict

SKIP = {"events", "event_refs", "meta", "sync_state"}


def ulid(n: int) -> str:
    return f"01JZ9Q3K5M7N8P0R2S4T6V8W{n:02d}"


def fold_state(project: Project) -> dict[str, list[str]]:
    """Every projected row outside the event tables, per table."""
    project.index.sync()
    with project.index.connect() as conn:
        names = [
            str(r[0])
            for r in conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            )
        ]
        return {
            n: sorted(repr(tuple(r)) for r in conn.execute(text(f'SELECT * FROM "{n}"')))
            for n in names
            if n not in SKIP
        }


def forge(project: Project, type_: str, model: StrictModel, actor: Actor) -> str:
    """Append one hand-written event through the real log (what a service would never write)."""
    blob = None if actor.kind == "human" else project.blobs.put_json({"forged": True})
    event = project.events.make(type_, model, actor, input_blob=blob)
    project.record([event])
    return event.id


def inert(project: Project, type_: str, model: StrictModel, actor: Actor) -> None:
    """The fold of this event changes nothing, and a rebuild reproduces the synced state."""
    before = fold_state(project)
    forge(project, type_, model, actor)
    assert fold_state(project) == before, f"{type_} by {actor.kind} {actor.session} folded"
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    assert fold_state(project) == before


def folds(project: Project, type_: str, model: StrictModel, actor: Actor) -> str:
    """Control: the event written by the right actor changes the projection."""
    before = fold_state(project)
    event_id = forge(project, type_, model, actor)
    assert fold_state(project) != before, f"{type_} by {actor.kind} did not fold"
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    return event_id


def settled(project: Project, type_: str, model: StrictModel, actor: Actor) -> None:
    """The event is logged, `sync()` and `rebuild()` do not raise and agree."""
    forge(project, type_, model, actor)
    project.index.sync()
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


AGENT = OTHER  # session S4: neither the drafter's nor the lead author's nor the critic's


def applied(n: int = 1, label: str = "Alpha", **over: Any) -> LabelApplied:
    body: dict[str, Any] = {
        "application_id": f"lbl_{ulid(n)}",
        "target_type": MemberType.WORK,
        "target": "rf:work-1",
        "text": label,
        "key": label_key(label),
        "status": "stated",
        "origin": "agent",
    }
    body.update(over)
    return LabelApplied(**body)


def promoted(n: int = 1, **over: Any) -> TermPromoted:
    body: dict[str, Any] = {
        "term_id": f"trm_{ulid(n)}",
        "name": "Alpha",
        "definition": "A thing.",
        "applies_to": (MemberType.WORK,),
    }
    body.update(over)
    return TermPromoted(**body)


# --- Acts that only a human may fold (no precondition beyond the setup) ---

Case = Callable[[Project, Actor], tuple[str, StrictModel]]


def _region_reviewed(p: Project, h: Actor) -> tuple[str, StrictModel]:
    return "region.reviewed", RegionReviewed(
        version="R@0badcafe", state="reviewed", self_reviewed=False
    )


def _region_decided(p: Project, h: Actor) -> tuple[str, StrictModel]:
    return "region.member_decided", RegionMemberDecided(
        region_id=f"reg_{ulid(1)}", member_type=MemberType.WORK, member="w1", decision="add"
    )


def _region_linked(p: Project, h: Actor) -> tuple[str, StrictModel]:
    return "region.linked", RegionLinked(
        link_type="related", source="R@00000001", target="R@00000002", note="alike"
    )


def _label_decided(p: Project, h: Actor) -> tuple[str, StrictModel]:
    forge(p, "label.applied", applied(), h)
    return "label.application_decided", LabelApplicationDecided(
        application_id=f"lbl_{ulid(1)}", decision="confirm"
    )


def _label_merged(p: Project, h: Actor) -> tuple[str, StrictModel]:
    return "label.merged", LabelMerged(into_key="beta", from_key="alpha", reason="same")


def _label_unmerged(p: Project, h: Actor) -> tuple[str, StrictModel]:
    merge = forge(p, "label.merged", LabelMerged(into_key="beta", from_key="alpha", reason="s"), h)
    return "label.unmerged", LabelUnmerged(merge_event=merge, reason="no")


def _term_promoted(p: Project, h: Actor) -> tuple[str, StrictModel]:
    return "term.promoted", promoted()


def _term_revised(p: Project, h: Actor) -> tuple[str, StrictModel]:
    first = forge(p, "term.promoted", promoted(), h)
    return "term.revised", TermRevised(
        **promoted(definition="Better.").model_dump(), supersedes=first
    )


def _term_retired(p: Project, h: Actor) -> tuple[str, StrictModel]:
    forge(p, "term.promoted", promoted(), h)
    return "term.retired", TermRetired(term_id=f"trm_{ulid(1)}", reason="gone")


def _consolidation_decided(p: Project, h: Actor) -> tuple[str, StrictModel]:
    return "consolidation.decided", ConsolidationDecided(
        pass_id=f"cns_{ulid(1)}", cluster_index=0, decision="skip", reason="not now"
    )


def _cutoff(p: Project, h: Actor) -> tuple[str, StrictModel]:
    from datetime import date

    return "model.cutoff_declared", ModelCutoffDeclared(
        model="model-x", cutoff=date(2025, 1, 1), source="card"
    )


HUMAN_ONLY: dict[str, Case] = {
    "region.reviewed": _region_reviewed,
    "region.member_decided": _region_decided,
    "region.linked": _region_linked,
    "label.application_decided": _label_decided,
    "label.merged": _label_merged,
    "label.unmerged": _label_unmerged,
    "term.promoted": _term_promoted,
    "term.revised": _term_revised,
    "term.retired": _term_retired,
    "consolidation.decided": _consolidation_decided,
    "model.cutoff_declared": _cutoff,
}


@pytest.mark.parametrize("name", sorted(HUMAN_ONLY))
def test_human_act_by_an_agent_does_not_fold(project: Project, human: Actor, name: str) -> None:
    type_, model = HUMAN_ONLY[name](project, human)
    inert(project, type_, model, AGENT)
    folds(project, type_, model, human)


def test_abandon_and_conclusion_by_an_agent_do_not_fold(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    hw = xw  # the hypothesis of the experiment world (`hw.hid`)
    inert(
        project,
        "hypothesis.abandoned",
        HypothesisAbandoned(hypothesis_id=hw.hid, reason=AbandonReason.OTHER, note="n"),
        AGENT,
    )
    # A conclusion folds only after a folded conclusive evaluation (5cc44fe5, review I2): record a
    # real one, so the agent's conclusion below is inert because of its actor, not for want of it.
    report_runs(project, human, tmp_path, unlocked(project, human, xw), REFUTED)
    inert(
        project,
        "hypothesis.concluded",
        HypothesisConcluded(hypothesis_id=hw.hid, text="done"),
        AGENT,
    )
    folds(
        project,
        "hypothesis.concluded",
        HypothesisConcluded(hypothesis_id=hw.hid, text="done"),
        human,
    )


def test_first_abandonment_stands(project: Project, human: Actor, hw: HW) -> None:
    abandon = HypothesisAbandoned(hypothesis_id=hw.hid, reason=AbandonReason.OTHER, note="first")
    first = folds(project, "hypothesis.abandoned", abandon, human)
    inert(
        project,
        "hypothesis.abandoned",
        HypothesisAbandoned(hypothesis_id=hw.hid, reason=AbandonReason.OTHER, note="second"),
        human,
    )
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT abandoned_event_id FROM hypotheses WHERE hypothesis_id = :h"),
            {"h": hw.hid},
        ).scalar()
    assert row == first


# --- Lead decisions ---


def test_lead_decision_must_match_the_policy_in_force(
    project: Project, human: Actor, hw: HW
) -> None:
    """Pilot: the gate is human. Only a human act under a human policy folds."""
    discard = {"decision": "discard", "reason": "duplicate"}
    inert(
        project,
        "lead.decided",
        LeadDecided(lead_id=hw.lead, policy=PolicyKind.HUMAN, **discard),
        AGENT,
    )
    # a human act recorded under a policy that is not in force
    inert(
        project,
        "lead.decided",
        LeadDecided(lead_id=hw.lead, policy=PolicyKind.AGENT, **discard),
        human,
    )
    inert(
        project,
        "lead.decided",
        LeadDecided(lead_id=hw.lead, policy=PolicyKind.AGENT, **discard),
        AGENT,
    )
    folds(
        project,
        "lead.decided",
        LeadDecided(lead_id=hw.lead, policy=PolicyKind.HUMAN, **discard),
        human,
    )


def test_lead_decision_of_an_unknown_lead_changes_nothing(project: Project, human: Actor) -> None:
    unknown = f"led_{ulid(7)}"
    inert(
        project,
        "lead.decided",
        LeadDecided(lead_id=unknown, decision="park", policy=PolicyKind.HUMAN),
        human,
    )


def test_agent_policy_refuses_the_leads_own_author(explore_project: Project, human: Actor) -> None:
    """Exploratory: the lead gate is `agent`, but never for the session that wrote the lead."""
    p = explore_project
    card = exploratory_card(p, human)
    lead = record_lead(p, LEAD_AUTHOR, lead_input("A lead", card_trigger(card)))
    park = LeadDecided(lead_id=lead, decision="park", policy=PolicyKind.AGENT)
    inert(p, "lead.decided", park, LEAD_AUTHOR)
    folds(p, "lead.decided", park, AGENT)


# --- Registration ---


def _review(project: Project) -> str:
    served = review_next(project, CRITIC)
    assert served is not None
    return record_review(project, CRITIC, served.task_id, verdict("register"))


def _registration(hw: HW, review: str | None, **over: Any) -> HypothesisRegistered:
    body: dict[str, Any] = {
        "hypothesis_id": hw.hid,
        "h_version": hw.version,
        "review_event_id": review,
        "policy": PolicyKind.HUMAN,
        "autonomy": "human",
        "flags": (),
    }
    body.update(over)
    return HypothesisRegistered(**body)


def _forged_review(hw: HW, **over: Any) -> HypothesisReviewed:
    body: dict[str, Any] = {
        "hypothesis_id": hw.hid,
        "h_version": hw.version,
        "items": verdict("register").items,
        "recommend": "register",
        "critic_session": CRITIC.session,
        "critic_model": CRITIC.model,
        "task_id": "tsk_forged",
    }
    body.update(over)
    return HypothesisReviewed(**body)


def test_registration_by_a_human_under_the_wrong_policy_does_not_fold(
    project: Project, human: Actor, other_session_human: Actor, hw: HW
) -> None:
    review = _review(project)
    wrong = _registration(hw, review, policy=PolicyKind.AGENT)
    inert(project, "hypothesis.registered", wrong, other_session_human)
    folds(project, "hypothesis.registered", _registration(hw, review), human)


def test_registration_of_another_version_does_not_fold(
    project: Project, human: Actor, hw: HW
) -> None:
    """With no review to cite, the version is the only thing tying the act to the draft."""
    inert(project, "hypothesis.registered", _registration(hw, None, h_version="H@00000000"), human)
    folds(project, "hypothesis.registered", _registration(hw, None), human)


def test_registration_of_an_abandoned_hypothesis_does_not_fold(
    project: Project, human: Actor, hw: HW
) -> None:
    review = _review(project)
    abandon_hypothesis(project, human, hw.hid, AbandonReason.OTHER, "dropped")
    inert(project, "hypothesis.registered", _registration(hw, review), human)


def test_registration_of_a_superseded_hypothesis_does_not_fold(
    project: Project, human: Actor, hw: HW
) -> None:
    review = _review(project)
    draft_hypothesis(
        project, DRAFTER, make_spec(lead=hw.lead, statement="Another statement."), supersedes=hw.hid
    )
    inert(project, "hypothesis.registered", _registration(hw, review), human)


def _draft(hw: HW, **over: Any) -> HypothesisDrafted:
    spec = make_spec(lead=hw.lead, statement="A replacement statement.", **over)
    return HypothesisDrafted(
        hypothesis_id=f"hyp_{ulid(5)}", spec=spec, h_version=hypothesis_version(spec)
    )


def test_a_draft_does_not_supersede_a_registered_hypothesis(
    project: Project, human: Actor, hw: HW
) -> None:
    """The draft is kept, but only its own registration replaces a registered hypothesis."""
    register = _registration(hw, _review(project))
    folds(project, "hypothesis.registered", register, human)
    forge(
        project,
        "hypothesis.drafted",
        _draft(hw).model_copy(update={"supersedes": hw.hid}),
        DRAFTER,
    )
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT hypothesis_id, superseded_by FROM hypotheses ORDER BY hypothesis_id")
        ).all()
    assert {str(h): s for h, s in rows} == {hw.hid: None, f"hyp_{ulid(5)}": None}
    assert project.index.rebuild() == project.index.state_hash()


def test_a_second_draft_of_a_known_id_changes_nothing(project: Project, hw: HW) -> None:
    again = _draft(hw).model_copy(update={"hypothesis_id": hw.hid})
    inert(project, "hypothesis.drafted", again, DRAFTER)


def test_a_stated_version_is_refused_before_it_can_be_logged(project: Project, hw: HW) -> None:
    """`h_version` is recomputed from the spec by the model, so the log never holds a wrong one."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HypothesisDrafted.model_validate(
            {**_draft(hw).model_dump(mode="json"), "h_version": "H@00000000"}
        )


def test_registration_needs_an_eligible_review_of_this_version(
    project: Project, human: Actor, hw: HW
) -> None:
    """A review of the drafter's own session, of another version, or of another hypothesis is
    not one a registration may cite."""
    own = forge(
        project,
        "hypothesis.reviewed",
        _forged_review(hw, critic_session=DRAFTER.session),
        DRAFTER,
    )
    inert(project, "hypothesis.registered", _registration(hw, own), human)
    lead_authors = forge(
        project,
        "hypothesis.reviewed",
        _forged_review(hw, critic_session=LEAD_AUTHOR.session),
        LEAD_AUTHOR,
    )
    inert(project, "hypothesis.registered", _registration(hw, lead_authors), human)
    # claims another session as critic: the writer's session is not the payload's
    claimed = forge(project, "hypothesis.reviewed", _forged_review(hw, critic_session=S2), AGENT)
    inert(project, "hypothesis.registered", _registration(hw, claimed), human)
    other_version = forge(
        project, "hypothesis.reviewed", _forged_review(hw, h_version="H@00000000"), CRITIC
    )
    inert(project, "hypothesis.registered", _registration(hw, other_version), human)
    hid2, version2 = draft_hypothesis(
        project, DRAFTER, make_spec(statement="Second.", lead=hw.lead)
    )
    elsewhere = forge(
        project,
        "hypothesis.reviewed",
        _forged_review(hw, hypothesis_id=hid2, h_version=version2),
        CRITIC,
    )
    inert(project, "hypothesis.registered", _registration(hw, elsewhere), human)
    # control: a genuine review of this version lets it fold
    folds(project, "hypothesis.registered", _registration(hw, _review(project)), human)


def test_review_by_a_proposers_session_is_kept_but_ineligible(
    project: Project, human: Actor, hw: HW
) -> None:
    for actor in (DRAFTER, LEAD_AUTHOR):
        forge(
            project, "hypothesis.reviewed", _forged_review(hw, critic_session=actor.session), actor
        )
    forge(project, "hypothesis.reviewed", _forged_review(hw), CRITIC)
    project.index.sync()
    with project.index.connect() as conn:
        flags = conn.execute(text("SELECT critic_session, eligible FROM hypothesis_reviews")).all()
    assert sorted((str(s), int(e)) for s, e in flags) == sorted(
        [(DRAFTER.session, 0), (LEAD_AUTHOR.session, 0), (CRITIC.session, 1)]
    )
    assert project.index.rebuild() == project.index.state_hash()


def test_agent_policy_registration_refuses_both_proposers(
    explore_project: Project, human: Actor
) -> None:
    p = explore_project
    card = exploratory_card(p, human)
    lead = record_lead(p, LEAD_AUTHOR, lead_input("A lead", card_trigger(card)))
    from factory.services.leads import decide_lead

    decide_lead(p, AGENT, lead, "promote")
    hid, version = draft_hypothesis(p, DRAFTER, make_spec(lead=lead))
    body = HypothesisRegistered(
        hypothesis_id=hid, h_version=version, policy=PolicyKind.AGENT, autonomy="agent"
    )
    inert(p, "hypothesis.registered", body, DRAFTER)
    inert(p, "hypothesis.registered", body, LEAD_AUTHOR)
    inert(p, "hypothesis.registered", body.model_copy(update={"autonomy": "human"}), AGENT)
    folds(p, "hypothesis.registered", body, AGENT)


# --- Totality: events that name nothing, and repeats ---

UNKNOWN_H = f"hyp_{ulid(9)}"


def _unknown_cases(human: Actor) -> list[tuple[str, StrictModel, Actor]]:
    return [
        (
            "hypothesis.abandoned",
            HypothesisAbandoned(hypothesis_id=UNKNOWN_H, reason=AbandonReason.OTHER, note="n"),
            human,
        ),
        ("hypothesis.concluded", HypothesisConcluded(hypothesis_id=UNKNOWN_H, text="t"), human),
        (
            "hypothesis.registered",
            HypothesisRegistered(
                hypothesis_id=UNKNOWN_H,
                h_version="H@00000000",
                policy=PolicyKind.HUMAN,
                autonomy="human",
            ),
            human,
        ),
        (
            "label.application_decided",
            LabelApplicationDecided(application_id=f"lbl_{ulid(3)}", decision="reject"),
            human,
        ),
        ("label.unmerged", LabelUnmerged(merge_event=f"ev_{ulid(3)}", reason="r"), human),
        (
            "term.revised",
            TermRevised(**promoted(5).model_dump(), supersedes=f"ev_{ulid(3)}"),
            human,
        ),
        ("term.retired", TermRetired(term_id=f"trm_{ulid(3)}", reason="r"), human),
        ("label.withdrawn", LabelWithdrawn(application_id=f"lbl_{ulid(3)}", reason="r"), AGENT),
        (
            "consolidation.pass_completed",
            ConsolidationPassCompleted(pass_id=f"cns_{ulid(3)}"),
            AGENT,
        ),
    ]


def test_events_naming_nothing_change_nothing(project: Project, human: Actor) -> None:
    for type_, model, actor in _unknown_cases(human):
        inert(project, type_, model, actor)


def test_reviews_of_an_unknown_hypothesis_change_nothing(project: Project, human: Actor) -> None:
    review = HypothesisReviewed(
        hypothesis_id=UNKNOWN_H,
        h_version="H@00000000",
        items=verdict("register").items,
        recommend="register",
        critic_session=CRITIC.session,
        task_id="tsk_x",
    )
    inert(project, "hypothesis.reviewed", review, CRITIC)


def test_repeated_events_are_total(project: Project, human: Actor) -> None:
    """Duplicate ids, keys and members never raise in sync or rebuild; the first stands."""
    lead = LeadRecorded(
        lead_id=f"led_{ulid(1)}",
        text="Lead",
        triggers=(
            Trigger(kind=TriggerKind.LEAD, ref=f"led_{ulid(2)}"),
            Trigger(kind=TriggerKind.LEAD, ref=f"led_{ulid(2)}"),
        ),
        keys=("k", "k", "j"),
    )
    settled(project, "lead.recorded", lead, AGENT)
    settled(project, "lead.recorded", lead.model_copy(update={"text": "Other"}), AGENT)
    for type_, model in (
        ("label.applied", applied()),
        ("label.applied", applied(label="Beta", application_id=f"lbl_{ulid(1)}", key="beta")),
        ("term.promoted", promoted()),
        ("term.promoted", promoted(name="Gamma")),
        (
            "consolidation.pass_started",
            ConsolidationPassStarted(
                pass_id=f"cns_{ulid(1)}",
                clusters_blob=f"sha256:{'a' * 64}",
                constants={"a": 1},
                counts={"c": 1},
            ),
        ),
    ):
        settled(project, type_, model, human)
        settled(project, type_, model, human)
    project.index.sync()
    with project.index.connect() as conn:
        assert conn.execute(text("SELECT text FROM leads")).scalar() == "Lead"
        assert conn.execute(text("SELECT key FROM labels")).scalar() == "alpha"


def test_merge_cycles_and_second_merges_are_total(project: Project, human: Actor) -> None:
    def merge(into: str, frm: str) -> LabelMerged:
        return LabelMerged(into_key=into, from_key=frm, reason="r")

    settled(project, "label.applied", applied(1, "Alpha"), AGENT)
    settled(project, "label.merged", merge("beta", "alpha"), human)
    settled(project, "label.merged", merge("gamma", "alpha"), human)  # a second merge of alpha
    settled(project, "label.merged", merge("alpha", "beta"), human)  # closes a cycle
    with project.index.connect() as conn:
        active = conn.execute(
            text("SELECT into_key, from_key, active FROM label_merges ORDER BY event_id")
        ).all()
        live = conn.execute(text("SELECT live_key FROM labels")).scalar()
    assert [tuple(r) for r in active] == [
        ("beta", "alpha", 1),
        ("gamma", "alpha", 0),
        ("alpha", "beta", 1),
    ]
    assert live in {"alpha", "beta"}


def test_a_second_merge_of_a_key_does_not_move_it(project: Project, human: Actor) -> None:
    settled(project, "label.applied", applied(1, "Alpha"), AGENT)
    settled(
        project, "label.merged", LabelMerged(into_key="beta", from_key="alpha", reason="r"), human
    )
    settled(
        project, "label.merged", LabelMerged(into_key="gamma", from_key="alpha", reason="r"), human
    )
    with project.index.connect() as conn:
        assert conn.execute(text("SELECT live_key FROM labels")).scalar() == "beta"


def test_term_revision_must_supersede_the_current_version(project: Project, human: Actor) -> None:
    first = forge(project, "term.promoted", promoted(), human)
    stale = f"ev_{ulid(2)}"
    revise = promoted(definition="Better.").model_dump()
    inert(project, "term.revised", TermRevised(**revise, supersedes=stale), human)
    folds(project, "term.revised", TermRevised(**revise, supersedes=first), human)


def test_withdrawal_touches_only_its_application(project: Project, human: Actor) -> None:
    settled(project, "label.applied", applied(1, "Alpha"), AGENT)
    settled(project, "label.applied", applied(2, "Beta"), AGENT)
    settled(
        project,
        "label.withdrawn",
        LabelWithdrawn(application_id=f"lbl_{ulid(1)}", reason="r"),
        AGENT,
    )
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT application_id, withdrawn FROM labels")).all()
    assert {str(a): int(w) for a, w in rows} == {f"lbl_{ulid(1)}": 1, f"lbl_{ulid(2)}": 0}


def test_first_completion_of_a_pass_stands(project: Project, human: Actor) -> None:
    started = ConsolidationPassStarted(
        pass_id=f"cns_{ulid(1)}", clusters_blob=f"sha256:{'a' * 64}", constants={}, counts={}
    )
    settled(project, "consolidation.pass_started", started, AGENT)
    first = forge(
        project,
        "consolidation.pass_completed",
        ConsolidationPassCompleted(pass_id=f"cns_{ulid(1)}"),
        AGENT,
    )
    inert(
        project,
        "consolidation.pass_completed",
        ConsolidationPassCompleted(pass_id=f"cns_{ulid(1)}"),
        AGENT,
    )
    with project.index.connect() as conn:
        assert (
            conn.execute(text("SELECT completed_event FROM consolidation_passes")).scalar() == first
        )


# --- Regions: a snapshot whose blobs are malformed ---


def _gz(text_: str) -> bytes:
    return gzip.compress(text_.encode())


def _snapshot(project: Project, members: bytes | None, basis: object = None) -> RegionSnapshotTaken:
    """A snapshot over `members` (a missing blob when None)."""
    members_blob = f"sha256:{'c' * 64}" if members is None else project.blobs.put(members)
    return RegionSnapshotTaken(
        region_id=f"reg_{ulid(1)}",
        version="R@0badcafe",
        definition_event=f"ev_{ulid(1)}",
        rules_hash="0" * 64,
        members_blob=members_blob,
        members_hash="1" * 64,
        basis_blob=project.blobs.put_json({} if basis is None else basis),  # type: ignore[arg-type]
        counts={MemberType.WORK: 1},
        as_of=f"ev_{ulid(2)}",
    )


MALFORMED: dict[str, tuple[bytes | None, object]] = {
    "not-gzip": (b"plain bytes", None),
    "no-tab": (_gz("work-without-a-tab\n"), None),
    "duplicate-member": (_gz("work\tw1\nwork\tw1\n"), None),
    "basis-not-a-dict": (_gz("work\tw1\n"), ["not", "a", "dict"]),
    "blob-missing": (None, None),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_snapshot_blobs_never_raise(project: Project, agent: Actor, case: str) -> None:
    """A logged event can never be removed: a snapshot the projector cannot read stays unfolded."""
    members, basis = MALFORMED[case]
    inert(project, "region.snapshot_taken", _snapshot(project, members, basis), agent)


def test_well_formed_snapshot_folds(project: Project, agent: Actor) -> None:
    folds(project, "region.snapshot_taken", _snapshot(project, _gz("work\tw1\n")), agent)


# --- Miners: registration and calibration ---


def _registered(project: Project, *, kind: str = "human", version: int = 1) -> MinerRegistered:
    spec = method_vision(version=version)
    return MinerRegistered(
        miner_id=f"mnr_{ulid(version)}",
        name=spec.name,
        version=version,
        digest=miner_digest(spec),
        spec_blob=project.blobs.put_json(spec_to_json(spec)),
        proposer_kind=kind,  # type: ignore[arg-type]
    )


def _drawn(project: Project, **over: Any) -> MinerCalibrationDrawn:
    body: dict[str, Any] = {
        "calibration_id": f"mcl_{ulid(1)}",
        "name": method_vision().name,
        "version": 1,
        "digest": miner_digest(method_vision()),
        "units": (
            CalibrationUnit(work_id="w1", conversion_id=f"cnv_{ulid(1)}"),
            CalibrationUnit(work_id="w2", conversion_id=f"cnv_{ulid(2)}"),
        ),
        "random_seed": 5,
        "population": 4,
        "population_digest": "d",
        "protocol_id": "P@0badcafe",
    }
    body.update(over)
    return MinerCalibrationDrawn(**body)


def _gold(work: str = "w1", **over: Any) -> MinerCalibrationLabelled:
    body: dict[str, Any] = {
        "calibration_id": f"mcl_{ulid(1)}",
        "work_id": work,
        "empty": True,
        "channel": Channel.CLI,
    }
    body.update(over)
    return MinerCalibrationLabelled(**body)


def test_registration_cannot_claim_another_proposer_kind(project: Project, human: Actor) -> None:
    """`proposer_kind` is what the independence rules read: it must be the writer's own kind."""
    inert(project, "miner.registered", _registered(project, kind="human"), AGENT)
    folds(project, "miner.registered", _registered(project, kind="human"), human)


def test_calibration_is_drawn_by_a_human_for_a_registered_digest(
    project: Project, human: Actor
) -> None:
    forge(project, "miner.registered", _registered(project), human)
    inert(project, "miner.calibration_drawn", _drawn(project), AGENT)
    inert(project, "miner.calibration_drawn", _drawn(project, digest="0" * 16), human)
    inert(project, "miner.calibration_drawn", _drawn(project, name="m-unregistered"), human)
    folds(project, "miner.calibration_drawn", _drawn(project), human)


def test_gold_label_is_a_human_act_on_a_drawn_unit(project: Project, human: Actor) -> None:
    forge(project, "miner.registered", _registered(project), human)
    forge(project, "miner.calibration_drawn", _drawn(project), human)
    inert(project, "miner.calibration_labelled", _gold(), AGENT)
    inert(project, "miner.calibration_labelled", _gold("w9"), human)  # not a drawn unit
    inert(project, "miner.calibration_labelled", _gold(calibration_id=f"mcl_{ulid(9)}"), human)
    folds(project, "miner.calibration_labelled", _gold(), human)
    inert(project, "miner.calibration_labelled", _gold(), AGENT)  # nor does it replace a gold label


def test_a_drawn_sample_the_model_refuses_is_never_logged(project: Project) -> None:
    from pydantic import ValidationError

    unit = CalibrationUnit(work_id="w1", conversion_id=f"cnv_{ulid(1)}")
    for units in ((unit, unit), ()):
        with pytest.raises(ValidationError):
            _drawn(project, units=units)


# --- Gate audit ---


def _sampled(**over: Any) -> GateAuditSampled:
    body: dict[str, Any] = {
        "audit_id": f"gau_{ulid(1)}",
        "gate_id": "links.confirm",
        "act_event_ids": (f"ev_{ulid(1)}", f"ev_{ulid(1)}", f"ev_{ulid(2)}"),
        "random_seed": 3,
        "population": 5,
        "population_digest": "d",
    }
    body.update(over)
    return GateAuditSampled(**body)


def _audit_label(act: str = f"ev_{ulid(1)}", **over: Any) -> GateAuditLabelled:
    body: dict[str, Any] = {
        "audit_id": f"gau_{ulid(1)}",
        "act_event_id": act,
        "correct": False,
        "channel": Channel.CLI,
    }
    body.update(over)
    return GateAuditLabelled(**body)


def test_gate_audit_sample_is_a_human_act(project: Project, human: Actor) -> None:
    inert(project, "gate.audit_sampled", _sampled(), AGENT)
    folds(project, "gate.audit_sampled", _sampled(), human)
    settled(project, "gate.audit_sampled", _sampled(), human)  # a repeat, with repeated acts


def test_gate_audit_label_is_a_human_act_on_a_sampled_act(project: Project, human: Actor) -> None:
    forge(project, "gate.audit_sampled", _sampled(), human)
    inert(project, "gate.audit_labelled", _audit_label(), AGENT)
    inert(project, "gate.audit_labelled", _audit_label(f"ev_{ulid(8)}"), human)
    inert(project, "gate.audit_labelled", _audit_label(audit_id=f"gau_{ulid(8)}"), human)
    folds(project, "gate.audit_labelled", _audit_label(), human)
    inert(project, "gate.audit_labelled", _audit_label(correct=True), AGENT)
