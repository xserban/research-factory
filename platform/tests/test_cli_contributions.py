# ruff: noqa: F401, F811
"""The `factory contributions` commands (plan G2-B, task 5): human acts on the CLI channel."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.contributions import contribution_agreement
from tests.cli_helpers import _env
from tests.contribution_helpers import ctr_a, ctr_b, screened, with_references, world
from tests.test_contribution_agreement import _drive, _reading, refs

runner = CliRunner()
A, B = PassLabel.A, PassLabel.B


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def _both(project: Project, a: Actor, b: Actor, work: str, cited_b: int = 5) -> None:
    _drive(project, a, A, _reading(work))
    _drive(project, b, B, _reading(work, cited=cited_b))


def test_status_prints_computed_counts_and_no_references_ids(
    settings: Settings, project: Project, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    _both(project, ctr_a, ctr_b, refs[0])
    code, out, err = _run(settings.root, "contributions", "status")
    assert code == 0, err
    n = len(refs)
    assert f"units: current {2 * n}" in out
    assert f"addition {n}" in out and f"not-stated {2 * (n - 1)}" in out
    assert f"not-stated: base-idea {n - 1}, limitation {n - 1}" in out
    assert "cited-entry markers: matched 1" in out
    assert f"no-references: {n - 1}" in out
    assert all(f"  {w}" in out for w in refs[1:]) and f"  {refs[0]}" not in out
    assert "other-conversion: 0" in out


def test_list_filters_by_work_and_kind(
    settings: Settings, project: Project, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    _both(project, ctr_a, ctr_b, refs[0])
    code, out, err = _run(settings.root, "contributions", "list", "--work", refs[0])
    assert code == 0, err
    assert "base-idea" in out and "entry 5 (matched)" in out
    assert "quote: We build on linear attention [5] for vision." in out
    assert refs[1] not in out
    code, out, _ = _run(settings.root, "contributions", "list", "--kind", "not-stated")
    assert code == 0
    assert "not-stated (base-idea)" in out and "base-idea  name" not in out
    code, out, _ = _run(settings.root, "contributions", "list", "--kind", "result")
    assert out.strip() == "no items"


def test_agreement_prints_the_disagreements(
    settings: Settings, project: Project, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    _both(project, ctr_a, ctr_b, refs[0], cited_b=4)
    code, out, err = _run(settings.root, "contributions", "agreement")
    assert code == 0, err
    assert "cited_entry (value)" in out and "  A: 5" in out and "  B: 4" in out


def test_resolve_records_a_human_cli_event_with_the_contribution_pack(
    settings: Settings,
    project: Project,
    human: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    refs: list[str],
) -> None:
    _both(project, ctr_a, ctr_b, refs[0], cited_b=4)
    (d,) = contribution_agreement(project, human).disagreements
    base = ["contributions", "resolve", d.work_id, d.row_key, "--field", "cited_entry"]
    code, _, _ = _run(settings.root, *base, "--reason", "B reads it", "--choice", "x")
    assert code != 0 and not _of(project, "extraction.resolved")
    code, _, err = _run(settings.root, *base, "--reason", "B reads it", "--choice", "b")
    assert code == 0, err
    [event] = _of(project, "extraction.resolved")
    assert event.actor.kind == "human" and event.payload["channel"] == "cli"
    assert event.payload["pack"] == "contribution" and event.payload["choice"] == "b"
    assert not contribution_agreement(project, human).disagreements


def test_audit_sample_label_and_report(
    settings: Settings, project: Project, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    _both(project, ctr_a, ctr_b, refs[0])
    code, out, err = _run(settings.root, "contributions", "audit", "sample")
    assert code == 0, err
    [sampled] = _of(project, "extraction.audit_sampled")
    assert sampled.payload["pack"] == "contribution"
    audit_id = sampled.payload["audit_id"]
    item = sampled.payload["items"][0]
    assert audit_id in out
    outside = _run(
        settings.root,
        "contributions",
        "audit",
        "label",
        audit_id,
        item["work_id"],
        "rk_000000000000",
        item["field"],
        "--correct",
    )
    assert outside[0] != 0 and not _of(project, "extraction.audit_labelled")
    code, out, err = _run(
        settings.root,
        "contributions",
        "audit",
        "label",
        audit_id,
        item["work_id"],
        item["row_key"],
        item["field"],
        "--incorrect",
        "--note",
        "wrong entry",
    )
    assert code == 0, err
    [label] = _of(project, "extraction.audit_labelled")
    assert label.actor.kind == "human" and label.payload["correct"] is False
    assert label.payload["pack"] == "contribution"
    code, out, err = _run(settings.root, "contributions", "audit", "report")
    assert code == 0, err
    assert f"audit {audit_id}" in out and "error rate" in out and "incorrect 1" in out


def test_audit_report_without_a_sample(
    settings: Settings, project: Project, world: list[str]
) -> None:
    code, out, err = _run(settings.root, "contributions", "audit", "report")
    assert code == 0, err
    assert "no audit sampled" in out
