"""Verification and release in a `systematic` project (slice 7b, plan W-B).

The rigor mode is fixed when a project is created, and a systematic project's screening needs more
than the writing world has, so these drafts rest on computed figures (`stat` supports) of a fresh
project; `project` is overridden here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.model.drafts import (
    AuditLabel,
    DraftAuditReport,
    DraftKind,
    DraftReleased,
    SentenceVerified,
    SupportSpan,
    Verdict,
)
from factory.model.gates import GatePolicies, GatePolicyEntry
from factory.modules.contract import PolicyKind
from factory.services.context import Project
from factory.services.draft_audit import draw_audit, open_audit_items, record_audit
from factory.services.draft_release import release, released_drafts
from factory.services.draft_verify import verify_next, verify_record
from factory.services.drafts import create_draft, write_sentences
from factory.services.project import init_project
from factory.services.protocol import record_protocol
from tests.draft_b_helpers import (
    SYNTH,
    WRITER_MODEL,
    sent,
    verdict_on,
    verifier,
    verify_all,
    verify_one,
    writer,
)
from tests.helpers import bind_ids, pilot_protocol_spec, record_pilot_question

SESSION = "01JZ9Q3K5M7N8P0R2S4T6V8W0X"
ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W"


@pytest.fixture
def project(settings: Settings, clock: FixedClock) -> Project:
    return init_project(settings, "demo", "systematic", session=SESSION, clock=clock)


@dataclass
class SysDraft:
    draft: str
    sentences: list[str]


def stat_draft(project: Project, n: int = 2) -> SysDraft:
    draft = create_draft(project, title="Notes", kind=DraftKind.OTHER, actor=project.human_actor())
    written = write_sentences(
        project,
        draft,
        [
            sent(
                "sec_01",
                SYNTH,
                f"No idea is confirmed in part {'abcdefg'[i]}",
                "stat:ideas-confirmed",
            )
            for i in range(n)
        ],
        actor=writer(),
    )
    assert not written.rejected
    return SysDraft(draft, written.written)


@pytest.fixture
def sd(project: Project) -> SysDraft:
    return stat_draft(project)


def test_systematic_same_model_refused(project: Project, sd: SysDraft) -> None:
    same = verifier(model=WRITER_MODEL)
    with pytest.raises(FactoryValidationError) as caught:
        verify_next(project, sd.draft, actor=same)
    assert caught.value.issues[0].field == "model"
    unit = verify_next(project, sd.draft, actor=verifier())
    assert unit is not None
    changed = verifier().model_copy(update={"model": WRITER_MODEL})
    with pytest.raises(FactoryValidationError) as recorded:
        verify_record(project, unit.task_id, verdict_on(unit), actor=changed)
    assert recorded.value.issues[0].field == "model"


def test_systematic_serves_another_writers_sentence_to_that_model(
    project: Project, sd: SysDraft
) -> None:
    """A verifier of one writer's model is passed over that writer's sentences only."""
    other = writer("01JZ9Q3K5M7N8P0R2S4T6V8W44", model="claude-haiku-5-5")
    done = write_sentences(
        project,
        sd.draft,
        [sent("sec_01", SYNTH, "No idea is confirmed here", "stat:ideas-confirmed")],
        actor=other,
    )
    unit = verify_next(project, sd.draft, actor=verifier(model=WRITER_MODEL))
    assert unit is not None and unit.sentence_id == done.written[0]


def test_forged_verdict_of_the_writers_model_is_inert(project: Project, sd: SysDraft) -> None:
    unit = verify_next(project, sd.draft, actor=verifier())
    assert unit is not None
    blob = project.blobs.put_json(unit.model_dump(mode="json", exclude={"task_id"}))
    spans = [SupportSpan(ref=unit.supports[0].ref, substring=unit.supports[0].spans[0])]

    def forged(model: str, n: int) -> int:
        payload = SentenceVerified(
            verdict_id=f"svd_{ULID}{n:02d}",
            sentence_id=unit.sentence_id,
            verdict=Verdict.SUPPORTED,
            support_spans=spans,
        )
        project.record(
            [project.events.make("draft.verified", payload, verifier(model=model), input_blob=blob)]
        )
        project.index.sync()
        with project.index.connect() as conn:
            return int(conn.execute(text("SELECT COUNT(*) FROM sentence_verdicts")).scalar_one())

    assert forged(WRITER_MODEL, 1) == 0
    assert forged("claude-opus-5-5", 2) == 1


# --- The release gate -----------------------------------------------------------------------


def with_reviewer(
    project: Project, agent: Actor, reviewer: str = "obd", gates: bool = False
) -> None:
    spec = pilot_protocol_spec(record_pilot_question(project, agent), None, reviewer=reviewer)
    if gates:  # a protocol that lets agents pass the gate: it may not reach `systematic`
        entries = (GatePolicyEntry(gate="writing.release", policy=PolicyKind.AGENT),)
        spec = spec.model_copy(update={"gate_policies": GatePolicies(entries=entries)})
    record_protocol(
        project,
        project.human_actor(),
        spec,
        ready=False,
        decision_ids=bind_ids(project, agent, DecisionLevel.PROTOCOL),
    )


def audited(project: Project, draft: str, *, wrong: int = 0) -> None:
    audit = draw_audit(project, draft)
    for i, (_, verdict) in enumerate(open_audit_items(project, draft)):
        label = AuditLabel.INCORRECT if i < wrong else AuditLabel.CORRECT
        record_audit(project, audit, verdict, label, None, actor=project.human_actor())


def refusal(project: Project, draft: str, actor: Actor) -> list[tuple[str, str]]:
    with pytest.raises(FactoryValidationError) as caught:
        release(project, draft, actor=actor)
    return [(i.field, i.reason) for i in caught.value.issues]


def test_systematic_requires_reviewer_of_record(
    project: Project, sd: SysDraft, agent: Actor
) -> None:
    verify_all(project, sd.draft)
    audited(project, sd.draft)
    assert refusal(project, sd.draft, project.human_actor())[0][0] == "actor"  # no protocol yet
    with_reviewer(project, agent, reviewer="ana")
    assert refusal(project, sd.draft, project.human_actor())[0][0] == "actor"


def test_reviewer_of_record_releases(project: Project, sd: SysDraft, agent: Actor) -> None:
    with_reviewer(project, agent)
    verify_all(project, sd.draft)
    audited(project, sd.draft)
    assert release(project, sd.draft, actor=project.human_actor())
    assert sd.draft in released_drafts(project)


def test_agent_cannot_release_in_systematic(project: Project, sd: SysDraft, agent: Actor) -> None:
    with_reviewer(project, agent)
    verify_all(project, sd.draft)
    audited(project, sd.draft)
    assert refusal(project, sd.draft, agent)[0][0] == "actor"


def test_a_protocol_cannot_let_an_agent_release_in_systematic(
    project: Project, agent: Actor
) -> None:
    """R-39: the policy is the reviewer of record's; a weaker entry is refused at the record."""
    spec = pilot_protocol_spec(record_pilot_question(project, agent), None)
    entries = (GatePolicyEntry(gate="writing.release", policy=PolicyKind.AGENT),)
    weak = spec.model_copy(update={"gate_policies": GatePolicies(entries=entries)})
    with pytest.raises(FactoryValidationError):
        record_protocol(project, project.human_actor(), weak, ready=False)


def test_systematic_refuses_flagged_unchecked(project: Project, agent: Actor) -> None:
    with_reviewer(project, agent)
    sd = stat_draft(project, 3)
    verify_one(project, sd.draft)
    verify_one(project, sd.draft, Verdict.OVERSTATED)
    audited(project, sd.draft)
    assert refusal(project, sd.draft, project.human_actor()) == [
        ("flagged", "1 flagged sentence(s)"),
        ("unchecked", "1 unchecked sentence(s)"),
    ]


def test_systematic_refuses_rate_above_ceiling(project: Project, agent: Actor) -> None:
    with_reviewer(project, agent)
    sd = stat_draft(project, 3)
    verify_all(project, sd.draft)
    audited(project, sd.draft, wrong=1)
    reasons = refusal(project, sd.draft, project.human_actor())
    assert ("audit", "the audit error rate is above the ceiling") in reasons
    assert ("flagged", "1 flagged sentence(s)") in reasons


def test_systematic_refuses_stale(
    project: Project, sd: SysDraft, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.writing import stats

    with_reviewer(project, agent)
    verify_all(project, sd.draft)
    audited(project, sd.draft)
    monkeypatch.setattr(stats, "confirmed_ideas", lambda _p: ["a"])
    # both sentences are stale, so none is live-supported either (cc3a08f)
    assert refusal(project, sd.draft, project.human_actor()) == [
        ("audit", "no live sentence is supported"),
        ("stale", "2 stale sentence(s)"),
    ]


def test_systematic_needs_the_audit(project: Project, sd: SysDraft, agent: Actor) -> None:
    with_reviewer(project, agent)
    verify_all(project, sd.draft)
    assert refusal(project, sd.draft, project.human_actor()) == [("audit", "no audit is drawn")]


def _rows(project: Project) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM draft_releases")).scalar_one())


def _forged(project: Project, draft: str, actor: Actor, **over: object) -> None:
    head = project.index.head()
    assert head is not None
    body: dict[str, object] = {
        "draft_id": draft,
        "as_of": head,
        "policy": PolicyKind.HUMAN,
        "counts": {"supported": 2},
        "audit": DraftAuditReport(drawn=2, labelled=2, incorrect=0, rate=0.0, above_ceiling=False),
        "released_by": actor.id,
    }
    body.update(over)
    blob = project.blobs.put_json({"forged": True}) if actor.kind == "agent" else None
    payload = DraftReleased.model_validate(body)
    project.record([project.events.make("draft.released", payload, actor, input_blob=blob)])


def test_forged_systematic_releases_are_inert(project: Project, sd: SysDraft, agent: Actor) -> None:
    with_reviewer(project, agent)
    verify_all(project, sd.draft)
    audited(project, sd.draft)
    me = project.human_actor()
    other = me.model_copy(update={"id": "ana"})
    _forged(project, sd.draft, agent)  # an agent, at a human gate
    _forged(project, sd.draft, other)  # a human who is not the reviewer of record
    _forged(project, sd.draft, me, counts={"flagged": 2})
    _forged(project, sd.draft, me, counts={"supported": 1, "unchecked": 1})
    assert _rows(project) == 0
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    _forged(project, sd.draft, me)  # control
    assert _rows(project) == 1


def test_forged_systematic_release_above_the_ceiling_is_inert(
    project: Project, agent: Actor
) -> None:
    with_reviewer(project, agent)
    sd = stat_draft(project, 2)
    verify_all(project, sd.draft)
    audited(project, sd.draft, wrong=1)
    _forged(project, sd.draft, project.human_actor())
    assert _rows(project) == 0
