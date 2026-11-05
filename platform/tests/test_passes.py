"""One pass-membership service and one independence rule (slice M ruling 21, decision 55)."""

import re
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel
from factory.services import passes
from factory.services.agreement import resolve_disagreement
from factory.services.audit import audit_record, audit_sample
from factory.services.calibration import label_calibration
from factory.services.context import Project
from factory.services.passes import (
    PassMembership,
    is_pass_session,
    memberships,
    shared_refusal,
)
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION
from tests.test_agreement import _decide_four
from tests.test_agreement import _ready as _agreement_ready
from tests.test_audit import _agree, _population
from tests.test_calibration import _draw
from tests.test_calibration import _setup as _calibration_setup

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
A, B = PassLabel.A, PassLabel.B
SERVICES = Path(__file__).parent.parent / "src" / "factory" / "services"


def _extraction_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every session a member of one extraction pass and of no screening pass."""
    member = PassMembership(module="extraction", scope="evidence", stage=None, label=A)
    monkeypatch.setattr(passes, "memberships", lambda project, session: frozenset({member}))


def _screening_only(monkeypatch: pytest.MonkeyPatch) -> None:
    member = PassMembership(module="screening", scope=None, stage="title-abstract", label=A)
    monkeypatch.setattr(passes, "memberships", lambda project, session: frozenset({member}))


def _fields(exc: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in exc.value.issues]


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


# --- Membership ---


def test_memberships_empty_for_a_stranger(project: Project) -> None:
    assert memberships(project, "ses_nobody") == frozenset()
    assert not is_pass_session(project, "ses_nobody")


def test_is_pass_session_filters_by_module_and_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    project = None  # the stub below ignores it
    screening = PassMembership("screening", None, "full-text", A)
    extraction = PassMembership("extraction", "contribution", None, B)
    monkeypatch.setattr(passes, "memberships", lambda p, s: frozenset({screening, extraction}))
    assert is_pass_session(project, "s")  # type: ignore[arg-type]
    assert is_pass_session(project, "s", module="screening")  # type: ignore[arg-type]
    assert is_pass_session(project, "s", module="extraction")  # type: ignore[arg-type]
    assert is_pass_session(project, "s", stage=ScreeningStage.FULL_TEXT)  # type: ignore[arg-type]
    assert not is_pass_session(
        project,  # type: ignore[arg-type]
        "s",
        stage=ScreeningStage.TITLE_ABSTRACT,
    )
    assert not is_pass_session(
        project,  # type: ignore[arg-type]
        "s",
        module="extraction",
        stage=ScreeningStage.FULL_TEXT,
    )


def test_memberships_cover_both_tables(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from factory.model.screening import PassJoined

    _calibration_setup(project, agent, human, mock_sources)
    joined = PassJoined(pass_label=A, session=SESSION, model="claude-opus-5-5")
    project.record(
        [
            project.events.make(
                "screening.pass_joined",
                joined,
                agent,
                input_blob=project.blobs.put_json({"pass": "A"}),
            )
        ]
    )
    found = memberships(project, SESSION)
    assert {m.module for m in found} == {"screening"}
    assert {m.stage for m in found} == {"title-abstract"}
    assert is_pass_session(project, SESSION, module="screening")
    assert not is_pass_session(project, SESSION, module="extraction")


# --- The independence rule ---


def test_shared_refusal_messages_unchanged() -> None:
    err = shared_refusal({A: {"s1"}, B: {"s1"}}, {A: set(), B: set()}, noun="screening")
    assert err is not None
    assert err.issues[0].field == "passes"
    assert (
        err.issues[0].reason == "a session has joined both passes; each pass needs its own session"
    )
    err = shared_refusal({A: {"s1"}, B: {"s2"}}, {A: {"m"}, B: {"m", "n"}}, noun="screening")
    assert err is not None
    assert err.issues[0].reason == "the passes share a model (m); each pass needs its own"
    err = shared_refusal({A: {"s1"}, B: {"s1"}}, {A: set(), B: set()}, noun="extraction")
    assert err is not None
    assert err.issues[0].reason == (
        "a session has joined both extraction passes; each needs its own session"
    )
    err = shared_refusal({A: {"s1"}, B: {"s2"}}, {A: {"m"}, B: {"m"}}, noun="extraction")
    assert err is not None
    assert err.issues[0].reason == "the passes share a model (m); each needs its own"
    assert shared_refusal({A: {"s1"}, B: {"s2"}}, {A: {"m"}, B: {"n"}}, noun="extraction") is None


def test_session_refusal_precedes_model_refusal() -> None:
    err = shared_refusal({A: {"s"}, B: {"s"}}, {A: {"m"}, B: {"m"}}, noun="screening")
    assert err is not None
    assert "session" in err.issues[0].reason


# --- Ruling 2: a session in any pass cannot relay a human act ---


def test_extraction_session_cannot_relay_calibration_label(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration_setup(project, agent, human, mock_sources)
    items = _draw(project)
    before = _count(project)
    _extraction_only(monkeypatch)
    with pytest.raises(FactoryValidationError) as exc:
        label_calibration(project, human, items[0], "include", None, Channel.MCP)
    assert "channel" in _fields(exc)
    assert _count(project) == before
    assert label_calibration(project, human, items[0], "include", None, Channel.CLI)


def test_extraction_session_cannot_relay_screening_resolution(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_id = _agreement_ready(project, agent, human, mock_sources)
    _, _, w3, _ = _decide_four(project, agent, protocol_id)
    before = _count(project)
    _extraction_only(monkeypatch)
    with pytest.raises(FactoryValidationError) as exc:
        resolve_disagreement(project, human, w3, "include", None, "relayed", Channel.MCP)
    assert _fields(exc) == ["channel"]
    assert _count(project) == before


def test_extraction_session_cannot_relay_screening_audit_label(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=False)
    sampled = audit_sample(project, human, random_seed=7)
    before = _count(project)
    _extraction_only(monkeypatch)
    work = sampled.work_ids[0]
    with pytest.raises(FactoryValidationError) as exc:
        audit_record(project, human, sampled.audit_id, work, "include", None, Channel.MCP)
    assert _fields(exc) == ["channel"]
    assert _count(project) == before


def test_screening_session_still_cannot_relay_calibration_label(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration_setup(project, agent, human, mock_sources)
    items = _draw(project)
    _screening_only(monkeypatch)
    with pytest.raises(FactoryValidationError):
        label_calibration(project, human, items[0], "include", None, Channel.MCP)


# --- One definition ---


def test_no_duplicate_membership_queries() -> None:
    """The membership predicate (`SELECT 1 FROM pass_sessions` and `SELECT 1 FROM
    extraction_sessions`, the form the five old helpers used) is gone from every service but
    `services/passes.py`, which asks `... FROM <table> WHERE session = :session`."""
    old = re.compile(r"SELECT 1 FROM (pass|extraction)_sessions")
    assert [p.name for p in SERVICES.glob("*.py") if old.search(p.read_text())] == []
    pattern = re.compile(r"FROM (pass|extraction)_sessions WHERE session = :session\"")
    owners = {path.name: len(pattern.findall(path.read_text())) for path in SERVICES.glob("*.py")}
    assert {name: n for name, n in owners.items() if n} == {"passes.py": 2}
