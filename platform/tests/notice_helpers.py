"""Helpers for notice and version tests: dependent works and a scripted status source.

`StatusScript` answers status lookups from a function of the query, records which identifiers each
query named, and archives one page, like a real adapter. `status_factories` mounts scripts under
the names the notice service looks up (openalex, crossref, arxiv).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from factory.events.envelope import Actor
from factory.model.notices import NoticeKind
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.work import Identifiers
from factory.services.context import Project
from factory.services.notices import NoticeCheckSummary, notice_check
from factory.services.search import list_works
from factory.services.versions import VersionCheckSummary, version_check
from factory.services.watch import CycleHook, CycleSummary, watch_run
from factory.sources.base import PageSink, RawPage, SearchResult, StatusRecord
from factory.sources.registry import SourceFactory
from tests.helpers import T0, SourcesFor
from tests.living_helpers import agree, screening_watch_setup, start_screening
from tests.watch_helpers import ScriptedSource, adapters, by_text, record

Answer = Callable[[QuerySpec], list[StatusRecord]]


class StatusScript:
    """A status source: `answer(spec)` gives the records; `queried` keeps each query's text."""

    kinds = frozenset({QueryKind.ID_LIST, QueryKind.FILTER})

    def __init__(self, name: str, answer: Answer | None = None) -> None:
        self.name = name
        self._answer = answer or (lambda _spec: [])
        self.queried: list[str] = []
        self.fail = False
        self.raises = False
        self.tick: Callable[[], None] | None = None
        self.reported: int | None = None

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        self.queried.append(spec.text)
        if self.tick is not None:
            self.tick()
        archive(RawPage(ordinal=0, body=f'{{"q": "{spec.text}"}}', url="stub://", fetched_at=T0))
        if self.raises:
            raise RuntimeError("stub crash")
        if self.fail:
            return SearchResult(
                source=self.name,
                query_sent=spec.text,
                reported_count=None,
                works=[],
                pages=1,
                status=RunStatus.FAILED,
                note="stub failure",
            )
        return SearchResult(
            source=self.name,
            query_sent=spec.text,
            reported_count=self.reported,
            works=[],
            pages=1,
            status=RunStatus.COMPLETE,
            note=None if self.reported is None else "stub: fewer than reported",
            status_records=tuple(self._answer(spec)),
        )


def status_factories(**scripts: StatusScript) -> dict[str, SourceFactory]:
    return {
        name: SourceFactory(StatusScript.kinds, lambda _s, _c, script=script: script)  # type: ignore[misc]
        for name, script in scripts.items()
    }


def ids_in(spec: QuerySpec) -> list[str]:
    """The identifiers a status query names: `doi:a|b`, `openalex:W1|W2`, `updates:a,updates:b`
    or an arXiv id list, as bare values."""
    text = spec.text
    if text.startswith("updates:"):
        return [part.removeprefix("updates:") for part in text.split(",")]
    for prefix in ("doi:", "openalex:"):
        if text.startswith(prefix):
            return text.removeprefix(prefix).split("|")
    return text.split(",")


def notice_record(
    doi: str,
    kind: NoticeKind = NoticeKind.RETRACTION,
    notice_doi: str | None = None,
    when: date | None = None,
) -> StatusRecord:
    return StatusRecord(
        target=Identifiers(doi=doi),
        kind="notice",
        notice_kind=kind,
        notice_doi=notice_doi,
        notice_date=when,
    )


def crossref_notices(
    by_doi: Mapping[str, list[StatusRecord]],
) -> Answer:
    """A Crossref answer: the records registered for each DOI the query names."""
    return lambda spec: [r for doi in ids_in(spec) for r in by_doi.get(doi, [])]


@dataclass
class NoticeWorld:
    project: Project
    by_title: dict[str, str] = field(default_factory=dict)
    """Work id of each included record, by title."""

    @property
    def included(self) -> list[str]:
        return sorted(self.by_title.values())

    def doi(self, work_id: str) -> str | None:
        work = next(w for w in list_works(self.project) if w.id == work_id)
        return work.identifiers.doi


def dependent_world(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    records: list[dict[str, Any]],
) -> NoticeWorld:
    """A screening corpus with a watch, one cycle that brings `records`, both passes
    opened first (so no record is a calibration work), and every record included by agreement."""
    screening_watch_setup(project, agent, human, mock_sources)
    protocol_id, calibration = start_screening(project, agent)
    project.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    source = ScriptedSource(by_text({"attention": [records]}))
    summary = watch_run(project, sources=adapters(source), trigger="scheduler")
    assert summary is not None
    titles = {str(r["title"]) for r in records}
    world = NoticeWorld(project)
    for work in list_works(project):
        if work.title in titles:
            assert work.id not in calibration  # drawn before the records arrived
            agree(project, agent, work.id, protocol_id, "include")
            world.by_title[work.title] = work.id
    assert len(world.by_title) == len(titles)
    return world


def numbered_records(count: int, *, no_doi: int = 0) -> list[dict[str, Any]]:
    """`count` distinct records; the first `no_doi` have an OpenAlex id and no DOI."""
    out: list[dict[str, Any]] = []
    for k in range(count):
        if k < no_doi:
            out.append(
                {
                    **record(f"Dependent study {k} of gating", author=f"Dep {k}", year=2024),
                    "openalex": f"W70{k}",
                }
            )
        else:
            out.append(
                record(
                    f"Dependent study {k} of gating",
                    author=f"Dep {k}",
                    year=2024,
                    doi=f"10.2000/d{k}",
                )
            )
    return out


def check_in_cycle(
    project: Project,
    factories: Mapping[str, SourceFactory],
    *,
    budget: int = 200,
    notice_sources: tuple[str, ...] = ("openalex", "crossref"),
    advance_days: int = 8,
) -> tuple[CycleSummary, NoticeCheckSummary]:
    """Run an (empty) watch cycle whose hook calls `notice_check`; return both summaries."""
    out: list[NoticeCheckSummary] = []

    def hook(p: Project, cycle_id: str, _w: tuple[str, ...]) -> tuple[str, ...]:
        summary = notice_check(
            p, cycle_id, sources=factories, budget=budget, notice_sources=notice_sources
        )
        out.append(summary)
        return summary.run_ids

    project.clock.advance(timedelta(days=advance_days))  # type: ignore[attr-defined]
    cycle = _cycle(project, hook)
    return cycle, out[0]


def _cycle(
    project: Project, hook: CycleHook, records: list[dict[str, Any]] | None = None
) -> CycleSummary:
    source = ScriptedSource(by_text({"attention": [records or []]}))
    summary = watch_run(project, sources=adapters(source), trigger="scheduler", after_runs=(hook,))
    assert summary is not None
    return summary


def version_record(
    arxiv: str | None = None,
    *,
    latest: int | None = None,
    doi: str | None = None,
    linked_doi: str | None = None,
    venue: str | None = None,
) -> StatusRecord:
    """A version status record: the latest arXiv version and/or a published version's DOI."""
    return StatusRecord(
        target=Identifiers(arxiv=arxiv, doi=doi),
        kind="version",
        source_version=None if arxiv is None or latest is None else f"{arxiv}v{latest}",
        linked=None if linked_doi is None else Identifiers(doi=linked_doi),
        venue=venue,
    )


def version_in_cycle(
    project: Project,
    factories: Mapping[str, SourceFactory],
    work_ids: list[str],
    *,
    advance_days: int = 8,
    records: list[dict[str, Any]] | None = None,
) -> tuple[CycleSummary, VersionCheckSummary]:
    """Run an (empty) watch cycle whose hook calls `version_check` over `work_ids`."""
    out: list[VersionCheckSummary] = []

    def hook(p: Project, cycle_id: str, _w: tuple[str, ...]) -> tuple[str, ...]:
        summary = version_check(p, cycle_id, sources=factories, work_ids=work_ids)
        out.append(summary)
        return summary.run_ids

    project.clock.advance(timedelta(days=advance_days))  # type: ignore[attr-defined]
    return _cycle(project, hook, records), out[0]


def fetch_arxiv_version(project: Project, work_id: str, version: str) -> None:
    """Fetch an arXiv HTML document of `work_id` at `version` through a stub route."""
    from factory.model.fulltext import Route
    from factory.services.fulltext import fetch_fulltext
    from tests.route_helpers import StubRoute, always, retrieved

    body = f"<html><body>{work_id} {version}</body></html>".encode()
    route = StubRoute(Route.ARXIV_HTML, always(retrieved(Route.ARXIV_HTML, body, version=version)))
    fetch_fulltext(
        project, routes={Route.ARXIV_HTML: route}, work_ids=[work_id], only=[Route.ARXIV_HTML]
    )


def declare_schema(
    project: Project,
    agent: Actor,
    fields: tuple[str, ...] = (
        "method_name",
        "task",
        "dataset",
        "split",
        "metric",
        "value",
        "latency",
    ),
) -> None:
    """Amend the protocol to declare an extraction schema over `fields` (no rows are written)."""
    from factory.model.protocol import ExtractionSchema
    from factory.services.protocol import amend_protocol, current_protocol

    current = current_protocol(project)
    assert current is not None
    schema = ExtractionSchema(
        pack="ml-benchmark",
        pack_version=1,
        fields=fields,
        comparability_keys=("task", "dataset", "metric"),
        dual_extract_sample=1.0,
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"extraction_schema": schema}),
        reason="declare extraction",
        semantic=True,
        effects={},
    )
