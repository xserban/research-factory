"""Full PRISMA with full-text boxes, check, trace, methods and status (plan 2C, task 7)."""

import json

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.screening import DecisionRecorded, PassLabel, ScreeningPhase, Verdict
from factory.services.agreement import Outcome, final_outcomes
from factory.services.check import check
from factory.services.context import Project
from factory.services.dedup import merged_after_screening
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
    assert boxes.not_sought + boxes.sought == len(promoted_works(project))
    assert boxes.not_sought + boxes.not_retrieved == len(queue.not_retrieved)
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
    }
    assert boxes.not_sought == 1  # promoted, never attempted: not a "not retrieved" reason
    assert boxes.sought == boxes.eligible + boxes.not_retrieved
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
    assert f"{boxes.not_sought} promoted works were not yet sought" in body
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


_LATE_MERGE = "mrg_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


def _merge_late(project: Project, primary: str, *absorbed: str) -> None:
    """A merge recorded after title/abstract screening, as the cascade does on a later run."""
    model = project.catalog.get("dedup.merged").payload.model_validate(
        {
            "merge_id": _LATE_MERGE,
            "primary": primary,
            "absorbed": sorted(absorbed),
            "rule": "title-identical",
            "records": 1 + len(absorbed),
        }
    )
    project.record([project.events.make("dedup.merged", model, project.system_actor())])


def test_absorbed_promoted_work_is_not_queued_and_boxes_still_sum(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ta_world(project, agent, human, mock_sources)
    before = prisma_flow(project)
    first, second, *_ = promoted_works(project)
    _merge_late(project, first, second)

    queue = fulltext_queue(project)
    queued = {e.work_id for e in queue.eligible} | set(queue.not_retrieved)
    assert second not in queued and first in queued
    flow = prisma_flow(project)
    boxes = flow.full_text
    # Promoted is a subset of the canonical works: included = not sought + sought.
    assert boxes.not_sought + boxes.sought == flow.included
    assert flow.included == before.included - 1
    assert (
        boxes.not_sought + boxes.sought == before.full_text.not_sought + before.full_text.sought - 1
    )


def test_merged_after_screening_lists_differing_outcomes_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ta_world(project, agent, human, mock_sources)
    outcomes = final_outcomes(project)
    included = sorted(w for w, o in outcomes.items() if o is Outcome.INCLUDED)
    excluded = sorted(w for w, o in outcomes.items() if o is Outcome.EXCLUDED)
    assert merged_after_screening(project) == []  # no merge yet
    _merge_late(project, excluded[0], included[0], included[1])
    rows = merged_after_screening(project)
    assert [(r.primary, r.absorbed) for r in rows] == [
        (excluded[0], included[0]),
        (excluded[0], included[1]),
    ]
    assert {(r.primary_outcome, r.absorbed_outcome, r.rule) for r in rows} == {
        ("excluded", "included", "title-identical")
    }
    # Read-only: the absorbed works keep their own outcomes.
    assert final_outcomes(project)[included[0]] is Outcome.INCLUDED
