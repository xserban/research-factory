"""Slice 4b acceptance 1-14 on fixtures (offline), one test per criterion.

One living-review world is built once per process (the first test to run builds it from its own
fixtures; the others read the same project, which no test writes to except `test_ac14_rebuild`,
which only rebuilds the index). The world: a pilot project with a screening corpus and a window
watch on openalex; a first cycle (a full replay) whose works two scripted passes include; a
snapshot and a recorded digest; a second cycle (a window) whose status hook observes a Crossref
retraction and a correction, a newer arXiv version and a published-version link; the correction
assessed `affects`; one new work included; one registered conclusion; a second snapshot.

Documented departures from the plan text (see the build report): the protocol fixtures plan only
openalex, so the window source is openalex (its filter declared by a monkeypatch, as the window
tests do), not arXiv; and no better extracted row exists in this world, so criterion 12's three
states are scripted over the facts in their own small world, the facts being computed by the
pure, separately tested `living.facts`. Criteria 10 and 11 (rows, documents) run in plan D's
full-text extraction world.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.living.counts import source_counts
from factory.living.digest_render import to_json, to_markdown
from factory.living.window import window_spec
from factory.model.conclusions import BasisRef
from factory.model.notices import AssessmentDecision, NoticeKind
from factory.model.project import RigorMode
from factory.model.protocol import MethodProfile, protocol_version, search_strategy_hash
from factory.model.screening import PassLabel
from factory.model.search import QueryKind, QuerySpec
from factory.model.watch import WatchSource
from factory.services import conclusions as conclusion_service
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items, calibration_status
from factory.services.check import _findings_as
from factory.services.conclusions import conclusion_diff, register_conclusion
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.digest import agent_digest, digest_build, record_digest
from factory.services.evidence_report import evidence_report
from factory.services.extraction import stale_extractions, unit_states
from factory.services.inbox_watch import inbox_entries
from factory.services.living_hooks import extend_sample_hook, make_status_hook
from factory.services.notices import assess_notice, observed_notices, work_states
from factory.services.prisma import prisma_flow
from factory.services.prisma_update import prisma_update
from factory.services.protocol import amend_protocol, current_protocol, search_authorization
from factory.services.snapshots import snapshot, snapshot_blob, snapshots
from factory.services.versions import aliases, newer_versions, vor_available
from factory.services.watch import CycleSummary, cycles, watch_run, watch_status
from tests.helpers import SourcesFor, ready_protocol
from tests.living_helpers import agree, filler
from tests.notice_helpers import (
    NoticeWorld,
    StatusScript,
    crossref_notices,
    declare_schema,
    dependent_world,
    fetch_arxiv_version,
    notice_record,
    numbered_records,
    status_factories,
)
from tests.test_conclusion_diff import AXIS, NEW, OLD, facts, register, retract
from tests.test_notice_effects import _extract_work, _observe, _second_document, ext_a, world
from tests.test_protocol_rules import _spec
from tests.test_versions import PRE, _answer_by_arxiv
from tests.test_watch_plan import KNOWN_P_ID, PLAN, REQUIRED, _check, _pairs
from tests.watch_helpers import QUERIES, ScriptedSource, adapters, by_text, watch_ready, window_plan

pytestmark = pytest.mark.slow

PUBLISHED = "10.3000/pub"
__all__ = ["ext_a", "world"]  # the extraction world's fixtures, imported for criteria 10 and 11


@dataclass
class Living:
    project: Project
    members: NoticeWorld
    pre: str
    first: str
    second: CycleSummary
    window_specs: list[QuerySpec]
    first_started: datetime
    s1: str
    s2: str
    digest_id: str
    conclusion_id: str
    retracted: str
    corrected: str
    included_after_first: dict[str, Outcome]
    sample_events_before: int


_WORLD: Living | None = None


def _build(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, clock: FixedClock
) -> Living:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "factory.services.protocol.window_filter_sources", lambda: frozenset({"openalex"})
        )
        deps = numbered_records(3)
        members = dependent_world(project, agent, human, mock_sources, [PRE, *deps])
        pre = members.by_title[str(PRE["title"])]
        fetch_arxiv_version(project, pre, "2301.00001v1")
        first_view = cycles(project)[0]
        outcomes = {w: final_outcomes(project)[w] for w in members.included}
        declare_schema(project, agent)
        current = current_protocol(project)
        assert current is not None
        amend_protocol(
            project,
            agent,
            current.spec.model_copy(
                update={"watch_plan": window_plan(overlap_days=2, replay_every=3)}
            ),
            reason="window the watch",
            semantic=True,
            effects={},
        )
        s1 = snapshot(project, human, trigger="human").snapshot_id
        digest_id = record_digest([project], digest_build([project]))
        samples = sum(
            1
            for e in read_all(project.paths.events_dir, project.catalog)
            if e.type == "screening.sample_extended"
        )

        doi = {w: members.doi(w) for w in members.included}
        retracted, corrected = sorted(w for w in members.included if w != pre)[:2]
        crossref = StatusScript(
            "crossref",
            crossref_notices(
                {
                    str(doi[retracted]): [
                        notice_record(
                            str(doi[retracted]),
                            NoticeKind.RETRACTION,
                            "10.2000/ret",
                            date(2025, 1, 2),
                        )
                    ],
                    str(doi[corrected]): [
                        notice_record(str(doi[corrected]), NoticeKind.CORRECTION, "10.2000/cor")
                    ],
                }
            ),
        )
        arxiv = StatusScript(
            "arxiv", _answer_by_arxiv({"2301.00001": 2}, {"2301.00001": PUBLISHED})
        )
        factories = status_factories(
            crossref=crossref, openalex=StatusScript("openalex"), arxiv=arxiv
        )
        clock.advance(timedelta(days=8))
        source = ScriptedSource(by_text({"attention": [filler(3, first=100)]}))
        second = watch_run(
            project,
            sources=adapters(source),
            trigger="scheduler",
            after_runs=(extend_sample_hook, make_status_hook(factories)),
        )
        assert second is not None
        from factory.services.screening import live_decisions  # noqa: F401

        protocol = current_protocol(project)
        assert protocol is not None
        chosen = next(
            w for w in sorted(second.new_work_ids) if w not in set(calibration_items(project))
        )
        agree(project, agent, chosen, protocol.protocol_id, "include")
        notice = next(
            n
            for n in observed_notices(project)
            if n.work_id == corrected and n.kind is NoticeKind.CORRECTION
        )
        assess_notice(
            project,
            human,
            notice.notice_id,
            AssessmentDecision.AFFECTS,
            fields=("latency",),
            rationale="the figure was corrected",
        )
        clean = next(w for w in sorted(members.included) if w not in (pre, retracted, corrected))
        conclusion_id = register_conclusion(
            project,
            human,
            "The gating mechanism suffices.",
            [BasisRef(kind="work", ref=clean)],
            None,
        )
        s2 = snapshot(project, human, trigger="human").snapshot_id
    return Living(
        project=project,
        members=members,
        pre=pre,
        first=first_view.cycle_id,
        second=second,
        window_specs=source.specs,
        first_started=first_view.started_at,
        s1=s1,
        s2=s2,
        digest_id=digest_id,
        conclusion_id=conclusion_id,
        retracted=retracted,
        corrected=corrected,
        included_after_first=outcomes,
        sample_events_before=samples,
    )


@pytest.fixture
def living(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, clock: FixedClock
) -> Living:
    global _WORLD
    if _WORLD is None:
        _WORLD = _build(project, agent, human, mock_sources, clock)
    return _WORLD


def _events(project: Project, type_: str) -> list[object]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == type_]


# --- 1 and 2: the protocol section ---


def test_ac01_hash_stability(living: Living) -> None:
    from tests.helpers import pilot_protocol_spec

    bare = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert protocol_version(bare) == KNOWN_P_ID  # a log without watch_plan keeps its P@
    planned = bare.model_copy(update={"watch_plan": PLAN})
    assert protocol_version(planned) != KNOWN_P_ID
    assert search_strategy_hash(planned) == search_strategy_hash(bare)  # S@ unchanged
    project = living.project
    current = current_protocol(project)
    assert current is not None and current.spec.watch_plan is not None
    without = current.spec.model_copy(update={"watch_plan": None})
    assert protocol_version(without) != current.protocol_id
    assert search_strategy_hash(without) == search_strategy_hash(current.spec)
    planned_query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    assert search_authorization(project, planned_query, deviation_id=None) == []  # PRESS carries


def test_ac02_readiness(living: Living) -> None:
    living_spec = _spec(method_profile=MethodProfile.LIVING_REVIEW)
    assert REQUIRED in _pairs(_check(living_spec, RigorMode.PILOT).gaps)
    exploratory = _check(living_spec, RigorMode.EXPLORATORY)
    assert "watch_plan" not in [i.field for i in exploratory.errors + exploratory.gaps]
    with pytest.raises(ValidationError):
        WatchSource(source="openalex", interval_days=7, mode="window")  # no full_replay_every
    # The adapter has no listing-date filter here (the world declared one by monkeypatch only
    # while it was built): a window plan is refused and nothing is written.
    project = living.project
    before = len(read_all(project.paths.events_dir, project.catalog))
    current = current_protocol(project)
    assert current is not None
    with pytest.raises(FactoryValidationError):
        amend_protocol(
            project,
            project.human_actor(),
            current.spec.model_copy(update={"watch_plan": window_plan()}),
            reason="window",
            semantic=True,
            effects={},
        )
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


# --- 3 to 7: the cycles ---


def test_ac03_cycle_is_search_runs(living: Living) -> None:
    project = living.project
    events = read_all(project.paths.events_dir, project.catalog)
    [started] = [
        e for e in events if e.type == "watch.cycle_started" and e.refs[0] == living.second.cycle_id
    ]
    [finished] = [
        e
        for e in events
        if e.type == "watch.cycle_finished" and e.refs[0] == living.second.cycle_id
    ]
    assert started.id < finished.id and finished.payload["status"] == "complete"
    planned = [q for q in current_protocol(project).spec.queries if q.source == "openalex"]  # type: ignore[union-attr]
    run_ids = finished.payload["run_ids"]
    assert isinstance(run_ids, list) and len(run_ids) == len(planned)
    runs = {e.payload["run_id"]: e.payload for e in events if e.type == "search.run_finished"}
    assert all(runs[r]["status"] == "complete" for r in run_ids)
    recomputed = [c.model_dump(mode="json") for c in source_counts(project, living.second.cycle_id)]
    assert finished.payload["counts"] == recomputed


def test_ac04_due_and_idempotence(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, clock: FixedClock
) -> None:
    watch_ready(project, agent, human, mock_sources)
    source = ScriptedSource(by_text({"attention": [[]], "transformers": [[]]}))

    def run() -> CycleSummary | None:
        return watch_run(project, sources=adapters(source), trigger="scheduler")

    assert run() is not None  # never run: due
    count = len(read_all(project.paths.events_dir, project.catalog))
    assert run() is None  # the same time: nothing
    clock.advance(timedelta(days=6))
    assert run() is None and not any(s.due for s in watch_status(project).sources)
    clock.advance(timedelta(days=2))
    assert run() is not None  # after the interval: one cycle
    assert run() is None  # and a second call at that time runs nothing
    assert len(read_all(project.paths.events_dir, project.catalog)) > count
    assert len(cycles(project)) == 2


def test_ac05_window(living: Living) -> None:
    project = living.project
    expected = (living.first_started - timedelta(days=2)).date().isoformat()
    # cycle 1 was a full replay (no earlier window), cycle 2 a window.
    first, second = cycles(project)[0], cycles(project)[1]
    assert first.full_replay_sources == ("openalex",) and second.full_replay_sources == ()
    assert [s.filters for s in living.window_specs] == [{"listed_since": expected}]
    window = living.window_specs[0]
    assert window.text == "attention"  # the planned text plus the window filter
    foreign = f"wcy_{'0' * 26}"
    assert search_authorization(project, window, deviation_id=None, cycle_id=foreign)
    assert search_authorization(project, window, deviation_id=None)  # needs its cycle
    assert window == window_spec(QUERIES[0], date.fromisoformat(expected))


def test_ac06_incremental_dedup_equivalence(living: Living) -> None:
    project = living.project
    before = len(read_all(project.paths.events_dir, project.catalog))
    dedup_run(project)  # the full reconciler after incremental dedup in both cycles
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_ac07_screening_of_updates(living: Living) -> None:
    project = living.project
    new = set(living.second.new_work_ids)
    entries = inbox_entries(project, route="database:openalex")
    pending = {e.work_id for e in entries}
    outcomes = final_outcomes(project)
    assert pending <= new and pending == {w for w in new if outcomes[w] is Outcome.PENDING}
    assert all(e.route_ref == living.second.cycle_id for e in entries if e.work_id in new)
    extended = [e for e in _events(project, "screening.sample_extended")]
    assert len(extended) >= 2
    latest = extended[-1]
    assert new <= set(latest.payload["considered"]) and "random_seed" in latest.payload  # type: ignore[attr-defined]
    assert len(_events(project, "calibration.drawn")) == 1  # calibration is not re-drawn
    assert calibration_status(project).drawn == len(calibration_items(project))


# --- 8: the update flow ---


def test_ac08_prisma_update_flow(living: Living) -> None:
    project = living.project
    update = prisma_update(project, since=living.s1, until=living.s2)
    new = set(living.second.new_work_ids)
    assert update.screened == len(new)
    identified = sum(update.identified_databases.values()) + sum(update.identified_other.values())
    assert identified - update.duplicates_removed == update.screened  # identities hold
    assert update.excluded_total + update.pending + update.included == update.screened
    assert update.previous_included == len(living.members.included)
    flow = prisma_flow(project)
    assert flow.screened >= update.screened  # the cumulative flow covers both cycles
    assert snapshot_blob(project, living.s2).update is not None  # closed updates are pinned


# --- 9 to 11: notices, propagation, versions ---


def test_ac09_notices(living: Living) -> None:
    project = living.project
    observed = observed_notices(project)
    retractions = [n for n in observed if n.kind is NoticeKind.RETRACTION]
    assert [(n.work_id, n.source) for n in retractions] == [(living.retracted, "crossref")]
    assert len([n for n in observed if n.work_id == living.retracted]) == 1  # once
    state = work_states(project)[living.retracted]
    assert (state.flag, state.synthesis) == ("retracted", "excluded")
    codes = {f.code: f for f in _findings_as(project, RigorMode.PILOT)}
    assert living.retracted in codes["included-retracted"].refs
    assert {e.reason for e in evidence_report(project).excluded} <= {"retracted", "no-final-row"}
    assert final_outcomes(project)[living.retracted] is Outcome.INCLUDED  # no outcome changed
    assert (
        final_outcomes(project)[living.retracted] is living.included_after_first[living.retracted]
    )


def test_ac10_bounded_propagation(project: Project, ext_a: Actor, world: list[str]) -> None:
    first, second = world[0], world[1]
    plain1, latency1 = _extract_work(project, ext_a, first)
    plain2, latency2 = _extract_work(project, ext_a, second)
    before = {(s.work_id, s.pass_label): (s.state, s.reason) for s in unit_states(project)}
    notice = _observe(project, first, NoticeKind.CORRECTION, "10.2000/corr")
    assess_notice(
        project,
        project.human_actor(),
        notice,
        AssessmentDecision.AFFECTS,
        fields=("latency",),
        rationale="the latency figure was corrected",
    )
    assert stale_extractions(project) == {latency1}  # exactly that work's rows with that field
    after = {(s.work_id, s.pass_label): (s.state, s.reason) for s in unit_states(project)}
    assert {k for k in after if after[k] != before[k]} == {(first, PassLabel.A)}
    assert not {plain1, plain2, latency2} & stale_extractions(project)


def test_ac11_versions(living: Living) -> None:
    project = living.project
    [newer] = newer_versions(project)
    assert (newer.work_id, newer.source_version) == (living.pre, "2301.00001v2")
    assert vor_available(project) == [living.pre]
    assert aliases(project, living.pre).doi == PUBLISHED  # linked, not merged away
    assert not [e for e in _events(project, "fulltext.fetch_started")][1:]  # nothing was fetched
    outcomes = final_outcomes(project)
    assert all(outcomes[w] is o for w, o in living.included_after_first.items())  # no decision
    codes = {f.code for f in _findings_as(project, RigorMode.PILOT)}
    assert {"newer-version-available", "version-of-record-available"} <= codes


def test_ac11_preferred_document(project: Project, ext_a: Actor, world: list[str]) -> None:
    from factory.services.document_read import default_conversion
    from factory.services.versions import prefer_document

    first, second = world[0], world[1]
    first_rows = set(_extract_work(project, ext_a, first))
    second_rows = set(_extract_work(project, ext_a, second))
    preferred = _second_document(project, first)
    prefer_document(project, project.human_actor(), first, preferred, "complete source copy")
    served = default_conversion(project, first)
    assert served is not None and served.document_id == preferred  # default_conversion serves it
    assert stale_extractions(project) == first_rows  # that work's rows only
    assert not stale_extractions(project) & second_rows


# --- 12: conclusions ---


def test_ac12_conclusions(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members = dependent_world(project, agent, human, mock_sources, numbered_records(3))
    script = {"current": facts(OLD)}
    monkeypatch.setattr(conclusion_service, "current_facts", lambda p: script["current"])
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError):  # an unresolvable basis is refused
        register_conclusion(
            project, human, "Unfounded.", [BasisRef(kind="work", ref="rf:unknown-deadbeef")], None
        )
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    monkeypatch.setattr(
        conclusion_service, "_resolves", lambda p, ref: True
    )  # rows: see test_conclusions_rows
    cid = register(members, human)
    snapshot(project, human, trigger="human")
    assert [d.state for d in conclusion_diff(project)] == ["unchanged"]  # no row added
    script["current"] = facts(NEW, rows=3, frontier=(OLD, NEW))  # a better row
    [changed] = conclusion_diff(project)
    assert changed.conclusion_id == cid and changed.state == "changed"
    assert AXIS in (changed.facts.groups[0].frontier_added if changed.facts else {})
    retract(project, members.included[0])  # the basis work is retracted
    assert [d.state for d in conclusion_diff(project)] == ["basis-affected"]


# --- 13: the digest ---


def test_ac13_digest(living: Living) -> None:
    project = living.project
    built = digest_build([project])
    [part] = built.projects
    assert part.since_event is not None
    assert {c.work_id for c in part.new_candidates.items} == set(living.second.new_work_ids)
    assert all(c.query_ids for c in part.new_candidates.items)
    assert set(part.open_decisions) >= {"screening-disagreements", "notice-assessments"}
    assert part.open_decisions["notice-assessments"] == 1  # the retraction
    assert {n.kind for n in part.notices.items} == {"retraction", "correction"}
    assert {v.kind for v in part.versions.items} == {"newer-version", "version-of-record"}
    [diff] = part.conclusions
    assert diff.conclusion_id == living.conclusion_id
    for rendered in (to_markdown(built), to_json(built), to_json(agent_digest(built))):
        assert "statement" not in rendered and "gating mechanism suffices" not in rendered
        assert re.search(r"\b(SEED|NEG)\d{2,}\b", rendered) is None
        for word in ("abstract", "verdict", "recommend", "relevan"):
            assert word not in rendered.lower()
    again = digest_build([project])
    assert to_json(again) == to_json(built) and to_markdown(again) == to_markdown(built)
    project.index.rebuild()
    rebuilt = digest_build([project])
    assert to_json(rebuilt) == to_json(built) and to_markdown(rebuilt) == to_markdown(built)
    assert json.loads(to_json(built))["projects"][0]["slug"] == project.paths.slug


# --- 14: rebuild ---


def test_ac14_rebuild(living: Living) -> None:
    project = living.project
    names = (
        "watch_cycles",
        "watch_cycle_runs",
        "snapshots",
        "notices",
        "notice_assessments",
        "version_observations",
        "version_links",
        "work_aliases",
        "conclusions",
        "digests",
    )

    def tables() -> dict[str, list[tuple[object, ...]]]:
        with project.index.connect() as conn:
            return {
                n: [tuple(r) for r in conn.exec_driver_sql(f"SELECT * FROM {n} ORDER BY 1, 2")]
                for n in names
            }

    before_hash, before = project.index.state_hash(), tables()
    assert all(before[n] for n in names)  # every living table holds rows
    assert project.index.rebuild() == before_hash
    assert tables() == before
    assert [s.snapshot_id for s in snapshots(project)] == [living.s1, living.s2]
    _ = Settings, ready_protocol  # imported for fixtures of the shared helpers
