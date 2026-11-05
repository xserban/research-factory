"""Full PRISMA with full-text boxes, check, trace, methods and status (plan 2C, task 7)."""

import json

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.screening import DecisionRecorded, PassLabel, ScreeningPhase, Verdict
from factory.services.agreement import Outcome, final_outcomes
from factory.services.check import check
from factory.services.context import Project
from factory.services.fulltext_screening import fulltext_queue
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import prisma_flow
from factory.services.project import project_status
from factory.services.trace import TraceNode, trace
from tests.document_helpers import (
    StubConverter,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.fulltext_helpers import FT, _ft_world, _ta_world
from tests.helpers import SourcesFor, _setup


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
        "oa-pdf: paywalled": 1,  # the latest attempt of the one failed work
        "unconverted": 1,
        "unsought": 1,
    }
    assert sum(boxes.not_retrieved_reasons.values()) == boxes.not_retrieved
    # Attempts, not works: the failed work has one latest reason per route.
    assert boxes.failed_attempts_by_route == {
        "arxiv-html: no html": 1,
        "arxiv-source: no src": 1,
        "oa-pdf: paywalled": 1,
    }


def test_slice1_flow_unchanged_before_full_text_runs(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ta_world(project, agent, human, mock_sources)
    flow = prisma_flow(project)
    boxes = flow.full_text
    assert boxes.stage_run is False and boxes.provisional is True
    assert boxes.assessed == boxes.included == 0 and boxes.excluded == {}
    assert boxes.pending == boxes.eligible > 0
    assert boxes.eligible == boxes.assessed + boxes.pending
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
    assert "full-text stage has not run" in render_methods(methods_report(project))
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
    assert report.full_text_sessions == 0  # passes opened, no session has joined one
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
