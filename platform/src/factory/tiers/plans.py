"""The four tier plans as data (contract C3).

`pilot` and `systematic` name today's stages in order with no caps: what they differ in (hold-out
split, calibration, dual passes, kappa floors) is the rigour mode, not the stage list. `brief` and
`deep` cap each stage; a stage they do not run is `skipped`. `skipped_steps` is computed from this
data, so nothing is typed twice.
"""

from __future__ import annotations

from typing import Final

from factory.model.levels import Tier
from factory.model.protocol import MethodProfile
from factory.tiers.model import (
    PHASE_FULL_TEXT,
    PHASE_TITLE_ABSTRACT,
    PLAN_STAGE_IDS,
    Limits,
    ProtocolTemplate,
    ReportTemplate,
    StagePlan,
    TierPlan,
)

# The skill that runs each stage in `pilot` and `systematic`.
STAGE_SKILL: Final[dict[str, str]] = {
    "frame": "rf-frame",
    "gather": "rf-search-run",
    "screen": "rf-screen",
    "acquire": "rf-acquire",
    "extract": "rf-extract",
    "understand": "rf-lineage",
    "develop": "rf-develop",
    "write": "rf-write",
    "maintain": "rf-living",
}
assert tuple(STAGE_SKILL) == PLAN_STAGE_IDS

BRIEF_SKILL: Final = "rf-brief"
DEEP_SKILL: Final = "rf-deep"

_BRIEF_FIELDS: Final = ("method_name", "task", "dataset", "metric", "value", "split")
"""At most six fields of the ml-benchmark pack (the template schema of a brief)."""
_BRIEF_KEYS: Final = ("task", "dataset", "metric")


def _stage(
    stage_id: str,
    *,
    skill: str | None = None,
    caps: dict[str, int] | None = None,
    skipped: bool = False,
    note: str = "",
    second_pass: bool = False,
    phase: str | None = None,
) -> StagePlan:
    return StagePlan(
        stage_id=stage_id,
        skill=skill or STAGE_SKILL[stage_id],
        caps=caps or {},
        skipped=skipped,
        note=note,
        second_pass=second_pass,
        phase=phase,
    )


def _screen_phases(stages: tuple[StagePlan, ...], full_text: StagePlan) -> tuple[StagePlan, ...]:
    """`stages` with `screen` marked as the title/abstract phase and `full_text` (the full-text
    phase) listed right after `acquire`: nothing can be screened at full text before a document
    exists, so the conductor runs the two phases around `acquire`."""
    out: list[StagePlan] = []
    for st in stages:
        if st.stage_id == "screen":
            st = st.model_copy(update={"phase": PHASE_TITLE_ABSTRACT})
        out.append(st)
        if st.stage_id == "acquire":
            out.append(full_text)
    return tuple(out)


def _full_text(skill: str, *, caps: dict[str, int] | None = None, note: str = "") -> StagePlan:
    return _stage(
        "screen", skill=skill, caps=caps, note=note or "full text of the acquired works",
        phase=PHASE_FULL_TEXT,
    )  # fmt: skip


def _uncapped() -> tuple[StagePlan, ...]:
    return _screen_phases(
        tuple(_stage(s) for s in PLAN_STAGE_IDS), _full_text(STAGE_SKILL["screen"])
    )


_BRIEF_PROTOCOL = ProtocolTemplate(
    method_profile=MethodProfile.RAPID_REVIEW,
    sources=("openalex", "arxiv"),
    queries_per_source=1,
    passes=1,
    stop_after_consecutive_excludes=10,
    pack="ml-benchmark",
    pack_version=1,
    fields=_BRIEF_FIELDS,
    comparability_keys=_BRIEF_KEYS,
    dual_extract_sample=0.01,
    snowball_backward_rounds=0,
    press_lite=False,
    full_text_screening=True,
)

_DEEP_PROTOCOL = ProtocolTemplate(
    method_profile=MethodProfile.RAPID_REVIEW,
    sources=("openalex", "arxiv", "pubmed"),
    queries_per_source=2,
    passes=1,
    stop_after_consecutive_excludes=15,
    pack="ml-benchmark",
    pack_version=1,
    fields=_BRIEF_FIELDS,
    comparability_keys=_BRIEF_KEYS,
    dual_extract_sample=0.2,
    snowball_backward_rounds=1,
    press_lite=True,
    full_text_screening=True,
)


def _brief() -> TierPlan:
    s = BRIEF_SKILL
    return TierPlan(
        tier=Tier.BRIEF,
        stages=_screen_phases(
            (
                _stage(
                    "frame",
                    skill=s,
                    caps={"press_reviews": 0},
                    note="question, optional seeds, exploratory protocol template; "
                    "no protocol gate",
                ),
                _stage(
                    "gather",
                    skill=s,
                    caps={"sources": 2, "searches_per_source": 1, "snowball_rounds": 0},
                    note="one search per source, then dedup",
                ),
                _stage(
                    "screen",
                    skill=s,
                    caps={"passes": 1, "max_screened": 40},
                    note="one pass in ranked order with the stopping rule",
                ),
                _stage(
                    "acquire",
                    skill=s,
                    caps={"max_included": 20, "open_access_only": 1},
                    note="open-access full texts only",
                ),
                _stage(
                    "extract",
                    skill=s,
                    caps={"passes": 1, "max_fields": 6},
                    note="a template schema; pass A, then pass B opened for the 1% dual sample",
                    second_pass=True,
                ),
                _stage("understand", skipped=True),
                _stage("develop", skipped=True),
                _stage(
                    "write",
                    skill=s,
                    note="an evidence note from report_evidence with verified quotes and the level "
                    "statement",
                ),
                _stage("maintain", skipped=True),
            ),
            _full_text(s, caps={"passes": 1}, note="one pass over the acquired works"),
        ),
        limits=Limits(max_papers=30, max_minutes=60, max_runs=20),
        protocol_template=_BRIEF_PROTOCOL,
        report_template=ReportTemplate(
            sections=("question", "search", "screening", "included", "evidence", "quotes", "level"),
            label="quick review",
        ),
    )


def _deep() -> TierPlan:
    s = DEEP_SKILL
    return TierPlan(
        tier=Tier.DEEP,
        stages=_screen_phases(
            (
                _stage(
                    "frame",
                    skill=s,
                    note="protocol-lite with an independent PRESS-lite review "
                    "in a separate session",
                ),
                _stage(
                    "gather",
                    skill=s,
                    caps={"sources": 3, "searches_per_source": 2, "snowball_rounds": 1},
                    note="one capped backward snowball round",
                ),
                _stage("screen", skill=s, caps={"passes": 1, "max_screened": 300}),
                _stage("acquire", skill=s, caps={"max_included": 150, "open_access_only": 1}),
                _stage(
                    "extract",
                    skill=s,
                    caps={"max_fields": 6},
                    note="template schema; a sampled audit and agreement on a sample",
                    second_pass=True,
                ),
                _stage("understand", skipped=True),
                _stage(
                    "develop",
                    skill=s,
                    caps={"contradiction_finder_only": 1},
                    note="the contradiction finder only",
                ),
                _stage("write", skill=s),
                _stage("maintain", skipped=True),
            ),
            _full_text(s, caps={"passes": 1}, note="one pass over the acquired works"),
        ),
        limits=Limits(max_papers=150, max_minutes=360, max_runs=60),
        protocol_template=_DEEP_PROTOCOL,
        report_template=ReportTemplate(
            sections=(
                "question",
                "protocol",
                "search",
                "screening",
                "included",
                "evidence",
                "contradictions",
                "audit",
                "quotes",
                "level",
            ),
            label="deep review",
        ),
    )


def _full(tier: Tier) -> TierPlan:
    return TierPlan(
        tier=tier,
        stages=_uncapped(),
        limits=None,
        protocol_template=None,
        report_template=ReportTemplate(
            sections=("prisma", "search", "methods", "evidence", "discovery")
        ),
    )


PLANS: Final[dict[Tier, TierPlan]] = {
    Tier.BRIEF: _brief(),
    Tier.DEEP: _deep(),
    Tier.PILOT: _full(Tier.PILOT),
    Tier.SYSTEMATIC: _full(Tier.SYSTEMATIC),
}
