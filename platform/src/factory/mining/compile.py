"""Compile a miner specification to a pack, derive one from a pack, and digest it (M-C ruling 2).

The built-in packs are miners: `compile_miner(miner_of_pack(p, ...)) == p` (`BUILT_IN_MINERS`).
Pure; no services are imported, so the round trip is testable without a project.

Invariants:
- A field kind compiles to exactly one `FieldDef` (the table in `_field_def`); `miner_of_pack` is
  its inverse on the field shapes the built-in packs use and raises `ValueError` on any other, so a
  new pack shape cannot silently lose a property.
- `miner_digest` hashes the spec without prose (`rationale`, each field's `description`); the
  procedure skill is hashed by name only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from types import MappingProxyType

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.mining.spec import (
    AnchorKindRef,
    CitationKind,
    EnumKind,
    EvidenceRule,
    FieldKindSpec,
    IntegerKind,
    MinerField,
    MinerRegime,
    MinerSpec,
    NumberKind,
    Population,
    QuoteKind,
    Selector,
    Unverified,
    WorkRefKind,
    spec_to_json,
)
from factory.model.protocol import strip_prose
from factory.packs import CONTRIBUTION_V1, ML_BENCHMARK_V1
from factory.packs.model import Check, FieldDef, FieldKind, Pack, UnitFamily

WORK_REF_FIELDS: Mapping[tuple[str, str], str] = MappingProxyType(
    {("contribution", "cited_entry"): "entry"}
)
"""Built-in fields that name a reference-list entry: `(pack, field)` to the kind of reference."""

_UNVERIFIED_KINDS: Mapping[FieldKind, str] = MappingProxyType(
    {FieldKind.TEXT: "text", FieldKind.INTEGER: "integer", FieldKind.BOOL: "bool"}
)


def _field_def(f: MinerField) -> FieldDef:
    kind = f.kind
    none = UnitFamily.NONE
    if isinstance(kind, NumberKind):
        return FieldDef(
            f.name, f.group, FieldKind.NUMBER, kind.unit_family, Check.NUMBER, kind.units
        )
    if isinstance(kind, IntegerKind):
        return FieldDef(f.name, f.group, FieldKind.INTEGER, none, Check.NUMBER)
    if isinstance(kind, EnumKind):
        return FieldDef(f.name, f.group, FieldKind.TEXT, none, Check.NONE, allowed=kind.values)
    if isinstance(kind, QuoteKind | CitationKind):
        return FieldDef(f.name, f.group, FieldKind.TEXT, none, Check.TEXT_IN_QUOTE)
    if isinstance(kind, AnchorKindRef):
        return FieldDef(f.name, f.group, FieldKind.TEXT, none, Check.NONE, unitless=True)
    if isinstance(kind, WorkRefKind):
        if kind.by == "entry":
            return FieldDef(f.name, f.group, FieldKind.INTEGER, none, Check.NONE, unitless=True)
        return FieldDef(f.name, f.group, FieldKind.TEXT, none, Check.TEXT_IN_QUOTE)
    return FieldDef(
        f.name, f.group, FieldKind(kind.kind), none, Check.NONE, normaliser=kind.normaliser
    )


def keyed_on_work(spec: MinerSpec) -> bool:
    """Whether `spec` keys each row on its work: a derived miner (taxonomy reference) that
    declares no row key fields (one single dimension, `derive_miner`; IDEA-69 (1))."""
    return spec.taxonomy is not None and not spec.row_key_fields


def compile_miner(spec: MinerSpec) -> Pack:
    """The pack of `spec`. Required fields are those marked; `compared_fields` is None when every
    field is compared, else the compared fields in declaration order (a quote field of group
    `evidence` is never compared); citation patterns are the spec's own then those of its
    `CitationKind` fields, without repeats."""
    compared = tuple(
        f.name
        for f in spec.fields
        if f.compared and not (isinstance(f.kind, QuoteKind) and f.group == "evidence")
    )
    patterns: list[str] = list(spec.citation_patterns)
    for f in spec.fields:
        if isinstance(f.kind, CitationKind):
            patterns.extend(f.kind.patterns)
    return Pack(
        name=spec.name,
        version=spec.version,
        fields=tuple(_field_def(f) for f in spec.fields),
        required=tuple(f.name for f in spec.fields if f.required),
        default_comparability_keys=spec.comparability_keys,
        citation_patterns=tuple(dict.fromkeys(patterns)),
        conditionals=spec.conditionals,
        row_key_fields=spec.row_key_fields,
        row_anchor_fields=spec.row_anchor_fields,
        compared_fields=None if len(compared) == len(spec.fields) else compared,
        row_per_work=keyed_on_work(spec),
        report=spec.report,
    )


def _kind_of_def(pack: Pack, d: FieldDef) -> MinerField:
    """The miner field of a pack field; ValueError when its shape has no miner kind."""
    required = d.name in pack.required
    compared = pack.compared_fields is None or d.name in pack.compared_fields
    none = UnitFamily.NONE
    plain = d.normaliser is None and not d.allowed
    built: FieldKindSpec
    if d.check is Check.NUMBER and d.kind is FieldKind.NUMBER and plain:
        built = NumberKind(d.unit_family, d.units)
    elif (
        d.check is Check.NUMBER
        and d.kind is FieldKind.INTEGER
        and plain
        and d.unit_family is none
        and not d.units
    ):
        built = IntegerKind()
    elif (
        d.check is Check.TEXT_IN_QUOTE
        and d.kind is FieldKind.TEXT
        and plain
        and d.unit_family is none
        and not d.units
    ):
        built = QuoteKind()
    elif (
        d.check is Check.NONE
        and d.kind is FieldKind.TEXT
        and d.allowed
        and d.normaliser is None
        and d.unit_family is none
        and not d.units
    ):
        built = EnumKind(d.allowed)
    elif (
        d.check is Check.NONE
        and d.kind is FieldKind.INTEGER
        and plain
        and (pack.name, d.name) in WORK_REF_FIELDS
    ):
        built = WorkRefKind("entry")
    elif (
        d.check is Check.NONE
        and d.kind in _UNVERIFIED_KINDS
        and not d.allowed
        and d.unit_family is none
        and not d.units
    ):
        value_kind = _UNVERIFIED_KINDS[d.kind]
        built = Unverified(
            "integer" if value_kind == "integer" else "bool" if value_kind == "bool" else "text",
            d.normaliser,
        )
    else:
        raise ValueError(f"field {d.name} of pack {pack.name} has no miner kind")
    return MinerField(d.name, d.group, built, required, compared=compared)


def miner_of_pack(
    pack: Pack,
    selector: Selector,
    regime: MinerRegime,
    *,
    procedure: str = "rf-extract",
) -> MinerSpec:
    """The miner a built-in pack is. Its evidence rule asks for nothing (a built-in's records are
    verified field by field and by its own dual extraction and audit)."""
    return MinerSpec(
        name=pack.name,
        version=pack.version,
        selector=selector,
        fields=tuple(_kind_of_def(pack, d) for d in pack.fields),
        row_key_fields=pack.row_key_fields,
        row_anchor_fields=pack.row_anchor_fields,
        conditionals=pack.conditionals,
        evidence=EvidenceRule(0, False),
        procedure=procedure,
        regime=regime,
        comparability_keys=pack.default_comparability_keys,
        citation_patterns=pack.citation_patterns,
        report=pack.report,
    )


def _without_prose(spec: MinerSpec) -> JsonValue:
    body = spec_to_json(spec)
    fields = body["fields"]
    assert isinstance(fields, list)
    for entry in fields:
        assert isinstance(entry, dict)
        entry.pop("description", None)
    return strip_prose(body)


def miner_digest(spec: MinerSpec) -> str:
    """The first 16 hex digits of the SHA-256 of the canonical JSON of `spec` without prose."""
    return hashlib.sha256(canonical_json(_without_prose(spec))).hexdigest()[:16]


def unverified_fields(spec: MinerSpec) -> list[str]:
    """The names of the fields with no check (built-in packs only), in declaration order."""
    return [f.name for f in spec.fields if isinstance(f.kind, Unverified)]


_REGIME = MinerRegime(2, 10, 0.8, 0.9)

BUILT_IN_MINERS: Mapping[str, MinerSpec] = MappingProxyType(
    {
        f"{ML_BENCHMARK_V1.name}@{ML_BENCHMARK_V1.version}": miner_of_pack(
            ML_BENCHMARK_V1, Selector(Population.INCLUDED_FT), _REGIME
        ),
        f"{CONTRIBUTION_V1.name}@{CONTRIBUTION_V1.version}": miner_of_pack(
            CONTRIBUTION_V1,
            Selector(Population.INCLUDED_FINAL),
            _REGIME,
            procedure="rf-contributions",
        ),
    }
)
"""The built-in packs as miners, keyed `<name>@<version>`."""
