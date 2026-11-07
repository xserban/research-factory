"""Forward snowball rounds narrowed by the plan (slice 8, IDEA-43, E2): core works only, a topic
filter on citing works, and at most N citing works per source work ordered by the ranker.

A fake embedder stands in for SPECTER2, so no torch or weights are needed. Every work is invented.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import SnowballPlan
from factory.model.references import (
    FORWARD_ROUND_RE,
    CoreSelection,
    Direction,
    ForwardSelection,
    SnowballRoundStarted,
    Via,
)
from factory.model.search import QueryPurpose
from factory.services import snowball
from factory.services.chase import chase_rounds
from factory.services.context import Project
from factory.services.core_works import seed_core_works
from factory.services.prisma import prisma_flow, search_report
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.search import list_works
from factory.services.snowball import plan_round, recorded_rounds, snowball_round
from tests.document_helpers import event_bytes, events_of_type
from tests.references_service_helpers import Lookups, oa_item
from tests.test_snowball_round import _screen_new

PLAN = SnowballPlan(max_backward_rounds=0, max_forward_rounds=2)


class TierEmbedder:
    """References (and any title not starting `Mid` or `Far`) embed to [0, 1]; `Mid...` to
    [1, 1]; `Far...` to [1, 0]. A citing work's score is therefore 1.0, ~0.707 or 0.0."""

    model_id = "fake/tiers"
    weights_hash = hashlib.sha256(b"tiers").hexdigest()
    software = "fake==1"

    def __init__(self, project: Project | None = None) -> None:
        self.project = project
        self.calls: list[list[str]] = []
        self.holding: list[bool] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.project is not None:
            self.holding.append(self.project.index._holding)
        out: list[list[float]] = []
        for text in texts:
            if text.startswith("Far"):
                out.append([1.0, 0.0])
            elif text.startswith("Mid"):
                out.append([1.0, 1.0])
            else:
                out.append([0.0, 1.0])
        return out


CITING = [
    oa_item("Far one", "Ann A", 2024, "W901"),
    oa_item("Close one", "Bea B", 2024, "W902"),
    oa_item("Mid one", "Cy C", 2024, "W903"),
    oa_item("Close two", "Di D", 2024, "W904"),
    oa_item("Far two", "Ed E", 2024, "W905"),
]


def _amend(project: Project, agent: Actor, plan: SnowballPlan) -> None:
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_copy(update={"snowball_plan": plan})
    amend_protocol(project, agent, spec, reason="declare snowballing", semantic=True, effects={})


def _lookups() -> Lookups:
    return Lookups(openalex=list(CITING), citing=list(CITING))


def _planned(project: Project, agent: Actor, **options: Any) -> None:
    _amend(project, agent, PLAN.model_copy(update=options))


def test_forward_round_text_grammar() -> None:
    ids = "|".join(f"W{n}" for n in range(1, 51))
    for ok in (
        "cites:W1",
        f"cites:{ids}",
        "cites:W1,title_and_abstract.search:agentic AND (science OR discovery)",
        f"openalex:{ids}",
    ):
        assert FORWARD_ROUND_RE.fullmatch(ok), ok
    for bad in (
        "cited_by:W1",
        "cites:W1/x",
        "cites:W1,title_and_abstract.search:a,b",
        "openalex:W1,title_and_abstract.search:a",
        f"cites:{ids}|W51",
        "cites:W1,publication_year:2024",
    ):
        assert FORWARD_ROUND_RE.fullmatch(bad) is None, bad


def test_selection_is_forward_only_and_bounded() -> None:
    core = CoreSelection(work_id="rf:a-00000000", matched=5, in_corpus=1, taken=2)
    assert core.not_taken == 2
    with pytest.raises(ValueError):
        CoreSelection(work_id="rf:a-00000000", matched=2, in_corpus=1, taken=2)
    selection = ForwardSelection(
        model_id="m",
        weights_hash="a" * 64,
        software="s",
        max_per_work=2,
        cores=(core,),
    )
    with pytest.raises(ValueError):
        ForwardSelection(
            model_id="m",
            weights_hash="a" * 64,
            software="s",
            max_per_work=1,
            cores=(core,),
        )
    with pytest.raises(ValueError):
        SnowballRoundStarted(
            round_id="snw_01JZ9Q3K5M7N8P0R2S4T6V8W1Z",
            direction=Direction.BACKWARD,
            via=Via.DOCUMENT_REFERENCE_LIST,
            round_no=1,
            sources=(),
            extraction_ids=(),
            candidates=(),
            queries=(),
            rule="none",
            selection=selection,
        )


def test_core_only_makes_the_core_works_the_sources(
    project: Project, corpus: None, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _planned(project, agent)
    everything = plan_round(project, Direction.FORWARD)
    assert everything.sources
    one = everything.sources[0]
    _amend(project, agent, PLAN.model_copy(update={"forward_core_only": True}))
    monkeypatch.setattr(snowball, "forward_core_sources", lambda _p, _included: [one])
    narrowed = plan_round(project, Direction.FORWARD)
    assert narrowed.sources == [one]
    named = {i for q in narrowed.queries for i in q.text.removeprefix("cites:").split("|")}
    assert len(named) == 1
    monkeypatch.undo()
    real = plan_round(project, Direction.FORWARD)
    seeds = set(seed_core_works(project))
    assert set(real.sources) | set(real.unqueryable) <= seeds | set(everything.sources)
    assert seeds & (set(real.sources) | set(real.unqueryable))


def test_core_only_without_a_core_work_is_refused(
    project: Project, corpus: None, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _planned(project, agent, forward_core_only=True)
    monkeypatch.setattr(snowball, "forward_core_sources", lambda _p, _included: [])
    plan = plan_round(project, Direction.FORWARD)
    assert [(i.field, i.reason) for i in plan.state.refusals] == [
        ("sources", "no core work with an OpenAlex id")
    ]


def test_topic_filter_is_carried_by_every_cites_query(
    project: Project, corpus: None, agent: Actor
) -> None:
    topic = "agentic AND (science OR discovery)"
    _planned(project, agent, forward_topic_filter=topic)
    dry = snowball_round(project, agent, Direction.FORWARD, sources=_lookups().sources())
    assert dry.queries and all(
        q.text.startswith("cites:") and q.text.endswith(f",title_and_abstract.search:{topic}")
        for q in dry.queries
    )
    lookups = _lookups()
    result = snowball_round(
        project, agent, Direction.FORWARD, sources=lookups.sources(), dry_run=False
    )
    assert result.round_id is not None and result.selection is None
    [chase] = chase_rounds(project)
    assert list(chase.queries) == [q.text for q in dry.queries]
    asked = [a for a in lookups.asked if a.startswith("openalex cites:")]
    assert asked and all(a.endswith(f",title_and_abstract.search:{topic}") for a in asked)
    [ledger] = events_of_type(project, "snowball.round_started")
    assert list(ledger.payload["queries"]) == list(chase.queries)
    assert "selection" not in ledger.payload


def test_dry_run_of_a_capped_round_writes_and_fetches_nothing(
    project: Project, corpus: None, agent: Actor
) -> None:
    _planned(project, agent, forward_max_per_work=2)
    lookups = _lookups()
    before = event_bytes(project)
    dry = snowball_round(project, agent, Direction.FORWARD, sources=lookups.sources())
    assert event_bytes(project) == before and lookups.asked == []
    assert dry.state.allowed and any("capped at 2" in note for note in dry.state.notes)


def test_capped_round_takes_the_best_n_and_records_the_rest(
    project: Project, corpus: None, agent: Actor
) -> None:
    _planned(project, agent, forward_max_per_work=2)
    embedder = TierEmbedder(project)
    lookups = _lookups()
    held_before = {w.id for w in list_works(project)}
    result = snowball_round(
        project,
        agent,
        Direction.FORWARD,
        sources=lookups.sources(),
        dry_run=False,
        embedder=embedder,
    )
    # The two "Close" works are the nearest to the references; nothing else enters the corpus.
    assert [q.text for q in result.queries] == ["openalex:W902|W904"]
    assert result.new_works == 2
    new = {w.title for w in list_works(project) if w.id not in held_before}
    assert new == {"Close one", "Close two"}
    # Embedded outside the write lock, once, references first.
    assert embedder.holding == [False] and len(embedder.calls) == 1
    # What the round recorded, per source work.
    selection = result.selection
    assert selection is not None and selection.max_per_work == 2
    assert selection.model_id == "fake/tiers" and selection.weights_hash == embedder.weights_hash
    assert len(selection.cores) == len(result.sources)
    for core in selection.cores:
        assert (core.matched, core.in_corpus, core.taken, core.not_taken) == (5, 0, 2, 3)
    [ledger] = events_of_type(project, "snowball.round_started")
    assert ledger.payload["selection"]["cores"][0]["taken"] == 2  # type: ignore[index]
    [recorded] = recorded_rounds(project)
    assert recorded.selection == selection
    # The probe runs are recorded, outside the corpus and the search report.
    assert len(selection.probe_runs) == len(selection.cores)
    probes = [
        e
        for e in events_of_type(project, "query.registered")
        if e.payload["spec"]["purpose"] == QueryPurpose.PROBE.value  # type: ignore[index]
        and e.payload["spec"]["text"].startswith("cites:")  # type: ignore[index]
    ]
    assert len(probes) == len(selection.cores)
    # The runs stay linked to the round through its chase round.
    [chase] = chase_rounds(project)
    assert list(chase.queries) == ["openalex:W902|W904"]
    assert snowball.round_runs(project, recorded.round_id)
    # The report shows the counts not taken, computed.
    report = search_report(project)
    [row] = report.forward_selections
    assert row.round_id == recorded.round_id and row.not_taken == 3 * len(selection.cores)
    assert all(c.not_taken == c.matched - c.in_corpus - c.taken for c in row.cores)
    # Those works are forward chase finds in the flow.
    assert prisma_flow(project).identified_other_detail["chase-forward"] == 2


def test_citing_works_already_held_are_not_candidates(
    project: Project, corpus: None, agent: Actor
) -> None:
    _planned(project, agent, forward_max_per_work=2)
    first = snowball_round(
        project,
        agent,
        Direction.FORWARD,
        sources=_lookups().sources(),
        dry_run=False,
        embedder=TierEmbedder(),
    )
    assert first.selection is not None
    # Second round (the plan allows two): the best two are held now, so the next two are taken.
    _screen_new(project, agent, "include")
    second = snowball_round(
        project,
        agent,
        Direction.FORWARD,
        sources=_lookups().sources(),
        dry_run=False,
        embedder=TierEmbedder(),
    )
    assert [q.text for q in second.queries] == ["openalex:W901|W903"]
    assert second.selection is not None
    for core in second.selection.cores:
        assert core.in_corpus == 2 and core.taken == 2 and core.not_taken == 1


def test_capped_round_without_the_extra_is_refused_with_the_remedy(
    project: Project, corpus: None, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACTORY_RANKER_MODEL", raising=False)
    _planned(project, agent, forward_max_per_work=2)
    lookups = _lookups()
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as refused:
        snowball_round(project, agent, Direction.FORWARD, sources=lookups.sources(), dry_run=False)
    assert "FACTORY_RANKER_MODEL" in str(refused.value) and "uv sync --extra ranker" in str(
        refused.value
    )
    assert event_bytes(project) == before and lookups.asked == []


def test_capped_round_with_nothing_to_take_is_refused(
    project: Project, corpus: None, agent: Actor
) -> None:
    _planned(project, agent, forward_max_per_work=2)
    empty = Lookups()
    with pytest.raises(FactoryValidationError) as refused:
        snowball_round(
            project,
            agent,
            Direction.FORWARD,
            sources=empty.sources(),
            dry_run=False,
            embedder=TierEmbedder(),
        )
    assert [i.field for i in refused.value.issues] == ["citing"]
    assert events_of_type(project, "snowball.round_started") == []
    assert chase_rounds(project) == []


def test_capped_round_with_a_failed_fetch_is_refused(
    project: Project, corpus: None, agent: Actor
) -> None:
    _planned(project, agent, forward_max_per_work=2)
    down = Lookups(fail_openalex=True)
    with pytest.raises(FactoryValidationError) as refused:
        snowball_round(
            project,
            agent,
            Direction.FORWARD,
            sources=down.sources(),
            dry_run=False,
            embedder=TierEmbedder(),
        )
    assert [i.field for i in refused.value.issues] == ["citing"]
    assert events_of_type(project, "snowball.round_started") == []
    assert chase_rounds(project) == []
