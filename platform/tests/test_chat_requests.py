"""Chat requests: the researcher's request for a spar or an ask, taken by a headless run and
answered by a sheet or answer (plan spar-night N3). No real `claude` is started."""

# ruff: noqa: F811
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.chat_requests import ChatRequested, ChatRequestTaken
from factory.model.sheets import SheetOpened
from factory.services import answers as an
from factory.services import chat_requests as cr
from factory.services import runner
from factory.services import sheets as sh
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project
from factory.services.selection import SelectionSpec, resolve_selection_cached
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import install_skill
from tests.test_runner import FakeLauncher

SPEC = SelectionSpec()
ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"


@pytest.fixture(autouse=True)
def chat_env(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    install_skill(project.settings, "rf-chat", "CHAT SKILL BODY")
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")


def _events(project: Project, etype: str | None = None) -> int:
    project.index.sync()
    where = "" if etype is None else f" WHERE type = '{etype}'"
    with project.index.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM events{where}")).scalar_one())


def _rows(project: Project) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM chat_requests")).scalar_one())


def _spar(project: Project, human: Actor, **kw: object) -> str:
    return cr.request_chat(
        project, human, "spar", SPEC, hypothesis="Reflection helps", **kw
    ).request_id  # type: ignore[arg-type]


def _ask(project: Project, human: Actor, **kw: object) -> str:
    return cr.request_chat(project, human, "ask", SPEC, question="Does it help?", **kw).request_id  # type: ignore[arg-type]


def _run(project: Project, kind: str) -> tuple[str, FakeLauncher]:
    launcher = FakeLauncher()
    return runner.start_run(project, kind, launcher=launcher, unit_cap=1), launcher


def _release(launcher: FakeLauncher, run_id: str) -> None:
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)


def test_request_is_a_human_act_service_and_nothing_written_otherwise(
    project: Project, agent: Actor, human: Actor
) -> None:
    before = _events(project)
    for actor in (agent, project.system_actor()):
        with pytest.raises(FactoryValidationError) as err:
            cr.request_chat(project, actor, "ask", SPEC, question="q")
        assert err.value.issues[0].field == "actor"
    for kwargs, field in (
        ({"kind": "ask", "hypothesis": "h", "question": "q"}, "hypothesis"),
        ({"kind": "ask"}, "question"),
        ({"kind": "spar"}, "hypothesis"),
        ({"kind": "spar", "hypothesis": "h", "question": "q"}, "question"),
        ({"kind": "ask", "question": "q", "mode": "prepare"}, "mode"),
        ({"kind": "spar", "hypothesis": "h", "mode": "wild"}, "mode"),
        ({"kind": "talk", "question": "q"}, "kind"),
        ({"kind": "ask", "question": "q", "parent": "nope"}, "parent"),
        ({"kind": "ask", "question": "q", "parent": "sht_" + "0" * 26}, "parent"),
    ):
        with pytest.raises(FactoryValidationError) as err:
            cr.request_chat(project, human, spec=SPEC, **kwargs)  # type: ignore[arg-type]
        assert field in {i.field for i in err.value.issues}, kwargs
    assert _events(project) == before and _rows(project) == 0


def test_request_records_spec_mode_and_lists_open(project: Project, human: Actor) -> None:
    one = _spar(project, human, mode="prepare", note="for the lead")
    two = _ask(project, human)
    info = cr.view_request(project, one)
    assert info.kind == "spar" and info.mode == "prepare" and info.state == "open"
    assert info.hypothesis == "Reflection helps" and info.note == "for the lead"
    assert info.selection["layers"] == []
    assert cr.view_request(project, two).mode is None
    assert [r.request_id for r in cr.list_requests(project)] == [one, two]
    assert [r.request_id for r in cr.list_requests(project, kind="ask")] == [two]
    assert cr.open_count(project, "spar") == 1 and cr.open_count(project, "ask") == 1


def test_projection_ignores_hand_written_requests_by_an_agent(
    project: Project, agent: Actor, human: Actor
) -> None:
    payload = ChatRequested(
        request_id="chr_" + "0" * 26,
        kind="ask",
        selection=SPEC.model_dump(mode="json"),
        question="forged",
    )
    blob = project.blobs.put_json({"forged": True})
    with project.index.exclusive():
        project.record([project.events.make("chat.requested", payload, agent, input_blob=blob)])
        project.record([project.events.make("chat.requested", payload, project.system_actor())])
    assert _rows(project) == 0
    with project.index.exclusive():
        project.record([project.events.make("chat.requested", payload, human)])
    assert _rows(project) == 1


def test_next_serves_oldest_of_the_runs_kind_and_marks_it_taken(
    project: Project, agent: Actor, human: Actor
) -> None:
    first = _ask(project, human)
    spar = _spar(project, human)
    second = _ask(project, human)
    run_id, launcher = _run(project, "ask")
    served = cr.take_next(project, agent, run_id)
    assert served is not None and served.request_id == first and served.state == "taken"
    assert cr.view_request(project, first).taken_run == run_id
    assert cr.view_request(project, spar).state == "open"
    assert cr.open_count(project, "ask") == 1  # `second` waits; `first` is taken
    again = cr.take_next(project, agent, run_id)
    assert again is not None and again.request_id == second  # the cap, not this module, stops a run
    _release(launcher, run_id)


def test_next_refuses_a_session_that_is_not_an_open_chat_run(
    project: Project, agent: Actor, human: Actor
) -> None:
    _ask(project, human)
    for run_id in ("rnr_" + "0" * 26, "not-a-run"):
        with pytest.raises(FactoryValidationError) as err:
            cr.take_next(project, agent, run_id)
        assert err.value.issues[0].field == "run"
    with pytest.raises(FactoryValidationError) as err:
        cr.take_next(project, human, "rnr_" + "0" * 26)
    assert err.value.issues[0].field == "actor"
    assert cr.open_count(project, "ask") == 1
    run_id, launcher = _run(project, "ask")
    _release(launcher, run_id)
    with pytest.raises(FactoryValidationError) as err:  # the run has ended
        cr.take_next(project, agent, run_id)
    assert err.value.issues[0].field == "run"


def test_next_with_nothing_open_serves_nothing(
    project: Project, agent: Actor, human: Actor
) -> None:
    _spar(project, human)
    _ask(project, human)
    run_id, launcher = _run(project, "ask")
    assert cr.take_next(project, agent, run_id) is not None
    assert cr.take_next(project, agent, run_id) is None
    _release(launcher, run_id)


def test_lifecycle_open_taken_done(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    request = _ask(project, human)
    assert cr.view_request(project, request).state == "open"
    run_id, launcher = _run(project, "ask")
    cr.take_next(project, agent, run_id)
    assert cr.view_request(project, request).state == "taken"
    work = sorted(world)[0]
    digest = resolve_selection_cached(project, SPEC).digest
    answer = an.record_answer(
        project,
        agent,
        "Does it help?",
        SPEC,
        digest,
        [an.SentenceInput("It does.", work, ANCHOR, QUOTE)],
        request_id=request,
    )
    _release(launcher, run_id)
    view = cr.view_request(project, request)
    assert view.state == "done" and view.result == answer.answer_id
    assert an.list_answers(project)[0].answer_id == answer.answer_id
    project.index.rebuild()
    assert cr.view_request(project, request) == view


def test_lifecycle_taken_then_run_ends_without_result_is_failed(
    project: Project, agent: Actor, human: Actor
) -> None:
    request = _ask(project, human)
    run_id, launcher = _run(project, "ask")
    cr.take_next(project, agent, run_id)
    launcher.code = 1
    for process in launcher.processes:
        process.code = 1
    _release(launcher, run_id)
    assert cr.view_request(project, request).state == "failed"
    assert cr.open_count(project, "ask") == 0  # a failed request is not served again
    project.index.rebuild()
    assert cr.view_request(project, request).state == "failed"


def test_sheet_opened_with_request_id_marks_it_done(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    request = _spar(project, human)
    run_id, launcher = _run(project, "spar")
    cr.take_next(project, agent, run_id)
    work = sorted(world)[0]
    sheet = sh.open_sheet(
        project, agent, "Reflection helps", SPEC, [C(work, "claims", "against", ANCHOR, QUOTE)],
        request_id=request,
    )  # fmt: skip
    _release(launcher, run_id)
    view = cr.view_request(project, request)
    assert view.state == "done" and view.result == sheet.sheet_id


def test_for_case_follow_up_is_done_when_its_section_closes_with_the_request(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    work = sorted(world)[0]
    sheet = sh.open_sheet(
        project, agent, "Reflection helps", SPEC, [C(work, "claims", "against", ANCHOR, QUOTE)],
        mode="prepare",
    ).sheet_id  # fmt: skip
    sh.record_arguments(
        project, agent, sheet,
        [sh.ArgumentInput("against", work, ANCHOR, QUOTE, "it fails", "moderate")],
    )  # fmt: skip
    sh.close_section(project, agent, sheet, "against")
    follow = _spar(project, human, mode="prepare", parent=sheet)
    run_id, launcher = _run(project, "spar")
    cr.take_next(project, agent_other, run_id)
    sh.record_arguments(
        project, agent_other, sheet,
        [sh.ArgumentInput("for", work, ANCHOR, QUOTE, "it helps", "weak")],
    )  # fmt: skip
    assert cr.view_request(project, follow).state == "taken"
    sh.close_section(project, agent_other, sheet, "for", request_id=follow)
    _release(launcher, run_id)
    view = cr.view_request(project, follow)
    assert view.state == "done" and view.result == sheet and view.parent == sheet


def test_unknown_or_wrong_kind_request_id_refused_nothing_written(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ask = _ask(project, human)
    work = sorted(world)[0]
    before = _events(project)
    for bad in ("chr_" + "0" * 26, ask, "junk"):
        with pytest.raises(FactoryValidationError) as err:
            sh.open_sheet(
                project, agent, "h", SPEC, [C(work, "claims", "against", ANCHOR, QUOTE)],
                request_id=bad,
            )  # fmt: skip
        assert err.value.issues[0].field == "request_id"
    digest = resolve_selection_cached(project, SPEC).digest
    spar = _spar(project, human)
    with pytest.raises(FactoryValidationError) as err:
        an.record_answer(
            project, agent, "q", SPEC, digest, [an.SentenceInput("t", work, ANCHOR, QUOTE)],
            request_id=spar,
        )  # fmt: skip
    assert err.value.issues[0].field == "request_id"
    assert _events(project) == before + 1  # only the spar request itself


def test_a_request_is_done_once_the_first_result_links(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    request = _ask(project, human)
    work = sorted(world)[0]
    digest = resolve_selection_cached(project, SPEC).digest
    first = an.record_answer(
        project, agent, "q", SPEC, digest, [an.SentenceInput("t", work, ANCHOR, QUOTE)],
        request_id=request,
    )  # fmt: skip
    an.record_answer(
        project, agent, "q", SPEC, digest, [an.SentenceInput("t", work, ANCHOR, QUOTE)],
        request_id=request,
    )  # fmt: skip
    assert cr.view_request(project, request).result == first.answer_id


def test_old_events_without_request_id_stay_valid(project: Project, agent: Actor) -> None:
    old = {
        "sheet_id": "sht_" + "0" * 26, "hypothesis": "h", "mode": "explore", "selection": {},
        "selection_digest": "d", "candidates_digest": "0" * 64, "candidates": [], "tier1_cap": 15,
    }  # fmt: skip
    assert SheetOpened.model_validate(old).request_id is None
    assert ChatRequestTaken.model_fields["run_id"] is not None


def test_taken_events_by_a_human_or_for_a_taken_request_fold_nothing(
    project: Project, agent: Actor, human: Actor
) -> None:
    request = _ask(project, human)
    run_id, launcher = _run(project, "ask")
    blob = project.blobs.put_json({"forged": True})
    forged = ChatRequestTaken(request_id=request, run_id=run_id)
    with project.index.exclusive():
        project.record([project.events.make("chat.request_taken", forged, human)])
    assert cr.view_request(project, request).state == "open"
    cr.take_next(project, agent, run_id)
    other = ChatRequestTaken(request_id=request, run_id="rnr_" + "1" * 26)
    with project.index.exclusive():
        project.record([project.events.make("chat.request_taken", other, agent, input_blob=blob)])
    assert cr.view_request(project, request).taken_run == run_id
    _release(launcher, run_id)


def test_state_is_never_stored_in_a_file(project: Project, human: Actor, tmp_path: Path) -> None:
    _ask(project, human)
    assert not list(project.paths.dir.glob("**/chat_requests*"))
