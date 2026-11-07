"""Ranked serving, the stopping rule and its reports (slice 8, D2; IDEA-42)."""

import pytest
from pydantic import ValidationError

from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.protocol import MethodProfile, protocol_version
from factory.model.screening import PassLabel, Verdict
from factory.services.context import Project
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import prisma_flow
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.ranked_queue import (
    rank_key,
    ranked_sequence,
    stop_status,
    unreached,
    walk,
)
from factory.services.ranking import compute_ranking, ranking_positions
from factory.services.screening import SCREEN_BATCH, open_pass, screen_next, screening_stop
from tests.helpers import SourcesFor, _setup
from tests.screening_helpers import _calibrate, _check, _draw, _fields, _screening, _spec
from tests.test_ranking import FakeEmbedder

EX = Verdict.EXCLUDE
IN = Verdict.INCLUDE


def test_rank_key_puts_unranked_works_after_ranked_ones_by_id() -> None:
    key = rank_key({"w2": 1, "w1": 2})
    assert sorted(["w9", "w1", "w2", "w3"], key=key) == ["w2", "w1", "w3", "w9"]
    assert sorted(["b", "a"], key=rank_key({})) == ["a", "b"]


def test_walk_counts_the_run_and_ends_at_the_first_undecided_work() -> None:
    sequence = ["a", "b", "c", "d", "e"]
    result = walk(sequence, {"a": IN, "b": EX, "c": EX})
    assert result.run == 2 and result.rest == ["d", "e"]
    assert walk(sequence, {"a": EX, "b": EX, "c": IN, "d": EX}).run == 1
    # Only an exclusion extends the run: unsure or cannot-assess resets it.
    assert walk(["a", "b"], {"a": EX, "b": Verdict.UNSURE}).run == 0
    done = walk(["a"], {"a": EX})
    assert done.run == 1 and done.rest == []


def test_stop_needs_a_frontier_inside_the_ranking() -> None:
    sequence = ["a", "b", "c"]
    verdicts = {"a": EX, "b": EX}
    stopped = stop_status(sequence, verdicts, set(), 2)
    assert stopped.stopped and stopped.not_screened == 1
    assert not stop_status(sequence, verdicts, set(), 3).stopped
    # Everything the ranking covers is decided: records outside it are still served.
    assert not stop_status(sequence, {"a": EX, "b": EX, "c": EX}, set(), 2).stopped
    # A served batch is completed, not counted as unscreened.
    assert stop_status(sequence, verdicts, {"c"}, 2).not_screened == 0
    assert unreached(sequence, verdicts, {"c"}) == set()


def test_ranked_sequence_leaves_out_unranked_and_non_queue_works() -> None:
    positions = {"a": 3, "b": 1, "c": 2, "gone": 4}
    assert ranked_sequence(positions, {"a", "b", "c", "new"}) == ["b", "c", "a"]


def test_a_stop_rule_leaves_hashes_alone_while_unset() -> None:
    plain = _spec()
    explicit = _spec(screening=_screening(stop_after_consecutive_excludes=None))
    assert protocol_version(plain) == protocol_version(explicit)
    assert "stop_after_consecutive_excludes" not in plain.model_dump(mode="json")["screening"]
    ruled = _spec(screening=_screening(stop_after_consecutive_excludes=50))
    assert protocol_version(ruled) != protocol_version(plain)


def test_the_stop_rule_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _screening(stop_after_consecutive_excludes=0)


def test_systematic_refuses_a_stop_rule_unless_rapid_review() -> None:
    plan = _screening(kappa_enforced=True, dual_sample=1.0, stop_after_consecutive_excludes=50)
    systematic = _spec(screening=plan, method_profile=MethodProfile.SYSTEMATIC_REVIEW)
    errors = _fields(_check(systematic, RigorMode.SYSTEMATIC).errors)
    assert "screening.stop_after_consecutive_excludes" in errors
    rapid = _spec(screening=plan, method_profile=MethodProfile.RAPID_REVIEW)
    assert _check(rapid, RigorMode.SYSTEMATIC).errors == []
    assert _check(systematic, RigorMode.PILOT).errors == []


def _ranked_world(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, n: int | None
) -> tuple[str, list[str]]:
    """A calibrated pilot corpus with a stop rule `n`, ranked, passes open; the ordinary works in
    ranked order."""
    _setup(project, agent, human, mock_sources, dual_sample=0.5)
    old = current_protocol(project)
    assert old is not None
    plan = old.spec.screening.model_copy(update={"stop_after_consecutive_excludes": n})
    amend_protocol(
        project,
        agent,
        old.spec.model_copy(update={"screening": plan}),
        reason="stop rule",
        semantic=False,
        effects={},
    )
    protocol = current_protocol(project)
    assert protocol is not None
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _calibrate(project, agent, human, protocol.protocol_id)
    compute_ranking(project, FakeEmbedder())
    positions = ranking_positions(project)
    return protocol.protocol_id, sorted(positions, key=rank_key(positions))


def test_screen_next_serves_the_best_ranked_batch_first(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _, ordered = _ranked_world(project, agent, human, mock_sources, None)
    served = screen_next(project, agent, PassLabel.A)
    assert served.batch is not None and served.stopped is None
    got = {record["work_id"] for record in served.batch.records}
    assert got == set(ordered[: len(got)]) and len(got) == min(SCREEN_BATCH, len(ordered))


def test_stop_withholds_unscreened_works_and_says_so(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordered = _ranked_world(project, agent, human, mock_sources, 2)
    assert len(ordered) > 3
    from tests.screening_helpers import _decide

    for work, verdict in zip(ordered, ["include", "exclude", "exclude"], strict=False):
        _decide(project, agent, work, "A", "screening", verdict, None, protocol_id)
    status = screening_stop(project)
    assert status is not None and status.stopped and status.run == 2
    assert status.not_screened == len(ordered) - 3
    result = screen_next(project, agent, PassLabel.A)
    assert result.batch is None
    assert result.stopped is not None and result.stopped.rule == "stop_after_consecutive_excludes"
    assert result.stopped.n == 2 and any("stop_after" in line for line in result.blocked)
    assert result.remaining == 0
    flow = prisma_flow(project)
    assert flow.not_screened_stop == len(ordered) - 3
    assert flow.stop_rule is not None and flow.not_screened_stop <= flow.pending
    assert "of which not screened because of the stop" in _markdown(flow)
    report = methods_report(project)
    assert report.ranking_model_id == "fake/model"
    text = render_methods(report)
    assert "fake/model" in text and "a" * 64 in text and "consecutive exclusions" in text


def _markdown(flow: object) -> str:
    from factory.cli.render import prisma_markdown
    from factory.services.prisma import PrismaFlow

    assert isinstance(flow, PrismaFlow)
    return prisma_markdown(flow)


def test_an_inclusion_breaks_the_run_and_serving_continues(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id, ordered = _ranked_world(project, agent, human, mock_sources, 2)
    from tests.screening_helpers import _decide

    for work, verdict in zip(ordered, ["exclude", "include", "exclude"], strict=False):
        _decide(project, agent, work, "A", "screening", verdict, None, protocol_id)
    status = screening_stop(project)
    assert status is not None and not status.stopped
    result = screen_next(project, agent, PassLabel.A)
    assert result.batch is not None and result.stopped is None
    assert ordered[3] in {record["work_id"] for record in result.batch.records}
    flow = prisma_flow(project)
    assert flow.not_screened_stop == 0


def test_without_a_stop_rule_nothing_is_reported(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ranked_world(project, agent, human, mock_sources, None)
    assert screening_stop(project) is None
    flow = prisma_flow(project)
    assert flow.stop_rule is None and "stop_rule" not in flow.model_dump(mode="json")
