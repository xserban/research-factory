"""Drafts, slots and sentence recording (slice 7b, plan W-A, task 5; Review Focus 1 and 5)."""

# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

import factory.services.drafts as drafts_mod
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.drafts import DraftKind, SentenceClass, SentenceFlag
from factory.model.task import TaskStatus
from factory.services.context import Project
from factory.services.drafts import (
    SentenceInput,
    create_draft,
    draft_next,
    get_draft,
    list_drafts,
    live_sentences,
    reorder,
    repin_outline,
    withdraw,
    write_sentences,
)
from factory.services.outline import OutlineScope
from factory.services.tasks import get_task
from tests.contribution_helpers import ctr_a, ctr_b, ext_a, screened  # noqa: F401
from tests.views_b_helpers import ext_b  # noqa: F401
from tests.writing_helpers import WWorld, ww  # noqa: F401

W1 = "01JZ9Q3K5M7N8P0R2S4T6V8W11"
W2 = "01JZ9Q3K5M7N8P0R2S4T6V8W12"
CLAIM, SYNTH, STRUCT = SentenceClass.CLAIM, SentenceClass.SYNTHESIS, SentenceClass.STRUCTURAL
LOREM = "Lorem is described in the method section"


def writer(session: str = W1) -> Actor:
    return Actor(
        kind="agent",
        id="writer",
        user="obd",
        session=session,
        model="claude-sonnet-5-5",
        skill="rf-write@1a2b3c4d",
    )


def sent(
    section: str, cls: SentenceClass, body: str, *supports: str, **kw: object
) -> SentenceInput:
    return SentenceInput(section_id=section, cls=cls, text=body, supports=list(supports), **kw)  # type: ignore[arg-type]


@pytest.fixture
def me(project: Project) -> Actor:
    return project.human_actor()


@pytest.fixture
def draft(project: Project, ww: WWorld, me: Actor) -> str:
    return create_draft(project, title="Related work", kind=DraftKind.RELATED_WORK, actor=me)


def section_of(project: Project, draft: str, ref_prefix: str) -> str:
    row = get_draft(project, draft)
    assert row is not None
    return next(
        s.section_id for s in row.sections if (s.outline_section or "").startswith(ref_prefix)
    )


def test_create_pins_the_outline_and_makes_a_section_per_slot(
    project: Project, ww: WWorld, draft: str
) -> None:
    row = get_draft(project, draft)
    assert row is not None and row.outline_ref.startswith("OL@")
    refs = [s.outline_section for s in row.sections]
    assert refs[0] == f"idea:{ww.idea}" and refs[-1] == "limits"
    assert [s.section_id for s in row.sections] == [f"sec_{i + 1:02d}" for i in range(len(refs))]
    assert [d.draft_id for d in list_drafts(project)] == [draft]


def test_create_refuses_a_blank_title_and_a_system_actor(project: Project, ww: WWorld) -> None:
    with pytest.raises(FactoryValidationError):
        create_draft(project, title=" ", kind=DraftKind.OTHER, actor=project.human_actor())
    with pytest.raises(FactoryValidationError):
        create_draft(project, title="x", kind=DraftKind.OTHER, actor=project.system_actor())


def test_partial_acceptance_per_sentence(
    project: Project, ww: WWorld, draft: str
) -> None:  # Review Focus 1
    sec = section_of(project, draft, "idea:")
    result = write_sentences(
        project,
        draft,
        [
            sent(sec, CLAIM, LOREM, ww.claim(0)),
            sent(
                sec, CLAIM, "It builds on the earlier work", ww.claim(1), f"edge:{ww.inferred_edge}"
            ),
            sent(sec, STRUCT, "The next paragraph states the scope"),
        ],
        actor=writer(),
    )
    assert len(result.written) == 2
    [bad] = result.rejected
    assert bad.index == 1
    assert [(i.field, i.reason) for i in bad.issues] == [("supports[1]", "inferred")]
    live = live_sentences(project, draft)
    assert [r.text for r in live] == [LOREM, "The next paragraph states the scope"]


def test_everything_refused_writes_nothing(project: Project, ww: WWorld, draft: str) -> None:
    sec = section_of(project, draft, "idea:")
    before = project.index.head()
    result = write_sentences(
        project,
        draft,
        [sent(sec, CLAIM, "It works", "claim:clm_01JZ9Q3K5M7N8P0R2S4T6V8W99")],
        actor=writer(),
    )
    assert result.written == [] and len(result.rejected) == 1
    assert project.index.head() == before


def test_bad_items_are_reported_by_field(project: Project, ww: WWorld, draft: str) -> None:
    sec = section_of(project, draft, "idea:")
    result = write_sentences(
        project,
        draft,
        [
            sent("sec_77", STRUCT, "Scope follows"),
            sent(sec, CLAIM, "It works", "not-a-support"),
            sent(sec, CLAIM, "It works", ww.claim(0), ww.claim(0)),
            sent(sec, STRUCT, "Scope follows", supersedes="snt_01JZ9Q3K5M7N8P0R2S4T6V8W99"),
            sent(sec, STRUCT, "x" * 401),
        ],
        actor=writer(),
    )
    assert result.written == []
    fields = [{i.field for i in r.issues} for r in result.rejected]
    assert fields == [
        {"section_id"},
        {"supports[0]"},
        {"supports"},
        {"supersedes"},
        {"text"},
    ]


def test_unknown_draft_and_wrong_actor(project: Project, ww: WWorld, draft: str) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        write_sentences(project, "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", [], actor=writer())
    assert caught.value.issues[0].field == "draft_id"
    with pytest.raises(FactoryValidationError):
        write_sentences(project, draft, [], actor=project.system_actor())


def test_supersede_marks_old_and_keeps_order(project: Project, ww: WWorld, draft: str) -> None:
    sec = section_of(project, draft, "idea:")
    first = write_sentences(
        project,
        draft,
        [
            sent(sec, CLAIM, LOREM, ww.claim(0)),
            sent(sec, STRUCT, "The next paragraph states scope"),
        ],
        actor=writer(),
    )
    a, b = first.written
    again = write_sentences(
        project,
        draft,
        [sent(sec, CLAIM, "Lorem is described in the method", ww.claim(0), supersedes=a)],
        actor=writer(),
    )
    live = live_sentences(project, draft)
    assert [r.sentence_id for r in live] == [again.written[0], b]
    assert live[0].order < live[1].order and live[0].supersedes == a
    with project.index.connect() as conn:
        assert (
            conn.execute(
                text("SELECT superseded_by FROM draft_sentences WHERE sentence_id = :s"), {"s": a}
            ).scalar_one()
            == again.written[0]
        )
    # the old sentence cannot be superseded again
    redo = write_sentences(
        project, draft, [sent(sec, STRUCT, "Scope again", supersedes=a)], actor=writer()
    )
    assert redo.rejected[0].issues[0].field == "supersedes"


def test_withdraw_and_reorder(project: Project, ww: WWorld, draft: str, me: Actor) -> None:
    sec = section_of(project, draft, "idea:")
    a, b, c = write_sentences(
        project,
        draft,
        [
            sent(
                sec,
                STRUCT,
                f"Scope {n} follows".replace("1", "one").replace("2", "two").replace("3", "three"),
            )
            for n in (1, 2, 3)
        ],
        actor=me,
    ).written
    reorder(project, draft, sec, [c, a, b], actor=me)
    assert [r.sentence_id for r in live_sentences(project, draft)] == [c, a, b]
    withdraw(project, a, "no longer needed", actor=me)
    assert [r.sentence_id for r in live_sentences(project, draft)] == [c, b]
    with pytest.raises(FactoryValidationError):
        withdraw(project, a, "again", actor=me)
    with pytest.raises(FactoryValidationError):
        reorder(project, draft, sec, [c], actor=me)  # b is missing
    with pytest.raises(FactoryValidationError):
        reorder(project, draft, "sec_99", [c, b], actor=me)
    with pytest.raises(FactoryValidationError):
        withdraw(project, "snt_01JZ9Q3K5M7N8P0R2S4T6V8W99", "x", actor=me)
    reorder(project, draft, sec, [b, c], actor=me)
    assert [r.sentence_id for r in live_sentences(project, draft)] == [b, c]


def test_slot_task_content_has_spans_and_is_input_blob(
    project: Project, ww: WWorld, draft: str
) -> None:
    slot = draft_next(project, draft, actor=writer())
    assert slot is not None and slot.section_id == section_of(project, draft, "idea:")
    shown = {s["ref"]: s for s in slot.content["supports"]}  # type: ignore[union-attr]
    claim = shown[ww.claim(0)]
    assert claim["quotes"] == ["Lorem ipsum dolor sit amet."]  # the verified quote, in the task
    assert shown[f"item:{ww.base_item}"]["works"] == [ww.works[0]]
    assert f"edge:{ww.inferred_edge}" not in shown
    task = get_task(project, slot.task_id)
    assert task is not None and task.status is TaskStatus.CLAIMED
    assert project.blobs.get_json(task.content_blob) == slot.content
    # the same session is served the same task again
    assert draft_next(project, draft, actor=writer()) is not None
    assert draft_next(project, draft, actor=writer()).task_id == slot.task_id  # type: ignore[union-attr]
    # another session is not served it, but gets the next section
    other = draft_next(project, draft, actor=writer(W2))
    assert other is not None and other.section_id != slot.section_id

    written = write_sentences(
        project,
        draft,
        [sent(slot.section_id, CLAIM, LOREM, ww.claim(0))],
        actor=writer(),
        task_id=slot.task_id,
    )
    assert len(written.written) == 1
    done = get_task(project, slot.task_id)
    assert done is not None and done.status is TaskStatus.COMPLETED
    # the sentence's event carries the call and the task content as its input (R-04)
    project.index.sync()
    with project.index.connect() as conn:
        blob = conn.execute(
            text("SELECT input_blob FROM events WHERE type = 'draft.sentence_recorded'")
        ).scalar_one()
    seen = project.blobs.get_json(str(blob))
    assert isinstance(seen, dict) and seen["task_input"] == task.content_blob
    with project.index.connect() as conn:
        assert (
            conn.execute(text("SELECT task_id FROM draft_sentences")).scalar_one() == slot.task_id
        )
    # the section has a sentence now: the next slot is another one
    nxt = draft_next(project, draft, actor=writer())
    assert nxt is not None and nxt.section_id != slot.section_id


def test_draft_next_is_for_agents_and_known_drafts(
    project: Project, ww: WWorld, draft: str, me: Actor
) -> None:
    with pytest.raises(FactoryValidationError):
        draft_next(project, draft, actor=me)
    with pytest.raises(FactoryValidationError):
        draft_next(project, "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", actor=writer())
    with pytest.raises(FactoryValidationError):
        draft_next(project, draft, section_id="sec_99", actor=writer())


def test_draft_next_returns_none_when_every_section_has_a_sentence(
    project: Project, ww: WWorld, draft: str, me: Actor
) -> None:
    row = get_draft(project, draft)
    assert row is not None
    for s in row.sections:
        assert write_sentences(
            project, draft, [sent(s.section_id, STRUCT, "Scope follows")], actor=me
        ).written
    assert draft_next(project, draft, actor=writer()) is None
    named = draft_next(project, draft, section_id="sec_01", actor=writer())
    assert named is not None and named.section_id == "sec_01"


def test_slot_task_is_refused_for_another_draft_or_a_human(
    project: Project, ww: WWorld, draft: str, me: Actor
) -> None:
    other = create_draft(project, title="Other", kind=DraftKind.OTHER, actor=me)
    slot = draft_next(project, draft, actor=writer())
    assert slot is not None
    with pytest.raises(FactoryValidationError) as caught:
        write_sentences(
            project,
            other,
            [sent("sec_01", STRUCT, "Scope follows")],
            actor=writer(),
            task_id=slot.task_id,
        )
    assert caught.value.issues[0].field == "task_id"
    with pytest.raises(FactoryValidationError):
        write_sentences(
            project,
            draft,
            [sent(slot.section_id, STRUCT, "Scope follows")],
            actor=me,
            task_id=slot.task_id,
        )
    with pytest.raises(FactoryValidationError):  # a session that does not hold it
        write_sentences(
            project,
            draft,
            [sent(slot.section_id, STRUCT, "Scope follows")],
            actor=writer(W2),
            task_id=slot.task_id,
        )


def test_no_quote_text_in_events(project: Project, ww: WWorld, draft: str) -> None:  # Focus 5
    sec = section_of(project, draft, "idea:")
    write_sentences(
        project,
        draft,
        [sent(sec, CLAIM, LOREM, ww.claim(0), ww.cell(0), f"item:{ww.base_item}")],
        actor=writer(),
    )
    project.index.sync()
    with project.index.connect() as conn:
        quotes = {
            str(q)
            for (q,) in conn.execute(
                text(
                    "SELECT quote FROM extraction_claims UNION SELECT quote FROM extraction_fields "
                    "WHERE quote IS NOT NULL AND length(quote) > 12"
                )
            )
        }
        blob = conn.execute(text("SELECT outline_blob FROM drafts")).scalar_one()
    assert "Lorem ipsum dolor sit amet." in quotes
    log = "".join(p.read_text("utf-8") for p in sorted(project.paths.events_dir.rglob("*.jsonl")))
    draft_lines = [ln for ln in log.splitlines() if '"type":"draft.' in ln]
    assert len(draft_lines) == 2
    outline = project.blobs.get(str(blob)).decode()
    for quote in quotes:
        assert quote not in outline
        assert not any(quote in ln for ln in draft_lines), quote


def test_human_sentence_has_no_model(project: Project, ww: WWorld, draft: str, me: Actor) -> None:
    (sid,) = write_sentences(
        project, draft, [sent("sec_01", STRUCT, "Scope follows")], actor=me
    ).written
    (row,) = [r for r in live_sentences(project, draft) if r.sentence_id == sid]
    assert (row.author, row.model, row.task_id) == ("human", None, None)


def test_agent_sentence_outside_a_slot_carries_provenance(
    project: Project, ww: WWorld, draft: str
) -> None:
    sec = section_of(project, draft, "idea:")
    (sid,) = write_sentences(
        project, draft, [sent(sec, CLAIM, LOREM, ww.claim(0))], actor=writer()
    ).written
    (row,) = [r for r in live_sentences(project, draft) if r.sentence_id == sid]
    assert (row.author, row.model, row.task_id) == ("agent", "claude-sonnet-5-5", None)
    project.index.sync()
    with project.index.connect() as conn:
        blob = conn.execute(
            text("SELECT input_blob FROM events WHERE type = 'draft.sentence_recorded'")
        ).scalar_one()
    assert project.blobs.get_json(str(blob)) is not None


def test_stat_values_are_stored_as_computed(project: Project, ww: WWorld, draft: str) -> None:
    sec = section_of(project, draft, "limits")
    (sid,) = write_sentences(
        project,
        draft,
        [sent(sec, SYNTH, "1 idea is confirmed", "stat:ideas-confirmed")],
        actor=writer(),
    ).written
    (row,) = [r for r in live_sentences(project, draft) if r.sentence_id == sid]
    assert row.stat_values == {"ideas-confirmed": 1}
    # a number the platform did not compute is refused
    bad = write_sentences(
        project,
        draft,
        [sent(sec, SYNTH, "7 ideas are confirmed", "stat:ideas-confirmed")],
        actor=writer(),
    )
    assert bad.written == []
    assert bad.rejected[0].issues[0].reason == "number-unsupported"


def test_verifier_session_cannot_write(
    project: Project, ww: WWorld, draft: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drafts_mod, "verifier_sessions", lambda _p, _d: frozenset({W1}))
    with pytest.raises(FactoryValidationError) as caught:
        write_sentences(project, draft, [sent("sec_01", STRUCT, "Scope follows")], actor=writer())
    assert caught.value.issues[0].field == "session"
    assert write_sentences(
        project, draft, [sent("sec_01", STRUCT, "Scope follows")], actor=writer(W2)
    ).written


def test_structural_context_names_the_drafts_methods(
    project: Project, ww: WWorld, draft: str, me: Actor
) -> None:
    sec = section_of(project, draft, "idea:")
    write_sentences(project, draft, [sent(sec, CLAIM, LOREM, ww.cell(0))], actor=me)
    refused = write_sentences(
        project, draft, [sent(sec, STRUCT, "Next we turn to lorem")], actor=me
    )
    assert refused.rejected[0].issues[0].reason == "structural-method-name"


def test_off_outline_flag_at_write_time_and_after_repin(
    project: Project, ww: WWorld, draft: str, me: Actor
) -> None:
    sec = section_of(project, draft, "idea:")
    on, off = write_sentences(
        project,
        draft,
        [
            sent(sec, CLAIM, LOREM, ww.cell(0)),
            sent(sec, CLAIM, "The result is listed", f"item:{ww.result_item}"),
        ],
        actor=me,
    ).written
    flags = {r.sentence_id: r.flags for r in live_sentences(project, draft)}
    assert flags[on] == [] and flags[off] == [SentenceFlag.OFF_OUTLINE]
    repin_outline(project, draft, OutlineScope(groups=()), actor=me)  # no group sections now
    flags = {r.sentence_id: r.flags for r in live_sentences(project, draft)}
    assert SentenceFlag.OFF_OUTLINE in flags[on]
    with project.index.connect() as conn:
        stored = conn.execute(
            text("SELECT flag FROM sentence_flags WHERE sentence_id = :s"), {"s": on}
        ).all()
    assert stored == []  # the flag is computed on read, nothing is rewritten


def test_events_of_a_draft_carry_no_prose_beyond_the_sentence(
    project: Project, ww: WWorld, draft: str, tmp_path: Path
) -> None:
    log = "".join(p.read_text("utf-8") for p in sorted(project.paths.events_dir.rglob("*.jsonl")))
    created = [json.loads(ln) for ln in log.splitlines() if '"type":"draft.created"' in ln]
    assert len(created) == 1 and set(created[0]["payload"]) == {
        "draft_id", "title", "kind", "outline_ref", "outline_blob", "sections",
    }  # fmt: skip
