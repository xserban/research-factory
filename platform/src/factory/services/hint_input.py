"""A human's capture hints as typed, resolved into the recorded `CaptureHints` (IDEA-81).

Invariants:
- Only a human gives hints; an agent's hints are refused with nothing written.
- A layer must be an id of the latest recorded layer scheme and is recorded with that scheme's
  version; a category must be a full category id (`dimension/category`) of the latest version of a
  registered taxonomy and is recorded with its name and version. These versions are what makes a
  hint stale later (`capture_hints.hint_staleness`).
- Blank fields are absent; a hint with nothing set is no hint (None, nothing recorded).
- Read-only: the caller holds the write lock and records the event.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from factory.errors import ValidationIssue
from factory.events.envelope import Actor
from factory.mining.taxonomy import TaxonomySpec, full_id
from factory.model.inbox import MAX_MINER_NOTES, CaptureHints
from factory.services.context import Project
from factory.services.reference_layers import current_scheme
from factory.services.taxonomies import registered_taxonomy

__all__ = ["HintInput", "resolve_hints"]


@dataclass(frozen=True)
class HintInput:
    """The hints as the researcher typed them: all optional. `taxonomy` names the taxonomy of
    `category` and may be left out when exactly one registered taxonomy holds the category."""

    layer: str | None = None
    category: str | None = None
    taxonomy: str | None = None
    miner_notes: str | None = None

    def empty(self) -> bool:
        return not any(
            _clean(v) for v in (self.layer, self.category, self.taxonomy, self.miner_notes)
        )


def _clean(value: str | None) -> str | None:
    return None if value is None or not value.strip() else value.strip()


def _latest_taxonomies(project: Project) -> dict[str, int]:
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT name, MAX(version) FROM taxonomies GROUP BY name")).all()
    return {str(r[0]): int(r[1]) for r in rows}


def _category_holders(project: Project, category: str, latest: dict[str, int]) -> list[str]:
    found: list[str] = []
    for name, version in sorted(latest.items()):
        spec = registered_taxonomy(project, name, version)
        if spec is None:
            continue
        ids = {full_id(d.id, c.id) for d in spec.dimensions for c in d.categories}
        scheme_ids = _scheme_categories(project, spec)
        if category in ids | scheme_ids:
            found.append(name)
    return found


def _scheme_categories(project: Project, spec: TaxonomySpec) -> set[str]:
    """Dimension zero's categories: the layers of the recorded scheme, as `dimension/layer`."""
    out: set[str] = set()
    scheme = current_scheme(project)
    if scheme is None:
        return out
    for dimension in spec.dimensions:
        if dimension.layer_scheme is not None:
            out.update(full_id(dimension.id, layer.id) for layer in scheme.layers)
    return out


def resolve_hints(
    project: Project, actor: Actor, given: HintInput | None
) -> tuple[CaptureHints | None, list[ValidationIssue]]:
    """`(hints, [])` for valid hints, `(None, [])` for none or empty ones, `(None, issues)` for
    invalid ones (fields `hints`, `hints.layer`, `hints.category`, `hints.taxonomy`,
    `hints.miner_notes`)."""
    if given is None or given.empty():
        return None, []
    if actor.kind != "human":
        return None, [ValidationIssue("hints", "only the researcher gives capture hints")]
    issues: list[ValidationIssue] = []
    layer = _clean(given.layer)
    category = _clean(given.category)
    taxonomy = _clean(given.taxonomy)
    notes = _clean(given.miner_notes)
    scheme_version: int | None = None
    if layer is not None:
        scheme = current_scheme(project)
        if scheme is None:
            issues.append(ValidationIssue("hints.layer", "no layer scheme is recorded"))
        elif layer not in {d.id for d in scheme.layers}:
            issues.append(
                ValidationIssue(
                    "hints.layer", f"{layer} is not a layer of scheme version {scheme.version}"
                )
            )
        else:
            scheme_version = scheme.version
    if notes is not None and len(notes) > MAX_MINER_NOTES:
        issues.append(ValidationIssue("hints.miner_notes", f"at most {MAX_MINER_NOTES} characters"))
    taxonomy_version: int | None = None
    if taxonomy is not None and category is None:
        issues.append(ValidationIssue("hints.taxonomy", "a taxonomy needs a category"))
    if category is not None:
        latest = _latest_taxonomies(project)
        if taxonomy is not None:
            if taxonomy not in latest:
                issues.append(ValidationIssue("hints.taxonomy", f"unknown taxonomy {taxonomy}"))
            elif taxonomy not in _category_holders(project, category, {taxonomy: latest[taxonomy]}):
                issues.append(
                    ValidationIssue(
                        "hints.category",
                        f"{category} is not a category of {taxonomy} version {latest[taxonomy]}",
                    )
                )
            else:
                taxonomy_version = latest[taxonomy]
        else:
            holders = _category_holders(project, category, latest)
            if len(holders) == 1:
                taxonomy = holders[0]
                taxonomy_version = latest[taxonomy]
            elif not holders:
                issues.append(
                    ValidationIssue("hints.category", f"{category} is in no registered taxonomy")
                )
            else:
                issues.append(
                    ValidationIssue(
                        "hints.taxonomy",
                        f"{category} is in {', '.join(holders)}: name the taxonomy",
                    )
                )
    if issues:
        return None, issues
    try:
        hints = CaptureHints(
            layer=layer,
            scheme_version=scheme_version,
            category=category,
            taxonomy=taxonomy,
            taxonomy_version=taxonomy_version,
            miner_notes=notes,
        )
    except ValueError as exc:
        return None, [ValidationIssue("hints", str(exc))]
    return hints, []
