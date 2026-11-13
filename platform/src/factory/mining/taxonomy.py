"""Taxonomies: named, versioned classification schemes, as pure data (plan 2026-11-12 §2, §5).

A taxonomy is a registered specification (`t-` names) of dimensions and their categories. This
module holds the value types, the canonical JSON form, the meaning checks, the two digests and the
diff between two versions. It is pure: no services, no I/O, no clock, no randomness.

Invariants:
- `taxonomy_from_json(taxonomy_to_json(s)) == s` for every spec; the JSON form is canonical (lists
  in declaration order, absent optional values as null).
- `taxonomy_from_json` checks shape only and raises `FactoryValidationError` with dotted paths
  and writes nothing; `validate_taxonomy` checks meaning and returns the issues.
- `taxonomy_digest` hashes the spec without prose: rationale, accepts, rejects, dimension titles,
  category names, patterns and lineage. Two specs that differ only in prose share a digest.
- `category_digest` covers a category's definition, cues and examples, so a diff names the
  categories whose meaning changed; a rename alone does not change it.
- Dimension zero: a dimension with `layer_scheme` set has no categories in the spec; the service
  imports them from that layer scheme. Any other dimension has at least one category.
- `diff` and `lineage_issues` are computed from the two specs; lineage is the researcher's
  statement and is checked against the computed diff, never trusted.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.errors import FactoryValidationError, ValidationIssue
from factory.mining.spec import _Reader

TAXONOMY_NAME_RE = r"^t-[a-z0-9][a-z0-9-]*$"
SLUG_RE = r"^[a-z0-9][a-z0-9-]*$"
RESIDUALS: tuple[str, ...] = ("other", "not-stated", "not-applicable")
REQUIRED_RESIDUALS: tuple[str, ...] = ("other", "not-stated")

Cardinality = Literal["single", "multi"]


# --- value types -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Example:
    """A verbatim quote that illustrates a category, with its work and anchor."""

    quote: str
    work_id: str
    anchor: str


@dataclass(frozen=True)
class Lineage:
    """The researcher's statement of the previous version's categories this one came from."""

    split_from: tuple[str, ...] = ()
    merged_from: tuple[str, ...] = ()
    renamed_from: str | None = None


@dataclass(frozen=True)
class Category:
    """A category within a dimension. `name` and `pattern` and `lineage` are prose or
    counting aids: they are not part of the category's digest."""

    id: str
    name: str
    definition: str
    include_cues: tuple[str, ...] = ()
    exclude_cues: tuple[str, ...] = ()
    examples: tuple[Example, ...] = ()
    pattern: str | None = None
    lineage: Lineage = Lineage()


@dataclass(frozen=True)
class ReadScope:
    """Where a dimension's facts may sit: heading patterns, or the whole text."""

    headings: tuple[str, ...] = ()
    whole_text: bool = False


@dataclass(frozen=True)
class Dimension:
    """One question a work is classified by. A dimension with `layer_scheme` set is dimension
    zero: its categories come from that layer scheme, so `categories` is empty in the spec."""

    id: str
    title: str
    question: str
    cardinality: Cardinality
    categories: tuple[Category, ...]
    max_labels: int | None = None
    applies_to_layers: tuple[str, ...] = ()
    read_scope: ReadScope = ReadScope()
    residuals: tuple[str, ...] = REQUIRED_RESIDUALS
    layer_scheme: int | None = None


@dataclass(frozen=True)
class ProposalRejection:
    """A proposal this version rejects, with the researcher's reason."""

    proposal_id: str
    reason: str


@dataclass(frozen=True)
class TaxonomySpec:
    """A taxonomy version. `rationale`, `accepts` and `rejects` are prose and are not digested."""

    name: str
    version: int
    dimensions: tuple[Dimension, ...]
    rationale: str = ""
    accepts: tuple[str, ...] = ()
    rejects: tuple[ProposalRejection, ...] = ()

    def dimension_named(self, dimension_id: str) -> Dimension | None:
        """The dimension with `dimension_id`, or None."""
        for dimension in self.dimensions:
            if dimension.id == dimension_id:
                return dimension
        return None


def full_id(dimension_id: str, category_id: str) -> str:
    """The identity a row cites: `dimension/category`, for example `technique/multi-agent`."""
    return f"{dimension_id}/{category_id}"


# --- JSON form -------------------------------------------------------------------------------

_TAXONOMY_KEYS = {"name", "version", "dimensions", "rationale", "accepts", "rejects"}
_DIMENSION_KEYS = {
    "id", "title", "question", "cardinality", "categories", "max_labels",
    "applies_to_layers", "read_scope", "residuals", "layer_scheme",
}  # fmt: skip
_CATEGORY_KEYS = {
    "id", "name", "definition", "include_cues", "exclude_cues", "examples", "pattern", "lineage",
}  # fmt: skip
_EXAMPLE_KEYS = {"quote", "work_id", "anchor"}
_LINEAGE_KEYS = {"split_from", "merged_from", "renamed_from"}
_READ_SCOPE_KEYS = {"headings", "whole_text"}
_REJECTION_KEYS = {"proposal_id", "reason"}


def _example_json(example: Example) -> dict[str, JsonValue]:
    return {"quote": example.quote, "work_id": example.work_id, "anchor": example.anchor}


def _category_json(category: Category) -> dict[str, JsonValue]:
    examples: list[JsonValue] = [_example_json(e) for e in category.examples]
    lineage = category.lineage
    return {
        "id": category.id,
        "name": category.name,
        "definition": category.definition,
        "include_cues": list(category.include_cues),
        "exclude_cues": list(category.exclude_cues),
        "examples": examples,
        "pattern": category.pattern,
        "lineage": {
            "split_from": list(lineage.split_from),
            "merged_from": list(lineage.merged_from),
            "renamed_from": lineage.renamed_from,
        },
    }


def _dimension_json(dimension: Dimension) -> dict[str, JsonValue]:
    categories: list[JsonValue] = [_category_json(c) for c in dimension.categories]
    scope = dimension.read_scope
    return {
        "id": dimension.id,
        "title": dimension.title,
        "question": dimension.question,
        "cardinality": dimension.cardinality,
        "categories": categories,
        "max_labels": dimension.max_labels,
        "applies_to_layers": list(dimension.applies_to_layers),
        "read_scope": {"headings": list(scope.headings), "whole_text": scope.whole_text},
        "residuals": list(dimension.residuals),
        "layer_scheme": dimension.layer_scheme,
    }


def taxonomy_to_json(spec: TaxonomySpec) -> dict[str, JsonValue]:
    """The canonical JSON form of `spec`, in declaration order (prose included)."""
    dimensions: list[JsonValue] = [_dimension_json(d) for d in spec.dimensions]
    rejects: list[JsonValue] = [
        {"proposal_id": r.proposal_id, "reason": r.reason} for r in spec.rejects
    ]
    return {
        "name": spec.name,
        "version": spec.version,
        "dimensions": dimensions,
        "rationale": spec.rationale,
        "accepts": list(spec.accepts),
        "rejects": rejects,
    }


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _elements(
    r: _Reader, data: dict[str, object], key: str, path: str, *, required: bool = False
) -> list[tuple[str, object]]:
    """The elements of the list under `key`, each with its dotted path. A missing required list
    or a non-list is an issue; a missing optional list is empty."""
    where = _join(path, key)
    if key not in data:
        if required:
            r.bad(where, "is required")
        return []
    value = data[key]
    if not isinstance(value, list):
        r.bad(where, "must be a list")
        return []
    return [(f"{where}[{i}]", item) for i, item in enumerate(value)]


def _opt_int(r: _Reader, data: dict[str, object], key: str, path: str) -> int | None:
    if data.get(key) is None:
        return None
    return r.integer(data, key, path, None)


def _opt_text(r: _Reader, data: dict[str, object], key: str, path: str) -> str | None:
    if data.get(key) is None:
        return None
    return r.text(data, key, path, None)


def _example_from(r: _Reader, value: object, path: str) -> Example:
    data = r.obj(value, path, _EXAMPLE_KEYS)
    return Example(
        quote=r.text(data, "quote", path, None),
        work_id=r.text(data, "work_id", path, None),
        anchor=r.text(data, "anchor", path, None),
    )


def _category_from(r: _Reader, value: object, path: str) -> Category:
    data = r.obj(value, path, _CATEGORY_KEYS)
    lineage_path = _join(path, "lineage")
    lineage_data = r.obj(data.get("lineage", {}), lineage_path, _LINEAGE_KEYS)
    lineage = Lineage(
        split_from=r.strings(lineage_data, "split_from", lineage_path),
        merged_from=r.strings(lineage_data, "merged_from", lineage_path),
        renamed_from=_opt_text(r, lineage_data, "renamed_from", lineage_path),
    )
    examples = tuple(
        _example_from(r, item, where) for where, item in _elements(r, data, "examples", path)
    )
    return Category(
        id=r.text(data, "id", path, None),
        name=r.text(data, "name", path, None),
        definition=r.text(data, "definition", path, None),
        include_cues=r.strings(data, "include_cues", path),
        exclude_cues=r.strings(data, "exclude_cues", path),
        examples=examples,
        pattern=_opt_text(r, data, "pattern", path),
        lineage=lineage,
    )


def _dimension_from(r: _Reader, value: object, path: str) -> Dimension:
    data = r.obj(value, path, _DIMENSION_KEYS)
    cardinality_raw = r.text(data, "cardinality", path, None)
    if cardinality_raw not in ("single", "multi"):
        r.bad(_join(path, "cardinality"), "must be single or multi")
    cardinality: Cardinality = "multi" if cardinality_raw == "multi" else "single"
    categories = tuple(
        _category_from(r, item, where)
        for where, item in _elements(r, data, "categories", path, required=True)
    )
    scope_path = _join(path, "read_scope")
    scope_data = r.obj(data.get("read_scope", {}), scope_path, _READ_SCOPE_KEYS)
    read_scope = ReadScope(
        headings=r.strings(scope_data, "headings", scope_path),
        whole_text=r.boolean(scope_data, "whole_text", scope_path, False),
    )
    residuals = r.strings(data, "residuals", path) if "residuals" in data else REQUIRED_RESIDUALS
    return Dimension(
        id=r.text(data, "id", path, None),
        title=r.text(data, "title", path, None),
        question=r.text(data, "question", path, None),
        cardinality=cardinality,
        categories=categories,
        max_labels=_opt_int(r, data, "max_labels", path),
        applies_to_layers=r.strings(data, "applies_to_layers", path),
        read_scope=read_scope,
        residuals=residuals,
        layer_scheme=_opt_int(r, data, "layer_scheme", path),
    )


def _rejection_from(r: _Reader, value: object, path: str) -> ProposalRejection:
    data = r.obj(value, path, _REJECTION_KEYS)
    return ProposalRejection(
        proposal_id=r.text(data, "proposal_id", path, None),
        reason=r.text(data, "reason", path, None),
    )


def taxonomy_from_json(value: object) -> TaxonomySpec:
    """The spec `value` describes. Raises `FactoryValidationError` (dotted paths) on any shape
    error: a missing or unknown key, a wrong type, a cardinality other than single or multi.
    Shape only; `validate_taxonomy` checks meaning."""
    r = _Reader()
    top = r.obj(value, "", _TAXONOMY_KEYS)
    name = r.text(top, "name", "", None)
    version = r.integer(top, "version", "", None)
    dimensions = tuple(
        _dimension_from(r, item, where)
        for where, item in _elements(r, top, "dimensions", "", required=True)
    )
    rejects = tuple(
        _rejection_from(r, item, where) for where, item in _elements(r, top, "rejects", "")
    )
    spec = TaxonomySpec(
        name=name,
        version=version,
        dimensions=dimensions,
        rationale=r.text(top, "rationale", "", ""),
        accepts=r.strings(top, "accepts", ""),
        rejects=rejects,
    )
    if r.issues:
        raise FactoryValidationError(r.issues)
    return spec


# --- meaning ---------------------------------------------------------------------------------


def _is_slug(text: str) -> bool:
    return re.fullmatch(SLUG_RE, text) is not None


def _compiles(pattern: str) -> bool:
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def validate_taxonomy(spec: TaxonomySpec) -> list[ValidationIssue]:
    """The meaning problems of `spec`, located by dotted path. An empty list means valid.

    Checks: the name; the version; dimension and category ids (slugs, unique, no residual
    name); residuals (a subset of `RESIDUALS` that includes `REQUIRED_RESIDUALS`, no
    duplicates); `max_labels` only for multi cardinality and at least 1; at most one layer-scheme
    dimension, which has no categories and a scheme of at least 1; every other dimension has a
    category; definitions not blank; patterns and heading patterns compile; lineage ids are slugs.
    """
    issues: list[ValidationIssue] = []
    if not re.fullmatch(TAXONOMY_NAME_RE, spec.name):
        issues.append(ValidationIssue("name", "must match t-<slug>"))
    if spec.version < 1:
        issues.append(ValidationIssue("version", "must be at least 1"))
    seen_dimensions: set[str] = set()
    layer_dimensions = 0
    for i, dimension in enumerate(spec.dimensions):
        dp = f"dimensions[{i}]"
        if not _is_slug(dimension.id):
            issues.append(ValidationIssue(f"{dp}.id", "must be a slug"))
        if dimension.id in seen_dimensions:
            issues.append(ValidationIssue(f"{dp}.id", "is already used by another dimension"))
        seen_dimensions.add(dimension.id)
        if dimension.cardinality not in ("single", "multi"):
            issues.append(ValidationIssue(f"{dp}.cardinality", "must be single or multi"))
        _residual_issues(dimension, dp, issues)
        if dimension.max_labels is not None:
            if dimension.cardinality != "multi":
                issues.append(ValidationIssue(f"{dp}.max_labels", "only with multi cardinality"))
            if dimension.max_labels < 1:
                issues.append(ValidationIssue(f"{dp}.max_labels", "must be at least 1"))
        if dimension.layer_scheme is not None:
            layer_dimensions += 1
            if dimension.layer_scheme < 1:
                issues.append(ValidationIssue(f"{dp}.layer_scheme", "must be at least 1"))
            if dimension.categories:
                issues.append(
                    ValidationIssue(f"{dp}.categories", "a layer-scheme dimension takes none")
                )
            if layer_dimensions > 1:
                issues.append(
                    ValidationIssue(f"{dp}.layer_scheme", "only one dimension may take a scheme")
                )
        elif not dimension.categories:
            issues.append(ValidationIssue(f"{dp}.categories", "must have at least one category"))
        for k, heading in enumerate(dimension.read_scope.headings):
            if not _compiles(heading):
                issues.append(ValidationIssue(f"{dp}.read_scope.headings[{k}]", "must be a regex"))
        _category_issues(dimension, dp, issues)
    return issues


def _residual_issues(dimension: Dimension, dp: str, issues: list[ValidationIssue]) -> None:
    where = f"{dp}.residuals"
    for residual in dimension.residuals:
        if residual not in RESIDUALS:
            issues.append(ValidationIssue(where, f"unknown residual {residual}"))
    for required in REQUIRED_RESIDUALS:
        if required not in dimension.residuals:
            issues.append(ValidationIssue(where, f"must include {required}"))
    if len(set(dimension.residuals)) != len(dimension.residuals):
        issues.append(ValidationIssue(where, "must not repeat a residual"))


def _category_issues(dimension: Dimension, dp: str, issues: list[ValidationIssue]) -> None:
    seen: set[str] = set()
    for j, category in enumerate(dimension.categories):
        cp = f"{dp}.categories[{j}]"
        if category.id in RESIDUALS:
            issues.append(ValidationIssue(f"{cp}.id", "must not be a residual name"))
        elif not _is_slug(category.id):
            issues.append(ValidationIssue(f"{cp}.id", "must be a slug"))
        if category.id in seen:
            issues.append(ValidationIssue(f"{cp}.id", "is already used in this dimension"))
        seen.add(category.id)
        if not category.definition.strip():
            issues.append(ValidationIssue(f"{cp}.definition", "must not be blank"))
        if category.pattern is not None and not _compiles(category.pattern):
            issues.append(ValidationIssue(f"{cp}.pattern", "must be a regex"))
        lineage = category.lineage
        for name, ids in (("split_from", lineage.split_from), ("merged_from", lineage.merged_from)):
            for k, previous in enumerate(ids):
                if not _is_slug(previous):
                    issues.append(ValidationIssue(f"{cp}.lineage.{name}[{k}]", "must be a slug"))
        if lineage.renamed_from is not None and not _is_slug(lineage.renamed_from):
            issues.append(ValidationIssue(f"{cp}.lineage.renamed_from", "must be a slug"))


# --- digests ---------------------------------------------------------------------------------


def _digest_category(category: Category) -> dict[str, JsonValue]:
    examples: list[JsonValue] = [_example_json(e) for e in category.examples]
    return {
        "id": category.id,
        "definition": category.definition,
        "include_cues": list(category.include_cues),
        "exclude_cues": list(category.exclude_cues),
        "examples": examples,
    }


def _digest_dimension(dimension: Dimension) -> dict[str, JsonValue]:
    categories: list[JsonValue] = [_digest_category(c) for c in dimension.categories]
    scope = dimension.read_scope
    return {
        "id": dimension.id,
        "question": dimension.question,
        "cardinality": dimension.cardinality,
        "categories": categories,
        "max_labels": dimension.max_labels,
        "applies_to_layers": list(dimension.applies_to_layers),
        "read_scope": {"headings": list(scope.headings), "whole_text": scope.whole_text},
        "residuals": list(dimension.residuals),
        "layer_scheme": dimension.layer_scheme,
    }


def taxonomy_digest(spec: TaxonomySpec) -> str:
    """16 hex digits: sha256 of the canonical JSON of `spec` without prose (rationale, accepts,
    rejects, dimension titles, category names, patterns and lineage)."""
    dimensions: list[JsonValue] = [_digest_dimension(d) for d in spec.dimensions]
    form: dict[str, JsonValue] = {
        "name": spec.name,
        "version": spec.version,
        "dimensions": dimensions,
    }
    return hashlib.sha256(canonical_json(form)).hexdigest()[:16]


def category_digest(category: Category) -> str:
    """16 hex digits over a category's definition, cues and examples. Names, patterns and
    lineage do not count, so a rename alone leaves the digest unchanged."""
    return hashlib.sha256(canonical_json(_digest_category(category))).hexdigest()[:16]


# --- diff ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TaxonomyDiff:
    """The computed difference between two versions. Every field is sorted.

    `added` excludes the children named by a split or a merge; `removed` lists every full id
    absent from the new version, split and merge parents included. `split` maps an old parent to
    its new children; `merged` maps old parents to the new child. `dimension_changes` pairs a
    dimension id with what changed in it (added, removed, or one attribute name).
    """

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    redefined: tuple[str, ...] = ()
    renamed: tuple[str, ...] = ()
    split: tuple[tuple[str, tuple[str, ...]], ...] = ()
    merged: tuple[tuple[tuple[str, ...], str], ...] = ()
    dimension_changes: tuple[tuple[str, str], ...] = ()


def _index(spec: TaxonomySpec) -> dict[str, tuple[str, Category]]:
    """Full id to (dimension id, category)."""
    return {full_id(d.id, c.id): (d.id, c) for d in spec.dimensions for c in d.categories}


def diff(old: TaxonomySpec, new: TaxonomySpec) -> TaxonomyDiff:
    """The difference from `old` to `new`, computed, never taken from lineage statements."""
    old_index = _index(old)
    new_index = _index(new)
    split_map: dict[str, list[str]] = {}
    merged_pairs: list[tuple[tuple[str, ...], str]] = []
    children: set[str] = set()
    for fid, (dim, category) in new_index.items():
        lineage = category.lineage
        if lineage.split_from:
            children.add(fid)
            for parent in lineage.split_from:
                split_map.setdefault(full_id(dim, parent), []).append(fid)
        if lineage.merged_from:
            children.add(fid)
            parents = tuple(sorted(full_id(dim, p) for p in lineage.merged_from))
            merged_pairs.append((parents, fid))

    shared = sorted(old_index.keys() & new_index.keys())
    redefined: list[str] = []
    renamed: list[str] = []
    for fid in shared:
        old_cat = old_index[fid][1]
        new_cat = new_index[fid][1]
        if category_digest(old_cat) != category_digest(new_cat):
            redefined.append(fid)
        elif old_cat.name != new_cat.name:
            renamed.append(fid)

    dimension_changes = _dimension_changes(old, new)
    return TaxonomyDiff(
        added=tuple(sorted(f for f in new_index if f not in old_index and f not in children)),
        removed=tuple(sorted(f for f in old_index if f not in new_index)),
        redefined=tuple(redefined),
        renamed=tuple(renamed),
        split=tuple((parent, tuple(sorted(kids))) for parent, kids in sorted(split_map.items())),
        merged=tuple(sorted(merged_pairs)),
        dimension_changes=dimension_changes,
    )


def _dimension_changes(old: TaxonomySpec, new: TaxonomySpec) -> tuple[tuple[str, str], ...]:
    old_dims = {d.id: d for d in old.dimensions}
    new_dims = {d.id: d for d in new.dimensions}
    changes: list[tuple[str, str]] = [(d, "removed") for d in old_dims.keys() - new_dims.keys()]
    changes.extend((d, "added") for d in new_dims.keys() - old_dims.keys())
    for dim_id in old_dims.keys() & new_dims.keys():
        before = old_dims[dim_id]
        after = new_dims[dim_id]
        checks: tuple[tuple[str, bool], ...] = (
            ("question", before.question != after.question),
            ("cardinality", before.cardinality != after.cardinality),
            ("max_labels", before.max_labels != after.max_labels),
            ("applies_to_layers", before.applies_to_layers != after.applies_to_layers),
            ("read_scope", before.read_scope != after.read_scope),
            ("residuals", before.residuals != after.residuals),
            ("layer_scheme", before.layer_scheme != after.layer_scheme),
        )
        changes.extend((dim_id, kind) for kind, changed in checks if changed)
    return tuple(sorted(changes))


def lineage_issues(old: TaxonomySpec, new: TaxonomySpec) -> list[ValidationIssue]:
    """Lineage names that match no category of the same dimension in `old`. An empty list means
    every statement of `split_from`, `merged_from` and `renamed_from` names a previous category."""
    issues: list[ValidationIssue] = []
    for i, dimension in enumerate(new.dimensions):
        previous = old.dimension_named(dimension.id)
        previous_ids = {c.id for c in previous.categories} if previous is not None else set()
        for j, category in enumerate(dimension.categories):
            base = f"dimensions[{i}].categories[{j}].lineage"
            reason = f"names no category of {dimension.id} in version {old.version}"
            lineage = category.lineage
            for name, ids in (
                ("split_from", lineage.split_from),
                ("merged_from", lineage.merged_from),
            ):
                for k, pid in enumerate(ids):
                    if pid not in previous_ids:
                        issues.append(ValidationIssue(f"{base}.{name}[{k}]", reason))
            if lineage.renamed_from is not None and lineage.renamed_from not in previous_ids:
                issues.append(ValidationIssue(f"{base}.renamed_from", reason))
    return issues
