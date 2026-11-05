"""The human audit of agent acts at `agent_audit` gates (slice M, M-B Task 5)."""

# ruff: noqa: F811
from collections.abc import Iterator

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.project import RigorMode
from factory.model.references import Decision
from factory.model.screening import Channel, PassJoined, PassLabel
from factory.modules.contract import Autonomy
from factory.services import gates
from factory.services.check import LEVELS, _findings_as
from factory.services.context import Project
from factory.services.gates import (
    GATE_AUDIT_ERROR_CEILING,
    GateAct,
    autonomy_of,
    gate_acts,
    gate_audit_record,
    gate_audit_report,
    gate_audit_sample,
)
from tests.references_service_helpers import second_agent
from tests.test_references_resolve import _decide, extraction  # noqa: F401

LINK = "reference.link_confirm"


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _synthetic(monkeypatch: pytest.MonkeyPatch, kinds: list[str]) -> list[str]:
    """Make the gate list `kinds` as acts (`agent` or `human`), with synthetic event ids."""
    acts = [GateAct(LINK, f"evt_{i:04d}", kind, "S", None) for i, kind in enumerate(kinds)]

    def fake(project: Project, gate_id: str) -> Iterator[GateAct]:
        yield from acts

    monkeypatch.setattr(gates, "gate_acts", fake)
    return [a.event_id for a in acts if a.actor_kind == "agent"]


def _second_agent_confirms(project: Project, rex: str, agent: Actor) -> None:
    _decide(project, agent, rex, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), rex, 1, Decision.CONFIRM)


@pytest.mark.parametrize(("population", "size"), [(50, 20), (300, 30), (10, 10)])
def test_sample_size_follows_policy(
    project: Project,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
    population: int,
    size: int,
) -> None:
    _synthetic(monkeypatch, ["agent"] * population)
    sampled = gate_audit_sample(project, human, LINK, random_seed=7)
    assert len(sampled.act_event_ids) == size
    assert sampled.population == population
    assert sampled.act_event_ids == tuple(sorted(sampled.act_event_ids))


def test_draw_is_deterministic_in_the_seed(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synthetic(monkeypatch, ["agent"] * 60)
    first = gate_audit_sample(project, human, LINK, random_seed=3)
    again = gates.draw_uniform([f"evt_{i:04d}" for i in range(60)], 20, 3, key=str)
    assert list(first.act_event_ids) == again


def test_population_is_agent_acts_only(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    agents = _synthetic(monkeypatch, ["agent", "human", "agent", "human", "agent"])
    sampled = gate_audit_sample(project, human, LINK, random_seed=1)
    assert sampled.population == 3
    assert set(sampled.act_event_ids) == set(agents)


def test_agent_cannot_draw_or_label(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _second_agent_confirms(project, extraction, agent)
    before = _count(project)
    with pytest.raises(FactoryValidationError) as drawn:
        gate_audit_sample(project, agent, LINK)
    assert [i.field for i in drawn.value.issues] == ["actor"]
    sampled = gate_audit_sample(project, human, LINK, random_seed=2)
    after_draw = _count(project)
    assert after_draw == before + 1
    with pytest.raises(FactoryValidationError) as labelled:
        gate_audit_record(
            project, agent, sampled.audit_id, sampled.act_event_ids[0], True, None, Channel.CLI
        )
    assert [i.field for i in labelled.value.issues] == ["actor"]
    assert _count(project) == after_draw


def test_pass_session_cannot_relay_label(
    project: Project, extraction: str, agent: Actor, agent_other: Actor, human: Actor
) -> None:
    _second_agent_confirms(project, extraction, agent)
    sampled = gate_audit_sample(project, human, LINK, random_seed=2)
    joined = PassJoined(pass_label=PassLabel.A, session=agent_other.session, model="m")
    blob = project.blobs.put_json({"pass_label": "A"})
    project.record(
        [project.events.make("screening.pass_joined", joined, agent_other, input_blob=blob)]
    )
    relayed = human.model_copy(update={"session": agent_other.session})
    before = _count(project)
    with pytest.raises(FactoryValidationError) as err:
        gate_audit_record(
            project, relayed, sampled.audit_id, sampled.act_event_ids[0], True, None, Channel.MCP
        )
    assert [i.field for i in err.value.issues] == ["channel"]
    assert _count(project) == before
    gate_audit_record(
        project, relayed, sampled.audit_id, sampled.act_event_ids[0], True, None, Channel.CLI
    )


def test_label_refuses_unknown_audit_and_foreign_act(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _second_agent_confirms(project, extraction, agent)
    sampled = gate_audit_sample(project, human, LINK, random_seed=2)
    with pytest.raises(FactoryValidationError) as unknown:
        gate_audit_record(
            project, human, "gau_01JZ9Q3K5M7N8P0R2S4T6V8W0X", "x", True, None, Channel.CLI
        )
    assert [i.field for i in unknown.value.issues] == ["audit_id"]
    with pytest.raises(FactoryValidationError) as foreign:
        gate_audit_record(project, human, sampled.audit_id, "evt_other", True, None, Channel.CLI)
    assert [i.field for i in foreign.value.issues] == ["act_event_id"]


def test_reopen_refused_for_same_population(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synthetic(monkeypatch, ["agent"] * 30)
    gate_audit_sample(project, human, LINK, random_seed=1)
    before = _count(project)
    with pytest.raises(FactoryValidationError) as err:
        gate_audit_sample(project, human, LINK, random_seed=2)
    assert [i.field for i in err.value.issues] == ["passes"]
    assert _count(project) == before
    _synthetic(monkeypatch, ["agent"] * 31)  # a new act changes the population
    gate_audit_sample(project, human, LINK, random_seed=2)


def test_refuses_gate_that_is_not_agent_audit(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synthetic(monkeypatch, ["agent"])
    for gate in ("screening.resolve", "no.such_gate"):
        with pytest.raises(FactoryValidationError) as err:
            gate_audit_sample(project, human, gate, random_seed=1)
        assert [i.field for i in err.value.issues] == ["gate_id"]


def test_refuses_empty_population_and_bad_seed(project: Project, human: Actor) -> None:
    with pytest.raises(FactoryValidationError) as empty:
        gate_audit_sample(project, human, LINK, random_seed=1)
    assert [i.field for i in empty.value.issues] == ["gate_id"]
    with pytest.raises(FactoryValidationError) as seed:
        gate_audit_sample(project, human, LINK, random_seed=-1)
    assert "random_seed" in [i.field for i in seed.value.issues]


def _codes(project: Project, mode: RigorMode) -> list[str]:
    return [f.code for f in _findings_as(project, mode) if f.code.startswith("gate-audit")]


def test_missing_audit_finding_in_pilot(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    assert LEVELS["gate-audit-missing"] == (None, "warning", "error")
    assert _codes(project, RigorMode.PILOT) == []
    _second_agent_confirms(project, extraction, agent)
    assert _codes(project, RigorMode.PILOT) == ["gate-audit-missing"]
    assert _codes(project, RigorMode.EXPLORATORY) == []
    sampled = gate_audit_sample(project, human, LINK, random_seed=4)
    assert _codes(project, RigorMode.PILOT) == ["gate-audit-unlabelled"]
    gate_audit_record(
        project, human, sampled.audit_id, sampled.act_event_ids[0], True, None, Channel.CLI
    )
    assert _codes(project, RigorMode.PILOT) == []


def test_error_high_finding(project: Project, extraction: str, agent: Actor, human: Actor) -> None:
    assert GATE_AUDIT_ERROR_CEILING == 0.05
    _second_agent_confirms(project, extraction, agent)
    sampled = gate_audit_sample(project, human, LINK, random_seed=4)
    [act] = sampled.act_event_ids
    gate_audit_record(project, human, sampled.audit_id, act, True, None, Channel.CLI)
    report = gate_audit_report(project, LINK)
    assert report is not None and (report.sample_size, report.labelled, report.incorrect) == (
        1,
        1,
        0,
    )
    assert not report.verdict.above
    assert _codes(project, RigorMode.PILOT) == []
    gate_audit_record(project, human, sampled.audit_id, act, False, "wrong work", Channel.CLI)
    report = gate_audit_report(project, LINK)
    assert report is not None and report.incorrect == 1 and report.verdict.above
    assert not report.verdict.enforced  # advisory in pilot
    assert _codes(project, RigorMode.PILOT) == ["gate-audit-error-high"]
    [finding] = [f for f in _findings_as(project, RigorMode.PILOT) if f.code.endswith("high")]
    assert "0." not in finding.message and "1.0" not in finding.message


def test_autonomy_becomes_audited_agent_once_sampled(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _second_agent_confirms(project, extraction, agent)
    [act] = list(gate_acts(project, LINK))
    assert autonomy_of(project, act) is Autonomy.AGENT
    gate_audit_sample(project, human, LINK, random_seed=4)
    assert autonomy_of(project, act) is Autonomy.AUDITED_AGENT


def test_rebuild_determinism_with_gate_audit(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _second_agent_confirms(project, extraction, agent)
    sampled = gate_audit_sample(project, human, LINK, random_seed=4)
    gate_audit_record(
        project, human, sampled.audit_id, sampled.act_event_ids[0], False, "n", Channel.CLI
    )
    project.index.sync()
    before = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == before
    report = gate_audit_report(project, LINK)
    assert report is not None and report.incorrect == 1
