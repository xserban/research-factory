"""A human settles a full-text `cannot-assess` work with `screen resolve` (IDEA-49, part 2).

Unresolved, a `cannot-assess` work still promotes (as before); a resolution with a reason decides
its outcome, and an exclusion needs an EX criterion. At title/abstract nothing changes.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel
from factory.services.agreement import (
    Outcome,
    cannot_assess_open,
    exclusion_criteria,
    final_outcomes,
    resolve_disagreement,
)
from factory.services.calibration import calibration_items, draw_calibration
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.screening import open_pass, pass_b_sample
from factory.sources.registry import SourceFactory
from tests.cli_helpers import _env
from tests.document_helpers import promoted_works
from tests.fulltext_helpers import _convert, _decide_at, _world
from tests.helpers import _of_type

FT = ScreeningStage.FULL_TEXT
TA = ScreeningStage.TITLE_ABSTRACT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
RESOLVED = "screening.disagreement_resolved"
runner = CliRunner()


@dataclass
class _Passes:
    protocol_id: str
    dual: list[str]
    single: list[str]


@pytest.fixture
def passes(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> _Passes:
    """Full-text passes open on a partly dual-coded plan; no full-text decision yet."""
    _world(project, agent, human, mock_sources, dual_sample=0.2)
    promoted = promoted_works(project)
    _convert(project, promoted)
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    open_pass(project, agent, PassLabel.A, stage=FT)
    open_pass(project, agent, PassLabel.B, stage=FT)
    protocol = current_protocol(project)
    assert protocol is not None
    calibration = set(calibration_items(project, stage=FT))
    sample = set(pass_b_sample(project, stage=FT) or ())
    ordinary = [w for w in promoted if w not in calibration]
    dual = [w for w in ordinary if w in sample]
    single = [w for w in ordinary if w not in sample]
    assert dual and single, "the world needs dual-coded and single-pass works"
    return _Passes(protocol.protocol_id, dual, single)


def _decide_all(
    project: Project, agent: Actor, passes: _Passes, unassessed: str, *, pass_b: str = "include"
) -> None:
    """Pass A includes every work but `unassessed`, which it cannot assess under EX01; pass B
    gives `unassessed` the verdict `pass_b` and includes every other dual-coded work."""
    pid = passes.protocol_id
    for work in passes.dual + passes.single:
        if work == unassessed:
            _decide_at(project, agent, FT, work, "A", "cannot-assess", "EX01", pid)
        else:
            _decide_at(project, agent, FT, work, "A", "include", None, pid)
    for work in passes.dual:
        if work == unassessed:
            criterion = "EX01" if pass_b in ("exclude", "cannot-assess") else None
            _decide_at(project, agent, FT, work, "B", pass_b, criterion, pid)
        else:
            _decide_at(project, agent, FT, work, "B", "include", None, pid)


def _fields(exc: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in exc.value.issues]


def test_single_pass_cannot_assess_resolved_to_exclude(
    project: Project, agent: Actor, human: Actor, passes: _Passes
) -> None:
    work = passes.single[0]
    _decide_all(project, agent, passes, work)
    assert final_outcomes(project, stage=FT)[work] is Outcome.INCLUDED  # unresolved: promotes
    assert cannot_assess_open(project, stage=FT) == [work]
    assert cannot_assess_open(project, stage=TA) == []

    before = len(_of_type(project, RESOLVED))
    with pytest.raises(FactoryValidationError) as no_criterion:
        resolve_disagreement(project, human, work, "exclude", None, "slides", Channel.CLI, stage=FT)
    assert _fields(no_criterion) == ["criterion"]
    with pytest.raises(FactoryValidationError) as no_reason:
        resolve_disagreement(project, human, work, "exclude", "EX01", " ", Channel.CLI, stage=FT)
    assert _fields(no_reason) == ["reason"]
    with pytest.raises(FactoryValidationError) as by_agent:
        resolve_disagreement(
            project, agent, work, "exclude", "EX01", "agent", Channel.CLI, stage=FT
        )
    assert "actor" in _fields(by_agent)
    assert len(_of_type(project, RESOLVED)) == before

    resolve_disagreement(
        project, human, work, "exclude", "EX01", "a slide deck, not a paper", Channel.CLI, stage=FT
    )
    assert final_outcomes(project, stage=FT)[work] is Outcome.EXCLUDED
    assert exclusion_criteria(project, stage=FT)[work] == "EX01"
    assert cannot_assess_open(project, stage=FT) == []
    with pytest.raises(FactoryValidationError) as again:
        resolve_disagreement(
            project, human, work, "include", None, "changed mind", Channel.CLI, stage=FT
        )
    assert _fields(again) == ["work_id"]


def test_dual_pass_cannot_assess_resolved_to_include(
    project: Project, agent: Actor, human: Actor, passes: _Passes
) -> None:
    work = passes.dual[0]
    _decide_all(project, agent, passes, work)
    assert final_outcomes(project, stage=FT)[work] is Outcome.INCLUDED
    assert cannot_assess_open(project, stage=FT) == [work]
    resolve_disagreement(
        project, human, work, "include", None, "the methods fit", Channel.CLI, stage=FT
    )
    assert final_outcomes(project, stage=FT)[work] is Outcome.INCLUDED
    assert cannot_assess_open(project, stage=FT) == []
    (event,) = _of_type(project, RESOLVED)
    assert event.payload["work_id"] == work and event.payload["reason"] == "the methods fit"


def test_dual_pass_cannot_assess_against_exclude_stays_a_disagreement(
    project: Project, agent: Actor, human: Actor, passes: _Passes
) -> None:
    work = passes.dual[0]
    _decide_all(project, agent, passes, work, pass_b="exclude")
    assert final_outcomes(project, stage=FT)[work] is Outcome.PENDING
    assert cannot_assess_open(project, stage=FT) == []  # open as a disagreement instead
    resolve_disagreement(
        project, human, work, "exclude", "EX01", "out of scope", Channel.CLI, stage=FT
    )
    assert final_outcomes(project, stage=FT)[work] is Outcome.EXCLUDED


def test_an_included_work_is_not_resolvable(
    project: Project, agent: Actor, human: Actor, passes: _Passes
) -> None:
    _decide_all(project, agent, passes, passes.single[0])
    with pytest.raises(FactoryValidationError) as caught:
        resolve_disagreement(
            project, human, passes.single[1], "exclude", "EX01", "no", Channel.CLI, stage=FT
        )
    assert _fields(caught) == ["work_id"]


def test_cli_resolves_a_cannot_assess_work(
    settings: Settings, project: Project, agent: Actor, passes: _Passes
) -> None:
    work = passes.single[0]
    _decide_all(project, agent, passes, work)
    args = [
        "screen",
        "resolve",
        work,
        "exclude",
        "--reason",
        "a slide deck",
        "--stage",
        "full-text",
    ]
    refused = runner.invoke(app, args, env=_env(settings.root))
    assert refused.exit_code != 0  # an exclusion needs its EX criterion
    result = runner.invoke(app, [*args, "--criterion", "EX01"], env=_env(settings.root))
    assert result.exit_code == 0, result.stderr
    assert result.stdout == f"resolved {work} (exclude)\n"
    assert final_outcomes(project, stage=FT)[work] is Outcome.EXCLUDED
