"""`check` for drafts (slice 7b, plan W-B, task 6): each finding in a constructed case. Findings
carry ids and counts only; the agent view carries no rate, no ceiling flag and no label."""

from __future__ import annotations

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.drafts import (
    AuditLabel,
    DraftKind,
    SentenceClass,
    SentenceRecorded,
    SentenceVerified,
    Verdict,
)
from factory.model.project import RigorMode
from factory.services.check import _findings_as, agent_check, check
from factory.services.context import Project
from factory.services.draft_audit import draw_audit, open_audit_items, record_audit
from factory.services.draft_release import release
from factory.services.drafts import create_draft, write_sentences
from factory.services.project import init_project
from tests.draft_b_helpers import LOREM, SYNTH, W1, sent, verifier, verify_all, verify_one, writer

ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W"
BODY = "No idea is confirmed in part"


def stat_draft(project: Project, n: int = 2) -> tuple[str, list[str]]:
    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    done = write_sentences(
        project,
        draft,
        [sent("sec_01", SYNTH, f"{BODY} {'abcdef'[i]}", "stat:ideas-confirmed") for i in range(n)],
        actor=writer(),
    )
    return draft, done.written


def codes(project: Project) -> dict[str, list[str]]:
    return {f.code: f.refs for f in check(project).findings if f.code.startswith("draft-")}


def severity(project: Project, code: str, mode: RigorMode) -> list[str]:
    return [f.severity for f in _findings_as(project, mode) if f.code == code]


def label(project: Project, draft: str, wrong: int = 0) -> None:
    audit = draw_audit(project, draft)
    for i, (_, verdict) in enumerate(open_audit_items(project, draft)):
        chosen = AuditLabel.INCORRECT if i < wrong else AuditLabel.CORRECT
        record_audit(project, audit, verdict, chosen, None, actor=project.human_actor())


def test_a_fresh_project_has_no_draft_finding(project: Project) -> None:
    assert codes(project) == {}


def test_unchecked_finding(project: Project) -> None:
    draft, sentences = stat_draft(project)
    assert codes(project)["draft-sentence-unchecked"] == [draft, *sentences]


def test_flagged_finding(project: Project) -> None:
    draft, sentences = stat_draft(project, 1)
    verify_one(project, draft, Verdict.PARTIAL)
    assert codes(project)["draft-sentence-flagged"] == [draft, *sentences]


def test_stale_finding(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from factory.writing import stats

    draft, sentences = stat_draft(project, 1)
    monkeypatch.setattr(stats, "confirmed_ideas", lambda _p: ["a"])
    assert codes(project)["draft-sentence-stale"] == [draft, *sentences]


def test_audit_missing_finding(project: Project) -> None:
    draft, _ = stat_draft(project, 1)
    assert "draft-audit-missing" not in codes(project)  # nothing to audit yet
    verify_all(project, draft)
    assert codes(project)["draft-audit-missing"] == [draft]
    audit = draw_audit(project, draft)
    assert "draft-audit-missing" in codes(project)  # drawn, not labelled
    [(_, verdict)] = open_audit_items(project, draft)
    record_audit(project, audit, verdict, AuditLabel.CORRECT, None, actor=project.human_actor())
    assert "draft-audit-missing" not in codes(project)


def test_audit_missing_is_silent_in_exploratory(project: Project) -> None:
    draft, _ = stat_draft(project, 1)
    verify_all(project, draft)
    assert severity(project, "draft-audit-missing", RigorMode.EXPLORATORY) == []
    assert severity(project, "draft-audit-missing", RigorMode.SYSTEMATIC) == ["warning"]


def test_error_high_finding_by_mode(project: Project) -> None:
    draft, _ = stat_draft(project)
    verify_all(project, draft)
    label(project, draft, wrong=1)
    assert codes(project)["draft-verify-error-high"] == [draft]
    assert severity(project, "draft-verify-error-high", RigorMode.PILOT) == ["warning"]
    assert severity(project, "draft-verify-error-high", RigorMode.SYSTEMATIC) == ["error"]


def test_sentence_findings_are_warnings_until_released(
    settings: Settings, clock: FixedClock, agent: Actor
) -> None:
    project = init_project(settings, "loose", "exploratory", session=W1, clock=clock)
    draft, _ = stat_draft(project)
    code = "draft-sentence-unchecked"
    assert severity(project, code, RigorMode.SYSTEMATIC) == ["warning"]
    release(project, draft, actor=agent)
    assert severity(project, code, RigorMode.EXPLORATORY) == ["warning"]
    assert severity(project, code, RigorMode.SYSTEMATIC) == ["error"]
    promoted = check(project, promote_to=RigorMode.SYSTEMATIC)
    assert code in {f.code for f in promoted.findings}


def forge_verdict(project: Project, actor: Actor, sentence: str, n: int = 1) -> None:
    payload = SentenceVerified(
        verdict_id=f"svd_{ULID}{n:02d}",
        sentence_id=sentence,
        verdict=Verdict.UNSUPPORTED,
        sentence_span="No idea",
    )
    blob = project.blobs.put_json({"forged": True})
    project.record([project.events.make("draft.verified", payload, actor, input_blob=blob)])


def test_writer_verified_finding_is_an_error_in_every_mode(project: Project) -> None:
    """A verdict the fold refused still shows: it is in the log."""
    draft, sentences = stat_draft(project, 1)
    forge_verdict(project, writer(), sentences[0])
    assert codes(project)["draft-writer-verified"] == [draft, sentences[0]]
    for mode in RigorMode:
        assert severity(project, "draft-writer-verified", mode) == ["error"]


def test_writer_verified_finding_in_the_other_order(project: Project) -> None:
    """A sentence written by hand after the session's verdict."""
    draft, sentences = stat_draft(project, 1)
    verify_all(project, draft)
    payload = SentenceRecorded(
        sentence_id=f"snt_{ULID}01",
        draft_id=draft,
        section_id="sec_01",
        order=500,
        cls=SentenceClass.STRUCTURAL,
        text="Scope follows here",
        stats_version=1,
        author="agent",
    )
    blob = project.blobs.put_json({"forged": True})
    project.record(
        [project.events.make("draft.sentence_recorded", payload, verifier(), input_blob=blob)]
    )
    assert codes(project)["draft-writer-verified"] == [draft, sentences[0]]


def test_independent_verdicts_raise_no_finding(project: Project) -> None:
    draft, _ = stat_draft(project, 1)
    verify_all(project, draft)
    assert "draft-writer-verified" not in codes(project)


def test_findings_have_no_text(project: Project) -> None:
    draft, _ = stat_draft(project, 3)
    verify_one(project, draft, Verdict.OVERSTATED)
    said = " ".join(f.message + " ".join(f.refs) for f in check(project).findings)
    assert BODY not in said and LOREM not in said


def test_agent_view_withholds_rate(project: Project) -> None:  # Review Focus 5
    draft, _ = stat_draft(project)
    verify_all(project, draft)
    label(project, draft, wrong=1)
    assert any(f.code == "draft-verify-error-high" for f in check(project).findings)
    assert any(f.code == "draft-sentence-flagged" for f in check(project).findings)
    seen = agent_check(project).findings
    found = {f.code for f in seen}
    assert "draft-verify-error-high" not in found
    assert "draft-sentence-flagged" not in found  # flagged by a label only
    assert "draft-audit-reported" in found


def test_agent_view_is_the_same_above_and_below_the_ceiling(project: Project) -> None:
    high, _ = stat_draft(project)
    verify_all(project, high)
    label(project, high, wrong=1)
    above = [
        (f.code, f.severity, f.message)
        for f in agent_check(project).findings
        if f.code.startswith("draft-")
    ]
    assert above == [
        (
            "draft-audit-reported",
            "warning",
            "a draft's audit is labelled; its result is reported to the researcher",
        )
    ]


def test_agent_view_keeps_a_verdicts_flag(project: Project) -> None:
    draft, _ = stat_draft(project, 1)
    verify_one(project, draft, Verdict.PARTIAL)
    assert "draft-sentence-flagged" in {f.code for f in agent_check(project).findings}
