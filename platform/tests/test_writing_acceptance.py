"""Acceptance of the writing slice, automated (slice 7b, plan W-B, task 7; acceptance 7 to 11, 15).

A pilot-shaped fixture: three ideas, two comparability groups and 15 scripted sentences, written by
one session and judged by another, run end to end through the services: outline, write, verify,
audit, release in pilot, the clean rendering and the BibTeX of the draft's scope. Values are
invented; no literature text.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.drafts import AuditLabel, DraftKind, DraftReleased, SentenceClass, Verdict
from factory.model.lineage import LineageDecision
from factory.services.context import Project
from factory.services.draft_audit import audit_report, draw_audit, open_audit_items, record_audit
from factory.services.draft_release import release
from factory.services.draft_verify import verify_next, verify_record
from factory.services.drafts import (
    create_draft,
    draft_render,
    get_draft,
    sentence_status,
    status_counts,
    write_sentences,
)
from factory.services.exports import export_bibliography, select_works
from factory.services.ideas import decide_idea, propose_idea
from factory.services.outline import build_outline
from factory.services.trace import trace
from factory.services.write_rows import visible_rows_by_group
from tests.draft_b_helpers import (
    CLAIM,
    STRUCT,
    SYNTH,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    screened,
    sent,
    verdict_on,
    verifier,
    writer,
    ww,
)
from tests.extraction_helpers import _item
from tests.lineage_helpers import record_both
from tests.writing_helpers import WWorld

pytestmark = pytest.mark.slow
KINDS = ("base-idea", "addition", "limitation")


def more_ideas(
    project: Project, ww: WWorld, agent: Actor, human: Actor, ctr_a: Actor, ctr_b: Actor
) -> None:
    """Two more confirmed ideas, each named by a base-idea item of its own work."""
    for work in ww.works[1:3]:
        ids, _ = record_both(project, ctr_a, ctr_b, work, [_item(k) for k in KINDS])
        idea = propose_idea(project, agent, "Lorem", work, ids[0], [work, ww.works[3]])
        decide_idea(project, human, idea, LineageDecision.CONFIRM, "named")


def script(project: Project, ww: WWorld, draft: str) -> list[tuple[str, object, str, list[str]]]:
    row = get_draft(project, draft)
    assert row is not None
    sections = [s.section_id for s in row.sections]
    groups = sorted(visible_rows_by_group(project).groups)
    first, second = sections[0], sections[1]
    out: list[tuple[str, object, str, list[str]]] = [
        (first, STRUCT, "This section sets out the first line of work", []),
    ]
    for i in range(6):
        out.append((first, CLAIM, f"Lorem is described in part {'abcdef'[i]}", [ww.claim(i)]))
    for i in range(4):
        out.append((second, CLAIM, f"The value is stated in part {'ghij'[i]}", [ww.cell(i)]))
    out.append((second, SYNTH, "Three ideas are confirmed", ["stat:ideas-confirmed"]))
    out.append((second, SYNTH, "The rows of one group agree in form", [f"group:{groups[0]}"]))
    out.append((second, SYNTH, "The rows of another group agree in form", [f"group:{groups[1]}"]))
    out.append((second, STRUCT, "The next section turns to what is missing", []))
    return out


def test_related_work_end_to_end(
    project: Project,
    ww: WWorld,
    agent: Actor,
    other_session_human: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
) -> None:
    more_ideas(project, ww, agent, other_session_human, ctr_a, ctr_b)
    outline = build_outline(project)
    assert sum(1 for s in outline.sections if s.kind == "idea") == 3
    assert sum(1 for s in outline.sections if s.kind == "group") == 2

    me = project.human_actor()
    draft = create_draft(project, title="Related work", kind=DraftKind.RELATED_WORK, actor=me)
    planned = script(project, ww, draft)
    assert len(planned) == 15
    written = write_sentences(
        project,
        draft,
        [sent(section, cls, body, *supports) for section, cls, body, supports in planned],  # type: ignore[arg-type]
        actor=writer(),
    )
    assert not written.rejected and len(written.written) == 15

    with pytest.raises(FactoryValidationError):  # the writer cannot verify
        verify_next(project, draft, actor=writer())

    judged = 0
    who = verifier()
    while (unit := verify_next(project, draft, actor=who)) is not None:
        verdict = Verdict.OVERSTATED if judged == 1 else Verdict.SUPPORTED
        verify_record(project, unit.task_id, verdict_on(unit, verdict), actor=who)
        judged += 1
    assert judged == 13

    with pytest.raises(FactoryValidationError):  # the audit comes first in pilot
        release(project, draft, actor=agent)
    audit = draw_audit(project, draft)
    for _, verdict_id in open_audit_items(project, draft):
        record_audit(project, audit, verdict_id, AuditLabel.CORRECT, None, actor=me)
    report = audit_report(project, draft)
    assert (report.drawn, report.labelled, report.rate) == (12, 12, 0.0)

    release(project, draft, actor=agent)
    [event] = [
        DraftReleased.model_validate(e.payload)
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "draft.released"
    ]
    counts = status_counts(sentence_status(project, draft))
    assert counts == {
        "structural": 2,
        "interpretive": 0,
        "unchecked": 0,
        "supported": 12,
        "flagged": 1,
        "stale": 0,
    }
    assert event.counts == counts and event.audit.rate == 0.0

    clean = draft_render(project, draft, "clean")
    assert clean.count("[[UNSUPPORTED: flagged; overstated]]") == 1 and clean.count("[[/]]") == 1
    assert "[@" in clean and "flagged 1, structural 2, supported 12" in clean

    cited = select_works(project, f"draft:{draft}")
    assert cited == sorted(ww.works[:6])
    bibtex = "".join(export_bibliography(project, "bibtex", scope=f"draft:{draft}"))
    assert bibtex.count("@") == len(cited)

    claim_sentence = written.written[1]
    tree = trace(project, claim_sentence)

    def kinds(node: object) -> set[str]:
        return {node.kind}.union(*(kinds(c) for c in node.children))  # type: ignore[attr-defined]

    assert {"sentence", "claim", "work", "question"} <= kinds(tree)
    assert project.index.rebuild() == project.index.state_hash()
