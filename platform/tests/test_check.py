"""`check` (plan 5b, task 4): one table-driven test per rule row, the named gaps, and promotion.

Each row's severity is asserted per mode through `_findings_as`, which gives the findings a mode
emits over the same events. Each assertion names the code, the severity and the refs.
"""

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.chase import ChaseDirection
from factory.model.dedup import DedupReverted
from factory.model.fulltext import Route
from factory.model.project import RigorMode
from factory.model.protocol import PressElement, PressFinding
from factory.model.screening import (
    CalibrationLabelled,
    Channel,
    DisagreementResolved,
    PassLabel,
)
from factory.model.search import (
    QueryKind,
    QuerySpec,
    RunStatus,
    SearchRunFinished,
    SearchRunStarted,
)
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services import check as check_module
from factory.services.agreement import Outcome, final_outcomes
from factory.services.audit import audit_record, audit_sample
from factory.services.calibration import calibration_items, label_calibration
from factory.services.chase import search_chase
from factory.services.check import Finding, _findings_as, check
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run
from factory.services.fulltext import fetch_fulltext, restore_document
from factory.services.prisma import search_report
from factory.services.protocol import press_review
from factory.services.screening import open_pass, pass_b_sample
from factory.services.search import list_works, register_query, run_query
from factory.services.seeds import (
    SeedRole,
    add_seeds,
    all_seeds,
    explain_seed_miss,
    split_is_drawn,
)
from factory.sources.registry import SourceFactory
from tests import helpers
from tests.helpers import _protocol, _seed_item, _setup
from tests.test_chase_service import _citing, _corpus, _ordinary, _settle
from tests.test_fulltext_service import _include_all, always, retrieved, routes_for
from tests.test_prisma import _merge_items
from tests.test_screening_next import _decide, _draw

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"

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


def _planned_query(project: Project, human: Actor, mock_sources: SourcesFor) -> str:
    """Register the protocol's planned search ("attention") and return its query id."""
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    return register_query(project, human, spec, sources=mock_sources(openalex=[]))


def _record_run(
    project: Project, query_id: str, *, reported: int, retrieved: int, note: str | None
) -> None:
    """Record one finished search run as the search service writes it: a started event, then
    its finish. The note is written as given, None included: the event model does not require
    one, and an adapter that gives none is the case under test."""
    run_id = project.ids.new("run")
    system = project.system_actor()
    project.record(
        [
            project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=run_id, query_id=query_id),
                system,
                refs=(run_id,),
            )
        ]
    )
    project.record(
        [
            project.events.make(
                "search.run_finished",
                SearchRunFinished(
                    run_id=run_id,
                    status=RunStatus.COMPLETE,
                    reported_count=reported,
                    retrieved_count=retrieved,
                    note=note,
                ),
                system,
                refs=(run_id,),
            )
        ]
    )


def _shortfall_query(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, *, note: str
) -> str:
    """A ready protocol, and one search that retrieved 3 of the 5 it reported, with `note`."""
    _protocol(project, agent, human, mock_sources)
    query_id = _planned_query(project, human, mock_sources)
    _record_run(project, query_id, reported=5, retrieved=3, note=note)
    return query_id


def _clear_shortfall_reason(project: Project, monkeypatch: pytest.MonkeyPatch) -> str:
    """Patch the search report so its one row carries no shortfall reason; returns its query id.

    The event model refuses an unexplained shortfall (R-23: a run that is not fully explained
    needs a note; see `test_run_without_note_is_refused_by_the_event_model`), so no event can
    produce this row. The rule is therefore tested on the report row it would read."""
    real = search_report(project)
    [row] = real.rows
    patched = real.model_copy(update={"rows": [row.model_copy(update={"shortfall_reason": None})]})
    monkeypatch.setattr(check_module, "search_report", lambda _project: patched)
    return row.query_id


def _enforce_kappa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the κ floor of protocols recorded from now on enforced. `_protocol` builds its spec
    with `helpers.pilot_protocol_spec`, which is wrapped here; nothing else changes."""
    original = helpers.pilot_protocol_spec

    def enforced(*args: Any, **kwargs: Any) -> Any:
        spec = original(*args, **kwargs)
        plan = spec.screening.model_copy(update={"kappa_enforced": True})
        return spec.model_copy(update={"screening": plan})

    monkeypatch.setattr(helpers, "pilot_protocol_spec", enforced)


def _seed_role_corpus(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> dict[SeedRole, str]:
    """A ready pilot protocol whose probe draws the split over the three positives, then a corpus
    that omits the works of one held-out and one development positive. Returns those two seed
    ids by role. The roles are read from `all_seeds`, not assumed."""
    _protocol(project, agent, human, mock_sources)
    positives = {s.seed_id: s.role for s in all_seeds(project) if s.kind is SeedKind.POSITIVE}
    omitted = {
        SeedRole.HELD_OUT: next(s for s, r in positives.items() if r is SeedRole.HELD_OUT),
        SeedRole.DEVELOPMENT: next(s for s, r in positives.items() if r is SeedRole.DEVELOPMENT),
    }
    kept = [int(seed_id[-2:]) for seed_id in positives if seed_id not in omitted.values()]
    items = [_seed_item(n) for n in kept]
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    query_id = register_query(project, human, spec, sources=mock_sources(openalex=items))
    run_query(project, query_id, sources=mock_sources(openalex=items))
    return omitted


def _decide_outcomes(
    project: Project,
    agent: Actor,
    human: Actor,
    protocol_id: str,
    excluded: set[str],
    *,
    skip: frozenset[str] = frozenset(),
) -> None:
    """Decide the corpus in both passes: works in `excluded` exclude (EX01), the rest include.
    Calibration works take the human label instead, as in the real flow. Works in `skip` are
    left undecided."""
    calibration = set(calibration_items(project))
    for work in sorted(w.id for w in list_works(project)):
        if work in skip:
            continue
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
    """Tested through a patched `_provenance_rows`. Not through the log: `Event` refuses to be
    built without provenance, and the reader raises `EventLogCorruptError` on a hand-edited line
    that lacks it, so no event file can carry such a gap."""
    _corpus(project, agent, human, mock_sources)
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
    _shortfall_query(project, agent, human, mock_sources, note="2 records skipped by the source")
    query_id = _clear_shortfall_reason(project, monkeypatch)

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

    # Items 6 (information sources), 7 (search strategy) and 8 (selection process) have a derived
    # source; 9 (data collection process) and 13a (synthesis eligibility) have none in slice 1.
    uncovered = ["prisma-2020:9", "prisma-2020:13a"]
    _assert_row(project, "profile-checklist", mode, expected, refs=uncovered)


def test_profile_checklist_lists_unsearched_items_and_uses_prisma_2020_wording(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Before any search, items 6 and 7 are uncovered too; the wording is PRISMA 2020's."""
    _protocol(project, agent, human, mock_sources)

    [finding] = [f for f in check(project).findings if f.code == "profile-checklist"]

    assert finding.refs == [
        "prisma-2020:6",
        "prisma-2020:7",
        "prisma-2020:9",
        "prisma-2020:13a",
    ]
    assert "6 (information sources)" in finding.message
    assert "7 (search strategy)" in finding.message
    assert "9 (data collection process)" in finding.message
    assert "13a (synthesis eligibility)" in finding.message
    assert [(i.number, i.text) for i in check_module._PRISMA_CHECKLIST] == [
        ("6", "information sources"),
        ("7", "search strategy"),
        ("8", "selection process"),
        ("9", "data collection process"),
        ("13a", "synthesis eligibility"),
    ]


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


def _inject(project: Project, human: Actor, name: str, payload: Any) -> None:
    """Record an event the services would refuse, as `_dangling_merge_event` does."""
    project.record([project.events.make(name, payload, human)])


def test_calibration_label_citing_an_undefined_criterion_is_a_broken_link(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """A criterion cited by a label but defined by no protocol version is a broken link."""
    protocol_id = _corpus(project, agent, human, mock_sources)
    work = calibration_items(project)[0]
    cited = f"{protocol_id}:EX99"
    assert [f for f in check(project).findings if f.code == "broken-link"] == []
    _inject(
        project,
        human,
        "calibration.labelled",
        CalibrationLabelled(work_id=work, verdict="exclude", criterion=cited, channel=Channel.CLI),
    )

    [finding] = [f for f in check(project).findings if f.code == "broken-link"]

    assert finding.severity == "error" and finding.refs == [cited]


def test_resolution_citing_an_unknown_protocol_version_is_a_broken_link(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    work = _ordinary(project)[0]
    cited = "P@00000000:EX01"
    assert cited.split(":")[0] != protocol_id
    _inject(
        project,
        human,
        "screening.disagreement_resolved",
        DisagreementResolved(
            work_id=work, verdict="exclude", criterion=cited, reason="r", channel=Channel.CLI
        ),
    )

    [finding] = [f for f in check(project).findings if f.code == "broken-link"]

    assert finding.refs == [cited]


def test_defined_criteria_cited_by_decisions_and_labels_are_not_broken(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id, verdict="exclude")

    assert [f for f in check(project).findings if f.code == "broken-link"] == []


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
    _shortfall_query(project, agent, human, mock_sources, note="2 records skipped by the source")
    query_id = _clear_shortfall_reason(project, monkeypatch)

    for mode in MODES:
        _assert_row(project, "shortfall-unexplained", mode, "error", refs=[query_id])


def test_run_without_note_is_refused_by_the_event_model(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """R-23 at the event level: a finished run short of its reported count needs a note."""
    with pytest.raises(ValidationError):
        SearchRunFinished(
            run_id=f"run_{project.ids.ulid()}",
            status=RunStatus.COMPLETE,
            reported_count=5,
            retrieved_count=3,
            note=None,
        )


def test_explained_shortfall_gives_no_finding(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    note = "2 records skipped by the source"
    _shortfall_query(project, agent, human, mock_sources, note=note)

    for mode in MODES:
        _assert_row(project, "shortfall-unexplained", mode, None)


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
        "fulltext-unsought",
        "snowball-plan-missing",  # a pilot warning (slice 3a ruling 19): no snowball_plan
    }


# --- The enforced κ floor (R-36: advisory in pilot, enforced in systematic) ---


def test_kappa_enforced_below_floor_is_error_in_every_mode(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enforce_kappa(monkeypatch)
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    _screen_ordinary(project, agent, protocol_id, pass_b="exclude", b_sample_only=True)

    for mode in MODES:
        _assert_row(project, "kappa-below-floor", mode, "error", refs=[])


def test_kappa_enforced_gap_is_not_repeated_on_promotion(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enforce_kappa(monkeypatch)
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    _screen_ordinary(project, agent, protocol_id, pass_b="exclude", b_sample_only=True)
    assert "kappa-below-floor" in _errors(check(project).findings)

    promoted = check(project, promote_to=RigorMode.SYSTEMATIC)

    assert "kappa-below-floor" not in {f.code for f in promoted.findings}


# --- Seed roles (controller Ruling G) ---


def _seed_missing_by_role(project: Project, mode: RigorMode) -> dict[str | None, Finding]:
    return {f.role: f for f in _findings_as(project, mode) if f.code == "seed-missing"}


def test_missing_held_out_positive_has_role_held_out(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    omitted = _seed_role_corpus(project, agent, human, mock_sources)

    found = _seed_missing_by_role(project, RigorMode.PILOT)

    assert found["held-out"].refs == [omitted[SeedRole.HELD_OUT]]
    assert found["held-out"].severity == "error"


def test_missing_development_positive_has_role_development(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    omitted = _seed_role_corpus(project, agent, human, mock_sources)

    found = _seed_missing_by_role(project, RigorMode.PILOT)

    assert found["development"].refs == [omitted[SeedRole.DEVELOPMENT]]
    assert found["development"].severity == "error"


def test_missing_unsplit_positive_has_role_unsplit(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Before the split is drawn a positive is `unsplit`: it may still become held-out."""
    seed_id = _unfound_seed(project, agent, mock_sources)
    assert not split_is_drawn(project)
    assert {r.seed_id: r.role for r in all_seeds(project)}[seed_id] is SeedRole.UNSPLIT

    _assert_row(project, "seed-missing", RigorMode.PILOT, "error", refs=[seed_id], role="unsplit")


def test_late_positive_folds_into_development(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """A positive added after the split is `late`, and counts as development (recall, role)."""
    _corpus(project, agent, human, mock_sources)
    seed_id = _unfound_seed(project, agent, mock_sources)
    assert {r.seed_id: r.role for r in all_seeds(project)}[seed_id] is SeedRole.LATE

    _assert_row(
        project, "seed-missing", RigorMode.PILOT, "error", refs=[seed_id], role="development"
    )


# --- Chase and merges: the proxies and their edges ---


def test_chase_round_after_decisions_clears_chase_missing(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    dedup_run(project)
    assert [f for f in _findings_as(project, RigorMode.PILOT) if f.code == "chase-missing"]

    citing = [_citing(n) for n in range(900, 910)]
    search_chase(project, human, [ChaseDirection.BACKWARD], sources=mock_sources(openalex=citing))

    assert [f for f in _findings_as(project, RigorMode.PILOT) if f.code == "chase-missing"] == []


def test_pending_record_in_a_merge_is_not_a_conflict(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources, extra=_merge_items())
    dedup_run(project)
    [merge] = active_merges(project)
    absorbed = frozenset(merge.absorbed)
    _decide_outcomes(project, agent, human, protocol_id, excluded=set(), skip=absorbed)

    outcomes = final_outcomes(project)
    assert all(outcomes[work] is Outcome.PENDING for work in absorbed)
    assert outcomes[merge.primary] is Outcome.INCLUDED
    assert [
        f for f in _findings_as(project, RigorMode.PILOT) if f.code == "merge-verdict-conflict"
    ] == []


# --- The agent view: seed findings by role and count (R-20) ---


def _seed_finding(code: str, role: str, *refs: str) -> Finding:
    return Finding(code=code, severity="error", refs=list(refs), message="m", role=role)


def test_agent_view_counts_seeds_by_role_and_names_none() -> None:
    report = check_module.CheckReport(
        mode=RigorMode.PILOT,
        evaluated_as=RigorMode.PILOT,
        findings=[
            _seed_finding("seed-missing", "held-out", "SEED01", "SEED02"),
            _seed_finding("seed-missing", "development", "SEED03"),
            _seed_finding("seed-missing", "unsplit", "SEED04"),
            _seed_finding("seed-admission-pending", "held-out", "SEED05"),
            Finding(code="broken-link", severity="error", refs=["SEED09", "rf:a"], message="x"),
        ],
    )

    view = check_module.agent_view(report)

    by_key = {(f.code, f.role): f for f in view.findings}
    assert by_key[("seed-missing", "held-out")].message == "2 held-out positive seed(s) missing"
    assert by_key[("seed-missing", "development")].message.startswith("1 development ")
    # An unsplit positive may still become held-out: it is never counted as development.
    assert ("seed-missing", "unsplit") not in by_key
    assert by_key[("seed-missing", "held-out-possible")].message.startswith("1 held-out-possible")
    assert by_key[("seed-admission-pending", "held-out")].message.startswith("1 held-out ")
    assert [f.refs for f in view.findings if f.role is not None] == [[], [], [], []]
    [broken] = [f for f in view.findings if f.code == "broken-link"]
    assert broken.refs == ["rf:a"]
    assert not any("SEED0" in f.model_dump_json() for f in view.findings)
    assert view.mode is report.mode and view.evaluated_as is report.evaluated_as


# --- Full text (plan 2A, task 11): library findings and unsought promoted works ---


def _fetched_corpus(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    """A corpus with every ordinary work included, and its promoted works sorted by id."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)
    return sorted(w for w, o in final_outcomes(project).items() if o is Outcome.INCLUDED)


def _fetch_first(project: Project, promoted: list[str], content: bytes) -> tuple[str, str, str]:
    """Fetch the first promoted work from arXiv HTML. Returns (work, document, raw_hash)."""
    work = promoted[0]
    summary = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, content))),
        work_ids=[work],
    )
    document = summary.works[0].documents[0]
    [added] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "fulltext.document_added" and e.payload["document_id"] == document
    ]
    return work, document, str(added.payload["raw_hash"])


@_rows(("warning", "warning", "warning"))
def test_check_reports_missing_library_entry(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    promoted = _fetched_corpus(project, agent, human, mock_sources)
    work, document, raw_hash = _fetch_first(project, promoted, b"full text")
    project.library.path(raw_hash).unlink()

    _assert_row(project, "library-missing", mode, expected, refs=[document, work])
    _assert_row(project, "library-corrupt", mode, None)


def test_check_clean_after_restore(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    promoted = _fetched_corpus(project, agent, human, mock_sources)
    _, document, raw_hash = _fetch_first(project, promoted, b"full text")
    project.library.path(raw_hash).unlink()
    stub = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"full text")))
    assert restore_document(project, document, routes=stub) == "restored"

    for mode in MODES:
        _assert_row(project, "library-missing", mode, None)


@_rows(("error", "error", "error"))
def test_check_corrupt_entry_is_error(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    promoted = _fetched_corpus(project, agent, human, mock_sources)
    work, document, raw_hash = _fetch_first(project, promoted, b"full text")
    project.library.path(raw_hash).write_bytes(b"tampered")

    _assert_row(project, "library-corrupt", mode, expected, refs=[document, work])
    _assert_row(project, "library-missing", mode, None)
    assert not check(project).ok


@_rows(("warning", "warning", "warning"))
def test_check_source_changed_is_warning(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    promoted = _fetched_corpus(project, agent, human, mock_sources)
    work, document, _ = _fetch_first(project, promoted, b"first bytes")
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"second bytes"))),
        work_ids=[work],
        refresh=True,
    )

    _assert_row(project, "source-changed", mode, expected, refs=[document, work])


@_rows(("warning", "warning", "warning"))
def test_check_unsought_promoted_work(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    mode: RigorMode,
    expected: str,
) -> None:
    promoted = _fetched_corpus(project, agent, human, mock_sources)
    _fetch_first(project, promoted, b"full text")

    _assert_row(project, "fulltext-unsought", mode, expected, refs=promoted[1:])


def test_clean_project_without_fulltext_is_unsought_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    promoted = _fetched_corpus(project, agent, human, mock_sources)

    for mode in MODES:
        _assert_row(project, "fulltext-unsought", mode, "warning", refs=promoted)
