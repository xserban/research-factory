"""`check` findings of a living review: the watch, the cycle, the update audit (Task 6)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.model.project import RigorMode
from factory.model.protocol import MethodProfile
from factory.model.watch import WatchPlan, WatchSource
from factory.services.check import Finding, _findings_as, check
from factory.services.context import Project
from factory.services.dedup import canonical_works
from factory.services.protocol import amend_protocol, current_protocol, record_protocol
from factory.services.watch import watch_run
from tests.helpers import SourcesFor, bind_ids, pilot_protocol_spec, record_pilot_question
from tests.living_helpers import filler
from tests.test_watch_window import windowed  # noqa: F401  (a fixture)
from tests.watch_helpers import ScriptedSource, adapters, by_text, record, watch_ready

A = [record("Alpha methods for sparse graphs", author="Ana Li", year=2021)]


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    watch_ready(project, agent, human, mock_sources)
    return project


def _run(project: Project, script: Any = None, **kw: Any) -> Any:
    source = ScriptedSource(script or by_text({"attention": [A], "transformers": [A]}))
    return watch_run(project, sources=adapters(source), trigger="scheduler", **kw)


def _found(project: Project, code: str, mode: RigorMode = RigorMode.PILOT) -> list[Finding]:
    return [f for f in _findings_as(project, mode) if f.code == code]


def test_finding_watch_plan_missing(explore_project: Project, agent: Actor, human: Actor) -> None:
    question_id = record_pilot_question(explore_project, agent)
    spec = pilot_protocol_spec(question_id, None, reviewer=human.id)
    living = spec.model_copy(update={"method_profile": MethodProfile.LIVING_REVIEW})
    record_protocol(
        explore_project,
        agent,
        living,
        ready=False,
        decision_ids=bind_ids(explore_project, agent, DecisionLevel.PROTOCOL),
    )
    assert [
        f.severity for f in _found(explore_project, "watch-plan-missing", RigorMode.EXPLORATORY)
    ] == ["warning"]
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        [finding] = _found(explore_project, "watch-plan-missing", mode)
        assert finding.severity == "error"


def test_check_promote_to_pilot_lists_watch_plan_gap(
    explore_project: Project, agent: Actor, human: Actor
) -> None:
    question_id = record_pilot_question(explore_project, agent)
    spec = pilot_protocol_spec(question_id, None, reviewer=human.id)
    living = spec.model_copy(update={"method_profile": MethodProfile.LIVING_REVIEW})
    record_protocol(
        explore_project,
        agent,
        living,
        ready=False,
        decision_ids=bind_ids(explore_project, agent, DecisionLevel.PROTOCOL),
    )
    assert "watch-plan-missing" not in {
        f.code for f in check(explore_project).findings if f.severity == "error"
    }
    promoted = check(explore_project, promote_to=RigorMode.PILOT)
    assert "watch-plan-missing" in {f.code for f in promoted.findings}


def test_no_watch_findings_without_a_living_setup(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from tests.helpers import ready_protocol

    ready_protocol(project, agent, human, mock_sources)
    watch_codes = {
        "watch-plan-missing",
        "watch-overdue",
        "watch-source-failing",
        "watch-cycle-open",
        "window-misses",
        "update-audit-outstanding",
        "calibration-model-drift",
    }
    assert watch_codes.isdisjoint({f.code for f in check(project).findings})


def test_finding_watch_overdue(ready: Project, clock: FixedClock) -> None:
    assert _run(ready) is not None
    clock.advance(timedelta(days=13))  # due at +7, overdue after +14
    assert _found(ready, "watch-overdue") == []
    clock.advance(timedelta(days=2))
    [finding] = _found(ready, "watch-overdue")
    assert finding.severity == "warning" and finding.refs == ["openalex"]


def test_finding_watch_source_failing(ready: Project, clock: FixedClock) -> None:
    for _ in range(2):
        _run(ready, lambda _n, _s: "fail")
        clock.advance(timedelta(days=8))
    assert _found(ready, "watch-source-failing") == []
    _run(ready, lambda _n, _s: "fail")
    [finding] = _found(ready, "watch-source-failing")
    assert finding.refs == ["openalex"] and "3" in finding.message
    assert [f.severity for f in _found(ready, "watch-source-failing", RigorMode.SYSTEMATIC)] == [
        "error"
    ]


def test_finding_watch_cycle_open(
    ready: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("process died")

    with monkeypatch.context() as patch:
        patch.setattr("factory.services.watch._finish", boom)
        with pytest.raises(RuntimeError):
            _run(ready)
    assert _found(ready, "watch-cycle-open") == []  # it may still be running
    clock.advance(timedelta(days=2))
    [finding] = _found(ready, "watch-cycle-open")
    assert finding.severity == "warning" and finding.refs[0].startswith("wcy_")


def test_finding_window_misses(windowed: Project, clock: FixedClock) -> None:  # noqa: F811
    known = record("Alpha methods for sparse graphs", author="Ana Li", published="2026-10-01")
    missed = record("Beta bounds on federated drift", author="Bo Chen", published="2026-11-03")
    pages = {"attention": [[known]], "transformers": [[]]}
    assert _run(windowed, by_text(pages)) is not None
    clock.advance(timedelta(days=8))
    assert _run(windowed, by_text(pages)) is not None
    assert _found(windowed, "window-misses") == []
    clock.advance(timedelta(days=8))
    replay = _run(windowed, by_text({"attention": [[known, missed]], "transformers": [[]]}))
    assert replay is not None
    [finding] = _found(windowed, "window-misses")
    assert finding.severity == "warning" and finding.refs == [replay.cycle_id]
    assert "1" in finding.message
    assert [f.severity for f in _found(windowed, "window-misses", RigorMode.SYSTEMATIC)] == [
        "warning"
    ]


def test_finding_update_audit_outstanding(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from tests.test_audit import _agree
    from tests.test_audit_top_up import _audited, _protocol_id

    _audited(project, agent, human, mock_sources)
    current = current_protocol(project)
    assert current is not None
    plan = WatchPlan(sources=(WatchSource(source="openalex", interval_days=7),))
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"watch_plan": plan}),
        reason="declare the watch",
        semantic=True,
        effects={},
    )
    assert _found(project, "update-audit-outstanding") == []  # no cycle yet
    summary = _run(project, by_text({"attention": [filler(40)]}))
    new = sorted(w.id for w in canonical_works(project) if w.id in set(summary.new_work_ids))
    _agree(project, agent, new[:30], _protocol_id(project), exclude=True)
    _agree(project, agent, new[30:], _protocol_id(project), exclude=False)
    [finding] = _found(project, "update-audit-outstanding")
    assert finding.severity == "warning" and "20" in finding.message
    assert [
        f.severity for f in _found(project, "update-audit-outstanding", RigorMode.SYSTEMATIC)
    ] == ["error"]
    assert _found(project, "update-audit-outstanding", RigorMode.EXPLORATORY) == []


def test_findings_carry_no_document_text(ready: Project, clock: FixedClock) -> None:
    assert _run(ready) is not None
    clock.advance(timedelta(days=30))
    findings = _found(ready, "watch-overdue")
    assert findings
    text = " ".join(f.message + " ".join(f.refs) for f in findings)
    assert "Alpha" not in text and "sparse" not in text
