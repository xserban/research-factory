"""Regions and foci: typed selection rules, pinned versions and their review.

Declaration only (slice M, decision 55); behaviour stays in the services. A region selects and
asserts nothing, so it is a proposal module whose decisions are made by a human (slice 3d
ruling 26).
"""

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
    name="regions",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "region.adopted",
            "region.defined",
            "region.linked",
            "region.member_decided",
            "region.member_proposed",
            "region.reviewed",
            "region.snapshot_taken",
        ),
        tables=(
            "region_adoptions",
            "region_definitions",
            "region_links",
            "region_member_decisions",
            "region_member_proposals",
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
        GateSpec(
            "regions.link",
            GateKind.DECISION,
            ("region.linked",),
            PolicyKind.HUMAN,
            ("slice 3d ruling 11", "R-51", "R-90"),
        ),
        GateSpec(
            "regions.adopt",
            GateKind.DECISION,
            ("region.adopted",),
            PolicyKind.HUMAN,
            ("slice 3d ruling 4", "R-51", "R-90"),
        ),
    ),
    checks=(
        CheckRule("region-adoption-outdated", ("warning", "warning", "warning")),
        CheckRule("region-unreviewed", ("warning", "warning", "warning")),
        CheckRule("region-drift", ("warning", "warning", "warning")),
        CheckRule("region-subregion-violated", ("warning", "warning", "warning")),
        CheckRule("region-focus-slot-missing", ("warning", "warning", "warning")),
        CheckRule("region-member-proposal-pending", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)
