"""Verdicts and verification units (slice 7b, plan W-B, task 1; Review Focus 1 and 2).

Independence is tested in both directions, at the service and, with hand-written events, at the
fold: an event a service would refuse stays in the log and changes nothing, on rebuild too.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.drafts import SentenceVerified, SupportSpan, Verdict
from factory.services.context import Project
from factory.services.draft_verify import VerdictInput, verify_next, verify_record
from factory.services.drafts import live_sentences, withdraw, write_sentences
from factory.services.tasks import task_counts
from tests.draft_b_helpers import (
    CLAIM,
    IPSUM,
    LOREM,
    QUOTE,
    STRUCT,
    SYNTH,
    V1,
    V2,
    VERIFIER_MODEL,
    W1,
    WRITER_MODEL,
    Written,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    screened,
    sent,
    verdict_on,
    verifier,
    verify_one,
    wd,
    write_draft,
    writer,
    ww,
)
from tests.writing_helpers import WWorld

ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W"


def verdicts(project: Project) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT * FROM sentence_verdicts"))]


def refused(field: str, call: Any, *args: Any, **kw: Any) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        call(*args, **kw)
    assert field in [i.field for i in caught.value.issues]


def test_independence_both_directions(project: Project, wd: Written) -> None:  # Review Focus 1
    refused("session", verify_next, project, wd.draft, actor=writer())
    verify_one(project, wd.draft)
    refused(
        "session",
        write_sentences,
        project,
        wd.draft,
        [sent(wd.section, STRUCT, "Scope follows")],
        actor=verifier(),
    )


def test_a_writer_holding_a_unit_cannot_record(project: Project, wd: Written) -> None:
    """A session that claimed a unit and wrote in the draft afterwards is refused at the record."""
    who = verifier(V2)
    unit = verify_next(project, wd.draft, actor=who)
    assert unit is not None
    write_sentences(project, wd.draft, [sent(wd.section, STRUCT, "Scope follows")], actor=who)
    refused("session", verify_record, project, unit.task_id, verdict_on(unit), actor=who)
    assert verdicts(project) == []


def test_superseded_and_withdrawn_sentences_keep_their_writer_out(
    project: Project, wd: Written
) -> None:
    other = writer("01JZ9Q3K5M7N8P0R2S4T6V8W33")
    write_sentences(
        project,
        wd.draft,
        [sent(wd.section, STRUCT, "Scope comes next")],
        actor=other,
    )
    live = [r for r in live_sentences(project, wd.draft) if r.session == other.session]
    withdraw(project, live[0].sentence_id, "not needed", actor=other)
    refused("session", verify_next, project, wd.draft, actor=other)


def test_a_human_writer_is_kept_out_across_sessions(
    project: Project, ww: WWorld, settings: Settings, clock: FixedClock
) -> None:
    """A human's session changes with each command: the human is kept out by id."""
    me = project.human_actor()
    written = write_draft(project, ww, me)
    later = me.model_copy(update={"session": V2})
    refused("session", verify_next, project, written.draft, actor=later)


def test_a_human_may_verify_an_agents_sentence(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft, actor=project.human_actor())
    assert len(verdicts(project)) == 1
    refused(
        "session",
        write_sentences,
        project,
        wd.draft,
        [sent(wd.section, STRUCT, "Scope follows")],
        actor=project.human_actor().model_copy(update={"session": V2}),
    )


def test_pilot_records_the_same_model_pair(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft, actor=verifier(model=WRITER_MODEL))
    assert WRITER_MODEL in verdicts(project)[0]


def test_unit_content_has_no_writer_material(project: Project, wd: Written) -> None:
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    dumped = unit.model_dump()
    assert set(dumped) == {"sentence_id", "text", "cls", "context_previous", "supports", "task_id"}
    assert unit.text == LOREM and unit.context_previous is None
    assert QUOTE in unit.supports[0].spans[0]
    assert "writer" not in repr(dumped) and WRITER_MODEL not in repr(dumped)


def test_unit_shows_the_preceding_sentence_as_context(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft)
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None and unit.text == IPSUM
    assert unit.context_previous == "The next paragraph states the scope"


def test_input_blob_is_the_unit(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft)
    project.index.sync()
    with project.index.connect() as conn:
        blob = conn.execute(
            text("SELECT input_blob FROM events WHERE type = 'draft.verified'")
        ).scalar_one()
    content = project.blobs.get_json(str(blob))
    assert isinstance(content, dict) and content["text"] == LOREM and "task_id" not in content


def test_a_stat_only_sentence_can_be_supported(project: Project, ww: WWorld, wd: Written) -> None:
    """A stat has no quote: its value is its span, so a synthesis on it can be `supported`."""
    done = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, SYNTH, "One idea is confirmed in total", "stat:ideas-confirmed")],
        actor=writer(),
    )
    assert done.written
    verify_one(project, wd.draft)
    verify_one(project, wd.draft)
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None and unit.supports[0].stat_value == 1
    verify_record(project, unit.task_id, verdict_on(unit), actor=verifier())
    assert len(verdicts(project)) == 3


def test_group_and_cell_supports_show_their_values(
    project: Project, ww: WWorld, wd: Written
) -> None:
    group = _group_of(project)
    done = write_sentences(
        project,
        wd.draft,
        [
            sent(wd.section, CLAIM, "The value is recorded", ww.cell(0)),
            sent(wd.section, SYNTH, "The group has rows", f"group:{group}"),
        ],
        actor=writer(),
    )
    assert not done.rejected
    verify_one(project, wd.draft)
    verify_one(project, wd.draft)
    cell = verify_next(project, wd.draft, actor=verifier())
    assert cell is not None and cell.supports[0].value == "2"
    assert "2" in cell.supports[0].spans
    verify_record(project, cell.task_id, verdict_on(cell), actor=verifier())
    grouped = verify_next(project, wd.draft, actor=verifier())
    assert grouped is not None and grouped.supports[0].spans


def _group_of(project: Project) -> str:
    from factory.services.write_rows import visible_rows_by_group

    return sorted(visible_rows_by_group(project).groups)[0]


def test_sentence_span_must_be_substring(project: Project, wd: Written) -> None:
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    good = verdict_on(unit, Verdict.PARTIAL)
    bad = good.model_copy(update={"sentence_span": "not in the sentence"})
    refused("sentence_span", verify_record, project, unit.task_id, bad, actor=verifier())
    none = good.model_copy(update={"sentence_span": None})
    refused("sentence_span", verify_record, project, unit.task_id, none, actor=verifier())
    spaced = good.model_copy(update={"sentence_span": "Lorem   is\ndescribed"})
    verify_record(project, unit.task_id, spaced, actor=verifier())
    assert len(verdicts(project)) == 1


def test_support_substring_verified(project: Project, wd: Written) -> None:  # Review Focus 2
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    ref = unit.supports[0].ref
    bad = VerdictInput(
        verdict=Verdict.SUPPORTED,
        support_spans=[SupportSpan(ref=ref, substring="words the source never used")],
    )
    refused(
        "support_spans[0].substring", verify_record, project, unit.task_id, bad, actor=verifier()
    )
    empty = VerdictInput(verdict=Verdict.SUPPORTED)
    refused("support_spans", verify_record, project, unit.task_id, empty, actor=verifier())
    assert verdicts(project) == []


def test_unsupported_may_name_no_support(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft, Verdict.UNSUPPORTED)
    assert verdicts(project)[0][3] == "unsupported"


def test_ref_outside_supports_refused(project: Project, ww: WWorld, wd: Written) -> None:
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    outside = VerdictInput(
        verdict=Verdict.SUPPORTED,
        support_spans=[SupportSpan(ref=ww.claim(2), substring=QUOTE)],
    )
    refused("support_spans[0].ref", verify_record, project, unit.task_id, outside, actor=verifier())


def test_note_is_bounded(project: Project, wd: Written) -> None:
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    long = verdict_on(unit).model_copy(update={"note": "x" * 301})
    refused("note", verify_record, project, unit.task_id, long, actor=verifier())


def test_structural_and_interpretive_not_served(project: Project, wd: Written) -> None:
    served = {verify_one(project, wd.draft), verify_one(project, wd.draft)}
    assert served == {wd.first, wd.second}
    assert verify_next(project, wd.draft, actor=verifier()) is None


def test_a_sentence_has_one_verdict(project: Project, wd: Written) -> None:
    """A task lease that ran out cannot give a second verdict: the first stands."""
    first = verifier()
    second = verifier(V2)
    unit = verify_next(project, wd.draft, actor=first)
    other = verify_next(project, wd.draft, actor=second)
    assert unit is not None and other is not None and unit.sentence_id != other.sentence_id
    verify_record(project, unit.task_id, verdict_on(unit), actor=first)
    refused("task_id", verify_record, project, unit.task_id, verdict_on(unit), actor=first)


def test_superseding_sentence_needs_new_verdict(project: Project, ww: WWorld, wd: Written) -> None:
    assert verify_one(project, wd.draft) == wd.first
    done = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "Lorem is stated", ww.claim(0), supersedes=wd.first)],
        actor=writer(),
    )
    served = verify_next(project, wd.draft, actor=verifier())
    assert served is not None and served.sentence_id == done.written[0]


def test_a_superseded_sentence_cannot_be_recorded(
    project: Project, ww: WWorld, wd: Written
) -> None:
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "Lorem is stated", ww.claim(0), supersedes=wd.first)],
        actor=writer(),
    )
    refused("sentence_id", verify_record, project, unit.task_id, verdict_on(unit), actor=verifier())


def test_a_verdict_needs_the_verify_skill(project: Project, wd: Written) -> None:
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    wrong = verifier().model_copy(update={"skill": "rf-write@1a2b3c4d"})
    refused("skill", verify_record, project, unit.task_id, verdict_on(unit), actor=wrong)


def test_system_actor_refused(project: Project, wd: Written) -> None:
    refused("actor", verify_next, project, wd.draft, actor=project.system_actor())


def test_no_text_in_errors(project: Project, wd: Written) -> None:
    unit = verify_next(project, wd.draft, actor=verifier())
    assert unit is not None
    probe = "secret words of a document"
    bad = VerdictInput(
        verdict=Verdict.PARTIAL,
        sentence_span=probe,
        support_spans=[SupportSpan(ref=unit.supports[0].ref, substring=probe)],
    )
    with pytest.raises(FactoryValidationError) as caught:
        verify_record(project, unit.task_id, bad, actor=verifier())
    said = repr(caught.value.issues)
    assert probe not in said and LOREM not in said and QUOTE not in said


def test_verification_tasks_are_not_counted(project: Project, wd: Written) -> None:
    before = task_counts(project)
    verify_next(project, wd.draft, actor=verifier())
    assert task_counts(project) == before


# --- Hand-written events --------------------------------------------------------------------


def _forged(
    project: Project,
    actor: Actor,
    sentence: str,
    blob: str | None,
    *,
    n: int = 1,
    **over: Any,
) -> SentenceVerified:
    body: dict[str, Any] = {
        "verdict_id": f"svd_{ULID}{n:02d}",
        "sentence_id": sentence,
        "verdict": Verdict.SUPPORTED,
        "support_spans": [],
    }
    body.update(over)
    payload = SentenceVerified.model_validate(body)
    project.record([project.events.make("draft.verified", payload, actor, input_blob=blob)])
    return payload


def _unit_blob(project: Project, wd: Written, ww: WWorld) -> tuple[str, list[SupportSpan]]:
    unit = verify_next(project, wd.draft, actor=verifier(V2))
    assert unit is not None
    content = unit.model_dump(mode="json", exclude={"task_id"})
    spans = [SupportSpan(ref=unit.supports[0].ref, substring=QUOTE)]
    return project.blobs.put_json(content), spans


def _inert(project: Project, *args: Any, **kw: Any) -> None:
    before = verdicts(project)
    _forged(project, *args, **kw)
    assert verdicts(project) == before
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


def test_forged_verdict_control_folds(project: Project, ww: WWorld, wd: Written) -> None:
    blob, spans = _unit_blob(project, wd, ww)
    _forged(project, verifier(), wd.first, blob, support_spans=spans)
    assert len(verdicts(project)) == 1
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


def test_forged_verdict_by_the_writer_is_inert(project: Project, ww: WWorld, wd: Written) -> None:
    blob, spans = _unit_blob(project, wd, ww)
    _inert(project, writer(), wd.first, blob, support_spans=spans)


def test_forged_verdict_with_a_foreign_quote_is_inert(
    project: Project, ww: WWorld, wd: Written
) -> None:
    blob, spans = _unit_blob(project, wd, ww)
    made_up = [SupportSpan(ref=spans[0].ref, substring="the source never said this")]
    _inert(project, verifier(), wd.first, blob, support_spans=made_up)


def test_forged_verdict_on_another_unit_is_inert(project: Project, ww: WWorld, wd: Written) -> None:
    blob, spans = _unit_blob(project, wd, ww)
    _inert(project, verifier(), wd.second, blob, support_spans=spans)


def test_forged_verdict_on_a_structural_sentence_is_inert(
    project: Project, ww: WWorld, wd: Written
) -> None:
    blob, spans = _unit_blob(project, wd, ww)
    _inert(project, verifier(), wd.structural, blob, support_spans=spans)


def test_forged_verdict_of_a_system_actor_or_other_skill_is_inert(
    project: Project, ww: WWorld, wd: Written
) -> None:
    blob, spans = _unit_blob(project, wd, ww)
    _inert(project, project.system_actor(), wd.first, blob, support_spans=spans)
    wrong = verifier().model_copy(update={"skill": "rf-write@1a2b3c4d"})
    _inert(project, wrong, wd.first, blob, support_spans=spans)


def test_forged_second_verdict_is_inert(project: Project, ww: WWorld, wd: Written) -> None:
    """An unsupported verdict cannot be overwritten by writing a supported one by hand."""
    blob, spans = _unit_blob(project, wd, ww)
    _forged(
        project,
        verifier(),
        wd.first,
        blob,
        verdict=Verdict.UNSUPPORTED,
        sentence_span="Lorem",
    )
    _inert(project, verifier(), wd.first, blob, n=2, support_spans=spans)


def test_forged_sentence_by_a_verifier_is_inert(project: Project, wd: Written) -> None:
    from factory.model.drafts import SentenceClass, SentenceRecorded

    verify_one(project, wd.draft)

    def forged(actor: Actor, n: int) -> SentenceRecorded:
        return SentenceRecorded(
            sentence_id=f"snt_{ULID}{n:02d}",
            draft_id=wd.draft,
            section_id=wd.section,
            order=500,
            cls=SentenceClass.STRUCTURAL,
            text="Scope follows here",
            stats_version=1,
            author="agent",
        )

    before = len(live_sentences(project, wd.draft))
    project.record(
        [
            project.events.make(
                "draft.sentence_recorded",
                forged(verifier(), 1),
                verifier(),
                input_blob=project.blobs.put_json({"forged": True}),
            )
        ]
    )
    assert len(live_sentences(project, wd.draft)) == before
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    project.record(
        [
            project.events.make(
                "draft.sentence_recorded",
                forged(writer(), 2),
                writer(),
                input_blob=project.blobs.put_json({"forged": True}),
            )
        ]
    )
    assert len(live_sentences(project, wd.draft)) == before + 1
