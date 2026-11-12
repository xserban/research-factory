"""The miner specification: field kinds, selector, evidence rule, regime and JSON form.

A `MinerSpec` is data. Registered miners (names `m-...`) are built from it by an agent or a
human; the built-in packs convert to it and back (`factory.mining.compile`). Prose (`rationale`,
each field's `description`) is not part of the digest.

Invariants:
- `spec_from_json(spec_to_json(s)) == s` for every spec; the JSON form is canonical (lists in
  declaration order, enums as their values).
- `spec_from_json` raises `FactoryValidationError` with dotted field names and writes nothing;
  it checks shape only, `validate_miner` checks meaning.
- Keys added after the first registered miners (`taxonomy`, `evidence.absence_values`) are written
  only when not default, so existing spec blobs and miner digests do not change. `max_works` is an
  input alias of `max_units`; `spec_to_json` keeps writing `max_units`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import JsonValue

from factory.document.anchors import AnchorKind
from factory.errors import FactoryValidationError, ValidationIssue
from factory.packs.model import Conditional, ReportSpec, UnitFamily

FIELD_NAME_RE = r"^[a-z][a-z0-9_]*$"


class Population(StrEnum):
    """A population the platform computes from the log (never listed by an agent)."""

    INCLUDED_FINAL = "included-final"
    INCLUDED_TA = "included-ta"
    INCLUDED_FT = "included-ft"
    WITH_REFERENCES = "with-references"
    CORPUS = "corpus"


@dataclass(frozen=True)
class NumberKind:
    unit_family: UnitFamily
    units: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntegerKind:
    pass


@dataclass(frozen=True)
class EnumKind:
    values: tuple[str, ...]


@dataclass(frozen=True)
class QuoteKind:
    pass


@dataclass(frozen=True)
class CitationKind:
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class AnchorKindRef:
    kinds: tuple[AnchorKind, ...]


@dataclass(frozen=True)
class WorkRefKind:
    by: Literal["entry", "title"]


@dataclass(frozen=True)
class Unverified:
    """A field with no check; legal only in built-in packs. `kind` and `normaliser` keep the
    pack's `FieldDef` exactly, so that compiling a built-in miner gives back its pack."""

    kind: Literal["text", "integer", "bool"] = "text"
    normaliser: str | None = None


FieldKindSpec = (
    NumberKind
    | IntegerKind
    | EnumKind
    | QuoteKind
    | CitationKind
    | AnchorKindRef
    | WorkRefKind
    | Unverified
)


@dataclass(frozen=True)
class MinerField:
    """One field. `compared=False` keeps it out of dual-extraction agreement."""

    name: str
    group: str
    kind: FieldKindSpec
    required: bool = False
    description: str = ""
    compared: bool = True


@dataclass(frozen=True)
class Selector:
    """`max_units` caps the number of WORKS a miner reads, not paragraphs (JSON key `max_works`
    is accepted as its alias; `spec_to_json` writes `max_units`)."""

    population: Population
    elements: tuple[AnchorKind, ...] = ()
    heading_patterns: tuple[str, ...] = ()
    max_units: int | None = None


@dataclass(frozen=True)
class EvidenceRule:
    """`absence_values` are enum values that say the document does not state the fact (for
    example `<dim>/not-stated`); a record carrying one is exempt from the quote rule."""

    min_quotes_per_record: int = 1
    enum_needs_quote: bool = True
    absence_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class MinerRegime:
    passes: Literal[1, 2] = 2
    calibration_size: int = 10
    recall_min: float = 0.8
    field_agreement_min: float = 0.9


@dataclass(frozen=True)
class TaxonomyRef:
    """The taxonomy version a derived miner projects: its name, version, digest (the taxonomy
    digest at derivation) and the dimensions chosen, in taxonomy order."""

    name: str
    version: int
    digest: str
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class MinerSpec:
    """A miner. `comparability_keys` and `citation_patterns` are pack-level values a built-in
    carries (default comparability keys; patterns that mark a copied value); a registered miner
    leaves them empty. `report` is carried for built-ins only and is neither compared nor
    serialised."""

    name: str
    version: int
    selector: Selector
    fields: tuple[MinerField, ...]
    row_key_fields: tuple[str, ...]
    row_anchor_fields: tuple[str, ...]
    conditionals: tuple[Conditional, ...]
    evidence: EvidenceRule
    procedure: str
    regime: MinerRegime
    rationale: str = ""
    comparability_keys: tuple[str, ...] = ()
    citation_patterns: tuple[str, ...] = ()
    report: ReportSpec | None = field(default=None, repr=False, compare=False, hash=False)
    taxonomy: TaxonomyRef | None = None

    def field_named(self, name: str) -> MinerField | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


# --- JSON form -----------------------------------------------------------------------------


def kind_to_json(kind: FieldKindSpec) -> dict[str, JsonValue]:
    if isinstance(kind, NumberKind):
        return {"type": "number", "unit_family": kind.unit_family.value, "units": list(kind.units)}
    if isinstance(kind, IntegerKind):
        return {"type": "integer"}
    if isinstance(kind, EnumKind):
        return {"type": "enum", "values": list(kind.values)}
    if isinstance(kind, QuoteKind):
        return {"type": "quote"}
    if isinstance(kind, CitationKind):
        return {"type": "citation", "patterns": list(kind.patterns)}
    if isinstance(kind, AnchorKindRef):
        return {"type": "anchor", "kinds": [k.value for k in kind.kinds]}
    if isinstance(kind, WorkRefKind):
        return {"type": "work_ref", "by": kind.by}
    return {"type": "unverified", "value_kind": kind.kind, "normaliser": kind.normaliser}


def spec_to_json(spec: MinerSpec) -> dict[str, JsonValue]:
    """The canonical JSON form of `spec` (everything but `report`). `taxonomy` and
    `evidence.absence_values` appear only when set."""
    fields: list[JsonValue] = [
        {
            "name": f.name,
            "group": f.group,
            "kind": kind_to_json(f.kind),
            "required": f.required,
            "description": f.description,
            "compared": f.compared,
        }
        for f in spec.fields
    ]
    conditionals: list[JsonValue] = [
        {"field": c.field, "when": c.when, "values": list(c.values), "rule": c.rule}
        for c in spec.conditionals
    ]
    evidence: dict[str, JsonValue] = {
        "min_quotes_per_record": spec.evidence.min_quotes_per_record,
        "enum_needs_quote": spec.evidence.enum_needs_quote,
    }
    if spec.evidence.absence_values:
        evidence["absence_values"] = list(spec.evidence.absence_values)
    body: dict[str, JsonValue] = {
        "name": spec.name,
        "version": spec.version,
        "selector": {
            "population": spec.selector.population.value,
            "elements": [e.value for e in spec.selector.elements],
            "heading_patterns": list(spec.selector.heading_patterns),
            "max_units": spec.selector.max_units,
        },
        "fields": fields,
        "row_key_fields": list(spec.row_key_fields),
        "row_anchor_fields": list(spec.row_anchor_fields),
        "conditionals": conditionals,
        "evidence": evidence,
        "procedure": spec.procedure,
        "regime": {
            "passes": spec.regime.passes,
            "calibration_size": spec.regime.calibration_size,
            "recall_min": spec.regime.recall_min,
            "field_agreement_min": spec.regime.field_agreement_min,
        },
        "rationale": spec.rationale,
        "comparability_keys": list(spec.comparability_keys),
        "citation_patterns": list(spec.citation_patterns),
    }
    if spec.taxonomy is not None:
        body["taxonomy"] = {
            "name": spec.taxonomy.name,
            "version": spec.taxonomy.version,
            "digest": spec.taxonomy.digest,
            "dimensions": list(spec.taxonomy.dimensions),
        }
    return body


class _Reader:
    """Reads a JSON value into typed parts, collecting located shape issues."""

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def bad(self, path: str, reason: str) -> None:
        self.issues.append(ValidationIssue(path, reason))

    @staticmethod
    def _at(path: str, key: str) -> str:
        return f"{path}.{key}" if path else key

    def obj(self, value: object, path: str, allowed: set[str]) -> dict[str, object]:
        if not isinstance(value, dict):
            self.bad(path or "spec", "must be an object")
            return {}
        for key in value:
            if key not in allowed:
                self.bad(self._at(path, str(key)), "unknown key")
        return {str(k): v for k, v in value.items()}

    def text(self, data: dict[str, object], key: str, path: str, default: str | None) -> str:
        if key not in data:
            if default is None:
                self.bad(self._at(path, key), "is required")
                return ""
            return default
        value = data[key]
        if not isinstance(value, str):
            self.bad(self._at(path, key), "must be a string")
            return ""
        return value

    def integer(self, data: dict[str, object], key: str, path: str, default: int | None) -> int:
        if key not in data:
            if default is None:
                self.bad(self._at(path, key), "is required")
                return 0
            return default
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int):
            self.bad(self._at(path, key), "must be an integer")
            return 0
        return value

    def number(self, data: dict[str, object], key: str, path: str, default: float) -> float:
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.bad(self._at(path, key), "must be a number")
            return default
        return float(value)

    def boolean(self, data: dict[str, object], key: str, path: str, default: bool) -> bool:
        value = data.get(key, default)
        if not isinstance(value, bool):
            self.bad(self._at(path, key), "must be true or false")
            return default
        return value

    def strings(
        self, data: dict[str, object], key: str, path: str, *, required: bool = False
    ) -> tuple[str, ...]:
        if key not in data:
            if required:
                self.bad(self._at(path, key), "is required")
            return ()
        value = data[key]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.bad(self._at(path, key), "must be a list of strings")
            return ()
        return tuple(str(v) for v in value)


_KIND_KEYS = {"type", "unit_family", "units", "values", "patterns", "kinds", "by"} | {
    "value_kind",
    "normaliser",
}
_KIND_NAMES = "number, integer, enum, quote, citation, anchor, work_ref"


def _kind_from_json(r: _Reader, value: object, path: str) -> FieldKindSpec:
    data = r.obj(value, path, _KIND_KEYS)
    type_ = r.text(data, "type", path, None)
    if type_ == "number":
        family = r.text(data, "unit_family", path, "none")
        try:
            return NumberKind(UnitFamily(family), r.strings(data, "units", path))
        except ValueError:
            r.bad(f"{path}.unit_family", "must be score, count, other or none")
            return NumberKind(UnitFamily.NONE)
    if type_ == "integer":
        return IntegerKind()
    if type_ == "enum":
        return EnumKind(r.strings(data, "values", path, required=True))
    if type_ == "quote":
        return QuoteKind()
    if type_ == "citation":
        return CitationKind(r.strings(data, "patterns", path, required=True))
    if type_ == "anchor":
        names = r.strings(data, "kinds", path, required=True)
        try:
            return AnchorKindRef(tuple(AnchorKind(n) for n in names))
        except ValueError:
            r.bad(f"{path}.kinds", "must be anchor kinds")
            return AnchorKindRef(())
    if type_ == "work_ref":
        by = r.text(data, "by", path, None)
        if by not in ("entry", "title"):
            r.bad(f"{path}.by", "must be entry or title")
        return WorkRefKind("title" if by == "title" else "entry")
    if type_ == "unverified":
        value_kind = r.text(data, "value_kind", path, "text")
        normaliser = data.get("normaliser")
        if value_kind not in ("text", "integer", "bool"):
            r.bad(f"{path}.value_kind", "must be text, integer or bool")
        if normaliser is not None and not isinstance(normaliser, str):
            r.bad(f"{path}.normaliser", "must be a string or null")
            normaliser = None
        kind: Literal["text", "integer", "bool"] = (
            "integer" if value_kind == "integer" else "bool" if value_kind == "bool" else "text"
        )
        return Unverified(kind, normaliser)
    if type_:
        r.bad(f"{path}.type", f"must be one of {_KIND_NAMES}")
    return Unverified()


def _selector_from_json(r: _Reader, value: object) -> Selector:
    data = r.obj(
        value,
        "selector",
        {"population", "elements", "heading_patterns", "max_units", "max_works"},
    )
    population = r.text(data, "population", "selector", None)
    pop = Population.CORPUS
    if population:
        try:
            pop = Population(population)
        except ValueError:
            r.bad("selector.population", "must be one of " + ", ".join(p.value for p in Population))
    elements: list[AnchorKind] = []
    for name in r.strings(data, "elements", "selector"):
        try:
            elements.append(AnchorKind(name))
        except ValueError:
            r.bad("selector.elements", f"not an anchor kind: {name}")
    maximum: int | None = None
    if "max_units" in data and "max_works" in data:
        r.bad("selector", "give max_units or max_works, not both")
    key = "max_works" if "max_works" in data else "max_units"
    if data.get(key) is not None:
        maximum = r.integer(data, key, "selector", None)
    return Selector(pop, tuple(elements), r.strings(data, "heading_patterns", "selector"), maximum)


_TOP_KEYS = {
    "name", "version", "selector", "fields", "row_key_fields", "row_anchor_fields",
    "conditionals", "evidence", "procedure", "regime", "rationale", "comparability_keys",
    "citation_patterns", "taxonomy",
}  # fmt: skip


def _taxonomy_ref_from_json(r: _Reader, value: object) -> TaxonomyRef:
    data = r.obj(value, "taxonomy", {"name", "version", "digest", "dimensions"})
    return TaxonomyRef(
        name=r.text(data, "name", "taxonomy", None),
        version=r.integer(data, "version", "taxonomy", None),
        digest=r.text(data, "digest", "taxonomy", None),
        dimensions=r.strings(data, "dimensions", "taxonomy", required=True),
    )


def spec_from_json(value: object) -> MinerSpec:
    """The spec `value` describes. Raises `FactoryValidationError` (dotted fields) on any shape
    error: a missing or unknown key, a wrong type, an unknown kind or population."""
    r = _Reader()
    top = r.obj(value, "", _TOP_KEYS)
    name = r.text(top, "name", "", None)
    version = r.integer(top, "version", "", None)
    selector = _selector_from_json(r, top.get("selector"))
    fields: list[MinerField] = []
    raw_fields = top.get("fields")
    if not isinstance(raw_fields, list):
        r.bad("fields", "must be a list")
        raw_fields = []
    for i, raw in enumerate(raw_fields):
        path = f"fields[{i}]"
        data = r.obj(raw, path, {"name", "group", "kind", "required", "description", "compared"})
        fields.append(
            MinerField(
                name=r.text(data, "name", path, None),
                group=r.text(data, "group", path, None),
                kind=_kind_from_json(r, data.get("kind"), f"{path}.kind"),
                required=r.boolean(data, "required", path, False),
                description=r.text(data, "description", path, ""),
                compared=r.boolean(data, "compared", path, True),
            )
        )
    conditionals: list[Conditional] = []
    raw_cond = top.get("conditionals", [])
    if not isinstance(raw_cond, list):
        r.bad("conditionals", "must be a list")
        raw_cond = []
    for i, raw in enumerate(raw_cond):
        path = f"conditionals[{i}]"
        data = r.obj(raw, path, {"field", "when", "values", "rule"})
        rule = r.text(data, "rule", path, None)
        if rule not in ("required", "forbidden"):
            r.bad(f"{path}.rule", "must be required or forbidden")
        conditionals.append(
            Conditional(
                field=r.text(data, "field", path, None),
                when=r.text(data, "when", path, None),
                values=r.strings(data, "values", path, required=True),
                rule="forbidden" if rule == "forbidden" else "required",
            )
        )
    evidence_data = r.obj(
        top.get("evidence", {}),
        "evidence",
        {"min_quotes_per_record", "enum_needs_quote", "absence_values"},
    )
    evidence = EvidenceRule(
        r.integer(evidence_data, "min_quotes_per_record", "evidence", 1),
        r.boolean(evidence_data, "enum_needs_quote", "evidence", True),
        r.strings(evidence_data, "absence_values", "evidence"),
    )
    taxonomy = _taxonomy_ref_from_json(r, top["taxonomy"]) if "taxonomy" in top else None
    regime_data = r.obj(
        top.get("regime", {}),
        "regime",
        {"passes", "calibration_size", "recall_min", "field_agreement_min"},
    )
    passes = r.integer(regime_data, "passes", "regime", 2)
    if passes not in (1, 2):
        r.bad("regime.passes", "must be 1 or 2")
    regime = MinerRegime(
        1 if passes == 1 else 2,
        r.integer(regime_data, "calibration_size", "regime", 10),
        r.number(regime_data, "recall_min", "regime", 0.8),
        r.number(regime_data, "field_agreement_min", "regime", 0.9),
    )
    spec = MinerSpec(
        name=name,
        version=version,
        selector=selector,
        fields=tuple(fields),
        row_key_fields=r.strings(top, "row_key_fields", ""),
        row_anchor_fields=r.strings(top, "row_anchor_fields", ""),
        conditionals=tuple(conditionals),
        evidence=evidence,
        procedure=r.text(top, "procedure", "", None),
        regime=regime,
        rationale=r.text(top, "rationale", "", ""),
        comparability_keys=r.strings(top, "comparability_keys", ""),
        citation_patterns=r.strings(top, "citation_patterns", ""),
        taxonomy=taxonomy,
    )
    if r.issues:
        raise FactoryValidationError(r.issues)
    return spec
