"""Check findings, trace and methods text of slice 6 (plan XP-B task 7; acceptance 11, 22, 23;
R-51, R-52)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from factory.model.directions import Conditions, DirectionReason
from factory.model.findings import ContradictionInput
from factory.model.hypotheses import DiscardReason, Trigger, TriggerKind
from factory.model.project import RigorMode
from factory.services.check import _findings_as, agent_check, check
from factory.services.context import Project
from factory.services.directions import close_direction
from factory.services.evaluation import evaluate_hypothesis, latest_evaluation
from factory.services.experiments import (
    design_experiment,
    freeze_experiment,
    record_deviation,
    unlock_experiment,
)
from factory.services.finders import propose_contradiction
from factory.services.hypotheses import (
    conclude_hypothesis,
    declare_cutoff,
    draft_hypothesis,
    register_hypothesis,
)
from factory.services.leads import decide_lead, record_lead
from factory.services.methods import agent_methods, methods_report, render_methods
from factory.services.trace import TraceNode, agent_trace, trace
from factory.services.xruns import ingest_results, register_run
from tests.card_helpers import cw
from tests.contribution_helpers import ext_a
from tests.evaluation_helpers import REFUTED, SUPPORTED, report_runs, unlocked
from tests.experiment_helpers import (
    COMMIT,
    XW,
    cell,
    frozen_design,
    register_with_review,
    results_file,
    xe,
    xw,
)
from tests.finder_helpers import MatchWorld, mw
from tests.hypothesis_helpers import (
    CRITIC,
    DRAFTER,
    HW,
    LEAD_AUTHOR,
    LEAD_TEXT,
    OTHER,
    RATIONALE,
    STATEMENT,
    card_trigger,
    gw,
    hw,
    lead_input,
    make_spec,
    promoted_lead,
)
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.test_contradictions import CtrWorld, ctrw


def _codes(project: Project, mode: RigorMode = RigorMode.PILOT) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for f in _findings_as(project, mode):
        out.setdefault(f.code, []).append(f)
    return out


def _nodes(node: TraceNode) -> Iterator[TraceNode]:
    yield node
    for child in node.children:
        yield from _nodes(child)


def test_fresh_project_has_none_of_the_slice_findings(project: Project) -> None:
    slice6 = {
        "property-proposed-unapproved",
        "assertion-inferred-unconfirmed",
        "assertion-stale",
        "contradiction-unconfirmed",
        "lead-undecided",
        "hypothesis-unreviewed",
        "hypothesis-registered-untested",
        "hypothesis-cutoff-unknown",
        "hypothesis-contaminated",
        "hypothesis-evaluated-unconcluded",
        "experiment-not-frozen",
        "baseline-unresolved",
        "xrun-environment-differs",
        "xrun-reported-without-registration",
        "compute-budget-exceeded",
        "test-access-exceeded",
        "controls-missing",
        "evaluation-stale",
    }
    assert not slice6 & set(_codes(project, RigorMode.SYSTEMATIC))
    methods = methods_report(project)
    assert methods.hypotheses is None
    assert "Hypotheses and tests" not in render_methods(methods)


# --- Findings, one constructed case each -------------------------------------------------------


def test_cards_and_contradictions_findings(
    project: Project, agent: Any, human: Any, mw: MatchWorld
) -> None:
    from factory.services.properties import propose_property
    from tests.card_helpers import prop

    propose_property(
        project,
        agent,
        prop("pr:proposed-only", allowed=["a", "b"], applies_to="both", value_aliases={}),
    )
    found = _codes(project)
    assert found["property-proposed-unapproved"][0].refs == ["pr:proposed-only"]
    assert mw.inferred and found["assertion-inferred-unconfirmed"]  # the world's inferred card
    assert all("pas_" in r for r in found["assertion-inferred-unconfirmed"][0].refs)
    assert found["assertion-inferred-unconfirmed"][0].message.endswith(
        "inferred assertion(s) no human confirmed"
    )
    assert _codes(project, RigorMode.EXPLORATORY).get("assertion-inferred-unconfirmed") is None


def test_contradiction_unconfirmed(project: Project, agent: Any, ctrw: CtrWorld) -> None:
    cid, _ = propose_contradiction(
        project, agent, ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note="n")
    )
    assert _codes(project)["contradiction-unconfirmed"][0].refs == [cid]


def test_assertion_stale(
    project: Project, other_session_human: Any, mw: MatchWorld, human: Any
) -> None:
    from factory.services.properties import decide_property

    decide_property(project, other_session_human, "pr:dense", "reject", "dropped")
    assert _codes(project)["assertion-stale"]


def test_lead_and_hypothesis_findings(
    project: Project, human: Any, hw: HW, xw_unused: Any = None
) -> None:
    found = _codes(project)
    assert found["hypothesis-unreviewed"][0].refs == [hw.hid]
    lead = record_lead(
        project, LEAD_AUTHOR, lead_input(LEAD_TEXT, Trigger(kind=TriggerKind.WORK, ref=hw.works[1]))
    )
    assert _codes(project)["lead-undecided"][0].refs == [lead]
    decide_lead(project, human, lead, "park")
    assert "lead-undecided" not in _codes(project)


def test_registered_untested_and_evaluated_unconcluded(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    assert _codes(project)["hypothesis-registered-untested"][0].refs == [xw.hid]
    exp = unlocked(project, human, xw)
    assert "hypothesis-registered-untested" not in _codes(project)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    assert _codes(project)["hypothesis-evaluated-unconcluded"][0].refs == [xw.hid]
    conclude_hypothesis(project, human, xw.hid, "It works here.")
    assert "hypothesis-evaluated-unconcluded" not in _codes(project)


def _literature(project: Project, human: Any, hw: HW) -> str:
    from factory.services.hypothesis_review import record_review, review_next
    from tests.test_hypothesis_review import verdict

    spec = make_spec(
        kind="literature",
        lead=hw.lead,
        rationale="lit",
        statement="Lorem beats Low in later literature.",
        decision_rule={"rule": "literature-direction", "n_min": 2, "q": "0.75"},
        test={"kind": "literature", "window_start": "2020-01-01"},
    )
    hid, _ = draft_hypothesis(project, DRAFTER, spec)
    for _ in range(2):
        served = review_next(project, CRITIC)
        assert served is not None
        record_review(project, CRITIC, served.task_id, verdict("register"))
    register_hypothesis(project, human, hid)
    return hid


def test_cutoff_findings(project: Project, human: Any, hw: HW) -> None:
    hid = _literature(project, human, hw)
    found = _codes(project, RigorMode.SYSTEMATIC)
    assert found["hypothesis-cutoff-unknown"][0].severity == "error"
    assert found["hypothesis-cutoff-unknown"][0].refs == [hid]
    assert _codes(project)["hypothesis-cutoff-unknown"][0].severity == "warning"
    declare_cutoff(project, human, "model-drafter", date(2021, 1, 1), "vendor card")
    declare_cutoff(project, human, "model-critic", date(2019, 1, 1), "vendor card")
    found = _codes(project)
    assert "hypothesis-cutoff-unknown" not in found
    assert found["hypothesis-contaminated"][0].refs == [hid]


def test_design_and_run_findings(project: Project, human: Any, xw: XW, tmp_path: Path) -> None:
    exp, _ = design_experiment(project, DRAFTER, xw.design())
    assert _codes(project)["experiment-not-frozen"][0].refs == [exp]
    freeze_experiment(project, human, exp)
    found = _codes(project)
    assert "experiment-not-frozen" not in found
    assert found["baseline-unresolved"][0].refs == [exp]
    systematic = _codes(project, RigorMode.SYSTEMATIC)
    assert "controls-missing" not in systematic  # the default design has both controls


def test_controls_missing_is_a_systematic_error(project: Project, human: Any, xw: XW) -> None:
    exp = frozen_design(project, human, xw, controls=[], baselines=[])
    assert "controls-missing" not in _codes(project)
    hit = _codes(project, RigorMode.SYSTEMATIC)["controls-missing"][0]
    assert (hit.severity, hit.refs) == ("error", [exp])


def test_environment_budget_and_access_findings(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(
        project, human, xw, budget={"gpu_hours": "2", "per_run_gpu_hours": "2", "max_runs": 40}
    )
    odd = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    ingest_results(project, human, results_file(tmp_path, odd, commit="other", name="env.json"))
    report_runs(project, human, tmp_path, exp, {("treatment", 1): "77.0"})
    report_runs(project, human, tmp_path, exp, {("treatment", 1): "77.0"})  # a second read
    found = _codes(project)
    assert found["xrun-environment-differs"][0].refs == [odd]
    assert found["compute-budget-exceeded"][0].refs == [exp]
    assert len(found["test-access-exceeded"][0].refs) == 1
    assert "xrun-reported-without-registration" not in found  # structurally impossible


def test_evaluation_stale_after_a_later_deviation(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    assert "evaluation-stale" not in _codes(project)
    record_deviation(project, human, exp, "planned-change-after-freeze", "swapped a layer", True)
    stale = _codes(project)["evaluation-stale"][0]
    assert (stale.severity, stale.refs) == ("error", [xw.hid])
    evaluate_hypothesis(project, xw.hid)  # a new evaluation supersedes: no longer stale
    assert "evaluation-stale" not in _codes(project)


def test_each_message_is_ids_and_counts_only(
    project: Project, human: Any, hw: HW, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, SUPPORTED)
    lead = record_lead(
        project, LEAD_AUTHOR, lead_input(LEAD_TEXT, Trigger(kind=TriggerKind.WORK, ref=hw.works[1]))
    )
    texts = [f.message for f in _findings_as(project, RigorMode.SYSTEMATIC)]
    texts += [f.message for f in agent_check(project).findings]
    blob = " ".join(texts)
    for secret in (LEAD_TEXT, RATIONALE, STATEMENT):
        assert secret not in blob
    assert lead  # the lead exists and is reported by id only


# --- Trace ------------------------------------------------------------------------------------


def _row_lead_hypothesis(project: Project, human: Any, xw: XW, hw: HW) -> str:
    """A second hypothesis whose lead cites a final evidence row, registered after a review."""
    lead = promoted_lead(project, human, Trigger(kind=TriggerKind.ROW, ref=xw.rows[0]))
    hid, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=lead, rationale="via a row"))
    register_with_review(project, human, hid)
    return hid


def test_trace_from_outcome_reaches_question(
    project: Project, human: Any, xw: XW, hw: HW, tmp_path: Path
) -> None:
    hid = _row_lead_hypothesis(project, human, xw, hw)
    fresh = [
        {"name": "imagenet-dev", "version": "1", "sha256": "a" * 64, "role": "dev"},
        {"name": "imagenet-test2", "version": "1", "sha256": "c" * 64, "role": "confirmatory"},
    ]
    exp = unlocked(project, human, XW(hid, xw.rows), datasets=fresh)
    report_runs(project, human, tmp_path, exp, REFUTED)
    live = latest_evaluation(project, hid)
    assert live is not None
    tree = trace(project, live.event_id)
    kinds = {n.kind for n in _nodes(tree)}
    assert {
        "hypothesis_act",
        "xrun",
        "xrun_metrics",
        "experiment",
        "hypothesis",
        "lead",
        "cell",
        "question",
    } <= kinds
    assert tree.kind == "hypothesis_act" and "evaluation refuted" in tree.label
    metrics = [n for n in _nodes(tree) if n.kind == "xrun_metrics"]
    assert len(metrics) == 6 and all("sha256" in n.label or "blob" in n.label for n in metrics)
    # the review and registration of the hypothesis are on the chain
    acts = [n for n in _nodes(tree) if n.kind == "hypothesis_act" and n is not tree]
    assert {a.label.split(" ", 1)[0] for a in acts} == {"review", "registration"}
    assert any(n.kind == "hypothesis" and n.id == hid for n in _nodes(tree))


def test_trace_forward_from_work(project: Project, human: Any, xw: XW, hw: HW) -> None:
    tree = trace(project, hw.works[0], direction="forward")
    kinds = {n.id: n.kind for n in _nodes(tree)}
    assert kinds.get(hw.lead) == "lead" and kinds.get(hw.hid) == "hypothesis"


def test_design_run_and_direction_nodes(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    runs = report_runs(project, human, tmp_path, exp, REFUTED)
    closed = close_direction(
        project, human, "Closed.", DirectionReason.OTHER, Conditions(), [xw.hid, exp]
    )
    for ref in (exp, closed, xw.hid, *runs.values()):
        assert trace(project, ref).id == ref
    direction = trace(project, closed)
    assert {n.kind for n in _nodes(direction)} >= {"direction", "hypothesis", "experiment"}
    assert trace(project, exp, direction="forward").children[0].kind == "xrun"


def test_card_assertion_and_contradiction_nodes(
    project: Project, agent: Any, mw: MatchWorld, human: Any
) -> None:
    assertion = mw.assertions[mw.ok]["pr:tasks"]
    node = trace(project, assertion)
    assert node.kind == "assertion" and "property pr:tasks" in node.label
    assert any(n.kind == "card" and n.id == mw.ok for n in _nodes(node))
    card = trace(project, mw.ok, direction="forward")
    assert assertion in {n.id for n in _nodes(card)}
    lead = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, card_trigger(mw.ok)))
    assert lead in {n.id for n in _nodes(trace(project, mw.ok, direction="forward"))}
    assert LEAD_TEXT not in json.dumps(trace(project, lead).model_dump(mode="json"))


def test_contradiction_node(project: Project, agent: Any, ctrw: CtrWorld) -> None:
    cid, _ = propose_contradiction(
        project, agent, ContradictionInput(ref_a=ctrw.claim_x, ref_b=ctrw.item, note="n")
    )
    node = trace(project, cid)
    assert node.kind == "contradiction" and "undecided" in node.label
    assert {ctrw.claim_x} <= {n.id for n in _nodes(node)}


def test_agent_trace_labels_omit_lead_text_and_rationale(
    project: Project, human: Any, xw: XW, hw: HW, tmp_path: Path
) -> None:
    hid = _row_lead_hypothesis(project, human, xw, hw)
    fresh = [
        {"name": "imagenet-dev", "version": "1", "sha256": "a" * 64, "role": "dev"},
        {"name": "imagenet-test2", "version": "1", "sha256": "c" * 64, "role": "confirmatory"},
    ]
    exp = unlocked(project, human, XW(hid, xw.rows), datasets=fresh)
    report_runs(project, human, tmp_path, exp, REFUTED)
    live = latest_evaluation(project, hid)
    assert live is not None
    seen_kinds: set[str] = set()
    for ref, direction in ((live.event_id, "back"), (hid, "back"), (hw.lead, "forward")):
        tree = agent_trace(project, ref, direction=direction)  # type: ignore[arg-type]
        seen_kinds |= {n.kind for n in _nodes(tree)}
        blob = json.dumps(tree.model_dump(mode="json"))
        assert LEAD_TEXT not in blob and RATIONALE not in blob and STATEMENT not in blob
        assert "via a row" not in blob  # the second drafter's rationale
    assert {"lead", "hypothesis", "hypothesis_act"} <= seen_kinds
    # the labels of a lead, a hypothesis and a review hold ids and states only
    for node in _nodes(agent_trace(project, hid, direction="back")):
        if node.kind in ("lead", "hypothesis", "hypothesis_act"):
            assert len(node.label) < 200 and node.label.split(" ", 1)[0] in {
                "lead",
                "hypothesis",
                "review",
                "registration",
                "evaluation",
            }


# --- Methods ------------------------------------------------------------------------------------


def test_methods_counts_include_refuted_and_inconclusive(
    project: Project, human: Any, xw: XW, hw: HW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    lead = record_lead(
        project, LEAD_AUTHOR, lead_input(LEAD_TEXT, Trigger(kind=TriggerKind.WORK, ref=hw.works[2]))
    )
    decide_lead(project, human, lead, "discard", DiscardReason.PRIOR_FAILURE, "tried")
    report = methods_report(project)
    counts = report.hypotheses
    assert counts is not None
    assert counts.outcomes == {"refuted": 1}
    assert counts.hypotheses_by_state == {"evaluated": 1}
    assert counts.leads_by_decision["discarded"] == 1
    assert counts.registry_rows == 2  # the refuted hypothesis and the discarded lead
    text = render_methods(report)
    assert "Outcomes, computed by the registered decision rule: refuted 1." in text
    assert "Failed-direction registry rows: 2." in text
    for secret in (LEAD_TEXT, RATIONALE, STATEMENT):
        assert secret not in text
    agent_report, _withheld = agent_methods(project, report)
    assert agent_report.hypotheses == counts  # counts, no rate: the same for an agent


def test_methods_reports_autonomy_label(
    xe: XW, explore_project: Project, human: Any, tmp_path: Path
) -> None:
    exp, _ = design_experiment(explore_project, DRAFTER, xe.design())
    freeze_experiment(explore_project, OTHER, exp)
    unlock_experiment(explore_project, OTHER, exp)
    report_runs(explore_project, human, tmp_path, exp, SUPPORTED)
    counts = methods_report(explore_project).hypotheses
    assert counts is not None and counts.autonomy_agent == 1
    assert counts.flags.get("autonomy:agent") == 1
    assert "Hypotheses registered with autonomy: agent: 1." in render_methods(
        methods_report(explore_project)
    )
