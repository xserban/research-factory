"""Resolve a selection of papers to the works a chat will read (plan chat, T1).

A `SelectionSpec` names a population, optional layers, and explicit includes and excludes. The
result lists the works kept, each with its default conversion and size, and the works left out with
the reason.

Invariants:
- Read-only: no event is written. The index is synced before reading.
- Validated at the boundary: an unknown layer (not a layer of the project's current layer scheme)
  is refused on field `layers` before anything is read.
- `works` and `excluded` are sorted by work id; a work appears in at most one of them.
- A work is kept only with a default conversion; one without goes to `excluded` as
  `no-conversion`. An `include` id that is no work of the project goes to `excluded` as
  `unknown-work`; an explicitly excluded work is listed as `excluded` when it was otherwise
  selected.
- `chars` is the sum of the characters of the canonical Markdown of the kept conversions;
  `est_tokens` is an estimate only (`chars // CHARS_PER_TOKEN`).
- `digest` is the sha256 of the canonical JSON of the sorted `[work_id, conversion_id]` pairs, so
  it does not depend on input order and changes when a conversion changes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import Field, JsonValue
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.errors import FactoryValidationError, ValidationIssue
from factory.mining.spec import Population
from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.conversions import conversion_of
from factory.services.document_read import default_conversions
from factory.services.mining import population_works
from factory.services.reference_layers import current_scheme
from factory.services.work_layers import layers_for

__all__ = [
    "CHARS_PER_TOKEN",
    "SelectedWork",
    "Selection",
    "SelectionSpec",
    "resolve_selection",
]

CHARS_PER_TOKEN = 4
"""Characters per token used for `est_tokens`. A rough estimate, not a tokeniser count."""


class SelectionSpec(StrictModel):
    """Which works a chat reads: the works of `population`, restricted to `layers` when given,
    plus `include` (known works, even outside the population), minus `exclude`."""

    layers: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    population: Population = Population.INCLUDED_FT


@dataclass(frozen=True)
class SelectedWork:
    """One kept work with the conversion a chat reads and its size in characters."""

    work_id: str
    document_id: str
    conversion_id: str
    chars: int


@dataclass(frozen=True)
class Selection:
    """The resolved selection (see the module invariants)."""

    works: tuple[SelectedWork, ...]
    excluded: tuple[tuple[str, str], ...]
    chars: int
    est_tokens: int
    digest: str


def _known_layers(project: Project) -> set[str]:
    scheme = current_scheme(project)
    return set() if scheme is None else {d.id for d in scheme.layers}


def _is_work(project: Project, work_id: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT 1 FROM works WHERE work_id = :w"), {"w": work_id}).first()
    return row is not None


def _markdown_chars(project: Project, conversion_id: str) -> int:
    conversion = conversion_of(project, conversion_id)
    if conversion is None:
        raise FactoryValidationError(
            [ValidationIssue("conversion_id", f"{conversion_id}: unknown conversion")]
        )
    return len(project.library.get(conversion.markdown_hash).decode("utf-8"))


def resolve_selection(project: Project, spec: SelectionSpec) -> Selection:
    """Resolve `spec` to the kept works and the left-out ones. Read-only; see the module
    invariants. Raises `FactoryValidationError` on field `layers` for an unknown layer."""
    project.index.sync()
    unknown = sorted(set(spec.layers) - _known_layers(project))
    if unknown:
        raise FactoryValidationError(
            [ValidationIssue("layers", f"unknown layer: {', '.join(unknown)}")]
        )

    base = list(population_works(project, spec.population))
    if spec.layers:
        wanted = set(spec.layers)
        found = layers_for(project, base)
        base = [w for w in base if w in found and found[w].layer in wanted]
    candidates = set(base)
    excluded: dict[str, str] = {}
    for work in spec.include:
        if work in candidates:
            continue
        if _is_work(project, work):
            candidates.add(work)
        else:
            excluded[work] = "unknown-work"
    for work in spec.exclude:
        if work in candidates:
            candidates.discard(work)
            excluded[work] = "excluded"

    ordered = sorted(candidates)
    conversions = default_conversions(project, ordered)
    works: list[SelectedWork] = []
    for work in ordered:
        ref = conversions.get(work)
        if ref is None:
            excluded[work] = "no-conversion"
            continue
        works.append(
            SelectedWork(
                work,
                ref.document_id,
                ref.conversion_id,
                _markdown_chars(project, ref.conversion_id),
            )
        )
    pairs: list[JsonValue] = [[w.work_id, w.conversion_id] for w in works]
    total = sum(w.chars for w in works)
    return Selection(
        works=tuple(works),
        excluded=tuple(sorted(excluded.items())),
        chars=total,
        est_tokens=total // CHARS_PER_TOKEN,
        digest=hashlib.sha256(canonical_json(pairs)).hexdigest(),
    )
