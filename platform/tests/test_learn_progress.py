"""Tutorial progress: derived from stage facts, event counts and the human queue only."""

from __future__ import annotations

from dataclasses import replace

from factory.events.envelope import Actor
from factory.learn.stages import STAGES
from factory.services import learn_progress as lp
from factory.services.context import Project
from factory.services.human_queue import Gate, HumanItem
from factory.services.project_stage import StageFacts
from tests.helpers import SourcesFor, ready_protocol

EMPTY = StageFacts(
    has_question=False,
    has_protocol=False,
    protocol_ready=False,
    press_confirmed=False,
    press_required=True,
    complete_search_runs=0,
    ta_pending=0,
    ft_plan=False,
    ft_open=0,
    extraction_schema=False,
    extraction_open=0,
    snowball_plan=False,
    snowball_open=False,
)
NONE: dict[str, int] = {}


def by_id(rows: list[lp.StageProgress]) -> dict[str, lp.StageProgress]:
    return {r.stage_id: r for r in rows}


def test_a_new_project_has_every_stage_not_started_and_the_first_step_next() -> None:
    rows = lp.derive(EMPTY, NONE, [])
    assert [r.stage_id for r in rows] == [s.id for s in STAGES]
    assert {r.state for r in rows} == {lp.StageState.NOT_STARTED}
    assert rows[0].next_step == STAGES[0].steps[0].text


def test_frame_is_done_when_the_protocol_is_ready_and_press_confirmed() -> None:
    ready = replace(EMPTY, has_question=True, has_protocol=True, protocol_ready=True)
    assert by_id(lp.derive(ready, NONE, []))["frame"].state is lp.StageState.IN_PROGRESS
    done = replace(ready, press_confirmed=True)
    rows = by_id(lp.derive(done, NONE, []))
    assert rows["frame"].state is lp.StageState.DONE
    assert rows["frame"].next_step.startswith("Next stage: Search and gather")
    assert (
        by_id(lp.derive(replace(ready, press_required=False), NONE, []))["frame"].state
        is lp.StageState.DONE
    )


def test_screen_follows_pending_works_and_decisions() -> None:
    f = replace(EMPTY, complete_search_runs=1, ta_pending=4)
    assert by_id(lp.derive(f, NONE, []))["screen"].state is lp.StageState.NOT_STARTED
    n = {"screen": 3}
    assert by_id(lp.derive(f, n, []))["screen"].state is lp.StageState.IN_PROGRESS
    assert by_id(lp.derive(replace(f, ta_pending=0), n, []))["screen"].state is lp.StageState.DONE


def test_a_waiting_human_gate_blocks_its_stage_and_names_the_command() -> None:
    item = HumanItem(
        gate=Gate.SCREENING_DISAGREEMENTS, stage="title-abstract", count=2, command="screen resolve"
    )
    rows = by_id(lp.derive(replace(EMPTY, complete_search_runs=1), {"screen": 5}, [item]))
    assert rows["screen"].state is lp.StageState.BLOCKED
    assert "screen resolve" in rows["screen"].next_step
    ft = HumanItem(gate=Gate.CALIBRATION_LABELS, stage="full-text", count=1, command="x")
    assert lp.gate_stage(ft) == "acquire"


def test_stages_without_a_computed_finish_are_never_done() -> None:
    n = {"understand": 9, "develop": 9, "maintain": 9}
    rows = by_id(lp.derive(EMPTY, n, []))
    for stage in n:
        assert rows[stage].state is lp.StageState.IN_PROGRESS
    released = by_id(lp.derive(EMPTY, {"write": 2, "released": 1}, []))
    assert released["write"].state is lp.StageState.DONE


def test_project_progress_reads_a_fresh_project_and_writes_nothing(project: Project) -> None:
    def events() -> object:
        with project.index.connect() as conn:
            return conn.exec_driver_sql("SELECT COUNT(*) FROM events").scalar()

    count = events()
    rows = lp.project_progress(project)
    assert {r.state for r in rows} == {lp.StageState.NOT_STARTED}
    assert events() == count


def test_project_progress_sees_a_ready_protocol(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    rows = by_id(lp.project_progress(project))
    assert rows["frame"].state is lp.StageState.DONE
    assert rows["gather"].state is lp.StageState.NOT_STARTED
