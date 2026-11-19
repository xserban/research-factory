"""The agentic spar, engine v2: coordinator, role records and guards (plan spar-night N6).

No real `claude` is started: the launcher is faked and `subprocess.Popen` is made to fail.
"""

# ruff: noqa: F811
from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.chat_requests import ChatRequested
from factory.model.spar_v2 import SheetArgumentChecked, SparRoleStarted
from factory.services import chat_requests as cr
from factory.services import runner
from factory.services import sheets as sh
from factory.services import spar_v2 as sv
from factory.services.chat_candidates import CandidateInput as C
from factory.services.chat_read import chat_sections
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import install_skill
from tests.test_runner import FakeLauncher

SPEC = SelectionSpec()
ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"
ROLE_SKILL = "rf-spar-v2@1a2b3c4d"


def _agent(n: int) -> Actor:
    """A role session: every call of this helper with a new `n` is a new MCP session."""
    return Actor(
        kind="agent",
        id=f"role-{n}",
        user="obd",
        session=f"01AAAAAAAAAAAAAAAAAAAAA{n:03d}",
        model="claude-sonnet-5-5",
        skill=ROLE_SKILL,
    )


@pytest.fixture(autouse=True)
def v2_env(project: Project, monkeypatch: pytest.MonkeyPatch) -> FakeLauncher:
    install_skill(project.settings, "rf-spar-v2", "SPAR V2 SKILL BODY")
    install_skill(project.settings, "rf-chat", "CHAT SKILL BODY")
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")

    def no_process(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a real process was started")

    monkeypatch.setattr("factory.services.runner.subprocess.Popen", no_process)
    launcher = FakeLauncher()
    # the watcher starts the next role through `default_launcher`: fake it too
    monkeypatch.setattr(runner, "default_launcher", launcher)
    return launcher


def _count(project: Project, table: str) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def _events(project: Project, etype: str | None = None) -> int:
    project.index.sync()
    where = "" if etype is None else f" WHERE type = '{etype}'"
    with project.index.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM events{where}")).scalar_one())


def _request(project: Project, **kw: Any) -> str:
    params: dict[str, Any] = {"hypothesis": "Reflection helps", "engine": "v2", "mode": "prepare"}
    params.update(kw)
    return cr.request_chat(project, project.human_actor(), "spar", SPEC, **params).request_id


def _open_run(project: Project) -> str:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT run_id FROM runner_runs WHERE outcome IS NULL")).all()
    assert len(rows) == 1, rows
    return str(rows[0][0])


def _stage(project: Project, run_id: str) -> str:
    record = runner.run_record(project, run_id)
    assert record is not None
    return record.stage


def _end(launcher: FakeLauncher, run_id: str) -> None:
    """The open run's process exits; the watcher records it and starts the next role."""
    launcher.processes[-1].release()
    assert runner.wait(run_id, 10)


def _proposals(world: list[str]) -> list[C]:
    w = sorted(world)
    return [
        C(w[0], "claims", "against", ANCHOR, QUOTE),
        C(w[0], "keyword", "for", ANCHOR, QUOTE),
        C(w[1], "claims", "against", ANCHOR, QUOTE),
        C(w[1], "vector", "for", ANCHOR, QUOTE),
        C(w[2], "keyword", "against", ANCHOR, QUOTE),
    ]


def _search(project: Project, world: list[str], request: str, run_id: str, n: int = 1) -> str:
    return sh.open_sheet(
        project, _agent(n), "Reflection helps", SPEC, _proposals(world), mode="prepare",
        request_id=request, run_id=run_id,
    ).sheet_id  # fmt: skip


def _read(project: Project, run_id: str, work: str, n: int, stance: str = "against") -> None:
    section = chat_sections(project, work).sections[0].anchor
    sv.record_reading(
        project, _agent(n), run_id, work,
        [sv.ReadingInput(ANCHOR, QUOTE, stance, "it states the claim")], [section],
    )  # fmt: skip


def _arg(work: str, stance: str) -> sh.ArgumentInput:
    return sh.ArgumentInput(stance, work, ANCHOR, QUOTE, "it fails", "moderate")


def _play_to_critic(
    project: Project,
    launcher: FakeLauncher,
    world: list[str],
    request: str,
    started: str | None = None,
) -> tuple[str, str]:
    """Play search, both readers and both writers; returns the sheet id and the critic's run id."""
    w = sorted(world)
    run = started or sv.advance(project, request, launcher=launcher)
    assert run is not None
    sheet = _search(project, world, request, run)
    _end(launcher, run)
    for i, work in enumerate((w[0], w[1])):
        run = _open_run(project)
        _read(project, run, work, 10 + i)
        _end(launcher, run)
    run = _open_run(project)
    sh.record_arguments(project, _agent(20), sheet, [_arg(w[0], "against")], run_id=run)
    sh.close_section(project, _agent(20), sheet, "against", run_id=run)
    _end(launcher, run)
    run = _open_run(project)
    sh.record_arguments(project, _agent(21), sheet, [_arg(w[1], "for")], run_id=run)
    sh.close_section(project, _agent(21), sheet, "for", run_id=run)
    _end(launcher, run)
    return sheet, _open_run(project)


def _play_all(
    project: Project,
    launcher: FakeLauncher,
    world: list[str],
    request: str,
    started: str | None = None,
) -> tuple[str, list[str]]:
    sheet, critic = _play_to_critic(project, launcher, world, request, started)
    view = sh.view_sheet(project, sheet)
    sv.record_checks(
        project, _agent(30),
        critic,
        [sv.CheckInput(a.argument_id, "holds", "the paragraph says so") for a in view.arguments],
    )  # fmt: skip
    _end(launcher, critic)
    cover = _open_run(project)
    tier3 = [c for c in sorted(world) if c not in sorted(world)[:3]]
    sv.record_coverage(project, _agent(31), cover, tier3[:1], [(tier3[0], "title looks relevant")])
    _end(launcher, cover)
    stages = [
        str(r[0]) for r in _rows(project, "SELECT stage FROM runner_runs ORDER BY started_event_id")
    ]
    return sheet, stages


def _rows(project: Project, sql: str) -> list[Any]:
    project.index.sync()
    with project.index.connect() as conn:
        return list(conn.execute(text(sql)).all())


# ---------------------------------------------------------------------------- the request field


def test_engine_defaults_to_v1_and_old_events_are_valid(project: Project) -> None:
    old = {
        "request_id": "chr_" + "0" * 26,
        "kind": "spar",
        "selection": {},
        "hypothesis": "h",
        "mode": "explore",
    }
    parsed = ChatRequested.model_validate(old)  # an event written before N6 has no engine
    assert parsed.engine == "v1" and parsed.max_sessions is None
    v1 = cr.request_chat(project, project.human_actor(), "spar", SPEC, hypothesis="h")
    assert v1.engine == "v1"
    info = cr.view_request(project, v1.request_id)
    assert info.engine == "v1" and info.next_role is None and info.sessions is None
    v2 = _request(project)
    got = cr.view_request(project, v2)
    assert got.engine == "v2" and got.state == "open" and got.next_role == "search"
    assert got.sessions == 0


def test_v2_request_is_refused_for_an_ask_a_parent_or_a_bad_budget(project: Project) -> None:
    human = project.human_actor()
    before = _events(project)
    with pytest.raises(FactoryValidationError) as err:
        cr.request_chat(project, human, "ask", SPEC, question="q", engine="v2")
    assert err.value.issues[0].field == "engine"
    with pytest.raises(FactoryValidationError) as err2:
        cr.request_chat(project, human, "spar", SPEC, hypothesis="h", engine="v3")
    assert err2.value.issues[0].field == "engine"
    for bad in (4, 99):
        with pytest.raises(FactoryValidationError) as err3:
            cr.request_chat(
                project, human, "spar", SPEC, hypothesis="h", engine="v2", max_sessions=bad
            )
        assert err3.value.issues[0].field == "max_sessions"
    with pytest.raises(FactoryValidationError) as err4:
        cr.request_chat(project, human, "spar", SPEC, hypothesis="h", max_sessions=8)
    assert err4.value.issues[0].field == "max_sessions"
    assert _events(project) == before


def test_a_v2_request_is_not_a_unit_of_the_v1_stage(project: Project, v2_env: FakeLauncher) -> None:
    _request(project)
    assert runner.pending_units(project, "spar") == {"spar": 0}
    assert runner.pending_units(project, "spar2-search") == {"spar2-search": 1}
    assert runner.pending_units(project, "spar2-read") == {"spar2-read": 0}
    with pytest.raises(FactoryValidationError, match="no pending unit"):
        runner.start_run(project, "spar", launcher=v2_env)
    v1 = cr.request_chat(project, project.human_actor(), "spar", SPEC, hypothesis="old")
    run = runner.start_run(project, "spar", launcher=v2_env)
    served = cr.take_next(project, _agent(1), run)
    assert served is not None and served.request_id == v1.request_id  # never the v2 request
    _end(v2_env, run)


def test_a_role_stage_is_started_only_by_the_coordinator(
    project: Project, v2_env: FakeLauncher
) -> None:
    _request(project)
    with pytest.raises(FactoryValidationError, match="factory chat advance"):
        runner.start_run(project, "spar2-search", launcher=v2_env)
    assert v2_env.calls == []


# ------------------------------------------------------------------------------ the chain


def test_roles_run_in_order_one_at_a_time_and_state_is_derived(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None and _stage(project, run) == "spar2-search"
    got = cr.view_request(project, request)
    assert got.state == "taken" and got.taken_run == run and got.next_role == "search"
    with pytest.raises(FactoryValidationError, match="open"):  # one run at a time
        sv.advance(project, request, launcher=v2_env)
    sheet, stages = _play_all(project, v2_env, world, request, run)
    assert stages == [
        "spar2-search", "spar2-read", "spar2-read", "spar2-against", "spar2-for",
        "spar2-critic", "spar2-cover",
    ]  # fmt: skip
    final = cr.view_request(project, request)
    assert final.state == "done" and final.next_role is None and final.sessions == 7
    assert final.result == sheet and final.readers_cut == ()
    assert sv.advance(project, request) is None  # nothing left
    assert _count(project, "spar_roles") == 7 and _events(project, "spar.role_started") == 7
    # one run at a time: the runs never overlapped
    assert all(
        r[0] is not None for r in _rows(project, "SELECT outcome FROM runner_runs")
    )  # fmt: skip
    # state is derived: nothing about it is stored in a file
    assert not list(project.paths.dir.glob("**/spar*"))


def test_the_writers_are_different_sessions_and_the_lead_guard_still_needs_a_balance(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    sheet, _ = _play_all(project, v2_env, world, request)
    rows = _rows(
        project,
        f"SELECT stance, session FROM sheet_arguments WHERE sheet_id = '{sheet}' ORDER BY stance",
    )
    assert [r[0] for r in rows] == ["against", "for"] and rows[0][1] != rows[1][1]
    with project.index.connect() as conn:
        from factory.index.sheets import sheet_lead_problem

        problem = sheet_lead_problem(conn, sheet)
    assert problem is not None and "balance" in problem  # N4 guard: the researcher writes it


def test_the_for_writer_cannot_be_the_against_writer_session(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    w = sorted(world)
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None
    sheet = _search(project, world, request, run)
    _end(v2_env, run)
    for i, work in enumerate((w[0], w[1])):
        run = _open_run(project)
        _read(project, run, work, 10 + i)
        _end(v2_env, run)
    run = _open_run(project)
    same = _agent(20)
    sh.record_arguments(project, same, sheet, [_arg(w[0], "against")], run_id=run)
    sh.close_section(project, same, sheet, "against", run_id=run)
    _end(v2_env, run)
    run = _open_run(project)
    with pytest.raises(FactoryValidationError) as err:  # same MCP session as the against writer
        sh.record_arguments(project, same, sheet, [_arg(w[1], "for")], run_id=run)
    assert err.value.issues[0].field == "session"


# ------------------------------------------------------------------------- role boundaries


def test_a_role_writes_only_its_own_records(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    w = sorted(world)
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None
    # the searcher opens the sheet; it cannot argue, read, check or sweep
    sheet = _search(project, world, request, run)
    with pytest.raises(FactoryValidationError) as err:
        sh.record_arguments(project, _agent(1), sheet, [_arg(w[0], "against")], run_id=run)
    assert "run" in {i.field for i in err.value.issues}
    with pytest.raises(FactoryValidationError):
        sv.record_checks(project, _agent(1), run, [sv.CheckInput("arg_" + "0" * 26, "holds", "x")])
    with pytest.raises(FactoryValidationError):
        sv.record_coverage(project, _agent(1), run, [])
    _end(v2_env, run)
    reader = _open_run(project)
    # the reader: another paper, not argue, not close
    with pytest.raises(FactoryValidationError) as err2:
        sv.record_reading(
            project, _agent(2), reader, w[2],
            [], [chat_sections(project, w[2]).sections[0].anchor],
        )  # fmt: skip
    assert err2.value.issues[0].field == "work_id"
    for call in (
        lambda: sh.record_arguments(
            project, _agent(2), sheet, [_arg(w[0], "against")], run_id=reader
        ),
        lambda: sh.close_section(project, _agent(2), sheet, "against", run_id=reader),
    ):
        with pytest.raises(FactoryValidationError):
            call()
    _read(project, reader, w[0], 2)
    _end(v2_env, reader)
    reader = _open_run(project)
    _read(project, reader, w[1], 3)
    _end(v2_env, reader)
    writer = _open_run(project)  # the against writer: no `for`, no reading, no sheet, no human
    with pytest.raises(FactoryValidationError):
        sh.record_arguments(project, _agent(4), sheet, [_arg(w[0], "for")], run_id=writer)
    with pytest.raises(FactoryValidationError):
        _read(project, writer, w[0], 4)
    with pytest.raises(FactoryValidationError):
        sh.open_sheet(
            project, _agent(4), "h", SPEC, _proposals(world), mode="prepare", run_id=writer
        )
    with pytest.raises(FactoryValidationError):
        sv.serve_task(project, project.human_actor(), writer)
    assert _count(project, "sheet_arguments") == 0


def test_a_sheet_of_a_v2_request_is_written_only_by_its_role_sessions(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    before = _events(project)
    with pytest.raises(FactoryValidationError) as err:  # no run at all
        sh.open_sheet(
            project, _agent(1), "h", SPEC, _proposals(world), mode="prepare", request_id=request
        )
    assert "run" in {i.field for i in err.value.issues}
    assert _events(project) == before and _count(project, "sheets") == 0
    # an ordinary sheet of a v1 session is untouched by v2
    plain = sh.open_sheet(project, _agent(1), "h", SPEC, _proposals(world), mode="explore")
    sh.record_arguments(project, _agent(1), plain.sheet_id, [_arg(sorted(world)[0], "against")])


def test_serve_task_names_the_role_and_the_paper_and_serves_once_per_run(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None
    task = sv.serve_task(project, _agent(1), run)
    assert task.role == "search" and task.request_id == request and task.sheet_id is None
    assert task.hypothesis == "Reflection helps" and task.work_id is None
    prompt = (project.paths.dir / "runs" / run / "prompt.txt").read_text(encoding="utf-8")
    assert "SPAR V2 SKILL BODY" in prompt and "spar_role_next" in prompt and request in prompt
    _search(project, world, request, run)
    _end(v2_env, run)
    run = _open_run(project)
    reader = sv.serve_task(project, _agent(2), run)
    assert reader.role == "read" and reader.work_id == sorted(world)[0]
    assert reader.sheet_id is not None and reader.max_sessions == 15
    _end(v2_env, run)


# ----------------------------------------------------------------------------------- readings


def test_readings_quotes_are_verified_and_counts_are_computed(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    w = sorted(world)
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None
    _search(project, world, request, run)
    _end(v2_env, run)
    reader = _open_run(project)
    sections = chat_sections(project, w[0]).sections
    good = sv.ReadingInput(ANCHOR, QUOTE, "against", "it states the claim")
    before = _events(project)
    bad = [
        good,
        sv.ReadingInput(ANCHOR, "never said this", "for", "why"),
        sv.ReadingInput(ANCHOR, QUOTE, "maybe", "why"),
    ]
    with pytest.raises(FactoryValidationError) as err:
        sv.record_reading(project, _agent(2), reader, w[0], bad, [sections[0].anchor, "s99"])
    fields = {i.field for i in err.value.issues}
    assert {"items[1].quote", "items[2].stance", "sections_read"} <= fields
    assert _events(project) == before and _count(project, "spar_readings") == 0
    with pytest.raises(FactoryValidationError) as err2:  # none read
        sv.record_reading(project, _agent(2), reader, w[0], [good], [])
    assert err2.value.issues[0].field == "sections_read"
    recorded = sv.record_reading(
        project, _agent(2), reader, w[0], [good, sv.ReadingInput(ANCHOR, QUOTE, "neither", "n/a")],
        [sections[0].anchor, sections[0].anchor],
    )  # fmt: skip
    assert recorded.sections_total == len(sections) and len(recorded.sections_read) == 1
    assert recorded.conversion_id.startswith("cnv_")
    with pytest.raises(FactoryValidationError, match="already read"):
        sv.record_reading(project, _agent(2), reader, w[0], [], [sections[0].anchor])
    row = _rows(
        project,
        "SELECT items_against, items_for, items_neither, sections_read_count, sections_total, "
        "model FROM spar_readings",
    )[0]
    assert tuple(row) == (1, 0, 1, 1, len(sections), "claude-sonnet-5-5")
    blob = _rows(
        project, "SELECT input_blob, skill FROM events WHERE type = 'spar.reading_recorded'"
    )[0]
    assert str(blob[0]).startswith("sha256:") and blob[1] == ROLE_SKILL
    view = sv.readings_view(project, request)
    assert [(r.work_id, r.read) for r in view.readers] == [(w[0], True), (w[1], False)]
    assert view.readers[0].sections_total == len(sections) and len(view.items) == 2
    _end(v2_env, reader)


# --------------------------------------------------------------------------------- the critic


def test_checks_are_agent_only_and_never_fold_as_ratings(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    sheet, critic = _play_to_critic(project, v2_env, world, request)
    arguments = sh.view_sheet(project, sheet).arguments
    first = arguments[0].argument_id
    with pytest.raises(FactoryValidationError) as err:  # a human is no critic
        sv.record_checks(
            project, project.human_actor(), critic, [sv.CheckInput(first, "holds", "r")]
        )
    assert err.value.issues[0].field == "actor"
    for bad, field in (
        (sv.CheckInput(first, "fine", "r"), "checks[0].verdict"),
        (sv.CheckInput(first, "holds", " "), "checks[0].reason"),
        (sv.CheckInput("arg_" + "1" * 26, "holds", "r"), "checks[0].argument_id"),
    ):
        with pytest.raises(FactoryValidationError) as err2:
            sv.record_checks(project, _agent(30), critic, [bad])
        assert err2.value.issues[0].field == field
    assert _count(project, "argument_checks") == 0
    sv.record_checks(
        project, _agent(30), critic,
        [sv.CheckInput(first, "overreaches", "the paragraph says less")],
    )  # fmt: skip
    # a hand-written check by a human, or from a session that holds no critic run, folds nothing
    forged = SheetArgumentChecked(
        argument_id=first, sheet_id=sheet, request_id=request, run_id=critic,
        verdict="holds", reason="forged",
    )  # fmt: skip
    with project.index.exclusive():
        project.record(
            [project.events.make("sheet.argument_checked", forged, project.human_actor())]
        )
    assert _count(project, "argument_checks") == 1
    assert _count(project, "sheet_ratings") == 0  # a check is no rating
    view = sh.view_sheet(project, sheet)
    shown = {a.argument_id: a for a in view.arguments}
    assert shown[first].check_verdict == "overreaches" and shown[first].rating is None
    assert view.coverage.unrated == len(arguments) and view.coverage.ratings["sound"] == 0
    sh.rate_argument(project, project.human_actor(), first, "sound", "I read it")
    after = {a.argument_id: a for a in sh.view_sheet(project, sheet).arguments}
    assert after[first].rating == "sound" and after[first].check_verdict == "overreaches"
    # the critic is not done until every argument has a check
    assert cr.view_request(project, request).state == "taken"
    rest = [sv.CheckInput(a.argument_id, "holds", "ok") for a in arguments[1:]]
    sv.record_checks(project, _agent(30), critic, rest)
    _end(v2_env, critic)
    assert cr.view_request(project, request).next_role == "cover"


def test_no_role_stage_can_rate_write_a_balance_or_record_a_lead() -> None:
    for stage in runner.SPAR2_STAGES:
        tools = {t.removeprefix("mcp__factory__") for t in runner.STAGES[stage].tools}
        assert not tools & {"lead_record", "lead_decide", "contradiction_propose", "answer_record"}
        assert not any("rate" in t or "balance" in t for t in tools), stage
        assert "chat_request_next" not in tools, stage
        assert runner.STAGES[stage].skill == "rf-spar-v2" and runner.STAGES[stage].fixed_cap == 1


def test_each_role_has_only_its_own_recording_tool() -> None:
    def tools(stage: str) -> set[str]:
        return {t.removeprefix("mcp__factory__") for t in runner.STAGES[stage].tools}

    owners = {
        "sheet_open": {"spar2-search"},
        "spar_reading_record": {"spar2-read"},
        "sheet_argue": {"spar2-against", "spar2-for"},
        "sheet_close": {"spar2-against", "spar2-for"},
        "sheet_check": {"spar2-critic"},
        "spar_coverage_record": {"spar2-cover"},
    }
    for tool, allowed in owners.items():
        have = {s for s in runner.SPAR2_STAGES if tool in tools(s)}
        assert have == allowed, tool
    assert all("spar_role_next" in tools(s) for s in runner.SPAR2_STAGES)
    # the for writer does not read the sheet: it would see the case against it must not anchor on
    assert "sheet_view" not in tools("spar2-for") and "sheet_view" not in tools("spar2-against")
    assert runner.is_stage_key("spar2-critic") and not runner.is_stage_key("spar2-judge")


# -------------------------------------------------------------------------------- the sweep


def test_coverage_counts_are_computed_and_only_unproposed_papers_are_swept(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    sheet, critic = _play_to_critic(project, v2_env, world, request)
    view = sh.view_sheet(project, sheet)
    sv.record_checks(
        project, _agent(30), critic,
        [sv.CheckInput(a.argument_id, "holds", "ok") for a in view.arguments],
    )  # fmt: skip
    _end(v2_env, critic)
    cover = _open_run(project)
    w = sorted(world)
    task = sv.serve_task(project, _agent(31), cover)
    assert set(task.unproposed) == set(w[3:]) and task.role == "cover"
    with pytest.raises(FactoryValidationError) as err:  # w[0] was proposed
        sv.record_coverage(project, _agent(31), cover, [w[0]])
    assert err.value.issues[0].field == "examined[0]"
    with pytest.raises(FactoryValidationError) as err2:  # flagged but not examined
        sv.record_coverage(project, _agent(31), cover, [w[3]], [(w[3], "")])
    assert "flagged[0].reason" in {i.field for i in err2.value.issues}
    assert _count(project, "spar_coverage") == 0
    recorded = sv.record_coverage(
        project, _agent(31), cover, [w[3]], [(w[3], "the title concerns review")], "looked at one"
    )
    assert recorded.unproposed_total == len(w) - 3 and recorded.not_examined == len(w) - 4
    row = _rows(project, "SELECT unproposed_total, not_examined, flagged FROM spar_coverage")[0]
    assert (row[0], row[1]) == (len(w) - 3, len(w) - 4)
    assert json.loads(row[2])[0]["work_id"] == w[3]
    with pytest.raises(FactoryValidationError, match="already recorded"):
        sv.record_coverage(project, _agent(31), cover, [])
    _end(v2_env, cover)
    assert cr.view_request(project, request).state == "done"


# ------------------------------------------------------------------------ failure and retry


def test_a_failed_role_stops_the_chain_and_advance_retries_it(
    project: Project, world: list[str], v2_env: FakeLauncher
) -> None:
    request = _request(project)
    v2_env.code = 1
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None
    _end(v2_env, run)
    got = cr.view_request(project, request)
    assert got.state == "failed" and got.next_role == "search" and got.sessions == 1
    assert _rows(project, "SELECT COUNT(*) FROM runner_runs WHERE outcome IS NULL")[0][0] == 0
    with pytest.raises(FactoryValidationError, match="retries"):  # the hook does not retry
        sv.advance(project, request, retry=False, launcher=v2_env)
    assert sv.advance_open(project) is None
    v2_env.code = 0
    again = sv.advance(project, request, launcher=v2_env)
    assert again is not None and again != run
    task_a = sv.serve_task(project, _agent(2), again)
    assert task_a.role == "search"
    assert cr.view_request(project, request).state == "taken"
    assert cr.view_request(project, request).sessions == 2
    _search(project, world, request, again, n=2)
    _end(v2_env, again)
    assert cr.view_request(project, request).next_role == "read"
    # a run that ends without doing its role is failed too, even with exit status 0
    run = _open_run(project)
    _end(v2_env, run)
    got = cr.view_request(project, request)
    assert got.state == "failed" and got.next_role == "read"
    assert got.next_work == sorted(world)[0]


def test_the_session_budget_cuts_readers_and_refuses_to_start_past_it(
    project: Project, world: list[str], v2_env: FakeLauncher
) -> None:
    request = _request(project, max_sessions=6)  # five fixed roles, so one reader
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None
    _search(project, world, request, run)
    _end(v2_env, run)
    got = cr.view_request(project, request)
    assert got.max_sessions == 6 and got.readers_cut == (sorted(world)[1],)
    assert got.next_work == sorted(world)[0] and len(got.readers_cut) == 1
    # failures spend the budget: the reader run the watcher started and four retries all fail
    # (exit status 1), then the budget of six is spent
    v2_env.code = 1
    v2_env.processes[-1].code = 1
    _end(v2_env, _open_run(project))
    for _ in range(4):
        run = sv.advance(project, request, launcher=v2_env)
        assert run is not None
        _end(v2_env, run)
    assert cr.view_request(project, request).sessions == 6
    with pytest.raises(FactoryValidationError, match="budget of 6"):
        sv.advance(project, request, launcher=v2_env)
    minimal = _request(project, max_sessions=5)
    assert cr.view_request(project, minimal).max_sessions == 5


def test_default_budget_is_fifteen_sessions_and_five_roles_are_fixed() -> None:
    assert sv.DEFAULT_MAX_SESSIONS == 15 and sv.FIXED_ROLES == 5 and sv.MIN_MAX_SESSIONS == 5


# --------------------------------------------------------------------------- forged and rebuilt


def test_hand_written_role_events_change_nothing(
    project: Project, v2_env: FakeLauncher, world: list[str]
) -> None:
    request = _request(project)
    fake_run = "rnr_" + "9" * 26
    forged = SparRoleStarted(request_id=request, run_id=fake_run, role="search")
    with project.index.exclusive():
        project.record([project.events.make("spar.role_started", forged, project.human_actor())])
        blob = project.blobs.put_json({"forged": True})
        project.record(
            [project.events.make("spar.role_started", forged, _agent(1), input_blob=blob)]
        )
    assert _count(project, "spar_roles") == 0
    # the system actor, but out of order (the next role is search, not read): changes nothing
    late = SparRoleStarted(request_id=request, run_id=fake_run, role="read", work_id="rf:x")
    with project.index.exclusive():
        project.record([project.events.make("spar.role_started", late, project.system_actor())])
    assert _count(project, "spar_roles") == 0
    assert cr.view_request(project, request).state == "open"


def test_rebuild_equals_live(project: Project, v2_env: FakeLauncher, world: list[str]) -> None:
    request = _request(project)
    _play_all(project, v2_env, world, request)
    tables = (
        "chat_requests", "spar_roles", "spar_readings", "argument_checks", "spar_coverage",
        "sheets", "sheet_arguments", "runner_runs",
    )  # fmt: skip

    def dump() -> dict[str, list[tuple[Any, ...]]]:
        return {t: sorted(tuple(r) for r in _rows(project, f"SELECT * FROM {t}")) for t in tables}

    live = dump()
    state = cr.view_request(project, request)
    project.index.rebuild()
    assert dump() == live
    assert cr.view_request(project, request) == state and state.state == "done"
    assert _count(project, "sheet_ratings") == 0


def test_no_real_claude_was_launched(project: Project, v2_env: FakeLauncher) -> None:
    request = _request(project)
    sv.advance(project, request, launcher=v2_env)
    assert len(v2_env.calls) == 1 and v2_env.calls[0][0][0] == "sh"  # wrapped, and faked
    argv = v2_env.calls[0][0]
    assert "/usr/bin/claude" in argv and "--allowedTools" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    allowed = argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]
    assert allowed == list(runner.STAGES["spar2-search"].tools)
    _end(v2_env, _open_run(project))
