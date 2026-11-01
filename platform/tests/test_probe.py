"""The probe: recall per query, source and pool, negative hits, and held-out seeds (R-20, R-24)."""

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast
from urllib.parse import unquote

import httpx
import pytest

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.project import RigorMode
from factory.model.question import NonGoal, QuestionSpec, Slot
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.services.context import Project
from factory.services.probe import THRESHOLDS, ProbeReport, run_probe
from factory.services.project import init_project
from factory.services.question import record_question, state_goal
from factory.services.search import get_work, list_works
from factory.services.seeds import (
    SeedRole,
    add_seeds,
    all_seeds,
    split_seeds,
)
from factory.sources.base import PageSink, Prober, Source, SourceError
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION, arxiv_atom, openalex_item

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
PROBE_EVENTS = {"query.registered", "probe.page_archived", "probe.measured", "probe.failed"}


def _item(n: int, title: str | None = None) -> dict[str, Any]:
    return openalex_item(
        title=title or f"Paper {n}",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )


def _question_spec() -> QuestionSpec:
    return QuestionSpec(
        scheme="PICO",
        primary_question="Does linear attention match softmax on vision?",
        slots=(
            Slot(name="population", value="vision transformers"),
            Slot(name="outcome", open="which accuracy metric", resolve_in="protocol"),
        ),
        non_goals=tuple(NonGoal(id=f"NG{i:02d}", text=f"not topic {i}") for i in (1, 2, 3)),
        rationale="Vision is the target domain.",
        objectives="Compare accuracy and cost.",
        scheme_rationale="PICO fits a comparison.",
    )


def _question(project: Project, actor: Actor) -> None:
    state_goal(project, actor, "Compare attention on vision")
    record_question(project, actor, _question_spec())


def _seed(
    project: Project,
    actor: Actor,
    mock_sources: SourcesFor,
    n: int,
    *,
    kind: SeedKind = SeedKind.POSITIVE,
    title: str | None = None,
) -> None:
    spec = SeedSpec(kind=kind, cite=f"Paper {n}", doi=f"10.1000/p{n}")
    [outcome] = add_seeds(
        project, actor, [spec], sources=mock_sources(openalex=[_item(n, title)])
    ).written
    assert outcome.work_id is not None


def _positives(project: Project, actor: Actor, mock_sources: SourcesFor, count: int) -> None:
    for n in range(1, count + 1):
        _seed(project, actor, mock_sources, n)


def _probe_spec(text: str = "attention") -> QuerySpec:
    return QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text=text)


def _exploratory(settings: Any, clock: Any) -> Project:
    return init_project(settings, "explore", "exploratory", session=SESSION, clock=clock)


def _events(project: Project) -> list[Any]:
    return read_all(project.paths.events_dir, project.catalog)


def _held_out_needles(project: Project) -> set[str]:
    """Every identifier of every held-out seed: seed id, work id, DOI, arXiv and OpenAlex ids."""
    needles: set[str] = set()
    for record in all_seeds(project):
        if record.role is not SeedRole.HELD_OUT:
            continue
        needles.update(
            {record.seed_id, record.doi or "", record.arxiv or "", record.openalex or ""}
        )
        assert record.work_id is not None
        work = get_work(project, record.work_id)
        assert work is not None
        needles.add(record.work_id)
        if work.identifiers.openalex:
            needles.add(work.identifiers.openalex)
        if work.identifiers.doi:
            needles.add(work.identifiers.doi)
        if work.identifiers.arxiv:
            needles.add(work.identifiers.arxiv)
    needles.discard("")
    assert needles, "the scenario must hold out at least one seed"
    return needles


# --- Recall, negatives, untestable seeds (acceptance 7) ---


def test_probe_reports_recall_per_query_and_source_and_pooled(
    settings: Any, clock: Any, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = _exploratory(settings, clock)
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    [outcome] = add_seeds(
        project,
        agent,
        [SeedSpec(kind=SeedKind.POSITIVE, cite="Arxiv 1", arxiv="2301.01234")],
        sources=mock_sources(arxiv=arxiv_atom([("2301.01234v2", "Linear", 2023, "Ada")])),
    ).written
    assert outcome.work_id is not None
    sources = mock_sources(openalex=[_item(1), _item(2), _item(3)])

    report = run_probe(
        project, agent, [_probe_spec("attention"), _probe_spec("transformers")], sources=sources
    )

    # Four development positives; SEED04 has no OpenAlex id, so it is untestable and missed.
    assert [q.recall for q in report.queries] == [0.75, 0.75]
    assert report.queries[0].retrieved == ("SEED01", "SEED02", "SEED03")
    assert report.queries[0].missed == ("SEED04",)
    assert report.queries[0].untestable == ("SEED04",)
    assert report.per_source_recall == {"openalex": 0.75}
    assert report.pooled_recall == 0.75
    assert report.threshold == 0.6
    assert report.meets_threshold is True


def test_probe_reports_negative_hits(
    settings: Any, clock: Any, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = _exploratory(settings, clock)
    _question(project, agent)
    _positives(project, agent, mock_sources, 2)
    _seed(project, agent, mock_sources, 9, kind=SeedKind.NEGATIVE)
    sources = mock_sources(openalex=[_item(1), _item(9)])

    report = run_probe(project, agent, [_probe_spec()], sources=sources)

    [query] = report.queries
    assert query.negatives_retrieved == ("NEG01",)
    assert query.retrieved == ("SEED01",)
    assert query.missed == ("SEED02",)


# --- Held-out seeds (acceptance 22) ---


def _arxiv_seed(project: Project, actor: Actor, mock_sources: SourcesFor, n: int) -> None:
    arxiv_id = f"2301.{n:05d}"
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", arxiv=arxiv_id)
    sources = mock_sources(arxiv=arxiv_atom([(f"{arxiv_id}v1", f"Paper {n}", 2020, "Ada")]))
    [outcome] = add_seeds(project, actor, [spec], sources=sources).written
    assert outcome.work_id is not None


def _assert_probe_writes_clean(
    project: Project,
    before: int,
    report: ProbeReport,
    http_log: list[httpx.Request],
    needles: set[str],
) -> None:
    """No held-out identifier in what the probe returns, writes or sends.

    Checked: the report, every payload and input blob the probe wrote, and every request URL.
    Documented exception (controller ruling on R-20): a raw page blob (`probe.page_archived`) is
    archived verbatim and is human-only, so it may hold a record the source returned on its own.
    The scenario makes sure that happens, to prove the exception is exercised, not avoided.

    Outside the scan: `seed.split_drawn` (the recorded split, which must name the held-out seeds)
    and the seed lookups of `add_seeds` (probe-purpose queries that precede the split).
    """
    probe_events = [e for e in _events(project)[before:] if e.type in PROBE_EVENTS]
    assert any(e.type == "probe.page_archived" for e in probe_events)
    assert http_log, "the probe must have sent requests to be checked"

    texts: list[str] = [report.model_dump_json()]
    raw_pages: list[str] = []
    for event in probe_events:
        texts.append(json.dumps(event.payload, sort_keys=True))
        if event.input_blob is not None:
            texts.append(project.blobs.get(event.input_blob).decode("utf-8"))
        if event.type == "probe.page_archived":
            raw_pages.append(project.blobs.get(event.payload["raw_blob"]).decode("utf-8"))
    texts.extend(unquote(str(request.url)) for request in http_log)

    for text in texts:
        for needle in needles:
            assert needle not in text, f"held-out identifier {needle!r} leaked"
    # The exception is real: the source's own answer carried a held-out record into a raw page.
    assert any(needle in page for page in raw_pages for needle in needles)


def test_probe_never_mentions_held_out_seeds(
    project: Project,
    agent: Actor,
    mock_sources: SourcesFor,
    http_log: list[httpx.Request],
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 6)
    split = split_seeds(project, random_seed=7)
    assert split.held_out
    needles = _held_out_needles(project)
    development = [n for n in range(1, 7) if f"SEED{n:02d}" in split.development]
    # The source answers with every work, held-out ones included, as a real count can.
    sources = mock_sources(openalex=[_item(n) for n in range(1, 7)])
    http_log.clear()
    before = len(_events(project))

    report = run_probe(
        project, agent, [_probe_spec(), _probe_spec("transformers")], sources=sources
    )

    assert report.queries[0].retrieved == tuple(f"SEED{n:02d}" for n in development)
    _assert_probe_writes_clean(project, before, report, http_log, needles)

    # Validation messages, too: a refused probe names fields, never seeds.
    with pytest.raises(FactoryValidationError) as refused:
        run_probe(
            project,
            agent,
            [QuerySpec(source="nope", kind=QueryKind.KEYWORD, text="x")],
            sources=sources,
        )
    for issue in refused.value.issues:
        for needle in needles:
            assert needle not in issue.reason and needle not in issue.field


def test_probe_never_sends_held_out_arxiv_ids(
    project: Project,
    agent: Actor,
    mock_sources: SourcesFor,
    http_log: list[httpx.Request],
) -> None:
    _question(project, agent)
    for n in range(1, 7):
        _arxiv_seed(project, agent, mock_sources, n)
    split = split_seeds(project, random_seed=7)
    assert split.held_out
    needles = _held_out_needles(project)
    assert any(needle.startswith("2301.") for needle in needles)
    sources = mock_sources(
        arxiv=arxiv_atom([(f"2301.{n:05d}v1", f"Paper {n}", 2020, "Ada") for n in range(1, 7)])
    )
    http_log.clear()
    before = len(_events(project))

    report = run_probe(
        project,
        agent,
        [QuerySpec(source="arxiv", kind=QueryKind.KEYWORD, text="linear attention")],
        sources=sources,
    )

    urls = [unquote(str(request.url)) for request in http_log]
    assert any("id_list=" in url for url in urls), "the id-list match must have been sent"
    assert any("search_query=" in url for url in urls)
    assert len(report.queries[0].retrieved) == len(split.development)
    _assert_probe_writes_clean(project, before, report, http_log, needles)


def test_probe_draws_the_split_in_pilot(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    sources = mock_sources(openalex=[_item(1)])

    run_probe(project, agent, [_probe_spec()], sources=sources)
    run_probe(project, agent, [_probe_spec("again")], sources=sources)

    splits = [e for e in _events(project) if e.type == "seed.split_drawn"]
    assert len(splits) == 1


# --- Validation before writing (acceptance 7) ---


def test_probe_requires_a_question(
    settings: Any, clock: Any, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = _exploratory(settings, clock)
    _positives(project, agent, mock_sources, 2)
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as refused:
        run_probe(project, agent, [_probe_spec()], sources=mock_sources(openalex=[_item(1)]))
    assert [issue.field for issue in refused.value.issues] == ["question"]
    assert _events(project)[before:] == []


def test_probe_validates_all_specs_before_writing(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    before = len(_events(project))
    specs = [
        _probe_spec(),
        QuerySpec(source="nope", kind=QueryKind.KEYWORD, text="attention"),
        QuerySpec(source="arxiv", kind=QueryKind.ID_LIST, text="2301.01234"),
    ]

    sources = mock_sources(openalex=[_item(1)], arxiv=arxiv_atom())
    with pytest.raises(FactoryValidationError) as refused:
        run_probe(project, agent, specs, sources=sources)

    fields = [issue.field for issue in refused.value.issues]
    assert fields == ["queries[1].source", "queries[2].kind"]
    assert len(_events(project)) == before


def test_probe_creates_no_works(project: Project, agent: Actor, mock_sources: SourcesFor) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    works_before = [w.id for w in list_works(project, include_probe=True)]

    run_probe(project, agent, [_probe_spec()], sources=mock_sources(openalex=[_item(1)]))

    assert [w.id for w in list_works(project, include_probe=True)] == works_before
    assert list_works(project) == []


def test_probe_registers_queries_with_purpose_probe(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    report = run_probe(
        project,
        agent,
        [_probe_spec()],
        sources=mock_sources(openalex=[_item(1)]),
    )
    [registered] = [
        e
        for e in _events(project)
        if e.type == "query.registered" and e.payload["spec"]["text"] == "attention"
    ]
    assert registered.payload["spec"]["purpose"] == QueryPurpose.PROBE.value
    assert registered.actor.kind == "agent"
    assert report.queries[0].query_id == registered.payload["query_id"]


# --- Event order and failure handling (acceptance 7) ---


def test_probe_pages_archived_before_measurement(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    report = run_probe(project, agent, [_probe_spec()], sources=mock_sources(openalex=[_item(1)]))
    types = [e.type for e in _events(project)]
    measured = types.index("probe.measured")
    assert types[:measured].count("probe.page_archived") >= 1
    assert report.queries[0].status == "measured"


class _Broken:
    """Wraps a real adapter so that the query `broken` fails: at its count request, before any
    page is archived, or, by default, at matching, after its count page is archived."""

    def __init__(self, inner: Prober, broken: str, *, at: str) -> None:
        self._inner = inner
        self._broken = broken
        self._at = at

    def count(self, spec: QuerySpec, *, archive: PageSink) -> int | None:
        if self._at == "count" and spec.text == self._broken:
            raise SourceError("boom: connection reset")
        return self._inner.count(spec, archive=archive)

    def matching(self, ids: Sequence[str], spec: QuerySpec, *, archive: PageSink) -> set[str]:
        if self._at == "match" and spec.text == self._broken:
            raise SourceError("boom: connection reset")
        return self._inner.matching(ids, spec, archive=archive)


def _broken_sources(
    base: Mapping[str, SourceFactory], broken: str, *, at: str = "match"
) -> dict[str, SourceFactory]:
    """The OpenAlex adapter of `base`, wrapped so that `broken` fails at `at` (count or match)."""
    inner = base["openalex"]

    def build(settings: Settings, clock: Clock) -> Source:
        # The wrapped adapter is a Source; the wrapper is only a Prober, which is all probes use.
        return cast(Source, _Broken(cast(Prober, inner(settings, clock)), broken, at=at))

    return {"openalex": SourceFactory(inner.kinds, build)}


def test_source_error_during_probe_is_reported(
    settings: Any, clock: Any, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = _exploratory(settings, clock)
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    sources = _broken_sources(mock_sources(openalex=[_item(1), _item(2)]), "broken")

    report = run_probe(
        project, agent, [_probe_spec("broken"), _probe_spec("attention")], sources=sources
    )

    broken, good = report.queries
    assert broken.status == "failed"
    assert broken.recall is None
    assert broken.reason is not None and "boom" in broken.reason
    assert good.status == "measured"
    assert good.recall == pytest.approx(2 / 3)
    assert report.per_source_recall == {"openalex": pytest.approx(2 / 3)}

    events = _events(project)
    [failed] = [e for e in events if e.type == "probe.failed"]
    assert failed.payload["query_id"] == broken.query_id
    assert "boom" in failed.payload["reason"]
    # The count page fetched before the failure stays archived.
    archived_for_broken = [
        e
        for e in events
        if e.type == "probe.page_archived" and e.payload["query_id"] == broken.query_id
    ]
    assert archived_for_broken


def test_source_error_in_the_count_request_is_reported_without_recall(
    settings: Any, clock: Any, agent: Actor, mock_sources: SourcesFor
) -> None:
    # Final review, finding 4: a failed count request is reported with its reason, claims no
    # recall, archives no page, and leaves the other queries measured.
    project = _exploratory(settings, clock)
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    sources = _broken_sources(
        mock_sources(openalex=[_item(1), _item(2)]), "broken", at="count"
    )

    report = run_probe(
        project, agent, [_probe_spec("broken"), _probe_spec("attention")], sources=sources
    )

    broken, good = report.queries
    assert broken.status == "failed"
    assert broken.recall is None and broken.reported_count is None
    assert broken.reason is not None and "boom" in broken.reason
    assert good.status == "measured" and good.recall == pytest.approx(2 / 3)
    assert report.per_source_recall == {"openalex": pytest.approx(2 / 3)}
    [failed] = [e for e in _events(project) if e.type == "probe.failed"]
    assert failed.payload["query_id"] == broken.query_id
    assert "boom" in failed.payload["reason"]
    assert not [
        e
        for e in _events(project)
        if e.type == "probe.page_archived" and e.payload["query_id"] == broken.query_id
    ]


# --- Thresholds (acceptance 7) ---


def test_threshold_by_mode() -> None:
    assert THRESHOLDS == {
        RigorMode.EXPLORATORY: 0.6,
        RigorMode.PILOT: 0.9,
        RigorMode.SYSTEMATIC: 1.0,
    }


def test_exploratory_recall_meets_its_threshold(
    settings: Any, clock: Any, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = _exploratory(settings, clock)
    _question(project, agent)
    _positives(project, agent, mock_sources, 5)
    report = run_probe(
        project,
        agent,
        [_probe_spec()],
        sources=mock_sources(openalex=[_item(n) for n in (1, 2, 3, 4)]),
    )
    assert report.pooled_recall == 0.8
    assert report.meets_threshold is True


def test_pilot_recall_below_threshold_is_not_met(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 8)
    split = split_seeds(project, random_seed=7)
    development = [int(s[4:]) for s in split.development]
    assert len(development) == 5
    sources = mock_sources(openalex=[_item(n) for n in development[1:]])

    report = run_probe(project, agent, [_probe_spec()], sources=sources)

    assert report.pooled_recall == 0.8
    assert report.threshold == 0.9
    assert report.meets_threshold is False


def test_recall_is_none_when_nothing_measured(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    sources = _broken_sources(mock_sources(openalex=[_item(1)]), "attention")
    report = run_probe(project, agent, [_probe_spec()], sources=sources)
    assert report.pooled_recall is None
    assert report.per_source_recall == {"openalex": None}
    assert report.meets_threshold is False


# --- Suggestions and rebuild ---


def test_suggestions_name_development_seeds(
    settings: Any, clock: Any, agent: Actor, mock_sources: SourcesFor
) -> None:
    project = _exploratory(settings, clock)
    _question(project, agent)
    _seed(project, agent, mock_sources, 1, title="Linear attention")
    for n in (2, 3, 4):
        _seed(project, agent, mock_sources, n, title="Graph neural network scaling")
    sources = mock_sources(openalex=[_item(1, "Linear attention")])

    report = run_probe(project, agent, [_probe_spec("attention")], sources=sources)

    [query] = report.queries
    assert query.missed == ("SEED02", "SEED03", "SEED04")
    graph = [s for s in query.suggestions if "graph neural" in s.term]
    assert graph, "the phrase shared by the missed seeds must be suggested"
    assert set(graph[0].holders) <= {"SEED02", "SEED03", "SEED04"}
    assert graph[0].seeds == len(graph[0].holders) == 3


def test_probe_rebuild_equals_incremental(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question(project, agent)
    _positives(project, agent, mock_sources, 3)
    run_probe(project, agent, [_probe_spec()], sources=mock_sources(openalex=[_item(1)]))
    before = project.index.state_hash()
    assert project.index.rebuild() == before
