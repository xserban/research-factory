"""Answers of the papers chat in Ask mode: events, folds, guards, ratings (plan N2)."""

# ruff: noqa: F811
from dataclasses import replace

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.answers import AnswerRated, AnswerRecorded
from factory.services import answers as an
from factory.services.context import Project
from factory.services.selection import SelectionSpec, resolve_selection_cached
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"
SPEC = SelectionSpec()


def _sent(work: str, **kw: str) -> an.SentenceInput:
    base = {"text": "The paper says so.", "anchor": ANCHOR, "quote": QUOTE}
    return an.SentenceInput(work_id=work, **{**base, **kw})


def _digest(project: Project) -> str:
    return resolve_selection_cached(project, SPEC).digest


def _record(
    project: Project, agent: Actor, world: list[str], n: int = 2, **kw: str | None
) -> AnswerRecorded:
    works = sorted(world)
    return an.record_answer(
        project,
        agent,
        "Does reflection help?",
        SPEC,
        _digest(project),
        [_sent(works[i % len(works)]) for i in range(n)],
        **kw,
    )


def _count(project: Project, table: str) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def _events(project: Project) -> int:
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())


def _forge(
    project: Project, actor: Actor, etype: str, payload: AnswerRecorded | AnswerRated
) -> None:
    blob = project.blobs.put_json({"forged": True})
    with project.index.exclusive():
        project.record([project.events.make(etype, payload, actor, input_blob=blob)])


def test_record_and_view_with_paragraphs_and_provenance(
    project: Project, agent: Actor, world: list[str]
) -> None:
    rec = _record(project, agent, world, unanswered="Nothing on long-term effects.")
    assert rec.mode == "ask" and rec.selection_digest == _digest(project)
    assert all(s.conversion_id.startswith("cnv_") for s in rec.sentences)
    view = an.view_answer(project, rec.answer_id)
    assert view.info.sentences == 2 and view.unanswered == "Nothing on long-term effects."
    assert all(QUOTE in s.paragraph for s in view.sentences)
    assert view.counts.sentences == 2 and view.counts.works == len(
        {s.work_id for s in view.sentences}
    )
    assert view.counts.unrated == 2 and view.counts.ratings == {"sound": 0, "weak": 0, "wrong": 0}
    with project.index.connect() as conn:
        model, skill, blob = conn.execute(
            text("SELECT model, skill, input_blob FROM events WHERE type = 'chat.answer_recorded'")
        ).one()
    assert model == agent.model and skill == agent.skill and str(blob).startswith("sha256:")
    assert [a.answer_id for a in an.list_answers(project)] == [rec.answer_id]


def test_agent_only_and_bad_input_located_nothing_written(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works = sorted(world)
    before = _events(project)
    with pytest.raises(FactoryValidationError) as err:
        an.record_answer(project, human, "q", SPEC, _digest(project), [_sent(works[0])])
    assert err.value.issues[0].field == "actor"
    long_text = "x" * 601
    sentences = [
        _sent(works[0]),
        _sent(works[0], text=long_text),
        _sent("rf:nobody-1"),
        _sent(works[0], quote=" "),
    ]
    with pytest.raises(FactoryValidationError) as err2:
        an.record_answer(project, agent, " ", SPEC, _digest(project), sentences)
    fields = {i.field for i in err2.value.issues}
    assert {"question", "sentences[1].text", "sentences[2].work_id", "sentences[3].quote"} <= fields
    with pytest.raises(FactoryValidationError) as err3:
        an.record_answer(project, agent, "q", SPEC, _digest(project), [])
    assert err3.value.issues[0].field == "sentences"
    assert _events(project) == before and _count(project, "answers") == 0


def test_no_sentences_allowed_only_with_unanswered_note(
    project: Project, agent: Actor, world: list[str]
) -> None:
    rec = an.record_answer(
        project, agent, "q", SPEC, _digest(project), [], unanswered="The papers do not say."
    )
    assert an.view_answer(project, rec.answer_id).info.sentences == 0


def test_unverified_quote_refused_all_or_none(
    project: Project, agent: Actor, world: list[str]
) -> None:
    work = sorted(world)[0]
    before = _events(project)
    with pytest.raises(FactoryValidationError) as err:
        an.record_answer(
            project,
            agent,
            "q",
            SPEC,
            _digest(project),
            [_sent(work), _sent(work, quote="never said this"), _sent(work, anchor="s99.p9")],
        )
    assert [i.field for i in err.value.issues] == ["sentences[1].quote", "sentences[2].quote"]
    assert _events(project) == before and _count(project, "answers") == 0


def test_stale_selection_refused_nothing_written(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    work = sorted(world)[0]
    before = _events(project)
    with pytest.raises(FactoryValidationError) as err:
        an.record_answer(project, agent, "q", SPEC, "0" * 64, [_sent(work)])
    assert err.value.issues[0].field == "selection_digest"
    assert "selection changed" in err.value.issues[0].reason
    good = _digest(project)
    real = resolve_selection_cached
    monkeypatch.setattr(
        an, "resolve_selection_cached", lambda p, s: replace(real(p, s), digest="x")
    )
    with pytest.raises(FactoryValidationError) as err2:
        an.record_answer(project, agent, "q", SPEC, good, [_sent(work)])
    assert "selection changed" in err2.value.issues[0].reason
    assert _events(project) == before and _count(project, "answers") == 0


def test_work_outside_the_selection_refused(
    project: Project, agent: Actor, world: list[str]
) -> None:
    works = sorted(world)
    spec = SelectionSpec(exclude=[works[0]])
    digest = resolve_selection_cached(project, spec).digest
    with pytest.raises(FactoryValidationError) as err:
        an.record_answer(project, agent, "q", spec, digest, [_sent(works[0])])
    assert err.value.issues[0].field == "sentences[0].work_id"
    assert "not in the selection" in err.value.issues[0].reason


def test_follow_up_parent_answer_or_sheet_must_exist(
    project: Project, agent: Actor, world: list[str]
) -> None:
    first = _record(project, agent, world, n=1)
    second = _record(project, agent, world, n=1, parent=first.answer_id)
    assert an.view_answer(project, second.answer_id).info.parent == first.answer_id
    with pytest.raises(FactoryValidationError) as err:
        _record(project, agent, world, n=1, parent="ans_NOPE")
    assert err.value.issues[0].field == "parent"
    from factory.services import sheets as sh
    from factory.services.chat_candidates import CandidateInput as C

    sheet = sh.open_sheet(
        project, agent, "h", SPEC, [C(sorted(world)[0], "claims", "against", ANCHOR, QUOTE)]
    )
    third = _record(project, agent, world, n=1, parent=sheet.sheet_id)
    assert an.view_answer(project, third.answer_id).info.parent == sheet.sheet_id


def test_rating_is_human_only_latest_stands(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    rec = _record(project, agent, world)
    with pytest.raises(FactoryValidationError) as err:
        an.rate_answer(project, agent, rec.answer_id, "sound")
    assert err.value.issues[0].field == "actor"
    for bad in (
        dict(answer_id=rec.answer_id, rating="great"),
        dict(answer_id="ans_NOPE", rating="sound"),
        dict(answer_id=rec.answer_id, rating="sound", sentence=5),
        dict(answer_id=rec.answer_id, rating="sound", note="n" * 601),
    ):
        with pytest.raises(FactoryValidationError):
            an.rate_answer(project, human, **bad)
    an.rate_answer(project, human, rec.answer_id, "weak", "thin", sentence=0)
    an.rate_answer(project, human, rec.answer_id, "sound", sentence=0)
    an.rate_answer(project, human, rec.answer_id, "wrong", "overall")
    view = an.view_answer(project, rec.answer_id)
    assert view.sentences[0].rating == "sound" and view.sentences[1].rating is None
    assert view.rating == "wrong" and view.rating_note == "overall"
    assert view.counts.ratings == {"sound": 1, "weak": 0, "wrong": 0} and view.counts.unrated == 1


def test_projection_ignores_hand_written_events(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """An agent-written rating, a sentence for a work outside the selection, a bad digest and an
    unknown parent stay in the log and fold nothing."""
    rec = _record(project, agent, world)
    _forge(
        project,
        agent,
        "chat.answer_rated",
        AnswerRated(answer_id=rec.answer_id, rating="wrong"),
    )
    assert _count(project, "answer_ratings") == 0
    outside = rec.sentences[0].model_copy(update={"work_id": "w_nowhere"})
    forged = rec.model_copy(update={"answer_id": "ans_" + "0" * 26, "sentences": (outside,)})
    _forge(project, agent, "chat.answer_recorded", forged)
    assert _count(project, "answers") == 1
    bad_digest = rec.model_copy(
        update={"answer_id": "ans_" + "1" * 26, "selection_digest": "0" * 64}
    )
    _forge(project, agent, "chat.answer_recorded", bad_digest)
    orphan = rec.model_copy(update={"answer_id": "ans_" + "2" * 26, "parent": "ans_" + "9" * 26})
    _forge(project, agent, "chat.answer_recorded", orphan)
    by_human = rec.model_copy(update={"answer_id": "ans_" + "3" * 26})
    _forge(project, human, "chat.answer_recorded", by_human)
    assert _count(project, "answers") == 1 and _count(project, "answer_sentences") == 2
    _forge(
        project,
        human,
        "chat.answer_rated",
        AnswerRated(answer_id=rec.answer_id, sentence=7, rating="weak"),
    )
    assert _count(project, "answer_ratings") == 0
    _forge(
        project,
        human,
        "chat.answer_rated",
        AnswerRated(answer_id=rec.answer_id, sentence=1, rating="weak"),
    )
    assert _count(project, "answer_ratings") == 1


def test_rebuild_keeps_answers_and_ratings(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    rec = _record(project, agent, world)
    an.rate_answer(project, human, rec.answer_id, "sound", sentence=1)
    an.rate_answer(project, human, rec.answer_id, "weak")
    before = an.view_answer(project, rec.answer_id)
    project.index.rebuild()
    assert an.view_answer(project, rec.answer_id) == before
    assert [a.answer_id for a in an.list_answers(project)] == [rec.answer_id]
