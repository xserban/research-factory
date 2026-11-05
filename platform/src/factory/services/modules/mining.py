"""Generic mining over registered miners (slice M, M-C).

Declaration only (decision 55); behaviour stays in `services/mining.py`. The module grows with
the plan: task kinds here, the registration event, the `miners` section, the gate and the check
rules as their tasks land."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    GateKind,
    GateSpec,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
    QualityRegime,
)
from factory.services.modules.base import RuleModule
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="mining",
    kind=ModuleKind.MINER,
    inputs=(ArtifactKind.CONVERSION, ArtifactKind.PROTOCOL, ArtifactKind.MINER),
    outputs=(ArtifactKind.RECORD,),
    events=EventFamily(
        types=(
            "miner.registered",
            "miner.retired",
            "miner.calibration_drawn",
            "miner.calibration_labelled",
        ),
        tables=(
            "miners",
            "miner_calibrations",
            "miner_calibration_units",
            "miner_calibration_labels",
        ),
        note="registered miners are data; their records are written in the extraction.* family"
        " (the pack on each event is the miner's name); mine.resolve is the gate of the"
        " extraction.resolved events whose pack is a miner's.",
    ),
    task_kinds=default_task_kinds().kinds_of("mining"),
    protocol_sections=("miners",),
    gates=(
        GateSpec(
            "miner.calibration_label",
            GateKind.DECISION,
            ("miner.calibration_labelled",),
            PolicyKind.HUMAN,
            ("slice-M ruling 16",),
        ),
        GateSpec(
            "mine.resolve",
            GateKind.DECISION,
            ("extraction.resolved",),
            PolicyKind.HUMAN,
            ("decision 51",),
        ),
    ),
    regime=QualityRegime(
        2,
        "session-and-model",
        "field-value",
        "none",
        "agreed-sample",
        ("amendment", "document-version", "conversion"),
    ),
    checks=(
        CheckRule("mine-pending", ("warning", "warning", "warning")),
        CheckRule("mine-single", (None, "warning", "error")),
    ),
)

MODULE = RuleModule(SPEC)
