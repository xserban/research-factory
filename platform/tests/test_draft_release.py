"""The release gate in `exploratory` and `pilot` (plan W-B, task 5; Review Focus 3). `systematic`
is in `tests/test_draft_systematic.py`. Hand-written releases change nothing, on rebuild too."""

# ruff: noqa: F401, F811

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.drafts import AuditLabel, DraftAuditReport, DraftKind, DraftReleased, Verdict
from factory.modules.contract import PolicyKind
from factory.services.context import Project
from factory.services.draft_audit import draw_audit, open_audit_items, record_audit
from factory.services.draft_release import release, released_drafts
from factory.services.drafts import create_draft, write_sentences
from factory.services.gates import autonomy_counts
from factory.services.project import init_project
from tests.draft_b_helpers import (
    CLAIM,
    STRUCT,
    SYNTH,
    W1,
    Written,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    screened,
    sent,
    verdict_on,
    verifier,
    verify_all,
    verify_one,
    wd,
    writer,
    ww,
)
from tests.gate_helpers import amend_gate_policies, entry
from tests.test_draft_status import supersede_claim
from tests.writing_helpers import WWorld


def audited(project: Project, draft: str, *, wrong: int = 0) -> None:
    audit = draw_audit(project, draft)
    for i, (_, verdict) in enumerate(open_audit_items(project, draft)):
        label = AuditLabel.INCORRECT if i < wrong else AuditLabel.CORRECT
        record_audit(project, audit, verdict, label, None, actor=project.human_actor())


def fields(call: Any, *args: Any, **kw: Any) -> list[tuple[str, str]]:
    with pytest.raises(FactoryValidationError) as caught:
        call(*args, **kw)
    return [(i.field, i.reason) for i in caught.value.issues]


def stat_draft(project: Project, n: int = 1) -> str:
    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    write_sentences(
        project,
        draft,
        [
            sent(
                "sec_01", SYNTH, f"No idea is confirmed in part {'abc'[i]}", "stat:ideas-confirmed"
            )
            for i in range(n)
        ],
        actor=writer(),
    )
    return draft


def released_events(project: Project) -> list[DraftReleased]:
    return [
        DraftReleased.model_validate(e.payload)
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "draft.released"
    ]


def test_exploratory_releases_with_flags(
    settings: Settings, clock: FixedClock, agent: Actor
) -> None:
    project = init_project(settings, "loose", "exploratory", session=W1, clock=clock)
    draft = stat_draft(project, 3)
    verify_one(project, draft, Verdict.OVERSTATED)
    assert release(project, draft, actor=agent)
    [event] = released_events(project)
    assert event.counts["flagged"] == 1 and event.counts["unchecked"] == 2
    assert event.policy is PolicyKind.AGENT and event.released_by == agent.id
    assert draft in released_drafts(project)


def test_exploratory_refuses_an_empty_draft(
    settings: Settings, clock: FixedClock, agent: Actor
) -> None:
    project = init_project(settings, "loose", "exploratory", session=W1, clock=clock)
    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    assert fields(release, project, draft, actor=agent) == [
        ("draft_id", "the draft has no sentence")
    ]


def test_unknown_draft_refused(project: Project, agent: Actor) -> None:
    assert fields(release, project, "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", actor=agent)[0][0] == (
        "draft_id"
    )


def test_pilot_release_refused_when_stale(
    project: Project, ww: WWorld, wd: Written, agent: Actor
) -> None:  # Review Focus 3
    verify_all(project, wd.draft)
    audited(project, wd.draft)
    supersede_claim(project, ww.claims[ww.works[0]])
    assert fields(release, project, wd.draft, actor=agent) == [("stale", "1 stale sentence(s)")]


def test_pilot_requires_labelled_audit(project: Project, agent: Actor) -> None:
    draft = stat_draft(project, 2)
    verify_all(project, draft)
    assert fields(release, project, draft, actor=agent) == [("audit", "no audit is drawn")]
    audit = draw_audit(project, draft)
    assert fields(release, project, draft, actor=agent) == [
        ("audit", "2 sampled verdict(s) unlabelled")
    ]
    verdict = open_audit_items(project, draft)[0][1]
    record_audit(project, audit, verdict, AuditLabel.CORRECT, None, actor=project.human_actor())
    assert fields(release, project, draft, actor=agent) == [
        ("audit", "1 sampled verdict(s) unlabelled")
    ]
    verdict = open_audit_items(project, draft)[0][1]
    record_audit(project, audit, verdict, AuditLabel.CORRECT, None, actor=project.human_actor())
    assert release(project, draft, actor=agent)


def test_pilot_refuses_an_audit_older_than_the_last_verdict(project: Project, agent: Actor) -> None:
    draft = stat_draft(project, 2)
    verify_one(project, draft)
    audited(project, draft)
    verify_one(project, draft)
    assert fields(release, project, draft, actor=agent) == [
        ("audit", "a verdict is newer than the last draw")
    ]
    audited(project, draft)
    assert release(project, draft, actor=agent)


def test_pilot_marks_flagged_and_unchecked_but_releases(project: Project, agent: Actor) -> None:
    """Flagged and unchecked sentences do not block a pilot release (ruling 13)."""
    draft = stat_draft(project, 3)
    verify_one(project, draft)
    verify_one(project, draft, Verdict.PARTIAL)
    audited(project, draft)
    assert release(project, draft, actor=agent)
    [event] = released_events(project)
    assert (event.counts["supported"], event.counts["flagged"], event.counts["unchecked"]) == (
        1,
        1,
        1,
    )


def test_pilot_rate_above_the_ceiling_is_advisory(project: Project, agent: Actor) -> None:
    """The refusals an agent can reach do not depend on an audit's result."""
    draft = stat_draft(project, 2)
    verify_all(project, draft)
    audited(project, draft, wrong=2)
    assert release(project, draft, actor=agent)


def test_a_tightened_gate_refuses_an_agent(
    project: Project, ww: WWorld, wd: Written, agent: Actor
) -> None:
    amend_gate_policies(project, project.human_actor(), entry("writing.release", PolicyKind.HUMAN))
    verify_all(project, wd.draft)
    audited(project, wd.draft)
    assert fields(release, project, wd.draft, actor=agent)[0][0] == "actor"
    assert release(project, wd.draft, actor=project.human_actor())
    assert released_events(project)[0].policy is PolicyKind.HUMAN


def test_release_records_counts_and_as_of(project: Project, agent: Actor) -> None:
    draft = stat_draft(project, 2)
    verify_all(project, draft)
    audited(project, draft)
    head = project.index.head()
    assert release(project, draft, actor=agent)
    [event] = released_events(project)
    assert event.as_of == head
    assert event.counts["supported"] == 2 and event.audit.drawn == 2 and event.audit.rate == 0.0


def test_release_is_an_act_at_the_gate(project: Project, agent: Actor) -> None:
    draft = stat_draft(project, 1)
    verify_all(project, draft)
    audited(project, draft)
    release(project, draft, actor=agent)
    assert sum(autonomy_counts(project, "writing.release").values()) == 1


def test_a_later_release_is_a_new_event(project: Project, agent: Actor) -> None:
    draft = stat_draft(project, 1)
    verify_all(project, draft)
    audited(project, draft)
    release(project, draft, actor=agent)
    release(project, draft, actor=agent)
    assert len(released_events(project)) == 2


# --- Hand-written events --------------------------------------------------------------------


def rows(project: Project) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT * FROM draft_releases"))]


def forged(project: Project, draft: str, actor: Actor, **over: Any) -> None:
    head = project.index.head()
    assert head is not None
    body: dict[str, Any] = {
        "draft_id": draft,
        "as_of": head,
        "policy": PolicyKind.AGENT,
        "counts": {"supported": 1},
        "audit": DraftAuditReport(drawn=1, labelled=1, incorrect=0, rate=0.0, above_ceiling=False),
        "released_by": actor.id,
    }
    body.update(over)
    blob = project.blobs.put_json({"forged": True}) if actor.kind == "agent" else None
    payload = DraftReleased.model_validate(body)
    project.record([project.events.make("draft.released", payload, actor, input_blob=blob)])


def inert(project: Project, draft: str, actor: Actor, **over: Any) -> None:
    before = rows(project)
    forged(project, draft, actor, **over)
    assert rows(project) == before
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


@pytest.fixture
def ready(project: Project) -> str:
    draft = stat_draft(project, 1)
    verify_all(project, draft)
    audited(project, draft)
    return draft


def test_forged_release_control_folds(project: Project, ready: str, agent: Actor) -> None:
    forged(project, ready, agent)
    assert len(rows(project)) == 1
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


def test_forged_release_without_the_audit_is_inert(project: Project, agent: Actor) -> None:
    draft = stat_draft(project, 1)
    verify_all(project, draft)
    inert(project, draft, agent)


def test_forged_release_with_stale_counts_is_inert(
    project: Project, ready: str, agent: Actor
) -> None:
    inert(project, ready, agent, counts={"stale": 1})


def test_forged_release_with_wrong_counts_is_inert(
    project: Project, ready: str, agent: Actor
) -> None:
    inert(project, ready, agent, counts={"supported": 9})


def test_forged_release_under_a_policy_not_in_force_is_inert(
    project: Project, ready: str, agent: Actor
) -> None:
    inert(project, ready, agent, policy=PolicyKind.HUMAN)


def test_forged_release_by_an_agent_at_a_human_gate_is_inert(
    project: Project, ww: WWorld, agent: Actor
) -> None:
    amend_gate_policies(project, project.human_actor(), entry("writing.release", PolicyKind.HUMAN))
    draft = stat_draft(project, 1)
    verify_all(project, draft)
    audited(project, draft)
    inert(project, draft, agent, policy=PolicyKind.HUMAN)


def test_forged_release_by_the_system_or_of_someone_else_is_inert(
    project: Project, ready: str, agent: Actor
) -> None:
    inert(project, ready, project.system_actor())
    inert(project, ready, agent, released_by="someone")


def test_forged_release_of_an_unknown_draft_is_inert(project: Project, agent: Actor) -> None:
    inert(project, "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", agent)


def test_forged_release_as_of_the_future_is_inert(
    project: Project, ready: str, agent: Actor
) -> None:
    inert(project, ready, agent, as_of="ev_ZZZZZZZZZZZZZZZZZZZZZZZZZZ")
