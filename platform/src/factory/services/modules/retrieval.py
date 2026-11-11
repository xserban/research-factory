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
            "work.marked_core",
            "work.unmarked_core",
        ),
        tables=(
            "chase_queries",
            "chase_rounds",
            "core_works",
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
        CheckRule("chase-run-unattributed", ("warning", "warning", "warning")),
        CheckRule("snowball-over-plan", ("warning", "warning", "warning")),
        CheckRule("snowball-unscreened", ("error", "error", "error")),
    ),
)

MODULE = RuleModule(SPEC)

FEED_SPEC = ModuleSpec(
    name="feed",
    kind=ModuleKind.RETRIEVAL,
    events=EventFamily(
        types=(
            "feed.configured",
            "feed.fetched",
            "feed.ranked",
            "feed.reacted",
            "feed.sent",
        ),
        tables=(
            "feed_configs",
            "feed_entries",
            "feed_fetches",
            "feed_rankings",
            "feed_reactions",
            "feed_sends",
        ),
        note=(
            "Discovery feed (slice 4c, decision 117): entries stay outside the corpus until a "
            "human sends one through the inbox. configured, reacted and sent are human acts."
        ),
    ),
    checks=(CheckRule("feed-scope-drift", ("warning", "warning", "warning")),),
)

FEED_MODULE = RuleModule(FEED_SPEC)

RUNNER_SPEC = ModuleSpec(
    name="runner",
    kind=ModuleKind.RETRIEVAL,
    events=EventFamily(
        types=("runner.started", "runner.finished"),
        tables=("runner_runs",),
        note=(
            "Headless runner (plan feed-hub H5, decision 118): the platform starts the installed "
            "`claude` executable for one stage; both events are system acts, and every judgement "
            "is written through MCP with the agent's provenance."
        ),
    ),
)

RUNNER_MODULE = RuleModule(RUNNER_SPEC)
