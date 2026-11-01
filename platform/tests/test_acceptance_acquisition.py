"""Slice-1 acceptance for works and acquisition (criteria 3, 4, 14), over the REAL adapters.

The OpenAlex and arXiv adapters run against `httpx.MockTransport` payloads (`mock_sources`), so
nothing here touches the network. Each test states the acceptance criterion it proves.
"""

import shutil
from collections.abc import Callable, Mapping
from datetime import timedelta

import httpx
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.services.context import Project
from factory.services.dedup import active_merges, canonical_works, dedup_run, revert_merge
from factory.services.search import (
    RunSummary,
    list_works,
    register_query,
    run_query,
    search_counts,
)
from factory.sources.registry import SourceFactory
from tests.helpers import arxiv_atom, openalex_item

MockSources = Callable[..., Mapping[str, SourceFactory]]
DOI_ARXIV = "10.48550/arXiv.2301.01234"  # DataCite DOI that arXiv mints for 2301.01234


def _search(
    project: Project, sources: Mapping[str, SourceFactory], source: str, text: str
) -> RunSummary:
    spec = QuerySpec(source=source, kind=QueryKind.KEYWORD, text=text)
    query_id = register_query(project, project.human_actor(), spec, sources=sources)
    return run_query(project, query_id, sources=sources)


def test_datacite_doi_and_bare_arxiv_id_are_one_work(
    project: Project, mock_sources: MockSources, clock: FixedClock
) -> None:
    # Acceptance 3, same metadata: OpenAlex's DOI and arXiv's bare id meet under one work id.
    sources = mock_sources(
        openalex=[
            openalex_item(
                title="Linear attention",
                author="Ada Zhou",
                published="2023-01-05",
                openalex_id="W4001",
                doi=DOI_ARXIV,
            )
        ],
        arxiv=arxiv_atom([("2301.01234v2", "Linear attention", 2023, "Ada Zhou")]),
    )
    _search(project, sources, "openalex", "linear attention")
    clock.advance(timedelta(milliseconds=1))
    _search(project, sources, "arxiv", "linear attention")

    [work] = list_works(project)
    assert work.sources == ["openalex", "arxiv"]
    assert len(work.provenance) == 2
    assert dedup_run(project).created == []  # one work already: no merge to record


def test_datacite_doi_and_bare_arxiv_id_with_differing_metadata_merge_reversibly(
    project: Project, agent: Actor, mock_sources: MockSources, clock: FixedClock
) -> None:
    # Acceptance 3, differing metadata (OpenAlex 2024, arXiv 2023): two works, one merge.
    sources = mock_sources(
        openalex=[
            openalex_item(
                title="Linear attention",
                author="Ada Zhou",
                published="2024-02-01",
                openalex_id="W4002",
                doi=DOI_ARXIV,
            )
        ],
        arxiv=arxiv_atom([("2301.01234v2", "Linear attention", 2023, "Ada Zhou")]),
    )
    _search(project, sources, "openalex", "linear attention")
    clock.advance(timedelta(milliseconds=1))
    _search(project, sources, "arxiv", "linear attention")
    assert len(list_works(project)) == 2

    summary = dedup_run(project)
    assert len(summary.created) == 1
    [merge] = active_merges(project)
    assert merge.merge_id == summary.created[0]
    assert "identifier:arxiv" in merge.rule

    clock.advance(timedelta(milliseconds=1))
    revert_merge(project, agent, merge.merge_id, "test")
    assert len(canonical_works(project)) == 2
    again = dedup_run(project)
    assert again.created == []


def test_published_and_preprint_merge_is_listed_and_reversible(
    project: Project, agent: Actor, mock_sources: MockSources, clock: FixedClock
) -> None:
    # Acceptance 3, cross-identifier case: a published DOI and a preprint of the same paper.
    sources = mock_sources(
        openalex=[
            openalex_item(
                title="Linear attention in transformers",
                author="Ada Zhou",
                published="2024-06-01",
                openalex_id="W4003",
                doi="10.1000/x",
            )
        ],
        arxiv=arxiv_atom([("2301.00001v1", "Linear attention in transformers", 2024, "Ada Zhou")]),
    )
    _search(project, sources, "openalex", "linear attention")
    clock.advance(timedelta(milliseconds=1))
    _search(project, sources, "arxiv", "linear attention")

    summary = dedup_run(project)
    assert len(summary.created) == 1
    [merge] = active_merges(project)
    assert merge.merge_id == summary.created[0]

    clock.advance(timedelta(milliseconds=1))
    revert_merge(project, agent, merge.merge_id, "different papers")
    assert active_merges(project) == []
    assert len(canonical_works(project)) == 2
    assert dedup_run(project).created == []


def test_every_run_stores_reported_and_retrieved_and_shortfall_is_visible(
    project: Project, mock_sources: MockSources
) -> None:
    # Acceptance 4: OpenAlex reports 5, delivers 2 (one untitled record skipped); the run says why.
    items = [
        openalex_item(
            title="Linear attention", author="Ada Zhou", published="2023-01-05", openalex_id="W1"
        ),
        openalex_item(
            title="Sparse attention", author="Ben Li", published="2023-02-05", openalex_id="W2"
        ),
        openalex_item(title="", author="Cai Wu", published="2023-03-05", openalex_id="W3"),
    ]
    sources = mock_sources(openalex=items, openalex_count=5)
    summary = _search(project, sources, "openalex", "attention")

    assert summary.status == RunStatus.COMPLETE
    assert (summary.reported_count, summary.retrieved_count) == (5, 2)
    assert summary.note is not None and "skipped" in summary.note
    [shortfall] = search_counts(project).shortfalls
    assert (shortfall.run_id, shortfall.reported_count, shortfall.retrieved_count) == (
        summary.run_id,
        5,
        2,
    )
    assert shortfall.note == summary.note


def test_adapters_never_request_relevance_sorting(
    project: Project, mock_sources: MockSources, http_log: list[httpx.Request]
) -> None:
    # Acceptance 14 (R-21): OpenAlex sends no `sort`/`search`; arXiv sorts by submission date.
    sources = mock_sources(
        openalex=[
            openalex_item(
                title="Linear attention",
                author="Ada Zhou",
                published="2023-01-05",
                openalex_id="W1",
            )
        ],
        arxiv=arxiv_atom(),
    )
    _search(project, sources, "openalex", "linear attention")
    _search(project, sources, "arxiv", "linear attention")

    openalex = [r for r in http_log if r.url.host == "api.openalex.org"]
    arxiv = [r for r in http_log if r.url.host == "export.arxiv.org"]
    assert openalex and arxiv
    for request in openalex:
        assert "sort" not in request.url.params and "search" not in request.url.params
    for request in arxiv:
        assert request.url.params["sortBy"] == "submittedDate"
        assert request.url.params["sortOrder"] == "ascending"


def test_acquisition_rebuild_is_deterministic(
    settings: Settings,
    project: Project,
    agent: Actor,
    mock_sources: MockSources,
    clock: FixedClock,
) -> None:
    # Criterion 1 for acquisition: searches, dedup and a reversal survive an index rebuild.
    sources = mock_sources(
        openalex=[
            openalex_item(
                title="Linear attention",
                author="Ada Zhou",
                published="2024-02-01",
                openalex_id="W4004",
                doi=DOI_ARXIV,
            )
        ],
        arxiv=arxiv_atom([("2301.01234v2", "Linear attention", 2023, "Ada Zhou")]),
    )
    _search(project, sources, "openalex", "linear attention")
    clock.advance(timedelta(milliseconds=1))
    _search(project, sources, "arxiv", "linear attention")
    clock.advance(timedelta(milliseconds=1))
    [merge_id] = dedup_run(project).created
    clock.advance(timedelta(milliseconds=1))
    revert_merge(project, agent, merge_id, "test")
    dedup_run(project)

    before = project.index.state_hash()
    shutil.rmtree(project.paths.dir / ".index")
    out = CliRunner().invoke(
        app,
        ["--root", str(settings.root), "rebuild"],
        env={"FACTORY_USER": "obd", "FACTORY_ROOT": None, "FACTORY_PROJECT": None},
    )
    assert out.exit_code == 0, out.stderr
    assert out.stdout.strip() == f"state {before}"
