"""Agreement of the two passes of a derived (taxonomy) miner, per dimension (plan 2026-11-12 §3.2).

Rows are one per (work, category) under the key `category` alone (B2), so agreement is set
comparison per dimension, never row alignment.

Invariants:
- Only category values are compared. Quotes and `described_as` are evidence and are never
  compared, so two passes citing different sentences for one category agree.
- Only live rows enter, read through the extraction readers: superseded rows, stale rows, rows of
  works outside the miner's population, calibration rows and works filled by an import never do. A
  work enters only when its pass A and pass B units are both current and it is in the dual sample
  (recorded seed, declared fraction). Single-pass works are not compared.
- A dimension's set of a pass is the full ids (`dimension/category`) of that pass's live rows
  whose category falls in the dimension; residuals (`other`, `not-stated`, `not-applicable`) are
  values like any other.
- Per dimension each compared work falls in exactly one bucket: both passes without a row
  (skipped); one pass without a row (`one_pass_missing`, completeness); one pass exactly
  `<dim>/not-stated` and the other without it (`not_stated_vs_category`, completeness, ruling Q5);
  otherwise compared. Completeness works are excluded from disagreement counts, rates, kappa and
  Jaccard.
- `single` dimensions: rate and Cohen's kappa over the category labels (a set of several values,
  which a single dimension should not hold, is its sorted values joined by `|`). `multi`
  dimensions: per category, presence counts and a binary kappa, and per-work Jaccard with its mean.
  Kappa is None when undefined.
- Counts are computed from the rows, never supplied. Order is deterministic: dimensions in
  taxonomy order, categories sorted, works by id.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from factory.errors import FactoryValidationError, ValidationIssue
from factory.mining.spec import MinerSpec
from factory.mining.taxonomy import Dimension, TaxonomySpec, full_id
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.quality.stats import cohen_kappa, cohen_kappa_nominal
from factory.services.context import Project
from factory.services.extraction import (
    filled_imports,
    in_dual_sample,
    live_rows,
    pass_config,
    scope_population,
    stale_extractions,
    unit_states,
)
from factory.services.mining import miner_schema, registered_miner
from factory.services.protocol import current_protocol
from factory.services.taxonomies import layer_categories, registered_taxonomy

__all__ = [
    "CategoryPresence",
    "DimensionAgreement",
    "DimensionDisagreement",
    "TaxonomyAgreement",
    "taxonomy_agreement",
]

NOT_STATED = "not-stated"
_CATEGORY = "category"


@dataclass(frozen=True)
class CategoryPresence:
    """One category of a `multi` dimension: presence in pass A against pass B over the compared
    works of the dimension."""

    category: str
    both: int
    a_only: int
    b_only: int
    neither: int
    kappa: float | None


@dataclass(frozen=True)
class DimensionDisagreement:
    """A compared work whose two sets differ in a dimension."""

    work_id: str
    dimension: str
    a: tuple[str, ...]
    b: tuple[str, ...]


@dataclass(frozen=True)
class DimensionAgreement:
    """Agreement of one dimension. `rate` is works equal over works compared (None when none was).
    `kappa` and `mean_jaccard` are set by `single` and `multi` dimensions respectively; `presence`
    and `jaccard_by_work` are empty for a `single` dimension."""

    dimension: str
    cardinality: str
    works_compared: int
    works_equal: int
    rate: float | None
    kappa: float | None
    presence: tuple[CategoryPresence, ...]
    mean_jaccard: float | None
    jaccard_by_work: tuple[tuple[str, float], ...]
    not_stated_vs_category: tuple[str, ...]
    one_pass_missing: tuple[str, ...]


@dataclass(frozen=True)
class TaxonomyAgreement:
    """The agreement of a derived miner's two passes over the works whose units are current in
    both. `disagreements` is by dimension, then work."""

    miner: str
    version: int
    taxonomy: str
    taxonomy_version: int
    works_dual: int
    dimensions: tuple[DimensionAgreement, ...]
    disagreements: tuple[DimensionDisagreement, ...]


def _refuse(field: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, message)])


def _spec(project: Project, name: str) -> MinerSpec:
    """The registered spec of the miner version the protocol lists; raises when it is not
    listed, not registered or not derived from a taxonomy."""
    miner_schema(project, name)  # raises when the protocol does not list `name`
    protocol = current_protocol(project)
    use = next(
        (u for u in (protocol.spec.miners or ()) if u.name == name) if protocol else iter(()),
        None,
    )
    spec = None if use is None else registered_miner(project, name, use.version)
    if spec is None:
        raise _refuse("miner", f"miner {name} is not registered")
    if spec.taxonomy is None:
        raise _refuse("miner", f"miner {name} is not derived from a taxonomy")
    return spec


def _category_values(project: Project, taxonomy: TaxonomySpec, dimension: Dimension) -> list[str]:
    """Every full id the dimension can take, categories then residuals."""
    if dimension.layer_scheme is not None:
        names = list(layer_categories(project, taxonomy))
    else:
        names = [c.id for c in dimension.categories]
    return [full_id(dimension.id, n) for n in (*names, *dimension.residuals)]


def _sets(
    project: Project, name: str, work: str, label: PassLabel, stale: set[str]
) -> dict[str, set[str]]:
    """The category values of one pass of one work, by dimension id (the part before `/`)."""
    found: dict[str, set[str]] = {}
    for row in live_rows(project, label, work_id=work, scope=MinerScope(name)):
        if row.extraction_id in stale or _CATEGORY not in row.fields:
            continue
        value = str(row.fields[_CATEGORY].value)
        found.setdefault(value.split("/", 1)[0], set()).add(value)
    return found


def _dual_works(project: Project, name: str, fraction: float | None) -> list[str]:
    """The works in the dual sample whose pass A and pass B units are both current."""
    scope = MinerScope(name)
    config = pass_config(project, PassLabel.B, scope=scope)
    if config is None or pass_config(project, PassLabel.A, scope=scope) is None:
        return []
    filled = set(filled_imports(project, scope))
    current = {
        (s.work_id, s.pass_label) for s in unit_states(project, scope=scope) if s.state == "current"
    }
    return [
        w
        for w in sorted(scope_population(project, scope))
        if w not in filled
        and in_dual_sample(config.seed, w, fraction)
        and (w, PassLabel.A) in current
        and (w, PassLabel.B) in current
    ]


def _label(values: set[str]) -> str:
    return "|".join(sorted(values))


def _agreement(
    project: Project,
    taxonomy: TaxonomySpec,
    dimension: Dimension,
    works: Mapping[str, tuple[dict[str, set[str]], dict[str, set[str]]]],
) -> tuple[DimensionAgreement, list[DimensionDisagreement]]:
    not_stated = full_id(dimension.id, NOT_STATED)
    compared: list[tuple[str, set[str], set[str]]] = []
    absent_vs_category: list[str] = []
    missing: list[str] = []
    for work in sorted(works):
        a = works[work][0].get(dimension.id, set())
        b = works[work][1].get(dimension.id, set())
        if not a and not b:
            continue
        if not a or not b:
            missing.append(work)
        elif (a == {not_stated} and not_stated not in b) or (
            b == {not_stated} and not_stated not in a
        ):
            absent_vs_category.append(work)
        else:
            compared.append((work, a, b))
    differing = [
        DimensionDisagreement(w, dimension.id, tuple(sorted(a)), tuple(sorted(b)))
        for w, a, b in compared
        if a != b
    ]
    equal = len(compared) - len(differing)
    rate = equal / len(compared) if compared else None
    kappa: float | None = None
    presence: list[CategoryPresence] = []
    jaccard: list[tuple[str, float]] = []
    mean: float | None = None
    if dimension.cardinality == "single":
        kappa = cohen_kappa_nominal([(_label(a), _label(b)) for _, a, b in compared])
    else:
        observed = {v for _, a, b in compared for v in (*a, *b)}
        for value in sorted({*_category_values(project, taxonomy, dimension), *observed}):
            pairs = [(value in a, value in b) for _, a, b in compared]
            presence.append(
                CategoryPresence(
                    category=value,
                    both=sum(1 for x, y in pairs if x and y),
                    a_only=sum(1 for x, y in pairs if x and not y),
                    b_only=sum(1 for x, y in pairs if y and not x),
                    neither=sum(1 for x, y in pairs if not x and not y),
                    kappa=cohen_kappa(pairs),
                )
            )
        jaccard = [(w, len(a & b) / len(a | b)) for w, a, b in compared]
        mean = sum(j for _, j in jaccard) / len(jaccard) if jaccard else None
    return (
        DimensionAgreement(
            dimension=dimension.id,
            cardinality=dimension.cardinality,
            works_compared=len(compared),
            works_equal=equal,
            rate=rate,
            kappa=kappa,
            presence=tuple(presence),
            mean_jaccard=mean,
            jaccard_by_work=tuple(jaccard),
            not_stated_vs_category=tuple(absent_vs_category),
            one_pass_missing=tuple(missing),
        ),
        differing,
    )


def taxonomy_agreement(project: Project, miner_name: str) -> TaxonomyAgreement:
    """The per-dimension agreement of the derived miner `miner_name`. Raises
    `FactoryValidationError` (field `miner`) when the miner is not listed and registered, is not
    derived from a taxonomy, or its taxonomy version is not registered. Read-only."""
    project.index.sync()
    spec = _spec(project, miner_name)
    ref = spec.taxonomy
    assert ref is not None
    taxonomy = registered_taxonomy(project, ref.name, ref.version)
    if taxonomy is None:
        raise _refuse("miner", f"taxonomy {ref.name} version {ref.version} is not registered")
    _, schema, _ = miner_schema(project, miner_name)
    stale = stale_extractions(project, scope=MinerScope(miner_name))
    dual = _dual_works(project, miner_name, schema.dual_extract_sample)
    works = {
        w: (
            _sets(project, miner_name, w, PassLabel.A, stale),
            _sets(project, miner_name, w, PassLabel.B, stale),
        )
        for w in dual
    }
    dimensions: list[DimensionAgreement] = []
    disagreements: list[DimensionDisagreement] = []
    for dimension in taxonomy.dimensions:
        if dimension.id not in ref.dimensions:
            continue
        result, differing = _agreement(project, taxonomy, dimension, works)
        dimensions.append(result)
        disagreements.extend(differing)
    return TaxonomyAgreement(
        miner=spec.name,
        version=spec.version,
        taxonomy=taxonomy.name,
        taxonomy_version=taxonomy.version,
        works_dual=len(dual),
        dimensions=tuple(dimensions),
        disagreements=tuple(disagreements),
    )
