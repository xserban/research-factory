"""The screening commands at the full-text stage (plan 2C, task 8): `--stage full-text`."""

import re
from collections.abc import Callable, Mapping
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import screen_agreement
from factory.services.calibration import calibration_items, calibration_labels
from factory.services.context import Project
from factory.services.screening import open_pass
from factory.sources.registry import SourceFactory
from tests.helpers import _setup
from tests.test_cli import _env
from tests.test_prisma_full import _ta_world
from tests.test_stage_services import _both, _decide_at

FT = ScreeningStage.FULL_TEXT
TA = ScreeningStage.TITLE_ABSTRACT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_status_without_a_full_text_plan_does_not_raise(
    settings: Settings, project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    code, out, err = _run(settings.root, "status")
    assert code == 0, err
    assert "full-text" not in out


def test_full_text_commands_with_stage_option(
    settings: Settings, project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _ta_world(project, agent, human, mock_sources)
    root = settings.root
    pid = world.protocol_id
    ta_items = calibration_items(project)

    code, out, err = _run(root, "status")
    assert code == 0, err
    assert "full-text pass A: not opened" in out

    # Calibration: the stage-keyed set is drawn and labelled; title/abstract is untouched.
    code, out, err = _run(root, "calibrate", "draw", "--stage", "full-text")
    assert code == 0, err
    ft_items = calibration_items(project, stage=FT)
    assert out == f"calibration set: {len(ft_items)} works\n" and ft_items
    assert calibration_items(project) == ta_items
    code, _, err = _run(
        root,
        "calibrate",
        "label",
        ft_items[0],
        "exclude",
        "--criterion",
        "EX04",
        "--stage",
        "full-text",
    )
    assert code == 0, err
    for item in ft_items[1:]:
        code, _, err = _run(root, "calibrate", "label", item, "include", "--stage", "full-text")
        assert code == 0, err
    assert len(calibration_labels(project, stage=FT)) == len(ft_items)
    assert len(calibration_labels(project)) == len(ta_items)

    # Passes decide; the passes disagree on one work.
    open_pass(project, agent, PassLabel.A, stage=FT)
    open_pass(project, agent, PassLabel.B, stage=FT)
    first, *rest = world.eligible
    _decide_at(project, agent, FT, first, "A", "include", None, pid)
    _decide_at(project, agent, FT, first, "B", "exclude", "EX04", pid)
    for work in rest:
        _both(project, agent, FT, work, ("include", None), ("include", None), pid)

    code, out, err = _run(root, "status")
    assert code == 0, err
    assert re.search(r"full-text pass A: queued [1-9]\d*, decided [1-9]", out)

    # Agreement and resolve.
    code, out, err = _run(root, "screen", "disagreements", "--stage", "full-text")
    assert code == 0, err
    assert first in out
    code, out, _ = _run(root, "screen", "disagreements")
    assert first not in out  # the title/abstract stage has no such disagreement
    code, out, err = _run(
        root,
        "screen",
        "resolve",
        first,
        "include",
        "--reason",
        "the methods fit",
        "--stage",
        "full-text",
    )
    assert code == 0, err
    assert screen_agreement(project, project.human_actor(), stage=FT).disagreements == []

    # Audit: sample at full text, label (the stage is the audit's), report.
    code, out, err = _run(root, "audit", "sample", "--stage", "full-text")
    assert code == 0, err
    audit_id = re.search(r"aud_\w+", out)
    assert audit_id is not None
    sampled = [line.split()[0] for line in out.splitlines()[1:]]
    code, _, err = _run(root, "audit", "label", audit_id.group(0), sampled[0], "include")
    assert code == 0, err
    code, out, err = _run(root, "audit", "report", "--stage", "full-text")
    assert code == 0, err
    assert f"audit {audit_id.group(0)}: sample" in out and "labelled 1" in out
    code, out, _ = _run(root, "audit", "report")
    assert "no audit sampled" in out


def test_invalid_stage_option_exits_nonzero_and_writes_nothing(
    settings: Settings, project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    before = len(read_all(project.paths.events_dir, project.catalog))
    for args in (
        ("calibrate", "draw", "--stage", "either"),
        ("screen", "disagreements", "--stage", "bogus"),
        ("audit", "sample", "--stage", "either"),
    ):
        code, _, err = _run(settings.root, *args)
        assert code != 0 and err
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    assert calibration_items(project) == []
