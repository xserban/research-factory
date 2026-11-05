"""Question, seeds, probe and protocol: what is asked and how it will be answered.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    GateKind,
    GateSpec,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
    StrategySpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="scoping",
    kind=ModuleKind.SCOPING,
    outputs=(
        ArtifactKind.QUESTION,
        ArtifactKind.PROTOCOL,
        ArtifactKind.SEED,
    ),
    events=EventFamily(
        types=(
            "probe.failed",
            "probe.measured",
            "probe.page_archived",
            "protocol.amended",
            "protocol.deviation_recorded",
            "protocol.press_confirmed",
            "protocol.press_reviewed",
            "protocol.recorded",
            "question.goal_stated",
            "question.recorded",
            "seed.added",
            "seed.miss_explained",
            "seed.resolved",
            "seed.split_drawn",
            "seed.unresolved",
        ),
        tables=(
            "amendments",
            "deviations",
            "goals",
            "press_reviews",
            "probes",
            "protocols",
            "questions",
            "seed_explanations",
            "seed_split",
            "seeds",
        ),
    ),
    protocol_sections=(
        "question_id",
        "method_profile",
        "criteria",
        "rationale",
    ),
    gates=(
        GateSpec(
            "protocol.press_confirm",
            GateKind.DECISION,
            ("protocol.press_confirmed",),
            PolicyKind.HUMAN,
            ("R-61",),
        ),
    ),
    checks=(
        CheckRule("seed-missing", ("warning", "error", "error")),
        CheckRule("protocol-not-ready", (None, "error", "error")),
        CheckRule("press-missing", (None, "error", "error")),
        CheckRule("profile-checklist", ("warning", "warning", "warning")),
    ),
    strategies=(
        StrategySpec("interview", "1", "rf-frame"),
        StrategySpec("probe", "1", "rf-probe"),
    ),
)

MODULE = RuleModule(SPEC)
