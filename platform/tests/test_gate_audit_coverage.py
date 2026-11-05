"""A stale or unlabelled gate audit does not silence the findings (M-B review, finding 3)."""

from collections.abc import Iterator

import pytest

from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.screening import Channel
from factory.services import gates
from factory.services.check import _findings_as
from factory.services.context import Project
from factory.services.gates import GateAct, gate_audit_record, gate_audit_sample

LINK = "reference.link_confirm"
EARLY1 = "ev_" + "0" * 25 + "1"
EARLY2 = "ev_" + "0" * 25 + "2"
LATE = "ev_" + "Z" * 26


def _acts(monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> None:
    acts = [GateAct(LINK, i, "agent", "S", None) for i in ids]

    def fake(project: Project, gate_id: str) -> Iterator[GateAct]:
        if gate_id == LINK:
            yield from acts

    monkeypatch.setattr(gates, "gate_acts", fake)


def _findings(project: Project) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (f.code, tuple(f.refs))
        for f in _findings_as(project, RigorMode.PILOT)
        if f.code.startswith("gate-audit")
    ]


def test_acts_after_the_audit_are_missing_again(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acts(monkeypatch, [EARLY1, EARLY2])
    sampled = gate_audit_sample(project, human, LINK, random_seed=1)
    for act in sampled.act_event_ids:
        gate_audit_record(project, human, sampled.audit_id, act, True, None, Channel.CLI)
    assert _findings(project) == []
    _acts(monkeypatch, [EARLY1, EARLY2, LATE])
    assert _findings(project) == [("gate-audit-missing", (LATE,))]
    gate_audit_sample(project, human, LINK, random_seed=2)  # a new population allows a new draw


def test_an_unlabelled_sample_is_reported(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _acts(monkeypatch, [EARLY1, EARLY2])
    sampled = gate_audit_sample(project, human, LINK, random_seed=1)
    assert [c for c, _ in _findings(project)] == ["gate-audit-unlabelled"]
    first, *rest = sampled.act_event_ids
    gate_audit_record(project, human, sampled.audit_id, first, True, None, Channel.CLI)
    assert bool(rest) is ([c for c, _ in _findings(project)] == ["gate-audit-unlabelled"])
    for act in rest:
        gate_audit_record(project, human, sampled.audit_id, act, True, None, Channel.CLI)
    assert _findings(project) == []


def test_only_acts_inside_a_drawn_population_read_audited(
    project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.modules.contract import Autonomy
    from factory.services.gates import autonomy_of

    _acts(monkeypatch, [EARLY1])
    gate_audit_sample(project, human, LINK, random_seed=1)
    early = GateAct(LINK, EARLY1, "agent", "S", None)
    late = GateAct(LINK, LATE, "agent", "S", None)
    assert autonomy_of(project, early) is Autonomy.AUDITED_AGENT
    assert autonomy_of(project, late) is Autonomy.AGENT
