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
            "mine.imported",
            "mine.reopened",
            "taxonomy.registered",
            "taxonomy.change_proposed",
            "mining.requested",
            "work.layer_set",
        ),
        tables=(
            "miners",
            "miner_calibrations",
            "miner_calibration_units",
            "miner_calibration_labels",
            "miner_calibration_label_sessions",
            "mine_imports",
            "mine_reopenings",
            "mine_import_items",
            "taxonomies",
            "taxonomy_proposals",
            "mining_requests",
            "mining_request_works",
            "work_layer_moves",
        ),
        note="registered miners are data; their records are written in the extraction.* family"
        " (the pack on each event is the miner's name); mine.resolve is the gate of the"
        " extraction.resolved events whose pack is a miner's. Taxonomies (IDEA-50) are miner-like"
        " data: a classification miner is derived from a registered taxonomy version; on-demand"
        " requests and the researcher's layer moves decide which works a listed miner reads.",
    ),
    task_kinds=default_task_kinds().kinds_of("mining"),
    protocol_sections=("miners", "taxonomies"),
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
            PolicyKind.AGENT,
            ("decision 51", "slice-M ruling 16"),
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
        CheckRule("mine-import-unaudited", ("warning", "warning", "error")),
        CheckRule("mine-import-unverified", ("error", "error", "error")),
        CheckRule("mine-pending", ("warning", "warning", "warning")),
        CheckRule("mine-single", (None, "warning", "error")),
        CheckRule("mine-source-superseded", ("warning", "warning", "error")),
        CheckRule("mine-source-unavailable", ("warning", "warning", "warning")),
        CheckRule("miner-calibration-failed", ("warning", "warning", "warning")),
        CheckRule("miner-uncalibrated-evidence", ("error", "error", "error")),
        CheckRule("miner-version-unread", ("warning", "warning", "warning")),
        CheckRule("technique-no-miner", ("warning", "warning", "warning")),
        CheckRule("technique-taxonomy-empty", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
