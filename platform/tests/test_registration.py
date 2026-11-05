"""Gated registration, model cut-offs and the R-53 flags (slice 6, plan H-C task 6)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from datetime import date

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.hypotheses import HypothesisRegistered, Trigger, TriggerKind
from factory.modules.contract import PolicyKind
from factory.services.context import Project
from factory.services.hypotheses import (
    cutoff_flags,
    declare_cutoff,
    draft_hypothesis,
    hypothesis_view,
    register_hypothesis,
)
from factory.services.hypothesis_review import record_review, review_next
from factory.services.leads import decide_lead, record_lead
from factory.services.project import init_project
from tests.helpers import SESSION
from tests.hypothesis_helpers import (
    CRITIC,
    DRAFTER,
    HW,
    LEAD_AUTHOR,
    LEAD_TEXT,
    OTHER,
    card_trigger,
    exploratory_card,
    gw,
    hw,
    lead_input,
    make_spec,
    promoted_lead,
)
from tests.test_hypothesis_review import verdict

WINDOW = date(2026, 1, 1)
LITERATURE = {
    "kind": "literature",
    "decision_rule": {"rule": "literature-direction", "n_min": 5, "q": "0.8"},
    "prediction": {"direction": "treatment-better", "margin": "0"},
    "test": {"kind": "literature", "window_start": WINDOW.isoformat(), "sources": []},
}


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def _review(project: Project, recommend: str = "register", critic: Actor = CRITIC) -> str:
    served = review_next(project, critic)
    assert served is not None
    return record_review(project, critic, served.task_id, verdict(recommend))


def test_pilot_agent_cannot_register(project: Project, human: Actor, hw: HW) -> None:  # acc. 11
    review = _review(project)
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, OTHER, hw.hid)
    assert _fields(err) == [("actor", "gate hypotheses.register is human: an agent cannot pass it")]
    assert _events(project, "hypothesis.registered") == []
    event_id = register_hypothesis(project, human, hw.hid)
    view = hypothesis_view(project, hw.hid)
    assert view is not None and view.state == "registered"
    assert (view.registration, view.autonomy, view.reviews) == (event_id, "human", [review])
    [event] = _events(project, "hypothesis.registered")
    assert event.payload["policy"] == "human" and event.payload["review_event_id"] == review
    assert event.payload["h_version"] == hw.version and event.actor.kind == "human"


def test_registration_needs_register_review(project: Project, human: Actor, hw: HW) -> None:
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, hw.hid)
    assert _fields(err) == [("review", "review-required")]
    _review(project, "revise")
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, hw.hid)
    assert _fields(err) == [("review", "not-recommended")]
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, "hyp_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    assert _fields(err) == [("hypothesis_id", "unknown")]


def test_registered_once_and_h_version_frozen(project: Project, human: Actor, hw: HW) -> None:
    _review(project)
    register_hypothesis(project, human, hw.hid)
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, hw.hid)
    assert _fields(err) == [("hypothesis_id", "state-registered")]
    before = hypothesis_view(project, hw.hid)
    assert before is not None
    new, new_version = draft_hypothesis(
        project,
        DRAFTER,
        make_spec(lead=hw.lead, prediction={"direction": "treatment-better", "margin": "3"}),
        supersedes=hw.hid,
    )
    # an unreviewed draft does not undo the human registration (I2)
    old = hypothesis_view(project, hw.hid)
    assert old is not None and old.h_version == hw.version != new_version
    assert (old.state, old.superseded_by) == ("registered", None)
    assert (old.registration, old.autonomy) == (before.registration, "human")
    fresh = hypothesis_view(project, new)
    assert fresh is not None and fresh.state == "draft" and fresh.registration is None
    with pytest.raises(FactoryValidationError) as err:  # the replacement needs its own review
        register_hypothesis(project, human, new)
    assert _fields(err) == [("review", "review-required")]
    assert hypothesis_view(project, hw.hid).state == "registered"  # type: ignore[union-attr]
    _review(project)
    register_hypothesis(project, human, new)  # through the gate
    old = hypothesis_view(project, hw.hid)
    assert old is not None and (old.state, old.superseded_by) == ("superseded", new)
    assert old.registration == before.registration and old.h_version == hw.version


def test_revised_draft_registers_over_its_unregistered_predecessor(
    project: Project, human: Actor, hw: HW
) -> None:
    # H1 is a draft; H2 supersedes it at once, so H1 already names H2 as `superseded_by`.
    new, _ = draft_hypothesis(
        project,
        DRAFTER,
        make_spec(lead=hw.lead, prediction={"direction": "treatment-better", "margin": "3"}),
        supersedes=hw.hid,
    )
    old = hypothesis_view(project, hw.hid)
    assert old is not None and old.superseded_by == new and old.registration is None
    _review(project)
    register_hypothesis(project, human, new)  # not refused `already-superseded`
    fresh = hypothesis_view(project, new)
    assert fresh is not None and fresh.state == "registered"


def test_two_rivals_first_to_register_wins(project: Project, human: Actor, hw: HW) -> None:
    _review(project)
    register_hypothesis(project, human, hw.hid)
    rivals = [
        draft_hypothesis(
            project,
            DRAFTER,
            make_spec(lead=hw.lead, prediction={"direction": "treatment-better", "margin": margin}),
            supersedes=hw.hid,
        )[0]
        for margin in ("3", "4")
    ]
    _review(project)
    register_hypothesis(project, human, rivals[0])
    _review(project)
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, rivals[1])
    assert _fields(err) == [("supersedes", "already-superseded")]


def test_replacement_registration_refused_once_the_old_one_has_evidence(
    project: Project, human: Actor, hw: HW, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import hypotheses as hyp

    _review(project)
    register_hypothesis(project, human, hw.hid)
    new, _ = draft_hypothesis(
        project,
        DRAFTER,
        make_spec(lead=hw.lead, prediction={"direction": "treatment-better", "margin": "3"}),
        supersedes=hw.hid,
    )
    _review(project)
    monkeypatch.setattr(hyp, "EVALUATION_SOURCES", [lambda _p, h: h == hw.hid])
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, new)
    assert _fields(err) == [("supersedes", "evidence-exists")]


def test_exploratory_non_drafter_agent_registers_with_autonomy_label(
    explore_project: Project, human: Actor
) -> None:  # acceptance 11
    project = explore_project
    hid, _ = draft_hypothesis(project, DRAFTER, make_spec())  # no lead, no review needed
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, DRAFTER, hid)
    assert _fields(err) == [("session", "the proposer cannot pass gate hypotheses.register")]
    event_id = register_hypothesis(project, OTHER, hid)
    view = hypothesis_view(project, hid)
    assert view is not None and view.state == "registered"
    assert (view.registration, view.autonomy) == (event_id, "agent")
    [event] = _events(project, "hypothesis.registered")
    assert event.payload["autonomy"] == "agent" and event.payload["policy"] == "agent"
    assert event.input_blob is not None and event.actor.kind == "agent"
    assert event.payload["review_event_id"] is None


def test_exploratory_review_that_says_no_still_blocks(
    explore_project: Project, human: Actor
) -> None:
    project = explore_project
    hid, _ = draft_hypothesis(project, DRAFTER, make_spec())
    served = review_next(project, CRITIC)
    assert served is not None
    record_review(project, CRITIC, served.task_id, verdict("reject"))
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, OTHER, hid)
    assert _fields(err) == [("review", "not-recommended")]


def _literature(project: Project, human: Actor, work: str) -> tuple[str, str]:
    lead = promoted_lead(project, human, Trigger(kind=TriggerKind.WORK, ref=work))
    return draft_hypothesis(project, DRAFTER, make_spec(lead=lead, **LITERATURE))


def test_contaminated_and_cutoff_unknown_flags(
    project: Project, human: Actor, gw: list[str]
) -> None:  # acceptance 12
    hid, _ = _literature(project, human, gw[0])
    view = hypothesis_view(project, hid)
    assert view is not None and view.flags == ("cutoff-unknown",)  # the drafter's model
    served = review_next(project, CRITIC)
    assert served is not None
    record_review(project, CRITIC, served.task_id, verdict())
    assert cutoff_flags(project, hid) == ("cutoff-unknown",)
    declare_cutoff(project, human, "model-drafter", date(2025, 6, 1), "vendor card")
    declare_cutoff(project, human, "model-critic", date(2026, 3, 1), "vendor card")
    assert cutoff_flags(project, hid) == ("contaminated",)  # the critic's cut-off is in the window
    declare_cutoff(project, human, "model-critic", date(2026, 1, 1), "vendor card")
    assert cutoff_flags(project, hid) == ("contaminated",)  # on the window start counts
    register_hypothesis(project, human, hid)  # pilot registers with the flag
    [event] = _events(project, "hypothesis.registered")
    assert event.payload["flags"] == ["contaminated"]
    view = hypothesis_view(project, hid)
    assert view is not None and view.flags == ("contaminated",)


def test_experiment_hypotheses_carry_no_cutoff_flag(project: Project, hw: HW) -> None:
    assert cutoff_flags(project, hw.hid) == ()


def test_latest_cutoff_declaration_wins(project: Project, human: Actor, hw: HW) -> None:
    declare_cutoff(project, human, "model-x", date(2026, 6, 1), "first")
    declare_cutoff(project, human, "model-x", date(2025, 1, 1), "corrected")
    with project.index.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(text("SELECT cutoff FROM model_cutoffs WHERE model = 'model-x'")).one()
    assert str(row[0]) == "2025-01-01"
    with pytest.raises(FactoryValidationError) as err:
        declare_cutoff(project, OTHER, "model-x", date(2020, 1, 1), "agent")
    assert _fields(err) == [("actor", "human-only")]
    with pytest.raises(FactoryValidationError):
        declare_cutoff(project, human, "  ", date(2020, 1, 1), "blank model")
    assert len(_events(project, "model.cutoff_declared")) == 2


def test_systematic_refuses_unknown_cutoff(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", "systematic", session=SESSION, clock=clock)
    human = project.human_actor()
    card = exploratory_card(project, human)
    lead = promoted_lead(project, human, card_trigger(card))
    hid, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=lead, **LITERATURE))
    _review(project)
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, hid)
    assert _fields(err) == [("test.window_start", "cutoff-unknown")]
    declare_cutoff(project, human, "model-drafter", date(2025, 1, 1), "card")
    declare_cutoff(project, human, "model-critic", date(2026, 2, 1), "card")
    with pytest.raises(FactoryValidationError) as err:
        register_hypothesis(project, human, hid)
    assert _fields(err) == [("test.window_start", "contaminated")]
    declare_cutoff(project, human, "model-critic", date(2025, 12, 31), "card")
    assert register_hypothesis(project, human, hid)
    assert _events(project, "hypothesis.registered")[0].payload["flags"] == []


def test_projector_ignores_ineligible_registration(
    project: Project, human: Actor, hw: HW
) -> None:  # Review Focus 3
    review = _review(project)

    def write(actor: Actor, **change: object) -> None:
        body = {
            "hypothesis_id": hw.hid,
            "h_version": hw.version,
            "review_event_id": review,
            "policy": PolicyKind.HUMAN,
            "autonomy": "human",
            "flags": (),
        }
        body.update(change)
        blob = None if actor.kind == "human" else project.blobs.put_json({"forged": True})
        project.record(
            [
                project.events.make(
                    "hypothesis.registered",
                    HypothesisRegistered.model_validate(body),
                    actor,
                    input_blob=blob,
                )
            ]
        )

    write(OTHER)  # an agent claims the human policy
    write(OTHER, policy=PolicyKind.AGENT, autonomy="agent")  # claims a policy that is not in force
    write(human, autonomy="agent")  # a human act mislabelled
    write(human, h_version="H@00000000")  # not the hypothesis's version
    write(human, review_event_id="ev_01JZ9Q3K5M7N8P0R2S4T6V8W0X")  # not a review of it
    view = hypothesis_view(project, hw.hid)
    assert view is not None and view.state == "reviewed" and view.registration is None
    assert len(_events(project, "hypothesis.registered")) == 5
    write(human)  # the consistent one folds
    view = hypothesis_view(project, hw.hid)
    assert view is not None and view.state == "registered" and view.autonomy == "human"
