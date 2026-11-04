"""Window queries: adapter filters, the cycle waiver in `search_authorization`, window counts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.living.window import window_spec
from factory.model.protocol import PlannedQuery
from factory.model.search import QueryKind, QuerySpec
from factory.services.context import Project
from factory.services.protocol import current_protocol, search_authorization
from factory.services.search import register_query
from factory.services.watch import CycleSummary, cycles, watch_run
from factory.sources.registry import SourceFactory, default_sources
from tests.helpers import SESSION, T0
from tests.watch_helpers import (
    QUERIES,
    ScriptedSource,
    adapters,
    by_text,
    record,
    watch_ready,
    window_plan,
)

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


@pytest.fixture
def windowed(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> Project:
    """A ready project that windows openalex. The real adapter's filter is unverified (see
    `OpenAlexSource.window_filter`), so the readiness rule is told openalex has one."""
    monkeypatch.setattr(
        "factory.services.protocol.window_filter_sources", lambda: frozenset({"openalex"})
    )
    watch_ready(project, agent, human, mock_sources, plan=window_plan())
    return project


def _run(project: Project, source: ScriptedSource) -> CycleSummary | None:
    return watch_run(project, sources=adapters(source), trigger="scheduler")


def _crash_before_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("process died")

    monkeypatch.setattr("factory.services.watch._finish", boom)


def _planned(text: str = "attention") -> PlannedQuery:
    return PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text=text)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _open_window_cycle(
    project: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, date]:
    """Leave an open cycle that runs openalex as a window; return its id and window start."""
    first = ScriptedSource(by_text({"attention": [[]], "transformers": [[]]}))
    assert _run(project, first) is not None
    clock.advance(timedelta(days=8))
    with monkeypatch.context() as patch:
        _crash_before_finish(patch)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError):
            _run(project, ScriptedSource(by_text({"attention": [[]], "transformers": [[]]})))
    open_view = next(v for v in cycles(project) if v.finished_at is None)
    sources = project.index.connect()
    with sources as conn:
        row = conn.exec_driver_sql(
            "SELECT window_start FROM watch_cycle_sources WHERE cycle_id = ?",
            (open_view.cycle_id,),
        ).one()
    assert row[0] is not None
    return open_view.cycle_id, date.fromisoformat(row[0])


def test_window_spec_authorised_with_its_cycle(windowed: Project, clock: FixedClock) -> None:
    first = ScriptedSource(by_text({"attention": [[]], "transformers": [[]]}))
    one = _run(windowed, first)
    assert one is not None
    assert all("listed_since" not in s.filters for s in first.specs)  # no complete cycle: full
    started = clock.now()
    clock.advance(timedelta(days=8))
    second = ScriptedSource(by_text({"attention": [[]], "transformers": [[]]}))
    two = _run(windowed, second)
    assert two is not None and two.status.value == "complete"
    expected = (started - timedelta(days=2)).date().isoformat()
    assert [s.filters for s in second.specs] == [{"listed_since": expected}] * 2
    [open_one, open_two] = cycles(windowed)
    assert open_one.full_replay_sources == ("openalex",) and open_two.full_replay_sources == ()
    # The window queries are separate registered queries that name their cycle last.
    events = read_all(windowed.paths.events_dir, windowed.catalog)
    window_queries = [
        e for e in events if e.type == "query.registered" and e.refs[-1] == two.cycle_id
    ]
    assert len(window_queries) == 2
    assert {e.payload["spec"]["filters"]["listed_since"] for e in window_queries} == {expected}


def test_window_query_needs_its_open_cycle(
    windowed: Project,
    agent: Actor,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    mock_sources: SourcesFor,
) -> None:
    cycle_id, start = _open_window_cycle(windowed, clock, monkeypatch)
    spec = window_spec(_planned(), start)
    sources = mock_sources()
    # No cycle named: not a planned text.
    before = _count(windowed)
    with pytest.raises(FactoryValidationError):
        register_query(windowed, agent, spec, sources=sources)
    assert _count(windowed) == before
    # A foreign cycle id.
    with pytest.raises(FactoryValidationError):
        register_query(windowed, agent, spec, sources=sources, cycle_id="wcy_" + SESSION)
    assert _count(windowed) == before
    # A cycle of an older protocol: amend the protocol, then name the (still open) old cycle.
    current = current_protocol(windowed)
    assert current is not None and current.spec.watch_plan is not None
    plan = current.spec.watch_plan
    source = plan.sources[0].model_copy(update={"interval_days": 9})
    from factory.services.protocol import amend_protocol

    amend_protocol(
        windowed,
        agent,
        current.spec.model_copy(
            update={"watch_plan": plan.model_copy(update={"sources": (source,)})}
        ),
        reason="slower cadence",
        semantic=True,
        effects={},
    )
    issues = search_authorization(windowed, spec, deviation_id=None, cycle_id=cycle_id)
    assert [i.field for i in issues] == ["query"]
    # A finished cycle.
    clock.advance(timedelta(days=30))
    finished = _run(windowed, ScriptedSource(by_text({"attention": [[]], "transformers": [[]]})))
    assert finished is not None
    closed = next(v for v in cycles(windowed) if v.cycle_id == cycle_id)
    assert closed.finished_at is not None  # abandoned: closed before the new cycle opened
    issues = search_authorization(windowed, spec, deviation_id=None, cycle_id=cycle_id)
    assert [i.field for i in issues] == ["query"]


def test_window_with_other_date_refused(
    windowed: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle_id, start = _open_window_cycle(windowed, clock, monkeypatch)
    ok = window_spec(_planned(), start)
    assert search_authorization(windowed, ok, deviation_id=None, cycle_id=cycle_id) == []
    later = window_spec(_planned(), start + timedelta(days=1))
    assert search_authorization(windowed, later, deviation_id=None, cycle_id=cycle_id)
    extra = ok.model_copy(update={"filters": {**ok.filters, "year": "2020"}})
    assert search_authorization(windowed, extra, deviation_id=None, cycle_id=cycle_id)
    other_text = window_spec(_planned("unplanned"), start)
    assert search_authorization(windowed, other_text, deviation_id=None, cycle_id=cycle_id)
    # A full-source cycle waives nothing: only a window cycle authorises window specs.
    assert search_authorization(windowed, ok, deviation_id=None)


def test_round_and_cycle_together_refused(
    windowed: Project,
    agent: Actor,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    mock_sources: SourcesFor,
) -> None:
    cycle_id, start = _open_window_cycle(windowed, clock, monkeypatch)
    before = _count(windowed)
    with pytest.raises(FactoryValidationError) as raised:
        register_query(
            windowed,
            agent,
            window_spec(_planned(), start),
            sources=mock_sources(),
            round_id="snw_" + SESSION,
            cycle_id=cycle_id,
        )
    assert "cycle_id" in [i.field for i in raised.value.issues]
    assert _count(windowed) == before


def test_full_replay_counts_window_missed(windowed: Project, clock: FixedClock) -> None:
    known = record("Alpha methods for sparse graphs", author="Ana Li", published="2026-10-01")
    missed = record("Beta bounds on federated drift", author="Bo Chen", published="2026-11-03")
    later = record("Gamma routing of experts", author="Cy Dee", published="2026-11-15")
    pages = {"attention": [[known]], "transformers": [[]]}
    first = _run(windowed, ScriptedSource(by_text(pages)))  # full replay, Oct 31
    assert first is not None and first.counts[0].window_missed is None
    clock.advance(timedelta(days=8))  # Nov 8: window, which does not return `missed`
    window = _run(windowed, ScriptedSource(by_text(pages)))
    assert window is not None and window.counts[0].window_missed is None
    clock.advance(timedelta(days=8))  # Nov 16: full replay again
    replay = _run(
        windowed,
        ScriptedSource(by_text({"attention": [[known, missed, later]], "transformers": [[]]})),
    )
    assert replay is not None
    [counts] = replay.counts
    assert counts.new_works == 2
    # `missed` was listed inside window 1 (between the last replay and the last cycle);
    # `later` was listed after the last cycle and is legitimately new.
    assert counts.window_missed == 1
    assert T0.date() == date(2026, 10, 31)


# --- adapters ---


def _archive(_page: Any) -> str:
    return "sha256:" + "a" * 64


def test_arxiv_maps_listed_since(
    mock_sources: SourcesFor, settings: Settings, clock: FixedClock, http_log: list[httpx.Request]
) -> None:
    from tests.helpers import arxiv_atom

    adapter = mock_sources(arxiv=arxiv_atom())["arxiv"](settings, clock)
    spec = QuerySpec(
        source="arxiv",
        kind=QueryKind.KEYWORD,
        text="all:attention",
        filters={"listed_since": "2026-03-01"},
    )
    result = adapter.run(spec, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_archive)
    sent = http_log[-1].url.params["search_query"]
    assert sent == "(all:attention) AND submittedDate:[202603010000 TO 999912312359]"
    assert result.query_sent == sent
    ored = spec.model_copy(update={"text": "all:a OR all:b"})
    adapter.run(ored, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_archive)
    assert http_log[-1].url.params["search_query"].startswith("(all:a OR all:b) AND submittedDate")
    plain = spec.model_copy(update={"filters": {}})
    adapter.run(plain, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_archive)
    assert http_log[-1].url.params["search_query"] == "all:attention"


def test_openalex_maps_listed_since(
    mock_sources: SourcesFor, settings: Settings, clock: FixedClock, http_log: list[httpx.Request]
) -> None:
    adapter = mock_sources(openalex=[])["openalex"](settings, clock)
    spec = QuerySpec(
        source="openalex",
        kind=QueryKind.KEYWORD,
        text="attention",
        filters={"listed_since": "2026-03-01", "type": "article"},
    )
    adapter.run(spec, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_archive)
    sent = http_log[-1].url.params["filter"]
    assert "from_created_date:2026-03-01" in sent and "type:article" in sent
    assert "listed_since" not in sent


def test_window_filter_flags() -> None:
    sources = default_sources()
    assert sources["arxiv"].window_filter is True
    assert sources["openalex"].window_filter is False  # unverified without a key; see the adapter


def test_planned_queries_unchanged() -> None:
    assert [q.text for q in QUERIES] == ["attention", "transformers"]
