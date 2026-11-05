"""The protocol's `watch_plan`: hash, readiness, PRESS carry-over (slice 4b, ruling 4)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.project import RigorMode
from factory.model.protocol import (
    AMENDABLE_FIELDS,
    MethodProfile,
    ProtocolSpec,
    protocol_version,
    search_strategy_hash,
)
from factory.model.search import QueryKind, QuerySpec
from factory.model.watch import WatchPlan, WatchSource
from factory.services.context import Project
from factory.services.protocol import (
    amend_protocol,
    current_protocol,
    record_protocol,
    search_authorization,
)
from factory.services.protocol_rules import ProtocolCheck, protocol_issues, watch_plan_gaps
from tests.helpers import SourcesFor, pilot_protocol_spec, ready_protocol, record_pilot_question
from tests.screening_helpers import KNOWN_SOURCES, PROBES, QID, QUESTION, _spec

KNOWN_P_ID = "P@1e7c316e"
"""pilot_protocol_spec("Q@aaaaaaaa", "prb_1"): fixed before `watch_plan` existed."""

PLAN = WatchPlan(sources=(WatchSource(source="openalex", interval_days=7),))
REQUIRED = ("watch_plan", "required for living-review")


def _check(
    spec: ProtocolSpec,
    mode: RigorMode = RigorMode.PILOT,
    window_sources: frozenset[str] = frozenset(),
) -> ProtocolCheck:
    return protocol_issues(
        spec,
        question=QUESTION,
        current_question_id=QID,
        mode=mode,
        seeds=[],
        probes=PROBES,
        known_sources=KNOWN_SOURCES,
        window_sources=window_sources,
    )


def _pairs(issues: Sequence[ValidationIssue]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in issues]


def test_absent_watch_plan_keeps_protocol_id() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.watch_plan is None
    assert (
        protocol_version(spec)
        == protocol_version(spec.model_copy(update={"watch_plan": None}))
        == KNOWN_P_ID
    )


def test_watch_plan_changes_p_but_not_s() -> None:
    a = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    b = a.model_copy(update={"watch_plan": PLAN})
    assert protocol_version(a) != protocol_version(b)
    assert search_strategy_hash(a) == search_strategy_hash(b)
    assert "watch_plan" in AMENDABLE_FIELDS


def test_source_order_does_not_change_the_hash() -> None:
    x = WatchSource(source="arxiv", interval_days=3)
    y = WatchSource(source="openalex", interval_days=7)
    base = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    one = base.model_copy(update={"watch_plan": WatchPlan(sources=(x, y))})
    two = base.model_copy(update={"watch_plan": WatchPlan(sources=(y, x))})
    assert protocol_version(one) == protocol_version(two)


def test_watch_plan_keeps_s_hash_and_press(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    current = current_protocol(project)
    assert current is not None
    planned = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    assert search_authorization(project, planned, deviation_id=None) == []
    amended = current.spec.model_copy(update={"watch_plan": PLAN})
    amend_protocol(project, agent, amended, reason="watch", semantic=True, effects={})
    after = current_protocol(project)
    assert after is not None and after.protocol_id != current.protocol_id
    assert search_authorization(project, planned, deviation_id=None) == []


def test_window_requires_full_replay_every() -> None:
    with pytest.raises(ValidationError):
        WatchSource(source="arxiv", interval_days=7, mode="window")
    ok = WatchSource(source="arxiv", interval_days=7, mode="window", full_replay_every=4)
    assert ok.overlap_days == 7


def test_watch_plan_rejects_duplicate_sources_and_empty() -> None:
    one = WatchSource(source="arxiv", interval_days=1)
    with pytest.raises(ValidationError):
        WatchPlan(sources=(one, one))
    with pytest.raises(ValidationError):
        WatchPlan(sources=())


def test_living_review_needs_watch_plan_in_pilot() -> None:
    spec = _spec(method_profile=MethodProfile.LIVING_REVIEW)
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        assert REQUIRED in _pairs(_check(spec, mode).gaps)
    declared = _spec(method_profile=MethodProfile.LIVING_REVIEW, watch_plan=PLAN)
    assert REQUIRED not in _pairs(_check(declared).gaps)


def test_watch_plan_permitted_for_other_profiles() -> None:
    check = _check(_spec(watch_plan=PLAN))
    assert not [f for f, _ in _pairs(check.errors + check.gaps) if f.startswith("watch_plan")]


def test_living_review_gap_in_exploratory() -> None:
    spec = _spec(method_profile=MethodProfile.LIVING_REVIEW)
    check = _check(spec, RigorMode.EXPLORATORY)
    assert "watch_plan" not in [i.field for i in check.errors + check.gaps]
    assert _pairs(watch_plan_gaps(spec, RigorMode.EXPLORATORY)) == [REQUIRED]
    assert watch_plan_gaps(_spec(), RigorMode.EXPLORATORY) == []


def test_watch_source_must_be_included() -> None:
    plan = WatchPlan(sources=(WatchSource(source="arxiv", interval_days=7),))
    errors = _pairs(_check(_spec(watch_plan=plan)).errors)
    assert ("watch_plan.sources[0].source", "not an included source") in errors


def test_window_on_adapter_without_filter_refused() -> None:
    plan = WatchPlan(
        sources=(
            WatchSource(source="openalex", interval_days=7, mode="window", full_replay_every=4),
        )
    )
    refused = _pairs(_check(_spec(watch_plan=plan)).errors)
    assert ("watch_plan.sources[0].mode", "source has no window filter") in refused
    allowed = _check(_spec(watch_plan=plan), window_sources=frozenset({"openalex"}))
    assert not [f for f, _ in _pairs(allowed.errors) if f.startswith("watch_plan")]


def test_invalid_watch_plan_writes_nothing(project: Project, agent: Actor) -> None:
    qid = record_pilot_question(project, agent)
    bad_plan = WatchPlan(sources=(WatchSource(source="pubmed", interval_days=7),))
    spec = pilot_protocol_spec(qid, "prb_1").model_copy(update={"watch_plan": bad_plan})
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError):
        record_protocol(project, agent, spec, ready=False)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
