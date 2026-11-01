"""Agreement, κ per criterion, human resolution and final outcomes (R-36, R-38, ruling 1).

The seed split is drawn at random by the probe, so the calibration set and hence the number of
ordinary works vary between runs. Every test therefore assigns the first four ordinary works their
designed roles and lets any further ordinary works agree as include.
"""

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.screening import Channel, Framing, PassJoined, PassLabel, ScreeningPhase, Verdict
from factory.services.agreement import (
    Outcome,
    final_outcomes,
    resolve_disagreement,
    screen_agreement,
)
from factory.services.calibration import calibration_items, label_calibration
from factory.services.context import Project
from factory.services.screening import (
    INSTRUCTIONS,
    ScreenBatchContent,
    join_pass,
    open_pass,
)
from factory.services.screening_stats import cohen_kappa
from factory.services.search import list_works
from factory.services.tasks import TaskSpec, create_tasks
from tests.test_screening_next import (
    SourcesFor,
    _decide,
    _draw,
    _events,
    _of_type,
    _setup,
)


def _ready(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    dual_sample: float = 0.5,
) -> str:
    """A nine-work corpus, its calibration set, and both passes opened."""
    protocol_id = _setup(
        project, agent, human, mock_sources, dual_sample=dual_sample, random_works=0
    )
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    return protocol_id


def _ordinary(project: Project) -> list[str]:
    """The works both passes are asked about: every work outside the calibration set, sorted."""
    calibration = set(calibration_items(project))
    ordinary = sorted(work.id for work in list_works(project) if work.id not in calibration)
    assert len(ordinary) >= 4
    return ordinary


def _b_queue(project: Project) -> set[str]:
    """The ordinary works of pass B: its recorded sample, less the calibration works."""
    [opened] = [
        e for e in _of_type(project, "screening.pass_opened") if e.payload["pass_label"] == "B"
    ]
    sample = opened.payload["sample"]
    ordinary = set(_ordinary(project))
    return ordinary if sample is None else ordinary & set(sample)


def _decide_four(project: Project, agent: Actor, protocol_id: str) -> tuple[str, str, str, str]:
    """Roles for the first four ordinary works, and agreed include for any others:

    w1 agreed include; w2 agreed exclusion under different criteria; w3 an outcome disagreement;
    w4 an `unsure` in pass A."""
    w1, w2, w3, w4, *rest = _ordinary(project)
    _decide(project, agent, w1, "A", "screening", "include", None, protocol_id)
    _decide(project, agent, w1, "B", "screening", "include", None, protocol_id)
    _decide(project, agent, w2, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, w2, "B", "screening", "exclude", "EX02", protocol_id)
    _decide(project, agent, w3, "A", "screening", "include", None, protocol_id)
    _decide(project, agent, w3, "B", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, w4, "A", "screening", "unsure", None, protocol_id)
    _decide(project, agent, w4, "B", "screening", "include", None, protocol_id)
    for work in rest:
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)
    return w1, w2, w3, w4


def _fields(exc: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in exc.value.issues]


def _reasons(exc: pytest.ExceptionInfo[FactoryValidationError]) -> str:
    return " ".join(issue.reason for issue in exc.value.issues)


# --- Refusals: isolation of the passes (acceptance 8, ruling 1) ---


def test_agreement_refused_while_tasks_open(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _decide_four(project, agent, protocol_id)
    content = ScreenBatchContent(
        pass_label=PassLabel.A,
        framing=Framing.INCLUSION,
        instructions=INSTRUCTIONS[Framing.INCLUSION],
        protocol_id=protocol_id,
        criteria=[],
        worked_examples=[],
        records=[],
        phase=ScreeningPhase.SCREENING,
    )
    create_tasks(
        project, agent, [TaskSpec(kind="screen_a", content=content.model_dump(mode="json"))]
    )
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        screen_agreement(project, agent)

    assert _fields(exc) == ["passes"]
    assert "task" in _reasons(exc)
    assert len(_events(project)) == before


def test_agreement_refused_while_works_unscreened(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    w1, *_ = _ordinary(project)
    _decide(project, agent, w1, "A", "screening", "include", None, protocol_id)

    with pytest.raises(FactoryValidationError) as exc:
        screen_agreement(project, agent)

    assert _fields(exc) == ["passes"]
    assert "still lack" in _reasons(exc)


def test_agreement_refused_when_passes_share_model(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _decide_four(project, agent, protocol_id)
    join_pass(project, agent, PassLabel.A)
    # A different session, the same model. join_pass refuses it, so the join exists only in the log.
    joined = PassJoined(
        pass_label=PassLabel.B, session=agent_other.session, model=agent.model or ""
    )
    blob = project.blobs.put_json({"pass_label": "B"})
    project.record(
        [project.events.make("screening.pass_joined", joined, agent_other, input_blob=blob)]
    )

    with pytest.raises(FactoryValidationError) as exc:
        screen_agreement(project, agent)

    assert _fields(exc) == ["passes"]
    assert "model" in _reasons(exc)


def test_agreement_refused_when_passes_share_session(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _decide_four(project, agent, protocol_id)
    join_pass(project, agent, PassLabel.A)
    # The projection keeps one join per session, so the shared join exists only in the log.
    joined = PassJoined(pass_label=PassLabel.B, session=agent.session, model="claude-sonnet-5-0")
    blob = project.blobs.put_json({"pass_label": "B"})
    project.record([project.events.make("screening.pass_joined", joined, agent, input_blob=blob)])

    with pytest.raises(FactoryValidationError) as exc:
        screen_agreement(project, agent)

    assert _fields(exc) == ["passes"]
    assert "session" in _reasons(exc)


# --- Agreement, κ and disagreements ---


def test_kappa_and_disagreements_listed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _, _, w3, w4 = _decide_four(project, agent, protocol_id)
    rest = len(_ordinary(project)) - 4
    before = len(_events(project))

    agreement = screen_agreement(project, agent)

    assert len(_events(project)) == before  # read-only
    assert agreement.n_dual == 4 + rest
    assert agreement.single_pass == []
    promoted = [(True, True), (False, False), (True, False), (False, True)]
    promoted += [(True, True)] * rest
    assert agreement.kappa == pytest.approx(cohen_kappa(promoted))
    assert [(d.work_id, d.reason) for d in agreement.disagreements] == [
        (w3, "outcome"),
        (w4, "unsure"),
    ]
    outcome_case = agreement.disagreements[0]
    assert outcome_case.a.verdict is Verdict.INCLUDE
    assert outcome_case.b.verdict is Verdict.EXCLUDE
    assert outcome_case.b.criterion == "EX01"
    assert [p.pass_label for p in agreement.passes] == [PassLabel.A, PassLabel.B]


def test_different_exclusion_criteria_agree_on_outcome(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    w1, w2, *rest = _ordinary(project)
    _decide(project, agent, w1, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, w1, "B", "screening", "exclude", "EX02", protocol_id)
    _decide(project, agent, w2, "A", "screening", "exclude", "EX02", protocol_id)
    _decide(project, agent, w2, "B", "screening", "exclude", "EX01", protocol_id)
    for work in rest:
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)

    agreement = screen_agreement(project, agent)

    assert agreement.disagreements == []
    assert agreement.kappa == pytest.approx(1.0)
    per_criterion = [(True, False), (False, True)] + [(False, False)] * len(rest)
    assert agreement.kappa_by_criterion["EX01"] == pytest.approx(cohen_kappa(per_criterion))
    assert agreement.kappa_by_criterion["EX03"] is None


def test_below_floor_flagged_advisory_in_pilot(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _decide_four(project, agent, protocol_id)

    agreement = screen_agreement(project, agent)

    assert agreement.kappa_floor == pytest.approx(0.7)
    assert agreement.kappa is not None and agreement.kappa < agreement.kappa_floor
    assert agreement.below_floor is True
    assert agreement.enforced is False


def test_single_pass_works_listed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources, dual_sample=0.25)
    ordinary = _ordinary(project)
    queue_b = _b_queue(project)
    singles = sorted(set(ordinary) - queue_b)
    assert singles, "a sample below the whole corpus leaves single-pass works"
    for work in ordinary:
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
    for work in queue_b:
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)

    agreement = screen_agreement(project, agent)

    assert agreement.single_pass == singles
    assert agreement.n_dual == len(queue_b)
    assert agreement.disagreements == []
    assert final_outcomes(project)[singles[0]] is Outcome.INCLUDED


def test_cannot_assess_rate_per_criterion(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    ordinary = _ordinary(project)
    _decide(project, agent, ordinary[0], "A", "screening", "cannot-assess", "EX01", protocol_id)
    for work in ordinary[1:]:
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
    for work in ordinary:
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)

    agreement = screen_agreement(project, agent)

    decisions = 2 * len(ordinary)
    assert set(agreement.cannot_assess_rate) == {"IN01", "EX01", "EX02", "EX03"}
    assert agreement.cannot_assess_rate["EX01"] == pytest.approx(1 / decisions)
    assert agreement.cannot_assess_rate["EX02"] == 0.0
    assert agreement.cannot_assess_rate["IN01"] == 0.0


# --- Human resolution and final outcomes ---


def test_resolution_removes_disagreement_and_sets_outcome(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    w1, w2, w3, w4 = _decide_four(project, agent, protocol_id)
    assert final_outcomes(project)[w3] is Outcome.PENDING

    resolve_disagreement(project, human, w3, "include", None, "borderline", Channel.CLI)
    resolve_disagreement(project, human, w4, "exclude", "EX01", "topic one", Channel.CLI)

    assert screen_agreement(project, agent).disagreements == []
    outcomes = final_outcomes(project)
    assert outcomes[w1] is Outcome.INCLUDED
    assert outcomes[w2] is Outcome.EXCLUDED
    assert outcomes[w3] is Outcome.INCLUDED
    assert outcomes[w4] is Outcome.EXCLUDED


def test_resolution_only_for_unresolved_disagreement(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    w1, _, w3, _ = _decide_four(project, agent, protocol_id)
    resolve_disagreement(project, human, w3, "include", None, "borderline", Channel.CLI)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as agreed:
        resolve_disagreement(project, human, w1, "include", None, "not needed", Channel.CLI)
    with pytest.raises(FactoryValidationError) as again:
        resolve_disagreement(project, human, w3, "exclude", None, "changed mind", Channel.CLI)

    assert _fields(agreed) == ["work_id"]
    assert _fields(again) == ["work_id"]
    assert len(_events(project)) == before


def test_resolution_exclusion_needs_current_ex_criterion(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _, _, w3, _ = _decide_four(project, agent, protocol_id)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as missing:
        resolve_disagreement(project, human, w3, "exclude", None, "no criterion", Channel.CLI)
    with pytest.raises(FactoryValidationError) as unknown:
        resolve_disagreement(project, human, w3, "exclude", "EX09", "unknown", Channel.CLI)

    assert _fields(missing) == ["criterion"]
    assert _fields(unknown) == ["criterion"]
    assert len(_events(project)) == before


def test_resolution_requires_human_actor(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _, _, w3, _ = _decide_four(project, agent, protocol_id)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        resolve_disagreement(project, agent, w3, "include", None, "agent tries", Channel.CLI)

    assert _fields(exc) == ["actor"]
    assert len(_events(project)) == before


def test_resolution_over_mcp_refused_from_pass_session(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources)
    _, _, w3, _ = _decide_four(project, agent, protocol_id)
    join_pass(project, agent, PassLabel.A)
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as exc:
        resolve_disagreement(project, human, w3, "include", None, "relayed", Channel.MCP)

    assert _fields(exc) == ["channel"]
    assert len(_events(project)) == before


def test_single_pass_unsure_is_pending_until_resolved(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources, dual_sample=0.25)
    ordinary = _ordinary(project)
    queue_b = _b_queue(project)
    single = sorted(set(ordinary) - queue_b)[0]
    for work in ordinary:
        verdict = "unsure" if work == single else "include"
        _decide(project, agent, work, "A", "screening", verdict, None, protocol_id)
    for work in queue_b:
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)

    agreement = screen_agreement(project, agent)
    assert single in agreement.single_pass
    assert final_outcomes(project)[single] is Outcome.PENDING

    resolve_disagreement(project, human, single, "exclude", "EX02", "off topic", Channel.CLI)

    assert final_outcomes(project)[single] is Outcome.EXCLUDED


def test_calibration_labels_set_final_outcome(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    items = calibration_items(project)
    label_calibration(project, human, items[0], "include", None, Channel.CLI)
    label_calibration(project, human, items[1], "exclude", "EX01", Channel.CLI)

    outcomes = final_outcomes(project)

    assert outcomes[items[0]] is Outcome.INCLUDED
    assert outcomes[items[1]] is Outcome.EXCLUDED
    assert outcomes[items[2]] is Outcome.PENDING
    assert outcomes[_ordinary(project)[0]] is Outcome.PENDING


def test_agreement_refused_before_pass_b_is_opened(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)

    with pytest.raises(FactoryValidationError) as exc:
        screen_agreement(project, agent)

    assert _fields(exc) == ["passes"]
    assert "pass B has not been opened" in _reasons(exc)
    assert final_outcomes(project)[_ordinary(project)[0]] is Outcome.PENDING
