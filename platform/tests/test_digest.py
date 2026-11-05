"""The computed digest and its renderers (living-D, task 4)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.living.digest_render import to_json, to_markdown
from factory.model.conclusions import BasisRef
from factory.model.notices import NoticeKind, NoticeObserved
from factory.model.watch import WatchPlan, WatchSource
from factory.services.conclusions import register_conclusion
from factory.services.context import Project
from factory.services.digest import agent_digest, digest_build, record_digest
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.snapshots import snapshot
from factory.services.watch import CycleSummary, watch_run
from tests.helpers import SourcesFor
from tests.living_helpers import agree, filler, screening_watch_setup, start_screening
from tests.watch_helpers import ScriptedSource, adapters, by_text, record

ABSTRACT = "Zorblax quantum frobnication of attention heads."


def cycle(project: Project, records: list[dict[str, Any]]) -> CycleSummary:
    source = ScriptedSource(by_text({"attention": [records]}))
    summary = watch_run(project, sources=adapters(source), trigger="scheduler")
    assert summary is not None
    return summary


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    screening_watch_setup(project, agent, human, mock_sources)
    return project


def two_cycles(project: Project, clock: FixedClock) -> tuple[CycleSummary, CycleSummary]:
    first = cycle(project, filler(5))
    record_digest([project], digest_build([project]))
    clock.advance(timedelta(days=8))
    second = cycle(project, filler(3, first=100))
    return first, second


def test_digest_lists_cycle_candidates_with_query_ids(ready: Project, clock: FixedClock) -> None:
    _, second = two_cycles(ready, clock)
    [digest] = digest_build([ready]).projects
    items = digest.new_candidates.items
    assert {c.work_id for c in items} == set(
        second.new_work_ids
    ) and digest.new_candidates.more == 0
    assert all(c.query_ids and c.query_ids[0].startswith("qry_") for c in items)
    assert all(c.title.startswith("Watch study") and c.route == "database:openalex" for c in items)
    assert [c.work_id for c in items] == [
        c.work_id for c in sorted(items, key=lambda c: (c.query_ids, c.work_id))
    ]
    [row] = digest.cycles
    assert row.cycle_id == second.cycle_id and row.counts[0].new_works == 3


def test_digest_since_last_recorded(ready: Project, clock: FixedClock) -> None:
    [fresh] = digest_build([ready]).projects
    assert fresh.since_event is None and fresh.new_candidates.items  # the set-up corpus
    digest_id = record_digest([ready], digest_build([ready]))
    assert digest_id.startswith("dig_")
    cycle(ready, filler(2))
    [after] = digest_build([ready]).projects
    assert after.since_event == fresh.cutoff_event and len(after.new_candidates.items) == 2
    # An explicit event id overrides "last"; so does None (from the start).
    [explicit] = digest_build([ready], since=None).projects
    assert explicit.since_event is None
    assert len(explicit.new_candidates.items) == len(fresh.new_candidates.items) + 2
    [named] = digest_build([ready], since=fresh.cutoff_event).projects
    assert named.since_event == fresh.cutoff_event


def test_record_writes_one_event_per_project_with_blobs(ready: Project) -> None:
    record_digest([ready], digest_build([ready]))
    cycle(ready, filler(2))
    built = digest_build([ready])
    digest_id = record_digest([ready], built)
    events = [
        e for e in read_all(ready.paths.events_dir, ready.catalog) if e.type == "digest.generated"
    ]
    assert len(events) == 2
    event = events[-1]
    assert event.payload["digest_id"] == digest_id and event.actor.kind == "system"
    assert event.payload["project"] == ready.paths.slug
    stored = ready.blobs.get(str(event.payload["blob"])).decode()
    assert stored == to_json(built.model_copy(update={"digest_id": digest_id}))
    assert ready.blobs.get(str(event.payload["markdown_blob"])).decode().startswith("# Digest")
    counts = event.payload["counts"]
    assert isinstance(counts, dict) and counts["new_candidates"] == 2


def test_open_decisions_counts_recompute(ready: Project, human: Actor) -> None:
    summary = cycle(ready, filler(2))
    [digest] = digest_build([ready]).projects
    assert set(digest.open_decisions) == {
        "screening-disagreements",
        "calibration-labels",
        "audit-labels",
        "notice-assessments",
        "inferred-relations",
        "fuzzy-reference-links",
    }
    assert digest.open_decisions["notice-assessments"] == 0
    work = summary.new_work_ids[0]
    payload = NoticeObserved(
        notice_id=ready.ids.new("ntc"),
        work_id=work,
        kind=NoticeKind.RETRACTION,
        notice_date=date(2025, 1, 2),
        notice_doi="10.2000/r",
        source="crossref",
        run_id=ready.ids.new("run"),
        raw_blob="sha256:" + "b" * 64,
    )
    ready.record(
        [
            ready.events.make(
                "notice.observed", payload, ready.system_actor(), refs=(payload.notice_id, work)
            )
        ]
    )
    [again] = digest_build([ready]).projects
    assert again.open_decisions["notice-assessments"] == 1
    [notice] = again.notices.items
    assert (notice.work_id, notice.kind, notice.assessed) == (work, "retraction", False)


def test_listing_cap_and_more(ready: Project, agent: Actor) -> None:
    current = current_protocol(ready)
    assert current is not None and current.spec.watch_plan is not None
    capped = current.spec.watch_plan.model_copy(update={"digest_listing_cap": 2})
    amend_protocol(
        ready,
        agent,
        current.spec.model_copy(update={"watch_plan": capped}),
        reason="cap the digest",
        semantic=True,
        effects={},
    )
    record_digest([ready], digest_build([ready]))
    cycle(ready, filler(5))
    [digest] = digest_build([ready]).projects
    assert len(digest.new_candidates.items) == 2 and digest.new_candidates.more == 3


def test_digest_has_no_text_or_verdict(ready: Project, human: Actor) -> None:
    records = [{**record("Watch study abstracts"), "abstract": ABSTRACT}, *filler(2)]
    summary = cycle(ready, records)
    register_conclusion(
        ready,
        human,
        "Linear attention beats softmax attention outright.",
        [BasisRef(kind="work", ref=summary.new_work_ids[0])],
        None,
    )
    snapshot(ready, human, trigger="human")
    built = digest_build([ready])
    for rendered in (to_markdown(built), to_json(built), to_markdown(agent_digest(built))):
        assert ABSTRACT not in rendered and "Zorblax" not in rendered
        assert "Linear attention beats" not in rendered
        lowered = rendered.lower()
        for word in ("verdict", "recommend", "relevan", "should "):
            assert word not in lowered


def test_digest_agent_view_withholds(ready: Project, agent: Actor, human: Actor) -> None:
    protocol_id, calibration = start_screening(ready, agent)
    ready.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    first = cycle(ready, filler(3))
    target = next(w for w in sorted(first.new_work_ids) if w not in calibration)
    agree(ready, agent, target, protocol_id, "include")
    snapshot(ready, human, trigger="human")
    ready.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    cycle(ready, filler(2, first=50))
    snapshot(ready, human, trigger="human")
    built = digest_build([ready], since=None)
    [full] = built.projects
    assert full.update_flow is not None
    [seen] = agent_digest(built).projects
    assert seen.update_flow is not None and seen.update_flow.changed_previous == ()
    assert seen.open_decisions == full.open_decisions  # counts of open decisions stay
    blob = to_json(agent_digest(built))
    assert re.search(r"\b(SEED|NEG)\d{2,}\b", blob) is None  # no seed id
    for word in ("error_rate", "sensitivity", "kappa", "held_out", "held-out", "recall"):
        assert word not in blob.lower()


def test_digest_deterministic(ready: Project, clock: FixedClock) -> None:
    two_cycles(ready, clock)
    first = digest_build([ready])
    second = digest_build([ready])
    assert to_markdown(first) == to_markdown(second) and to_json(first) == to_json(second)
    ready.index.rebuild()
    rebuilt = digest_build([ready])
    assert to_markdown(rebuilt) == to_markdown(first) and to_json(rebuilt) == to_json(first)


def test_retired_project_marked(ready: Project, agent: Actor, clock: FixedClock) -> None:
    [active] = digest_build([ready]).projects
    assert active.status == "active"
    current = current_protocol(ready)
    assert current is not None and current.spec.watch_plan is not None
    plan = WatchPlan(
        sources=(WatchSource(source="openalex", interval_days=7),),
        until=(clock.now() + timedelta(days=1)).date(),
    )
    amend_protocol(
        ready,
        agent,
        current.spec.model_copy(update={"watch_plan": plan}),
        reason="end the watch",
        semantic=True,
        effects={},
    )
    clock.advance(timedelta(days=3))
    [retired] = digest_build([ready]).projects
    assert retired.status == "retired" and retired.overdue == ()
