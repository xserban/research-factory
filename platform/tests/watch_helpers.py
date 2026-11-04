"""Fixtures for watch tests: a ready pilot project with a watch plan, and a scripted source.

`ScriptedSource` answers the nth call to `run` with the nth scripted response, so a cycle can see
different records on each replay. A response is a list of pages (lists of record dicts, as
`FakeSource` takes them) or the string "fail", which yields a failed run. The adapter is mounted
under the protocol's source name ("openalex") so the real protocol gate applies.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from factory.events.envelope import Actor
from factory.model.protocol import PlannedQuery
from factory.model.search import QueryKind, QuerySpec
from factory.model.watch import WatchPlan, WatchSource
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.sources.base import PageSink, SearchResult
from factory.sources.registry import SourceFactory
from tests.helpers import FakeSource, SourcesFor, ready_protocol

Response = Sequence[Sequence[dict[str, Any]]] | str

QUERIES = (
    PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="attention"),
    PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="transformers"),
)


def record(
    title: str,
    *,
    doi: str | None = None,
    year: int = 2024,
    author: str = "Ada Zhou",
    published: str | None = None,
) -> dict[str, Any]:
    """A record dict for `FakeSource`; `published` (ISO date) is when the source listed it."""
    out: dict[str, Any] = {"title": title, "authors": [author], "year": year}
    if doi is not None:
        out["doi"] = doi
    if published is not None:
        out["published"] = published
    return out


class ScriptedSource:
    """Answers call n with `script(n, spec)`; the specs it was asked are kept in `specs`."""

    name = "fake"
    kinds = FakeSource.kinds

    def __init__(self, script: Callable[[int, QuerySpec], Response]) -> None:
        self._script = script
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
        response = self._script(len(self.specs), spec)
        self.specs.append(spec)
        if response == "fail":
            return FakeSource([[]], fail_after=0).run(
                spec, run_id=run_id, query_id=query_id, archive=archive
            )
        pages = [list(page) for page in response]  # type: ignore[arg-type]
        return FakeSource(pages).run(spec, run_id=run_id, query_id=query_id, archive=archive)


def adapters(source: ScriptedSource) -> Mapping[str, SourceFactory]:
    return {"openalex": SourceFactory(ScriptedSource.kinds, lambda _s, _c: source)}


def by_text(pages_by_text: Mapping[str, Response]) -> Callable[[int, QuerySpec], Response]:
    """A script keyed on the query text."""
    return lambda _n, spec: pages_by_text.get(spec.text, [[]])


def watch_ready(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    interval_days: int = 7,
    queries: tuple[PlannedQuery, ...] = QUERIES,
    plan: WatchPlan | None = None,
) -> str:
    """A ready, PRESS-confirmed pilot protocol that declares a watch plan on openalex."""
    ready_protocol(project, agent, human, mock_sources, queries=queries)
    current = current_protocol(project)
    assert current is not None
    declared = plan or WatchPlan(
        sources=(WatchSource(source="openalex", interval_days=interval_days),)
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"watch_plan": declared}),
        reason="declare the watch",
        semantic=True,
        effects={},
    )
    amended = current_protocol(project)
    assert amended is not None
    return amended.protocol_id


def window_plan(
    *, interval_days: int = 7, overlap_days: int = 2, replay_every: int = 2
) -> WatchPlan:
    """A watch plan that windows openalex, replaying in full every `replay_every` cycles."""
    return WatchPlan(
        sources=(
            WatchSource(
                source="openalex",
                interval_days=interval_days,
                mode="window",
                overlap_days=overlap_days,
                full_replay_every=replay_every,
            ),
        )
    )
