"""Slice-1 acceptance for the supplementary search (flow 10; criteria 4, 14, 15, 22).

One pilot project. The corpus is searched, deduplicated, calibrated and screened in both passes;
the platform then chases citations from the included works, the new works are merged where they
duplicate and screened, and agreement is read again. Nothing touches the network: OpenAlex answers
from a mock transport.
"""

import json
from collections.abc import Callable, Mapping

import pytest

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection
from factory.model.screening import PassLabel
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.agreement import Outcome, final_outcomes, screen_agreement
from factory.services.calibration import calibration_items
from factory.services.chase import chase_rounds, search_chase
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.protocol import record_deviation
from factory.services.screening import open_pass, pass_b_sample, screen_next
from factory.services.search import get_work, list_works, register_query, run_query
from factory.services.seeds import (
    SeedRole,
    add_seeds,
    all_seeds,
    explain_seed_miss,
    seed_check,
)
from factory.services.tasks import complete_task
from factory.sources.base import SourceError
from factory.sources.registry import SourceFactory
from tests.helpers import (
    FakeSource,
    _leaks,
    _negative_item,
    _positive_item,
    _protocol,
    _random_item,
    _seed_item,
    install_skill,
    open_session,
    openalex_item,
)
from tests.test_chase_service import _citing, _corpus, _of_type, _ordinary, _settle
from tests.test_cli import _cli_env, runner
from tests.test_screening_next import _decide, _draw

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

ARGS = {"role": "searcher", "model": "claude-opus-5-5", "skill": "rf-search"}
SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _screen_new(project: Project, agent: Actor, label: PassLabel, protocol_id: str) -> list[str]:
    """Serve and decide (include) every batch pass `label` offers; return the works screened."""
    screened: list[str] = []
    calibration = set(calibration_items(project))
    for _ in range(30):
        served = screen_next(project, agent, label)
        if served.batch is None:
            break
        for record in served.batch.records:
            work = str(record["work_id"])
            _decide(
                project,
                agent,
                work,
                label.value,
                served.batch.phase.value,
                "include",
                None,
                protocol_id,
            )
            if work not in calibration:
                screened.append(work)
        complete_task(project, agent, served.batch.task_id)
    return screened


def test_supplementary_flow_end_to_end(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    dedup_run(project)
    screen_agreement(project, agent)
    before = {work.id for work in list_works(project)}

    new_items = [_citing(n) for n in range(900, 910)]
    summary = search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD, ChaseDirection.FORWARD],
        sources=mock_sources(openalex=new_items),
    )
    dedup_run(project)

    new = {work.id for work in list_works(project)} - before
    assert summary.new_works == len(new) == 10
    for work in list_works(project):
        if work.id in new:
            assert {p.method for p in work.provenance} == {ProvenanceMethod.CITATION_CHASE}
    # R-03, R-25: each chase query is its own run with archived pages.
    [round_] = chase_rounds(project)
    assert len(summary.runs) == len(round_.queries) == 2
    assert len({run.run_id for run in summary.runs}) == 2
    archived = _of_type(project, "search.page_archived")
    for run in summary.runs:
        assert [e for e in archived if e.payload["run_id"] == run.run_id]

    screened_a = _screen_new(project, agent, PassLabel.A, protocol_id)
    assert set(screened_a) == new
    pass_b = agent_other.model_copy(update={"model": "claude-haiku-5-5"})
    screened_b = _screen_new(project, pass_b, PassLabel.B, protocol_id)
    sample = set(pass_b_sample(project) or ())
    assert set(screened_b) == new & sample and screened_b
    assert set(screened_b) <= new

    agreement = screen_agreement(project, agent)
    assert agreement.disagreements == []
    outcomes = final_outcomes(project)
    assert {outcomes.get(work) for work in new} == {Outcome.INCLUDED}


def test_chased_duplicate_is_merged_not_rescreened(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    ordinary = _ordinary(project)
    [first] = [w for w in list_works(project) if w.id == ordinary[0]]
    duplicate = openalex_item(
        title=first.title,
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id="W9999",
        doi=first.identifiers.doi,
    )
    before = len(list_works(project))
    search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD],
        sources=mock_sources(openalex=[duplicate, _citing(901)]),
    )
    summary = dedup_run(project)

    assert summary.works == before + 1  # one record collapsed into its corpus work
    assert summary.records == summary.works + 1
    # The duplicate has no work of its own (its OpenAlex id is on no work); the corpus work
    # gained a citation-chase provenance row.
    holders = [w.id for w in list_works(project) if w.identifiers.openalex == "W9999"]
    assert holders == []
    first_after = get_work(project, first.id)
    assert first_after is not None
    assert ProvenanceMethod.CITATION_CHASE in {p.method for p in first_after.provenance}
    chased = [p for p in first_after.provenance if p.method is ProvenanceMethod.CITATION_CHASE]
    assert chased and {p.raw_ref for p in chased} == {"W9999"}
    assert not any(p.method is ProvenanceMethod.CITATION_CHASE for p in first.provenance)
    served = _screen_new(project, agent, PassLabel.A, protocol_id)
    assert len(served) == 1  # the new work only; the merged duplicate is not queued


def _held_out_tokens(project: Project) -> set[str]:
    """The seed id and every stated or normalised identifier of each held-out seed."""
    tokens: set[str] = set()
    for seed in all_seeds(project):
        if seed.role is not SeedRole.HELD_OUT:
            continue
        stated = SeedSpec(kind=seed.kind, cite=seed.cite, doi=seed.doi, arxiv=seed.arxiv)
        tokens.add(seed.seed_id)
        tokens.update(stated.identity_keys().values())
        tokens.update(v for v in (seed.doi, seed.arxiv, seed.openalex) if v)
    return tokens


def _corpus_missing_held_out(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[str, str, int]:
    """A pilot corpus whose base search lacks one held-out positive seed, resolved by lookup.

    Returns the protocol id, the held-out seed's id and its paper number. The seed's work is
    stored by the seed lookup only (a probe), so it is not in the corpus: `seed_check` says
    `missing` until something else retrieves it."""
    protocol_id = _protocol(project, agent, human, mock_sources, dual_sample=0.5)
    [held] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    number = int(held.cite.split()[-1])
    items = [_positive_item(n) for n in (1, 2, 3) if n != number]
    items += [_negative_item(k) for k in range(1, 4)]
    items += [_random_item(k) for k in range(1, 5)]
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    sources = mock_sources(openalex=items)
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    return protocol_id, held.seed_id, number


@pytest.mark.anyio
async def test_held_out_seed_found_by_chase_is_not_named(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    install_skill(settings, "rf-search")
    protocol_id, held, number = _corpus_missing_held_out(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    tokens = _held_out_tokens(project)
    assert {held, f"10.1000/p{number}"} <= tokens
    assert {c.seed_id: c.status for c in seed_check(project)}[held] == "missing"

    # A first chase fails at the source, and the source's error text names the held-out seed.
    # Contrived defence in depth: ChaseSummary carries no identifiers beyond rf: work ids. arXiv
    # forms are covered by the shared token tests (test_mcp_screening, test_acceptance_screening).
    doi = f"10.1000/p{number}"
    leaky = SourceError(f"HTTP 404 for doi:{doi} {held}")
    failing = FakeSource([[]], raise_at=0, raise_error=leaky)
    broken = {"openalex": SourceFactory(frozenset({QueryKind.FILTER}), lambda _s, _c: failing)}
    async with open_session(settings, clock, broken) as session:
        failed = await session.call("search_chase", project="demo", directions=["backward"], **ARGS)
    assert failed["ok"] is True
    raw_notes = " ".join(str(run["note"]) for run in failed["data"]["runs"])
    assert "HTTP 404" in raw_notes  # the note is passed on; only the identifiers are withheld
    assert {held, doi} <= tokens
    finished = _of_type(project, "search.run_finished")
    stored = " ".join(str(e.payload.get("note") or "") for e in finished)
    assert set(_leaks(stored, {held, doi})) == {held, doi}  # both are in the unscrubbed note
    assert _leaks(json.dumps(failed), {held, doi}) == []

    # The second chase returns the held-out seed's own record, with its DOI.
    page = [_seed_item(number), _citing(900)]
    async with open_session(settings, clock, dict(mock_sources(openalex=page))) as session:
        body = await session.call(
            "search_chase", project="demo", directions=["backward", "forward"], **ARGS
        )

    assert body["ok"] is True
    assert body["data"]["new_works"] == 2
    assert _leaks(json.dumps(body), tokens) == []
    # Screening-style scrub: work ids stay visible, so a screener can record against them.
    assert body["data"]["from_works"]
    # The human view: the seed is now retrieved, by a chase-provenance work.
    checks = {c.seed_id: c for c in seed_check(project)}
    assert checks[held].status == "retrieved" and checks[held].matched_work is not None
    work = get_work(project, str(checks[held].matched_work))
    assert work is not None
    assert ProvenanceMethod.CITATION_CHASE in {p.method for p in work.provenance}


def test_seed_check_passes_after_admission(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _corpus(project, agent, human, mock_sources)
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 7", doi="10.1000/p7")
    [outcome] = add_seeds(project, human, [spec], sources=mock_sources()).written
    assert [c.status for c in seed_check(project) if c.seed_id == outcome.seed_id] == ["missing"]
    explain_seed_miss(
        project, human, outcome.seed_id, "not indexed", ProvenanceMethod.SEED_ADMISSION
    )
    deviation = record_deviation(project, human, description="Seed lookup", reason="Admission.")
    found = openalex_item(
        title="Paper 7",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id="W7",
        doi="10.1000/p7",
    )
    monkeypatch.setattr("factory.cli.main.default_sources", lambda: mock_sources(openalex=[found]))

    result = runner.invoke(
        app,
        ["seeds", "admit", outcome.seed_id, "--deviation", deviation],
        env=_cli_env(settings.root),
    )

    assert result.exit_code == 0, result.stderr
    assert "admitted" in result.stdout
    assert "missing" not in {check.status for check in seed_check(project)}
    [work] = [w for w in list_works(project) if w.identifiers.openalex == "W7"]
    assert [p.method for p in work.provenance] == [ProvenanceMethod.SEED_ADMISSION]
