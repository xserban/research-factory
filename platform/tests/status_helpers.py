"""Helpers for living-C tests: a scripted status source and a cycle that runs a callback."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from factory.events.envelope import Actor
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.services.context import Project
from factory.services.search import register_query, run_query
from factory.services.watch import CycleHook, CycleSummary, watch_run
from factory.sources.base import PageSink, RawPage, SearchResult
from factory.sources.registry import SourceFactory
from tests.helpers import T0
from tests.watch_helpers import ScriptedSource, adapters, by_text, record

A = record("Alpha methods for sparse graphs", author="Ana Li", year=2021, doi="10.1000/alpha")
B = record("Beta bounds on federated drift", author="Bo Chen", year=2022, doi="10.1000/beta")


class StatusStub:
    """Accepts id-list and filter queries, archives one page and yields no works."""

    name = "openalex"
    kinds = frozenset({QueryKind.ID_LIST, QueryKind.FILTER})

    def __init__(self) -> None:
        self.specs: list[QuerySpec] = []

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        self.specs.append(spec)
        archive(RawPage(ordinal=0, body="{}", url="stub://status", fetched_at=T0))
        return SearchResult(
            source=self.name,
            query_sent="stub",
            reported_count=None,
            works=[],
            pages=1,
            status=RunStatus.COMPLETE,
        )


def in_cycle(
    project: Project,
    hook: CycleHook,
    *,
    records: list[dict[str, Any]] | None = None,
    sources: Mapping[str, SourceFactory] | None = None,
) -> CycleSummary:
    """Run one watch cycle (the `attention` query returns `records`) with `hook` inside it."""
    source = ScriptedSource(by_text({"attention": [[A, B] if records is None else records]}))
    summary = watch_run(
        project,
        sources=sources or adapters(source),
        trigger="scheduler",
        after_runs=(hook,),
    )
    assert summary is not None
    return summary


def noop_hook(_p: Project, _c: str, _w: tuple[str, ...]) -> tuple[str, ...]:
    return ()


def status_query_hook(
    spec: QuerySpec, out: list[str], factories: Mapping[str, SourceFactory], actor: Actor | None
) -> Callable[[Project, str, tuple[str, ...]], tuple[str, ...]]:
    """A hook that registers and runs `spec` naming the cycle; appends the run id to `out`."""

    def hook(project: Project, cycle_id: str, _w: tuple[str, ...]) -> tuple[str, ...]:
        qid = register_query(
            project, actor or project.system_actor(), spec, sources=factories, cycle_id=cycle_id
        )
        summary = run_query(project, qid, sources=factories, cycle_id=cycle_id)
        out.append(summary.run_id)
        return (summary.run_id,)

    return hook
