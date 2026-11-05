"""Region rule models (slice 3d ruling 3): a closed set of typed rule kinds.

Invariants:
- Rules are pure data; nothing here reads the index. Seed status, held-out membership and pass
  internals have no rule kind (I8).
- `kind` is the discriminator and defaults to the class's own kind, so a rule is built by its
  parameters alone; the canonical form (`regions/version.py`) re-adds it.
- Text terms are folded (NFKC, casefold, collapsed whitespace) at construction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from factory.extraction.numbers import normalise_text
from factory.lineage.paths import MAX_DEPTH
from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage

REGION_VERSION_RE = r"^R@[0-9a-f]{8}$"
TEXT_MAX_BLOCKS = 8
TEXT_MAX_TERMS = 20


class MemberType(StrEnum):
    WORK = "work"
    IDEA = "idea"
    CONCEPT = "concept"


class CorpusRule(StrictModel):
    kind: Literal["corpus"] = "corpus"
    outcome: Literal["included", "screened", "all"]
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT


class RunRule(StrictModel):
    kind: Literal["run"] = "run"
    run_id: str | None = None
    query_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.run_id is None) == (self.query_id is None):
            raise ValueError("exactly one of run_id or query_id must be set")
        return self


class ImportRule(StrictModel):
    kind: Literal["import"] = "import"
    import_id: str
    part: Literal["development", "all"] = "development"


class LineageRule(StrictModel):
    kind: Literal["lineage"] = "lineage"
    node: str
    direction: Literal["ancestors", "descendants"]
    depth: int = Field(ge=1, le=MAX_DEPTH)
    edge_types: tuple[Literal["builds-on", "improves-on"], ...] = ("builds-on", "improves-on")
    include_inferred: bool = False

    @field_validator("edge_types")
    @classmethod
    def _sorted_set(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one edge type")
        return tuple(sorted(set(value)))


class CitesRule(StrictModel):
    kind: Literal["cites"] = "cites"
    base: str = Field(pattern=REGION_VERSION_RE)
    direction: Literal["citing", "cited"]
    min_k: int = Field(default=1, ge=1)


class IdeaRule(StrictModel):
    kind: Literal["idea"] = "idea"
    idea_id: str


class ConceptRule(StrictModel):
    kind: Literal["concept"] = "concept"
    concept_id: str


class TermRule(StrictModel):
    """Accepted by the model; evaluation refuses it until Regions-C."""

    kind: Literal["term"] = "term"
    term_id: str


class RegionRule(StrictModel):
    kind: Literal["region"] = "region"
    version: str = Field(pattern=REGION_VERSION_RE)


class TextRule(StrictModel):
    """An AND of OR-lists of terms over normalised titles and abstracts."""

    kind: Literal["text"] = "text"
    blocks: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=TEXT_MAX_BLOCKS)

    @field_validator("blocks")
    @classmethod
    def _fold(cls, value: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        folded: list[tuple[str, ...]] = []
        for block in value:
            if not 1 <= len(block) <= TEXT_MAX_TERMS:
                raise ValueError(f"a block holds 1 to {TEXT_MAX_TERMS} terms")
            terms = tuple(sorted({normalise_text(term) for term in block}))
            if not all(terms):
                raise ValueError("a term must not be blank")
            folded.append(terms)
        return tuple(sorted(set(folded)))


Rule = Annotated[
    CorpusRule
    | RunRule
    | ImportRule
    | LineageRule
    | CitesRule
    | IdeaRule
    | ConceptRule
    | TermRule
    | RegionRule
    | TextRule,
    Field(discriminator="kind"),
]


class RuleSet(StrictModel):
    """`(union of include) intersect within, minus (union of exclude)`."""

    include: tuple[Rule, ...] = Field(min_length=1)
    exclude: tuple[Rule, ...] = ()
    within: Rule | None = None
