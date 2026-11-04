"""The audit top-up of a living review: only new agreements, the recomputed size, 3:1 weighting."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.screening import AuditSampled, Channel
from factory.services.audit import audit_record, audit_report, audit_sample, audit_shortfall
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening_stats import audit_size
from factory.services.search import list_works
from factory.sources.registry import SourceFactory
from tests.helpers import _of_type
from tests.test_audit import ACCEPTANCE_RANDOM_WORKS, _agree, _fields, _population, _split_160
from tests.test_screening_next import _late

SourcesFor = Callable[..., Mapping[str, SourceFactory]]

FRACTION = 0.5
MINIMUM = 50


def _protocol_id(project: Project) -> str:
    current = current_protocol(project)
    assert current is not None
    return current.protocol_id


def _audited(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[AuditSampled, list[str]]:
    """160 agreed works (120 exclusions, 40 inclusions), audited at 50 % (80 works) and labelled
    as the agreed verdict. Returns the first audit and the ordinary works."""
    _, ordinary = _population(
        project, agent, human, mock_sources, random_works=ACCEPTANCE_RANDOM_WORKS
    )
    current = current_protocol(project)
    assert current is not None
    screening = current.spec.screening.model_copy(
        update={"audit_fraction": FRACTION, "audit_minimum": MINIMUM}
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"screening": screening}),
        reason="size the audit",
        semantic=True,
        effects={},
    )
    _split_160(project, agent, _protocol_id(project), ordinary)
    first = audit_sample(project, human, random_seed=7)
    assert len(first.work_ids) == 80
    _label(project, human, first, flip=())
    return first, ordinary


def _label(project: Project, human: Actor, sampled: AuditSampled, flip: tuple[str, ...]) -> None:
    """Label every item of an audit as the agreed verdict (flipped for the works in `flip`)."""
    with project.index.connect() as conn:
        agreed = {
            str(w): str(v)
            for w, v in conn.execute(
                text("SELECT work_id, agreed_verdict FROM audit_items WHERE audit_id = :a"),
                {"a": sampled.audit_id},
            ).all()
        }
    for work, verdict in agreed.items():
        if work in flip:
            verdict = "include" if verdict == "exclude" else "exclude"
        criterion = "EX01" if verdict == "exclude" else None
        audit_record(project, human, sampled.audit_id, work, verdict, criterion, Channel.CLI)


def _late_agreed(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    first: int = 1000,
    count: int = 40,
    exclusions: int = 30,
) -> list[str]:
    """`count` new works that both passes decide: `exclusions` excluded, the rest included."""
    before = {w.id for w in list_works(project)}
    _late(project, human, mock_sources, first, count)
    new = sorted(w.id for w in list_works(project) if w.id not in before)
    assert len(new) == count
    _agree(project, agent, new[:exclusions], _protocol_id(project), exclude=True)
    _agree(project, agent, new[exclusions:], _protocol_id(project), exclude=False)
    return new


def test_top_up_draws_only_new_agreements(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    first, _ordinary = _audited(project, agent, human, mock_sources)
    new = _late_agreed(project, agent, human, mock_sources)
    top = audit_sample(project, human, random_seed=9, top_up=True)
    assert top.top_up_of == first.audit_id
    assert set(top.work_ids) <= set(new)
    assert not set(top.work_ids) & set(first.work_ids)
    assert len(_of_type(project, "audit.sampled")) == 2


def test_top_up_size_meets_recomputed_rule(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    first, _ordinary = _audited(project, agent, human, mock_sources)
    _late_agreed(project, agent, human, mock_sources)  # N grows from 160 to 200
    assert audit_shortfall(project) == audit_size(200, FRACTION, MINIMUM) - 80 == 20
    top = audit_sample(project, human, random_seed=9, top_up=True)
    assert len(first.work_ids) + len(top.work_ids) == audit_size(200, FRACTION, MINIMUM)
    assert top.population == 200
    assert audit_shortfall(project) == 0


def test_top_up_keeps_3_to_1_weighting(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _audited(project, agent, human, mock_sources)
    _late_agreed(project, agent, human, mock_sources)
    top = audit_sample(project, human, random_seed=9, top_up=True)
    assert (top.exclusions, top.inclusions) == (15, 5)  # floor(0.75 * 20 + 0.5) = 15


def test_top_up_refused_without_previous_audit(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(
        project, agent, human, mock_sources, random_works=ACCEPTANCE_RANDOM_WORKS
    )
    _split_160(project, agent, protocol_id, ordinary)
    before = len(_of_type(project, "audit.sampled"))
    with pytest.raises(FactoryValidationError) as exc:
        audit_sample(project, human, random_seed=9, top_up=True)
    assert _fields(exc) == ["top_up"]
    assert len(_of_type(project, "audit.sampled")) == before
    assert audit_shortfall(project) == 0


def test_top_up_refused_with_unlabelled_items_or_no_shortfall(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    first, _ordinary = _audited(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as exc:  # nothing new, no shortfall
        audit_sample(project, human, random_seed=9, top_up=True)
    assert _fields(exc) == ["top_up"]
    _late_agreed(project, agent, human, mock_sources)
    top = audit_sample(project, human, random_seed=9, top_up=True)
    _late_agreed(project, agent, human, mock_sources, first=2000, count=40)
    with pytest.raises(FactoryValidationError) as exc:  # the last draw is not yet labelled
        audit_sample(project, human, random_seed=10, top_up=True)
    assert _fields(exc) == ["top_up"]
    assert top.top_up_of == first.audit_id


def test_top_up_by_agent_refused(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _audited(project, agent, human, mock_sources)
    _late_agreed(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as exc:
        audit_sample(project, agent, random_seed=9, top_up=True)
    assert "actor" in _fields(exc)


def test_legacy_audit_events_project_unchanged(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=False)
    sampled = audit_sample(project, human, random_seed=7)
    assert sampled.top_up_of is None
    legacy = AuditSampled.model_validate(
        {
            "audit_id": sampled.audit_id,
            "work_ids": list(sampled.work_ids),
            "random_seed": 7,
            "population": sampled.population,
            "exclusions": sampled.exclusions,
            "inclusions": sampled.inclusions,
        }
    )
    assert legacy.top_up_of is None
    with project.index.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_top_ups")).scalar_one() == 0


def test_error_rate_over_all_labels(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    first, _ordinary = _audited(project, agent, human, mock_sources)
    _late_agreed(project, agent, human, mock_sources)
    top = audit_sample(project, human, random_seed=9, top_up=True)
    excluded = [w for w in top.work_ids if _agreed(project, top.audit_id, w) == "exclude"]
    _label(project, human, top, flip=(excluded[0],))
    report = audit_report(project)
    assert report is not None and report.audit_id == top.audit_id
    assert report.sample_size == len(first.work_ids) + len(top.work_ids) == 100
    assert report.labelled == 100
    # Agreed exclusions over both draws: 60 + 15; one is overturned.
    assert report.rates.false_exclusion == pytest.approx(1 / 75)
    assert report.rates.false_inclusion == 0.0
    assert report.rates.weighted is not None


def _agreed(project: Project, audit_id: str, work: str) -> str:
    with project.index.connect() as conn:
        return str(
            conn.execute(
                text("SELECT agreed_verdict FROM audit_items WHERE audit_id=:a AND work_id=:w"),
                {"a": audit_id, "w": work},
            ).scalar_one()
        )
