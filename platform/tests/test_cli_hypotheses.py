"""The `factory leads`, `hypotheses` and `models` commands (slice 6, plan H-C task 7)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.hypotheses import Trigger, TriggerKind
from factory.services.context import Project
from factory.services.hypotheses import hypothesis_view
from factory.services.hypothesis_review import record_review, review_next
from factory.services.leads import lead_view, record_lead
from tests.cli_helpers import _env
from tests.hypothesis_helpers import (
    CRITIC,
    HW,
    LEAD_AUTHOR,
    LEAD_TEXT,
    hw,
    lead_input,
)
from tests.test_finder_gaps import gw
from tests.test_hypothesis_review import verdict

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


def test_leads_list_and_decisions(settings: Settings, project: Project, hw: HW) -> None:
    code, out, _ = _run(settings.root, "leads", "list")
    assert code == 0 and hw.lead in out and "promoted" in out and f"work {hw.works[0]}" in out
    lead = record_lead(
        project,
        LEAD_AUTHOR,
        lead_input(LEAD_TEXT, Trigger(kind=TriggerKind.WORK, ref=hw.works[0]), framework="scamper"),
    )
    code, out, _ = _run(settings.root, "leads", "list", "--state", "open")
    assert code == 0 and lead in out and hw.lead not in out
    assert "framework: scamper" in out
    assert _run(settings.root, "leads", "list", "--state", "nonsense")[0] == 2
    code, out, _ = _run(settings.root, "leads", "park", lead)
    assert code == 0 and out.strip() == f"parked {lead}"
    assert lead_view(project, lead).state == "parked"  # type: ignore[union-attr]
    code, _, err = _run(settings.root, "leads", "discard", lead)
    assert code != 0  # the reason is required
    code, _, err = _run(settings.root, "leads", "discard", lead, "--reason", "nonsense")
    assert code == 2 and "expected one of" in err
    code, out, _ = _run(
        settings.root, "leads", "discard", lead, "--reason", "prior-failure", "--note", "n"
    )
    assert code == 0 and out.strip() == f"discarded {lead}"
    [*_, event] = _of(project, "lead.decided")
    assert event.actor.kind == "human" and event.payload["policy"] == "human"
    code, out, _ = _run(settings.root, "leads", "promote", lead)
    assert code == 0 and "promoted" in out
    code, _, err = _run(settings.root, "leads", "promote", "led_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    assert code == 1 and "lead_id" in err


def test_hypotheses_list_show_register(settings: Settings, project: Project, hw: HW) -> None:
    code, out, _ = _run(settings.root, "hypotheses", "list")
    assert code == 0 and hw.hid in out and hw.version in out and "draft" in out
    code, out, _ = _run(settings.root, "hypotheses", "show", hw.hid)
    assert code == 0
    assert "falsifier: Refuted if the 95% CI upper bound" in out and "draft" in out
    assert _run(settings.root, "hypotheses", "show", "hyp_01JZ9Q3K5M7N8P0R2S4T6V8W0X")[0] == 1
    code, _, err = _run(settings.root, "hypotheses", "register", hw.hid)
    assert code == 1 and "review-required" in err
    served = review_next(project, CRITIC)
    assert served is not None
    record_review(project, CRITIC, served.task_id, verdict())
    code, out, _ = _run(settings.root, "hypotheses", "register", hw.hid)
    assert code == 0 and out.strip() == f"registered {hw.hid} {hw.version}"
    [event] = _of(project, "hypothesis.registered")
    assert event.actor.kind == "human" and event.input_blob is None
    code, out, _ = _run(settings.root, "hypotheses", "show", hw.hid)
    assert "registered by human" in out and "reviews:" in out
    code, out, _ = _run(settings.root, "hypotheses", "list", "--state", "registered")
    assert hw.hid in out


def test_abandon_conclude_and_cutoff(settings: Settings, project: Project, hw: HW) -> None:
    code, _, err = _run(settings.root, "hypotheses", "conclude", hw.hid, "--text", "It held.")
    assert code == 1 and "not-evaluated" in err
    code, _, err = _run(
        settings.root, "hypotheses", "abandon", hw.hid, "--reason", "nonsense", "--note", "x"
    )
    assert code == 2
    code, out, _ = _run(
        settings.root, "hypotheses", "abandon", hw.hid, "--reason", "infeasible", "--note", "no gpu"
    )
    assert code == 0 and out.strip() == f"abandoned {hw.hid}"
    assert hypothesis_view(project, hw.hid).state == "abandoned"  # type: ignore[union-attr]
    code, out, _ = _run(
        settings.root, "models", "cutoff", "model-x", "2025-06-01", "--source", "model card"
    )
    assert code == 0 and out.strip() == "declared model-x 2025-06-01"
    [event] = _of(project, "model.cutoff_declared")
    assert event.actor.kind == "human" and event.payload["cutoff"] == "2025-06-01"
    assert _run(settings.root, "models", "cutoff", "model-x", "June", "--source", "s")[0] == 2
