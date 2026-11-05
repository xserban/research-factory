"""The `factory extract` commands (plan D, task 11): human acts on CLI channel."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.extraction_agreement import extraction_agreement
from tests.extraction_helpers import _both, _r, ext_a, ext_b, screened, world  # noqa: F401
from tests.test_cli import _env

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def test_status_prints_unit_counts_per_pass(
    settings: Settings,
    project: Project,
    ext_a: Actor,  # noqa: F811
    ext_b: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
) -> None:
    _both(project, ext_a, ext_b)
    code, out, err = _run(settings.root, "extract", "status")
    assert code == 0, err
    n = len(world)
    assert f"pass A: current {n}, open 0, queued 0, stale 0" in out
    assert f"pass B: current {n}, open 0, queued 0, stale 0" in out


def test_agreement_prints_disagreements_with_both_values_and_group_rates(
    settings: Settings,
    project: Project,
    human: Actor,
    ext_a: Actor,  # noqa: F811
    ext_b: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(unit="%")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    code, out, err = _run(settings.root, "extract", "agreement")
    assert code == 0, err
    assert f"{odd}  {d.row_key}  value (value)" in out
    assert "  A: 1" in out and "  B: 1 %" in out
    assert "anchor t1  cell t1.r3.c2  quote: 1" in out
    assert "rate " in out and "overall" in out


def test_resolve_records_a_human_cli_event_and_refuses_a_bad_choice(
    settings: Settings,
    project: Project,
    human: Actor,
    ext_a: Actor,  # noqa: F811
    ext_b: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(unit="%")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    base = ["extract", "resolve", odd, d.row_key, "--field", "value", "--reason", "B is right"]
    code, _, _ = _run(settings.root, *base, "--choice", "x")
    assert code != 0
    assert not _of(project, "extraction.resolved")
    code, _, err = _run(settings.root, *base, "--choice", "b")
    assert code == 0, err
    [event] = _of(project, "extraction.resolved")
    assert event.actor.kind == "human"
    assert event.payload["channel"] == "cli"
    assert event.payload["choice"] == "b"
    assert not extraction_agreement(project, human).disagreements


def test_audit_sample_label_and_report(
    settings: Settings,
    project: Project,
    ext_a: Actor,  # noqa: F811
    ext_b: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
) -> None:
    _both(project, ext_a, ext_b)
    code, out, err = _run(settings.root, "extract", "audit-sample")
    assert code == 0, err
    [sampled] = _of(project, "extraction.audit_sampled")
    audit_id = sampled.payload["audit_id"]
    item = sampled.payload["items"][0]
    assert audit_id in out and "element:" in out
    outside = _run(
        settings.root,
        "extract",
        "audit-label",
        audit_id,
        "wrk_none",
        item["row_key"],
        item["field"],
        "--correct",
    )
    assert outside[0] == 1 and "not in this audit sample" in outside[2]
    assert not _of(project, "extraction.audit_labelled")
    code, _, err = _run(
        settings.root,
        "extract",
        "audit-label",
        audit_id,
        item["work_id"],
        item["row_key"],
        item["field"],
        "--incorrect",
        "--note",
        "wrong cell",
    )
    assert code == 0, err
    [label] = _of(project, "extraction.audit_labelled")
    assert label.payload["correct"] is False and label.payload["channel"] == "cli"
    code, out, err = _run(settings.root, "extract", "audit-report")
    assert code == 0, err
    assert f"audit {audit_id}: sample" in out and "error rate" in out
