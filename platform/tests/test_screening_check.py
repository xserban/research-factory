"""Band checks, the tuning loop and measurement batches (slice 8, H2). Written, not yet run."""

from collections.abc import Callable, Mapping

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import CriterionExamples, ExampleCase
from factory.model.screening import Channel, PassLabel
from factory.model.screening_check import (
    CheckDrawn,
    CheckItem,
    CheckKind,
    ScoreBand,
)
from factory.services import screening_check as svc
from factory.services.calibration import calibration_items
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.screening import open_pass
from factory.services.search import list_works
from factory.services.seeds import SeedRole, all_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import _setup
from tests.screening_helpers import _decide, _draw

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _ready(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[str, list[str]]:
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=1.0, random_works=60)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    calibration = set(calibration_items(project))
    return protocol_id, sorted(w.id for w in list_works(project) if w.id not in calibration)


# --- Model ---


def test_bands_must_not_overlap() -> None:
    with pytest.raises(ValueError):
        CheckDrawn(
            draw_id="chk_01HZZZZZZZZZZZZZZZZZZZZZZZ",
            kind=CheckKind.BAND,
            random_seed=1,
            items=(),
            bands=(ScoreBand(low=1, high=5), ScoreBand(low=5, high=10)),
            per_band=3,
        )


def test_only_a_band_draw_has_bands() -> None:
    with pytest.raises(ValueError):
        CheckDrawn(
            draw_id="chk_01HZZZZZZZZZZZZZZZZZZZZZZZ",
            kind=CheckKind.TUNING,
            random_seed=1,
            items=(CheckItem(work_id="w1"),),
            bands=(ScoreBand(low=1, high=3),),
            per_band=3,
        )


def test_example_cases_are_left_out_of_dumps_while_empty() -> None:
    assert CriterionExamples().model_dump(mode="json") == {"include": [], "exclude": []}
    grown = CriterionExamples(include_cases=(ExampleCase(work_id="w1", text="t"),))
    assert grown.model_dump(mode="json")["include_cases"][0]["work_id"] == "w1"


def test_parse_bands() -> None:
    assert [b.label for b in svc.parse_bands("1-3, 4-7,9")] == ["1-3", "4-7", "9-9"]
    with pytest.raises(FactoryValidationError):
        svc.parse_bands("one-three")


# --- Band check ---


def test_band_check_is_stratified_recorded_and_reported(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _ready(project, agent, human, mock_sources)
    for i, work in enumerate(ordinary[:30]):
        score = None if i % 10 == 9 else (i % 10) + 1
        verdict = "include" if score is not None and score >= 8 else "exclude"
        criterion = None if verdict == "include" else "EX01"
        _decide(
            project, agent, work, "A", "screening", verdict, criterion, protocol_id, score=score
        )

    drawn = svc.draw_band_check(project, human, per_band=2, random_seed=5)

    assert drawn.per_band == 2 and drawn.random_seed == 5
    assert [b.label for b in drawn.bands] == ["1-3", "4-7", "8-10"]
    counts: dict[str, int] = {}
    for item in drawn.items:
        counts[item.band] = counts.get(item.band, 0) + 1
    assert set(counts) == {"1-3", "4-7", "8-10", "unscored"}
    assert all(n <= 2 for n in counts.values())

    for item in drawn.items:
        svc.check_label(project, human, drawn.draw_id, item.work_id, "include", Channel.CLI)
    report = svc.check_report(project, drawn.draw_id)
    assert report is not None
    rows = {r.band: r for r in report.rows}
    assert rows["8-10"].agreement == 1.0
    assert rows["1-3"].agreement == 0.0
    assert rows["1-3"].would_add_includes == rows["1-3"].compared


def test_agent_cannot_draw_or_label(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordinary = _ready(project, agent, human, mock_sources)
    _decide(project, agent, ordinary[0], "A", "screening", "include", None, protocol_id, score=9)
    with pytest.raises(FactoryValidationError):
        svc.draw_band_check(project, agent)
    drawn = svc.draw_band_check(project, human, per_band=1, random_seed=1)
    with pytest.raises(FactoryValidationError):
        svc.check_label(project, agent, drawn.draw_id, ordinary[0], "include", Channel.CLI)


# --- Tuning and measurement ---


def test_measurement_keeps_clear_of_tuning_and_examples(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, _ = _ready(project, agent, human, mock_sources)
    held_out = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT and s.work_id}

    tuning = svc.draw_tuning_batch(project, human, size=6, name="first", random_seed=3)
    tuned = [item.work_id for item in tuning.items]
    assert len(tuned) == 6 and not set(tuned) & held_out
    assert svc.tuning_priority(project, tuning.stage) == set(tuned)

    for work in tuned:  # the agent excludes all; the person includes the first two
        _decide(project, agent, work, "A", "screening", "exclude", "EX01", protocol_id, score=2)
    with pytest.raises(FactoryValidationError):
        svc.draw_measurement_batch(project, human, size=5)  # tuning batch unlabelled
    for i, work in enumerate(tuned):
        svc.check_label(
            project, human, tuning.draw_id, work, "include" if i < 2 else "exclude", Channel.CLI
        )

    assert svc.last_example_change(project) is None
    protocol = current_protocol(project)
    assert protocol is not None
    criterion = protocol.spec.criteria[0].id
    svc.add_tuning_example(
        project, human, tuning.draw_id, tuned[0], criterion, "A short title: it counts", Channel.CLI
    )
    after = current_protocol(project)
    assert after is not None
    assert after.spec.criteria[0].examples.include_cases[0].work_id == tuned[0]
    assert svc.example_works(project) == {tuned[0]}
    first_change = svc.last_example_change(project)
    assert first_change is not None

    measurement = svc.draw_measurement_batch(project, human, size=8, random_seed=4)
    drawn = {item.work_id for item in measurement.items}
    assert not drawn & set(tuned)
    assert not drawn & svc.example_works(project)
    assert not drawn & held_out
    assert measurement.last_example_change == first_change

    svc.add_tuning_example(
        project, human, tuning.draw_id, tuned[1], criterion, "Another title: it counts", Channel.CLI
    )
    report = svc.check_report(project, measurement.draw_id)
    assert report is not None and not report.current and report.agreement is None


def test_example_needs_a_disagreement_and_no_work_id_in_text(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, _ = _ready(project, agent, human, mock_sources)
    tuning = svc.draw_tuning_batch(project, human, size=2, random_seed=1)
    first, second = (item.work_id for item in tuning.items)
    _decide(project, agent, first, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, second, "A", "screening", "exclude", "EX01", protocol_id)
    svc.check_label(project, human, tuning.draw_id, first, "exclude", Channel.CLI)
    svc.check_label(project, human, tuning.draw_id, second, "include", Channel.CLI)
    protocol = current_protocol(project)
    assert protocol is not None
    criterion = protocol.spec.criteria[0].id

    with pytest.raises(FactoryValidationError):  # they agree
        svc.add_tuning_example(project, human, tuning.draw_id, first, criterion, "t", Channel.CLI)
    with pytest.raises(FactoryValidationError):  # the text names the work
        svc.add_tuning_example(
            project, human, tuning.draw_id, second, criterion, f"see {second}", Channel.CLI
        )
    with pytest.raises(FactoryValidationError):  # two lines
        svc.add_tuning_example(
            project, human, tuning.draw_id, second, criterion, "a\nb", Channel.CLI
        )
