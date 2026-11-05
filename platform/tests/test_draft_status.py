"""Computed sentence status and staleness (slice 7b, plan W-B, task 2; Review Focus 3)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.drafts import AuditLabel, DraftKind, Verdict
from factory.model.lineage import LineageDecision
from factory.services import supports as supports_mod
from factory.services.context import Project
from factory.services.draft_audit import draw_audit, open_audit_items, record_audit
from factory.services.drafts import (
    StatusRow,
    sentence_status,
    status_counts,
    withdraw,
    write_sentences,
)
from factory.services.relations import decide_relation
from tests.draft_b_helpers import (
    CLAIM,
    INTERP,
    STRUCT,
    SYNTH,
    Written,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    screened,
    sent,
    verify_all,
    verify_one,
    wd,
    writer,
    ww,
)
from tests.writing_helpers import WWorld


def status(project: Project, draft: str, sentence: str, *, agent: bool = False) -> StatusRow:
    return next(
        r for r in sentence_status(project, draft, agent=agent) if r.sentence_id == sentence
    )


def supersede_claim(project: Project, claim_id: str) -> None:
    """Test double of a re-extraction: the claim row reads as superseded (see test_supports)."""
    project.index.sync()
    with project.index.connect() as conn:
        conn.execute(
            text("UPDATE extraction_claims SET superseded_by = 'clm_X' WHERE claim_id = :c"),
            {"c": claim_id},
        )
        conn.commit()


def test_unchecked_until_a_verdict(project: Project, wd: Written) -> None:
    rows = sentence_status(project, wd.draft)
    assert [r.status for r in rows] == ["unchecked", "structural", "unchecked"]
    assert all(r.reason is None for r in rows)


def test_supported_and_flagged_follow_the_verdict(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft)
    verify_one(project, wd.draft, Verdict.OVERSTATED)
    assert status(project, wd.draft, wd.first).status == "supported"
    flagged = status(project, wd.draft, wd.second)
    assert (flagged.status, flagged.reason) == ("flagged", "overstated")


def test_precedence(project: Project, ww: WWorld, wd: Written) -> None:
    """stale over flagged over supported."""
    verify_all(project, wd.draft, Verdict.PARTIAL)
    assert status(project, wd.draft, wd.first).status == "flagged"
    supersede_claim(project, ww.claims[ww.works[0]])
    got = status(project, wd.draft, wd.first)
    assert (got.status, got.reason) == ("stale", "superseded")


def test_superseded_claim_stales_sentence(
    project: Project, ww: WWorld, wd: Written
) -> None:  # Review Focus 3
    verify_all(project, wd.draft)
    assert status(project, wd.draft, wd.first).status == "supported"
    supersede_claim(project, ww.claims[ww.works[0]])
    assert status(project, wd.draft, wd.first).status == "stale"
    assert status(project, wd.draft, wd.second).status == "supported"


def test_excluded_work_stales(
    project: Project, ww: WWorld, wd: Written, monkeypatch: pytest.MonkeyPatch
) -> None:
    verify_all(project, wd.draft)
    states = {ww.works[0]: SimpleNamespace(synthesis="excluded")}
    monkeypatch.setattr(supports_mod, "work_states", lambda _p: states)
    got = status(project, wd.draft, wd.first)
    assert (got.status, got.reason) == ("stale", "not-included")


def test_rejected_edge_stales(
    project: Project, ww: WWorld, wd: Written, other_session_human: Actor
) -> None:
    written = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "It builds on the earlier work", f"edge:{ww.confirmed_edge}")],
        actor=writer(),
    )
    assert not written.rejected
    verify_all(project, wd.draft)
    [sentence] = written.written
    assert status(project, wd.draft, sentence).status == "supported"
    decide_relation(
        project, other_session_human, ww.confirmed_edge, LineageDecision.REJECT, "no basis"
    )
    got = status(project, wd.draft, sentence)
    assert (got.status, got.reason) == ("stale", "rejected")


def test_stat_change_stales(
    project: Project, ww: WWorld, wd: Written, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.writing import stats

    written = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, SYNTH, "One idea is confirmed in total", "stat:ideas-confirmed")],
        actor=writer(),
    )
    verify_all(project, wd.draft)
    [sentence] = written.written
    assert status(project, wd.draft, sentence).status == "supported"
    monkeypatch.setattr(stats, "confirmed_ideas", lambda _p: ["a", "b"])
    got = status(project, wd.draft, sentence)
    assert (got.status, got.reason) == ("stale", "stat-changed")


def test_interp_wrong_stales_interpretive(
    project: Project, wd: Written, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.model.intuition import ReviewState

    interp = "interp:int_01JZ9Q3K5M7N8P0R2S4T6V8W00"
    reviewed = ReviewState.REVIEWED
    monkeypatch.setattr(supports_mod, "interpretation_state", lambda _p, _i: reviewed)
    written = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, INTERP, "This reads as a family", interp)],
        actor=writer(),
    )
    assert not written.rejected
    [sentence] = written.written
    assert status(project, wd.draft, sentence).status == "interpretive"
    monkeypatch.setattr(supports_mod, "interpretation_state", lambda _p, _i: ReviewState.WRONG)
    got = status(project, wd.draft, sentence)
    assert (got.status, got.reason) == ("stale", "rejected")


def test_audit_incorrect_flags(project: Project, wd: Written) -> None:
    verify_all(project, wd.draft)
    audit = draw_audit(project, wd.draft)
    verdicts = open_audit_items(project, wd.draft)
    me = project.human_actor()
    record_audit(project, audit, verdicts[0][1], AuditLabel.INCORRECT, "wrong", actor=me)
    rows = sentence_status(project, wd.draft)
    assert [r.reason for r in rows if r.status == "flagged"] == ["audit-incorrect"]
    assert status_counts(rows)["supported"] == 1
    assert "wrong" not in repr(rows)


def test_agent_variant_leaves_audit_labels_out(project: Project, wd: Written) -> None:
    """The sentences an audit flags would give an agent the error rate (decision 37.14)."""
    verify_all(project, wd.draft)
    audit = draw_audit(project, wd.draft)
    for _, verdict in open_audit_items(project, wd.draft):
        record_audit(
            project, audit, verdict, AuditLabel.INCORRECT, None, actor=project.human_actor()
        )
    seen = sentence_status(project, wd.draft, agent=True)
    assert status_counts(seen) == {
        "structural": 1,
        "interpretive": 0,
        "unchecked": 0,
        "supported": 2,
        "flagged": 0,
        "stale": 0,
    }


def test_counts_derived(project: Project, ww: WWorld, wd: Written) -> None:
    verify_one(project, wd.draft)
    counts = status_counts(sentence_status(project, wd.draft))
    assert counts["supported"] == 1 and counts["unchecked"] == 1 and counts["structural"] == 1
    assert sum(counts.values()) == 3


def test_withdrawn_sentence_has_no_status(project: Project, wd: Written) -> None:
    withdraw(project, wd.first, "dropped", actor=writer())
    assert wd.first not in {r.sentence_id for r in sentence_status(project, wd.draft)}


def test_revising_restarts_verification(project: Project, ww: WWorld, wd: Written) -> None:
    verify_all(project, wd.draft)
    written = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "Lorem is stated", ww.claim(0), supersedes=wd.first)],
        actor=writer(),
    )
    [revised] = written.written
    assert status(project, wd.draft, revised).status == "unchecked"


def test_flags_are_carried(project: Project, ww: WWorld, wd: Written) -> None:
    written = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "All methods are described", ww.claim(0))],
        actor=writer(),
    )
    [sentence] = written.written
    assert "quantifier-without-statistic" in status(project, wd.draft, sentence).flags


def test_fresh_project_structural_only(project: Project) -> None:
    from factory.services.drafts import create_draft

    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    assert sentence_status(project, draft) == []
    written = write_sentences(
        project, draft, [sent("sec_01", STRUCT, "Scope follows")], actor=writer()
    )
    assert written.written
    assert status_counts(sentence_status(project, draft))["structural"] == 1
