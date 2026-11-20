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
from factory.model.screening import DecisionRecorded, PassLabel, ScreeningPhase, Verdict
from factory.services.agreement import screen_agreement
from factory.services.calibration import calibration_items, calibration_labels
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.evidence import work_evidence
from factory.services.screening import open_pass
from factory.sources.registry import SourceFactory
from tests.cli_helpers import _env
from tests.fulltext_helpers import _both, _ta_world
from tests.helpers import _setup

FT = ScreeningStage.FULL_TEXT
TA = ScreeningStage.TITLE_ABSTRACT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _decide_real(
    project: Project,
    agent: Actor,
    work: str,
    label: str,
    verdict: str,
    criterion: str | None,
    protocol_id: str,
) -> None:
    """A full-text decision pinned to the work's real conversion, citing a real anchor."""
    ref = default_conversion(project, work)
    assert ref is not None
    decision_id = f"dec_{project.ids.ulid()}"
    payload = DecisionRecorded(
        decision_id=decision_id,
        work_id=work,
        pass_label=PassLabel(label),
        phase=ScreeningPhase.SCREENING,
        stage=FT,
        verdict=Verdict(verdict),
        criterion=None if criterion is None else f"{protocol_id}:{criterion}",
        quote="Lorem ipsum dolor sit amet.",
        rationale="rationale",
        protocol_id=protocol_id,
        task_id="tsk_test",
        supersedes=None,
        anchor="s3.p1",
        conversion_id=ref.conversion_id,
    )
    blob = project.blobs.put_json({"work_id": work})
    project.record(
        [
            project.events.make(
                "screening.decision_recorded", payload, agent, refs=(decision_id,), input_blob=blob
            )
        ]
    )


def test_status_without_a_full_text_plan_does_not_raise(
    settings: Settings, project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    code, out, err = _run(settings.root, "status")
    assert code == 0, err
    # Decision 149: a protocol without a full-text plan is named as a blocking next step.
    assert "BLOCKING next step" in out
    assert "full-text screening is not planned in the protocol" in out


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
    assert out.startswith(f"calibration set: {len(ft_items)} works\n") and ft_items
    assert calibration_items(project) == ta_items
    for item in ft_items:
        assert item in out
    assert out.count("  read: factory document read ") == len(ft_items)
    first_cal = ft_items[0]
    found_cal = work_evidence(project, first_cal, FT)
    assert found_cal.conversion_id and found_cal.document_id
    assert (
        f"  document {found_cal.document_id}  conversion {found_cal.conversion_id}\n"
        f"  read: factory document read {first_cal} --conversion {found_cal.conversion_id}" in out
    )
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
    _decide_real(project, agent, first, "A", "include", None, pid)
    _decide_real(project, agent, first, "B", "exclude", "EX04", pid)
    for work in rest:
        _both(project, agent, FT, work, ("include", None), ("include", None), pid)

    code, out, err = _run(root, "status")
    assert code == 0, err
    assert re.search(r"full-text pass A: queued [1-9]\d*, decided [1-9]", out)

    # Agreement and resolve.
    code, out, err = _run(root, "screen", "disagreements", "--stage", "full-text")
    assert code == 0, err
    assert first in out
    pinned = work_evidence(project, first, FT)
    assert pinned.conversion_id and pinned.document_id
    assert f"  document {pinned.document_id}  conversion {pinned.conversion_id}" in out
    assert f"factory document read {first} --conversion {pinned.conversion_id}" in out
    assert "anchor s3.p1" in out
    disagreement = screen_agreement(project, project.human_actor(), stage=FT).disagreements[0]
    assert disagreement.a.anchor == "s3.p1" and disagreement.a.conversion_id
    assert disagreement.a.document_id == pinned.document_id
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
    sampled = [line.split()[0] for line in out.splitlines()[1:] if line.startswith("rf:")]
    assert sampled and "  read: factory document read " in out and "conversion cnv_" in out
    assert "  anchor " in out and "quote: " in out
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
