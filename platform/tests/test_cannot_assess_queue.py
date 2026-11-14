"""Unresolved full-text cannot-assess works as a human queue (IDEA-67).

Read-only views computed from events: `agreement.cannot_assess_queue` (each pass's verdict,
criterion, quote and anchor, the command that reads the document and the command that resolves
the work), a count per stage in `factory status`, the dashboard's screening section (which the
hub's dashboard snapshot shows), and `factory screen disagreements --stage full-text`, which lists
the queue before both passes finish. Nothing here blocks extraction (the IDEA-49 ruling is open).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel
from factory.services.agreement import (
    Outcome,
    cannot_assess_counts,
    cannot_assess_queue,
    final_outcomes,
    resolve_disagreement,
)
from factory.services.context import Project
from factory.services.dashboard import dashboard_state
from factory.services.project import project_status
from factory.sources.registry import SourceFactory
from tests.cli_helpers import _env
from tests.fulltext_helpers import _decide_at
from tests.test_fulltext_resolve_cannot_assess import _decide_all, _open_passes, _Passes

FT = ScreeningStage.FULL_TEXT
TA = ScreeningStage.TITLE_ABSTRACT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
runner = CliRunner()


@pytest.fixture
def passes(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> _Passes:
    return _open_passes(project, agent, human, mock_sources)


def _pass_a_only(project: Project, agent: Actor, passes: _Passes, unassessed: str) -> None:
    """Pass A decides every work (`unassessed` as cannot-assess under EX01); pass B decides
    nothing, so the passes have not finished."""
    for work in passes.dual + passes.single:
        verdict, criterion = ("cannot-assess", "EX01") if work == unassessed else ("include", None)
        _decide_at(project, agent, FT, work, "A", verdict, criterion, passes.protocol_id)


def test_queue_lists_a_single_pass_work_before_pass_b_finishes(
    project: Project, agent: Actor, passes: _Passes
) -> None:
    work = passes.single[0]
    _pass_a_only(project, agent, passes, work)
    (item,) = cannot_assess_queue(project, stage=FT)
    assert item.work_id == work
    assert list(item.passes) == ["A"]
    view = item.passes["A"]
    assert view.verdict.value == "cannot-assess"
    assert view.criterion == "EX01"
    assert view.anchor is not None and view.quote
    assert view.conversion_id is not None
    assert item.read_command == f"factory document read {work} --conversion {view.conversion_id}"
    assert item.resolve_command.startswith(f"factory screen resolve {work} ")
    assert "--stage full-text" in item.resolve_command
    assert cannot_assess_counts(project) == {"title-abstract": 0, "full-text": 1}


def test_queue_shows_both_passes_of_a_dual_coded_work(
    project: Project, agent: Actor, passes: _Passes
) -> None:
    work = passes.dual[0]
    _decide_all(project, agent, passes, work, pass_b="include")
    (item,) = cannot_assess_queue(project, stage=FT)
    assert item.work_id == work
    assert [(k, v.verdict.value) for k, v in item.passes.items()] == [
        ("A", "cannot-assess"),
        ("B", "include"),
    ]


def test_a_resolved_work_leaves_the_queue_and_nothing_blocks(
    project: Project, agent: Actor, human: Actor, passes: _Passes
) -> None:
    work = passes.single[0]
    _decide_all(project, agent, passes, work)
    # unresolved: awaiting classification, pending (IDEA-49, decision 121)
    assert final_outcomes(project, stage=FT)[work] is Outcome.PENDING
    resolve_disagreement(project, human, work, "exclude", "EX01", "slides", Channel.CLI, stage=FT)
    assert cannot_assess_queue(project, stage=FT) == []
    assert cannot_assess_counts(project)["full-text"] == 0


def test_title_abstract_queue_is_empty(project: Project, agent: Actor, passes: _Passes) -> None:
    _pass_a_only(project, agent, passes, passes.single[0])
    assert cannot_assess_queue(project, stage=TA) == []


def test_status_counts_the_queue_per_stage(project: Project, agent: Actor, passes: _Passes) -> None:
    _pass_a_only(project, agent, passes, passes.single[0])
    status = project_status(project)
    assert status.screening.cannot_assess_open == {"title-abstract": 0, "full-text": 1}


def test_dashboard_screening_section_lists_the_queue(
    project: Project, agent: Actor, passes: _Passes
) -> None:
    work = passes.single[0]
    _pass_a_only(project, agent, passes, work)
    screening = dashboard_state(project)["screening"]
    assert isinstance(screening, dict)
    queue = screening["cannot_assess"]
    assert isinstance(queue, list)
    (row,) = queue
    assert isinstance(row, dict)
    assert row["work_id"] == work
    assert row["resolve_command"].startswith("factory screen resolve")  # type: ignore[union-attr]
    json.dumps(screening)  # the state is JSON


def test_cli_disagreements_lists_the_queue_before_the_passes_finish(
    project: Project, agent: Actor, passes: _Passes, settings: Settings
) -> None:
    work = passes.single[0]
    _pass_a_only(project, agent, passes, work)
    result = runner.invoke(
        app, ["screen", "disagreements", "--stage", "full-text"], env=_env(settings.root)
    )
    assert result.exit_code == 0, result.output
    assert f"{work}  cannot-assess (promoted until resolved)" in result.output
    assert "A: cannot-assess EX01" in result.output
    assert f"read: factory document read {work}" in result.output
    assert f"resolve: factory screen resolve {work}" in result.output
    assert "disagreements: not available until both passes finish" in result.output


def test_cli_status_prints_the_count(
    project: Project, agent: Actor, passes: _Passes, settings: Settings
) -> None:
    _pass_a_only(project, agent, passes, passes.single[0])
    result = runner.invoke(app, ["status"], env=_env(settings.root))
    assert result.exit_code == 0, result.output
    assert "cannot-assess to resolve: title-abstract 0, full-text 1" in result.output
