"""Experiment designs, runs, results and baseline reproduction (slice 6, plan XP-A).

Declaration only (slice M, decision 55); behaviour stays in the services. A design is a proposal an
agent drafts and a gate holder freezes and unlocks; runs and results are the researcher's or a
runner's record (an agent registers planned runs and never submits a result). The gate
`experiments.freeze_unlock` has its exploratory preset in `modules/presets.py`; it is declared
here, with the human-only `experiments.accept_baseline`."""

from factory.modules.contract import (
    CheckRule,
    EventFamily,
    GateKind,
    GateSpec,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="experiments",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "baseline.accepted",
            "baseline.evaluated",
            "experiment.amended",
            "experiment.designed",
            "experiment.deviation_recorded",
            "experiment.frozen",
            "experiment.unlocked",
            "xrun.registered",
            "xrun.reported",
        ),
        tables=(
            "baseline_evaluations",
            "experiment_amendments",
            "experiment_deviations",
            "experiments",
            "xruns",
        ),
    ),
    gates=(
        GateSpec(
            "experiments.freeze_unlock",
            GateKind.DECISION,
            ("experiment.frozen", "experiment.unlocked"),
            PolicyKind.AGENT,
            ("slice 6 ruling 14", "R-50", "R-51", "R-123"),
        ),
        GateSpec(
            "experiments.accept_baseline",
            GateKind.DECISION,
            ("baseline.accepted",),
            PolicyKind.HUMAN,
            ("slice 6 ruling 24", "R-122"),
        ),
    ),
    checks=(
        CheckRule("experiment-not-frozen", ("warning", "warning", "warning")),
        CheckRule("baseline-unresolved", ("warning", "warning", "warning")),
        CheckRule("xrun-environment-differs", ("warning", "warning", "warning")),
        CheckRule("xrun-reported-without-registration", ("error", "error", "error")),
        CheckRule("compute-budget-exceeded", ("warning", "warning", "warning")),
        CheckRule("test-access-exceeded", ("warning", "warning", "warning")),
        CheckRule("controls-missing", (None, None, "error")),
    ),
)

MODULE = RuleModule(SPEC)
