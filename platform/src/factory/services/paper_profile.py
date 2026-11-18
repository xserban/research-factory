"""Compact paper profiles: what every listed miner found in a work, in one short text (plan chat,
T5, section 4.2).

In the papers chat Claude reads one profile per paper in scope to decide which papers bear on a
question, before reading the chosen ones in full. The raw mined output is far larger; a profile
keeps the field values only.

Invariants:
- Read-only: nothing is written. The index is synced before reading.
- Miners included are those currently listed in the protocol's `miners` section, one entry per
  listed `(name, version)`; rows are read from the miner's scope (`MinerScope(name)`).
- A miner's rows for a work are its final rows (`final_rows_restricted`) with status `final`.
  Final rows leave out every row until pass B of the miner has opened, so a work with no final
  row falls back to its live (not superseded) pass A rows, with status `pass-a-only`. A work with
  neither is in `missing_miners`. Rows of the one status are never mixed for a work and miner.
- Quote fields are omitted, except for miners in `QUOTED_MINERS`, whose quotes are kept cut to
  `QUOTE_CHARS` characters. Other values are cut to `VALUE_CHARS`.
- A category of a miner derived from a taxonomy is shown by its category name, not its id.
- Unknown work ids are refused on field `work_ids` before anything is read; the order of the
  profiles is that of the work ids given. `render_profile` is deterministic: miners by name and
  version, rows by row key, fields in the miner spec's order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from factory.errors import FactoryValidationError, ValidationIssue
from factory.mining.spec import EnumKind, MinerSpec, QuoteKind
from factory.mining.taxonomy import TaxonomySpec, full_id
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import live_rows, scope_ledger
from factory.services.extraction_agreement import final_rows_restricted
from factory.services.mining import registered_miner
from factory.services.protocol import current_protocol
from factory.services.search import get_work
from factory.services.taxonomies import registered_taxonomy

__all__ = [
    "PROFILE_CHARS_PER_TOKEN",
    "QUOTED_MINERS",
    "QUOTE_CHARS",
    "VALUE_CHARS",
    "PaperProfile",
    "ProfileRow",
    "category_names",
    "paper_profiles",
    "profile_size",
    "render_profile",
]

QUOTED_MINERS = frozenset({"m-summary", "m-claims"})
"""Miners whose quote fields a profile keeps."""

QUOTE_CHARS = 300
VALUE_CHARS = 120
PROFILE_CHARS_PER_TOKEN = 4
"""Characters per token for `profile_size`. A rough estimate, not a tokeniser count."""

_ELLIPSIS = "…"


@dataclass(frozen=True)
class ProfileRow:
    """One row of a miner for a work: `status` is `final` or `pass-a-only`; `fields` are
    `(name, short value)` pairs in the miner spec's order."""

    miner: str
    version: int
    status: str
    row_key: str
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PaperProfile:
    """Everything the listed miners found in one work. `missing_miners` are the listed
    `(name, version)` with no row at all for the work."""

    work_id: str
    title: str
    year: str
    rows: tuple[ProfileRow, ...]
    missing_miners: tuple[tuple[str, int], ...]


def profile_size(text: str) -> int:
    """The estimated tokens of `text` (characters over `PROFILE_CHARS_PER_TOKEN`, rounded up)."""
    return -(-len(text) // PROFILE_CHARS_PER_TOKEN)


def category_names(taxonomy: TaxonomySpec) -> dict[str, str]:
    """`dimension/category` id to category name for every category of `taxonomy`. Pure.
    Residual values and layer categories have no name here and are shown by their id."""
    return {
        full_id(d.id, c.id): c.name for d in taxonomy.dimensions for c in d.categories if c.name
    }


def _cut(value: str, limit: int) -> str:
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + _ELLIPSIS


def _short(
    spec: MinerSpec, names: Mapping[str, str], field: str, value: str | int | float | bool
) -> str | None:
    """The shown value of a stored field, or None when the field is not shown."""
    definition = spec.field_named(field)
    if definition is None:
        return _cut(str(value), VALUE_CHARS)
    text = "true" if value is True else "false" if value is False else str(value)
    if isinstance(definition.kind, QuoteKind):
        return _cut(text, QUOTE_CHARS) if spec.name in QUOTED_MINERS else None
    if isinstance(definition.kind, EnumKind) and names:
        text = names.get(text, text)
    return _cut(text, VALUE_CHARS)


def _ordered(
    spec: MinerSpec, stored: Mapping[str, tuple[str | int | float | bool, str | None]]
) -> list[str]:
    declared = [f.name for f in spec.fields if f.name in stored]
    return declared + sorted(set(stored) - set(declared))


def _row(
    spec: MinerSpec,
    names: Mapping[str, str],
    status: str,
    row_key: str,
    stored: Mapping[str, tuple[str | int | float | bool, str | None]],
) -> ProfileRow:
    fields: list[tuple[str, str]] = []
    for field in _ordered(spec, stored):
        value, unit = stored[field]
        shown = _short(spec, names, field, value)
        if shown:
            fields.append((field, f"{shown} {unit}" if unit else shown))
    return ProfileRow(spec.name, spec.version, status, row_key, tuple(fields))


def _names_of(project: Project, spec: MinerSpec) -> dict[str, str]:
    if spec.taxonomy is None:
        return {}
    taxonomy = registered_taxonomy(project, spec.taxonomy.name, spec.taxonomy.version)
    return {} if taxonomy is None else category_names(taxonomy)


def paper_profiles(project: Project, work_ids: Sequence[str]) -> list[PaperProfile]:
    """The profile of each work in `work_ids`, in the order given (duplicates once). Refused on
    field `work_ids`, with nothing read further, when an id is no work of the project. Read-only;
    a project without a protocol or without listed miners gives profiles without rows."""
    project.index.sync()
    unique = list(dict.fromkeys(work_ids))
    works = {w: get_work(project, w) for w in unique}
    unknown = [w for w, work in works.items() if work is None]
    if unknown:
        raise FactoryValidationError(
            [ValidationIssue("work_ids", f"unknown work id: {', '.join(unknown)}")]
        )
    protocol = current_protocol(project)
    listed = sorted(
        {(u.name, u.version) for u in (protocol.spec.miners or ())} if protocol else set()
    )
    rows: dict[str, list[ProfileRow]] = {w: [] for w in unique}
    seen: dict[str, set[tuple[str, int]]] = {w: set() for w in unique}
    for name, version in listed:
        spec = registered_miner(project, name, version)
        if spec is None:
            continue
        names = _names_of(project, spec)
        scope = MinerScope(name)
        finals: dict[str, list[ProfileRow]] = {}
        for final in final_rows_restricted(
            project, unique, scope=scope, ledger=scope_ledger(project, scope)
        ):
            stored = {k: (f.value, f.unit) for k, f in final.fields.items()}
            finals.setdefault(final.work_id, []).append(
                _row(spec, names, "final", final.row_key, stored)
            )
        for work_id in unique:
            found = finals.get(work_id)
            if not found:
                found = [
                    _row(
                        spec,
                        names,
                        "pass-a-only",
                        live.row_key,
                        {k: (f.value, f.unit) for k, f in live.fields.items()},
                    )
                    for live in live_rows(project, PassLabel.A, work_id=work_id, scope=scope)
                ]
            if found:
                rows[work_id].extend(found)
                seen[work_id].add((name, version))
    profiles: list[PaperProfile] = []
    for work_id in unique:
        work = works[work_id]
        assert work is not None
        ordered = sorted(rows[work_id], key=lambda r: (r.miner, r.version, r.row_key))
        profiles.append(
            PaperProfile(
                work_id,
                work.title,
                str(work.dates.year or ""),
                tuple(ordered),
                tuple(m for m in listed if m not in seen[work_id]),
            )
        )
    return profiles


def render_profile(profile: PaperProfile) -> str:
    """The profile as plain text: a header line `work_id · year · title`, then one line per miner
    (and status) `miner [status]: field=value; field=value | next row`, ordered by miner name,
    then version; a line `missing: ...` lists the listed miners without rows. Pure."""
    lines = [f"{profile.work_id} · {profile.year or 'n.d.'} · {profile.title}"]
    groups: dict[tuple[str, int, str], list[ProfileRow]] = {}
    for row in sorted(profile.rows, key=lambda r: (r.miner, r.version, r.row_key)):
        groups.setdefault((row.miner, row.version, row.status), []).append(row)
    for (miner, _version, status), members in sorted(groups.items()):
        body = " | ".join("; ".join(f"{k}={v}" for k, v in m.fields) for m in members)
        lines.append(f"{miner} [{status}]: {body}")
    if profile.missing_miners:
        lines.append("missing: " + ", ".join(n for n, _ in profile.missing_miners))
    return "\n".join(lines)
