"""Search, citation chase, snowballing and seed admission: how works enter the corpus.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    ModuleKind,
    ModuleSpec,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="retrieval",
    kind=ModuleKind.RETRIEVAL,
    outputs=(
        ArtifactKind.QUERY,
        ArtifactKind.SEARCH_RUN,
        ArtifactKind.WORK,
        ArtifactKind.SNOWBALL_ROUND,
    ),
    events=EventFamily(
        types=(
            "chase.round_started",
            "query.registered",
            "search.page_archived",
            "search.records_parsed",
            "search.run_finished",
            "search.run_started",
            "seed.admitted",
            "snowball.round_started",
        ),
        tables=(
            "chase_queries",
            "chase_rounds",
            "pages",
            "provenance",
            "queries",
            "runs",
            "sample_considered",
            "sample_extensions",
            "seed_admissions",
            "snowball_candidates",
            "snowball_queries",
            "snowball_rounds",
            "work_keys",
            "work_title_buckets",
            "works",
        ),
        note=(
            "seed.admitted is written by seed admission, so it is owned here "
            "(the module whose service writes an event owns it)."
        ),
    ),
    protocol_sections=(
        "sources",
        "queries",
        "limits",
        "snowball_plan",
    ),
    checks=(
        CheckRule("shortfall-unexplained", ("error", "error", "error")),
        CheckRule("seed-admission-pending", ("warning", "warning", "error")),
        CheckRule("chase-missing", (None, "warning", "error")),
        CheckRule("snowball-plan-missing", (None, "warning", "error")),
        CheckRule("chase-declared-not-run", (None, "warning", "error")),
        CheckRule("snowball-over-plan", ("warning", "warning", "warning")),
        CheckRule("snowball-unscreened", ("error", "error", "error")),
    ),
)

MODULE = RuleModule(SPEC)
