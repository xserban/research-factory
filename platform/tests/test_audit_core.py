"""The audit lifecycle shared by screening and extraction (slice M ruling 21)."""

from pathlib import Path

import pytest

from factory.canonical import population_digest
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.screening import Channel
from factory.services import audit, audit_core, extraction_audit, passes
from factory.services.audit_core import (
    AuditPopulation,
    ceiling_verdict,
    human_gate,
    refuse_reopen,
    validate_seed,
)
from factory.services.context import Project

REOPEN = "an audit of this agreed set is open; a new one waits for a change to it"


def test_population_digest_order_independent() -> None:
    a = AuditPopulation.of([("w2", "include"), ("w1", "exclude")])
    b = AuditPopulation.of([("w1", "exclude"), ("w2", "include")])
    assert a == b
    assert a.keys == ("w1", "w2")
    assert a.provenance == ("exclude", "include")
    assert a.digest == population_digest([("w1", "exclude"), ("w2", "include")])
    assert a.digest != AuditPopulation.of([("w1", "include"), ("w2", "include")]).digest
    assert len(a) == 2


def test_refuse_reopen_same_digest() -> None:
    population = AuditPopulation.of([("w1", "include")])
    refuse_reopen(None, population)
    refuse_reopen("0" * 64, population)
    with pytest.raises(FactoryValidationError) as e:
        refuse_reopen(population.digest, population)
    assert [(i.field, i.reason) for i in e.value.issues] == [("passes", REOPEN)]


def test_human_gate_messages_per_noun(
    project: Project, agent: Actor, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert human_gate(project, human, Channel.CLI, noun="sample") == []
    assert human_gate(project, human, Channel.MCP, noun="sample") == []  # sampling is not a relay
    texts = {
        "sample": "audit samples are drawn by a human",
        "screening-label": "audit labels are human acts",
        "extraction-label": "audit labels and evidence are for a human",
    }
    for noun, text in texts.items():
        issues = human_gate(project, agent, Channel.CLI, noun=noun)  # type: ignore[arg-type]
        assert [(i.field, i.reason) for i in issues] == [("actor", text)]
    monkeypatch.setattr(passes, "is_pass_session", lambda p, s, **k: True)
    issues = human_gate(project, human, Channel.MCP, noun="screening-label")
    assert [(i.field, i.reason) for i in issues] == [("channel", "this session has joined a pass")]
    assert human_gate(project, human, Channel.CLI, noun="screening-label") == []


@pytest.mark.parametrize("given", [0, 1, 2**32 - 1])
def test_validate_seed_bounds_ok(given: int) -> None:
    assert validate_seed(given) == (given, [])


@pytest.mark.parametrize("given", [-1, 2**32])
def test_validate_seed_bounds_refused(given: int) -> None:
    seed, issues = validate_seed(given)
    assert seed == given
    assert [(i.field, i.reason) for i in issues] == [
        ("random_seed", "must be an integer from 0 to 2**32 - 1")
    ]


def test_validate_seed_draws_when_none() -> None:
    seed, issues = validate_seed(None)
    assert 0 <= seed < 2**32
    assert issues == []


def test_ceiling_verdict_enforced_flag() -> None:
    assert ceiling_verdict(0.06, 0.05, enforced=True).above is True
    assert ceiling_verdict(0.05, 0.05, enforced=True).above is False
    assert ceiling_verdict(None, 0.05, enforced=True).above is False
    verdict = ceiling_verdict(0.2, 0.05, enforced=False)
    assert (verdict.rate, verdict.ceiling, verdict.above, verdict.enforced) == (
        0.2,
        0.05,
        True,
        False,
    )


def test_screening_and_extraction_audits_share_core() -> None:
    """Both services reach the core through the module, so one patch sees both."""
    assert audit.audit_core is audit_core
    assert extraction_audit.audit_core is audit_core


def test_audit_lifecycle_is_written_once() -> None:
    services = Path(audit_core.__file__).parent
    for name in ("audit.py", "extraction_audit.py"):
        source = (services / name).read_text()
        assert "an audit of this agreed set is open" not in source, name
        assert "must be an integer from 0 to 2**32 - 1" not in source, name
        assert "secrets.randbits" not in source, name
        assert "import population_digest" not in source, name
