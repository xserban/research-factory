"""`check` findings of notices and versions: severity by mode, closure, the agent view."""

from __future__ import annotations

from datetime import timedelta

import pytest

from factory.events.envelope import Actor
from factory.model.notices import AssessmentDecision, NoticeKind
from factory.model.project import RigorMode
from factory.services.check import Finding, _findings_as, check
from factory.services.context import Project
from factory.services.notices import assess_notice
from factory.services.watch import watch_run
from tests.helpers import SourcesFor
from tests.notice_helpers import (
    NoticeWorld,
    StatusScript,
    check_in_cycle,
    crossref_notices,
    dependent_world,
    fetch_arxiv_version,
    notice_record,
    numbered_records,
    status_factories,
    version_in_cycle,
)
from tests.test_versions import HELD, PRE, PRE2, _answer_by_arxiv, _ids
from tests.watch_helpers import ScriptedSource, adapters, by_text


def _codes(project: Project, mode: RigorMode) -> dict[str, Finding]:
    return {f.code: f for f in _findings_as(project, mode)}


@pytest.fixture
def world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    return dependent_world(project, agent, human, mock_sources, numbered_records(3, no_doi=1))


def _retract(world: NoticeWorld, index: int = 1) -> str:
    """Observe a retraction of the `index`-th included work; return its notice id."""
    work = world.included[index]
    doi = world.doi(work)
    assert doi is not None
    crossref = StatusScript(
        "crossref",
        crossref_notices({doi: [notice_record(doi, NoticeKind.RETRACTION, "10.2000/r")]}),
    )
    check_in_cycle(
        world.project, status_factories(crossref=crossref, openalex=StatusScript("openalex"))
    )
    from tests.test_notices import _observed

    [event] = [e for e in _observed(world.project) if e["kind"] == "retraction"]
    return str(event["notice_id"])


def test_included_retracted_finding_by_mode(world: NoticeWorld) -> None:
    notice = _retract(world)
    work = world.included[1]
    severities = {
        mode: _codes(world.project, mode)["included-retracted"].severity for mode in RigorMode
    }
    assert severities == {
        RigorMode.EXPLORATORY: "warning",
        RigorMode.PILOT: "warning",
        RigorMode.SYSTEMATIC: "error",
    }
    finding = _codes(world.project, RigorMode.PILOT)["included-retracted"]
    assert finding.refs == [work] and "1" in finding.message
    # It is a gap to promote past: systematic raises it as an error.
    promoted = check(world.project, promote_to=RigorMode.SYSTEMATIC)
    assert any(f.code == "included-retracted" for f in promoted.findings)

    assess_notice(
        world.project,
        world.project.human_actor(),
        notice,
        AssessmentDecision.KEEP_FLAGGED,
        rationale="reviewed; the result stands and is labelled",
    )
    after = _codes(world.project, RigorMode.PILOT)
    assert "included-retracted" not in after and "notice-unassessed" not in after


def test_notice_unassessed_lists_notice_ids(world: NoticeWorld) -> None:
    notice = _retract(world)
    finding = _codes(world.project, RigorMode.PILOT)["notice-unassessed"]
    assert finding.refs == [notice] and finding.severity == "warning"


def test_notice_unchecked_crossref_names_works_without_a_doi(world: NoticeWorld) -> None:
    no_doi = world.by_title["Dependent study 0 of gating"]
    findings = _codes(world.project, RigorMode.PILOT)
    assert findings["notice-unchecked-crossref"].refs == [no_doi]
    assert findings["notice-unchecked-crossref"].severity == "warning"


def test_notice_coverage_age(world: NoticeWorld) -> None:
    # Three dependents against a budget of 200 give a full sweep in one cycle, so a dependent
    # never checked in more than 3 cycles is overdue.
    assert "notice-coverage-age" not in _codes(world.project, RigorMode.PILOT)
    for _ in range(4):
        world.project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
        assert (
            watch_run(
                world.project,
                sources=adapters(ScriptedSource(by_text({"attention": [[]]}))),
                trigger="scheduler",
            )
            is not None
        )
    finding = _codes(world.project, RigorMode.PILOT)["notice-coverage-age"]
    assert sorted(finding.refs) == world.included
    # A sweep clears it.
    check_in_cycle(
        world.project,
        status_factories(crossref=StatusScript("crossref"), openalex=StatusScript("openalex")),
    )
    assert "notice-coverage-age" not in _codes(world.project, RigorMode.PILOT)


@pytest.fixture
def versions(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    built = dependent_world(project, agent, human, mock_sources, [PRE, PRE2, HELD])
    pre, pre2, _ = _ids(built)
    fetch_arxiv_version(project, pre, "2301.00001v2")
    fetch_arxiv_version(project, pre2, "2301.00002v1")
    return built


def test_version_findings(versions: NoticeWorld) -> None:
    pre, pre2, held = _ids(versions)
    arxiv = StatusScript(
        "arxiv",
        _answer_by_arxiv({"2301.00001": 3, "2301.00002": 1}, linked={"2301.00002": "10.3000/pub"}),
    )
    version_in_cycle(versions.project, status_factories(arxiv=arxiv), [pre, pre2])
    findings = _codes(versions.project, RigorMode.PILOT)
    assert findings["newer-version-available"].refs == [pre]
    assert findings["version-of-record-available"].refs == [pre2]
    assert all(
        findings[c].severity == "warning"
        for c in ("newer-version-available", "version-of-record-available")
    )
    assert "version-link-conflict" not in findings

    clash = StatusScript(
        "arxiv", _answer_by_arxiv({"2301.00001": 2}, linked={"2301.00001": "10.3000/held"})
    )
    version_in_cycle(versions.project, status_factories(arxiv=clash), [pre, pre2])
    conflict = _codes(versions.project, RigorMode.PILOT)["version-link-conflict"]
    assert conflict.refs == [pre, held]
