"""Experiment designs, runs, results and baseline reproduction (slice 6, plan XP-A).

Declaration only (slice M, decision 55); behaviour stays in the services. A design is a proposal an
agent drafts and a gate holder freezes and unlocks; runs and results are the researcher's or a
runner's record (an agent registers planned runs and never submits a result). The gate
`experiments.freeze_unlock` has its exploratory preset in `modules/presets.py`; it is declared
here, with the human-only `experiments.accept_baseline`."""

from factory.modules.contract import (
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
            "experiment.amended",
            "experiment.designed",
            "experiment.deviation_recorded",
            "experiment.frozen",
            "experiment.unlocked",
            "xrun.registered",
            "xrun.reported",
        ),
        tables=(
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
    ),
)

MODULE = RuleModule(SPEC)
