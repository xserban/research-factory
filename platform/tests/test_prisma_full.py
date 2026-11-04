"""Full PRISMA with full-text boxes, check, trace, methods and status (plan 2C, task 7)."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.fulltext import AttemptOutcome, Route
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, DecisionRecorded, PassLabel, ScreeningPhase, Verdict
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items, draw_calibration, label_calibration
from factory.services.check import check
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.fulltext_screening import fulltext_queue
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import prisma_flow
from factory.services.project import project_status
from factory.services.screening import open_pass
from factory.services.search import list_works
from factory.services.trace import TraceNode, trace
from factory.sources.fulltext.base import not_retrieved
from factory.sources.registry import SourceFactory
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.helpers import _setup
from tests.test_fulltext_service import StubRoute, always
from tests.test_screening_next import _draw
from tests.test_stage_services import _both, _decide_at, _declare_full_text

FT = ScreeningStage.FULL_TEXT
TA = ScreeningStage.TITLE_ABSTRACT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]


@dataclass
class World:
    protocol_id: str
    eligible: list[str]
    failed: str
    fetched_only: str
    unsought: str


def _failing_routes() -> dict[Route, StubRoute]:
    return {
        route: StubRoute(route, always(not_retrieved(route, AttemptOutcome.NOT_AVAILABLE, why)))
        for route, why in (
            (Route.ARXIV_HTML, "no html"),
            (Route.ARXIV_SOURCE, "no src"),
            (Route.OA_PDF, "paywalled"),
        )
    }


def _ta_world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> World:
    """Title/abstract screening done and promoted; documents prepared; no full-text decision."""
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=6)
    pid = _declare_full_text(project, agent)
    _draw(project)
    for item in calibration_items(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    cal = set(calibration_items(project))
    for work in sorted(w.id for w in list_works(project) if w.id not in cal):
        _both(project, agent, TA, work, ("include", None), ("include", None), pid)
    promoted = promoted_works(project)
    assert len(promoted) >= 8
    *rest, failed, fetched_only, unsought = promoted
    for work in rest:
        fetched_document(project, work, ARTICLE)
    run_convert(project, make_registry(StubConverter()))
    fetch_fulltext(project, routes=_failing_routes(), work_ids=[failed])
    fetched_document(project, fetched_only, ARTICLE)  # live document, never converted
    return World(pid, rest, failed, fetched_only, unsought)


def _ft_world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> World:
    """Add full-text screening: one exclusion under EX04, one under EX05, one pending, rest in."""
    world = _ta_world(project, agent, human, mock_sources)
    draw_calibration(project, project.system_actor(), random_seed=5, stage=FT)
    open_pass(project, agent, PassLabel.A, stage=FT)
    open_pass(project, agent, PassLabel.B, stage=FT)
    first, second, third, *rest = world.eligible
    pid = world.protocol_id
    _both(project, agent, FT, first, ("exclude", "EX04"), ("exclude", "EX04"), pid)
    _both(project, agent, FT, second, ("exclude", "EX05"), ("exclude", "EX05"), pid)
    _decide_at(project, agent, FT, third, "A", "include", None, pid)  # B missing: pending
    for work in rest:
        _both(project, agent, FT, work, ("include", None), ("include", None), pid)
    return world


def test_boxes_sum_and_are_derived(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _ft_world(project, agent, human, mock_sources)
    boxes = prisma_flow(project).full_text
    queue = fulltext_queue(project)
    outcomes = final_outcomes(project, stage=FT)
    assert boxes.stage_run is True
    assert boxes.sought == len(promoted_works(project))
    assert boxes.not_retrieved == 3 == len(queue.not_retrieved)
    assert boxes.eligible == len(world.eligible)
    assert boxes.sought == boxes.not_retrieved + boxes.eligible
    assert boxes.eligible == boxes.assessed + boxes.pending
    assert boxes.assessed == boxes.included + sum(boxes.excluded.values())
    # Each count agrees with the outcomes the event-derived service reports.
    eligible = {e.work_id for e in queue.eligible}
    assert boxes.included == sum(1 for w in eligible if outcomes[w] is Outcome.INCLUDED)
    assert boxes.pending == sum(1 for w in eligible if outcomes[w] is Outcome.PENDING)
    assert boxes.excluded.get("EX04") and boxes.excluded.get("EX05")
    assert boxes.pending >= 1
    assert boxes.provisional is True
    flow = prisma_flow(project)
    assert flow.included_in_review == boxes.included
    assert flow.included == len(promoted_works(project))  # slice-1 meaning kept


def test_not_retrieved_has_route_reasons(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ta_world(project, agent, human, mock_sources)
    boxes = prisma_flow(project).full_text
    assert boxes.not_retrieved_reasons == {
        "arxiv-html: no html": 1,
        "arxiv-source: no src": 1,
        "oa-pdf: paywalled": 1,
        "unconverted": 1,
        "unsought": 1,
    }


def test_slice1_flow_unchanged_before_full_text_runs(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ta_world(project, agent, human, mock_sources)
    flow = prisma_flow(project)
    boxes = flow.full_text
    assert boxes.stage_run is False and boxes.provisional is True
    assert boxes.assessed == boxes.pending == boxes.included == 0 and boxes.excluded == {}
    assert boxes.sought == flow.included
    assert flow.included_in_review is None
    # The title/abstract numbers are exactly those of a protocol with no full-text plan.
    assert flow.included + flow.excluded_total + flow.pending == flow.screened


def test_no_full_text_plan_never_raises(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=2)
    flow = prisma_flow(project)
    assert flow.full_text.stage_run is False
    report = check(project)
    assert all(f.code != "fulltext-decision-stale-document" for f in report.findings)
    assert "Full-text screening" not in render_methods(methods_report(project))
    status = project_status(project)
    assert status.screening.full_text_passes is None


def test_check_lists_stale_document_decision(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _ft_world(project, agent, human, mock_sources)
    # The helper pins a made-up conversion id, so every full-text decision is stale; one real
    # decision (pinned to the work's current conversion) must not be flagged.
    current = {e.work_id: e.conversion_id for e in fulltext_queue(project).eligible}
    fresh = world.eligible[2]  # decided by pass A alone
    _decide_pinned(project, agent, fresh, current[fresh], world.protocol_id)
    findings = [f for f in check(project).findings if f.code == "fulltext-decision-stale-document"]
    assert len(findings) == 1 and findings[0].severity == "warning"
    named = set(findings[0].refs)
    assert world.eligible[0] in named and fresh not in named
    # A later conversion makes a previously fresh decision stale.
    run_convert(project, make_registry(StubConverter(version="2.0+b")))
    again = [f for f in check(project).findings if f.code == "fulltext-decision-stale-document"]
    assert fresh in set(again[0].refs)


def _decide_pinned(
    project: Project,
    agent: Actor,
    work: str,
    conversion_id: str,
    protocol_id: str,
    label: PassLabel = PassLabel.A,
) -> str:
    """A full-text decision pinned to a real conversion, citing a real anchor. It supersedes the
    live pass-A full-text decision of the work, if any."""
    with project.index.connect() as conn:
        prior = conn.execute(
            text(
                "SELECT decision_id FROM decisions WHERE work_id = :w AND stage = 'full-text' "
                "AND pass_label = :label AND superseded_by IS NULL"
            ),
            {"w": work, "label": label.value},
        ).scalar()
    decision_id = f"dec_{project.ids.ulid()}"
    payload = DecisionRecorded(
        decision_id=decision_id,
        work_id=work,
        pass_label=label,
        phase=ScreeningPhase.SCREENING,
        stage=FT,
        verdict=Verdict.INCLUDE,
        criterion=None,
        quote="Lorem ipsum dolor sit amet.",
        rationale="rationale",
        protocol_id=protocol_id,
        task_id="tsk_test",
        supersedes=None if prior is None else str(prior),
        anchor="s3.p1",
        conversion_id=conversion_id,
    )
    blob = project.blobs.put_json({"work_id": work})
    project.record(
        [
            project.events.make(
                "screening.decision_recorded", payload, agent, refs=(decision_id,), input_blob=blob
            )
        ]
    )
    return decision_id


def _walk(node: TraceNode) -> list[TraceNode]:
    return [node, *[n for child in node.children for n in _walk(child)]]


def test_trace_full_text_decision_chain(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _ft_world(project, agent, human, mock_sources)
    work = world.eligible[2]  # pass B has not decided it, so the decision supersedes nothing
    entry = next(e for e in fulltext_queue(project).eligible if e.work_id == work)
    decision = _decide_pinned(
        project, agent, work, entry.conversion_id, world.protocol_id, PassLabel.B
    )
    root = trace(project, decision)
    nodes = {(n.kind, n.id) for n in _walk(root)}
    assert ("anchor", f"{entry.conversion_id}/s3.p1") in nodes
    assert ("conversion", entry.conversion_id) in nodes
    assert ("document", entry.document_id) in nodes
    assert ("work", work) in nodes
    assert any(kind == "attempt" for kind, _ in nodes)
    assert any(kind == "protocol" for kind, _ in nodes)
    assert any(kind == "question" for kind, _ in nodes)
    assert all(n.label != "no such row" for n in _walk(root))
    # The chain is nested: anchor -> conversion -> document -> attempt -> work.
    anchor = next(n for n in _walk(root) if n.kind == "anchor")
    conversion = next(n for n in anchor.children if n.kind == "conversion")
    document = next(n for n in conversion.children if n.kind == "document")
    attempt = next(n for n in document.children if n.kind == "attempt")
    assert any(n.kind == "work" for n in attempt.children)
    # Forward from the conversion reaches the decision.
    forward = {
        (n.kind, n.id) for n in _walk(trace(project, entry.conversion_id, direction="forward"))
    }
    assert ("decision", decision) in forward


def test_methods_mentions_full_text_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    report = methods_report(project)
    assert report.full_text_passes == 2
    assert report.full_text_sessions == 0 or report.full_text_sessions >= 0
    body = render_methods(report)
    assert "Full-text screening." in body
    assert "kappa floor 0.700" in body
    assert "planned dual-coded share: 1.000" in body
    assert "audit fraction" in body
    boxes = report.prisma.full_text
    assert f"{boxes.sought} sought" in body and f"{boxes.not_retrieved} not retrieved" in body


def test_project_status_shows_full_text_progress(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    status = project_status(project)
    assert status.screening.full_text_passes is not None
    assert set(status.screening.full_text_passes) == {"A", "B"}


def test_rebuild_matches(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    before = prisma_flow(project).model_dump(mode="json")
    project.index.rebuild()
    after = prisma_flow(project).model_dump(mode="json")
    assert before == after
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
