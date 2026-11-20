"""Typed tier plans: stages with caps, limits and the protocol and report templates.

Invariants:
- A `TierPlan` lists every stage of `site_catalog.STAGE_IDS` except `cross`, once and in lifecycle
  order; a stage a tier does not run is kept with `skipped=True`, so the plan can be diffed against
  `systematic`'s.
- `caps` are whole numbers; a cap of 0 means the step is not done. A stage without caps is
  uncapped (the pilot and systematic plans have none).
- A `ProtocolTemplate` is data: `instantiate` builds a `ProtocolSpec` from it and never decides
  what the criteria or queries say (those come from the question and the researcher). The result
  still passes through the normal protocol service, which validates it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.model.levels import Tier
from factory.model.protocol import (
    Criterion,
    ExtractionSchema,
    MethodProfile,
    PlannedQuery,
    ProtocolSpec,
    Reviewer,
    ReviewerRole,
    ScreeningPlan,
    SnowballPlan,
    SourcePlan,
)
from factory.services.site_catalog import STAGE_IDS

PLAN_STAGE_IDS: tuple[str, ...] = tuple(s for s in STAGE_IDS if s != "cross")
"""The stages a tier plan lists, in lifecycle order."""


class StagePlan(StrictModel):
    stage_id: str
    skill: str = Field(min_length=1)
    caps: dict[str, int] = Field(default_factory=dict)
    skipped: bool = False
    note: str = ""
    second_pass: bool = False
    """The step needs a second, independent pass (a separate run, session and model) to be
    complete: extraction pass B, which a work needs opened before it is final. Data, so the
    conductor starts it whatever the autonomy level; it is no human act and lowers no gate."""

    @model_validator(mode="after")
    def _known(self) -> Self:
        if self.stage_id not in PLAN_STAGE_IDS:
            raise ValueError(f"unknown stage id {self.stage_id!r}")
        if any(v < 0 for v in self.caps.values()):
            raise ValueError("a cap is a whole number of at least 0")
        return self


class Limits(StrictModel):
    max_papers: int = Field(ge=1)
    max_minutes: int = Field(ge=1)
    max_runs: int = Field(ge=1)


class ProtocolTemplate(StrictModel):
    """The structure of a tier's protocol; the criteria and queries are filled in per question."""

    method_profile: MethodProfile
    sources: tuple[str, ...] = Field(min_length=1)
    queries_per_source: int = Field(ge=1)
    passes: int = Field(ge=1, le=2)
    stop_after_consecutive_excludes: int | None = Field(default=None, ge=1)
    pack: str
    pack_version: int = Field(ge=1)
    fields: tuple[str, ...] = Field(min_length=1)
    comparability_keys: tuple[str, ...] = ()
    dual_extract_sample: float | None = Field(default=None, gt=0, le=1)
    snowball_backward_rounds: int = Field(default=0, ge=0)
    press_lite: bool = False
    """Whether an independent PRESS-lite review (a separate session) follows the protocol."""
    full_text_screening: bool = False
    """Whether the protocol declares a one-pass full-text screening plan (included works only; no
    calibration). Extraction needs a plan; `instantiate` adds it, with the same reviewers."""

    def instantiate(
        self,
        question_id: str,
        *,
        criteria: Sequence[Criterion],
        queries: Sequence[PlannedQuery],
        reviewer: str,
    ) -> ProtocolSpec:
        """The `ProtocolSpec` of this template for a question. `reviewer` is the human
        reviewer-of-record. Raises ValueError when the queries do not fit the template (a query
        on a source the template does not name, or more than `queries_per_source` per source)."""
        for source in self.sources:
            count = sum(1 for q in queries if q.source == source)
            if count > self.queries_per_source:
                raise ValueError(
                    f"at most {self.queries_per_source} query per source; {source} has {count}"
                )
        stray = {q.source for q in queries} - set(self.sources)
        if stray:
            raise ValueError(f"queries on sources the template does not name: {sorted(stray)}")
        reviewers = (Reviewer(role=ReviewerRole.REVIEWER_OF_RECORD, actor=reviewer, kind="human"),)
        full_text = (
            ScreeningPlan(passes=1, calibration_size=0, reviewers=reviewers)
            if self.full_text_screening
            else None
        )
        snowball = (
            SnowballPlan(max_backward_rounds=self.snowball_backward_rounds, max_forward_rounds=0)
            if self.snowball_backward_rounds
            else None
        )
        return ProtocolSpec(
            question_id=question_id,
            method_profile=self.method_profile,
            criteria=tuple(criteria),
            sources=tuple(SourcePlan(name=s, included=True) for s in self.sources),
            queries=tuple(queries),
            screening=ScreeningPlan(
                passes=1 if self.passes == 1 else 2,
                stop_after_consecutive_excludes=self.stop_after_consecutive_excludes,
                reviewers=reviewers,
            ),
            full_text_screening=full_text,
            extraction_schema=ExtractionSchema(
                pack=self.pack,
                pack_version=self.pack_version,
                fields=self.fields,
                comparability_keys=self.comparability_keys,
                dual_extract_sample=self.dual_extract_sample,
            ),
            snowball_plan=snowball,
        )


class ReportTemplate(StrictModel):
    """The sections of a tier's report and the label it carries ('' for none)."""

    sections: tuple[str, ...] = Field(min_length=1)
    label: str = ""


class TierPlan(StrictModel):
    tier: Tier
    stages: tuple[StagePlan, ...]
    limits: Limits | None
    """None for the tiers with no cap (`pilot`, `systematic`): the conductor then has no budget."""
    protocol_template: ProtocolTemplate | None
    report_template: ReportTemplate

    @model_validator(mode="after")
    def _all_stages_once(self) -> Self:
        if tuple(s.stage_id for s in self.stages) != PLAN_STAGE_IDS:
            raise ValueError("a plan lists every stage once, in lifecycle order")
        return self

    def stage(self, stage_id: str) -> StagePlan:
        for s in self.stages:
            if s.stage_id == stage_id:
                return s
        raise KeyError(stage_id)
