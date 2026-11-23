"""The declared registry of count sources (R-87, IDEA-109).

A *count source* is a service whose numbers appear in a report or in the evidence counts: the
PRISMA flow, the search, evidence, methods and discovery reports, the briefing note, the digest
counts and the trace. Each declares the layers its inputs read:

- `evidence`: events and tables the evidence chain folds (screening, extraction, search, seeds);
- `organisation`: labels, terms, consolidation, regions (kept out of evidence by
  `organisation-leak`);
- `exploratory`: the technique graph, the lead engine, the claims digest and unadmitted miner
  rows.

R-87 says exploratory output never enters an evidence count. The `count-source-exploratory`
check rule reads this registry and flags any source declared with an `exploratory` input; the
enumeration test fails when a report or count service is neither declared here nor listed in
`NOT_COUNT_SOURCES`. Declaration only: it changes no count, and the scan of evidence outputs
(`organisation-leak`, `layer-leak`) stays the check of the output text. Adding a count service
means adding one `CountSource` row; wiring an exploratory input into one means changing its
`reads`, which `check` then reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Layer(StrEnum):
    EVIDENCE = "evidence"
    ORGANISATION = "organisation"
    EXPLORATORY = "exploratory"


@dataclass(frozen=True)
class CountSource:
    """One service that produces counts shown in a report.

    `module` is the dotted path under `factory.services`; `produces` names what it counts.
    `reads` is never empty: a source that reads nothing is not a count source."""

    name: str
    module: str
    produces: str
    reads: frozenset[Layer]

    def __post_init__(self) -> None:
        if not self.reads:
            raise ValueError(f"count source {self.name!r} declares no layer")


_E = frozenset({Layer.EVIDENCE})

COUNT_SOURCES: tuple[CountSource, ...] = (
    CountSource("prisma", "factory.services.prisma", "PRISMA flow and search report", _E),
    CountSource("prisma-update", "factory.services.prisma_update", "update flow", _E),
    CountSource("site-prisma", "factory.services.site_prisma", "PRISMA page figures", _E),
    CountSource("evidence-report", "factory.services.evidence_report", "evidence report", _E),
    CountSource("methods", "factory.services.methods", "methods statement counts", _E),
    CountSource(
        "hypothesis-methods",
        "factory.services.slice6_methods",
        "hypothesis paragraph of the methods statement (recorded leads, not engine candidates)",
        _E,
    ),
    CountSource("discovery", "factory.services.discovery", "discovery record counts", _E),
    CountSource("briefing", "factory.services.briefing", "brief note counts", _E),
    CountSource("digest", "factory.services.digest", "living digest counts", _E),
    CountSource("trace", "factory.services.trace", "trace nodes and edges", _E),
    CountSource("hub-trace", "factory.services.hub_trace", "trace figure", _E),
    CountSource("appraisal-report", "factory.services.appraisal_report", "appraisal counts", _E),
    CountSource("manuscript-report", "factory.services.manuscript_report", "manuscript counts", _E),
    CountSource(
        "label-trace",
        "factory.services.label_trace",
        "trace nodes for labels and terms",
        frozenset({Layer.ORGANISATION}),
    ),
    CountSource(
        "region-trace",
        "factory.services.region_trace",
        "trace nodes for regions",
        frozenset({Layer.ORGANISATION}),
    ),
)

NOT_COUNT_SOURCES: dict[str, str] = {
    # Exploratory services: never read by a count source above (the import scan in
    # tests/test_count_sources.py), so they need no declaration of their own.
    "claims_digest": "exploratory; a digest for the agent, not a report count",
    "miner_report": "miner calibration, shown beside, never inside, evidence counts",
    # Parts of a count source or of the trace family, declared through their parent.
    "briefing_served": "bookkeeping of served context packs",
    "slice6_trace": "trace describer, declared through trace",
    "layer_trace": "trace describer, declared through trace",
    "lab_trace": "trace describer, declared through trace",
    "draft_trace": "trace describer, declared through trace",
    "manuscript_trace": "trace describer, declared through trace",
}

EXPLORATORY_MODULES: frozenset[str] = frozenset(
    {
        "claims_digest",
        "technique_graph",
        "technique_rank",
        "lead_candidates",
        "lead_queue",
        "lead_cache",
        "lead_stats",
        "evidence_miners",
        "mining",
        "shared_mining",
        "hub_mining",
        "site_miners",
        "miner_independence",
    }
)
"""Service modules of the exploratory layer. A count source's module must not import them."""


def exploratory_sources(
    sources: tuple[CountSource, ...] | None = None,
) -> list[CountSource]:
    """The declared sources with an `exploratory` input, in declaration order."""
    use = COUNT_SOURCES if sources is None else sources
    return [s for s in use if Layer.EXPLORATORY in s.reads]
