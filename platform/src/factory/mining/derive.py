"""Derive a classification miner from a taxonomy version (plan 2026-11-12 §2.2). Pure.

The miner is a projection of the taxonomy and is never edited by hand. Definitions, cues and
examples are served in the task content, not in the enum.

Invariants:
- Deterministic: the same taxonomy, dimensions and arguments give the same spec. Chosen dimensions
  are taken in taxonomy order, whatever order they are given in.
- The `category` enum is the full ids of each chosen dimension's categories (dimension zero: the
  given `layer_ids`), then its residuals. `described_as` is required for the `other` residuals and
  forbidden for every other value.
- Rows are keyed on `category` alone (`row_anchor_fields` is empty), so passes never align on a
  quote (plan §3.2); except for one chosen dimension of `single` cardinality, whose spec declares
  no row key fields: its one row per work is keyed on the work (`compile.keyed_on_work`), so two
  passes that choose different categories align as one row and disagree (IDEA-69 (1)).
- Key rule B: the row key rule is `work` (no key fields) or `category` (`("category",)`); it is an
  argument of `derive_miner`, defaulting to `work` for one single dimension and `category` else,
  and `row_key_rule` reads it back from a spec. `register` derives with the rule the spec declares,
  so a version registered under the category key for one single dimension stays valid and a later
  change of the default never invalidates it. `work` is refused for any other dimension choice.
- `absence_values` are the `not-stated` and `not-applicable` residuals of the chosen dimensions.
- `derive_miner` raises `ValueError` for an unknown or repeated dimension, for no dimension, or
  for a dimension zero without `layer_ids`. Meaning is checked by `validate_miner`, not here.
"""

from __future__ import annotations

from collections.abc import Sequence

from factory.mining.spec import (
    EnumKind,
    EvidenceRule,
    MinerField,
    MinerRegime,
    MinerSpec,
    QuoteKind,
    Selector,
    TaxonomyRef,
)
from factory.mining.taxonomy import Dimension, TaxonomySpec, full_id, taxonomy_digest
from factory.packs.model import Conditional

OTHER = "other"
ABSENCE_RESIDUALS: tuple[str, ...] = ("not-stated", "not-applicable")
DERIVED_PROCEDURE = "rf-taxonomy"
ROW_KEY_WORK = "work"
ROW_KEY_CATEGORY = "category"
ROW_KEY_RULES: tuple[str, ...] = (ROW_KEY_WORK, ROW_KEY_CATEGORY)


def row_key_rule(spec: MinerSpec) -> str | None:
    """The key rule a derived spec declares: `work` for no key fields, `category` for
    `("category",)`, None for anything else (a spec `register` refuses)."""
    if not spec.row_key_fields:
        return ROW_KEY_WORK
    if spec.row_key_fields == ("category",):
        return ROW_KEY_CATEGORY
    return None


def _chosen(taxonomy: TaxonomySpec, dimensions: Sequence[str]) -> tuple[Dimension, ...]:
    """The chosen dimensions in taxonomy order; ValueError on an unknown or repeated one."""
    if not dimensions:
        raise ValueError("choose at least one dimension")
    if len(set(dimensions)) != len(dimensions):
        raise ValueError("a dimension is chosen twice")
    for dimension_id in dimensions:
        if taxonomy.dimension_named(dimension_id) is None:
            raise ValueError(f"unknown dimension: {dimension_id}")
    wanted = set(dimensions)
    return tuple(d for d in taxonomy.dimensions if d.id in wanted)


def _one_single(chosen: Sequence[Dimension]) -> bool:
    """Whether the miner holds one row per work: one chosen dimension, of `single` cardinality."""
    return len(chosen) == 1 and chosen[0].cardinality == "single"


def _category_ids(dimension: Dimension, layer_ids: Sequence[str]) -> list[str]:
    """The full ids of a dimension's categories; dimension zero takes `layer_ids` instead."""
    if dimension.layer_scheme is not None:
        if not layer_ids:
            raise ValueError(
                f"dimension {dimension.id} takes its categories from a layer scheme; give layer_ids"
            )
        return [full_id(dimension.id, layer) for layer in layer_ids]
    return [full_id(dimension.id, c.id) for c in dimension.categories]


def derive_miner(
    taxonomy: TaxonomySpec,
    dimensions: Sequence[str],
    *,
    name: str,
    version: int,
    selector: Selector,
    regime: MinerRegime,
    layer_ids: Sequence[str] = (),
    procedure: str = DERIVED_PROCEDURE,
    row_key: str | None = None,
) -> MinerSpec:
    """The classification miner of `taxonomy` over `dimensions`, named `name`. Raises
    `ValueError` when a dimension is unknown, repeated or missing, a dimension zero has no
    `layer_ids`, `row_key` is not a key rule, or `row_key` is `work` for other than one single
    dimension. The result carries the taxonomy reference (name, version, digest, dimensions)."""
    chosen = _chosen(taxonomy, dimensions)
    if row_key is None:
        row_key = ROW_KEY_WORK if _one_single(chosen) else ROW_KEY_CATEGORY
    if row_key not in ROW_KEY_RULES:
        raise ValueError(f"row key rule must be one of {', '.join(ROW_KEY_RULES)}")
    if row_key == ROW_KEY_WORK and not _one_single(chosen):
        raise ValueError("the work row key needs exactly one dimension of single cardinality")
    values: list[str] = []
    other: list[str] = []
    absent: list[str] = []
    questions: list[str] = []
    for dimension in chosen:
        values.extend(_category_ids(dimension, layer_ids))
        questions.append(f"{dimension.id}: {dimension.question}")
        for residual in dimension.residuals:
            value = full_id(dimension.id, residual)
            values.append(value)
            if residual == OTHER:
                other.append(value)
            if residual in ABSENCE_RESIDUALS:
                absent.append(value)
    category = MinerField(
        name="category",
        group="classification",
        kind=EnumKind(tuple(values)),
        required=True,
        description="; ".join(questions),
        compared=True,
    )
    quote = MinerField(name="quote", group="evidence", kind=QuoteKind(), compared=False)
    described_as = MinerField(
        name="described_as", group="evidence", kind=QuoteKind(), compared=False
    )
    conditionals: list[Conditional] = []
    if other:
        conditionals.append(Conditional("described_as", "category", tuple(other), "required"))
        forbidden = tuple(v for v in values if v not in other)
    else:
        forbidden = tuple(values)
    if forbidden:
        conditionals.append(Conditional("described_as", "category", forbidden, "forbidden"))
    digest = taxonomy_digest(taxonomy)
    ids = tuple(d.id for d in chosen)
    return MinerSpec(
        name=name,
        version=version,
        selector=selector,
        fields=(category, quote, described_as),
        row_key_fields=() if row_key == ROW_KEY_WORK else ("category",),
        row_anchor_fields=(),
        conditionals=tuple(conditionals),
        evidence=EvidenceRule(
            min_quotes_per_record=1, enum_needs_quote=True, absence_values=tuple(absent)
        ),
        procedure=procedure,
        regime=regime,
        rationale=(
            f"Derived from taxonomy {taxonomy.name} version {taxonomy.version} "
            f"(digest {digest}); dimensions: {', '.join(ids)}."
        ),
        taxonomy=TaxonomyRef(taxonomy.name, taxonomy.version, digest, ids),
    )
