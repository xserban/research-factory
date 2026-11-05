"""The `factory match`, `finders` and `contradictions` commands (slice 6, plan H-B, task 6)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.findings import ContradictionInput
from factory.services import finders
from factory.services.context import Project
from factory.services.evidence_report import assemble_report
from factory.services.finders import list_contradictions, propose_contradiction
from tests.card_helpers import cw
from tests.contribution_helpers import ext_a
from tests.evidence_helpers import ff, frow, pilot_inputs
from tests.finder_helpers import MatchWorld, mw
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.test_cli import _env
from tests.test_contradictions import CtrWorld, ctrw

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def test_match_prints_the_ordered_rows_with_transfer(
    settings: Settings, project: Project, mw: MatchWorld
) -> None:
    code, out, err = _run(settings.root, "match", mw.problem)
    assert code == 0, err
    lines = [line for line in out.splitlines() if line.startswith("mcd_")]
    assert [line.split()[0] for line in lines] == [mw.ok, mw.transfer, mw.unknown, mw.conflict]
    assert "transfer" in next(line for line in lines if line.startswith(mw.transfer))
    assert "transfer" not in next(line for line in lines if line.startswith(mw.ok))
    assert "match_key" in out and "conflicting pr:memory-scaling" in out
    code, out, _ = _run(settings.root, "match", mw.problem, "--transfer")
    assert [line.split()[0] for line in out.splitlines() if line.startswith("mcd_")] == [
        mw.transfer
    ]
    code, out, _ = _run(settings.root, "match", mw.problem, "--inferred")
    assert mw.inferred in out
    code, _, err = _run(settings.root, "match", mw.ok)
    assert code == 1 and "problem_id" in err


def test_finders_conflicts_prints_the_differing_conditions(
    settings: Settings, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        frow("rf:w1", "rk_a001", "M1", "80.0", training_epochs=ff("100")),
        frow("rf:w2", "rk_a002", "M1", "70.0", training_epochs=ff("300")),
    ]
    monkeypatch.setattr(
        finders, "evidence_report", lambda project, **kw: assemble_report(pilot_inputs(rows))
    )
    code, out, err = _run(settings.root, "finders", "conflicts")
    assert code == 0, err
    assert "differs_in training_epochs" in out
    assert "rk_a001" in out and "rk_a002" in out and "0.1250" in out
    code, out, _ = _run(settings.root, "finders", "conflicts", "--group", "grp_000000000000")
    assert out.strip() == "no conflicts"


def test_finders_gaps_prints_the_corpus_statement(
    settings: Settings, project: Project, mw: MatchWorld
) -> None:
    code, out, err = _run(
        settings.root, "finders", "gaps", "--rows", "card", "--columns", "pr:memory-scaling"
    )
    assert code == 0, err
    assert "Not found in this corpus" in out and "gap_key" in out
    assert f"{mw.inferred}  linear" in out
    code, _, err = _run(settings.root, "finders", "gaps", "--rows", "idea", "--columns", "task")
    assert code == 1 and "rows_axis" in err


def test_contradictions_list_confirm_and_reject(
    settings: Settings, project: Project, agent: Actor, ctrw: CtrWorld
) -> None:
    cid, _ = propose_contradiction(
        project, agent, ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note="n")
    )
    code, out, _ = _run(settings.root, "contradictions", "list")
    assert out.strip() == "no contradictions"
    code, out, err = _run(settings.root, "contradictions", "list", "--state", "inferred")
    assert code == 0, err
    assert cid in out and "inferred" in out
    code, _, err = _run(
        settings.root, "contradictions", "confirm", cid, "--rationale", "both quotes say so"
    )
    assert code == 0, err
    [decided] = _of(project, "contradiction.decided")
    assert decided.actor.kind == "human" and decided.payload["decision"] == "confirm"
    code, out, _ = _run(settings.root, "contradictions", "list")
    assert cid in out and "confirmed" in out
    code, _, err = _run(settings.root, "contradictions", "reject", cid, "--rationale", "no")
    assert code == 0, err
    assert [v.state for v in list_contradictions(project, states=("rejected",))] == ["rejected"]
    code, _, err = _run(settings.root, "contradictions", "confirm", "ctr_nope", "--rationale", "x")
    assert code == 1 and "contradiction_id" in err
