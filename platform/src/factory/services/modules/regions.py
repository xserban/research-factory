"""Regions and foci: typed selection rules, pinned versions and their review.

Declaration only (slice M, decision 55); behaviour stays in the services. A region selects and
asserts nothing, so it is a proposal module whose decisions are made by a human (slice 3d
ruling 26).
"""

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
    name="regions",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "region.defined",
            "region.member_decided",
            "region.reviewed",
            "region.snapshot_taken",
        ),
        tables=(
            "region_definitions",
            "region_member_decisions",
            "region_members",
            "region_reviews",
            "region_snapshots",
            "regions",
        ),
    ),
    gates=(
        GateSpec(
            "regions.review",
            GateKind.DECISION,
            ("region.reviewed",),
            PolicyKind.HUMAN,
            ("slice 3d ruling 26", "R-51", "R-90"),
        ),
        GateSpec(
            "regions.member_decide",
            GateKind.DECISION,
            ("region.member_decided",),
            PolicyKind.HUMAN,
            ("slice 3d ruling 26", "R-51", "R-90"),
        ),
    ),
)

MODULE = RuleModule(SPEC)
