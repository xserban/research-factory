"""The per-project human queue: one count per gate where a human is blocking (spec 7a ruling 5).

Counts only; a gate with nothing waiting is absent.
"""

from collections.abc import Callable, Mapping

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.protocol import PressElement, PressFinding
from factory.model.screening import Channel
from factory.services.agreement import screen_agreement
from factory.services.audit import audit_record, audit_sample
from factory.services.calibration import calibration_items, label_calibration
from factory.services.context import Project
from factory.services.human_queue import Gate, HumanItem, HumanQueue, human_queue
from factory.services.project import init_project, project_status
from factory.services.protocol import press_review
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION, ready_protocol, reviewer_of
from tests.portfolio_helpers import fresh, ta_world
from tests.test_agreement import _ready
from tests.test_audit import _agree, _population

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _items(queue: HumanQueue) -> dict[tuple[Gate, str | None], HumanItem]:
    return {(i.gate, i.stage): i for i in queue.items}


def test_nothing_waiting_gives_no_items(project: Project) -> None:
    assert human_queue(project) == HumanQueue(items=[])


def test_press_confirmation_awaits_a_human(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = ready_protocol(project, agent, human, mock_sources, press=False)
    finding = PressFinding(element=PressElement.TEXT_WORDS, finding="Add.", severity="minor")
    press_review(project, reviewer_of(agent), protocol_id, (finding,))
    item = _items(human_queue(project))[(Gate.PRESS_CONFIRMATION, None)]
    assert item.count == 1
    assert item.command == "factory --project demo protocol confirm-press <review-id>"


def test_calibration_labels_missing_count_down(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ta_world(project, agent, human, mock_sources)
    drawn = calibration_items(project)
    item = _items(human_queue(project))[(Gate.CALIBRATION_LABELS, "title-abstract")]
    assert item.count == len(drawn) > 0
    assert item.command == (
        "factory --project demo calibrate label <work> <include|exclude> --stage title-abstract"
    )
    label_calibration(project, human, drawn[0], "include", None, Channel.CLI)
    after = _items(human_queue(project))[(Gate.CALIBRATION_LABELS, "title-abstract")]
    assert after.count == len(drawn) - 1


def test_unsure_counts_as_a_disagreement(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ta_world(project, agent, human, mock_sources)
    agreement = screen_agreement(project, project.human_actor())
    assert {d.reason for d in agreement.disagreements} == {"outcome", "unsure"}
    item = _items(human_queue(project))[(Gate.SCREENING_DISAGREEMENTS, "title-abstract")]
    assert item.count == len(agreement.disagreements) >= 2
    assert item.command == "factory --project demo screen disagreements --stage title-abstract"


def test_open_pass_gives_no_disagreement_item_and_no_exception(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)  # passes opened, nothing decided
    assert Gate.SCREENING_DISAGREEMENTS not in {i.gate for i in human_queue(project).items}


def test_screening_audit_unlabelled(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _population(project, agent, human, mock_sources)
    _agree(project, agent, ordinary, protocol_id, exclude=True)
    sampled = audit_sample(project, human, random_seed=1)
    size = len(sampled.work_ids)
    item = _items(human_queue(project))[(Gate.SCREENING_AUDIT, "title-abstract")]
    assert item.count == size > 0
    assert item.command == "factory --project demo audit label <audit-id> <work> <include|exclude>"
    audit_record(
        project, human, sampled.audit_id, sampled.work_ids[0], "exclude", "EX01", Channel.CLI
    )
    after = _items(human_queue(project))
    assert after[(Gate.SCREENING_AUDIT, "title-abstract")].count == size - 1


def test_status_carries_the_same_queue(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ta_world(project, agent, human, mock_sources)
    assert project_status(project).human == human_queue(project)


def test_fresh_project_status_has_an_empty_queue(settings: Settings, clock: FixedClock) -> None:
    init_project(settings, "solo", "pilot", session=SESSION, clock=clock)
    assert project_status(fresh(settings, "solo", clock)).human == HumanQueue(items=[])


def test_undrawn_calibration_is_a_waiting_item_and_the_refusal_names_the_command(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from factory.model.screening import PassLabel
    from factory.services.calibration import calibration_drawn, calibration_status
    from factory.services.dedup import dedup_run
    from factory.services.screening import screen_next

    ready_protocol(project, agent, human, mock_sources)
    dedup_run(project)
    assert calibration_status(project).required
    assert not calibration_drawn(project)
    item = _items(human_queue(project))[(Gate.CALIBRATION_LABELS, "title-abstract")]
    assert item.command == "factory --project demo calibrate draw --stage title-abstract"
    refused = screen_next(project, agent, PassLabel.A)
    assert any("factory calibrate draw --stage title-abstract" in b for b in refused.blocked)
