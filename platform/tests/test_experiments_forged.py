"""One forged event per guard of the experiment projector (review: surviving mutants).

Every service refuses what these events say, so each is written to the log directly with
`project.record` (valid payloads, wrong history) or injected by hand. The fold must change nothing;
a rebuild from the log must give the same tables; and the honest event at the end of each scenario
must still fold, so that "nothing changed" is not just "nothing works". Each scenario is a
sequence: an ignored forgery leaves the state it found, so one state serves many guards.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.events.envelope import Actor
from factory.hypotheses.design import cell_hash, config_hash, design_version, run_config
from factory.model.experiments import (
    BaselineAccepted,
    BaselineEvaluated,
    CanonicalMetric,
    Cell,
    ExperimentAmended,
    ExperimentDesign,
    ExperimentDesigned,
    ExperimentDeviationRecorded,
    ExperimentFrozen,
    ExperimentUnlocked,
    XrunRegistered,
    XrunReported,
)
from factory.modules.contract import PolicyKind
from factory.services.context import Project
from factory.services.experiments import (
    accept_baseline,
    design_experiment,
    experiment_view,
    freeze_experiment,
    unlock_experiment,
    unlock_nonce,
)
from factory.services.hypotheses import draft_hypothesis, has_confirmatory_evidence
from factory.services.reproduction import baseline_verdicts, evaluate_baselines
from factory.services.xruns import ingest_results, register_run, xrun_list, xrun_view
from tests.experiment_helpers import (
    COMMIT,
    ENV,
    METRIC,
    XW,
    cell,
    design,
    experiment_rows,
    frozen_design,
    register_with_review,
    results_file,
    xe,
    xw,
)
from tests.hypothesis_helpers import DRAFTER, HW, LEAD_AUTHOR, OTHER, gw, hw, make_spec
from tests.test_reproduction import _repro

SYSTEM_S3 = Actor(kind="system", id="factory", user="obd", session=LEAD_AUTHOR.session)
NONCE = "ab" * 16


# --- Helpers --------------------------------------------------------------------------------------


def forge(project: Project, actor: Actor, type_: str, payload: Any) -> None:
    """Write a valid event that the history makes wrong."""
    blob = project.blobs.put_json({}) if actor.kind == "agent" else None
    project.record([project.events.make(type_, payload, actor, input_blob=blob)])


class Scenario:
    """Forge events and check that none of them moves any experiment table."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.before = experiment_rows(project)

    def ignored(self, label: str, actor: Actor, type_: str, payload: Any) -> None:
        forge(self.project, actor, type_, payload)
        assert experiment_rows(self.project) == self.before, label

    def accepted(self) -> None:
        """The honest event just written moved the tables: the next forgeries compare to it."""
        assert experiment_rows(self.project) != self.before
        self.before = experiment_rows(self.project)

    def rebuilt(self) -> None:
        self.project.index.rebuild()
        assert experiment_rows(self.project) == self.before


def frozen_payload(project: Project, exp: str, **over: Any) -> ExperimentFrozen:
    view = experiment_view(project, exp)
    assert view is not None
    body: dict[str, Any] = {
        "experiment_id": exp,
        "e_version": view.e_version,
        "policy": PolicyKind.HUMAN,
        "autonomy": "human",
        "test_access_limit": 1,
        "baseline_values": {},
    }
    body.update(over)
    return ExperimentFrozen(**body)


def unlock_payload(project: Project, exp: str, **over: Any) -> ExperimentUnlocked:
    view = experiment_view(project, exp)
    assert view is not None
    body: dict[str, Any] = {
        "experiment_id": exp,
        "e_version": view.e_version,
        "nonce": NONCE,
        "policy": PolicyKind.HUMAN,
        "autonomy": "human",
    }
    body.update(over)
    return ExperimentUnlocked(**body)


def run_payload(
    project: Project, exp: str, c: Cell, run_id: str, *, exploratory: bool = False, **over: Any
) -> XrunRegistered:
    view = experiment_view(project, exp)
    assert view is not None
    config = run_config(view.design, c)
    body: dict[str, Any] = {
        "run_id": run_id,
        "experiment_id": exp,
        "e_version": view.e_version,
        "cell": c,
        "cell_hash": cell_hash(c),
        "config": config,
        "config_hash": config_hash(config),
        "exploratory": exploratory,
    }
    body.update(over)
    return XrunRegistered(**body)


def report_payload(
    project: Project, run_id: str, value: str = "2", *, exit_status: int = 0, **over: Any
) -> XrunReported:
    body: dict[str, Any] = {
        "run_id": run_id,
        "results_blob": project.blobs.put(b"{}"),
        "metrics": {"top-1 accuracy": CanonicalMetric(printed=value, unit="%", value=value)},
        "gpu_hours": "1",
        "exit_status": exit_status,
        "code_commit": COMMIT,
        "environment": ENV,
    }
    body.update(over)
    return XrunReported(**body)


def raw_run(
    project: Project, human: Actor, exp: str, c: Cell, value: str = "2", exit_status: int = 0
) -> str:
    """Register a run and fold its report without the ingestion service, so that no baseline
    verdict is written behind the scenario's back."""
    run = register_run(project, DRAFTER, exp, c)
    forge(
        project,
        human,
        "xrun.reported",
        report_payload(project, run, value, exit_status=exit_status),
    )
    return run


def verdict_payload(exp: str, rk: str, runs: tuple[str, ...], **over: Any) -> BaselineEvaluated:
    body: dict[str, Any] = {
        "experiment_id": exp,
        "row_key": rk,
        "reported": "1",
        "reproduced": "2",
        "runs": runs,
        "tolerance": "0.01",
        "tolerance_kind": "relative",
        "verdict": "not-reproduced",
        "evaluator_version": "baseline-eval@1",
    }
    body.update(over)
    return BaselineEvaluated(**body)


# --- Freeze, unlock and design guards -------------------------------------------------------------


def test_a_forged_freeze_under_an_agent_policy_is_ignored(explore_project: Project, xe: XW) -> None:
    project = explore_project
    exp, _ = design_experiment(project, DRAFTER, xe.design())
    s = Scenario(project)
    agent_policy = {"policy": PolicyKind.AGENT, "autonomy": "agent"}
    s.ignored(  # F1: a system actor is neither an agent nor a human
        "F1", SYSTEM_S3, "experiment.frozen", frozen_payload(project, exp, **agent_policy)
    )
    s.ignored(  # F2: the autonomy label is the actor's
        "F2", OTHER, "experiment.frozen", frozen_payload(project, exp, policy=PolicyKind.AGENT)
    )
    s.ignored(  # F5: a session that designed it cannot pass the gate
        "F5", DRAFTER, "experiment.frozen", frozen_payload(project, exp, **agent_policy)
    )
    s.rebuilt()
    forge(project, OTHER, "experiment.frozen", frozen_payload(project, exp, **agent_policy))
    s.accepted()
    s.rebuilt()


def test_forged_designs_amendments_and_freezes_of_a_draft(
    project: Project, human: Actor, xw: XW, hw: HW
) -> None:
    exp1, v1 = design_experiment(project, DRAFTER, xw.design(baselines=[]))
    hid2, _ = draft_hypothesis(
        project, DRAFTER, make_spec(lead=hw.lead, conditions={}, rationale="2")
    )
    hid_lit, _ = draft_hypothesis(
        project,
        DRAFTER,
        make_spec(
            lead=hw.lead,
            kind="literature",
            decision_rule={"rule": "literature-direction", "n_min": 5, "q": "0.8"},
            prediction={"direction": "treatment-better", "margin": "0"},
            test={"kind": "literature", "window_start": "2026-01-01", "sources": []},
        ),
    )
    s = Scenario(project)
    other_design = design(hid2, baselines=[])
    literature_design = design(hid_lit, baselines=[])
    s.ignored(  # F8: a freeze of another version
        "F8",
        human,
        "experiment.frozen",
        frozen_payload(project, exp1, e_version=design_version(xw.design(seeds=[1, 2, 3, 9]))),
    )
    s.ignored(
        "V2",
        human,
        "experiment.deviation_recorded",
        ExperimentDeviationRecorded(
            experiment_id=exp1, kind="other", text="early", semantic=True, after_unlock=False
        ),
    )
    s.ignored("U1", human, "experiment.unlocked", unlock_payload(project, exp1))
    amended = xw.design(baselines=[], seeds=[1, 2, 3, 4])
    s.ignored(  # A4: the version of an amendment is recomputed
        "A4",
        DRAFTER,
        "experiment.amended",
        ExperimentAmended(
            experiment_id=exp1, design=amended, e_version="E@00000000", reason="r", semantic=False
        ),
    )
    s.ignored(  # A3: an amendment cannot move the design to another hypothesis
        "A3",
        DRAFTER,
        "experiment.amended",
        ExperimentAmended(
            experiment_id=exp1,
            design=other_design,
            e_version=design_version(other_design),
            reason="r",
            semantic=False,
        ),
    )
    s.ignored(  # D1: the version of a design is recomputed
        "D1",
        DRAFTER,
        "experiment.designed",
        ExperimentDesigned(
            experiment_id="exp_01JZ9Q3K5M7N8P0R2S4T6V8W71",
            design=other_design,
            e_version="E@00000000",
        ),
    )
    s.ignored(  # D2: only an experiment hypothesis has a design
        "D2",
        DRAFTER,
        "experiment.designed",
        ExperimentDesigned(
            experiment_id="exp_01JZ9Q3K5M7N8P0R2S4T6V8W72",
            design=literature_design,
            e_version=design_version(literature_design),
        ),
    )
    s.rebuilt()
    # supersede the draft: a freeze or an amendment of the replaced design is then ignored
    exp2, _ = design_experiment(
        project, DRAFTER, xw.design(baselines=[], seeds=[1, 2, 3, 4]), supersedes=exp1
    )
    s.accepted()
    s.ignored("F7", human, "experiment.frozen", frozen_payload(project, exp1, e_version=v1))
    s.ignored(
        "A2",
        DRAFTER,
        "experiment.amended",
        ExperimentAmended(
            experiment_id=exp1,
            design=xw.design(baselines=[], seeds=[1, 2, 3, 5]),
            e_version=design_version(xw.design(baselines=[], seeds=[1, 2, 3, 5])),
            reason="r",
            semantic=False,
        ),
    )
    forged_run = run_payload(
        project, exp2, cell("ablation:no-norm", split="dev"), "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W73"
    )
    s.ignored("R2", DRAFTER, "xrun.registered", forged_run)  # a draft design has no runs
    s.rebuilt()


def test_forged_events_of_a_frozen_design_change_nothing(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    budget = {"gpu_hours": "100", "per_run_gpu_hours": "10", "max_runs": 1}
    exp = frozen_design(project, human, xw, baselines=[], budget=budget)
    s = Scenario(project)
    s.ignored("F6", human, "experiment.frozen", frozen_payload(project, exp))
    replacement = xw.design(baselines=[], seeds=[1, 2, 3, 4])
    s.ignored(  # D4: a frozen design is never superseded
        "D4",
        DRAFTER,
        "experiment.designed",
        ExperimentDesigned(
            experiment_id="exp_01JZ9Q3K5M7N8P0R2S4T6V8W74",
            design=replacement,
            e_version=design_version(replacement),
            supersedes=exp,
        ),
    )
    s.ignored(
        "U4", human, "experiment.unlocked", unlock_payload(project, exp, e_version="E@00000000")
    )
    dev = cell("ablation:no-norm", split="dev")
    s.ignored(
        "R1",
        SYSTEM_S3,
        "xrun.registered",
        run_payload(project, exp, dev, "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W75"),
    )
    s.ignored(  # R5: the cell hash is the platform's
        "R5",
        DRAFTER,
        "xrun.registered",
        run_payload(project, exp, dev, "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W76", cell_hash="0" * 16),
    )
    s.ignored(  # R7: so is the configuration hash
        "R7",
        DRAFTER,
        "xrun.registered",
        run_payload(project, exp, dev, "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W77", config_hash="0" * 16),
    )
    off_design = Cell(universe=(("resolution", "512"),), seed=1, arm="treatment", split="dev")
    s.ignored(  # R10: a post hoc cell must still be a point of the design
        "R10",
        DRAFTER,
        "xrun.registered",
        run_payload(project, exp, off_design, "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W78", exploratory=True),
    )
    s.rebuilt()
    run = register_run(project, DRAFTER, exp, dev)  # the one run max_runs allows
    s.accepted()
    s.ignored(  # R12: the allowance of runs is the design's
        "R12",
        DRAFTER,
        "xrun.registered",
        run_payload(
            project,
            exp,
            cell("ablation:no-norm", seed=2, split="dev"),
            "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W79",
        ),
    )
    ingest_results(project, human, results_file(tmp_path, run, value="71"))
    s.accepted()
    s.ignored(  # P2: a run is reported once
        "P2", human, "xrun.reported", report_payload(project, run, value="99")
    )
    s.rebuilt()
    view = xrun_view(project, run)
    assert view is not None and view.metrics == {"top-1 accuracy": "71"}


def test_forged_events_of_an_unlocked_design_change_nothing(
    project: Project, human: Actor, xw: XW
) -> None:
    exp = frozen_design(project, human, xw, baselines=[])
    unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    s = Scenario(project)
    s.ignored(  # U2: a second unlock would issue a second nonce
        "U2", human, "experiment.unlocked", unlock_payload(project, exp)
    )
    unplanned = Cell(
        universe=(("resolution", "224"),), seed=99, arm="treatment", split="confirmatory"
    )
    s.ignored(  # R9: a cell the design does not plan is never read on the test split
        "R9",
        DRAFTER,
        "xrun.registered",
        run_payload(project, exp, unplanned, "xrn_01JZ9Q3K5M7N8P0R2S4T6V8W80", exploratory=True),
    )
    s.rebuilt()
    assert unlock_nonce(project, exp) == nonce


def test_a_forged_unlock_of_an_unregistered_hypothesis_is_ignored(
    project: Project, human: Actor, hw: HW
) -> None:
    exp, _ = design_experiment(project, DRAFTER, design(hw.hid, baselines=[]))
    freeze_experiment(project, human, exp)
    s = Scenario(project)
    s.ignored("U5", human, "experiment.unlocked", unlock_payload(project, exp))
    s.rebuilt()
    register_with_review(project, human, hw.hid)
    forge(project, human, "experiment.unlocked", unlock_payload(project, exp))
    s.accepted()


def test_a_forged_unlock_with_a_baseline_unresolved_is_ignored(
    project: Project, human: Actor, xw: XW
) -> None:
    exp = frozen_design(project, human, xw)
    s = Scenario(project)
    s.ignored("U6", human, "experiment.unlocked", unlock_payload(project, exp))
    s.rebuilt()


# --- Verdicts and acceptances ---------------------------------------------------------------------


def test_forged_baseline_verdicts_and_acceptances_change_nothing(
    project: Project, human: Actor, xw: XW, hw: HW
) -> None:
    r, r_other, r_good = xw.rows[0], xw.rows[1], xw.rows[2]
    baselines = [{"row_key": k, "tolerance": "0.01"} for k in (r, r_other, r_good)]
    exp = frozen_design(project, human, xw, baselines=baselines)
    # a second experiment, for the guard that a verdict lists runs of its own experiment
    hid2, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="second"))
    register_with_review(project, human, hid2)
    exp2 = frozen_design(
        project, human, XW(hid2, xw.rows), baselines=[{"row_key": r, "tolerance": "0.01"}]
    )
    seeds = (1, 2, 3)
    value2 = {
        s: raw_run(project, human, exp2, cell(f"reproduction:{r}", seed=s, split="dev"))
        for s in seeds
    }
    # reported first: the "first completed run of a seed" check must not hide the arm check
    on_other = {
        s: raw_run(project, human, exp, cell(f"reproduction:{r_other}", seed=s, split="dev"))
        for s in seeds
    }
    on_r = {
        s: raw_run(project, human, exp, cell(f"reproduction:{r}", seed=s, split="dev"))
        for s in (1, 2)
    }
    failed3 = raw_run(  # a failed run that carries a value, reported before the good one
        project, human, exp, cell(f"reproduction:{r}", seed=3, split="dev"), exit_status=1
    )
    off_universe = Cell(
        universe=(("resolution", "384"),), seed=3, arm=f"reproduction:{r}", split="dev"
    )
    exploratory3 = raw_run(project, human, exp, off_universe)  # post hoc: off the primary universe
    on_r[3] = raw_run(project, human, exp, cell(f"reproduction:{r}", seed=3, split="dev"))
    for seed in seeds:  # the third baseline reproduces
        raw_run(
            project, human, exp, cell(f"reproduction:{r_good}", seed=seed, split="dev"), value="1"
        )
    assert baseline_verdicts(project, exp) == {r: "pending", r_other: "pending", r_good: "pending"}
    s = Scenario(project)
    runs = (on_r[1], on_r[2], on_r[3])
    tolerant = verdict_payload(exp, r, runs, tolerance="2", verdict="reproduced")
    s.ignored("B3", SYSTEM_S3, "baseline.evaluated", tolerant)
    s.ignored(  # B5: the mean is the runs' (2), not the one the event states
        "B5",
        SYSTEM_S3,
        "baseline.evaluated",
        verdict_payload(exp, r, runs, reproduced="1"),  # the verdict is the true one
    )
    s.ignored(  # B7: the reported value is the one frozen with the design
        "B7",
        SYSTEM_S3,
        "baseline.evaluated",
        verdict_payload(exp, r, runs, reported="9"),
    )
    s.ignored(  # B6: the verdict is the one the mean gives
        "B6", SYSTEM_S3, "baseline.evaluated", verdict_payload(exp, r, runs, verdict="reproduced")
    )
    s.ignored(  # B4a: the runs belong to this experiment
        "B4a",
        SYSTEM_S3,
        "baseline.evaluated",
        verdict_payload(exp, r, (value2[1], value2[2], value2[3])),
    )
    s.ignored(  # B4b: and to this baseline
        "B4b",
        SYSTEM_S3,
        "baseline.evaluated",
        verdict_payload(exp, r, (on_other[1], on_other[2], on_other[3])),
    )
    s.ignored(  # B4c: a post hoc run is not a planned reproduction
        "B4c",
        SYSTEM_S3,
        "baseline.evaluated",
        verdict_payload(exp, r, (on_r[1], on_r[2], exploratory3)),
    )
    s.ignored(  # B4d: a failed run is left out, not averaged in
        "B4d",
        SYSTEM_S3,
        "baseline.evaluated",
        verdict_payload(exp, r, (on_r[1], on_r[2], failed3)),
    )
    s.ignored(  # a human or an agent does not write verdicts
        "B1", human, "baseline.evaluated", verdict_payload(exp, r, runs)
    )
    s.rebuilt()
    assert evaluate_baselines(project, exp) != []
    s.accepted()
    assert baseline_verdicts(project, exp)[r] == "not-reproduced"
    assert baseline_verdicts(project, exp)[r_good] == "reproduced"
    accept = BaselineAccepted(experiment_id=exp, row_key=r, rationale="paper used other data")
    s.ignored("BA1-system", SYSTEM_S3, "baseline.accepted", accept)
    s.ignored("BA1-agent", OTHER, "baseline.accepted", accept)
    s.ignored(  # BA2: a baseline that reproduced needs no acceptance
        "BA2",
        human,
        "baseline.accepted",
        BaselineAccepted(experiment_id=exp, row_key=r_good, rationale="not needed"),
    )
    s.rebuilt()
    accept_baseline(project, human, exp, r, "paper used other data")
    s.accepted()
    s.rebuilt()


# --- Report guards that the services enforce first ------------------------------------------------


def test_a_forged_report_by_a_system_actor_that_is_not_a_runner_is_ignored(
    project: Project, human: Actor, xw: XW
) -> None:
    exp = frozen_design(project, human, xw, baselines=[])
    run = register_run(project, DRAFTER, exp, cell("ablation:no-norm", split="dev"))
    s = Scenario(project)
    s.ignored("P1-factory", project.system_actor(), "xrun.reported", report_payload(project, run))
    s.ignored("P1-nonrunner", SYSTEM_S3, "xrun.reported", report_payload(project, run))
    s.rebuilt()
    runner = Actor(kind="system", id="runner-gpu1", user="obd", session=SYSTEM_S3.session)
    forge(project, runner, "xrun.reported", report_payload(project, run))
    s.accepted()


def test_replayed_under_systematic_rules_an_unlock_without_both_controls_is_ignored(
    project: Project, human: Actor, xw: XW, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.index import experiments as fold
    from factory.model.project import RigorMode

    exp = frozen_design(project, human, xw, baselines=[], controls=[])
    unlock_experiment(project, human, exp)  # pilot: controls are optional
    assert unlock_nonce(project, exp) is not None
    monkeypatch.setattr(fold, "mode_in_force", lambda _conn, _t: RigorMode.SYSTEMATIC)
    project.index.rebuild()
    assert unlock_nonce(project, exp) is None
    view = experiment_view(project, exp)
    assert view is not None and view.state == "frozen"


def test_a_forged_freeze_without_the_baseline_values_is_ignored(
    project: Project, human: Actor, xw: XW
) -> None:
    exp, _ = design_experiment(project, DRAFTER, xw.design())  # one baseline
    s = Scenario(project)
    s.ignored("F11-empty", human, "experiment.frozen", frozen_payload(project, exp))
    s.ignored(
        "F11-other-row",
        human,
        "experiment.frozen",
        frozen_payload(project, exp, baseline_values={xw.rows[1]: "1"}),
    )
    s.rebuilt()
    forge(
        project,
        human,
        "experiment.frozen",
        frozen_payload(project, exp, baseline_values={xw.rows[0]: "1"}),
    )
    s.accepted()
