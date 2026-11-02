"""`check` (plan 5b, task 4): one table-driven test per rule row, the named gaps, and promotion.

Each row's severity is asserted per mode through `_findings_as`, which gives the findings a mode
emits over the same events. Each assertion names the code, the severity and the refs.
"""

from collections.abc import Callable, Mapping

import pytest

from factory.events.envelope import Actor
from factory.model.dedup import DedupReverted
from factory.model.project import RigorMode
from factory.model.protocol import PressElement, PressFinding
from factory.model.screening import Channel, PassLabel
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services import check as check_module
from factory.services.audit import audit_record, audit_sample
from factory.services.calibration import calibration_items, label_calibration
from factory.services.check import Finding, _findings_as, check
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run
from factory.services.prisma import SearchReport, search_report
from factory.services.protocol import press_review
from factory.services.screening import open_pass, pass_b_sample
from factory.services.search import list_works
from factory.services.seeds import add_seeds, explain_seed_miss
from factory.sources.registry import SourceFactory
from tests.helpers import _protocol, _setup
from tests.test_chase_service import _corpus, _ordinary, _settle
from tests.test_prisma import _merge_items
from tests.test_screening_next import _decide, _draw

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
MODES = (RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC)
SEED_DOI = "10.1000/p7"
REVERTED_MERGE_NOTE = "gone"


def _rows(expected: tuple[str | None, str | None, str | None]) -> pytest.MarkDecorator:
    """Parametrize one rule row over the modes exploratory, pilot and systematic, in that order."""
    return pytest.mark.parametrize(
        ("mode", "expected"),
        list(zip(MODES, expected, strict=True)),
        ids=[mode.value for mode in MODES],
    )


def _assert_row(
    project: Project,
    code: str,
    mode: RigorMode,
    expected: str | None,
    *,
    refs: list[str] | None = None,
    role: str | None = None,
) -> None:
    """Under `mode` the findings with `code` are exactly one finding of `expected` severity, or
    none when `expected` is None; its refs and role are as given."""
    found = [f for f in _findings_as(project, mode) if f.code == code]
    if expected is None:
        assert found == [], f"{code} must not be reported as {mode.value}"
        return
    [finding] = found
    assert finding.severity == expected, f"{code} as {mode.value}"
    if refs is not None:
        assert finding.refs == refs, f"{code} refs as {mode.value}"
    assert finding.role == role, f"{code} role as {mode.value}"


def _errors(findings: list[Finding]) -> set[str]:
    return {f.code for f in findings if f.severity == "error"}


def _calibrate(project: Project, agent: Actor, human: Actor, protocol_id: str) -> None:
    """Label every calibration work and decide it the same way in both passes (sensitivity 1)."""
    for work in calibration_items(project):
        label_calibration(project, human, work, "include", None, Channel.CLI)
        _decide(project, agent, work, "A", "calibration", "include", None, protocol_id)
        _decide(project, agent, work, "B", "calibration", "include", None, protocol_id)


def _screen_ordinary(
    project: Project,
    agent: Actor,
    protocol_id: str,
    *,
    pass_a: str = "include",
    pass_b: str = "include",
    b_sample_only: bool = False,
) -> None:
    """Decide the ordinary works in pass A, and in pass B: all of them, or its sample only."""
    sample = set(pass_b_sample(project) or ())
    for work in _ordinary(project):
        _decide(project, agent, work, "A", "screening", pass_a, _cite(pass_a), protocol_id)
        if b_sample_only and work not in sample:
            continue
        _decide(project, agent, work, "B", "screening", pass_b, _cite(pass_b), protocol_id)


def _partial_corpus(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
    """As `test_chase_service._corpus`, with a dual sample of 0.3: pass B screens a part of the
    ordinary works, so some works are decided by pass A alone (and some by both)."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.3, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    return protocol_id


def _cite(verdict: str) -> str | None:
    """The criterion an exclusion must name; no criterion for any other verdict."""
    return "EX01" if verdict == "exclude" else None


def _single_pass_works(project: Project) -> list[str]:
    """The ordinary works pass B did not screen: the ones pass A decides alone."""
    sample = set(pass_b_sample(project) or ())
    return sorted(work for work in _ordinary(project) if work not in sample)


def _unfound_seed(project: Project, agent: Actor, mock_sources: SourcesFor) -> str:
    """Add a positive seed whose lookup finds no work; returns its id."""
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 7", doi=SEED_DOI)
    result = add_seeds(project, agent, [spec], sources=mock_sources(openalex=[]))
    [outcome] = result.written
    return outcome.seed_id


def _dangling_merge_event(project: Project, human: Actor) -> str:
    """Record a reversal of a merge that was never recorded: an event whose ref names no row."""
    merge_id = f"mrg_{project.ids.ulid()}"
    project.record(
        [
            project.events.make(
                "dedup.reverted",
                DedupReverted(merge_id=merge_id, reason=REVERTED_MERGE_NOTE, manual=True),
                human,
                refs=(merge_id,),
            )
        ]
    )
    return merge_id


def _short_search_without_reason(project: Project, monkeypatch: pytest.MonkeyPatch) -> str:
    """Make the one search report retrieved fewer than it reported, with no reason.

    The adapters always explain a shortfall in their run note, so the unexplained case is built
    from the real report: the row keeps its query and its counts, and loses its reason."""
    real = search_report(project)
    [row] = real.rows
    short = row.model_copy(update={"reported": row.retrieved + 2, "shortfall_reason": None})
    patched: SearchReport = real.model_copy(update={"rows": [short]})
    monkeypatch.setattr(check_module, "search_report", lambda _project: patched)
    return row.query_id


def _decide_outcomes(
    project: Project, agent: Actor, human: Actor, protocol_id: str, excluded: set[str]
) -> None:
    """Decide the corpus in both passes: works in `excluded` exclude (EX01), the rest include.
    Calibration works take the human label instead, as in the real flow."""
    calibration = set(calibration_items(project))
    for work in sorted(w.id for w in list_works(project)):
        verdict = "exclude" if work in excluded else "include"
        criterion = "EX01" if verdict == "exclude" else None
        if work in calibration:
            label_calibration(project, human, work, verdict, criterion, Channel.CLI)
            continue
        _decide(project, agent, work, "A", "screening", verdict, criterion, protocol_id)
        _decide(project, agent, work, "B", "screening", verdict, criterion, protocol_id)


# --- One table-driven test per rule row ---


@_rows(("error", "error", "error"))
def test_broken_link(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    _corpus(project, agent, human, mock_sources)
    merge_id = _dangling_merge_event(project, human)

    _assert_row(project, "broken-link", mode, expected, refs=[merge_id])


@_rows(("error", "error", "error"))
def test_missing_provenance(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
    mode: RigorMode,
    expected: str,
) -> None:
    _corpus(project, agent, human, mock_sources)
    # An agent event whose skill and input blob are absent. The event model refuses to write one,
    # so the projection row is supplied directly to the rule.
    gap = ("ev_01JZ9Q3K5M7N8P0R2S4T6V8W0X", "agent", "claude-opus-5-5", None, None)
    monkeypatch.setattr(check_module, "_provenance_rows", lambda _project: [gap])

    _assert_row(project, "missing-provenance", mode, expected, refs=[gap[0]])


@_rows(("error", "error", "error"))
def test_shortfall_unexplained(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
    mode: RigorMode,
    expected: str,
) -> None:
    _corpus(project, agent, human, mock_sources)
    query_id = _short_search_without_reason(project, monkeypatch)

    _assert_row(project, "shortfall-unexplained", mode, expected, refs=[query_id])


@_rows(("warning", "error", "error"))
def test_seed_missing(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    _corpus(project, agent, human, mock_sources)
    seed_id = _unfound_seed(project, agent, mock_sources)

    _assert_row(project, "seed-missing", mode, expected, refs=[seed_id], role="development")


@_rows(("warning", "warning", "error"))
def test_seed_admission_pending(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    _corpus(project, agent, human, mock_sources)
    seed_id = _unfound_seed(project, agent, mock_sources)
    explain_seed_miss(
        project, human, seed_id, "not indexed by OpenAlex", ProvenanceMethod.SEED_ADMISSION
    )

    _assert_row(
        project, "seed-admission-pending", mode, expected, refs=[seed_id], role="development"
    )


@_rows((None, "error", "error"))
def test_protocol_not_ready(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str | None,
) -> None:
    protocol_id = _protocol(project, agent, human, mock_sources, ready=False)

    _assert_row(project, "protocol-not-ready", mode, expected, refs=[protocol_id])


@_rows((None, "error", "error"))
def test_press_missing(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str | None,
) -> None:
    protocol_id = _protocol(project, agent, human, mock_sources, ready=False)
    finding = PressFinding(
        element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor"
    )
    review_id = press_review(project, agent, protocol_id, (finding,))

    _assert_row(project, "press-missing", mode, expected, refs=[review_id])


@_rows(("warning", "warning", "warning"))
def test_screening_pending(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    _corpus(project, agent, human, mock_sources)

    # Nothing is decided or labelled: every work is pending.
    _assert_row(
        project, "screening-pending", mode, expected, refs=sorted(w.id for w in list_works(project))
    )


@_rows((None, "warning", "error"))
def test_single_pass(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str | None,
) -> None:
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    _calibrate(project, agent, human, protocol_id)
    _screen_ordinary(project, agent, protocol_id, b_sample_only=True)

    _assert_row(project, "single-pass", mode, expected, refs=_single_pass_works(project))


@_rows((None, "error", "error"))
def test_calibration_missing(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str | None,
) -> None:
    _corpus(project, agent, human, mock_sources)

    _assert_row(project, "calibration-missing", mode, expected)


@_rows(("warning", "warning", "warning"))
def test_kappa_below_floor(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    # Pass A includes everything and pass B excludes its sample, so every dual pair disagrees:
    # kappa is 0, below the protocol's floor of 0.7. The floor is advisory (not enforced).
    _screen_ordinary(project, agent, protocol_id, pass_b="exclude", b_sample_only=True)

    _assert_row(project, "kappa-below-floor", mode, expected)


@_rows((None, "warning", "error"))
def test_audit_missing(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str | None,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    _assert_row(project, "audit-missing", mode, expected)


@_rows((None, "warning", "error"))
def test_audit_error_high(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str | None,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id, verdict="exclude")
    # The human overturns every sampled exclusion: a false-exclusion rate far above the ceiling.
    sample = audit_sample(project, human, random_seed=7)
    for work in sample.work_ids:
        audit_record(project, human, sample.audit_id, work, "include", None, Channel.CLI)

    _assert_row(project, "audit-error-high", mode, expected, refs=[sample.audit_id])


@_rows((None, "warning", "error"))
def test_chase_missing(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str | None,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    _assert_row(project, "chase-missing", mode, expected)


@_rows(("warning", "warning", "warning"))
def test_profile_checklist(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    _corpus(project, agent, human, mock_sources)

    # Item 6 has a derived source (the screening passes); items 7, 8, 9 and 13a have none.
    uncovered = ["prisma-2020:7", "prisma-2020:8", "prisma-2020:9", "prisma-2020:13a"]
    _assert_row(project, "profile-checklist", mode, expected, refs=uncovered)


@_rows(("warning", "warning", "warning"))
def test_merge_verdict_conflict(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources, extra=_merge_items())
    dedup_run(project)
    [merge] = active_merges(project)
    _decide_outcomes(project, agent, human, protocol_id, excluded=set(merge.absorbed))

    _assert_row(
        project, "merge-verdict-conflict", mode, expected, refs=[merge.primary, *merge.absorbed]
    )


# --- Named tests ---


def test_broken_ref_reported(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    merge_id = _dangling_merge_event(project, human)

    for mode in MODES:
        _assert_row(project, "broken-link", mode, "error", refs=[merge_id])


def test_unexplained_shortfall_is_error(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _corpus(project, agent, human, mock_sources)
    query_id = _short_search_without_reason(project, monkeypatch)

    for mode in MODES:
        _assert_row(project, "shortfall-unexplained", mode, "error", refs=[query_id])


def test_seed_admission_pending_includes_hand_search(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    seed_id = _unfound_seed(project, agent, mock_sources)
    explain_seed_miss(
        project, human, seed_id, "only in a hand search", ProvenanceMethod.HAND_SEARCH
    )

    _assert_row(
        project,
        "seed-admission-pending",
        RigorMode.PILOT,
        "warning",
        refs=[seed_id],
        role="development",
    )
    _assert_row(
        project,
        "seed-admission-pending",
        RigorMode.SYSTEMATIC,
        "error",
        refs=[seed_id],
        role="development",
    )


def test_promote_pilot_to_systematic_lists_single_pass_and_missing_audit(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    _calibrate(project, agent, human, protocol_id)
    _screen_ordinary(project, agent, protocol_id, b_sample_only=True)
    single = _single_pass_works(project)

    report = check(project, promote_to=RigorMode.SYSTEMATIC)

    assert (report.mode, report.evaluated_as) == (RigorMode.PILOT, RigorMode.SYSTEMATIC)
    assert all(f.severity == "error" for f in report.findings)
    by_code = {f.code: f for f in report.findings}
    assert by_code["single-pass"].refs == single
    assert "audit-missing" in by_code
    assert not report.ok
    # Errors that the pilot already reports are not repeated (see the next test).
    assert {"calibration-missing", "protocol-not-ready", "press-missing"}.isdisjoint(by_code)


def test_promote_omits_errors_the_current_mode_already_reports(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    # Screened but not calibrated: calibration-missing is an error in the pilot already.
    _screen_ordinary(project, agent, protocol_id, b_sample_only=True)
    assert "calibration-missing" in _errors(check(project).findings)

    promoted = check(project, promote_to=RigorMode.SYSTEMATIC)

    assert "calibration-missing" not in {f.code for f in promoted.findings}
    assert "single-pass" in {f.code for f in promoted.findings}


def test_merge_verdict_conflict_absent_when_outcomes_agree(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources, extra=_merge_items())
    dedup_run(project)
    _decide_outcomes(project, agent, human, protocol_id, excluded=set())

    assert [
        f for f in _findings_as(project, RigorMode.PILOT) if f.code == "merge-verdict-conflict"
    ] == []


def test_clean_project_is_ok(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _calibrate(project, agent, human, protocol_id)
    _screen_ordinary(project, agent, protocol_id)

    report = check(project)

    assert report.ok
    assert _errors(report.findings) == set()
    assert {f.code for f in report.findings} <= {
        "single-pass",
        "audit-missing",
        "chase-missing",
        "profile-checklist",
    }
