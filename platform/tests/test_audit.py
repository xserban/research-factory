"""The audit of agreed decisions: stratified sample, human labels, error rates and the open-audit
rule (acceptance 18, R-37).

The corpus is built as in the screening tests. Ordinary works are those outside the calibration set;
every ordinary work is decided by both passes, so every ordinary work is an agreed dual-coded work.
"""

from collections.abc import Callable, Mapping

import pytest
from sqlalchemy import text

from factory.canonical import population_digest
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.screening import Channel, PassJoined, PassLabel
from factory.services.agreement import AgreedWork, agreed_works
from factory.services.audit import audit_record, audit_report, audit_sample
from factory.services.calibration import calibration_items
from factory.services.context import Project
from factory.services.screening import open_pass
from factory.services.screening_stats import AUDIT_ERROR_CEILING
from factory.services.search import list_works
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION
from tests.test_calibration import _decide
from tests.test_screening_next import _draw, _events, _setup

SourcesFor = Callable[..., Mapping[str, SourceFactory]]

ACCEPTANCE_RANDOM_WORKS = 181
"""Seed works (9) plus random works, less the 30 calibration works, gives 160 ordinary works."""


def _population(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    random_works: int = 0,
) -> tuple[str, list[str]]:
    """A ready protocol, a drawn calibration set and both passes opened over full dual coding.
    Returns the protocol id and the ordinary works, sorted."""
    protocol_id = _setup(
        project, agent, human, mock_sources, dual_sample=1.0, random_works=random_works
    )
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    calibration = set(calibration_items(project))
    ordinary = sorted(work.id for work in list_works(project) if work.id not in calibration)
    return protocol_id, ordinary


def _agree(
    project: Project,
    agent: Actor,
    works: list[str],
    protocol_id: str,
    *,
    exclude: bool,
) -> None:
    for work in works:
        verdict, criterion = ("exclude", "EX01") if exclude else ("include", None)
        _decide(project, agent, work, "A", "screening", verdict, criterion, protocol_id)
        _decide(project, agent, work, "B", "screening", verdict, criterion, protocol_id)


def _split_160(project: Project, agent: Actor, protocol_id: str, ordinary: list[str]) -> None:
    """120 agreed exclusions (EX01 in both passes) then 40 agreed inclusions."""
    _agree(project, agent, ordinary[:120], protocol_id, exclude=True)
    _agree(project, agent, ordinary[120:], protocol_id, exclude=False)


def _fields(exc: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in exc.value.issues]


# --- Sample: size, stratification, refusals (acceptance 18, ruling 3) ---


def test_audit_draws_minimum_fifty_three_to_one(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(
        project, agent, human, mock_sources, random_works=ACCEPTANCE_RANDOM_WORKS
    )
    assert len(ordinary) == 160
    _split_160(project, agent, protocol_id, ordinary)

    sampled = audit_sample(project, human, random_seed=7)

    assert sampled.population == 160
    assert len(sampled.work_ids) == 50
    assert sampled.exclusions == 38
    assert sampled.inclusions == 12
    assert set(sampled.work_ids) <= set(ordinary)


def test_audit_all_when_fewer_than_minimum(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary[:1], protocol_id, exclude=True)
    _agree(project, agent, ordinary[1:], protocol_id, exclude=False)

    sampled = audit_sample(project, human, random_seed=7)

    assert sampled.population == len(ordinary)
    assert list(sampled.work_ids) == ordinary


def test_audit_refused_before_agreement(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _population(project, agent, human, mock_sources)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        audit_sample(project, human, random_seed=7)

    assert _fields(exc) == ["passes"]
    assert len(_events(project)) == before


def test_audit_sample_is_human_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=False)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        audit_sample(project, agent, random_seed=7)

    assert _fields(exc) == ["actor"]
    assert len(_events(project)) == before


def test_unsure_with_exclude_is_not_an_agreed_work(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary[1:], protocol_id, exclude=False)
    _decide(project, agent, ordinary[0], "A", "screening", "unsure", None, protocol_id)
    _decide(project, agent, ordinary[0], "B", "screening", "exclude", "EX01", protocol_id)

    agreed = agreed_works(project)
    sampled = audit_sample(project, human, random_seed=7)

    assert ordinary[0] not in agreed
    assert ordinary[0] not in sampled.work_ids
    assert sampled.population == len(ordinary) - 1


def test_one_open_audit_until_the_agreed_set_changes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=False)
    audit_sample(project, human, random_seed=7)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        audit_sample(project, human, random_seed=8)

    assert _fields(exc) == ["passes"]
    assert len(_events(project)) == before

    # Pass B now excludes one agreed include: the agreed set changes, so a new audit may be drawn.
    with project.index.connect() as conn:
        decision_id = str(
            conn.execute(
                text(
                    "SELECT decision_id FROM decisions WHERE work_id = :w AND pass_label = 'B' "
                    "AND superseded_by IS NULL"
                ),
                {"w": ordinary[0]},
            ).one()[0]
        )
    _decide(
        project,
        agent,
        ordinary[0],
        "B",
        "screening",
        "exclude",
        "EX01",
        protocol_id,
        supersedes=decision_id,
    )

    again = audit_sample(project, human, random_seed=8)

    assert again.population == len(ordinary) - 1


# --- Labels and error rates (acceptance 18, R-37) ---


def test_audit_record_rejects_work_outside_sample(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(
        project, agent, human, mock_sources, random_works=ACCEPTANCE_RANDOM_WORKS
    )
    _split_160(project, agent, protocol_id, ordinary)
    sampled = audit_sample(project, human, random_seed=7)
    outside = next(work for work in ordinary if work not in sampled.work_ids)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        audit_record(project, human, sampled.audit_id, outside, "include", None, Channel.CLI)

    assert _fields(exc) == ["work_id"]
    assert len(_events(project)) == before


def test_error_rates_reported_and_ceiling_flagged(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(
        project, agent, human, mock_sources, random_works=ACCEPTANCE_RANDOM_WORKS
    )
    _split_160(project, agent, protocol_id, ordinary)
    sampled = audit_sample(project, human, random_seed=7)
    agreed = agreed_works(project)
    drawn_excl = [w for w in sampled.work_ids if agreed[w].verdict == "exclude"]
    drawn_incl = [w for w in sampled.work_ids if agreed[w].verdict == "include"]
    assert len(drawn_excl) == 38
    overturned = set(drawn_excl[:2])

    for work in drawn_excl:
        if work in overturned:
            audit_record(project, human, sampled.audit_id, work, "include", None, Channel.CLI)
        else:
            audit_record(project, human, sampled.audit_id, work, "exclude", "EX01", Channel.CLI)
    for work in drawn_incl:
        audit_record(project, human, sampled.audit_id, work, "include", None, Channel.CLI)

    report = audit_report(project)

    assert report is not None
    assert report.audit_id == sampled.audit_id
    assert report.sample_size == 50
    assert report.labelled == 50
    assert report.rates.false_exclusion == pytest.approx(2 / 38)
    assert report.rates.false_inclusion == 0.0
    assert report.ceiling == AUDIT_ERROR_CEILING
    assert report.above_ceiling is True
    assert report.enforced is False
    assert report.criteria_implicated == ["EX01"]


def test_audit_record_channel_mcp_refused_for_pass_session(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=False)
    sampled = audit_sample(project, human, random_seed=7)
    joined = PassJoined(pass_label=PassLabel.A, session=SESSION, model="claude-opus-5-5")
    project.record(
        [
            project.events.make(
                "screening.pass_joined",
                joined,
                agent,
                input_blob=project.blobs.put_json({"pass": "A"}),
            )
        ]
    )
    work = sampled.work_ids[0]

    with pytest.raises(FactoryValidationError) as exc:
        audit_record(project, human, sampled.audit_id, work, "include", None, Channel.MCP)

    assert _fields(exc) == ["channel"]
    assert audit_record(project, human, sampled.audit_id, work, "include", None, Channel.CLI)


def test_audit_sample_reproducible_on_rebuild(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(
        project, agent, human, mock_sources, random_works=ACCEPTANCE_RANDOM_WORKS
    )
    _split_160(project, agent, protocol_id, ordinary)
    sampled = audit_sample(project, human, random_seed=7)

    def rows() -> list[tuple[str, str, str | None]]:
        with project.index.connect() as conn:
            found = conn.execute(
                text(
                    "SELECT work_id, agreed_verdict, human_verdict FROM audit_items "
                    "WHERE audit_id = :a ORDER BY work_id"
                ),
                {"a": sampled.audit_id},
            ).all()
        return [(str(w), str(a), None if h is None else str(h)) for w, a, h in found]

    before = rows()
    state = project.index.state_hash()

    assert project.index.rebuild() == state
    assert rows() == before
    assert sorted(sampled.work_ids) == [w for w, _, _ in before]
    assert {w for w, a, _ in before if a == "exclude"} == {
        w for w in sampled.work_ids if agreed_works(project)[w].verdict == "exclude"
    }


def test_audit_refused_for_bad_seed_and_for_no_agreed_work(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as bad_seed:
        audit_sample(project, human, random_seed=-1)
    with pytest.raises(FactoryValidationError) as nothing:
        audit_sample(project, human, random_seed=7)

    assert _fields(bad_seed) == ["random_seed"]
    assert _fields(nothing) == ["passes"]
    assert len(_events(project)) == before
    assert ordinary and protocol_id


def test_audit_report_is_none_before_any_sample(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _population(project, agent, human, mock_sources)

    assert audit_report(project) is None


def test_audit_record_rejects_unknown_criterion_and_invalid_verdict(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=False)
    sampled = audit_sample(project, human, random_seed=7)
    work = sampled.work_ids[0]
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as unknown:
        audit_record(project, human, sampled.audit_id, work, "exclude", "EX09", Channel.CLI)
    with pytest.raises(FactoryValidationError) as invalid:
        audit_record(project, human, sampled.audit_id, work, "maybe", None, Channel.CLI)

    assert _fields(unknown) == ["criterion"]
    assert _fields(invalid) == ["verdict"]
    assert len(_events(project)) == before


def _live_decision(project: Project, work_id: str, pass_label: str) -> str:
    with project.index.connect() as conn:
        return str(
            conn.execute(
                text(
                    "SELECT decision_id FROM decisions WHERE work_id = :w AND pass_label = :p "
                    "AND superseded_by IS NULL"
                ),
                {"w": work_id, "p": pass_label},
            ).one()[0]
        )


def test_report_is_fixed_at_sample_time(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary[:2], protocol_id, exclude=True)
    _agree(project, agent, ordinary[2:], protocol_id, exclude=False)
    sampled = audit_sample(project, human, random_seed=7)
    kept = ordinary[1]
    for work in sampled.work_ids:
        if work == kept:
            audit_record(project, human, sampled.audit_id, work, "exclude", "EX01", Channel.CLI)
        else:
            audit_record(project, human, sampled.audit_id, work, "include", None, Channel.CLI)
    before = audit_report(project)
    assert before is not None
    assert before.rates.weighted == pytest.approx(1 / len(ordinary))
    assert before.criteria_implicated == ["EX01"]

    # Pass B now excludes an agreed include: the live agreed set drifts from the audit's population.
    drifted = ordinary[2]
    _decide(
        project,
        agent,
        drifted,
        "B",
        "screening",
        "exclude",
        "EX01",
        protocol_id,
        supersedes=_live_decision(project, drifted, "B"),
    )
    assert drifted not in agreed_works(project)

    after = audit_report(project)

    assert after is not None
    assert after.rates.weighted == before.rates.weighted
    assert after.criteria_implicated == before.criteria_implicated


def test_projection_agrees_with_agreed_works_in_mixed_case(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    unsure, split, superseded, both_exclude, *rest = ordinary
    _decide(project, agent, unsure, "A", "screening", "unsure", None, protocol_id)
    _decide(project, agent, unsure, "B", "screening", "include", None, protocol_id)
    _decide(project, agent, split, "A", "screening", "include", None, protocol_id)
    _decide(project, agent, split, "B", "screening", "exclude", "EX02", protocol_id)
    first = _decide(project, agent, superseded, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(
        project,
        agent,
        superseded,
        "A",
        "screening",
        "include",
        None,
        protocol_id,
        supersedes=first,
    )
    _decide(project, agent, superseded, "B", "screening", "include", None, protocol_id)
    _decide(project, agent, both_exclude, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, both_exclude, "B", "screening", "exclude", "EX03", protocol_id)
    for work in rest:
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)

    agreed = agreed_works(project)
    sampled = audit_sample(project, human, random_seed=7)

    assert set(agreed) == set(ordinary) - {unsure, split}
    assert agreed[superseded].verdict == "include"
    assert agreed[both_exclude] == AgreedWork(verdict="exclude", criteria=["EX01", "EX03"])
    with project.index.connect() as conn:
        digest, pop_ex, pop_in = conn.execute(
            text(
                "SELECT population_digest, pop_exclusions, pop_inclusions FROM audits "
                "WHERE audit_id = :a"
            ),
            {"a": sampled.audit_id},
        ).one()
        items = {
            str(w): (av, ac)
            for w, av, ac in conn.execute(
                text(
                    "SELECT work_id, agreed_verdict, agreed_criteria FROM audit_items "
                    "WHERE audit_id = :a"
                ),
                {"a": sampled.audit_id},
            ).all()
        }
    verdicts = [(w, a.verdict) for w, a in agreed.items()]
    assert str(digest) == population_digest(verdicts)
    assert int(pop_ex) == sum(1 for _, v in verdicts if v == "exclude") == 1
    assert int(pop_in) == sum(1 for _, v in verdicts if v == "include")
    assert items[both_exclude] == ("exclude", "EX01,EX03")
    assert items[superseded] == ("include", None)


def test_unknown_audit_is_reported_on_audit_id(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=False)
    audit_sample(project, human, random_seed=7)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        audit_record(project, human, "aud_unknown", ordinary[0], "include", None, Channel.CLI)

    assert _fields(exc) == ["audit_id"]
    assert len(_events(project)) == before
