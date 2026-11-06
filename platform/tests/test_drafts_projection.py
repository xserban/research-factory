"""The draft projection: tables, rebuild and hand-written events (slice 7b, plan W-A, task 5).

A hand-written event that fails a projector guard stays in the log and changes nothing, on rebuild
too (as `tests/test_forged_events.py`); each case has a control where the same event, right, folds.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, text
from sqlalchemy.engine import Connection

from factory.events.envelope import Actor, Event
from factory.index.default import default_projection
from factory.index.drafts import _total
from factory.index.index import OMITTED_WHEN_EMPTY
from factory.model.base import StrictModel
from factory.model.drafts import (
    MAX_ORDER,
    DraftCreated,
    DraftKind,
    DraftOutlineRepinned,
    DraftReordered,
    SectionDef,
    SentenceClass,
    SentenceRecorded,
    SentenceWithdrawn,
    parse_support,
)
from factory.services.context import Project
from factory.services.drafts import (
    SentenceInput,
    create_draft,
    get_draft,
    live_sentences,
    repin_outline,
    write_sentences,
)
from factory.services.outline import OutlineScope
from tests.helpers import S2

SKIP = {"events", "event_refs", "meta", "sync_state"}
ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W"
CLAIM = f"claim:clm_{ULID}00"
DRAFT_TABLES = (
    "drafts",
    "draft_sections",
    "draft_sentences",
    "sentence_supports",
    "sentence_flags",
    "sentence_stats",
    "sentence_verdicts",
    "draft_audits",
    "draft_audit_items",
    "draft_releases",
)


def sid(n: int) -> str:
    return f"snt_{ULID}{n:02d}"


def state(project: Project) -> dict[str, list[str]]:
    project.index.sync()
    with project.index.connect() as conn:
        return {
            n: sorted(repr(tuple(r)) for r in conn.execute(text(f'SELECT * FROM "{n}"')))
            for n in DRAFT_TABLES
        }


def forge(project: Project, type_: str, model: StrictModel, actor: Actor) -> None:
    blob = None if actor.kind == "human" else project.blobs.put_json({"forged": True})
    project.record([project.events.make(type_, model, actor, input_blob=blob)])


def inert(project: Project, type_: str, model: StrictModel, actor: Actor) -> None:
    before = state(project)
    forge(project, type_, model, actor)
    assert state(project) == before, f"{type_} by {actor.kind} folded"
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    assert state(project) == before


def folds(project: Project, type_: str, model: StrictModel, actor: Actor) -> None:
    before = state(project)
    forge(project, type_, model, actor)
    assert state(project) != before, f"{type_} by {actor.kind} did not fold"
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


@pytest.fixture
def me(project: Project) -> Actor:
    return project.human_actor()


@pytest.fixture
def draft(project: Project, me: Actor) -> str:
    return create_draft(project, title="Notes", kind=DraftKind.OTHER, actor=me)


def sentence(draft_id: str, n: int = 1, **over: Any) -> SentenceRecorded:
    body: dict[str, Any] = {
        "sentence_id": sid(n),
        "draft_id": draft_id,
        "section_id": "sec_01",
        "order": 10,
        "cls": SentenceClass.CLAIM,
        "text": "Lorem is described in the method section.",
        "supports": [parse_support(CLAIM)],
        "stats_version": 1,
        "author": "human",
    }
    body.update(over)
    return SentenceRecorded.model_validate(body)


def test_tables_are_omitted_when_empty_and_version_is_bumped() -> None:
    from factory.index.default import PROJECTION_VERSION

    assert set(DRAFT_TABLES) <= OMITTED_WHEN_EMPTY
    assert PROJECTION_VERSION == "57"
    assert set(DRAFT_TABLES) <= set(default_projection().metadata.tables)


def test_a_log_without_drafts_keeps_its_state_hash(project: Project) -> None:
    project.index.sync()
    assert project.index.state_hash() == project.index.rebuild()


def test_create_projects_draft_and_sections(project: Project, draft: str) -> None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT title, kind, creator_kind FROM drafts WHERE draft_id = :d"), {"d": draft}
        ).one()
        sections = conn.execute(
            text("SELECT section_id, outline_section FROM draft_sections WHERE draft_id = :d"),
            {"d": draft},
        ).all()
    assert tuple(row) == ("Notes", "other", "human")
    assert [tuple(s) for s in sections] == [("sec_01", "limits")]  # a fresh project: limits only


def test_rebuild_identical_tables(project: Project, draft: str, me: Actor) -> None:
    write_sentences(
        project,
        draft,
        [SentenceInput(section_id="sec_01", cls=SentenceClass.STRUCTURAL, text="Scope follows")],
        actor=me,
    )
    before = state(project)
    assert any(before[t] for t in DRAFT_TABLES[:3])
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    assert state(project) == before
    assert [r.text for r in live_sentences(project, draft)] == ["Scope follows"]


# --- Hand-written events ---


def test_draft_created_guards(project: Project, me: Actor, draft: str) -> None:
    with project.index.connect() as conn:
        ref, blob = conn.execute(text("SELECT outline_ref, outline_blob FROM drafts")).one()
    system = project.system_actor()
    body = {
        "title": "Other",
        "kind": DraftKind.OTHER,
        "outline_ref": ref,
        "outline_blob": blob,
        "sections": [SectionDef(section_id="sec_01", heading="h")],
    }
    inert(project, "draft.created", DraftCreated(draft_id=f"drf_{ULID}01", **body), system)
    inert(project, "draft.created", DraftCreated(draft_id=draft, **body), me)  # duplicate id
    wrong = {**body, "outline_ref": "OL@00000000"}  # the blob does not hash to it
    inert(project, "draft.created", DraftCreated(draft_id=f"drf_{ULID}02", **wrong), me)
    folds(project, "draft.created", DraftCreated(draft_id=f"drf_{ULID}03", **body), me)


def test_repin_guards(project: Project, me: Actor, draft: str) -> None:
    with project.index.connect() as conn:
        ref, blob = conn.execute(text("SELECT outline_ref, outline_blob FROM drafts")).one()
    inert(
        project,
        "draft.outline_repinned",
        DraftOutlineRepinned(draft_id=draft, outline_ref="OL@00000000", outline_blob=blob),
        me,
    )
    inert(
        project,
        "draft.outline_repinned",
        DraftOutlineRepinned(draft_id=draft, outline_ref=ref, outline_blob=blob),
        project.system_actor(),
    )
    other = project.blobs.put_json({"outline_id": "OL@11111111", "scope": {}, "sections": []})
    inert(  # an empty outline does not hash to 11111111
        project,
        "draft.outline_repinned",
        DraftOutlineRepinned(draft_id=draft, outline_ref="OL@11111111", outline_blob=other),
        me,
    )
    before = state(project)  # control: the service pins a true outline
    repin_outline(project, draft, OutlineScope(ideas=(), groups=()), actor=me)
    assert state(project) != before


@pytest.mark.parametrize(
    ("label", "over"),
    [
        ("unknown draft", {"draft_id": f"drf_{ULID}99"}),
        ("unknown section", {"section_id": "sec_09"}),
        ("author is not the actor's kind", {"author": "agent"}),
        ("claim without support", {"supports": []}),
        ("synthesis without stat or group", {"cls": SentenceClass.SYNTHESIS}),
        ("two sentences", {"text": "It works. It fails."}),
        ("supersedes an unknown sentence", {"supersedes": sid(77)}),
        (
            "structural with a claim in it",
            {
                "cls": SentenceClass.STRUCTURAL,
                "supports": [],
                "text": "Performer reaches 91.5% (Smith, 2021)",
            },
        ),
        (
            "structural with a citation and no number",
            {"cls": SentenceClass.STRUCTURAL, "supports": [], "text": "As \\cite{smith} shows"},
        ),
        (
            "interpretive with a number",
            {
                "cls": SentenceClass.INTERPRETIVE,
                "supports": [],
                "text": "It reaches 91.5 percent",
            },
        ),
    ],
)
def test_sentence_guards(
    project: Project, me: Actor, draft: str, label: str, over: dict[str, Any]
) -> None:
    body = {"draft_id": draft, **over}
    inert(project, "draft.sentence_recorded", sentence(**body), me)


@pytest.mark.parametrize("cls", [SentenceClass.STRUCTURAL, SentenceClass.INTERPRETIVE])
def test_a_plain_structural_or_interpretive_sentence_folds(
    project: Project, me: Actor, draft: str, cls: SentenceClass
) -> None:  # the control of the cases above
    model = sentence(draft, cls=cls, supports=[], text="Next comes the scope")
    folds(project, "draft.sentence_recorded", model, me)


def test_sentence_by_a_system_actor_and_duplicate_ids(
    project: Project, me: Actor, draft: str
) -> None:
    inert(project, "draft.sentence_recorded", sentence(draft), project.system_actor())
    folds(project, "draft.sentence_recorded", sentence(draft), me)  # control
    inert(project, "draft.sentence_recorded", sentence(draft), me)  # the same id again


def test_supersession_guards(project: Project, me: Actor, draft: str) -> None:
    forge(project, "draft.sentence_recorded", sentence(draft, 1), me)
    inert(
        project,
        "draft.sentence_recorded",
        sentence(draft, 2, section_id="sec_09", supersedes=sid(1)),
        me,
    )
    folds(project, "draft.sentence_recorded", sentence(draft, 2, supersedes=sid(1)), me)
    # sentence 1 is superseded now: it cannot be superseded again, nor withdrawn
    inert(project, "draft.sentence_recorded", sentence(draft, 3, supersedes=sid(1)), me)
    inert(
        project, "draft.sentence_withdrawn", SentenceWithdrawn(sentence_id=sid(1), reason="x"), me
    )


def test_withdraw_guards(project: Project, me: Actor, draft: str) -> None:
    forge(project, "draft.sentence_recorded", sentence(draft, 1), me)
    inert(
        project, "draft.sentence_withdrawn", SentenceWithdrawn(sentence_id=sid(9), reason="x"), me
    )
    inert(
        project,
        "draft.sentence_withdrawn",
        SentenceWithdrawn(sentence_id=sid(1), reason="x"),
        project.system_actor(),
    )
    folds(
        project, "draft.sentence_withdrawn", SentenceWithdrawn(sentence_id=sid(1), reason="x"), me
    )
    inert(
        project, "draft.sentence_withdrawn", SentenceWithdrawn(sentence_id=sid(1), reason="y"), me
    )


def test_reorder_guards(project: Project, me: Actor, draft: str) -> None:
    forge(project, "draft.sentence_recorded", sentence(draft, 1, order=10), me)
    forge(project, "draft.sentence_recorded", sentence(draft, 2, order=20), me)
    both = [sid(2), sid(1)]
    inert(
        project,
        "draft.reordered",
        DraftReordered(draft_id=draft, section_id="sec_01", order=[sid(1)]),
        me,
    )
    inert(
        project,
        "draft.reordered",
        DraftReordered(draft_id=draft, section_id="sec_01", order=[sid(1), sid(2), sid(3)]),
        me,
    )
    inert(
        project,
        "draft.reordered",
        DraftReordered(draft_id=draft, section_id="sec_09", order=both),
        me,
    )
    inert(
        project,
        "draft.reordered",
        DraftReordered(draft_id=draft, section_id="sec_01", order=both),
        project.system_actor(),
    )
    folds(
        project,
        "draft.reordered",
        DraftReordered(draft_id=draft, section_id="sec_01", order=both),
        me,
    )
    assert [r.sentence_id for r in live_sentences(project, draft)] == both


MISSING_BLOB = "sha256:" + "0" * 64


def corrupt_blob(project: Project) -> str:
    """A stored blob whose bytes no longer hash to its ref."""
    ref = project.blobs.put(b'{"outline_id": "OL@00000000", "scope": {}, "sections": []}')
    path = project.blobs.path(ref)
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    return ref


def test_a_draft_naming_an_unreadable_blob_does_not_break_the_fold(
    project: Project, me: Actor, draft: str
) -> None:
    for n, blob in enumerate((MISSING_BLOB, corrupt_blob(project))):
        model = DraftCreated(
            draft_id=f"drf_{ULID}{n + 10:02d}",
            title="Other",
            kind=DraftKind.OTHER,
            outline_ref="OL@00000000",
            outline_blob=blob,
            sections=[SectionDef(section_id="sec_01", heading="h")],
        )
        inert(project, "draft.created", model, me)
    assert get_draft(project, draft) is not None  # the index still reads


def test_a_repin_naming_an_unreadable_blob_does_not_break_the_fold(
    project: Project, me: Actor, draft: str
) -> None:
    for blob in (MISSING_BLOB, corrupt_blob(project)):
        model = DraftOutlineRepinned(draft_id=draft, outline_ref="OL@00000000", outline_blob=blob)
        inert(project, "draft.outline_repinned", model, me)
    assert get_draft(project, draft) is not None


def test_an_agent_sentence_folds_with_its_session_and_model(project: Project, draft: str) -> None:
    agent = Actor(
        kind="agent", id="writer", user="obd", session=S2, model="m-1", skill="rf-write@1a2b3c4d"
    )
    folds(project, "draft.sentence_recorded", sentence(draft, 1, author="agent"), agent)
    (row,) = live_sentences(project, draft)
    assert (row.author, row.session, row.model) == ("agent", S2, "m-1")


def test_an_outline_blob_naming_another_id_is_refused(
    project: Project, me: Actor, draft: str
) -> None:
    with project.index.connect() as conn:
        ref, blob = conn.execute(text("SELECT outline_ref, outline_blob FROM drafts")).one()
    data = project.blobs.get_json(str(blob))
    assert isinstance(data, dict)
    other = project.blobs.put_json({**data, "outline_id": "OL@11111111"})  # same scope, sections
    model = DraftOutlineRepinned(draft_id=draft, outline_ref=str(ref), outline_blob=other)
    inert(project, "draft.outline_repinned", model, me)


def test_supersedes_stays_within_the_draft(project: Project, me: Actor, draft: str) -> None:
    other = create_draft(project, title="Other", kind=DraftKind.OTHER, actor=me)
    forge(project, "draft.sentence_recorded", sentence(draft, 1), me)
    inert(project, "draft.sentence_recorded", sentence(other, 2, supersedes=sid(1)), me)


def test_a_withdrawn_sentence_is_not_superseded(project: Project, me: Actor, draft: str) -> None:
    forge(project, "draft.sentence_recorded", sentence(draft, 1), me)
    forge(
        project, "draft.sentence_withdrawn", SentenceWithdrawn(sentence_id=sid(1), reason="x"), me
    )
    inert(project, "draft.sentence_recorded", sentence(draft, 2, supersedes=sid(1)), me)


def test_a_reorder_lists_live_sentences_only(project: Project, me: Actor, draft: str) -> None:
    forge(project, "draft.sentence_recorded", sentence(draft, 1, order=10), me)
    forge(project, "draft.sentence_recorded", sentence(draft, 2, order=20), me)
    forge(project, "draft.sentence_recorded", sentence(draft, 3, order=30, supersedes=sid(1)), me)
    forge(
        project, "draft.sentence_withdrawn", SentenceWithdrawn(sentence_id=sid(2), reason="x"), me
    )
    forge(project, "draft.sentence_recorded", sentence(draft, 4, order=40), me)
    for gone in (sid(1), sid(2)):  # a superseded and a withdrawn sentence
        model = DraftReordered(draft_id=draft, section_id="sec_01", order=[sid(4), sid(3), gone])
        inert(project, "draft.reordered", model, me)
    live = DraftReordered(draft_id=draft, section_id="sec_01", order=[sid(4), sid(3)])
    folds(project, "draft.reordered", live, me)


def raw(project: Project, type_: str, model: StrictModel, actor: Actor, **fields: Any) -> None:
    """Append a line the writer would refuse: a payload that no longer validates, as a hand-edited
    log may hold."""
    event = project.events.make(type_, model, actor)
    edited = event.model_copy(update={"payload": {**event.payload, **fields}})
    path = project.paths.events_dir / actor.id / f"{actor.session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(edited.to_line())


@pytest.mark.parametrize("order", [2**70, -5])
def test_an_order_out_of_range_changes_nothing_even_when_it_supersedes(
    project: Project, me: Actor, draft: str, order: int
) -> None:
    forge(project, "draft.sentence_recorded", sentence(draft, 1), me)
    before = state(project)
    raw(project, "draft.sentence_recorded", sentence(draft, 2, supersedes=sid(1)), me, order=order)
    assert state(project) == before  # the old sentence is not left superseded by nothing
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    assert [r.sentence_id for r in live_sentences(project, draft)] == [sid(1)]


def test_a_stat_value_out_of_range_changes_nothing(project: Project, me: Actor, draft: str) -> None:
    model = sentence(
        draft,
        1,
        cls=SentenceClass.SYNTHESIS,
        supports=[parse_support("stat:ideas-confirmed")],
        stat_values={"ideas-confirmed": 1},
    )
    before = state(project)
    raw(project, "draft.sentence_recorded", model, me, stat_values={"ideas-confirmed": 2**70})
    assert state(project) == before
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced


def test_order_and_stat_values_are_bounded_in_the_model(draft: str) -> None:
    assert sentence(draft, order=MAX_ORDER).order == MAX_ORDER
    for bad in (MAX_ORDER + 1, -1):
        with pytest.raises(ValueError):
            sentence(draft, order=bad)
    with pytest.raises(ValueError):
        sentence(
            draft,
            cls=SentenceClass.SYNTHESIS,
            supports=[parse_support("stat:ideas-confirmed")],
            stat_values={"ideas-confirmed": MAX_ORDER + 1},
        )


def test_a_handler_that_fails_half_way_leaves_no_partial_fold() -> None:
    engine = create_engine("sqlite://")
    rows = Table("rows", MetaData(), Column("n", Integer))
    rows.create(engine)

    def half(conn: Connection, _event: Event) -> None:
        conn.execute(rows.insert().values(n=1))
        raise OverflowError("after the first write")

    with engine.begin() as conn:
        conn.execute(rows.insert().values(n=0))  # the transaction `_write` holds open
        _total(half)(conn, cast(Event, None))
    with engine.connect() as conn:
        assert [r[0] for r in conn.execute(rows.select())] == [0]
