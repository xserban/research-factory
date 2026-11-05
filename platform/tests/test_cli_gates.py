"""`factory gates`, the gate audit commands, `gate_status` and the methods text (M-B Task 6)."""

# ruff: noqa: F811
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.references import Decision
from factory.modules.contract import GateKind, PolicyKind
from factory.services.context import Project
from factory.services.gate_status import GateStatusRow, gates_status
from factory.services.methods import agent_methods, methods_report, render_methods
from factory.services.modules.default import default_modules
from tests.gate_helpers import amend_gate_policies, entry
from tests.helpers import SourcesFor, _setup, open_session
from tests.references_service_helpers import second_agent
from tests.test_cli import _env
from tests.test_references_resolve import _decide, extraction  # noqa: F401
from tests.test_screening_next import _draw

runner = CliRunner()
LINK = "reference.link_confirm"
AGENT = {"role": "screener", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


def _cli(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["--project", "demo", *args], env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _confirm_as_second_agent(project: Project, rex: str, agent: Actor) -> None:
    _decide(project, agent, rex, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), rex, 1, Decision.CONFIRM)


def test_factory_gates_lists_every_decision_gate(settings: Settings, project: Project) -> None:
    code, out, _ = _cli(settings.root, "gates")
    assert code == 0, out
    decision = [g.gate_id for g in default_modules().gates() if g.kind is GateKind.DECISION]
    for gate in decision:
        assert f"{gate}: " in out
    assert "reference.link_confirm: agent_audit(0.1, 20) from the preset, floor agent_audit" in out
    code, raw, _ = _cli(settings.root, "gates", "--json")
    rows = [GateStatusRow.model_validate(r) for r in json.loads(raw)]
    assert [r.gate_id for r in rows] == decision
    assert rows == gates_status(project)


def test_gates_after_an_amendment_and_an_audit(
    settings: Settings, project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _confirm_as_second_agent(project, extraction, agent)
    code, out, err = _cli(settings.root, "gate", "audit", "sample", LINK, "--seed", "3")
    assert code == 0, err
    assert "of 1 agent acts" in out
    audit_id = out.split()[2].rstrip(":")
    act = out.splitlines()[1]
    code, _, err = _cli(settings.root, "gate", "audit", "label", audit_id, act, "wrong")
    assert code == 2
    code, _, err = _cli(settings.root, "gate", "audit", "label", audit_id, act, "incorrect")
    assert code == 0, err
    code, out, _ = _cli(settings.root, "gate", "audit", "report", LINK)
    assert "sample 1, labelled 1, incorrect 1" in out and "above ceiling: yes" in out
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    code, out, _ = _cli(settings.root, "gates")
    assert "reference.link_confirm: human from the protocol" in out
    assert "below policy: 1" in out
    lines = out.splitlines()
    block = lines[lines.index(next(x for x in lines if x.startswith(f"{LINK}: "))) + 1]
    assert block == "  acts: human 0, audited-agent 1, agent 0"


def test_gate_audit_report_without_a_sample(settings: Settings, project: Project) -> None:
    code, out, _ = _cli(settings.root, "gate", "audit", "report", LINK)
    assert code == 0 and "no gate audit sampled" in out
    code, _, err = _cli(settings.root, "gate", "audit", "sample", LINK)
    assert code == 1 and "gate_id" in err


@pytest.mark.anyio
async def test_gate_status_refused_to_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    async with open_session(settings, clock, {}) as session:
        fresh = await session.call("gate_status", project="demo")
        assert fresh["ok"] is True, fresh
        row = next(g for g in fresh["data"]["gates"] if g["gate_id"] == LINK)
        assert row["fraction"] is None and row["minimum"] is None and row["audit"] is None
        joined = await session.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True, joined
        before = len(read_all(project.paths.events_dir, project.catalog))
        refused = await session.call("gate_status", project="demo")
    assert refused["ok"] is False
    assert [e["field"] for e in refused["errors"]] == ["session"]
    assert len(read_all(project.paths.events_dir, project.catalog)) >= before


def test_agent_view_hides_figures(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    from factory.model.screening import Channel
    from factory.services.gates import gate_audit_record, gate_audit_sample

    _confirm_as_second_agent(project, extraction, agent)
    sampled = gate_audit_sample(project, human, LINK, random_seed=1)
    gate_audit_record(
        project, human, sampled.audit_id, sampled.act_event_ids[0], False, None, Channel.CLI
    )
    [row] = [r for r in gates_status(project) if r.gate_id == LINK]
    assert row.audit is not None and row.audit.incorrect == 1
    hidden = row.agent_view()
    assert hidden.fraction is None and hidden.minimum is None
    assert hidden.audit is not None and hidden.audit.audit_id == row.audit.audit_id
    assert hidden.audit.sample_size is None and hidden.audit.error_rate is None
    assert hidden.audit.labelled is None and hidden.audit.above_ceiling is None
    report = methods_report(project)
    agent_report, withheld = agent_methods(project, report)
    text = render_methods(agent_report, withheld=withheld)
    assert "Decision gates." in text and "withheld from the agent view" in text
    assert "1 incorrect" not in text


def test_methods_unchanged_for_all_human_projects(project: Project) -> None:
    """A pilot project whose gates were all passed by humans (or not at all) says nothing new,
    though the pilot preset of the link gates is `agent_audit`."""
    report = methods_report(project)
    assert report.gate_policy == []
    assert "Decision gates" not in render_methods(report)


def test_methods_states_policy_and_counts_in_pilot_with_agent_links(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    assert methods_report(project).gate_policy == []
    _confirm_as_second_agent(project, extraction, agent)
    report = methods_report(project)
    [row] = report.gate_policy
    assert row.gate_id == LINK and row.counts["agent"] == 1
    text = render_methods(report)
    assert "Decision gates." in text
    assert (
        "Gate reference.link_confirm: policy agent_audit (from the preset); "
        "acts human 0, audited-agent 0, agent 1. No human audit drawn." in text
    )
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    text = render_methods(methods_report(project))
    assert "policy human (from the protocol)" in text
    assert "1 act(s) were passed by an agent before the policy became human." in text


def test_methods_json_stays_a_model(project: Project) -> None:
    data: dict[str, Any] = methods_report(project).model_dump(mode="json")
    assert data["gate_policy"] == []
