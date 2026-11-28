"""The facets of a project's hub: which enum fields of its own miners the Corpus and Explore pages
offer as filters, in what order and under what name (HS-60 to HS-65).

Invariants:
- A facet is one enum field of a protocol-listed miner. The list is, in this order: the
  researcher's setting (the latest valid human `hub.facets_set`), else the default rule below.
  `Month` (key `year`, role `meta`) is always the last facet and is never part of a setting.
- Default rule. (1) Legacy preset: when the protocol lists at least one of the miners of the first
  pilot's roles (`m-classification`, `m-mapping`), or lists no miner at all, the facets are that
  pilot's, so its pages are unchanged: its keys, labels and order, restricted to the listed miners
  (all of them when none is listed, as before this module existed); a legacy facet is not checked
  for being an enum field. (2) Otherwise the enum
  fields of the protocol-listed miners, in protocol order then field order, at most
  `DEFAULT_PER_MINER` per miner and `DEFAULT_MAX` in all; the miners that supply the layer (a
  layer-scheme miner or one flagged `paper_layers`) are left out because Layer is always a facet of
  its own. A label is the field name made readable, with the miner in brackets when two facets
  would read alike. Nothing is judged: the rule reads the registered specs only.
- Labels and descriptions come from the registered spec (a field's `description`; for a miner
  derived from a taxonomy, the category names), never from code; the code fallback is the
  readable form of an id. A pick that no longer resolves (unregistered, unlisted, not an enum
  field) is skipped on read; `set_facets` refuses it at the boundary.
- `set_facets` is the researcher's act: a non-human actor is refused, and every refusal writes
  nothing. The setting is read from the event log, memoised per project directory and last event.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_typed
from factory.mining.spec import EnumKind, MinerSpec
from factory.mining.taxonomy import full_id
from factory.model.hub_facets import MAX_FACETS, FacetPick, HubFacetsSet
from factory.services.context import Project
from factory.services.mining import registered_miner
from factory.services.protocol import current_protocol
from factory.services.taxonomies import registered_taxonomy

__all__ = [
    "DEFAULT_MAX",
    "DEFAULT_PER_MINER",
    "LEGACY_DIMS",
    "LEGACY_ROLE_MINERS",
    "MONTH",
    "SLOTS",
    "Facet",
    "default_picks",
    "facet_setting",
    "facets_of",
    "facets_payload",
    "set_facets",
    "slot_aliases",
]

EVENT_TYPE: Final = "hub.facets_set"
DEFAULT_PER_MINER: Final = 6
DEFAULT_MAX: Final = 12
LEGACY_ROLE_MINERS: Final[dict[str, str]] = {
    "cls": "m-classification",
    "map": "m-mapping",
    "sum": "m-summary",
    "desc": "m-descriptors",
    "stages": "m-stages",
    "design": "m-design-approach",
}
LEGACY_DIMS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("technique", "Technique", "cls", "technique_primary"),
    ("field", "Field of science", "cls", "field_primary"),
    ("data", "Data", "cls", "data_primary"),
    ("architecture", "Architecture", "cls", "architecture_primary"),
    ("evaluation", "Evaluation", "cls", "evaluation_primary"),
    ("human", "Human position", "map", "human_position"),
    ("process", "Process shape", "map", "process_shape"),
    ("span", "Automated span", "map", "automated_span"),
    ("assess", "Idea assessment", "map", "idea_assessment_method"),
)
"""The first pilot's facets as (key, label, role, field), in its order, before `MONTH`."""
MONTH: Final = ("year", "Month", "meta", "month")
SLOTS: Final = ("technique", "architecture", "span", "human")
"""The four fields the Explore DNA and the lenses read, by their pilot keys (see `slot_aliases`)."""
_LEGACY: Final = {
    (LEGACY_ROLE_MINERS[role], f): (key, role) for key, _label, role, f in LEGACY_DIMS
}
"""(miner, field) -> (key, role) of the first pilot's facets."""


@dataclass(frozen=True)
class Facet:
    """One facet: `key` (in the address and the payload), the miner and field it reads, its `label`
    (the researcher's, else readable), the field's `description` and `values` (value id -> label,
    only where the spec names one). `role` is the legacy role name (`cls`, `map`) or the miner
    name; `dim` is the profile tuple `(key, label, role, field)`."""

    key: str
    miner: str
    field: str
    label: str
    role: str
    description: str = ""
    values: dict[str, str] = dataclasses.field(default_factory=dict)
    renamed: bool = False
    """True when the label is the researcher's (a setting's `label`)."""

    @property
    def dim(self) -> tuple[str, str, str, str]:
        return (self.key, self.label, self.role, self.field)


def readable(name: str) -> str:
    """An id made readable: separators to spaces, first letter capital."""
    words = name.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def _refuse(field_: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, message)])


def _listed(project: Project) -> list[tuple[str, MinerSpec]]:
    """`(name, spec)` of every protocol-listed miner with a registered spec, in protocol order."""
    protocol = current_protocol(project)
    out: list[tuple[str, MinerSpec]] = []
    for use in (protocol.spec.miners or ()) if protocol is not None else ():
        spec = registered_miner(project, use.name, use.version)
        if spec is not None:
            out.append((use.name, spec))
    return out


def _paper_layer_miners(project: Project) -> set[str]:
    from factory.services.work_layers import _layer_sources

    return {name for name, _d, _v, _f in _layer_sources(project)}


def _enum_field(spec: MinerSpec, name: str) -> EnumKind | None:
    for f in spec.fields:
        if f.name == name and isinstance(f.kind, EnumKind):
            return f.kind
    return None


def _value_labels(project: Project, spec: MinerSpec, name: str) -> dict[str, str]:
    """Category names of a derived miner's `category` field (full id -> name); empty otherwise."""
    if spec.taxonomy is None or name != "category":
        return {}
    taxonomy = registered_taxonomy(project, spec.taxonomy.name, spec.taxonomy.version)
    if taxonomy is None:
        return {}
    return {
        full_id(d.id, c.id): c.name
        for d in taxonomy.dimensions
        if d.id in spec.taxonomy.dimensions
        for c in d.categories
        if c.name
    }


def _facet(
    project: Project, miner: str, spec: MinerSpec, pick: FacetPick, *, set_by_researcher: bool
) -> Facet | None:
    if _enum_field(spec, pick.field) is None:
        return None
    described = next(f.description for f in spec.fields if f.name == pick.field)
    key, role = _LEGACY.get((miner, pick.field), (f"{miner}.{pick.field}", miner))
    return Facet(
        key=key,
        miner=miner,
        field=pick.field,
        label=pick.label or readable(pick.field),
        role=role,
        description=described,
        values=_value_labels(project, spec, pick.field),
        renamed=set_by_researcher and pick.label is not None,
    )


def _legacy_picks(listed: dict[str, MinerSpec]) -> tuple[FacetPick, ...]:
    """The first pilot's picks when the legacy preset applies (see the module invariants), else
    empty."""
    if listed and not any(m in listed for m in LEGACY_ROLE_MINERS.values()):
        return ()
    return tuple(
        FacetPick(miner=LEGACY_ROLE_MINERS[role], field=f, label=label)
        for _key, label, role, f in LEGACY_DIMS
        if not listed or LEGACY_ROLE_MINERS[role] in listed
    )


def _legacy_facet(project: Project, spec: MinerSpec | None, pick: FacetPick) -> Facet:
    """A facet of the legacy preset: built even when the spec is not registered or the field is
    not an enum, so the first pilot's pages stay as they were."""
    key, role = _LEGACY[(pick.miner, pick.field)]
    described = ""
    if spec is not None:
        described = next((f.description for f in spec.fields if f.name == pick.field), "")
    return Facet(
        key=key,
        miner=pick.miner,
        field=pick.field,
        label=pick.label or readable(pick.field),
        role=role,
        description=described,
        values={} if spec is None else _value_labels(project, spec, pick.field),
    )


def default_picks(project: Project) -> tuple[FacetPick, ...]:
    """The default facets of `project` as picks (see the module invariants)."""
    listed = _listed(project)
    by_name = dict(listed)
    legacy = _legacy_picks(by_name)
    if legacy:
        return legacy
    skip = _paper_layer_miners(project)
    picks: list[FacetPick] = []
    for name, spec in listed:
        if name in skip:
            continue
        enums = [f.name for f in spec.fields if isinstance(f.kind, EnumKind)]
        picks.extend(FacetPick(miner=name, field=f) for f in enums[:DEFAULT_PER_MINER])
    picks = picks[:DEFAULT_MAX]
    names = [readable(p.field) for p in picks]
    return tuple(
        FacetPick(
            miner=p.miner,
            field=p.field,
            label=f"{n} ({p.miner})" if names.count(n) > 1 else n,
        )
        for p, n in zip(picks, names, strict=True)
    )


_SETTING_CACHE: dict[str, tuple[str | None, tuple[FacetPick, ...] | None]] = {}
_CACHE_MAX = 8


def facet_setting(project: Project) -> tuple[FacetPick, ...] | None:
    """The picks of the latest valid human `hub.facets_set`, or None when none was recorded. An
    event of a non-human actor or with an invalid payload is skipped, as at the boundary."""
    project.index.sync()
    key = str(project.paths.dir)
    head = project.index.last_event_id()
    hit = _SETTING_CACHE.get(key)
    if hit is not None and hit[0] == head:
        return hit[1]
    found: tuple[FacetPick, ...] | None = None
    for event in reversed(read_typed(project.paths.events_dir, project.catalog, [EVENT_TYPE])):
        if event.actor.kind != "human":
            continue
        try:
            found = HubFacetsSet.model_validate(event.payload).facets
        except ValidationError:
            continue
        break
    _SETTING_CACHE.pop(key, None)
    while len(_SETTING_CACHE) >= _CACHE_MAX:
        _SETTING_CACHE.pop(next(iter(_SETTING_CACHE)))
    _SETTING_CACHE[key] = (head, found)
    return found


def facets_of(project: Project) -> tuple[Facet, ...]:
    """The project's facets in order, without Month: the setting, else the default. A pick whose
    miner is not listed or whose field is not an enum field of it is skipped; a repeated
    (miner, field) keeps its first place."""
    setting = facet_setting(project)
    picks = setting
    by_name = dict(_listed(project))
    if picks is None:
        picks = default_picks(project)
        if _legacy_picks(by_name):
            return tuple(_legacy_facet(project, by_name.get(p.miner), p) for p in picks)
    out: list[Facet] = []
    seen: set[tuple[str, str]] = set()
    for pick in picks:
        spec = by_name.get(pick.miner)
        if spec is None or (pick.miner, pick.field) in seen:
            continue
        found = _facet(project, pick.miner, spec, pick, set_by_researcher=setting is not None)
        if found is not None:
            seen.add((pick.miner, pick.field))
            out.append(found)
    return tuple(out)


def slot_aliases(keys: list[str]) -> dict[str, str]:
    """For a project with none of the four `SLOTS` keys, slot name -> the key of the facet at the
    same position (so the DNA and the lenses read the project's own first facets); empty for a
    project that has any slot key (the first pilot) and for the slots with no facet."""
    if any(s in keys for s in SLOTS):
        return {}
    return dict(zip(SLOTS, keys, strict=False))


def facets_payload(project: Project) -> list[dict[str, object]]:
    """The facets as JSON for the hub payloads: key, label, description, miner, field and the
    value labels the spec names. Month is last."""
    out: list[dict[str, object]] = [
        {
            "key": f.key,
            "label": f.label,
            "description": f.description,
            "miner": f.miner,
            "field": f.field,
            "values": dict(sorted(f.values.items())),
            "renamed": f.renamed,
        }
        for f in facets_of(project)
    ]
    out.append(
        {
            "key": MONTH[0],
            "label": MONTH[1],
            "description": "",
            "miner": "",
            "field": MONTH[3],
            "values": {},
            "renamed": False,
        }
    )
    return out


def set_facets(project: Project, actor: Actor, picks: list[FacetPick]) -> str:
    """Record the researcher's facet list; returns the event id.

    Refused, with nothing written: a non-human actor (`actor`); an empty or over-long list, or a
    blank label (`facets`); a miner that is not protocol-listed and registered (`facets`); a field
    that is not an enum field of that miner (`facets`); the same (miner, field) twice (`facets`)."""
    if actor.kind != "human":
        raise _refuse("actor", "only the researcher sets the hub facets")
    if not 1 <= len(picks) <= MAX_FACETS:
        raise _refuse("facets", f"give between 1 and {MAX_FACETS} facets")
    with project.index.exclusive():
        project.index.sync()
        by_name = dict(_listed(project))
        issues: list[ValidationIssue] = []
        seen: set[tuple[str, str]] = set()
        for i, pick in enumerate(picks):
            where = f"facets[{i}]"
            spec = by_name.get(pick.miner)
            if spec is None:
                issues.append(
                    ValidationIssue(where, f"{pick.miner} is not a listed, registered miner")
                )
            elif _enum_field(spec, pick.field) is None:
                issues.append(
                    ValidationIssue(where, f"{pick.miner} has no enum field {pick.field}")
                )
            if (pick.miner, pick.field) in seen:
                issues.append(ValidationIssue(where, f"{pick.miner}.{pick.field} is given twice"))
            seen.add((pick.miner, pick.field))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(EVENT_TYPE, HubFacetsSet(facets=tuple(picks)), actor)
        project.record([event])
    return event.id
