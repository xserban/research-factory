"""Review and clean renderings and the `draft:` bibliography scope (plan W-B, task 4; Review
Focus 4). The renderings are read through the service, over real verdicts."""

# ruff: noqa: F401, F811

from __future__ import annotations

import re

import pytest

from factory.errors import FactoryValidationError
from factory.exports.keys import assign_keys
from factory.model.drafts import AuditLabel, DraftKind, Verdict
from factory.services.context import Project
from factory.services.draft_audit import draw_audit, open_audit_items, record_audit
from factory.services.drafts import (
    create_draft,
    draft_render,
    draft_view,
    draft_works,
    write_sentences,
)
from factory.services.exports import export_bibliography, select_works
from tests.draft_b_helpers import (
    CLAIM,
    INTERP,
    IPSUM,
    LOREM,
    QUOTE,
    STRUCT,
    Written,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    screened,
    sent,
    verifier,
    verify_all,
    verify_one,
    wd,
    write_draft,
    writer,
    ww,
)
from tests.writing_helpers import WWorld

MARK = re.compile(r"\[\[UNSUPPORTED: ")


def test_clean_marks_flagged(project: Project, wd: Written) -> None:  # Review Focus 4
    verify_one(project, wd.draft)
    verify_one(project, wd.draft, Verdict.OVERSTATED)
    out = draft_render(project, wd.draft, "clean")
    assert out.count("[[UNSUPPORTED: flagged; overstated]]") == 1
    assert len(MARK.findall(out)) == 1 and out.count("[[/]]") == 1
    start, end = out.index("[[UNSUPPORTED"), out.index("[[/]]")
    assert IPSUM in out[start:end] and LOREM not in out[start:end]


def test_clean_without_markers_when_all_supported(project: Project, wd: Written) -> None:
    verify_all(project, wd.draft)
    out = draft_render(project, wd.draft, "clean")
    assert "[[" not in out and LOREM in out and "Appendix" not in out


def test_clean_marks_unchecked_and_lists_it(project: Project, wd: Written) -> None:
    out = draft_render(project, wd.draft, "clean")
    assert out.count("[[UNSUPPORTED: unchecked; no-verdict]]") == 2
    appendix = out[out.index("Appendix") :]
    assert wd.first in appendix and wd.second in appendix and LOREM not in appendix


def test_interpretive_labelled(
    project: Project, wd: Written, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.model.intuition import ReviewState
    from factory.services import supports as supports_mod

    monkeypatch.setattr(supports_mod, "interpretation_state", lambda _p, _i: ReviewState.REVIEWED)
    interp = "interp:int_01JZ9Q3K5M7N8P0R2S4T6V8W00"
    written = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, INTERP, "This reads as a family", interp)],
        actor=writer(),
    )
    assert not written.rejected
    verify_all(project, wd.draft)
    out = draft_render(project, wd.draft, "clean")
    assert "[[INTERPRETATION]] This reads as a family [[/]]" in out
    assert "UNSUPPORTED" not in out


def test_citation_keys_in_support_order(project: Project, ww: WWorld, wd: Written) -> None:
    written = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "Both describe it", ww.claim(3), ww.claim(1), ww.cell(3))],
        actor=writer(),
    )
    assert not written.rejected
    verify_all(project, wd.draft)
    keys = assign_keys(select_works(project, f"draft:{wd.draft}"))
    expected = f"Both describe it [@{keys[ww.works[3]]}; @{keys[ww.works[1]]}]"
    assert expected in draft_render(project, wd.draft, "clean")


def test_structural_sentence_is_plain(project: Project, wd: Written) -> None:
    verify_all(project, wd.draft)
    out = draft_render(project, wd.draft, "clean")
    assert "The next paragraph states the scope " in out


def test_counts_and_methods(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft)
    out = draft_render(project, wd.draft, "clean")
    title_part, methods = out.split("## Methods")
    assert "structural 1, supported 1, unchecked 1" in title_part
    assert "structural 1, supported 1, unchecked 1" in methods
    assert f"--scope draft:{wd.draft}" in out and "No audit" in methods


def test_methods_state_the_audit_to_the_researcher_only(project: Project, wd: Written) -> None:
    verify_all(project, wd.draft)
    audit = draw_audit(project, wd.draft)
    verdicts = open_audit_items(project, wd.draft)
    me = project.human_actor()
    record_audit(project, audit, verdicts[0][1], AuditLabel.INCORRECT, None, actor=me)
    record_audit(project, audit, verdicts[1][1], AuditLabel.CORRECT, None, actor=me)
    full = draft_render(project, wd.draft, "clean")
    assert "found 1 incorrect (error rate 0.500)" in full and "audit-incorrect" in full
    seen = draft_render(project, wd.draft, "clean", agent=True)
    assert "error rate" not in seen and "incorrect" not in seen and "[[" not in seen
    assert "reported to the researcher" in seen


def test_same_model_pair_is_stated(project: Project, wd: Written) -> None:
    from tests.draft_b_helpers import WRITER_MODEL

    verify_one(project, wd.draft, actor=verifier(model=WRITER_MODEL))
    assert "Verdicts by the writer's model: 1." in draft_render(project, wd.draft, "clean")


def test_review_shows_status_flags_and_quotes(project: Project, ww: WWorld, wd: Written) -> None:
    write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "All methods are described", ww.claim(2))],
        actor=writer(),
    )
    verify_one(project, wd.draft, Verdict.PARTIAL)
    out = draft_render(project, wd.draft, "review")
    assert "{flagged; partial}" in out and "{unchecked}" in out and "{structural}" in out
    assert "flags: quantifier-without-statistic" in out
    assert ww.claim(0) in out and f"> {QUOTE}" in out


def test_review_shows_quotes_from_events_only(
    project: Project, wd: Written, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_library(*_a: object, **_k: object) -> bytes:
        raise AssertionError("the library was read")

    monkeypatch.setattr(project.library, "get", no_library)
    assert QUOTE in draft_render(project, wd.draft, "review")


def test_render_deterministic(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft)
    assert draft_render(project, wd.draft, "clean") == draft_render(project, wd.draft, "clean")
    assert draft_render(project, wd.draft, "review") == draft_render(project, wd.draft, "review")


def test_render_writes_nothing(project: Project, wd: Written) -> None:
    before = project.index.head()
    draft_render(project, wd.draft, "clean")
    assert project.index.head() == before


def test_a_fresh_draft_renders(project: Project) -> None:
    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    out = draft_render(project, draft, "clean")
    assert out.startswith("# N") and "No sentences." in out and "[[" not in out
    assert draft_render(project, draft, "review").startswith("# N")
    assert draft_works(project, draft) == []


def test_unknown_draft_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        draft_render(project, "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", "clean")


def test_bibliography_scope_draft(project: Project, ww: WWorld, wd: Written) -> None:
    chosen = select_works(project, f"draft:{wd.draft}")
    assert chosen == sorted(ww.works[:2])
    body = "".join(export_bibliography(project, "bibtex", scope=f"draft:{wd.draft}"))
    assert body.count("@") == 2


def test_bibliography_scope_lists_only_cited_works(
    project: Project, ww: WWorld, wd: Written
) -> None:
    """A withdrawn sentence's work is no longer cited."""
    from factory.services.drafts import withdraw

    withdraw(project, wd.second, "dropped", actor=writer())
    assert select_works(project, f"draft:{wd.draft}") == [ww.works[0]]


def test_bibliography_keeps_the_work_of_a_marked_stale_sentence(
    project: Project, ww: WWorld, wd: Written
) -> None:
    from tests.test_draft_status import supersede_claim

    supersede_claim(project, ww.claims[ww.works[0]])
    assert ww.works[0] in select_works(project, f"draft:{wd.draft}")


def test_view_has_empty_sections_for_slots_not_written(project: Project, wd: Written) -> None:
    view = draft_view(project, wd.draft)
    assert len(view.sections) > 1
    assert [len(s.sentences) for s in view.sections if s.section_id == wd.section] == [3]


def test_unknown_scope_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        select_works(project, "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99")
    with pytest.raises(FactoryValidationError):
        select_works(project, "draft:drf_01JZ9Q3K5M7N8P0R2S4T6V8W99")
