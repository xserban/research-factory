"""The human audit of supported verdicts (slice 7b, plan W-B, task 3; Review Focus 5).

The sample size rule and the draw are tested on stat sentences of a fresh project, which need no
screened world; a draw is recomputed by the fold, so a sample cannot be picked by hand.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.drafts import (
    AuditLabel,
    DraftAuditDrawn,
    DraftAudited,
    DraftAuditReport,
    DraftKind,
    Verdict,
)
from factory.model.screening import Channel
from factory.quality.stats import draw_uniform
from factory.services.context import Project
from factory.services.draft_audit import (
    agent_audit_report,
    audit_report,
    draw_audit,
    open_audit_items,
    record_audit,
)
from factory.services.drafts import create_draft, withdraw, write_sentences
from tests.draft_b_helpers import SYNTH, sent, verify_all, verify_one, writer
from tests.extraction_helpers import SESSION_A

ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W"
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def word(i: int) -> str:
    return LETTERS[i // 26 % 26] + LETTERS[i % 26]


def stat_sentences(project: Project, draft: str, n: int, start: int = 0) -> list[str]:
    sentences = [
        sent(
            "sec_01",
            SYNTH,
            f"No idea is confirmed in part {word(start + i)}",
            "stat:ideas-confirmed",
        )
        for i in range(n)
    ]
    written = write_sentences(project, draft, sentences, actor=writer()).written
    assert len(written) == n
    return written


def new_draft(project: Project, n: int, verdict: Verdict = Verdict.SUPPORTED) -> str:
    draft = create_draft(project, title="Notes", kind=DraftKind.OTHER, actor=project.human_actor())
    stat_sentences(project, draft, n)
    verify_all(project, draft, verdict)
    return draft


def items(project: Project, audit: str) -> list[str]:
    project.index.sync()
    with project.index.connect() as conn:
        return [
            str(r[0])
            for r in conn.execute(
                text("SELECT verdict_id FROM draft_audit_items WHERE audit_id = :a"), {"a": audit}
            )
        ]


def verdict_ids(project: Project, draft: str) -> list[str]:
    project.index.sync()
    with project.index.connect() as conn:
        return sorted(
            str(r[0])
            for r in conn.execute(
                text("SELECT verdict_id FROM sentence_verdicts WHERE draft_id = :d"), {"d": draft}
            )
        )


def label_all(project: Project, draft: str, wrong: int = 0) -> None:
    for i, (audit, verdict) in enumerate(open_audit_items(project, draft)):
        label = AuditLabel.INCORRECT if i < wrong else AuditLabel.CORRECT
        record_audit(project, audit, verdict, label, None, actor=project.human_actor())


@pytest.mark.parametrize(("n", "expected"), [(5, 5), (50, 20)])
def test_sample_size_rule(project: Project, n: int, expected: int) -> None:
    draft = new_draft(project, n)
    assert len(items(project, draw_audit(project, draft))) == expected


def test_sample_size_rule_above_the_minimum() -> None:
    from factory.model.drafts import DRAFT_AUDIT_FRACTION, DRAFT_AUDIT_MINIMUM
    from factory.quality.stats import audit_size

    assert audit_size(300, DRAFT_AUDIT_FRACTION, DRAFT_AUDIT_MINIMUM) == 30


def test_seed_recorded_and_draw_reproducible(project: Project) -> None:
    draft = new_draft(project, 25)
    audit = draw_audit(project, draft, seed=7)
    with project.index.connect() as conn:
        seed = conn.execute(
            text("SELECT seed FROM draft_audits WHERE audit_id = :a"), {"a": audit}
        ).scalar_one()
    assert seed == 7
    population = verdict_ids(project, draft)
    assert sorted(items(project, audit)) == draw_uniform(population, 20, 7, key=str)


def test_seed_out_of_range_refused(project: Project) -> None:
    draft = new_draft(project, 1)
    with pytest.raises(FactoryValidationError):
        draw_audit(project, draft, seed=-1)


def test_only_supported_unaudited_verdicts_drawn(project: Project) -> None:
    draft = create_draft(project, title="Notes", kind=DraftKind.OTHER, actor=project.human_actor())
    first = stat_sentences(project, draft, 3)
    verify_one(project, draft, Verdict.OVERSTATED)
    verify_one(project, draft)
    verify_one(project, draft)
    withdraw(project, first[2], "dropped", actor=writer())
    audit = draw_audit(project, draft)
    assert len(items(project, audit)) == 1
    with pytest.raises(FactoryValidationError) as caught:
        draw_audit(project, draft)  # nothing waits
    assert caught.value.issues[0].field == "audit"
    stat_sentences(project, draft, 1, start=9)
    verify_all(project, draft)
    second = draw_audit(project, draft)
    assert not set(items(project, audit)) & set(items(project, second))


def test_a_new_draw_waits_for_a_newer_verdict(project: Project) -> None:
    """Samples cannot be drawn until an easy one comes up, though verdicts remain undrawn."""
    draft = new_draft(project, 25)
    draw_audit(project, draft)
    with pytest.raises(FactoryValidationError) as caught:
        draw_audit(project, draft)
    assert caught.value.issues[0].reason == "no verdict is newer than the last draw"


def test_unknown_draft_and_nothing_to_draw_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        draw_audit(project, f"drf_{ULID}00")
    draft = create_draft(project, title="Notes", kind=DraftKind.OTHER, actor=project.human_actor())
    with pytest.raises(FactoryValidationError):
        draw_audit(project, draft)


def test_agent_cannot_label(project: Project, agent: Actor) -> None:
    draft = new_draft(project, 1)
    audit = draw_audit(project, draft)
    [(_, verdict)] = open_audit_items(project, draft)
    with pytest.raises(FactoryValidationError) as caught:
        record_audit(project, audit, verdict, AuditLabel.CORRECT, None, actor=agent)
    assert caught.value.issues[0].field == "actor"
    assert audit_report(project, draft).labelled == 0


def test_label_outside_the_sample_refused(project: Project) -> None:
    draft = new_draft(project, 1)
    audit = draw_audit(project, draft)
    me = project.human_actor()
    with pytest.raises(FactoryValidationError) as outside:
        record_audit(project, audit, f"svd_{ULID}00", AuditLabel.CORRECT, None, actor=me)
    assert outside.value.issues[0].field == "verdict_id"
    with pytest.raises(FactoryValidationError) as unknown:
        record_audit(project, f"dau_{ULID}00", f"svd_{ULID}00", AuditLabel.CORRECT, None, actor=me)
    assert unknown.value.issues[0].field == "audit_id"
    [(_, verdict)] = open_audit_items(project, draft)
    with pytest.raises(FactoryValidationError) as long:
        record_audit(project, audit, verdict, AuditLabel.CORRECT, "x" * 301, actor=me)
    assert long.value.issues[0].field == "note"


def test_mcp_relay_records_channel(project: Project) -> None:
    draft = new_draft(project, 1)
    audit = draw_audit(project, draft)
    [(_, verdict)] = open_audit_items(project, draft)
    record_audit(
        project,
        audit,
        verdict,
        AuditLabel.CORRECT,
        None,
        actor=project.human_actor(),
        channel=Channel.MCP,
    )
    with project.index.connect() as conn:
        assert conn.execute(text("SELECT channel FROM draft_audit_items")).scalar_one() == "mcp"


def test_a_pass_session_cannot_relay_a_label(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import passes

    draft = new_draft(project, 1)
    audit = draw_audit(project, draft)
    [(_, verdict)] = open_audit_items(project, draft)
    monkeypatch.setattr(passes, "is_pass_session", lambda *_a, **_k: True)
    with pytest.raises(FactoryValidationError) as caught:
        record_audit(
            project,
            audit,
            verdict,
            AuditLabel.CORRECT,
            None,
            actor=project.human_actor(),
            channel=Channel.MCP,
        )
    assert caught.value.issues[0].field == "channel"


def test_a_later_label_replaces_the_earlier(project: Project) -> None:
    draft = new_draft(project, 1)
    audit = draw_audit(project, draft)
    [(_, verdict)] = open_audit_items(project, draft)
    me = project.human_actor()
    record_audit(project, audit, verdict, AuditLabel.INCORRECT, "wrong", actor=me)
    record_audit(project, audit, verdict, AuditLabel.CORRECT, None, actor=me)
    report = audit_report(project, draft)
    assert (report.labelled, report.incorrect, report.rate) == (1, 0, 0.0)


def test_report_counts_and_ceiling(project: Project) -> None:
    draft = new_draft(project, 3)
    assert audit_report(project, draft) == DraftAuditReport(
        drawn=0, labelled=0, incorrect=0, rate=None, above_ceiling=None
    )
    draw_audit(project, draft)
    label_all(project, draft, wrong=1)
    report = audit_report(project, draft)
    assert (report.drawn, report.labelled, report.incorrect) == (3, 3, 1)
    assert report.rate == pytest.approx(1 / 3) and report.above_ceiling is True


def test_report_is_outdated_by_a_newer_verdict(project: Project) -> None:
    draft = new_draft(project, 1)
    draw_audit(project, draft)
    assert audit_report(project, draft).outdated is False
    stat_sentences(project, draft, 1, start=5)
    verify_all(project, draft)
    assert audit_report(project, draft).outdated is True


def test_rate_withheld_from_agent(project: Project) -> None:  # Review Focus 5
    draft = new_draft(project, 3)
    draw_audit(project, draft)
    label_all(project, draft, wrong=1)
    seen = agent_audit_report(audit_report(project, draft))
    assert (seen.rate, seen.above_ceiling, seen.incorrect) == (None, None, None)
    assert (seen.drawn, seen.labelled) == (3, 3)


# --- Hand-written events --------------------------------------------------------------------


def state(project: Project) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [
            *(tuple(r) for r in conn.execute(text("SELECT * FROM draft_audits"))),
            *(tuple(r) for r in conn.execute(text("SELECT * FROM draft_audit_items"))),
        ]


def forge_draw(
    project: Project, draft: str, actor: Actor, verdicts: list[str], seed: int, n: int = 1
) -> None:
    payload = DraftAuditDrawn(
        audit_id=f"dau_{ULID}{n:02d}",
        draft_id=draft,
        seed=seed,
        population=len(verdict_ids(project, draft)),
        verdict_ids=verdicts,
    )
    blob = None if actor.kind != "agent" else project.blobs.put_json({"forged": True})
    project.record([project.events.make("draft.audit_drawn", payload, actor, input_blob=blob)])


def assert_rebuilds(project: Project) -> None:
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


def test_forged_draw_control_folds(project: Project) -> None:
    draft = new_draft(project, 25)
    drawn = draw_uniform(verdict_ids(project, draft), 20, 5, key=str)
    forge_draw(project, draft, project.system_actor(), drawn, 5)
    assert state(project)
    assert_rebuilds(project)


def test_forged_draw_of_a_picked_sample_is_inert(project: Project) -> None:
    draft = new_draft(project, 25)
    drawn = draw_uniform(verdict_ids(project, draft), 20, 5, key=str)
    other = sorted(set(verdict_ids(project, draft)) - set(drawn))[:1] + drawn[1:]
    forge_draw(project, draft, project.system_actor(), sorted(other), 5)
    assert state(project) == []
    assert_rebuilds(project)


def test_forged_draw_by_a_human_or_agent_is_inert(project: Project, agent: Actor) -> None:
    draft = new_draft(project, 25)
    drawn = draw_uniform(verdict_ids(project, draft), 20, 5, key=str)
    forge_draw(project, draft, project.human_actor(), drawn, 5)
    forge_draw(project, draft, agent, drawn, 5, n=2)
    assert state(project) == []
    assert_rebuilds(project)


def test_forged_second_draw_is_inert(project: Project) -> None:
    draft = new_draft(project, 25)
    draw_audit(project, draft)
    before = state(project)
    rest = sorted(set(verdict_ids(project, draft)) - set(items_of(before)))
    forge_draw(project, draft, project.system_actor(), rest[:1], 5, n=3)
    assert state(project) == before


def items_of(rows: list[tuple[Any, ...]]) -> list[str]:
    return [str(r[1]) for r in rows if str(r[1]).startswith("svd_")]


def test_forged_label_by_an_agent_is_inert(project: Project, agent: Actor) -> None:
    draft = new_draft(project, 1)
    audit = draw_audit(project, draft)
    [(_, verdict)] = open_audit_items(project, draft)
    before = state(project)
    payload = DraftAudited(
        audit_id=audit, verdict_id=verdict, label=AuditLabel.CORRECT, channel=Channel.MCP
    )
    forged = project.blobs.put_json({"forged": True})
    project.record([project.events.make("draft.audited", payload, agent, input_blob=forged)])
    assert state(project) == before
    assert_rebuilds(project)
    project.record([project.events.make("draft.audited", payload, project.human_actor())])
    assert state(project) != before


def test_forged_label_outside_the_sample_is_inert(project: Project) -> None:
    draft = new_draft(project, 1)
    audit = draw_audit(project, draft)
    before = state(project)
    payload = DraftAudited(
        audit_id=audit, verdict_id=f"svd_{ULID}00", label=AuditLabel.CORRECT, channel=Channel.CLI
    )
    project.record([project.events.make("draft.audited", payload, project.human_actor())])
    assert state(project) == before


def test_session_constant_is_a_session(project: Project) -> None:
    assert project.session != SESSION_A
