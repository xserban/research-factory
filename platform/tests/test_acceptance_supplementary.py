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
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.agreement import Outcome, final_outcomes, screen_agreement
from factory.services.calibration import calibration_items
from factory.services.chase import chase_rounds, search_chase
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.protocol import record_deviation
from factory.services.screening import pass_b_sample, screen_next
from factory.services.search import list_works
from factory.services.seeds import (
    SeedRole,
    add_seeds,
    all_seeds,
    explain_seed_miss,
    seed_check,
)
from factory.services.tasks import complete_task
from factory.sources.registry import SourceFactory
from tests.helpers import _leaks, install_skill, open_session, openalex_item
from tests.test_chase_service import _citing, _corpus, _of_type, _ordinary, _settle
from tests.test_cli import _cli_env, runner
from tests.test_screening_next import _decide

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
    served = _screen_new(project, agent, PassLabel.A, protocol_id)
    assert len(served) == 1  # the new work only; the duplicate is merged away
    assert first.id not in served


def _held_out_tokens(project: Project) -> set[str]:
    tokens: set[str] = set()
    for seed in all_seeds(project):
        if seed.role is SeedRole.HELD_OUT:
            tokens.update(v for v in (seed.seed_id, seed.doi, seed.arxiv, seed.work_id) if v)
    return tokens


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
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    tokens = _held_out_tokens(project)
    assert tokens

    # The chase returns the held-out seeds' own works again, with the new citing work.
    again = [_citing(900)]
    async with open_session(settings, clock, dict(mock_sources(openalex=again))) as session:
        body = await session.call(
            "search_chase",
            project="demo",
            directions=["backward", "forward"],
            role="searcher",
            model="claude-opus-5-5",
            skill="rf-search",
        )

    assert body["ok"] is True
    assert _leaks(json.dumps(body), tokens) == []
    # The human view still shows every positive seed as retrieved.
    assert {check.status for check in seed_check(project)} == {"retrieved"}
    held = [c for c in seed_check(project) if c.role is SeedRole.HELD_OUT]
    assert held


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
