"""Slice-1 acceptance: one test per criterion of docs/specs/slice-1.md (1-22).

A criterion that an earlier test already proves is proved here by calling that test's scenario
function with the same fixtures, in a project of its own (`_fresh`), so the claim stays in one
place. Where a criterion has parts no earlier test covers, the test adds them. Two criteria cannot
be proved offline from fixtures and are marked as gaps (12, 21); see their docstrings.
"""

import json
import shutil
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.chase import ChaseDirection
from factory.model.project import RigorMode
from factory.services.agreement import screen_agreement
from factory.services.chase import search_chase
from factory.services.check import check
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import prisma_flow, search_report
from factory.services.project import init_project
from factory.services.trace import trace
from factory.sources.registry import SourceFactory
from tests import (
    test_acceptance_acquisition as acquisition,
)
from tests import (
    test_acceptance_protocol as protocol,
)
from tests import (
    test_acceptance_rebuild as rebuild,
)
from tests import (
    test_acceptance_screening as screening,
)
from tests import (
    test_acceptance_supplementary as supplementary,
)
from tests import (
    test_agreement as agreement,
)
from tests import (
    test_audit as audit,
)
from tests import (
    test_calibration as calibration,
)
from tests import (
    test_check as checks,
)
from tests import (
    test_mcp_screening as mcp_screening,
)
from tests import (
    test_prisma as prisma,
)
from tests import (
    test_screening_next as screening_next,
)
from tests import (
    test_screening_record as screening_record,
)
from tests import (
    test_seed_split as seed_split,
)
from tests import (
    test_trace as traces,
)
from tests import (
    test_work as work,
)
from tests.helpers import SESSION, install_skill
from tests.test_chase_service import _citing, _corpus, _settle
from tests.test_cli import _cli_env, runner

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _fresh(
    root: Path, name: str, clock: FixedClock, mode: str = "pilot"
) -> tuple[Settings, Project]:
    """A project of its own, so that several scenarios can run in one test."""
    settings = Settings(root=root / name, user="obd")
    install_skill(settings, "rf-screen")
    install_skill(settings, "rf-search")
    return settings, init_project(settings, "demo", mode, session=SESSION, clock=clock)


def test_ac01_rebuild_determinism(tmp_path: Path, clock: FixedClock) -> None:
    """Rebuild determinism: deleting the index and running `factory rebuild` yields the same
    state hash."""
    rebuild.test_rebuild_after_deleting_index_yields_same_state_hash(tmp_path, clock)


def test_ac02_no_provenance_no_work() -> None:
    """No provenance, no work: constructing a `Work` without provenance fails."""
    work.test_work_without_provenance_cannot_exist()


def test_ac03_deduplication(
    tmp_path: Path, clock: FixedClock, agent: Actor, mock_sources: SourcesFor
) -> None:
    """Deduplication: the same paper returned by OpenAlex (DataCite DOI) and arXiv (bare ID)
    becomes one work with two provenance entries; the merge is listed and reversible."""
    _, one = _fresh(tmp_path, "one", clock, "exploratory")
    acquisition.test_datacite_doi_and_bare_arxiv_id_are_one_work(one, mock_sources, clock)
    _, merged = _fresh(tmp_path, "merged", clock, "exploratory")
    acquisition.test_published_and_preprint_merge_is_listed_and_reversible(
        merged, agent, mock_sources, clock
    )


def test_ac04_counts_and_shortfall_in_status(
    tmp_path: Path, clock: FixedClock, mock_sources: SourcesFor
) -> None:
    """Counts: for every search run, reported and retrieved counts are stored; a shortfall is
    visible in `status`."""
    settings, project = _fresh(tmp_path, "counts", clock, "exploratory")
    acquisition.test_every_run_stores_reported_and_retrieved_and_shortfall_is_visible(
        project, mock_sources
    )
    status = runner.invoke(app, ["status"], env=_cli_env(settings.root))
    assert status.exit_code == 0, status.stderr
    [line] = [row for row in status.stdout.splitlines() if row.startswith("shortfall:")]
    assert "2/5" in line and "skipped" in line


def test_ac05_validation(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Validation: `screen_record` rejects (and writes nothing for) a decision that cites a
    criterion absent from its protocol version, or an exclusion without criterion or rationale;
    valid items in the same batch are recorded."""
    for name, scenario in (
        ("unknown", screening_record.test_unknown_criterion_rejected_nothing_written),
        ("bare", screening_record.test_exclusion_without_criterion_or_rationale_rejected),
        ("batch", screening_record.test_batch_records_valid_items_only),
    ):
        _, project = _fresh(tmp_path, name, clock)
        scenario(project, agent, human, mock_sources)


@pytest.mark.anyio
async def test_ac06_amendments(
    tmp_path: Path,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """Amendments: loosening an exclusion criterion marks earlier exclusions citing it as stale;
    a prose-only change produces no new `P@`."""
    settings, project = _fresh(tmp_path, "amend", clock)
    await protocol.test_prose_only_change_mints_no_new_version_and_loosening_stales_exclusions(
        settings, project, clock, mock_sources, agent, human
    )


@pytest.mark.anyio
async def test_ac07_probe(
    tmp_path: Path, clock: FixedClock, agent: Actor, mock_sources: SourcesFor
) -> None:
    """Probe: `probe_run` reports recall on positive seeds and hits on negative seeds per query
    and source."""
    settings, project = _fresh(tmp_path, "probe", clock)
    await protocol.test_probe_run_reports_recall_and_negative_hits_per_query_and_source(
        settings, project, clock, mock_sources, agent
    )


@pytest.mark.anyio
async def test_ac08_dual_screening(
    tmp_path: Path,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """Dual screening: kappa is computed from passes A and B; disagreements are listed; neither
    pass can read the other's decisions through the tools."""
    settings, project = _fresh(tmp_path, "dual", clock)
    await screening.test_screening_agreement_and_audit_over_two_sessions(
        settings, project, clock, mock_sources, agent, human
    )
    settings, project = _fresh(tmp_path, "dual-tools", clock)
    await mcp_screening.test_pass_session_cannot_read_agreement_or_draw_an_audit(
        settings, project, clock, mock_sources, agent, human
    )


def test_ac09_trace(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Trace: `trace <decision>` returns the chain decision -> criterion -> protocol version ->
    question; `trace --forward Q@...` lists what the question produced."""
    for name, scenario in (
        ("back", traces.test_trace_decision_reaches_question),
        ("forward", traces.test_trace_forward_from_question_reaches_criteria),
    ):
        _, project = _fresh(tmp_path, name, clock)
        scenario(project, agent, human, mock_sources)


def test_ac10_prisma_numbers_are_derived(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """PRISMA: every PRISMA number is derived from events; none is entered by hand."""
    _, project = _fresh(tmp_path, "prisma", clock)
    prisma.test_prisma_identities_hold(project, agent, human, mock_sources)
    prisma.test_flow_refuses_inconsistent_counts()
    # No tool or command takes a count: the flow is a function of the project alone.
    _, project = _fresh(tmp_path, "prisma-derived", clock)
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    before = len(read_all(project.paths.events_dir, project.catalog))
    first = prisma_flow(project)
    assert prisma_flow(project) == first
    assert len(read_all(project.paths.events_dir, project.catalog)) == before  # nothing written


def test_ac11_agent_audit(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Agent audit: every agent decision event carries the model name and an `input_blob`
    containing the exact task content."""
    _, project = _fresh(tmp_path, "audit-trail", clock)
    screening_record.test_agent_decision_carries_model_skill_input_blob(
        project, agent, human, mock_sources
    )
    _, whole = _fresh(tmp_path, "whole", clock)
    protocol_id = _corpus(whole, agent, human, mock_sources)
    _settle(whole, agent, human, protocol_id)
    decisions = [
        e
        for e in read_all(whole.paths.events_dir, whole.catalog)
        if e.type == "screening.decision_recorded"
    ]
    assert decisions
    assert all(e.actor.model and e.input_blob for e in decisions)
    assert [f for f in check(whole).findings if f.code == "missing-provenance"] == []


def test_ac12_end_to_end_fixture_run_is_reproducible(
    tmp_path: Path,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """End-to-end: the pilot project runs through steps 1-11 with <= 300 retrieved records; the
    run is reproducible from the committed events.

    GAP: the live pilot (real OpenAlex and arXiv, the researcher's seeds) cannot run offline. This
    test is its fixture-scale equivalent: steps 1-11 on mocked sources with 12 records, then the
    index is deleted and every report is derived again from the events alone."""
    _, project = _fresh(tmp_path, "e2e", clock)
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    dedup_run(project)
    screen_agreement(project, agent)
    search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD, ChaseDirection.FORWARD],
        sources=mock_sources(openalex=[_citing(n) for n in range(900, 903)]),
    )
    dedup_run(project)

    def reports() -> tuple[str, str, str, str]:
        return (
            prisma_flow(project).model_dump_json(),
            search_report(project).model_dump_json(),
            render_methods(methods_report(project)),
            check(project).model_dump_json(),
        )

    before, digest = reports(), project.index.state_hash()
    assert prisma_flow(project).screened <= 300
    shutil.rmtree(project.paths.dir / ".index")
    clock.advance(timedelta(seconds=1))
    assert project.index.rebuild() == digest
    assert reports() == before
    [round_] = [r for r in search_report(project).rows if r.purpose.value == "chase"][:1]
    assert trace(project, round_.query_id).kind == "query"


@pytest.mark.anyio
async def test_ac13_parentage(tmp_path: Path, clock: FixedClock, agent: Actor) -> None:
    """Parentage: a criterion without a parent question element or non-goal is rejected
    (pilot/systematic)."""
    settings, project = _fresh(tmp_path, "parent", clock)
    await protocol.test_parentless_criterion_is_rejected_and_nothing_written(
        settings, project, clock, agent
    )


def test_ac14_no_truncation(
    tmp_path: Path,
    clock: FixedClock,
    mock_sources: SourcesFor,
    http_log: list[httpx.Request],
) -> None:
    """No truncation: source adapters never request relevance-sorted subsets; a test fails if
    retrieved < reported without a recorded reason."""
    _, sorting = _fresh(tmp_path, "sorting", clock, "exploratory")
    acquisition.test_adapters_never_request_relevance_sorting(sorting, mock_sources, http_log)
    _, counts = _fresh(tmp_path, "counts", clock, "exploratory")
    acquisition.test_every_run_stores_reported_and_retrieved_and_shortfall_is_visible(
        counts, mock_sources
    )
    # The reason is what makes a shortfall acceptable: without one, `check` fails.
    assert [f.code for f in check(counts).findings if f.severity == "error"] == []
    assert search_report(counts).rows[0].shortfall_reason is not None


def test_ac15_seed_check(
    tmp_path: Path,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed check: after search, every positive seed is retrieved or carries an explanation and
    admission route; otherwise `check` fails."""
    settings, missing = _fresh(tmp_path, "missing", clock)
    _, held, _number = supplementary._corpus_missing_held_out(missing, agent, human, mock_sources)
    report = check(missing)
    [gap] = [f for f in report.findings if f.code == "seed-missing"]
    assert gap.severity == "error" and held in gap.refs and not report.ok
    failed = runner.invoke(app, ["check"], env=_cli_env(settings.root))
    assert failed.exit_code == 1 and "seed-missing" in failed.stdout

    settings, project = _fresh(tmp_path, "admitted", clock)
    supplementary.test_seed_check_passes_after_admission(
        project, agent, human, mock_sources, settings, monkeypatch
    )


def test_ac16_quotes(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Quotes: a screening rationale whose quote is not verbatim in the title/abstract is
    rejected."""
    _, project = _fresh(tmp_path, "quote", clock)
    screening_record.test_quote_not_in_record_rejected(project, agent, human, mock_sources)


def test_ac17_independence_recorded(
    tmp_path: Path,
    clock: FixedClock,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """Independence recorded: each pass records model, framing and criterion order;
    `screen_agreement` refuses to compute kappa for two passes with identical configuration."""
    _, framing = _fresh(tmp_path, "framing", clock)
    screening_next.test_pass_b_reverses_criterion_order_and_uses_exclusion_framing(
        framing, agent, agent_other, human, mock_sources
    )
    _, model = _fresh(tmp_path, "model", clock)
    agreement.test_agreement_refused_when_passes_share_model(
        model, agent, agent_other, human, mock_sources
    )
    _, session = _fresh(tmp_path, "session", clock)
    agreement.test_agreement_refused_when_passes_share_session(session, agent, human, mock_sources)


def test_ac18_calibration_and_audit(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Calibration and audit: screening is blocked until the calibration set is labelled;
    `audit_sample` draws >= 2% (min. 50) of agreed decisions, 3:1 towards exclusions; error rates
    are reported."""
    for name, scenario in (
        ("gate", screening_next.test_calibration_not_drawn_blocks_screening),
        ("sample", audit.test_audit_draws_minimum_fifty_three_to_one),
        ("rates", audit.test_error_rates_reported_and_ceiling_flagged),
    ):
        _, project = _fresh(tmp_path, name, clock)
        scenario(project, agent, human, mock_sources)


@pytest.mark.anyio
async def test_ac19_deviations_and_amendments_in_the_methods_statement(
    tmp_path: Path,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """Deviations vs. amendments are stored separately and both appear in the methods
    statement."""
    settings, project = _fresh(tmp_path, "deviations", clock)
    await protocol.test_amendments_and_deviations_are_stored_separately(
        settings, project, clock, mock_sources, agent, human
    )
    report = methods_report(project)
    text = render_methods(report)
    assert report.amendments >= 1 and report.deviations >= 1
    assert f"Protocol amendments recorded: {report.amendments}." in text
    assert f"Deviations recorded: {report.deviations}." in text


def test_ac20_promotion(
    tmp_path: Path, clock: FixedClock, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Promotion: `check --promote-to systematic` on a pilot project lists the missing items
    (e.g. single-pass records, missing audit)."""
    settings, project = _fresh(tmp_path, "promote", clock)
    checks.test_promote_pilot_to_systematic_lists_single_pass_and_missing_audit(
        project, agent, human, mock_sources
    )
    result = runner.invoke(
        app, ["check", "--promote-to", "systematic"], env=_cli_env(settings.root)
    )
    assert result.exit_code == 1
    codes = {f.code for f in check(project, promote_to=RigorMode.SYSTEMATIC).findings}
    assert {"single-pass", "audit-missing"} <= codes
    assert all(code in result.stdout for code in ("single-pass", "audit-missing"))


@pytest.mark.skip(
    reason="GAP: mypy --strict, ruff and the 90% coverage gate are enforced by the verification "
    "commands (uv run mypy --strict src; ruff check; pytest --cov-fail-under=90), not by a "
    "pytest test; running them from inside the suite would recurse."
)
def test_ac21_quality() -> None:
    """Quality: `mypy --strict` and ruff pass; coverage >= 90% for `services/` and `model/`."""


@pytest.mark.anyio
async def test_ac22_seed_hold_out(
    tmp_path: Path,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """Seed hold-out: the split is drawn by the platform with a recorded random seed;
    `probe_run`, worked-example selection and agent-facing tools never return held-out seeds;
    `report_methods` reports held-out and development recall separately."""
    _, drawn = _fresh(tmp_path, "split", clock)
    seed_split.test_split_records_seed_and_procedure(drawn, agent, mock_sources)
    _, examples = _fresh(tmp_path, "examples", clock)
    calibration.test_calibration_set_includes_dev_seeds_excludes_held_out_and_examples(
        examples, agent, human, mock_sources
    )
    settings, tools = _fresh(tmp_path, "tools", clock)
    await protocol.test_agent_tools_never_reveal_held_out_seeds(
        settings, tools, clock, mock_sources, agent, human
    )
    _, methods = _fresh(tmp_path, "methods", clock)
    protocol_id = _corpus(methods, agent, human, mock_sources)
    _settle(methods, agent, human, protocol_id)
    report: dict[str, Any] = json.loads(methods_report(methods).model_dump_json())
    assert report["recall_held_out"] is not None and report["recall_development"] is not None
    text = render_methods(methods_report(methods))
    assert "Held-out seed recall:" in text and "Development seed recall:" in text
