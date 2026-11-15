"""`configure_watch`: the Updates page's weekly watch settings as a protocol amendment."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.watch import WatchPlan, WatchSource
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.watch_config import configure_watch
from tests.helpers import SourcesFor, ready_protocol
from tests.watch_helpers import watch_ready

REASON = "Weekly watch settings saved from the Updates page"


def _fields(exc: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in exc.value.issues]


def test_refuses_agent(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    before = current_protocol(project)
    with pytest.raises(FactoryValidationError) as exc:
        configure_watch(
            project, agent, sources=["openalex"], interval_days=7, until=None, reason=REASON
        )
    assert "actor" in _fields(exc)
    after = current_protocol(project)
    assert before is not None and after is not None
    assert after.protocol_id == before.protocol_id


def test_refuses_unknown_source(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as exc:
        configure_watch(
            project, human, sources=["nowhere"], interval_days=7, until=None, reason=REASON
        )
    assert "sources" in _fields(exc)


def test_refuses_empty_sources_and_bad_interval(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as exc:
        configure_watch(project, human, sources=[], interval_days=0, until=None, reason=REASON)
    assert {"sources", "interval_days"} <= set(_fields(exc))


def test_refuses_past_until(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as exc:
        configure_watch(
            project,
            human,
            sources=["openalex"],
            interval_days=7,
            until=date.today() - timedelta(days=1),
            reason=REASON,
        )
    assert "until" in _fields(exc)


def test_records_amendment_with_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    until = date.today() + timedelta(days=90)
    protocol_id = configure_watch(
        project, human, sources=["openalex"], interval_days=7, until=until, reason=REASON
    )
    current = current_protocol(project)
    assert current is not None and current.protocol_id == protocol_id
    plan = current.spec.watch_plan
    assert plan is not None
    assert plan.snapshot_every == 1 and plan.until == until
    (source,) = plan.sources
    assert (source.source, source.interval_days, source.mode) == ("openalex", 7, "window")
    assert source.overlap_days == 7 and source.full_replay_every == 52


def test_unchanged_is_refused(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    configure_watch(
        project, human, sources=["openalex"], interval_days=7, until=None, reason=REASON
    )
    saved = current_protocol(project)
    with pytest.raises(FactoryValidationError) as exc:
        configure_watch(
            project, human, sources=["openalex"], interval_days=7, until=None, reason=REASON
        )
    assert "watch_plan" in _fields(exc)
    after = current_protocol(project)
    assert saved is not None and after is not None
    assert after.protocol_id == saved.protocol_id


def test_keeps_notices_of_existing_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    existing = WatchPlan(
        sources=(WatchSource(source="openalex", interval_days=30),),
        notices=("openalex",),
        notice_budget=17,
    )
    watch_ready(project, agent, human, mock_sources, plan=existing)
    configure_watch(
        project, human, sources=["openalex"], interval_days=7, until=None, reason=REASON
    )
    current = current_protocol(project)
    assert current is not None and current.spec.watch_plan is not None
    assert current.spec.watch_plan.notices == ("openalex",)
    assert current.spec.watch_plan.notice_budget == 17
    assert current.spec.watch_plan.sources[0].interval_days == 7
