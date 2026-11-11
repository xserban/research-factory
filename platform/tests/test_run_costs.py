"""Run costs (plan restart-and-costs, C1): the log reader and the per-run figures."""

from __future__ import annotations

import json

import pytest

from factory.errors import FactoryValidationError
from factory.model.runner import RunnerFinished, RunnerOutcome, RunnerStarted
from factory.services import run_costs
from factory.services.context import Project

RUN_A = "rnr_01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_B = "rnr_01BRZ3NDEKTSV4RRFFQ69G5FAV"


def _assistant(msg_id: str, inp: int, out: int, read: int, write: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": msg_id,
                "usage": {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_input_tokens": read,
                    "cache_creation_input_tokens": write,
                },
                "content": [{"type": "text", "text": "ok"}],
            },
        }
    )


def _result(cost: float = 0.5) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "total_cost_usd": cost,
            "num_turns": 3,
            "duration_ms": 1000,
            "duration_api_ms": 800,
            "usage": {"input_tokens": 999},
        }
    )


def _synthetic_log() -> list[str]:
    return [
        json.dumps({"type": "system", "subtype": "init"}),
        _assistant("m1", 10, 5, 100, 20),
        _assistant("m2", 3, 7, 200, 0),
        _assistant("m3", 1, 2, 300, 50),
        _result(),
    ]


def test_parse_log_reads_turns_totals_and_result() -> None:
    log = run_costs.parse_log(_synthetic_log())
    assert log.complete is True
    assert log.reported_cost_usd == pytest.approx(0.5)
    assert log.num_turns == 3
    assert log.duration_ms == 1000
    assert log.duration_api_ms == 800
    assert [
        (t.input_tokens, t.output_tokens, t.cache_read_tokens, t.cache_write_tokens)
        for t in log.turns
    ] == [(10, 5, 100, 20), (3, 7, 200, 0), (1, 2, 300, 50)]
    assert log.input_tokens == 14
    assert log.output_tokens == 14
    assert log.cache_read_tokens == 600
    assert log.cache_write_tokens == 70
    assert log.malformed_lines == 0


def test_parse_log_counts_a_message_split_over_blocks_once() -> None:
    lines = [
        _assistant("m1", 10, 5, 0, 0),
        _assistant("m1", 10, 5, 0, 0),
        _assistant("m2", 1, 1, 0, 0),
    ]
    log = run_costs.parse_log(lines)
    assert len(log.turns) == 2
    assert log.input_tokens == 11


def test_parse_log_truncated_has_no_result_and_counts_the_broken_line() -> None:
    lines = [
        _assistant("m1", 10, 5, 0, 0),
        _assistant("m2", 3, 7, 0, 0),
        '{"type":"result","total_cost',
    ]
    log = run_costs.parse_log(lines)
    assert log.complete is False
    assert log.reported_cost_usd is None
    assert log.num_turns is None
    assert len(log.turns) == 2
    assert log.malformed_lines == 1


def test_parse_log_ignores_blank_and_non_object_lines() -> None:
    log = run_costs.parse_log(["", "   ", "[1, 2]", "null", _assistant("m1", 1, 1, 0, 0)])
    assert log.malformed_lines == 2
    assert len(log.turns) == 1


def test_parse_log_empty_is_zero_and_incomplete() -> None:
    log = run_costs.parse_log([])
    assert log.complete is False
    assert log.turns == []
    assert log.input_tokens == log.output_tokens == 0
    assert log.malformed_lines == 0


def _start(project: Project, run_id: str, stage: str, before: dict[str, int]) -> None:
    payload = RunnerStarted(
        run_id=run_id,
        stage=stage,
        model="claude-test",
        allowed_tools=("mcp__factory__screen_next",),
        prompt_blob=project.blobs.put(b"prompt"),
        unit_cap=25,
        counts_before=before,
        command=("claude", "-p"),
    )
    project.record([project.events.make("runner.started", payload, project.system_actor())])


def _finish(
    project: Project,
    run_id: str,
    after: dict[str, int],
    log_blob: str,
    outcome: RunnerOutcome = "complete",
) -> None:
    payload = RunnerFinished(
        run_id=run_id,
        exit_status=0 if outcome == "complete" else None,
        outcome=outcome,
        log_blob=log_blob,
        counts_after=after,
    )
    project.record([project.events.make("runner.finished", payload, project.system_actor())])


def _log_bytes(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_run_cost_units_and_per_unit_figures(project: Project) -> None:
    blob = project.blobs.put(_log_bytes(_synthetic_log()))
    _start(project, RUN_A, "screen", {"screen": 10})
    _finish(project, RUN_A, {"screen": 6}, blob)

    cost = run_costs.run_cost(project, RUN_A)
    assert cost.stage == "screen"
    assert cost.model == "claude-test"
    assert cost.miner is None
    assert cost.outcome == "complete"
    assert cost.exit_status == 0
    assert cost.units == 4
    assert cost.units_source == "counts-before-after"
    assert cost.cost_usd == pytest.approx(0.5)
    assert cost.cost_source == "reported-by-cli"
    assert cost.cost_per_unit_usd == pytest.approx(0.125)
    assert cost.input_tokens == 14
    assert cost.turns == 3
    assert cost.complete is True
    assert cost.log_source == "blob"
    total = 14 + 14 + 600 + 70
    assert cost.tokens_per_unit == pytest.approx(total / 4)


def test_run_cost_no_units_gives_no_per_unit_figures(project: Project) -> None:
    blob = project.blobs.put(_log_bytes(_synthetic_log()))
    _start(project, RUN_A, "extract", {"extract": 2})
    _finish(project, RUN_A, {"extract": 5}, blob)
    cost = run_costs.run_cost(project, RUN_A)
    assert cost.units == 0
    assert cost.cost_per_unit_usd is None
    assert cost.tokens_per_unit is None


def test_run_cost_miner_stage_and_open_run(project: Project) -> None:
    _start(project, RUN_B, "mine:m-alpha-1", {"mine:m-alpha-1": 3})
    cost = run_costs.run_cost(project, RUN_B)
    assert cost.stage == "mine:m-alpha-1"
    assert cost.miner == "m-alpha-1"
    assert cost.outcome is None
    assert cost.units == 0
    assert cost.units_source == "unavailable"
    assert cost.log_source == "none"


def test_run_cost_blob_absent_falls_back_to_the_run_file(project: Project) -> None:
    lines = _synthetic_log()
    ref = project.blobs.put(_log_bytes(lines))
    project.blobs.path(ref).unlink()
    _start(project, RUN_A, "screen", {"screen": 10})
    _finish(project, RUN_A, {"screen": 8}, ref)
    folder = project.paths.dir / "runs" / RUN_A
    folder.mkdir(parents=True)
    (folder / "log.jsonl").write_bytes(_log_bytes(lines))

    cost = run_costs.run_cost(project, RUN_A)
    assert cost.log_source == "file"
    assert cost.cost_usd == pytest.approx(0.5)
    assert cost.units == 2
    assert cost.cost_per_unit_usd == pytest.approx(0.25)


def test_run_cost_no_log_gives_zeros_and_incomplete(project: Project) -> None:
    _start(project, RUN_A, "screen", {"screen": 4})
    cost = run_costs.run_cost(project, RUN_A)
    assert cost.log_source == "none"
    assert cost.complete is False
    assert cost.cost_usd is None
    assert cost.cost_source is None
    assert cost.input_tokens == cost.output_tokens == 0
    assert cost.cache_read_tokens == cost.cache_write_tokens == 0
    assert cost.turns == 0


def test_run_cost_unknown_run_is_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as exc:
        run_costs.run_cost(project, RUN_A)
    assert exc.value.issues[0].field == "run_id"


def test_all_run_costs_in_recorded_order(project: Project) -> None:
    blob = project.blobs.put(_log_bytes(_synthetic_log()))
    _start(project, RUN_A, "screen", {"screen": 3})
    _finish(project, RUN_A, {"screen": 1}, blob)
    _start(project, RUN_B, "extract", {"extract": 2})
    costs = run_costs.all_run_costs(project)
    assert [c.run_id for c in costs] == [RUN_A, RUN_B]
    assert costs[0].units == 2
    assert costs[1].complete is False


def test_all_run_costs_empty_project(project: Project) -> None:
    assert run_costs.all_run_costs(project) == []


def test_reading_writes_nothing(project: Project) -> None:
    blob = project.blobs.put(_log_bytes(_synthetic_log()))
    _start(project, RUN_A, "screen", {"screen": 3})
    _finish(project, RUN_A, {"screen": 1}, blob)
    before = sorted(p.name for p in project.paths.events_dir.rglob("*") if p.is_file())
    run_costs.all_run_costs(project)
    run_costs.run_cost(project, RUN_A)
    after = sorted(p.name for p in project.paths.events_dir.rglob("*") if p.is_file())
    assert before == after


def test_run_cost_prefers_the_mcp_counter_file(project: Project) -> None:
    blob = project.blobs.put(_log_bytes(_synthetic_log()))
    _start(project, RUN_A, "screen", {"screen": 10})
    _finish(project, RUN_A, {"screen": 6}, blob)
    folder = project.paths.dir / "runs" / RUN_A
    folder.mkdir(parents=True)
    record = {"run_id": RUN_A, "served": 3, "cap": 25, "updated_at": "2026-11-11T00:00:00+00:00"}
    (folder / "units.json").write_text(json.dumps(record), encoding="utf-8")

    cost = run_costs.run_cost(project, RUN_A)
    assert cost.units == 3
    assert cost.units_source == "mcp-counter"
    assert cost.cost_per_unit_usd == pytest.approx(0.5 / 3)


def test_run_cost_counter_file_is_used_for_an_open_run(project: Project) -> None:
    _start(project, RUN_B, "screen", {"screen": 10})
    folder = project.paths.dir / "runs" / RUN_B
    folder.mkdir(parents=True)
    (folder / "units.json").write_text(json.dumps({"served": 2}), encoding="utf-8")
    cost = run_costs.run_cost(project, RUN_B)
    assert cost.units == 2 and cost.units_source == "mcp-counter"


def test_run_cost_malformed_counter_file_falls_back_to_the_counts(project: Project) -> None:
    blob = project.blobs.put(_log_bytes(_synthetic_log()))
    _start(project, RUN_A, "screen", {"screen": 10})
    _finish(project, RUN_A, {"screen": 6}, blob)
    folder = project.paths.dir / "runs" / RUN_A
    folder.mkdir(parents=True)
    for bad in ("not json", "[1]", json.dumps({"served": True}), json.dumps({"served": -1})):
        (folder / "units.json").write_text(bad, encoding="utf-8")
        cost = run_costs.run_cost(project, RUN_A)
        assert cost.units == 4 and cost.units_source == "counts-before-after"
